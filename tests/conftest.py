"""Safety boundaries shared by the standard test suite."""

from __future__ import annotations

import socket

import pytest
import requests


class _FakeMetaResponse:
    status_code = 200
    headers: dict = {}
    text = ""

    @staticmethod
    def json():
        return {"messages": [{"id": "test-message-id"}]}


class _FakeRequests:
    exceptions = requests.exceptions

    def __init__(self):
        self.calls: list[dict] = []

    def post(self, url, **kwargs):
        self.calls.append({"method": "POST", "url": url})
        return _FakeMetaResponse()


@pytest.fixture(autouse=True)
def block_real_network_and_meta(monkeypatch):
    """Fail closed on sockets and inject an in-memory HTTP boundary for Meta."""
    import api_whatsapp

    fake_requests = _FakeRequests()

    def blocked_connection(*args, **kwargs):
        raise AssertionError("A suite padrao nao permite acesso a rede real")

    monkeypatch.setattr(api_whatsapp, "_requests_module", lambda: fake_requests)
    monkeypatch.setattr(socket, "create_connection", blocked_connection)
    monkeypatch.setattr(socket.socket, "connect", blocked_connection)
    yield fake_requests
