import pytest

from dashboard.routers.secrets import _sanitize_env_value, mask_secret
from dashboard.utils.envfile import parse_env_line, unquote_env_value


@pytest.mark.parametrize("value", ["plain", "pa$s word", 'with "quotes"', "back\\slash", "tick`s", "hash#tag", "a'b"])
def test_env_value_round_trip(value):
    line = f"KEY={_sanitize_env_value(value)}"
    assert parse_env_line(line) == ("KEY", value)


def test_parse_env_line_skips_comments_and_blanks():
    assert parse_env_line("# comment") is None
    assert parse_env_line("   ") is None
    assert parse_env_line("novalue") is None
    assert parse_env_line("K='single'") == ("K", "single")
    assert unquote_env_value("  x  ") == "x"


def test_sanitize_strips_newlines():
    assert "\n" not in _sanitize_env_value("a\nb")


def test_mask_secret():
    assert mask_secret("") == ""
    assert mask_secret("short") == "********"
    assert mask_secret("abcdefghijkl") == "********ijkl"
