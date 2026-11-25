"""Shared fixtures: a fake `requests` layer so no test touches the network."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class FakeResponse:
    def __init__(self, payload=None, status_code=200, content=b"", headers=None, text=None):
        self._payload = payload
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}
        self.text = text if text is not None else (json.dumps(payload) if payload is not None else "")

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(f"{self.status_code} Client Error")

    def close(self):
        pass


@pytest.fixture
def fake_requests(monkeypatch):
    """Patch requests.get/post/put/delete inside notify.immich with a router keyed by (method, path-suffix).

    Usage: fake_requests.route("POST", "/api/search/statistics", lambda body: FakeResponse({...}))
    Handlers receive the JSON body (or None) and return a FakeResponse. The
    recorded calls are available in fake_requests.calls.
    """
    import notify.immich as immich

    class Router:
        def __init__(self):
            self.routes = {}
            self.calls = []

        def route(self, method, suffix, handler):
            self.routes[(method, suffix)] = handler

        def _dispatch(self, method, url, **kw):
            body = kw.get("json")
            params = kw.get("params")
            self.calls.append((method, url, body, params))
            for (m, suffix), handler in self.routes.items():
                if m == method and url.endswith(suffix):
                    try:
                        return handler(body, params)
                    except TypeError:
                        return handler(body)
            return FakeResponse({"message": "not routed"}, status_code=404)

    router = Router()
    monkeypatch.setattr(immich.requests, "get", lambda url, **kw: router._dispatch("GET", url, **kw))
    monkeypatch.setattr(immich.requests, "post", lambda url, **kw: router._dispatch("POST", url, **kw))
    monkeypatch.setattr(immich.requests, "put", lambda url, **kw: router._dispatch("PUT", url, **kw))
    monkeypatch.setattr(immich.requests, "delete", lambda url, **kw: router._dispatch("DELETE", url, **kw))
    immich._asset_details_cache.clear()
    return router


@pytest.fixture
def logger():
    return MagicMock()
