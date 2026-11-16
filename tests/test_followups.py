from unittest.mock import MagicMock

from notify import update_check
from notify.features import collage, then_and_now
from notify.utils import fix_plurals


def test_fix_plurals():
    assert fix_plurals("1 years ago today") == "1 year ago today"
    assert fix_plurals("A cozy memory from 1 years ago") == "A cozy memory from 1 year ago"
    assert fix_plurals("11 years ago") == "11 years ago"
    assert fix_plurals("2 years between") == "2 years between"
    assert fix_plurals("1 memories") == "1 memory"
    assert fix_plurals("") == ""


def test_then_and_now_skips_upload_when_disabled(monkeypatch):
    monkeypatch.setattr(then_and_now, "fetch_thumbnail", lambda *a, **k: _jpeg())
    monkeypatch.setattr(then_and_now, "create_then_and_now_image", lambda **k: b"composite")
    uploads = MagicMock()
    monkeypatch.setattr(then_and_now, "get_or_create_album", uploads)
    monkeypatch.setattr(then_and_now, "upload_collage_to_album", uploads)
    cand = {"then_asset_id": "a", "now_asset_id": "b", "then_faces": [], "now_faces": [],
            "then_year": 2015, "now_year": 2016, "gap": 1, "person_name": "P", "person_id": "p"}
    n = then_and_now.prepare_then_and_now_notification(cand, "u", "k", ["{gap} years apart"], True, upload=False)
    assert n["asset_id"] is None and n["composite_image"] == b"composite"
    assert n["message"] == "1 year apart"
    uploads.assert_not_called()


def test_collage_skips_upload_when_disabled(monkeypatch):
    monkeypatch.setattr(collage, "get_top_persons", lambda *a, **k: [{"id": "p", "name": "P", "asset_count": 1}])
    monkeypatch.setattr(collage, "get_random_person_photo", lambda **k: {"asset": {"id": "x"}, "person_name": "P", "person_id": "p"})
    monkeypatch.setattr(collage, "fetch_thumbnail", lambda *a, **k: _jpeg())
    monkeypatch.setattr(collage, "create_collage_image", lambda **k: b"collage")
    monkeypatch.setattr(collage, "COLLAGE_TEMPLATES", {"grid_custom": object()})
    monkeypatch.setattr(collage, "get_template_photo_count", lambda *a: 1)
    uploads = MagicMock()
    monkeypatch.setattr(collage, "get_or_create_album", uploads)
    n = collage.generate_weekly_collage({"name": "U", "immich_api_key": "k"}, {"immich": {"url": "u"}}, None,
                                        {"collage_template": "grid_custom"}, MagicMock(), test_mode=True, upload=False)
    assert n["asset_id"] is None and n["collage_data"] == b"collage"
    uploads.assert_not_called()


def test_update_check_uses_dispatcher(monkeypatch, tmp_path):
    cfg = tmp_path / "c.yaml"
    cfg.write_text("immich: {url: u}\nntfy: {url: n}\nusers:\n- {name: A, immich_api_key: k, notification_service: apprise, apprise_url: 'json://x'}\n"
                   f"settings: {{state_file: '{tmp_path}/s.json'}}\n")
    monkeypatch.setattr(update_check, "get_current_version", lambda: "1.0.0")
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"tag_name": "v9.9.9", "name": "Big"}
    monkeypatch.setattr(update_check.requests, "get", lambda *a, **k: resp)
    sent = {}

    def fake_send(user, notification, config, logger, thumbnail_override=None):
        sent.update(user=user["name"], **notification)
        return True

    monkeypatch.setattr(update_check, "send_notification", fake_send)
    update_check.check_for_updates(str(cfg), logger=MagicMock())
    assert sent["user"] == "A" and "v9.9.9" in sent["title"] and sent["tags"] == "arrow_up,package"
    # second run: already notified, no resend
    sent.clear()
    update_check.check_for_updates(str(cfg), logger=MagicMock())
    assert not sent


def _jpeg():
    import io

    from PIL import Image

    b = io.BytesIO()
    Image.new("RGB", (4, 4)).save(b, "JPEG")
    return b.getvalue()
