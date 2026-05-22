"""OIDC token verification for Cloud Tasks-delivered requests.

Cloud Tasks attaches an OIDC token on the Authorization header when the
task is created with `oidc_token.service_account_email` set (see
services/api/dispatcher.py — this field is the known gap patched in
commit 5). The receiver verifies the token before doing any work.

Two claims are checked:
  - audience (aud): must equal the receiver's own URL. Prevents tokens
    minted for other services from being replayed against this endpoint.
  - email: must equal the configured invoker service-account email
    (CLOUD_TASKS_INVOKER_SA env var). Prevents tokens from any other
    service account from being accepted.

google.oauth2.id_token.verify_oauth2_token is used for verification.
The google-auth library is already available in the runtime environment.

OIDCVerifier.verify() is called once per /process request before any
state is read or mutated.

Consumers: process_receiver.py (POST /process route).
"""
from __future__ import annotations

import os
from typing import Optional

# google-auth is always available in the runtime environment (it is a
# transitive dependency of google-cloud-storage, which is already required).
# Import at module level so tests can patch via
#   patch("google.oauth2.id_token.verify_oauth2_token", ...)
from google.auth.transport import requests as _grequests
from google.oauth2 import id_token as _id_token


class OIDCError(Exception):
    """OIDC token verification failed.

    Attributes
    ----------
    code:   machine-readable error code, one of:
                missing_token, invalid_token, wrong_audience, wrong_email
    detail: human-readable explanation
    """

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(detail)


class OIDCVerifier:
    """Verifies Cloud Tasks OIDC tokens.

    Parameters
    ----------
    audience:      the full HTTPS URL of this receiver endpoint
                   (e.g. https://perception-obj-xxx.run.app/process).
                   Must match the `aud` claim in the token.
    allowed_email: the Cloud Tasks invoker service-account email
                   (sourced from CLOUD_TASKS_INVOKER_SA). Must match the
                   `email` claim in the token.

    Usage::

        verifier = OIDCVerifier(
            audience=os.environ["RECEIVER_URL"] + "/process",
            allowed_email=os.environ["CLOUD_TASKS_INVOKER_SA"],
        )
        verifier.verify(request.headers.get("Authorization"))
    """

    def __init__(self, *, audience: str, allowed_email: str) -> None:
        self._audience = audience
        self._allowed_email = allowed_email

    def verify(self, authorization_header: Optional[str]) -> None:
        """Verify the Authorization header value from a Cloud Tasks request.

        Raises OIDCError on any failure. Returns None on success.

        Parameters
        ----------
        authorization_header:
            The raw value of the Authorization header, e.g.
            "Bearer eyJ...". Pass None (or the header's absence) to trigger
            a missing_token error.
        """
        if not authorization_header:
            raise OIDCError(
                code="missing_token",
                detail="Authorization header is absent",
            )

        parts = authorization_header.strip().split(" ", 1)
        if len(parts) != 2 or parts[0].lower() != "bearer":
            raise OIDCError(
                code="missing_token",
                detail="Authorization header must be 'Bearer <token>'",
            )
        token = parts[1]

        try:
            id_info = _id_token.verify_oauth2_token(
                token,
                _grequests.Request(),
                audience=self._audience,
            )
        except ValueError as exc:
            raise OIDCError(
                code="invalid_token",
                detail=str(exc),
            ) from exc

        if id_info.get("email") != self._allowed_email:
            raise OIDCError(
                code="wrong_email",
                detail=(
                    f"Token email {id_info.get('email')!r} does not match "
                    f"expected {self._allowed_email!r}"
                ),
            )
