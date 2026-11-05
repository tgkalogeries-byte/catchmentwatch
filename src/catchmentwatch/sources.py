from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import json


BASE = "https://environment.data.gov.uk/flood-monitoring"
USER_AGENT = "CatchmentWatch-portfolio-prototype/0.1 (open-data research)"


def fetch_items(path: str, params: dict[str, str] | None = None, limit: int = 10000) -> list[dict[str, Any]]:
    """Read a bounded list endpoint completely, following offset pages."""
    items: list[dict[str, Any]] = []
    page_size = 1000
    for offset in range(0, limit, page_size):
        query = {**(params or {}), "_limit": str(min(page_size, limit - offset)), "_offset": str(offset)}
        request = Request(f"{BASE}/{path}?{urlencode(query)}", headers={"User-Agent": USER_AGENT})
        with urlopen(request, timeout=30) as response:
            payload = json.load(response)
        page = payload.get("items", [])
        if not isinstance(page, list):
            raise ValueError(f"Unexpected response from {path}")
        items.extend(page)
        if len(page) < min(page_size, limit - offset):
            break
    return items


def _latest_by_measure(readings: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for reading in readings:
        measure = reading.get("measure")
        if not measure:
            continue
        current = latest.get(measure)
        if current is None or str(reading.get("dateTime", "")) > str(current.get("dateTime", "")):
            latest[measure] = reading
    return latest


def _signal_for_station(
    station: dict[str, Any],
    measure_uri: str,
    reading: dict[str, Any] | None,
    kind: str,
) -> dict[str, Any]:
    measure = next((m for m in station.get("measures", []) if m.get("@id") == measure_uri), {})
    raw_value = reading.get("value") if reading else None
    try:
        value = float(raw_value) if raw_value is not None else None
    except (TypeError, ValueError):
        value = None
    item = {
        "reference": station.get("stationReference") or station.get("notation"),
        "name": station.get("label") or "Unnamed monitoring station",
        "town": station.get("town"),
        "catchment": station.get("catchmentName"),
        "river": station.get("riverName"),
        "lat": station.get("lat"),
        "lon": station.get("long"),
        "kind": kind,
        "value": value,
        "unit": measure.get("unitName"),
        "observed_at": reading.get("dateTime") if reading else None,
        "source_url": reading.get("@id") if reading else None,
    }
    if kind == "level":
        qualifier = str(measure.get("qualifier", "")).lower()
        scale_key = "downstageScale" if "downstream" in qualifier else "stageScale"
        scale = (station.get(scale_key) or {}) if measure else {}
        typical_high = scale.get("typicalRangeHigh")
        try:
            typical_high = float(typical_high) if typical_high is not None else None
        except (TypeError, ValueError):
            typical_high = None
        item["typical_range_high"] = typical_high
        item["above_typical_range"] = value is not None and typical_high is not None and value > typical_high
        item["stage_scale_url"] = scale.get("@id")
        item["measure_qualifier"] = measure.get("qualifier")
    return item


def snapshot() -> dict[str, Any]:
    fetched_at = datetime.now(timezone.utc).isoformat()
    failures: list[str] = []
    feeds: dict[str, Any] = {}

    try:
        level_stations = fetch_items("id/stations", {"parameter": "level", "_view": "full"}, limit=500)
        level_readings = fetch_items("data/readings", {"latest": "", "parameter": "level"}, limit=20000)
        level_station_by_measure = {
            measure.get("@id"): station
            for station in level_stations
            for measure in station.get("measures", [])
            if measure.get("parameter") == "level" and measure.get("@id")
        }
        level_latest = _latest_by_measure(level_readings)
        water = []
        for uri, station in level_station_by_measure.items():
            reading = level_latest.get(uri)
            if reading:
                water.append(_signal_for_station(station, uri, reading, "level"))
        feeds["water"] = {"status": "ok", "stations_returned": len(level_stations), "readings_matched": len(water)}
    except Exception as exc:
        water = []
        failures.append(f"Water level feed: {type(exc).__name__}: {exc}")
        feeds["water"] = {"status": "unavailable", "stations_returned": 0, "readings_matched": 0}

    try:
        rain_stations = fetch_items("id/stations", {"parameter": "rainfall", "_view": "full"}, limit=500)
        rain_readings = fetch_items("data/readings", {"latest": "", "parameter": "rainfall"}, limit=20000)
        rain_station_by_measure = {
            measure.get("@id"): station
            for station in rain_stations
            for measure in station.get("measures", [])
            if measure.get("parameter") == "rainfall" and measure.get("@id")
        }
        rain_latest = _latest_by_measure(rain_readings)
        rain = []
        for uri, station in rain_station_by_measure.items():
            reading = rain_latest.get(uri)
            if reading:
                rain.append(_signal_for_station(station, uri, reading, "rainfall"))
        feeds["rainfall"] = {"status": "ok", "stations_returned": len(rain_stations), "readings_matched": len(rain)}
    except Exception as exc:
        rain = []
        failures.append(f"Rainfall feed: {type(exc).__name__}: {exc}")
        feeds["rainfall"] = {"status": "unavailable", "stations_returned": 0, "readings_matched": 0}

    try:
        alerts = fetch_items("id/floods", {"min-severity": "3"}, limit=500)
        feeds["alerts"] = {"status": "ok", "returned": len(alerts)}
    except Exception as exc:
        alerts = []
        failures.append(f"Flood alerts feed: {type(exc).__name__}: {exc}")
        feeds["alerts"] = {"status": "unavailable", "returned": 0}

    alert_rows = []
    for alert in alerts:
        alert_rows.append({
            "id": alert.get("@id"),
            "description": alert.get("description") or alert.get("message") or "Environment Agency flood alert",
            "severity": alert.get("severity"),
            "severity_level": alert.get("severityLevel"),
            "time_raised": alert.get("timeRaised"),
            "county": alert.get("floodArea", {}).get("county") if isinstance(alert.get("floodArea"), dict) else None,
            "area": alert.get("floodArea", {}).get("label") if isinstance(alert.get("floodArea"), dict) else None,
            "url": alert.get("@id"),
        })

    # Link rainfall gauges by straight-line proximity for situational context only;
    # geographic closeness does not imply that two sites share a hydrological catchment.
    for gauge in water:
        try:
            observed = datetime.fromisoformat(str(gauge["observed_at"]).replace("Z", "+00:00"))
            gauge["is_stale"] = (datetime.now(timezone.utc) - observed).total_seconds() > 86400
        except (KeyError, TypeError, ValueError):
            gauge["is_stale"] = True
        nearby = [r for r in rain if gauge.get("lat") is not None and r.get("lat") is not None]
        if nearby:
            from math import asin, cos, radians, sin, sqrt
            def distance_km(a: dict[str, Any], b: dict[str, Any]) -> float:
                lat1, lon1, lat2, lon2 = map(radians, [float(a["lat"]), float(a["lon"]), float(b["lat"]), float(b["lon"])])
                dlat, dlon = lat2 - lat1, lon2 - lon1
                h = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
                return 6371 * 2 * asin(sqrt(h))
            nearest = min(nearby, key=lambda r: distance_km(gauge, r))
            try:
                rain_time = datetime.fromisoformat(str(nearest["observed_at"]).replace("Z", "+00:00"))
                rain_stale = (datetime.now(timezone.utc) - rain_time).total_seconds() > 86400
            except (KeyError, TypeError, ValueError):
                rain_stale = True
            gauge["nearby_rainfall"] = {**nearest, "distance_km": round(distance_km(gauge, nearest), 1), "is_stale": rain_stale}
        else:
            gauge["nearby_rainfall"] = None


    water.sort(key=lambda row: (not row.get("above_typical_range", False), row.get("name", "")))
    return {
        "fetched_at": fetched_at,
        "source": "Environment Agency real-time flood-monitoring API",
        "source_url": "https://environment.data.gov.uk/flood-monitoring/doc/reference",
        "water_levels": water,
        "rainfall": rain,
        "alerts": alert_rows,
        "feeds": feeds,
        "partial_errors": failures,
        "scope_note": "A latest-reading snapshot and public alerts. It is not a forecast or safety-critical warning service.",
    }
