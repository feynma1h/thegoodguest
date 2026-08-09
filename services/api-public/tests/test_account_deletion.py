"""Pins for account deletion (decision 0095).

Two things are being pinned, and they fail differently:

  1. COMPLETENESS — the plan names every per-user collection and prefix. The
     failure mode is silent: data survives a deletion the user was told
     finished. `test_deletion_covers_every_collection_the_source_declares`
     DISCOVERS the collection names from the service source, so a collection
     introduced anywhere else breaks a test rather than a promise.

  2. ORDERING — GCS before Firestore, identity last. This is invisible to the
     planner and only observable through the executor, so the fakes below
     record a global operation log and the tests assert on its shape.

The fakes emulate only the surface account_deletion.py actually touches.
Firestore's real FieldFilter is used (the library is a transitive dependency)
so a query built the wrong way fails here rather than in production.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import public_server
from account_deletion import (
    CONVERSATION_TURNS_SUBCOLLECTION,
    CONVERSATIONS_COLLECTION,
    DESIGN_SPECS_COLLECTION,
    MINT_QUOTAS_COLLECTION,
    SCENES_COLLECTION,
    UPLOAD_SESSIONS_COLLECTION,
    AccountDeleter,
    OwnedRecords,
    plan_account_deletion,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class FakeDoc:
    def __init__(self, doc_id: str, data: dict, ref=None):
        self.id = doc_id
        self._data = data
        self.reference = ref

    def to_dict(self):
        return dict(self._data)


class FakeDocRef:
    def __init__(self, db, collection: str, doc_id: str):
        self._db, self._collection, self._id = db, collection, doc_id

    def collection(self, name: str):
        return FakeCollection(self._db, f"{self._collection}/{self._id}/{name}")

    def delete(self):
        self._db.log.append(("fs_delete", self._collection, self._id))
        self._db.data.get(self._collection, {}).pop(self._id, None)


class FakeQuery:
    def __init__(self, db, collection: str, predicate=None):
        self._db, self._collection, self._predicate = db, collection, predicate

    def where(self, *, filter):  # noqa: A002 — matches the firestore kwarg
        return FakeQuery(
            self._db,
            self._collection,
            lambda d: d.get(filter.field_path) == filter.value,
        )

    def limit(self, n: int):
        q = FakeQuery(self._db, self._collection, self._predicate)
        q._limit = n
        return q

    def stream(self):
        items = self._db.data.get(self._collection, {})
        out = [
            FakeDoc(k, v, FakeDocRef(self._db, self._collection, k))
            for k, v in sorted(items.items())
            if self._predicate is None or self._predicate(v)
        ]
        return out[: getattr(self, "_limit", len(out))]


class FakeCollection(FakeQuery):
    def document(self, doc_id: str):
        return FakeDocRef(self._db, self._collection, doc_id)


class FakeBatch:
    def __init__(self, db):
        self._db, self._ops = db, []

    def delete(self, ref):
        self._ops.append(ref)

    def commit(self):
        for ref in self._ops:
            ref.delete()


class FakeFirestore:
    def __init__(self, data: dict, log: list):
        self.data, self.log = data, log

    def collection(self, name: str):
        return FakeCollection(self, name)

    def batch(self):
        return FakeBatch(self)


class FakeBlob:
    def __init__(self, name: str):
        self.name = name


class FakeBucketHandle:
    def __init__(self, storage, bucket: str):
        self._storage, self._bucket = storage, bucket

    def blob(self, name: str):
        return _FakeBlobHandle(self._storage, self._bucket, name)


class _FakeBlobHandle:
    def __init__(self, storage, bucket: str, name: str):
        self._storage, self._bucket, self._name = storage, bucket, name

    def delete(self):
        if (self._bucket, self._name) in self._storage.fail:
            raise RuntimeError("503 backend error")
        self._storage.log.append(("gcs_delete", self._bucket, self._name))
        self._storage.objects.get(self._bucket, set()).discard(self._name)


class FakeStorage:
    def __init__(self, objects: dict, log: list, fail: set | None = None):
        self.objects, self.log, self.fail = objects, log, fail or set()

    def bucket(self, name: str):
        return FakeBucketHandle(self, name)

    def list_blobs(self, bucket: str, prefix: str = ""):
        return [
            FakeBlob(n)
            for n in sorted(self.objects.get(bucket, set()))
            if n.startswith(prefix)
        ]


class FakeAuth:
    def __init__(self, log: list):
        self.log = log

    def delete_user(self, uid: str):
        self.log.append(("auth_delete", uid))


UID = "user-1"
OTHER = "user-2"
CAPTURES, OUTPUTS = "captures-bkt", "outputs-bkt"


@pytest.fixture
def world():
    """One user with two scenes (one of whose upload_session has TTL'd away),
    one conversation with two turns, one design spec, plus another user's data
    that must survive untouched."""
    log: list = []
    data = {
        SCENES_COLLECTION: {
            "scene-a": {"user_id": UID, "bundle_id": "bundle-a"},
            "scene-b": {"user_id": UID, "bundle_id": "bundle-b"},
            "scene-x": {"user_id": OTHER, "bundle_id": "bundle-x"},
        },
        UPLOAD_SESSIONS_COLLECTION: {
            # bundle-a's session survived; bundle-b's hit its 7-day TTL.
            # bundle-c is a fresh upload with no scene yet.
            "bundle-a": {"user_id": UID},
            "bundle-c": {"user_id": UID},
            "bundle-x": {"user_id": OTHER},
        },
        CONVERSATIONS_COLLECTION: {
            f"scene-a__{UID}": {"user_id": UID, "scene_id": "scene-a"},
            f"scene-x__{OTHER}": {"user_id": OTHER, "scene_id": "scene-x"},
        },
        f"{CONVERSATIONS_COLLECTION}/scene-a__{UID}/turns": {
            "000000": {"user_text": "hi"},
            "000001": {"user_text": "again"},
        },
        f"{CONVERSATIONS_COLLECTION}/scene-x__{OTHER}/turns": {
            "000000": {"user_text": "theirs"},
        },
        DESIGN_SPECS_COLLECTION: {
            f"scene-a__{UID}": {"user_id": UID, "scene_id": "scene-a"},
            f"scene-x__{OTHER}": {"user_id": OTHER, "scene_id": "scene-x"},
        },
        MINT_QUOTAS_COLLECTION: {UID: {"count": 3}, OTHER: {"count": 1}},
    }
    objects = {
        OUTPUTS: {
            "scenes/scene-a/manifest.json",
            "scenes/scene-a/shell.json",
            "scenes/scene-a/frames/0000/masks.npz",
            "scenes/scene-b/manifest.json",
            "scenes/scene-x/manifest.json",
        },
        CAPTURES: {
            "captures/bundle-a/bundle.pb",
            "captures/bundle-c/frames/000000.jpg",
            "captures/bundle-x/bundle.pb",
        },
    }
    storage = FakeStorage(objects, log)
    return {
        "log": log,
        "data": data,
        "objects": objects,
        "storage": storage,
        "deleter": AccountDeleter(
            firestore_client=FakeFirestore(data, log),
            storage_client=storage,
            auth_client=FakeAuth(log),
            captures_bucket=CAPTURES,
            outputs_bucket=OUTPUTS,
            max_workers=4,
        ),
    }


# ---------------------------------------------------------------------------
# The plan (pure)
# ---------------------------------------------------------------------------

def test_plan_unions_bundle_ids_from_scenes_and_sessions():
    """The load-bearing union. upload_sessions carries a 7-day TTL while
    scenes persist, so each source knows bundles the other has lost. Taking
    either alone leaks capture blobs."""
    plan = plan_account_deletion(
        UID,
        OwnedRecords(
            scene_ids=("s1", "s2"),
            scene_bundle_ids=("only-in-scenes", None),
            upload_session_bundle_ids=("only-in-sessions",),
        ),
    )
    assert plan.captures_prefixes == (
        "captures/only-in-scenes/",
        "captures/only-in-sessions/",
    )


def test_deletion_covers_every_collection_the_source_declares():
    """Completeness, DISCOVERED rather than restated.

    This test used to compare account_deletion's own constants against a
    hardcoded set of the same four strings — which can only fail if someone
    edits both halves of one file, and never fires for the case its docstring
    promised: a collection introduced somewhere else. `design_specs` was added
    by the design-spec repository and went unnoticed for exactly that reason,
    so user design proposals survived a deletion reported as complete.

    Now the collection names are read out of the service source. A new
    `COLLECTION = "..."` or `.collection("...")` anywhere in api-public,
    api-internal, or api-core fails here until it is either deleted with the
    account or listed as deliberately not per-user.
    """
    roots = [
        Path(__file__).resolve().parents[1],                       # api-public
        Path(__file__).resolve().parents[2] / "api-internal",
        Path(__file__).resolve().parents[3]
        / "packages" / "api-core" / "roomstudio_api_core",
    ]
    literal = re.compile(r'(?:COLLECTION[A-Z_]*\s*=\s*|\.collection\()"([a-z_]+)"')
    declared: set[str] = set()
    for root in roots:
        for path in root.rglob("*.py"):
            if "tests" in path.parts or path.name.startswith("test_"):
                continue
            declared |= set(literal.findall(path.read_text(encoding="utf-8")))

    deleted_with_the_account = {
        SCENES_COLLECTION,
        UPLOAD_SESSIONS_COLLECTION,
        CONVERSATIONS_COLLECTION,
        CONVERSATION_TURNS_SUBCOLLECTION,
        DESIGN_SPECS_COLLECTION,
        MINT_QUOTAS_COLLECTION,
    }
    # Nothing is exempt today. A genuinely non-per-user collection goes here
    # WITH the reason it carries no user data — never to quiet this test.
    not_per_user: set[str] = set()

    assert declared, "collection discovery matched nothing — the regex broke"
    uncovered = declared - deleted_with_the_account - not_per_user
    assert not uncovered, (
        f"collections not erased by DELETE /account: {sorted(uncovered)}. "
        "Add them to plan_account_deletion and AccountDeleter.delete, or "
        "list them in not_per_user with a reason."
    )


def test_plan_names_every_collection_it_deletes():
    plan = plan_account_deletion(
        UID,
        OwnedRecords(
            scene_ids=("s1",),
            scene_bundle_ids=("b1",),
            upload_session_bundle_ids=("b1",),
            conversation_doc_ids=(f"s1__{UID}",),
            design_spec_doc_ids=(f"s1__{UID}",),
        ),
    )
    assert plan.scene_ids and plan.upload_session_ids
    assert plan.conversation_doc_ids and plan.mint_quota_doc_id == UID
    assert plan.design_spec_doc_ids
    assert plan.outputs_prefixes and plan.captures_prefixes


def test_a_design_spec_alone_is_not_an_empty_plan():
    """A user who proposed a rearrangement and nothing else still has data."""
    plan = plan_account_deletion(
        UID, OwnedRecords(design_spec_doc_ids=(f"s1__{UID}",))
    )
    assert not plan.is_empty


def test_empty_plan_is_reported_empty():
    assert plan_account_deletion(UID, OwnedRecords()).is_empty


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

def test_deletes_everything_owned(world):
    report = world["deleter"].delete(UID)

    assert report.complete and report.identity_deleted
    assert report.scenes_deleted == 2
    assert report.upload_sessions_deleted == 2
    assert report.conversations_deleted == 1
    assert report.conversation_turns_deleted == 2
    assert report.mint_quota_deleted
    # 4 outputs blobs (scene-a ×3, scene-b ×1) + 2 capture blobs.
    assert report.blobs_deleted == 6


def test_leaves_other_users_untouched(world):
    world["deleter"].delete(UID)

    data, objects = world["data"], world["objects"]
    assert set(data[SCENES_COLLECTION]) == {"scene-x"}
    assert set(data[UPLOAD_SESSIONS_COLLECTION]) == {"bundle-x"}
    assert set(data[CONVERSATIONS_COLLECTION]) == {f"scene-x__{OTHER}"}
    assert set(data[MINT_QUOTAS_COLLECTION]) == {OTHER}
    assert data[f"{CONVERSATIONS_COLLECTION}/scene-x__{OTHER}/turns"]
    assert objects[OUTPUTS] == {"scenes/scene-x/manifest.json"}
    assert objects[CAPTURES] == {"captures/bundle-x/bundle.pb"}


def test_turns_subcollection_is_deleted_explicitly(world):
    """Firestore does not cascade — the turns must be deleted by hand, and
    before the parent doc, or they become unreachable orphans."""
    world["deleter"].delete(UID)
    assert world["data"][f"{CONVERSATIONS_COLLECTION}/scene-a__{UID}/turns"] == {}


def test_ordering_gcs_then_firestore_then_identity(world):
    """The ordering IS the recoverability property (0095): GCS first so a
    failure leaves the records that the plan is derived FROM."""
    world["deleter"].delete(UID)
    kinds = [op[0] for op in world["log"]]

    assert kinds[-1] == "auth_delete", "identity must be the final act"
    assert max(i for i, k in enumerate(kinds) if k == "gcs_delete") < min(
        i for i, k in enumerate(kinds) if k == "fs_delete"
    ), "every GCS delete must precede every Firestore delete"


def test_storage_failure_aborts_before_firestore_and_keeps_identity(world):
    """A partial pass must strand nothing: no record is touched, the user can
    still sign in, and calling again re-derives the identical plan."""
    world["storage"].fail = {(OUTPUTS, "scenes/scene-a/shell.json")}

    report = world["deleter"].delete(UID)

    assert not report.complete and not report.identity_deleted
    assert report.errors
    kinds = [op[0] for op in world["log"]]
    assert "fs_delete" not in kinds and "auth_delete" not in kinds
    # Every record still present, so the retry sees the same world.
    assert set(world["data"][SCENES_COLLECTION]) == {"scene-a", "scene-b", "scene-x"}


def test_resumes_after_a_transient_storage_failure(world):
    world["storage"].fail = {(OUTPUTS, "scenes/scene-a/shell.json")}
    assert not world["deleter"].delete(UID).complete

    world["storage"].fail = set()
    report = world["deleter"].delete(UID)

    assert report.complete and report.identity_deleted
    assert world["objects"][OUTPUTS] == {"scenes/scene-x/manifest.json"}


def test_is_idempotent(world):
    world["deleter"].delete(UID)
    second = world["deleter"].delete(UID)

    assert second.complete
    assert second.scenes_deleted == 0 and second.blobs_deleted == 0
    assert second.conversations_deleted == 0


class UserNotFoundError(Exception):
    """Stands in for firebase_admin.auth.UserNotFoundError.

    THE CLASS NAME IS LOAD-BEARING. firebase_admin is not installed in the test
    environment (auth.py carries the same "deferred: not installed in tests"
    note), so the deleter cannot isinstance-check the real class and matches on
    __name__ instead. This double must therefore be named exactly as Firebase
    names it, or it tests nothing.
    """


def test_second_pass_survives_an_already_deleted_identity(world):
    """The regression that test_is_idempotent could not see.

    Its FakeAuth never raises, so idempotency passed in unit tests while the
    deployed endpoint 500'd on every second call: Firebase raises
    UserNotFoundError once the user is gone. Reachable in ordinary use — an ID
    token stays valid for up to an hour after its user is deleted, so any retry
    inside that window (exactly what the 202 "call again" contract asks for)
    hit it. Measured against the live service 2026-08-08; decision 0103.
    """
    class GoneAuth:
        def delete_user(self, uid):
            raise UserNotFoundError("No user record found for the given identifier")

    world["deleter"]._auth = GoneAuth()

    report = world["deleter"].delete(UID)

    assert report.complete
    assert report.identity_deleted, "an absent identity IS the desired end state"


def test_an_unexpected_auth_error_still_propagates(world):
    """The narrow catch must not become a blanket one — a permissions failure
    (the INSUFFICIENT_PERMISSION that shipped without the identity-deleter
    role) has to stay loud, not be reported as a completed deletion."""
    class BrokenAuth:
        def delete_user(self, uid):
            raise PermissionError("INSUFFICIENT_PERMISSION")

    world["deleter"]._auth = BrokenAuth()

    with pytest.raises(PermissionError):
        world["deleter"].delete(UID)


def test_missing_blob_between_list_and_delete_is_not_an_error(world):
    """The captures lifecycle rule (age=1d) races every deletion. A blob that
    vanished under us is the expected case, not a failure."""
    class Vanishing(_FakeBlobHandle):
        def delete(self):
            raise RuntimeError("404 Not Found")

    storage = world["storage"]
    storage.bucket = lambda name: type(
        "B", (), {"blob": staticmethod(lambda n: Vanishing(storage, name, n))}
    )()

    report = world["deleter"].delete(UID)
    assert report.complete and not report.errors


def test_report_counts_carry_no_paths_or_ids(world):
    """The client-facing projection is counts only — errors[] can contain
    object paths and is logged, never shipped."""
    counts = world["deleter"].delete(UID).counts()
    assert set(counts) == {
        "rooms", "conversations", "conversation_messages", "design_specs",
        "upload_sessions", "files",
    }
    assert all(isinstance(v, int) for v in counts.values())


# ---------------------------------------------------------------------------
# The route
# ---------------------------------------------------------------------------

@pytest.fixture
def client(world, monkeypatch):
    monkeypatch.setattr(public_server, "_get_account_deleter", lambda: world["deleter"])
    return TestClient(public_server.app)


def _auth(uid: str = UID) -> dict:
    return {"Authorization": f"Bearer test-uid:{uid}"}


def test_route_deletes_and_reports_counts(client):
    r = client.request(
        "DELETE", "/account", headers=_auth(), json={"confirm_user_id": UID}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["deleted"] is True and body["identity_deleted"] is True
    assert body["counts"]["rooms"] == 2


def test_route_refuses_a_mismatched_confirmation(client, world):
    r = client.request(
        "DELETE", "/account", headers=_auth(), json={"confirm_user_id": OTHER}
    )
    assert r.status_code == 400
    assert r.json()["error"] == "confirmation_mismatch"
    assert world["data"][SCENES_COLLECTION]  # nothing touched


def test_route_requires_a_token(client, world):
    r = client.request("DELETE", "/account", json={"confirm_user_id": UID})
    assert r.status_code == 422  # FastAPI: required header absent
    assert world["data"][SCENES_COLLECTION]


def test_route_rejects_an_invalid_token(client, world):
    r = client.request(
        "DELETE",
        "/account",
        headers={"Authorization": "Bearer garbage"},
        json={"confirm_user_id": UID},
    )
    assert r.status_code == 401
    assert world["data"][SCENES_COLLECTION]


def test_route_cannot_target_another_user(client, world):
    """There is no uid parameter — the token IS the target. The only way to
    name another user is confirm_user_id, and that must match."""
    r = client.request(
        "DELETE", "/account", headers=_auth(OTHER), json={"confirm_user_id": OTHER}
    )
    assert r.status_code == 200
    # OTHER's data went; UID's survived untouched.
    assert set(world["data"][SCENES_COLLECTION]) == {"scene-a", "scene-b"}


def test_route_202s_a_partial_pass_without_leaking_paths(client, world):
    world["storage"].fail = {(OUTPUTS, "scenes/scene-a/shell.json")}
    r = client.request(
        "DELETE", "/account", headers=_auth(), json={"confirm_user_id": UID}
    )
    assert r.status_code == 202
    body = r.json()
    assert body["deleted"] is False and body["identity_deleted"] is False
    assert "scenes/scene-a" not in r.text


def test_route_503s_when_no_datastore_is_configured(monkeypatch):
    monkeypatch.setattr(public_server, "_get_account_deleter", lambda: None)
    r = TestClient(public_server.app).request(
        "DELETE", "/account", headers=_auth(), json={"confirm_user_id": UID}
    )
    assert r.status_code == 503
    assert r.json()["error"] == "deletion_unavailable"
