from datetime import date, datetime

from notify import config as cfg

W = [{"start": "08:00", "end": "10:00"}, {"start": "12:00", "end": "14:00"}, {"start": "22:00", "end": "01:00"}]


def test_recent_assets_tracks_and_prunes():
    state = {}
    cfg.mark_asset_sent_recent(state, "A", date(2026, 1, 1), "old", repeat_days=30)
    cfg.mark_asset_sent_recent(state, "A", date(2026, 1, 20), "mid", repeat_days=30)
    today = date(2026, 2, 5)
    assert cfg.get_recent_assets(state, "A", today, 30) == {"mid"}
    cfg.mark_asset_sent_recent(state, "A", today, "new", repeat_days=30)
    assert set(state["users"]["A"]["assets_sent_recent"]) == {"mid", "new"}  # 'old' pruned
    assert cfg.get_recent_assets(state, "A", today, 0) == set()  # disabled
    cfg.mark_asset_sent_recent(state, "A", today, None, 30)  # no-op


def test_run_markers_lifecycle_and_pruning():
    state = {}
    d = date(2026, 3, 10)
    cfg.mark_run_started(state, date(2026, 3, 1), 1)
    cfg.mark_run_started(state, d, 2, now=datetime(2026, 3, 10, 12, 0))
    assert cfg.get_run_marker(state, d, 2) == {"started": "2026-03-10T12:00:00", "done": False}
    assert cfg.get_run_marker(state, date(2026, 3, 1), 1) is None  # pruned (> 3 days old)
    cfg.mark_run_done(state, d, 2)
    assert cfg.get_run_marker(state, d, 2)["done"] is True
    assert cfg.get_run_marker(state, d, 9) is None


def _state_with(markers):
    state = {}
    for slot, (started, done) in markers.items():
        cfg.mark_run_started(state, date(2026, 5, 5), slot, now=started)
        if done:
            cfg.mark_run_done(state, date(2026, 5, 5), slot)
    return state


def test_catch_up_nothing_before_windows_start():
    assert cfg.slots_due_for_catch_up(W, {}, datetime(2026, 5, 5, 7, 59)) == []


def test_catch_up_runs_window_that_never_started():
    # 9:00 — window 1 started at 8, cron never fired
    assert cfg.slots_due_for_catch_up(W, {}, datetime(2026, 5, 5, 9, 0)) == [1]


def test_catch_up_skips_run_still_sleeping_in_window():
    state = _state_with({1: (datetime(2026, 5, 5, 8, 0), False)})
    assert cfg.slots_due_for_catch_up(W, state, datetime(2026, 5, 5, 9, 0)) == []


def test_catch_up_reruns_run_that_died_mid_delay():
    state = _state_with({1: (datetime(2026, 5, 5, 8, 0), False)})
    assert cfg.slots_due_for_catch_up(W, state, datetime(2026, 5, 5, 10, 30)) == [1]


def test_catch_up_skips_done_and_too_late():
    state = _state_with({1: (datetime(2026, 5, 5, 8, 0), True)})
    # 13:30: slot 1 done, slot 2 (12-14) never started -> due
    assert cfg.slots_due_for_catch_up(W, state, datetime(2026, 5, 5, 13, 30)) == [2]
    # 17:30: slot 2 ended 3.5h ago -> too late, nothing due
    assert cfg.slots_due_for_catch_up(W, state, datetime(2026, 5, 5, 17, 30)) == []


def test_catch_up_overnight_window_and_bad_window():
    assert cfg.slots_due_for_catch_up(W, {}, datetime(2026, 5, 5, 23, 0)) == [3]
    assert cfg.slots_due_for_catch_up([{"start": "bad"}], {}, datetime(2026, 5, 5, 23, 0)) == []
