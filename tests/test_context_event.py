"""The `context` event inside the engine: selection, tracking and housekeeping."""

import copy
from datetime import date

import pytest

import notify.__main__ as engine
from notify.defaults import DEFAULT_SETTINGS, apply_template_defaults

TODAY = date(2026, 11, 26)
USER = {"name": "Tester", "immich_api_key": "key", "enabled": True}


def context_notification(lane_id="lane1"):
    return {"title": "Sunset, across the years", "message": "8 photos", "has_content": True, "asset_id": "a3",
            "asset_ids": ["a1", "a2", "a3"], "year": 2024, "is_context": True, "context_theme": "sunset",
            "lane_id": lane_id}


def make_config(themes=None):
    settings = copy.deepcopy(DEFAULT_SETTINGS)
    settings["notification_windows"] = [{"start": "10:00", "end": "23:00", "events": ["context"]}]
    settings["context_themes"] = ["sunset"] if themes is None else themes
    return apply_template_defaults({"immich": {"url": "http://immich"}, "settings": settings})


@pytest.fixture
def harness(monkeypatch, logger):
    """Run window 1 with Immich and ntfy stubbed out. Returns (run, calls)."""
    calls = {"context": [], "cleanup": [], "fallback": 0, "sent": []}

    def fake_context(**kw):
        calls["context"].append(kw)
        notification = dict(calls["notification"])
        if not kw["upload"]:
            notification["lane_id"] = None  # like the real feature: nothing is written to Immich
        return notification

    def fake_send(user, notification, config, logger, thumbnail_override=None):
        calls["sent"].append(notification)
        return calls["send_ok"]

    monkeypatch.setattr(engine, "fetch_memories", lambda *a, **k: [])
    monkeypatch.setattr(engine, "filter_todays_memories", lambda *a, **k: [])
    monkeypatch.setattr(engine, "fetch_people", lambda *a, **k: [])
    monkeypatch.setattr(engine, "get_top_persons", lambda *a, **k: [])
    monkeypatch.setattr(engine, "find_birthday_people", lambda *a, **k: [])
    monkeypatch.setattr(engine, "prepare_person_notification", lambda **k: calls.__setitem__("fallback", calls["fallback"] + 1))
    monkeypatch.setattr(engine, "prepare_context_notification", fake_context)
    monkeypatch.setattr(engine, "cleanup_lanes", lambda *a, **k: calls["cleanup"].append(a))
    monkeypatch.setattr(engine, "send_notification", fake_send)
    calls["notification"] = context_notification()
    calls["send_ok"] = True

    def run(state=None, themes=None, **kw):
        state = {} if state is None else state
        engine.process_user_window(USER, make_config(themes), state, TODAY, 1, logger=logger, **kw)
        return state

    return run, calls


def test_context_event_is_selected_and_every_lane_photo_counts_as_sent(harness):
    run, calls = harness
    state = run()
    assert len(calls["context"]) == 1 and len(calls["sent"]) == 1
    user_state = state["users"]["Tester"]
    assert set(user_state["assets_sent_recent"]) == {"a1", "a2", "a3"}
    assert user_state["context_last_used"] == {"sunset": "2026-11-26"}
    assert user_state["lanes"] == [{"id": "lane1", "created": "2026-11-26"}]
    assert user_state["history"][-1]["kind"] == "context"


def test_the_context_event_gets_the_configured_themes_and_templates(harness):
    run, calls = harness
    run(themes=["snow", "beach"])
    kw = calls["context"][0]
    assert kw["themes"] == ["snow", "beach"]
    assert kw["upload"] is True and kw["settings"]["lane_photos"] == 8
    assert kw["title_templates"] and kw["messages"]  # the default templates


def test_themes_are_off_by_default():
    assert DEFAULT_SETTINGS["context_themes"] == []


def test_at_most_one_themed_memory_a_day(harness):
    run, calls = harness
    state = {"users": {"Tester": {"context_last_used": {"snow": "2026-11-26"}}}}
    run(state)
    assert calls["context"] == [] and calls["fallback"] == 1
    state["users"]["Tester"]["context_last_used"] = {"snow": "2026-11-25"}
    run(state)
    assert len(calls["context"]) == 1


def test_a_failing_themed_memory_falls_back_instead_of_aborting_the_window(harness, monkeypatch):
    run, calls = harness

    def broken(**kw):
        raise TypeError("unexpected response")

    monkeypatch.setattr(engine, "prepare_context_notification", broken)
    run()
    assert calls["fallback"] == 1


def test_lanes_are_never_read_back_as_on_this_day_memories(harness, monkeypatch):
    run, calls = harness
    seen = []
    monkeypatch.setattr(engine, "fetch_memories", lambda *a, **k: [{"id": "lane1"}, {"id": "real"}])
    monkeypatch.setattr(engine, "filter_todays_memories", lambda memories, *a, **k: seen.append(memories) or [])
    run({"users": {"Tester": {"lanes": [{"id": "lane1", "created": "2026-11-26"}]}}})
    assert [m["id"] for m in seen[0]] == ["real"]


def test_context_is_not_eligible_without_themes(harness):
    run, calls = harness
    run(themes=[])
    assert calls["context"] == [] and calls["fallback"] == 1


def test_a_lane_is_tracked_even_when_sending_fails(harness):
    run, calls = harness
    calls["send_ok"] = False
    state = run()
    user_state = state["users"]["Tester"]
    assert user_state["lanes"] == [{"id": "lane1", "created": "2026-11-26"}]  # can still be cleaned up
    assert "assets_sent_recent" not in user_state  # nothing was shown, so nothing counts as sent


def test_no_lane_means_nothing_to_track(harness):
    run, calls = harness
    calls["notification"] = context_notification(lane_id=None)
    state = run()
    assert "lanes" not in state["users"]["Tester"]
    assert calls["sent"]


def test_old_lanes_are_cleaned_up_on_real_runs_only(harness):
    run, calls = harness
    run()
    assert len(calls["cleanup"]) == 1
    run(dry_run=True)
    run(test_mode=True)
    assert len(calls["cleanup"]) == 1


def test_dry_run_builds_the_set_but_does_not_upload_or_send(harness):
    run, calls = harness
    state = run(dry_run=True)
    assert calls["context"][0]["upload"] is False
    assert calls["sent"] == [] and state == {}


def test_the_engine_never_tracks_a_lane_in_a_dry_run_even_if_one_is_reported(harness, monkeypatch):
    run, calls = harness
    monkeypatch.setattr(engine, "prepare_context_notification", lambda **kw: context_notification())
    assert run(dry_run=True) == {}
