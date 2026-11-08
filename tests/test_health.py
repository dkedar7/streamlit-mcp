"""HTTP/SSE liveness endpoint (#197): reachable without the bearer token, reveals nothing."""

from __future__ import annotations

from pathlib import Path

import pytest

APP = str(Path(__file__).parent / "apps" / "sample_app.py")


def _client(transport, token=None):
    from starlette.testclient import TestClient

    from streamlit_mcp.guardrails import Guardrails
    from streamlit_mcp.server import bearer_auth, build_server
    guard = Guardrails(bearer_token=token) if token else None
    mcp = build_server(APP, guard=guard, auth=bearer_auth(guard))
    return TestClient(mcp.http_app(transport=transport))


@pytest.mark.parametrize("transport", ["http", "sse"])
@pytest.mark.parametrize("token", [None, "SEKRET"])
@pytest.mark.parametrize("path", ["/health", "/healthz"])
def test_health_answers_without_a_token(transport, token, path):
    with _client(transport, token) as client:
        r = client.get(path)
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "server": "streamlit-mcp"}


def test_health_reveals_nothing_a_token_protects():
    with _client("http", "SEKRET") as client:
        body = client.get("/health").text
    assert "SEKRET" not in body and "sample_app" not in body and "version" not in body


def test_the_mcp_endpoint_still_requires_the_token():
    """Mounting /health must not open the MCP endpoint itself."""
    body = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                       "clientInfo": {"name": "t", "version": "0"}}}
    hdr = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    with _client("http", "SEKRET") as client:
        assert client.post("/mcp", json=body, headers=hdr).status_code == 401
