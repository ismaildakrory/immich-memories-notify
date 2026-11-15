import io
from datetime import datetime

from PIL import Image

from notify.utils import calculate_random_delay, ensure_jpeg, format_location, get_primary_album, with_retry


def test_delay_before_window_lands_inside_window():
    now = datetime(2026, 1, 1, 7, 0)
    for _ in range(50):
        d = calculate_random_delay("08:00", "10:00", now=now)
        assert 3600 <= d <= 3600 + 7200


def test_delay_inside_window_never_exceeds_window_end():
    now = datetime(2026, 1, 1, 9, 30)
    for _ in range(50):
        assert 0 <= calculate_random_delay("08:00", "10:00", now=now) <= 1800


def test_delay_after_window_is_zero():
    assert calculate_random_delay("08:00", "10:00", now=datetime(2026, 1, 1, 11, 0)) == 0


def test_delay_handles_overnight_window():
    now = datetime(2026, 1, 1, 23, 30)
    d = calculate_random_delay("23:00", "01:00", now=now)
    assert 0 <= d <= 5400


def test_delay_test_mode_is_short():
    assert 1 <= calculate_random_delay("08:00", "10:00", test_mode=True) <= 5


def test_format_location_variants():
    assert format_location({"city": "Giza", "country": "Egypt"})["location"] == "Giza, Egypt"
    assert format_location({"city": "Giza"})["location"] == "Giza"
    assert format_location({"country": "Egypt"})["location"] == "Egypt"
    assert format_location({})["location"] == ""
    assert format_location(None)["location"] == ""


def test_get_primary_album_prefers_explicit_list():
    assert get_primary_album({"albums": [{"albumName": "v2"}]}) == "v2"
    assert get_primary_album({}, [{"albumName": "v3"}]) == "v3"
    assert get_primary_album({}, []) is None


def test_ensure_jpeg_converts_webp_and_passes_jpeg_through():
    img = Image.new("RGB", (8, 8), (200, 10, 10))
    webp = io.BytesIO()
    img.save(webp, "WEBP")
    out = ensure_jpeg(webp.getvalue())
    assert out[:3] == b"\xff\xd8\xff"  # JPEG SOI marker
    jpg = io.BytesIO()
    img.save(jpg, "JPEG")
    assert ensure_jpeg(jpg.getvalue()) == jpg.getvalue()


def test_with_retry_retries_then_raises(monkeypatch):
    monkeypatch.setattr("notify.utils.time.sleep", lambda s: None)
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("boom")
        return "ok"

    assert with_retry(flaky, max_attempts=3, delay=0) == "ok"
    calls["n"] = 0
    try:
        with_retry(flaky, max_attempts=2, delay=0)
        raise AssertionError("should have raised")
    except RuntimeError:
        pass
