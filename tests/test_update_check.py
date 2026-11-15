from notify.update_check import parse_version


def test_parse_version_orders_semver():
    assert parse_version("v3.3.0") == (3, 3, 0)
    assert parse_version("3.10.1") > parse_version("3.9.9")
    assert parse_version("1.2.x") == (1, 2, 0)
