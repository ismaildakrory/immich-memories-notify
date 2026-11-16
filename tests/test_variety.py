import random
from collections import Counter

from notify.features.memories import choose_memory_year
from notify.features.then_and_now import find_then_and_now_candidate
from notify.immich import _weighted_bucket_choice, select_asset_with_face_preference


def _parsed(years):
    return {
        "years": sorted(years, reverse=True),
        "by_year": {y: {"assets": [{"id": f"{y}-a"}, {"id": f"{y}-b"}]} for y in years},
    }


def test_choose_memory_year_gives_old_years_a_chance():
    random.seed(0)
    picks = Counter(choose_memory_year(_parsed([2025, 2022, 2016, 2008]), set(), set()) for _ in range(2000))
    assert set(picks) == {2025, 2022, 2016, 2008}
    assert min(picks.values()) > 300


def test_choose_memory_year_skips_years_sent_today_then_falls_back():
    parsed = _parsed([2025, 2016])
    assert choose_memory_year(parsed, set(), {"2025-a"}) == 2016
    assert choose_memory_year(parsed, set(), {"2025-a", "2016-b"}) in (2025, 2016)  # all sent today → any
    assert choose_memory_year(parsed, {"2025-a", "2025-b", "2016-a", "2016-b"}, set()) is None  # all excluded


def test_weighted_bucket_choice_prefers_but_does_not_monopolise():
    random.seed(1)
    buckets = [("best", ["b"], 8), ("worst", ["w"], 1)]
    picks = Counter(_weighted_bucket_choice(buckets)[0] for _ in range(3000))
    assert picks["b"] > picks["w"] * 4
    assert picks["w"] > 100
    assert _weighted_bucket_choice([("empty", [], 5)]) == (None, None)


def test_face_preference_still_excludes_sent_and_generated(monkeypatch):
    import notify.immich as im

    details = {
        "g": {"id": "g", "tags": [{"name": im.GENERATED_TAG_NAME}]},
        "x": {"id": "x", "people": []},
        "y": {"id": "y", "people": [{"id": "p1", "name": "P", "faces": [{"imageWidth": 1, "imageHeight": 1}]}]},
    }
    monkeypatch.setattr(im, "fetch_asset_details", lambda u, k, aid, timeout=10: details[aid])
    assets = [{"id": "sent"}, {"id": "g"}, {"id": "x"}, {"id": "y"}]
    random.seed(2)
    picks = {select_asset_with_face_preference(assets, {"p1"}, "u", "k", exclude_asset_ids={"sent"})["id"] for _ in range(200)}
    assert picks == {"x", "y"}  # faceless 'x' now gets a turn; sent/generated never


def test_then_and_now_rotates_people_and_then_years(monkeypatch):
    import notify.features.then_and_now as tan

    library = {
        "p1": [2010, 2015, 2020, 2025],  # big gap person
        "p2": [2019, 2025],
    }

    def fake_assets(url, key, pid):
        return [{"id": f"{pid}-{y}", "type": "IMAGE", "localDateTime": f"{y}-06-10T10:00:00"} for y in library[pid]]

    monkeypatch.setattr(tan, "fetch_person_assets", fake_assets)
    monkeypatch.setattr(tan, "fetch_asset_details", lambda u, k, a: {})
    monkeypatch.setattr(tan, "get_asset_people", lambda u, k, a: [])
    top = [{"id": "p1", "name": "One"}, {"id": "p2", "name": "Two"}]
    from datetime import date

    random.seed(3)
    results = [find_then_and_now_candidate("u", "k", top, date(2026, 6, 1), min_gap=5, year_range=20,
                                           used_person_ids=["p1"]) for _ in range(60)]
    # p1 was used last → p2 is preferred this round
    assert all(r["person_id"] == "p2" for r in results)
    then_years = {find_then_and_now_candidate("u", "k", top[:1], date(2026, 6, 1), min_gap=5, year_range=20)["then_year"]
                  for _ in range(60)}
    assert then_years == {2010, 2015, 2020}  # not always the oldest year
