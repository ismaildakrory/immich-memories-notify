from notify.utils import build_click_url, normalize_click_base


def test_normalize_click_base():
    assert normalize_click_base("photos.example.com/") == "https://photos.example.com"
    assert normalize_click_base("http://x:2283") == "http://x:2283"
    assert normalize_click_base(None) == ""


def test_app_mode_prefers_feature_link_then_asset():
    assert build_click_url({"asset_id": "a1", "app_click_url": "immich://memory?id=m"}, "https://b") == "immich://memory?id=m"
    assert build_click_url({"asset_id": "a1"}, "https://b") == "immich://asset?id=a1"
    assert build_click_url({"asset_id": "a1", "click_url": "https://b/photos/other"}, "https://b", "app") == "immich://asset?id=a1"


def test_app_mode_falls_back_to_web_without_asset():
    assert build_click_url({"asset_id": None, "click_url": "https://b/photos/orig"}, "https://b") == "https://b/photos/orig"
    assert build_click_url({"asset_id": None}, "https://b") == "https://b/"
    assert build_click_url({"asset_id": None}, "") is None


def test_web_mode_never_emits_app_scheme():
    n = {"asset_id": "a1", "app_click_url": "immich://album?id=x"}
    assert build_click_url(n, "https://b", "web") == "https://b/photos/a1"
    assert build_click_url({"asset_id": "a1", "click_url": "immich://memory?id=m"}, "https://b", "web") == "https://b/photos/a1"
