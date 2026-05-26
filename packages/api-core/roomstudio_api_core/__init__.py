"""roomstudio-api-core — shared logic for api-public and api-internal.

Exposes the upload session repository (Firestore-backed and in-memory
implementations) and the GCS resumable URI minting helper. Both API
services depend on this package; neither service owns it.

Consumers: services/api-public (upload_session route), services/api-internal
(_handle_failed_incomplete FCM token lookup).
"""
