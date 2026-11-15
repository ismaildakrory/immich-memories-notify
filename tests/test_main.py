import random

from notify.__main__ import REGULAR_EVENTS, SPECIAL_EVENTS, select_event_type


def test_event_sets_are_disjoint_and_complete():
    from notify.config import ALL_EVENTS

    assert REGULAR_EVENTS | SPECIAL_EVENTS == set(ALL_EVENTS)
    assert not (REGULAR_EVENTS & SPECIAL_EVENTS)


def test_select_event_type_only_returns_eligible_and_boosts_memory():
    random.seed(1)
    picks = [select_event_type(["memory", "person"]) for _ in range(4000)]
    assert set(picks) <= {"memory", "person"}
    ratio = picks.count("memory") / picks.count("person")
    assert 1.0 < ratio < 1.25  # 1.1 weight


def test_select_event_type_empty_falls_back_to_person():
    assert select_event_type([]) == "person"
