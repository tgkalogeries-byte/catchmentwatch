from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from math import sqrt
import re
from typing import Any

from .sources import fetch_items

HOLDOUT_MIN_CORRELATION = 0.20
HOLDOUT_MIN_LIFT_OVER_CONCURRENT = 0.10


def _station(reference: str, parameter: str) -> dict[str, Any]:
    rows = fetch_items("id/stations", {"stationReference": reference, "parameter": parameter, "_view": "full"}, limit=1)
    if not rows:
        raise ValueError(f"No {parameter} station found for {reference}")
    return rows[0]


def _measure(station: dict[str, Any], parameter: str) -> dict[str, Any]:
    measures = [m for m in station.get("measures", []) if m.get("parameter") == parameter]
    if parameter == "level":
        measures.sort(key=lambda m: (str(m.get("qualifier", "")).lower() != "stage", m.get("unitName") == "---"))
    else:
        measures.sort(key=lambda m: m.get("unitName") == "---")
    if not measures:
        raise ValueError(f"No usable {parameter} measure for station {station.get('stationReference')}")
    return measures[0]


def _history(measure_uri: str, since: str) -> list[dict[str, Any]]:
    measure_id = measure_uri.rstrip("/").split("/")[-1]
    rows = fetch_items(f"id/measures/{measure_id}/readings", {"since": since}, limit=3000)
    return rows


def _hourly(rows: list[dict[str, Any]], kind: str) -> dict[datetime, float]:
    buckets: dict[datetime, list[tuple[datetime, float]]] = defaultdict(list)
    for row in rows:
        try:
            timestamp = datetime.fromisoformat(str(row["dateTime"]).replace("Z", "+00:00")).astimezone(timezone.utc)
            value = float(row["value"])
        except (KeyError, TypeError, ValueError):
            continue
        hour = timestamp.replace(minute=0, second=0, microsecond=0)
        buckets[hour].append((timestamp, value))
    if kind == "rainfall":
        return {hour: sum(value for _, value in values) for hour, values in buckets.items()}
    return {hour: max(values, key=lambda item: item[0])[1] for hour, values in buckets.items()}


