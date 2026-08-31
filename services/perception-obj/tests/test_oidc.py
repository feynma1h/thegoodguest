"""Unit tests for OIDCVerifier.

Tests cover the one success path and the four ways OIDCVerifier.verify raises:
  - valid token   → no exception
  - wrong aud     → OIDCError(invalid_token)  [verify_oauth2_token raises ValueError]
  - wrong email   → OIDCError(wrong_email)
  - missing token → OIDCError(missing_token)
  - expired token → OIDCError(invalid_token)  [verify_oauth2_token raises ValueError]

google.oauth2.id_token.verify_oauth2_token is patched in all tests so no
network calls are made and no real tokens are needed.

Run from repo root:
  pytest services/perception-obj/tests/test_oidc.py -v
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from oidc import OIDCError, OIDCVerifier

_AUDIENCE      = "https://perception-obj-xxx.run.app/process"
_ALLOWED_EMAIL = "cloud-tasks-invoker@thegoodguest-prod.iam.gserviceaccount.com"
_VALID_HEADER  = "Bearer eyJfake.token.here"


def _verifier() -> OIDCVerifier:
    return OIDCVerifier(audience=_AUDIENCE, allowed_email=_ALLOWED_EMAIL)


def _mock_verify(return_value: dict):
    """Patch verify_oauth2_token to return the given id_info dict."""
    return patch(
        "google.oauth2.id_token.verify_oauth2_token",
        return_value=return_value,
    )


def _mock_verify_raises(exc: Exception):
    """Patch verify_oauth2_token to raise exc."""
    return patch(
        "google.oauth2.id_token.verify_oauth2_token",
        side_effect=exc,
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

class TestValidToken:
    def test_valid_token_does_not_raise(self):
        with _mock_verify({"email": _ALLOWED_EMAIL, "aud": _AUDIENCE}):
            _verifier().verify(_VALID_HEADER)  # must not raise

    def test_verify_called_with_correct_audience(self):
        with patch("google.oauth2.id_token.verify_oauth2_token", return_value={"email": _ALLOWED_EMAIL}) as mock_fn:
            _verifier().verify(_VALID_HEADER)
        _token = mock_fn.call_args[0][0]
        _aud   = mock_fn.call_args[1]["audience"]
        assert _token == "eyJfake.token.here"
        assert _aud   == _AUDIENCE


# ---------------------------------------------------------------------------
# Missing / malformed header
# ---------------------------------------------------------------------------

class TestMissingToken:
    def test_none_header_raises_missing_token(self):
        with pytest.raises(OIDCError) as exc_info:
            _verifier().verify(None)
        assert exc_info.value.code == "missing_token"

    def test_empty_string_raises_missing_token(self):
        with pytest.raises(OIDCError) as exc_info:
            _verifier().verify("")
        assert exc_info.value.code == "missing_token"

    def test_non_bearer_scheme_raises_missing_token(self):
        with pytest.raises(OIDCError) as exc_info:
            _verifier().verify("Basic dXNlcjpwYXNz")
        assert exc_info.value.code == "missing_token"


# ---------------------------------------------------------------------------
# Wrong audience
# ---------------------------------------------------------------------------

class TestWrongAudience:
    def test_wrong_aud_returns_invalid_token(self):
        """verify_oauth2_token raises ValueError for audience mismatch."""
        with _mock_verify_raises(ValueError("Token audience mismatch")):
            with pytest.raises(OIDCError) as exc_info:
                _verifier().verify(_VALID_HEADER)
        assert exc_info.value.code == "invalid_token"
        assert "Token audience mismatch" in exc_info.value.detail


# ---------------------------------------------------------------------------
# Wrong email
# ---------------------------------------------------------------------------

class TestWrongEmail:
    def test_wrong_email_raises_wrong_email(self):
        with _mock_verify({"email": "not-the-right-sa@other.iam.gserviceaccount.com"}):
            with pytest.raises(OIDCError) as exc_info:
                _verifier().verify(_VALID_HEADER)
        assert exc_info.value.code == "wrong_email"

    def test_error_detail_names_the_email(self):
        bad_email = "intruder@other.iam.gserviceaccount.com"
        with _mock_verify({"email": bad_email}):
            with pytest.raises(OIDCError) as exc_info:
                _verifier().verify(_VALID_HEADER)
        assert bad_email in exc_info.value.detail

    def test_missing_email_claim_raises_wrong_email(self):
        """Token without email claim (e.g. service account token missing scope)."""
        with _mock_verify({}):  # no email key
            with pytest.raises(OIDCError) as exc_info:
                _verifier().verify(_VALID_HEADER)
        assert exc_info.value.code == "wrong_email"


# ---------------------------------------------------------------------------
# Expired token
# ---------------------------------------------------------------------------

class TestExpiredToken:
    def test_expired_token_raises_invalid_token(self):
        with _mock_verify_raises(ValueError("Token expired")):
            with pytest.raises(OIDCError) as exc_info:
                _verifier().verify(_VALID_HEADER)
        assert exc_info.value.code == "invalid_token"
        assert "Token expired" in exc_info.value.detail
