import yaml

from dashboard.crontab import DEFAULT_CONFIG
from dashboard.models import FullConfig, MessagesUpdate, Settings, SettingsUpdate
from dashboard.routers.settings import build_settings_model
from notify import config as cfg
from notify.defaults import DEFAULT_SETTINGS, DEFAULT_TEMPLATES, apply_template_defaults, build_default_config


def test_settings_model_fields_match_defaults_exactly():
    assert set(Settings.model_fields) == set(DEFAULT_SETTINGS)
    # Every tunable (except the engine-only paths/windows) must be patchable from the dashboard
    engine_only = {"retry", "state_file", "log_level", "notification_windows"}
    assert set(SettingsUpdate.model_fields) == set(DEFAULT_SETTINGS) - engine_only


def test_template_lists_match_models():
    assert set(MessagesUpdate.model_fields) == set(DEFAULT_TEMPLATES)
    assert set(FullConfig.model_fields) == set(DEFAULT_TEMPLATES) | {"settings", "users"}


def test_default_config_validates_and_survives_yaml():
    c = build_default_config()
    dumped = yaml.safe_dump(c, allow_unicode=True, sort_keys=False)
    assert yaml.safe_load(dumped) == c
    model = build_settings_model(c["settings"])
    assert model.collage_template == "random"
    assert len(model.notification_windows) == 5
    assert DEFAULT_CONFIG["settings"] == DEFAULT_SETTINGS


def test_build_settings_model_merges_and_ignores_unknown_keys():
    m = build_settings_model({"top_persons_limit": 9, "collage_year_range": 12, "bogus": 1})
    assert m.top_persons_limit == 9
    assert m.year_range == 12
    assert m.weekly_collage_enabled == DEFAULT_SETTINGS["weekly_collage_enabled"]


def test_defaults_are_not_shared_mutable_objects():
    a, b = build_default_config(), build_default_config()
    a["settings"]["notification_windows"][0]["events"].append("x")
    assert "x" not in b["settings"]["notification_windows"][0]["events"]
    assert "x" not in DEFAULT_SETTINGS["notification_windows"][0]["events"]


def test_template_defaults_respect_explicit_empty_list():
    c = {"messages": []}
    apply_template_defaults(c)
    assert c["messages"] == []
    assert c["person_messages"] == DEFAULT_TEMPLATES["person_messages"]


def test_load_config_fills_templates_and_all_settings(tmp_path):
    path = tmp_path / "c.yaml"
    path.write_text("immich: {url: x}\nusers: []\n")
    c = cfg.load_config(str(path))
    assert set(DEFAULT_SETTINGS) <= set(c["settings"])
    assert c["memory_titles"] == DEFAULT_TEMPLATES["memory_titles"]
