"""Account deletion — the complete erasure of one user (decision 0095).

App Store guideline 5.1.1(v) requires an in-app path to account deletion for
any app offering account creation, and Sign in with Apple makes thegoodguest one
of those. There is deliberately no iOS sign-out (0064: launch-time
`signInIfNeeded` would re-mint a fresh anonymous UID), so deletion — not
sign-out — is the account operation the user gets.

WHY THIS MODULE EXISTS AT ALL: **Firestore never cascades.** Deleting a
document does not delete its subcollections, and no query returns "everything
belonging to user X" across collections. Every collection and every GCS prefix
has to be named here, by hand. A collection added later and not added here
becomes data that survives a deletion the user was told was complete — which
is exactly the failure this module is written to prevent. If you add a
per-user collection anywhere in this system, add it to `plan_account_deletion`
and to its test.

THE MAP:

  Firestore (project FIRESTORE_PROJECT)
    scenes/{scene_id}                     where user_id == uid
    upload_sessions/{bundle_id}           where user_id == uid
    upload_mint_quotas/{uid}              doc id IS the uid
    conversations/{scene_id}__{uid}       where user_id == uid
      └─ turns/{index}  (SUBCOLLECTION — does not cascade; deleted explicitly)
    design_specs/{scene_id}__{uid}        where user_id == uid

  GCS
    gs://{captures}/captures/{bundle_id}/**   for every bundle_id the user
                                              owns, from scenes AND from
                                              upload_sessions (see below)
    gs://{outputs}/scenes/{scene_id}/**       manifest, shell, splats,
                                              per-frame masks/objects,
                                              roomplan/room.json

  Firebase Auth
    the user record itself — deleted LAST, and only on a complete pass

THE BUNDLE-ID UNION IS LOAD-BEARING. Bundle ids reach us from two independent
places with different lifetimes: `upload_sessions` carries a 7-day TTL, while
`scenes` persist. A capture uploaded 8 days ago has a scene but no session; a
capture uploaded 30 seconds ago may have a session and no scene yet. Taking
either source alone leaks capture blobs, so the plan unions them.

ORDERING, and why it is not the obvious one:

  1. GCS blobs first.
  2. Firestore documents second.
  3. The Firebase Auth user last.

Deleting Firestore first would be faster to make "look" done, but a failure
between steps would leave GCS blobs with no record anywhere of which prefixes
they belonged to — an unrecoverable leak, since the plan is derived FROM those
Firestore records. Doing GCS first means any failure leaves the records
intact, a retry re-derives the identical plan, and nothing is stranded.

The auth user goes last for the same reason from the user's side: while it
exists they can still sign in and retry. Delete it first and a mid-way failure
locks them out of their own leftovers with no way back in.

Everything here is IDEMPOTENT and RESUMABLE. A partial pass deletes strictly
less; the next pass re-derives a smaller plan. `complete=False` in the report
means "call again", never "something is corrupt".

Consumers: public_server.py (DELETE /account).
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Collection names. Imported from the repositories that own them wherever one
# exists, so a rename there cannot silently desync this module. `conversations`
# / `turns` are api-public's own (conversation_repo).
from design_spec import FirestoreDesignSpecRepository
from thegoodguest_api_core.scene_read_repo import FirestoreSceneReadRepository
from thegoodguest_api_core.upload_session_repo import FirestoreUploadSessionRepository

SCENES_COLLECTION = FirestoreSceneReadRepository.COLLECTION
UPLOAD_SESSIONS_COLLECTION = FirestoreUploadSessionRepository.COLLECTION
MINT_QUOTAS_COLLECTION = FirestoreUploadSessionRepository.QUOTA_COLLECTION
DESIGN_SPECS_COLLECTION = FirestoreDesignSpecRepository.COLLECTION
CONVERSATIONS_COLLECTION = "conversations"
CONVERSATION_TURNS_SUBCOLLECTION = "turns"

# Concurrency for GCS blob deletes. Each delete is one small IO-bound HTTPS
# call; measured scene footprints are 87–147 blobs, so a 7-scene account is
# ~1k deletes. At 32 workers that is a couple of seconds, comfortably inside
# the service's 120 s request timeout.
_DELETE_CONCURRENCY = 32


@dataclass(frozen=True)
class OwnedRecords:
    """What the caller found in Firestore for this user. Kept as plain data so
    the planner below is pure and the enumeration is the only part that needs
    a live Firestore."""
    scene_ids: tuple[str, ...] = ()
    # bundle_id per scene, in scene order; None where the scene carries none.
    scene_bundle_ids: tuple[str | None, ...] = ()
    upload_session_bundle_ids: tuple[str, ...] = ()
    conversation_doc_ids: tuple[str, ...] = ()
    design_spec_doc_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class DeletionPlan:
    """Everything that must go, named explicitly. Ordered lists so a plan is
    comparable in tests and reproducible across runs."""
    user_id: str
    outputs_prefixes: tuple[str, ...]
    captures_prefixes: tuple[str, ...]
    scene_ids: tuple[str, ...]
    upload_session_ids: tuple[str, ...]
    conversation_doc_ids: tuple[str, ...]
    design_spec_doc_ids: tuple[str, ...]
    mint_quota_doc_id: str

    @property
    def is_empty(self) -> bool:
        """True when there is nothing but the identity left to remove."""
        return not (
            self.outputs_prefixes
            or self.captures_prefixes
            or self.scene_ids
            or self.upload_session_ids
            or self.conversation_doc_ids
            or self.design_spec_doc_ids
        )


@dataclass
class DeletionReport:
    """What actually happened. Returned to the caller verbatim (minus
    `errors`, which is logged, not shipped — it can carry GCS paths)."""
    user_id: str
    blobs_deleted: int = 0
    scenes_deleted: int = 0
    upload_sessions_deleted: int = 0
    conversations_deleted: int = 0
    conversation_turns_deleted: int = 0
    design_specs_deleted: int = 0
    mint_quota_deleted: bool = False
    identity_deleted: bool = False
    complete: bool = False
    errors: list[str] = field(default_factory=list)

    def counts(self) -> dict:
        """Client-facing projection — counts only, no paths or ids."""
        return {
            "rooms": self.scenes_deleted,
            "conversations": self.conversations_deleted,
            "conversation_messages": self.conversation_turns_deleted,
            "design_specs": self.design_specs_deleted,
            "upload_sessions": self.upload_sessions_deleted,
            "files": self.blobs_deleted,
        }


def plan_account_deletion(user_id: str, records: OwnedRecords) -> DeletionPlan:
    """PURE: owned records → everything that must be deleted.

    The bundle-id union (scenes ∪ upload_sessions) happens here; see the module
    docstring for why taking either source alone leaks capture blobs.
    """
    bundle_ids = {b for b in records.scene_bundle_ids if b}
    bundle_ids.update(b for b in records.upload_session_bundle_ids if b)

    return DeletionPlan(
        user_id=user_id,
        outputs_prefixes=tuple(f"scenes/{s}/" for s in sorted(records.scene_ids)),
        captures_prefixes=tuple(f"captures/{b}/" for b in sorted(bundle_ids)),
        scene_ids=tuple(sorted(records.scene_ids)),
        upload_session_ids=tuple(sorted(set(records.upload_session_bundle_ids))),
        conversation_doc_ids=tuple(sorted(records.conversation_doc_ids)),
        design_spec_doc_ids=tuple(sorted(records.design_spec_doc_ids)),
        mint_quota_doc_id=user_id,
    )


class AccountDeleter:
    """Executes a DeletionPlan against live Firestore / GCS / Firebase Auth.

    The three clients are injected so tests can drive the full ordering and
    failure behaviour with fakes — the ordering IS the correctness property
    here, and it is not observable from the pure planner.
    """

    def __init__(
        self,
        *,
        firestore_client,
        storage_client,
        auth_client,
        captures_bucket: str,
        outputs_bucket: str,
        max_workers: int = _DELETE_CONCURRENCY,
    ) -> None:
        self._db = firestore_client
        self._storage = storage_client
        self._auth = auth_client
        self._captures_bucket = captures_bucket
        self._outputs_bucket = outputs_bucket
        self._max_workers = max_workers

    # -- enumeration --------------------------------------------------------

    def enumerate_owned(self, user_id: str) -> OwnedRecords:
        """Read every per-user record. One query per collection; the mint
        quota needs none (its doc id is the uid)."""
        scene_ids: list[str] = []
        scene_bundles: list[str | None] = []
        for snap in self._query(SCENES_COLLECTION, user_id):
            scene_ids.append(snap.id)
            scene_bundles.append((snap.to_dict() or {}).get("bundle_id"))

        return OwnedRecords(
            scene_ids=tuple(scene_ids),
            scene_bundle_ids=tuple(scene_bundles),
            upload_session_bundle_ids=tuple(
                snap.id for snap in self._query(UPLOAD_SESSIONS_COLLECTION, user_id)
            ),
            conversation_doc_ids=tuple(
                snap.id for snap in self._query(CONVERSATIONS_COLLECTION, user_id)
            ),
            design_spec_doc_ids=tuple(
                snap.id for snap in self._query(DESIGN_SPECS_COLLECTION, user_id)
            ),
        )

    def _query(self, collection: str, user_id: str):
        from google.cloud.firestore_v1.base_query import FieldFilter  # deferred

        return (
            self._db.collection(collection)
            .where(filter=FieldFilter("user_id", "==", user_id))
            .stream()
        )

    # -- execution ----------------------------------------------------------

    def delete(self, user_id: str, *, delete_identity: bool = True) -> DeletionReport:
        """Run one full pass. Safe to call repeatedly — see module docstring.

        `delete_identity=False` erases the data and leaves the Firebase user
        alive; used by tests and available for an operator wipe that must not
        invalidate a live session.
        """
        report = DeletionReport(user_id=user_id)
        plan = plan_account_deletion(user_id, self.enumerate_owned(user_id))

        # 1. GCS first — see the ordering argument in the module docstring.
        report.blobs_deleted += self._delete_prefixes(
            self._outputs_bucket, plan.outputs_prefixes, report
        )
        report.blobs_deleted += self._delete_prefixes(
            self._captures_bucket, plan.captures_prefixes, report
        )
        if report.errors:
            logger.error(
                "account_deletion: aborting before Firestore, uid=%s errors=%d",
                user_id, len(report.errors),
            )
            return report

        # 2. Firestore. Conversations before scenes: a conversation doc id is
        # derived from its scene, so losing the scene first would leave the
        # only pointer to the turns subcollection in a doc we can still find
        # by query — recoverable, but the tidy order costs nothing.
        for doc_id in plan.conversation_doc_ids:
            conv_ref = self._db.collection(CONVERSATIONS_COLLECTION).document(doc_id)
            report.conversation_turns_deleted += self._delete_subcollection(
                conv_ref, CONVERSATION_TURNS_SUBCOLLECTION
            )
            conv_ref.delete()
            report.conversations_deleted += 1

        # Design specs before scenes, for the same reason as conversations: a
        # spec's doc id is derived from its scene.
        for doc_id in plan.design_spec_doc_ids:
            self._db.collection(DESIGN_SPECS_COLLECTION).document(doc_id).delete()
            report.design_specs_deleted += 1

        for scene_id in plan.scene_ids:
            self._db.collection(SCENES_COLLECTION).document(scene_id).delete()
            report.scenes_deleted += 1

        for bundle_id in plan.upload_session_ids:
            self._db.collection(UPLOAD_SESSIONS_COLLECTION).document(bundle_id).delete()
            report.upload_sessions_deleted += 1

        self._db.collection(MINT_QUOTAS_COLLECTION).document(
            plan.mint_quota_doc_id
        ).delete()
        report.mint_quota_deleted = True

        # 3. Identity last, and only now that nothing else is left.
        #
        # An ALREADY-ABSENT user is success, not failure: gone is the state we
        # are trying to reach. Firebase raises UserNotFoundError here, and
        # without this the second call of an idempotent endpoint 500s on an
        # account that was deleted perfectly — measured against the deployed
        # service 2026-08-08 (decision 0103). It is reachable in ordinary use:
        # an ID token stays cryptographically valid for up to an hour after
        # its user is deleted, so any client retry inside that window — which
        # is exactly what the 202 "call again" contract asks for — hits it.
        if delete_identity:
            try:
                self._auth.delete_user(user_id)
            except Exception as exc:  # noqa: BLE001 — narrowed by name below
                if type(exc).__name__ != "UserNotFoundError":
                    raise
                logger.info(
                    "account_deletion: identity already absent uid=%s", user_id
                )
            report.identity_deleted = True

        report.complete = True
        logger.info(
            "account_deletion: complete uid=%s rooms=%d conversations=%d "
            "turns=%d specs=%d sessions=%d blobs=%d identity=%s",
            user_id, report.scenes_deleted, report.conversations_deleted,
            report.conversation_turns_deleted, report.design_specs_deleted,
            report.upload_sessions_deleted,
            report.blobs_deleted, report.identity_deleted,
        )
        return report

    def _delete_prefixes(self, bucket_name: str, prefixes, report) -> int:
        """Delete every blob under each prefix, pooled. A per-blob failure is
        recorded and stops the pass (the caller returns before Firestore), so
        the plan stays re-derivable."""
        if not prefixes:
            return 0
        bucket = self._storage.bucket(bucket_name)
        blobs = [
            blob
            for prefix in prefixes
            for blob in self._storage.list_blobs(bucket_name, prefix=prefix)
        ]
        if not blobs:
            return 0

        deleted = 0

        def _rm(blob) -> bool:
            try:
                bucket.blob(blob.name).delete()
                return True
            except Exception as exc:  # noqa: BLE001 — recorded, not swallowed
                # A blob deleted by the lifecycle rule between listing and
                # deleting is the common case and is not an error worth
                # failing the pass over.
                if "404" in str(exc) or "Not Found" in str(exc):
                    return True
                report.errors.append(f"gs://{bucket_name}/{blob.name}: {exc}")
                return False

        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            for ok in pool.map(_rm, blobs):
                if ok:
                    deleted += 1
        return deleted

    def _delete_subcollection(self, parent_ref, name: str, page: int = 300) -> int:
        """Firestore does not cascade. Delete a subcollection in batches until
        it is empty."""
        total = 0
        while True:
            docs = list(parent_ref.collection(name).limit(page).stream())
            if not docs:
                return total
            batch = self._db.batch()
            for doc in docs:
                batch.delete(doc.reference)
            batch.commit()
            total += len(docs)
