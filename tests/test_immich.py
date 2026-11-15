from datetime import date, datetime, timedelta

from notify import immich
from notify.immich import (
    count_person_assets,
    fetch_people,
    filter_todays_memories,
    get_random_person_photo,
    get_top_persons,
    is_generated_asset,
    is_generated_search_item,
    parse_memories,
    search_metadata_all,
)
from tests.conftest import FakeResponse


def _memory(year, assets, show_at="2026-11-16T05:00:00.000Z", mid="m1"):
    return {"id": mid, "showAt": show_at, "data": {"year": year}, "assets": assets}


def test_filter_todays_memories_matches_date_prefix():
    mems = [_memory(2020, [], "2026-11-16T05:00:00Z"), _memory(2019, [], "2026-11-17T05:00:00Z")]
    assert len(filter_todays_memories(mems, date(2026, 11, 16))) == 1


def test_parse_memories_groups_by_year_and_counts_videos():
    mems = [
        _memory(2020, [{"id": "a", "type": "IMAGE"}, {"id": "b", "type": "VIDEO"}], mid="m2020"),
        _memory(2015, [{"id": "c"}], mid="m2015"),
        _memory(None, [{"id": "ignored"}]),
    ]
    parsed = parse_memories(mems)
    assert parsed["years"] == [2020, 2015]
    assert parsed["total_assets"] == 3
    assert parsed["video_count"] == 1
    assert parsed["by_year"][2020]["memory_id"] == "m2020"
    assert parsed["first_asset_id"] == "a"


def test_generated_detection_by_tag_filename_and_legacy_device():
    assert is_generated_search_item({"originalFileName": "memnotify-collage-1.jpg"})
    assert is_generated_search_item({"deviceId": "memnotify"})
    assert not is_generated_search_item({"originalFileName": "IMG_0001.jpg"})
    assert is_generated_asset({"tags": [{"name": immich.GENERATED_TAG_NAME}]})
    assert not is_generated_asset({"tags": [{"name": "holiday"}], "originalFileName": "x.jpg"})


def test_search_metadata_all_follows_next_page(fake_requests):
    pages = {
        1: {"assets": {"items": [{"id": "1"}, {"id": "2"}], "nextPage": "2"}},
        2: {"assets": {"items": [{"id": "3"}], "nextPage": None}},
    }
    fake_requests.route("POST", "/api/search/metadata", lambda body: FakeResponse(pages[body["page"]]))
    items = search_metadata_all("http://im", "key", {"personIds": ["p"]}, page_size=2)
    assert [i["id"] for i in items] == ["1", "2", "3"]
    assert len(fake_requests.calls) == 2


def test_search_metadata_all_handles_legacy_flat_list(fake_requests):
    fake_requests.route("POST", "/api/search/metadata", lambda body: FakeResponse({"assets": [{"id": "x"}]}))
    assert search_metadata_all("http://im", "key", {})[0]["id"] == "x"


def test_count_person_assets_prefers_statistics(fake_requests):
    fake_requests.route("POST", "/api/search/statistics", lambda body: FakeResponse({"total": 2737}))
    assert count_person_assets("http://im", "key", "p") == 2737


def test_count_person_assets_falls_back_when_statistics_missing(fake_requests):
    fake_requests.route("POST", "/api/search/statistics", lambda body: FakeResponse(None, status_code=404))
    fake_requests.route("POST", "/api/search/metadata", lambda body: FakeResponse({"assets": {"items": [{}], "total": 42}}))
    assert count_person_assets("http://im", "key", "p") == 42


def test_get_top_persons_ranks_by_count_and_skips_hidden_or_unnamed(fake_requests):
    totals = {"a": 10, "b": 300, "c": 50}
    fake_requests.route("POST", "/api/search/statistics", lambda body: FakeResponse({"total": totals[body["personIds"][0]]}))
    people = [
        {"id": "a", "name": "A"},
        {"id": "b", "name": "B"},
        {"id": "c", "name": "C"},
        {"id": "h", "name": "Hidden", "isHidden": True},
        {"id": "u", "name": ""},
    ]
    top = get_top_persons("http://im", "key", limit=2, people=people)
    assert [p["id"] for p in top] == ["b", "c"]
    assert top[0]["asset_count"] == 300


def test_fetch_people_follows_has_next_page(fake_requests):
    def handler(body, params):
        if params["page"] == 1:
            return FakeResponse({"people": [{"id": "1"}], "total": 2, "hasNextPage": True})
        return FakeResponse({"people": [{"id": "2"}], "total": 2, "hasNextPage": False})

    fake_requests.route("GET", "/api/people", handler)
    assert [p["id"] for p in fetch_people("http://im", "key")] == ["1", "2"]


def test_get_random_person_photo_filters_recent_excluded_and_generated(fake_requests):
    old = (datetime.now() - timedelta(days=400)).isoformat()
    new = datetime.now().isoformat()
    items = [
        {"id": "recent", "fileCreatedAt": new, "originalFileName": "a.jpg"},
        {"id": "sent", "fileCreatedAt": old, "originalFileName": "b.jpg"},
        {"id": "gen", "fileCreatedAt": old, "originalFileName": "memnotify-collage-9.jpg"},
        {"id": "good", "fileCreatedAt": old, "originalFileName": "c.jpg"},
    ]
    fake_requests.route("POST", "/api/search/metadata", lambda body: FakeResponse({"assets": {"items": items, "nextPage": None}}))
    fake_requests.route("GET", "/api/assets/good", lambda body: FakeResponse({"id": "good", "tags": []}))
    result = get_random_person_photo("http://im", "key", [{"id": "p", "name": "P"}], exclude_days=30, exclude_asset_ids={"sent"})
    assert result["asset"]["id"] == "good"
    detail_calls = [c for c in fake_requests.calls if c[0] == "GET" and "/api/assets/" in c[1]]
    assert len(detail_calls) == 1  # only the chosen asset is verified, not every candidate


def test_get_random_person_photo_returns_none_when_nothing_valid(fake_requests):
    fake_requests.route("POST", "/api/search/metadata", lambda body: FakeResponse({"assets": {"items": [], "nextPage": None}}))
    assert get_random_person_photo("http://im", "key", [{"id": "p", "name": "P"}]) is None
    assert get_random_person_photo("http://im", "key", []) is None
