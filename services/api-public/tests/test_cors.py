"""Tests for the CORS_ALLOWED_ORIGINS-gated CORS middleware.

The middleware is attached at module import time (FastAPI middleware
cannot be added after startup), so the enabled-path tests reload
public_server with the env var set and restore the clean module state
afterwards — importlib.reload mutates the module object in place, keeping
every other test module's `import public_server as server` reference
valid.

Covers:
  - default (env unset): no CORS headers on responses
  - enabled: preflight OPTIONS gets the allowed origin echoed, and
    Authorization is an allowed request header
  - enabled: a non-allowlisted origin gets no allow-origin header

Run from repo root:
  pytest services/api-public/tests/test_cors.py -v
"""
from __future__ import annotations

import importlib
import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import public_server


@pytest.fixture()
def cors_app():
    """Reload public_server with CORS enabled; restore the clean module."""
    with patch.dict(os.environ, {"CORS_ALLOWED_ORIGINS": "http://localhost:3000"}):
        importlib.reload(public_server)
        yield public_server.app
    importlib.reload(public_server)


def test_cors_disabled_by_default():
    assert not os.environ.get("CORS_ALLOWED_ORIGINS")
    client = TestClient(public_server.app)
    resp = client.get("/health", headers={"Origin": "http://localhost:3000"})
    assert resp.status_code == 200
    assert "access-control-allow-origin" not in resp.headers


def test_preflight_allows_configured_origin(cors_app):
    client = TestClient(cors_app)
    resp = client.options(
        "/scenes",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "authorization" in resp.headers["access-control-allow-headers"].lower()


def test_simple_request_gets_allow_origin(cors_app):
    client = TestClient(cors_app)
    resp = client.get("/health", headers={"Origin": "http://localhost:3000"})
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_unlisted_origin_gets_no_allow_origin(cors_app):
    client = TestClient(cors_app)
    resp = client.get("/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in resp.headers
