import base64

from notify import ntfy
from tests.conftest import FakeResponse


def test_sanitize_header_strips_control_chars():
    assert ntfy._sanitize_header("a\r\nb\x00c") == "abc"


def test_send_notification_headers(monkeypatch):
    captured = {}

    def fake_post(url, headers=None, data=None, auth=None, timeout=None):
        captured.update(url=url, headers=headers, data=data, auth=auth)
        return FakeResponse({}, 200)

    monkeypatch.setattr(ntfy.requests, "post", fake_post)
    assert ntfy.send_notification("http://n", "topic", "Héllo", "msg", click_url="https://x/1", priority="bogus", is_video=True)
    h = captured["headers"]
    assert h["Title"] == "=?UTF-8?B?" + base64.b64encode("Héllo".encode()).decode() + "?="
    assert h["Priority"] == "default"  # invalid priority falls back
    assert h["Tags"] == "movie,calendar"
    assert h["Click"] == "https://x/1"
    assert captured["url"] == "http://n/topic"
    assert captured["data"] == b"msg"


def test_send_notification_attaches_uploaded_image(monkeypatch):
    monkeypatch.setattr(ntfy, "upload_image_to_ntfy", lambda *a, **k: "https://n/file/abc.jpg")
    captured = {}
    monkeypatch.setattr(ntfy.requests, "post", lambda url, **kw: captured.update(kw) or FakeResponse({}, 200))
    ntfy.send_notification("http://n", "t", "T", "m", thumbnail_data=b"img", priority="high")
    assert captured["headers"]["Attach"] == "https://n/file/abc.jpg"
    assert captured["headers"]["Priority"] == "high"


def test_upload_image_returns_none_on_rejection(monkeypatch):
    monkeypatch.setattr(ntfy.requests, "put", lambda *a, **k: FakeResponse(None, 403, text="attachments not allowed"))
    assert ntfy.upload_image_to_ntfy("http://n", b"x") is None
