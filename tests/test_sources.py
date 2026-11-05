from catchmentwatch.sources import _latest_by_measure, _signal_for_station
from datetime import datetime, timedelta, timezone
import pytest


def test_latest_reading_uses_observation_time_per_measure():
    rows = [
        {"measure": "m1", "dateTime": "2026-01-01T01:00:00Z", "value": 1},
        {"measure": "m1", "dateTime": "2026-01-01T02:00:00Z", "value": 2},
        {"measure": "m2", "dateTime": "2026-01-01T01:30:00Z", "value": 3},
    ]
    latest = _latest_by_measure(rows)
    assert latest["m1"]["value"] == 2
    assert latest["m2"]["value"] == 3


def test_downstream_reading_uses_downstream_scale_and_matching_measure_units():
    station = {
        "stationReference": "1234",
        "measures": [
            {"@id": "main", "parameter": "level", "qualifier": "Stage", "unitName": "mASD"},
            {"@id": "down", "parameter": "level", "qualifier": "Downstream Stage", "unitName": "mASD"},
        ],
        "stageScale": {"typicalRangeHigh": 1.0, "@id": "stage-scale"},
        "downstageScale": {"typicalRangeHigh": 4.0, "@id": "downstage-scale"},
    }
    row = _signal_for_station(station, "down", {"value": 3.0, "dateTime": "2026-01-01T00:00:00Z"}, "level")
    assert row["unit"] == "mASD"
    assert row["measure_qualifier"] == "Downstream Stage"
    assert row["typical_range_high"] == 4.0
    assert row["above_typical_range"] is False


def test_unknown_measure_has_no_range_comparison():
    station = {"stationReference": "1234", "measures": [], "stageScale": {"typicalRangeHigh": 2}}
    row = _signal_for_station(station, "unknown", {"value": 3}, "level")
    assert row["unit"] is None
    assert row["typical_range_high"] is None
    assert row["above_typical_range"] is False


def test_lag_scan_recovers_delayed_rainfall_association(monkeypatch):
    import catchmentwatch.analysis as analysis

    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rain = [float(((i * 17 + i // 3) % 11) in (0, 1, 4)) for i in range(120)]
    levels = [0.0]
    for i in range(1, len(rain)):
        levels.append(levels[-1] + (rain[i - 2] if i >= 2 else 0.0))

    def make_rows(values):
        return [{"dateTime": (start + timedelta(hours=i)).isoformat(), "value": value} for i, value in enumerate(values)]

    stations = {
        "level": {"stationReference": "L1", "label": "River", "measures": [{"@id": "measure-level", "parameter": "level", "qualifier": "Stage", "unitName": "m"}]},
        "rainfall": {"stationReference": "R1", "label": "Rain", "measures": [{"@id": "measure-rain", "parameter": "rainfall", "unitName": "mm"}]},
    }
    monkeypatch.setattr(analysis, "_station", lambda ref, parameter: stations[parameter])
    monkeypatch.setattr(analysis, "_history", lambda uri, since: make_rows(levels if uri == "measure-level" else rain))
    result = analysis.analyze_pair("L1", "R1")
    assert result["status"] == "exploratory"
    assert result["best_lag"]["lag_hours"] == 2
    assert result["best_lag"]["training_correlation"] == pytest.approx(1.0)
    assert result["best_lag"]["holdout_correlation"] == pytest.approx(1.0)


def test_training_lag_pairs_do_not_cross_into_holdout():
    import catchmentwatch.analysis as analysis

    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    boundary = start + timedelta(hours=1)
    levels = {boundary: 1.0, boundary + timedelta(hours=1): 2.0}
    rain = {start: 1.0, boundary: 1.0}
    result = analysis._lag_correlation([start], levels, rain, 1, end_exclusive=boundary)
    assert result["pairs"] == 0


def test_lag_scan_does_not_report_dry_flat_series(monkeypatch):
    import catchmentwatch.analysis as analysis

    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = [{"dateTime": (start + timedelta(hours=i)).isoformat(), "value": 0.0} for i in range(72)]
    stations = {
        "level": {"stationReference": "L1", "label": "River", "measures": [{"@id": "level", "parameter": "level", "qualifier": "Stage", "unitName": "m"}]},
        "rainfall": {"stationReference": "R1", "label": "Rain", "measures": [{"@id": "rain", "parameter": "rainfall", "unitName": "mm"}]},
    }
    monkeypatch.setattr(analysis, "_station", lambda ref, parameter: stations[parameter])
    monkeypatch.setattr(analysis, "_history", lambda uri, since: rows)
    result = analysis.analyze_pair("L1", "R1")
    assert result["status"] == "insufficient_variation"
    assert result["best_lag"] is None


def test_api_rejects_invalid_station_reference_without_fetching():
    from fastapi.testclient import TestClient
    from catchmentwatch.main import app

    response = TestClient(app).get("/api/pair-analysis", params={"level_station": "../bad", "rain_station": "4163"})
    assert response.status_code == 400


def test_api_bounds_history_window():
    from fastapi.testclient import TestClient
    from catchmentwatch.main import app

    response = TestClient(app).get("/api/pair-analysis", params={"level_station": "4203", "rain_station": "4163", "days": 31})
    assert response.status_code == 422
