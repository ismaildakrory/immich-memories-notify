from collections import defaultdict
from datetime import date, datetime, timedelta

from notify.config import MAX_TRACKED_LANES, get_context_last_used, mark_context_used, record_lane
from notify.features.context import (
    MAX_THEMES_PER_RUN,
    MIN_LANE_PHOTOS,
    POOL_FACTOR,
    cleanup_lanes,
    order_themes,
    pick_spread,
    prepare_context_notification,
)
from notify.immich import PickPolicy
from tests.conftest import FakeResponse

URL = "http://immich"
NOW = datetime(2026, 11, 26, 12, 0, 0)


def asset(i, year, **extra):
    return {"id": f"a{i}", "localDateTime": f"{year}-06-0{i % 9 + 1}T10:00:00.000Z", "type": "IMAGE",
            "originalFileName": f"IMG_{i}.jpg", **extra}


def route_search(fake, by_query):
    fake.route("POST", "/api/search/smart", lambda body: FakeResponse({"assets": {"items": by_query[body["query"]]}}))


def route_create(fake, lane_id="lane1", status=201):
    fake.route("POST", "/api/memories", lambda body: FakeResponse({"id": lane_id}, status_code=status))


def memory_posts(fake):
    return [c for c in fake.calls if c[0] == "POST" and c[1].endswith("/api/memories")]


def prepare(logger, themes=("sunset",), **kw):
    kw.setdefault("assets_sent", set())
    kw.setdefault("messages", [])
    return prepare_context_notification(
        themes=list(themes), immich_url=URL, api_key="k", test_mode=False, logger=logger, now=NOW, **kw)


# --- pure helpers -----------------------------------------------------------

def test_pick_spread_covers_as_many_years_as_possible_in_date_order():
    assets = [asset(i, 2020) for i in range(6)] + [asset(10, 2021), asset(11, 2022)]
    picked = pick_spread(assets, 3)
    assert sorted(a["localDateTime"][:4] for a in picked) == ["2020", "2021", "2022"]
    dates = [a["localDateTime"] for a in picked]
    assert dates == sorted(dates)


def test_pick_spread_fills_up_from_the_same_year_when_needed():
    assets = [asset(i, 2020) for i in range(5)] + [asset(10, 2021)]
    picked = pick_spread(assets, 4)
    assert len(picked) == 4 and len({a["id"] for a in picked}) == 4
    assert {a["localDateTime"][:4] for a in picked} == {"2020", "2021"}


def test_pick_spread_returns_fewer_when_there_are_not_enough():
    assert len(pick_spread([asset(1, 2020), asset(2, 2021)], 8)) == 2
    assert pick_spread([], 8) == []


def test_pick_spread_prefers_unseen_photos_within_a_year():
    policy = PickPolicy(seen_ids={"a1"}, unseen_weight=1e9)
    assets = [asset(1, 2020), asset(2, 2020)]
    assert [a["id"] for a in pick_spread(assets, 1, policy)] == ["a2"]


def test_order_themes_tries_the_least_recently_used_first():
    last_used = {"a": "2026-11-01", "b": "2026-10-01"}
    assert order_themes(["a", "b", "c"], last_used) == ["c", "b", "a"]


# --- state helpers ----------------------------------------------------------

def test_context_usage_and_lane_tracking_state():
    state = {}
    assert get_context_last_used(state, "U") == {}
    mark_context_used(state, "U", "sunset", date(2026, 11, 20))
    assert get_context_last_used(state, "U") == {"sunset": "2026-11-20"}
    for n in range(MAX_TRACKED_LANES + 5):
        record_lane(state, "U", f"lane{n}", date(2026, 11, 20))
    lanes = state["users"]["U"]["lanes"]
    assert len(lanes) == MAX_TRACKED_LANES and lanes[-1]["id"] == f"lane{MAX_TRACKED_LANES + 4}"


# --- prepare_context_notification ------------------------------------------

def test_creates_a_lane_and_opens_it(fake_requests, logger):
    route_search(fake_requests, {"sunset": [asset(i, 2015 + i % 6) for i in range(12)]})
    route_create(fake_requests)
    result = prepare(logger, settings={"lane_photos": 6})

    assert result["is_context"] and result["context_theme"] == "sunset"
    assert result["lane_id"] == "lane1" and result["app_click_url"] == "immich://memory?id=lane1"
    assert len(result["asset_ids"]) == 6 and result["asset_id"] in result["asset_ids"]
    assert result["title"] == "Sunset, across the years"

    (_, _, body, _), = memory_posts(fake_requests)
    assert body["type"] == "on_this_day" and body["isSaved"] is False
    assert body["assetIds"] == result["asset_ids"]
    assert body["data"]["year"] == result["year"] == 2020
    # The app's memory bar needs showAt <= the start of the local day: it starts a day early, ends after tomorrow
    assert body["showAt"] == "2026-11-25T00:00:00.000Z" and body["hideAt"] == "2026-11-28T00:00:00.000Z"
    assert body["memoryAt"].startswith("2020-")  # newest photo in the lane