def _correlation(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 2:
        return None
    mean_x, mean_y = sum(xs) / len(xs), sum(ys) / len(ys)
    dx, dy = [x - mean_x for x in xs], [y - mean_y for y in ys]
    denominator = sqrt(sum(x * x for x in dx) * sum(y * y for y in dy))
    if denominator == 0:
        return None
    return sum(x * y for x, y in zip(dx, dy)) / denominator


def _lag_correlation(hours: list[datetime], levels: dict[datetime, float], rainfall: dict[datetime, float], lag: int, end_exclusive: datetime | None = None) -> dict[str, Any]:
    xs: list[float] = []
    ys: list[float] = []
    for hour in hours:
        target = hour + timedelta(hours=lag)
        previous = target - timedelta(hours=1)
        if end_exclusive is not None and target >= end_exclusive:
            continue
        if hour in rainfall and target in levels and previous in levels:
            xs.append(rainfall[hour])
            ys.append(levels[target] - levels[previous])
    return {"lag_hours": lag, "correlation": _correlation(xs, ys), "pairs": len(xs)}


def analyze_pair(level_reference: str, rain_reference: str, days: int = 30) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z0-9]{1,16}", level_reference) or not re.fullmatch(r"[A-Za-z0-9]{1,16}", rain_reference):
        raise ValueError("Invalid station reference")
    level_station = _station(level_reference, "level")
    rain_station = _station(rain_reference, "rainfall")
    level_measure = _measure(level_station, "level")
    rain_measure = _measure(rain_station, "rainfall")
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds").replace("+00:00", "Z")
    level_rows = _history(level_measure["@id"], since)
    rain_rows = _history(rain_measure["@id"], since)
    levels = _hourly(level_rows, "level")
    rainfall = _hourly(rain_rows, "rainfall")
    common = sorted(set(levels) & set(rainfall))
    pairs: list[dict[str, Any]] = []
    wet_hours = sum(rainfall.get(hour, 0) > 0 for hour in common)
    wet_days = len({hour.date() for hour in common if rainfall.get(hour, 0) > 0})
    split = max(1, int(len(common) * 0.7))
    train_hours, holdout_hours = common[:split], common[split:]
    split_time = common[split] if split < len(common) else None
    correlations = [_lag_correlation(train_hours, levels, rainfall, lag, split_time) for lag in range(13)]
    eligible = [item for item in correlations[1:] if item["correlation"] is not None and item["correlation"] > 0 and item["pairs"] >= 48]
    for hour in common:
        pairs.append({
            "time": hour.isoformat(),
            "rain_mm": round(rainfall[hour], 3),
            "level": round(levels[hour], 4),
        })
    if len(common) < 48:
        result = {"status": "insufficient_data", "message": "Fewer than 48 overlapping hourly observations were returned.", "best_lag": None}
    elif wet_hours < 12 or wet_days < 3:
        result = {"status": "insufficient_variation", "message": "Rainfall is concentrated in too few hours or days for a lag relationship to be reported.", "best_lag": None}
    elif not eligible:
        result = {"status": "no_positive_association", "message": "No future lag from 1 to 12 hours had a positive training correlation that met the minimum sample rule.", "best_lag": None}
    else:
        candidate = max(eligible, key=lambda item: item["correlation"])
        holdout = _lag_correlation(holdout_hours, levels, rainfall, candidate["lag_hours"])
        concurrent = _lag_correlation(holdout_hours, levels, rainfall, 0)
        best = {
            "lag_hours": candidate["lag_hours"],
            "training_correlation": candidate["correlation"],
            "training_pairs": candidate["pairs"],
            "holdout_correlation": holdout["correlation"],
            "holdout_pairs": holdout["pairs"],
            "holdout_concurrent_correlation": concurrent["correlation"],
        }
        if holdout["pairs"] < 24 or holdout["correlation"] is None:
            result = {"status": "insufficient_holdout", "message": "The later holdout period has too few paired hours to evaluate the selected lag.", "best_lag": best}
        elif holdout["correlation"] < HOLDOUT_MIN_CORRELATION or concurrent["correlation"] is None or holdout["correlation"] - concurrent["correlation"] < HOLDOUT_MIN_LIFT_OVER_CONCURRENT:
            result = {
                "status": "weak_holdout",
                "message": "The selected lag did not clear the holdout screening rules (r ≥ 0.20 and at least 0.10 above the same-hour baseline). No practically useful repeatable signal is established.",
                "best_lag": best,
            }
        else:
            result = {"status": "exploratory", "message": "The selected lag cleared the holdout screening rules. This remains exploratory association, not demonstrated forecast skill.", "best_lag": best}
    return {
        **result,
        "period_days": days,
        "matched_hours": len(common),
        "wet_hours": wet_hours,
        "wet_days": wet_days,
        "coverage_start": common[0].isoformat() if common else None,
        "coverage_end": common[-1].isoformat() if common else None,
        "lag_profile": correlations,
        "training_hours": len(train_hours),
        "holdout_hours": len(holdout_hours),
        "holdout_screening_rules": {
            "minimum_correlation": HOLDOUT_MIN_CORRELATION,
            "minimum_lift_over_concurrent": HOLDOUT_MIN_LIFT_OVER_CONCURRENT,
        },
        "series": pairs,
        "level_station": {"reference": level_reference, "name": level_station.get("label"), "river": level_station.get("riverName"), "measure": level_measure.get("qualifier"), "unit": level_measure.get("unitName")},
        "rain_station": {"reference": rain_reference, "name": rain_station.get("label"), "measure": rain_measure.get("qualifier"), "unit": rain_measure.get("unitName")},
        "source_url": "https://environment.data.gov.uk/flood-monitoring/doc/reference",
    }
