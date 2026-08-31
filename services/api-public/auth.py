"""Firebase ID token verification for the thegoodguest public API.

TokenVerifier interface with two implementations:
  NullTokenVerifier    — for tests; accepts tokens of the form "test-uid:<uid>"
  FirebaseTokenVerifier — production; verifies Firebase ID tokens via firebase-admin

firebase-admin is imported lazily so this module is safe to import in tests
without the library installed or Firebase credentials configured.

Consumers: public_server.py — every Firebase-authenticated route, via
_verify_bearer.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class TokenVerificationError(Exception):
    """Raised when a token cannot be verified (expired, invalid, malformed)."""


class TokenVerifier(ABC):
    """Interface for Firebase ID token verification."""

    @abstractmethod
    def verify(self, token: str) -> str:
        """Verify the token and return the Firebase UID.

        Raises TokenVerificationError if the token is invalid or expired.
        """


class FirebaseTokenVerifier(TokenVerifier):
    """Production verifier backed by firebase-admin.

    Initializes the default Firebase app from Application Default Credentials
    on first instantiation (Cloud Run ADC).  If the app is already initialized,
    reuses it. (DELETE /account also initializes firebase_admin — see
    public_server._get_account_deleter — so whichever path runs first wins and
    the reuse branch is genuinely reached, not merely defensive.)

    firebase-admin is imported lazily so importing this module in tests is safe.
    """

    def __init__(self) -> None:
        import firebase_admin  # deferred: not installed in tests

        try:
            firebase_admin.get_app()
        except ValueError:
            firebase_admin.initialize_app()

    def verify(self, token: str) -> str:
        import firebase_admin.auth as _auth  # deferred

        try:
            decoded = _auth.verify_id_token(token)
            return decoded["uid"]
        except Exception as exc:
            raise TokenVerificationError(str(exc)) from exc


class NullTokenVerifier(TokenVerifier):
    """Test verifier. Accepts tokens of the form "test-uid:<uid>".

    Any other token raises TokenVerificationError, making invalid-token
    tests work without mocking firebase-admin internals.
    """

    _PREFIX = "test-uid:"

    def verify(self, token: str) -> str:
        if token.startswith(self._PREFIX):
            return token[len(self._PREFIX):]
        raise TokenVerificationError(
            f"NullTokenVerifier: expected '{self._PREFIX}<uid>', got {token!r}"
        )