def test_lane_shows_in_the_apps_memory_bar_in_every_timezone(fake_requests, logger):
    """The Immich app lists a memory when showAt <= the start of the local day (read as UTC) <= hideAt."""
    route_search(fake_requests, {"sunset": [asset(i, 2015 + i) for i in range(5)]})
    route_create(fake_requests)
    prepare(logger)
    (_, _, body, _), = memory_posts(fake_requests)
    show = datetime.fromisoformat(body["showAt"].replace("Z", "+00:00")).replace(tzinfo=None)
    hide = datetime.fromisoformat(body["hideAt"].replace("Z", "+00:00")).replace(tzinfo=None)
    for offset in range(-12, 15):  # UTC-12 .. UTC+14
        local = NOW + timedelta(hours=offset)
        for extra_days in (0, 1):  # today and tomorrow on the phone
            local_midnight = datetime(local.year, local.month, local.day) + timedelta(days=extra_days)
            assert show <= local_midnight <= hide, (offset, extra_days)


def test_test_and_dry_runs_write_nothing_to_immich(fake_requests, logger):
    route_search(fake_requests, {"sunset": [asset(i, 2015 + i) for i in range(5)]})
    result = prepare(logger, upload=False)
    assert memory_posts(fake_requests) == []
    assert result["lane_id"] is None and "app_click_url" not in result and result["asset_ids"]


def test_still_notifies_when_the_lane_cannot_be_created(fake_requests, logger):
    route_search(fake_requests, {"sunset": [asset(i, 2015 + i) for i in range(5)]})
    route_create(fake_requests, status=403)
    result = prepare(logger)
    assert result["lane_id"] is None and "app_click_url" not in result and result["asset_id"]
    assert any("memory.create" in str(c) for c in logger.warning.call_args_list)


def test_never_uses_sent_screenshot_or_non_timeline_photos(fake_requests, logger):
    good = [asset(i, 2015 + i) for i in range(4)]
    bad = [
        asset(20, 2018, id="sent"),
        asset(21, 2018, originalFileName="Screenshot_2018.png"),
        asset(22, 2019, visibility="locked"),
        asset(23, 2019, visibility="archive"),
        asset(24, 2019, visibility="hidden"),
    ]
    route_search(fake_requests, {"sunset": good + bad})
    route_create(fake_requests)
    result = prepare(logger, assets_sent={"sent"}, settings={"lane_photos": 20})
    assert sorted(result["asset_ids"]) == sorted(a["id"] for a in good)


def test_skips_a_theme_with_too_few_photos_and_tries_the_next(fake_requests, logger):
    route_search(fake_requests, {"rare": [asset(i, 2020) for i in range(MIN_LANE_PHOTOS - 1)],
                                 "common": [asset(i, 2015 + i) for i in range(6)]})
    route_create(fake_requests)
    result = prepare(logger, themes=("rare", "common"), last_used={"common": "2026-11-25"})  # rare is tried first
    assert result["context_theme"] == "common"


def test_returns_nothing_when_no_theme_has_enough_photos(fake_requests, logger):
    route_search(fake_requests, {"sunset": [asset(1, 2020)]})
    assert prepare(logger) is None
    assert prepare(logger, themes=()) is None
    assert memory_posts(fake_requests) == []


def test_a_failing_search_moves_on_to_the_next_theme(fake_requests, logger):
    fake_requests.route("POST", "/api/search/smart", lambda body: (
        FakeResponse({}, status_code=500) if body["query"] == "broken"
        else FakeResponse({"assets": {"items": [asset(i, 2015 + i) for i in range(5)]}})))
    route_create(fake_requests)
    result = prepare(logger, themes=("broken", "fine"), last_used={"fine": "2026-11-25"})
    assert result["context_theme"] == "fine"
    assert logger.warning.called


def test_uses_templates_and_survives_a_bad_one(fake_requests, logger):
    route_search(fake_requests, {"snow": [asset(i, 2015 + i) for i in range(6)]})
    route_create(fake_requests)
    result = prepare(logger, themes=("snow",), messages=["{count} {theme}: {first_year}-{last_year}"],
                     title_templates=["{theme_title}!"])
    assert result["title"] == "Snow!" and result["message"] == "6 snow: 2015-2020"

    result = prepare(logger, themes=("snow",), messages=["{nope}"], title_templates=["{nope}"])
    assert result["title"] == "Snow, across the years" and result["message"] == "6 photos of snow, 2015 to 2020"


def test_test_mode_marks_the_title(fake_requests, logger):
    route_search(fake_requests, {"snow": [asset(i, 2015 + i) for i in range(4)]})
    result = prepare_context_notification(
        themes=["snow"], assets_sent=set(), immich_url=URL, api_key="k", messages=[], test_mode=True,
        logger=logger, upload=False, now=NOW)
    assert result["title"].startswith("[TEST] ")


