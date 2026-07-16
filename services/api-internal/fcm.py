"""FCM notifications for the roomstudio API ingester.

Sends push notifications to the iOS client when an upload is incomplete
(some referenced blobs are absent at ingest time). The iOS client uses the
notification to surface an error and prompt re-upload.

FCM failures are log-and-continue: a notification failure must not prevent
the Scene's Firestore record from being updated, and must not cause the
Eventarc handler to return an error status. The worst case is a silent
failure; the client can still poll.

firebase-admin is imported lazily so this module is safe to import in tests
without the library installed or Firebase credentials configured.

NullFcmNotifier is used in tests; FirebaseFcmNotifier is used in production.

Consumers: ingest_server.py (_handle_failed_incomplete, the existence-check
failure path).
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class FcmNotifier(ABC):
    """Interface for upload-related FCM push notifications."""

    @abstractmethod
    def notify_upload_incomplete(
        self, *, fcm_token: str, scene_id: str, missing_paths: list[str]
    ) -> None:
        """Notify the client that the capture upload is incomplete.

        fcm_token: FCM registration token from the upload_session record.
        scene_id:  The Scene that reached failed_incomplete.
        missing_paths: Relative paths that were absent at existence-check time.
        """


class NullFcmNotifier(FcmNotifier):
    """No-op notifier. For tests and local dev."""

    def notify_upload_incomplete(
        self, *, fcm_token: str, scene_id: str, missing_paths: list[str]
    ) -> None:
        logger.debug(
            "NullFcmNotifier.notify_upload_incomplete scene_id=%s token=%s paths=%s",
            scene_id,
            fcm_token,
            missing_paths,
        )


class FirebaseFcmNotifier(FcmNotifier):
    """Firebase Cloud Messaging notifier (production).

    Sends a data-only FCM message so the iOS app can handle it in the
    background without the OS showing a system notification UI. The payload
    carries scene_id, status, and a comma-separated list of missing paths so
    the iOS client can surface a diagnostic and re-upload the right files.

    The app is initialized from ADC; if firebase-admin was already initialized
    the existing app is reused. (Nothing else in api-internal initializes
    firebase_admin — the service is Cloud Run IAM-gated, not Firebase-JWT
    verified — so the reuse branch is defensive only.)

    firebase-admin is imported lazily.
    """

    def __init__(self) -> None:
        import firebase_admin  # deferred: not installed in tests

        try:
            firebase_admin.get_app()
        except ValueError:
            firebase_admin.initialize_app()
        import firebase_admin.messaging as _msg  # deferred

        self._messaging = _msg

    def notify_upload_incomplete(
        self, *, fcm_token: str, scene_id: str, missing_paths: list[str]
    ) -> None:
        self._send(
            token=fcm_token,
            data={
                "scene_id": scene_id,
                "status": "failed_incomplete",
                "missing_paths": ",".join(missing_paths)[:500],  # trim to avoid oversized payload
            },
        )

    def _send(self, *, token: str, data: dict) -> None:
        try:
            msg = self._messaging.Message(
                token=token,
                data={k: str(v) for k, v in data.items()},
            )
            self._messaging.send(msg)
            logger.info("FCM sent: token=...%s status=%s", token[-6:], data.get("status"))
        except Exception as exc:
            logger.warning(
                "FCM send failed (continuing): status=%s error=%s",
                data.get("status"),
                exc,
            )
