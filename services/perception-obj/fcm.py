"""FCM notifications for terminal Scene state transitions.

Fires a data-only FCM message to the device that owns a scene when the scene
reaches a terminal state (ready or failed). The iOS client receives this and
updates its local state without polling.

FCM failures are log-and-continue per 0004: a notification failure must not
prevent the Scene's Firestore record from being updated, and must not cause
Cloud Tasks to retry the task. The worst case is a silent push that never
arrives; the iOS client can always poll GET /scenes/{scene_id}.

firebase-admin is imported lazily so this module is safe to import in tests
without the library installed or Firebase credentials configured.

NullFcmNotifier is used in tests; FirebaseFcmNotifier is used in production.

Consumers: process_receiver.py (POST /process terminal transitions).
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class FcmNotifier(ABC):
    """Interface for FCM push notifications."""

    @abstractmethod
    def notify_ready(self, *, device_id: str, scene_id: str) -> None:
        """Notify device_id that scene_id has reached the ready state."""

    @abstractmethod
    def notify_failed(self, *, device_id: str, scene_id: str, reason: str) -> None:
        """Notify device_id that scene_id has reached the failed state."""


class NullFcmNotifier(FcmNotifier):
    """No-op notifier. For tests and local dev."""

    def notify_ready(self, *, device_id: str, scene_id: str) -> None:
        logger.debug("NullFcmNotifier.notify_ready scene_id=%s device_id=%s", scene_id, device_id)

    def notify_failed(self, *, device_id: str, scene_id: str, reason: str) -> None:
        logger.debug(
            "NullFcmNotifier.notify_failed scene_id=%s device_id=%s reason=%s",
            scene_id, device_id, reason,
        )


class FirebaseFcmNotifier(FcmNotifier):
    """Firebase Cloud Messaging notifier (production).

    Sends a data-only message so the iOS app can handle it in the background
    without the system showing a system notification UI. The app reads
    scene_id and status and refreshes its local cache.

    device_id is used as the FCM registration token. This works when the iOS
    app stores the FCM registration token under the device_id key in
    Firestore — that contract is a future concern; for now device_id is
    treated as the FCM token directly.

    firebase-admin is imported lazily; the app must be initialized before
    FirebaseFcmNotifier is instantiated. In Cloud Run, initialization happens
    via the application-default credentials (ADC).
    """

    def __init__(self) -> None:
        import firebase_admin  # deferred: not installed in tests
        from firebase_admin import messaging as _msg
        # Initialize the default app if not already done.
        try:
            firebase_admin.get_app()
        except ValueError:
            firebase_admin.initialize_app()
        self._messaging = _msg

    def notify_ready(self, *, device_id: str, scene_id: str) -> None:
        self._send(device_id=device_id, data={
            "scene_id": scene_id,
            "status": "ready",
        })

    def notify_failed(self, *, device_id: str, scene_id: str, reason: str) -> None:
        self._send(device_id=device_id, data={
            "scene_id": scene_id,
            "status": "failed",
            "reason": reason[:200],  # trim to avoid oversized payloads
        })

    def _send(self, *, device_id: str, data: dict) -> None:
        """Send a data message. Logs and continues on any failure."""
        try:
            msg = self._messaging.Message(
                token=device_id,
                data={k: str(v) for k, v in data.items()},
            )
            self._messaging.send(msg)
            logger.info(
                "FCM sent: device_id=%s status=%s", device_id, data.get("status")
            )
        except Exception as exc:
            # FCM failures are log-and-continue per 0004. A notification failure
            # must not prevent the Firestore update or cause a retry.
            logger.warning(
                "FCM send failed (continuing): device_id=%s status=%s error=%s",
                device_id, data.get("status"), exc,
            )
