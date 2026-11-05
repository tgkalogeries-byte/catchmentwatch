from catchmentwatch.sources import _latest_by_measure, _signal_for_station


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
