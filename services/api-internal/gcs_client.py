"""Per-thread GCS client cache for the roomstudio API ingester.

A single ingest request previously constructed one storage.Client per GCS
call: one for the bundle fetch, one per blob in the step-5 existence check
(fanned out over a ThreadPoolExecutor), and one per RGB frame in the step-5b
image validation — roughly 1+N+M client constructions for an N-blob/M-frame
bundle (~200 for a 50-keyframe capture). Each construction re-resolves
credentials and builds a new HTTP session.

This module caches one client PER THREAD instead. Per-thread rather than one
shared client because cross-thread safety of storage.Client's underlying
AuthorizedSession is not documented — only inferred from engineering
evidence (see requests issue psf/requests#2766) — and the existence/validity
checks run in worker threads.

google.cloud.storage is imported lazily so this module is safe to import in
test environments without the library installed; tests patch the callers
(_fetch_bundle_bytes, _blob_exists, _fetch_blob_header), never this module.

Consumers: ingest_server.py, blob_validator.py.
"""
from __future__ import annotations

import threading

_thread_local = threading.local()


def get_client():
    """Return this thread's cached GCS client, constructing it on first use."""
    client = getattr(_thread_local, "client", None)
    if client is None:
        from google.cloud import storage  # deferred

        client = storage.Client()
        _thread_local.client = client
    return client
