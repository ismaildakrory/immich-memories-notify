import json
from datetime import date

import yaml

from notify import config as cfg


def test_expand_env_vars_with_defaults(monkeypatch):
    monkeypatch.setenv("FOO", "bar")
    monkeypatch.delenv("MISSING", raising=False)
    data = {"a": "${FOO}", "b": "${MISSING:-dflt}", "c": "${MISSING}", "d": ["${FOO}"], "e": 5}
    assert cfg.expand_env_vars(data) == {"a": "bar", "b": "dflt", "c": "", "d": ["bar"], "e": 5}


def test_load_config_applies_defaults_and_migrations(tmp_path, monkeypatch):
    monkeypatch.setenv("IMMICH_URL", "http://im")
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump({
        "immich": {"url": "${IMMICH_URL}"},
        "users": [{"name": "A"}],
        "settings": {
            "collage_year_range": 12,
            "weekly_collage_day": 6,
            "memory_notifications": 3,
            "notification_windows": [{"start": "08:00", "end": "09:00"}],
        },
    }))
    c = cfg.load_config(str(path))
    s = c["settings"]
    assert c["immich"]["url"] == "http://im"
    assert s["year_range"] == 12 and "collage_year_range" not in s
    assert "weekly_collage_day" not in s and "memory_notifications" not in s
    assert s["collage_cooldown_days"] == 7
    assert s["notification_windows"][0]["events"] == cfg.ALL_EVENTS
    assert c["users"][0]["notification_service"] == "ntfy"


def test_get_window_events_out_of_range_returns_all():
    c = {"settings": {"notification_windows": [{"start": "08:00", "end": "09:00", "events": ["memory"]}]}}
    assert cfg.get_window_events(c, 1) == ["memory"]
    assert cfg.get_window_events(c, 5) == cfg.ALL_EVENTS


def test_slot_state_resets_on_new_day():
    state = {}
    d1, d2 = date(2026, 1, 1), date(2026, 1, 2)
    cfg.mark_slot_sent(state, "A", d1, 1, "asset1")
    cfg.mark_slot_sent(state, "A", d1, 2, "asset2")
    assert cfg.get_slots_sent_today(state, "A", d1) == [1, 2]
    assert cfg.get_assets_sent_today(state, "A", d1) == {"asset1", "asset2"}
    assert cfg.get_slots_sent_today(state, "A", d2) == []
    cfg.mark_slot_sent(state, "A", d2, 1, "asset3")
    assert cfg.get_slots_sent_today(state, "A", d2) == [1]
    assert cfg.get_assets_sent_today(state, "A", d2) == {"asset3"}


def test_feature_cooldown():
    state = {}
    today = date(2026, 1, 10)
    assert cfg.is_feature_ready(state, "A", "last_tan_date", 7, today)
    cfg.mark_feature_fired(state, "A", "last_tan_date", date(2026, 1, 5))
    assert not cfg.is_feature_ready(state, "A", "last_tan_date", 7, today)
    assert cfg.is_feature_ready(state, "A", "last_tan_date", 5, today)
    state["users"]["A"]["last_tan_date"] = "garbage"
    assert cfg.is_feature_ready(state, "A", "last_tan_date", 7, today)


def test_special_sent_today():
    state = {}
    assert not cfg.was_special_sent_today(state, "A", date(2026, 1, 1))
    cfg.mark_special_sent_today(state, "A", date(2026, 1, 1))
    assert cfg.was_special_sent_today(state, "A", date(2026, 1, 1))
    assert not cfg.was_special_sent_today(state, "A", date(2026, 1, 2))


def test_state_round_trip_and_corruption(tmp_path):
    sf = tmp_path / "state" / "state.json"
    cfg.save_state(str(sf), {"users": {"A": {"x": 1}}})
    assert cfg.load_state(str(sf)) == {"users": {"A": {"x": 1}}}
    assert json.loads(sf.read_text())["users"]["A"]["x"] == 1
    sf.write_text("{not json")
    assert cfg.load_state(str(sf)) == {}
    assert cfg.load_state(str(tmp_path / "nope.json")) == {}
