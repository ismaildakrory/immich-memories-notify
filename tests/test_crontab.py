import yaml

from dashboard import crontab


def test_generate_crontab_writes_slots_updates_and_catch_up(tmp_path, monkeypatch):
    monkeypatch.setattr(crontab, "ENV_FILE", str(tmp_path / "cron.env"))
    monkeypatch.setenv("ENV_PATH", str(tmp_path / "missing.env"))
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.safe_dump({"settings": {"notification_windows": [
        {"start": "08:30", "end": "09:00"}, {"start": "21:05", "end": "22:00"}]}}))
    out = crontab.generate_crontab(str(cfg), crontab_path=str(tmp_path / "crontab"))
    lines = open(out).read().strip().splitlines()
    assert lines[0].startswith("30 8 * * * ") and lines[0].endswith("python -m notify --slot 1")
    assert lines[1].startswith("5 21 * * * ") and lines[1].endswith("python -m notify --slot 2")
    assert any("--check-updates" in line for line in lines)
    assert lines[-1].startswith("*/10 * * * * ") and lines[-1].endswith("--catch-up")
    assert "/proc/1/fd/1" not in open(out).read()  # supercronic captures output itself
    assert (tmp_path / "cron.env").exists()


def test_ensure_config_writes_defaults_for_empty_file(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("")
    crontab.ensure_config(str(cfg))
    data = yaml.safe_load(cfg.read_text())
    assert data["users"] == []
    assert data["settings"]["collage_template"] == "random"
    # existing content is left alone
    cfg.write_text("users: [{name: X}]\n")
    crontab.ensure_config(str(cfg))
    assert yaml.safe_load(cfg.read_text())["users"][0]["name"] == "X"
