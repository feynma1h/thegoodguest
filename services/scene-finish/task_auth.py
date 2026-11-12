"""The app-side check on scene-finish's Cloud Tasks routes.

The platform gates the whole service (only tasks-invoker@ holds run.invoker,
the posture decision 0106 set for perception-obj). This is the second lock
perception-obj also keeps (services/perception-obj/oidc.py): the OIDC token's
audience must be this service's own URL plus the route, so a token minted for
another route or service cannot be replayed here, and its email must be the
invoker's.

With RECEIVER_URL or CLOUD_TASKS_INVOKER_SA unset the check is off — local
development — except under ENVIRONMENT=production, where the missing setting is
an error at first use, so a deploy that forgot one fails loudly instead of
running unchecked.

Read by: finish_server.py (builds the /still route's authorize).
"""

from __future__ import annotations

import os
from collections.abc import Callable

from fastapi import HTTPException, Request

Authorize = Callable[[Request, str], None]


def no_check(request: Request, path: str) -> None:  # noqa: ARG001
    """Local development: no task queue, no token."""


class OidcAuthorizer:
    def __init__(self, receiver_url: str, invoker_sa: str, verify: Callable[[str, str], dict] | None = None):
        self._receiver = receiver_url.rstrip("/")
        self._invoker = invoker_sa
        self._verify = verify or _verify_google

    def __call__(self, request: Request, path: str) -> None:
        scheme, _, token = (request.headers.get("Authorization") or "").partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            raise HTTPException(status_code=401, detail="missing bearer token")
        try:
            claims = self._verify(token.strip(), self._receiver + path)
        except ValueError as e:
            raise HTTPException(status_code=401, detail=f"invalid token: {e}") from None
        if claims.get("email") != self._invoker:
            raise HTTPException(status_code=401, detail="token is not the task invoker's")


def _verify_google(token: str, audience: str) -> dict:
    from google.auth.transport import requests as grequests
    from google.oauth2 import id_token

    return id_token.verify_oauth2_token(token, grequests.Request(), audience=audience)


def authorizer_from_env() -> Authorize:
    receiver = os.environ.get("RECEIVER_URL", "")
    invoker = os.environ.get("CLOUD_TASKS_INVOKER_SA", "")
    if receiver and invoker:
        return OidcAuthorizer(receiver, invoker)
    if os.environ.get("ENVIRONMENT") == "production":
        raise RuntimeError("RECEIVER_URL and CLOUD_TASKS_INVOKER_SA must both be set in production")
    return no_check
