"""Window 1 uses its events list like every other window (it lists only `memory` by default)."""

import copy
import random
from datetime import date
from pathlib import Path

import pytest
import yaml

import notify.__main__ as engine
from notify.defaults import ALL_EVENTS, DEFAULT_SETTINGS, DEFAULT_WINDOWS

TODAY = date(2026, 11, 26)
USER = {"name": "Tester", "immich_api_key": "key", "enabled": True}
NOTIFICATION = {"title": "t", "message": "m", "has_content": True, "asset_id": "a1"}


def make_config(events):
    settings = copy.deepcopy(DEFAULT_SETTINGS)
    settings["notification_windows"] = [{"start": "10:00", "end": "23:00", "events": events}]
    return {"immich": {"url": "http://immich"}, "settings": settings}


@pytest.fixture
def run_window_1(monkeypatch, logger):
    """Run window 1 once with Immich stubbed out; return the event types that were executed."""

    def run(events, has_memories=True, birthday_people=None):
        calls = []
        monkeypatch.setattr(engine, "fetch_memories", lambda *a, **k: [])
        monkeypatch.setattr(engine, "filter_todays_memories", lambda *a, **k: [{"id": "m"}] if has_memories else [])
        monkeypatch.setattr(engine, "parse_memories", lambda *a, **k: {"years": [2020], "by_year": {}, "total_assets": 1})
        monkeypatch.setattr(engine, "fetch_people", lambda *a, **k: [])
        monkeypatch.setattr(engine, "get_top_persons", lambda *a, **k: [])
        monkeypatch.setattr(engine, "find_birthday_people", lambda *a, **k: birthday_people or [])
        monkeypatch.setattr(engine, "prepare_birthday_notification", lambda **k: dict(NOTIFICATION))
        monkeypatch.setattr(engine, "prepare_person_notification", lambda **k: calls.append("person-fallback"))
        monkeypatch.setattr(engine, "_execute_event", lambda event_type, **k: calls.append(event_type) or dict(NOTIFICATION))
        engine.process_user_window(USER, make_config(events), {}, TODAY, 1, dry_run=True, logger=logger)
        return calls

    return run


def test_default_window_1_lists_only_memory():
    assert DEFAULT_WINDOWS[0]["events"] == ["memory"]
    assert all(w["events"] == ALL_EVENTS for w in DEFAULT_WINDOWS[1:])


def test_window_1_with_only_memory_sends_a_memory(run_window_1):
    assert {tuple(run_window_1(["memory"])) for _ in range(30)} == {("memory",)}


def test_window_1_without_memories_falls_back_to_a_person_photo(run_window_1):
    assert run_window_1(["memory"], has_memories=False) == ["person-fallback"]


def test_window_1_picks_from_its_events(run_window_1):
    random.seed(0)
    picks = [run_window_1(["memory", "person"]) for _ in range(100)]
    assert all(len(calls) == 1 for calls in picks)
    assert {calls[0] for calls in picks} == {"memory", "person"}


def test_window_1_does_not_force_a_memory_when_it_is_not_listed(run_window_1):
    assert {tuple(run_window_1(["person"])) for _ in range(20)} == {("person",)}


def test_window_1_skips_memory_when_there_is_none_today(run_window_1):
    random.seed(0)
    picks = {tuple(run_window_1(["memory", "person"], has_memories=False)) for _ in range(30)}
    assert picks == {("person",)}


def test_birthday_still_pre_empts_window_1(run_window_1):
    assert run_window_1(["memory", "person"], birthday_people=[{"id": "p1", "name": "Alex"}]) == []


def test_the_shipped_config_yaml_keeps_window_1_on_memories():
    shipped = yaml.safe_load((Path(__file__).parent.parent / "config.yaml").read_text(encoding="utf-8"))
    assert shipped["settings"]["notification_windows"][0]["events"] == ["memory"]
