from datetime import date

from notify.features.trip import _cluster_trip_dates, _is_home_city, _normalize_city


def test_normalize_city_strips_diacritics_and_case():
    assert _normalize_city("Al Finţās") == "al fintas"
    assert _normalize_city("  GIZA ") == "giza"


def test_is_home_city_exact_fuzzy_and_containment():
    assert _is_home_city("Al Fintas", ["Al Finţās"])
    assert _is_home_city("Giza", "Giza")  # legacy string form
    assert _is_home_city("Greater London", ["London"])
    assert not _is_home_city("Cairo", ["Giza", "London"])
    assert not _is_home_city("Cairo", [])
    assert not _is_home_city("Cairo", None)


def test_cluster_picks_largest_run_within_gap():
    d = date(2024, 7, 1)
    items = [("a", d), ("b", date(2024, 7, 2)), ("c", date(2024, 7, 3)), ("x", date(2024, 7, 20)), ("y", date(2024, 7, 21))]
    assert _cluster_trip_dates(items, max_gap_days=5) == ["a", "b", "c"]


def test_cluster_empty_and_single():
    assert _cluster_trip_dates([]) == []
    assert _cluster_trip_dates([("only", date(2024, 1, 1))]) == ["only"]
