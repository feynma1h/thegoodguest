#!/usr/bin/env python3
"""One-time backfill: stamp expire_at on existing terminal-failure scenes.

Gap F6 (decisions 0018/0086) ships expiry stamping in api-internal's
update_status — which only covers transitions from deploy day onward. Every
terminal-failure scene created before then (months of smoke-run
failed_invalid junk, dead failed scenes) has no expire_at and would never be
swept by the new TTL policy. This tool stamps exactly those documents.

What it stamps: scenes with status in {failed, failed_invalid,
failed_incomplete} AND no expire_at field. The deadline is now + --ttl-days
(default 90, mirroring SCENES_FAILED_TTL_DAYS).

What it never touches: queued / processing / ready scenes (including the
deliberate stuck-scene reference f077e9ed, which is processing), and any
scene already carrying an expire_at.

Default is a DRY RUN that lists what would change. Pass --apply to write.

Run from repo root with ADC (the operator's gcloud auth):
  .venv/bin/python tools/backfill_scene_expiry.py            # dry run
  .venv/bin/python tools/backfill_scene_expiry.py --apply    # stamp

Consumers: operator, once per environment after the F6 deploy; kept for
future environments.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone

TERMINAL_FAILURE_STATUSES = frozenset({"failed", "failed_invalid", "failed_incomplete"})


def should_stamp(status: str, existing_expire_at) -> bool:
    """Pure decision: stamp exactly the terminal-failure scenes that have no
    expiry yet. Anything else — live states, already-stamped docs, unknown
    statuses — is left alone (conservative: unknown means do not touch)."""
    return status in TERMINAL_FAILURE_STATUSES and existing_expire_at is None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--project", default="roomstudio")
    parser.add_argument("--ttl-days", type=int, default=90,
                        help="days until expiry (default 90, = SCENES_FAILED_TTL_DAYS)")
    parser.add_argument("--apply", action="store_true",
                        help="write the stamps (default: dry run)")
    args = parser.parse_args(argv)

    from google.cloud import firestore

    db = firestore.Client(project=args.project)
    expire_at = datetime.now(tz=timezone.utc) + timedelta(days=args.ttl_days)

    examined = 0
    to_stamp = []
    for snap in db.collection("scenes").stream():
        examined += 1
        data = snap.to_dict() or {}
        if should_stamp(data.get("status", ""), data.get("expire_at")):
            to_stamp.append((snap.id, data.get("status"), data.get("bundle_id")))

    mode = "APPLY" if args.apply else "DRY RUN"
    print(f"[{mode}] examined {examined} scenes; "
          f"{len(to_stamp)} terminal-failure scenes lack expire_at")
    for scene_id, status, bundle_id in to_stamp:
        print(f"  {scene_id}  status={status}  bundle_id={bundle_id}")

    if not args.apply:
        print("Dry run — nothing written. Re-run with --apply to stamp "
              f"expire_at={expire_at.isoformat()}.")
        return 0

    for scene_id, _, _ in to_stamp:
        db.collection("scenes").document(scene_id).update({"expire_at": expire_at})
    print(f"Stamped {len(to_stamp)} scenes with expire_at={expire_at.isoformat()}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
