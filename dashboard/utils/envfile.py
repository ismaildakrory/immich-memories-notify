"""Shared .env value parsing — exact inverse of secrets._sanitize_env_value.

The writer wraps values containing special characters in double quotes and
backslash-escapes \\ " $ ` inside them. Every reader must undo that, otherwise
secrets with those characters come back corrupted (e.g. pa$s -> pa\$s).
"""

import re


def unquote_env_value(value: str) -> str:
    """Strip surrounding quotes and undo backslash escapes from a .env value."""
    value = value.strip()
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return re.sub(r'\\(.)', r'\1', value[1:-1])
    if len(value) >= 2 and value[0] == "'" and value[-1] == "'":
        return value[1:-1]
    return value


def parse_env_line(line: str) -> tuple | None:
    """Parse one .env line into (key, value), or None for comments/blanks."""
    line = line.strip()
    if not line or line.startswith('#') or '=' not in line:
        return None
    key, _, raw = line.partition('=')
    return key.strip(), unquote_env_value(raw)