def test_only_the_best_matches_are_spread_over_the_years(fake_requests, logger):
    strong = [asset(i, 2024) for i in range(MIN_LANE_PHOTOS * POOL_FACTOR)]
    weak = [asset(100 + i, 2010 + i) for i in range(5)]  # ranked last: one per year, but poor matches
    route_search(fake_requests, {"sunset": strong + weak})
    route_create(fake_requests)
    result = prepare(logger, settings={"lane_photos": MIN_LANE_PHOTOS})
    assert set(result["asset_ids"]) <= {a["id"] for a in strong}


def test_a_too_small_lane_photos_setting_is_raised_to_the_minimum(fake_requests, logger):
    route_search(fake_requests, {"sunset": [asset(i, 2015 + i) for i in range(6)]})
    route_create(fake_requests)
    assert len(prepare(logger, settings={"lane_photos": 0})["asset_ids"]) == MIN_LANE_PHOTOS


def test_tries_at_most_a_few_themes_per_run(fake_requests, logger):
    route_search(fake_requests, defaultdict(list))
    assert prepare(logger, themes=[f"theme{i}" for i in range(MAX_THEMES_PER_RUN + 3)]) is None
    searches = [c for c in fake_requests.calls if c[1].endswith("/api/search/smart")]
    assert len(searches) == MAX_THEMES_PER_RUN


def test_odd_search_responses_count_as_no_results(fake_requests, logger):
    odd = [{"assets": None}, [], {"assets": {"items": None}}, {"assets": {"items": [None, "x", {"type": "IMAGE"}]}}]
    for payload in odd:
        fake_requests.route("POST", "/api/search/smart", lambda body, params=None, p=payload: FakeResponse(p))
        assert prepare(logger) is None
    assert memory_posts(fake_requests) == []


# --- cleanup_lanes ----------------------------------------------------------

def _lanes_state():
    state = {}
    record_lane(state, "U", "old", date(2026, 11, 10))
    record_lane(state, "U", "recent", date(2026, 11, 25))
    record_lane(state, "U", "saved", date(2026, 11, 1))
    return state


def route_memory(fake, memory_id, saved=False):
    fake.route("GET", f"/api/memories/{memory_id}", lambda body: FakeResponse({"id": memory_id, "isSaved": saved}))
    fake.route("DELETE", f"/api/memories/{memory_id}", lambda body: FakeResponse(None, status_code=204))


def deletes(fake):
    return [c[1].rsplit("/", 1)[1] for c in fake.calls if c[0] == "DELETE"]


def test_cleanup_deletes_old_lanes_but_never_saved_or_recent_ones(fake_requests, logger):
    state = _lanes_state()
    route_memory(fake_requests, "old")
    route_memory(fake_requests, "saved", saved=True)
    removed = cleanup_lanes(URL, "k", state, "U", 7, date(2026, 11, 26), logger)
    assert removed == 1 and deletes(fake_requests) == ["old"]
    assert [lane["id"] for lane in state["users"]["U"]["lanes"]] == ["recent"]  # saved lane is no longer tracked


def test_cleanup_forgets_lanes_that_are_already_gone(fake_requests, logger):
    state = _lanes_state()
    fake_requests.route("GET", "/api/memories/old", lambda body: FakeResponse({}, status_code=400))
    fake_requests.route("GET", "/api/memories/saved", lambda body: FakeResponse({}, status_code=404))
    assert cleanup_lanes(URL, "k", state, "U", 7, date(2026, 11, 26), logger) == 0
    assert deletes(fake_requests) == []
    assert [lane["id"] for lane in state["users"]["U"]["lanes"]] == ["recent"]


def test_cleanup_keeps_a_lane_it_could_not_check_for_the_next_run(fake_requests, logger):
    state = _lanes_state()
    fake_requests.route("GET", "/api/memories/old", lambda body: FakeResponse({}, status_code=500))
    route_memory(fake_requests, "saved", saved=True)
    cleanup_lanes(URL, "k", state, "U", 7, date(2026, 11, 26), logger)
    assert [lane["id"] for lane in state["users"]["U"]["lanes"]] == ["old", "recent"]
    assert logger.warning.called


def test_cleanup_keeps_a_lane_it_is_not_allowed_to_delete(fake_requests, logger):
    state = _lanes_state()
    fake_requests.route("GET", "/api/memories/old", lambda body: FakeResponse({"id": "old", "isSaved": False}))
    fake_requests.route("DELETE", "/api/memories/old", lambda body: FakeResponse({}, status_code=403))
    route_memory(fake_requests, "saved", saved=True)
    assert cleanup_lanes(URL, "k", state, "U", 7, date(2026, 11, 26), logger) == 0
    assert [lane["id"] for lane in state["users"]["U"]["lanes"]] == ["old", "recent"]
    assert logger.warning.called


def test_cleanup_drops_unreadable_entries_and_ignores_users_without_lanes(fake_requests, logger):
    state = {"users": {"U": {"lanes": [{"id": "x"}, {"id": "y", "created": "not a date"}]}}}
    assert cleanup_lanes(URL, "k", state, "U", 7, date(2026, 11, 26), logger) == 0
    assert state["users"]["U"]["lanes"] == []
    empty = {}
    assert cleanup_lanes(URL, "k", empty, "nobody", 7, date(2026, 11, 26), logger) == 0
    assert empty == {}
