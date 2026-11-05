import pytest

from triage import load


def test_all_event_units_exist_and_sorted(data):
    tenants, events = data
    assert {e.unit_id for e in events} <= set(tenants)
    assert [e.date for e in events] == sorted(e.date for e in events)
    assert [e.event_id for e in events] == ["R201", "R202", "R204", "R206", "R203", "R205"]


def test_unknown_unit_rejected(tmp_path, data):
    tenants, _ = data
    bad = tmp_path / "events.csv"
    bad.write_text(
        "event_id,unit_id,date,issue,status,detail\n"
        "R900,U9Z,2026-10-01,Kitchen sink leak,reported,x\n",
        encoding="utf-8",
    )
    with pytest.raises(load.ValidationError, match="U9Z"):
        load.validate(load.load_events(bad), tenants)


def test_bad_date_and_duplicate_rejected(tmp_path):
    p = tmp_path / "e.csv"
    p.write_text("event_id,unit_id,date,issue,status,detail\nR1,U2B,03/10/2026,a,b,c\n", encoding="utf-8")
    with pytest.raises(load.ValidationError, match="bad date"):
        load.load_events(p)
    p.write_text(
        "event_id,unit_id,date,issue,status,detail\nR1,U2B,2026-10-01,a,b,c\nR1,U2B,2026-10-02,a,b,c\n",
        encoding="utf-8",
    )
    with pytest.raises(load.ValidationError, match="duplicate"):
        load.load_events(p)


def test_missing_column_rejected(tmp_path):
    p = tmp_path / "t.csv"
    p.write_text("unit_id,name\nU1A,X\n", encoding="utf-8")
    with pytest.raises(load.ValidationError, match="missing columns"):
        load.load_tenants(p)
