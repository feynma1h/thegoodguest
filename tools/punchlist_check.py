#!/usr/bin/env python3
"""Verify the machine-checkable subset of docs/punchlist.md against the live system.

Run from the repo root:

    python3 tools/punchlist_check.py            # everything
    python3 tools/punchlist_check.py --offline  # skip checks that hit the network
    python3 tools/punchlist_check.py G3-01      # one item, or a gate prefix like G3

WHY THIS EXISTS. This project's recurring failure is not forgetting work — it is
documents going quietly out of date. On 2026-08-26 CLAUDE.md asserted CI was
green while it had been red for five days, named three different serving
revisions for one service, and said the phone held no captures when it held five.
Each of those was one command away from being caught. An item whose status can be
re-derived cannot rot the same way.

WHAT IT DOES NOT DO. It does not edit the punchlist. A check going green is a
signal to a human that an entry can be DELETED (the punchlist's own rule), not an
instruction this script carries out — deleting an entry is a judgment about
whether the work is actually finished, and a passing probe is only evidence.

ADDING A CHECK. Write a function returning (done: bool, detail: str) and register
it in CHECKS under the punchlist ID. Raise anything to report the check itself as
broken; a check that cannot run is reported as UNKNOWN and never as done, because
"I could not tell" and "it is finished" are different answers (0206's rule,
applied to this file).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PUNCHLIST = REPO / "docs" / "punchlist.md"

NET = "net"  # marks a check that reaches the network; --offline skips these


# ── helpers ──────────────────────────────────────────────────────────────────

def _run(cmd: list[str], timeout: int = 120) -> str:
    """Run a command and return stdout. Raises on non-zero so the caller reports
    UNKNOWN rather than silently treating a broken probe as a passing one."""
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=REPO)
    if p.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd[:3])}… exited {p.returncode}: {p.stderr.strip()[:160]}")
    return p.stdout


def _read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8", errors="replace")


def _fetch(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "punchlist-check"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


# ── Gate 1 ───────────────────────────────────────────────────────────────────

def check_privacy_manifest():
    """G1-02 — PrivacyInfo.xcprivacy must exist somewhere under ios/."""
    hits = list((REPO / "ios").rglob("PrivacyInfo.xcprivacy"))
    if hits:
        return True, f"present: {hits[0].relative_to(REPO)}"
    return False, "absent — App Store submission requires it (draft in labels §9)"


def check_web_base_url():
    """G1-05 — NetworkConfig.webBaseURL must stop being nil."""
    src = _read("ios/TheGoodGuest/TheGoodGuest/Networking/NetworkConfig.swift")
    m = re.search(r"webBaseURL\s*:\s*URL\?\s*=\s*(.+)", src)
    if not m:
        raise RuntimeError("could not find the webBaseURL declaration")
    value = m.group(1).strip().rstrip(";")
    if value == "nil":
        return False, "nil — the app has no route to the web; rooms cannot be opened"
    return True, f"set to {value}"


def check_ios_account_deletion():
    """G1-08 — the app must offer a route into DELETE /account.

    App Review 5.1.1(v) requires an app supporting account creation to let the
    user initiate deletion from inside it, and this app creates accounts the
    moment an anonymous UID is linked to Apple or Google. The backend half has
    been complete since account_deletion.py landed; what is missing is a call
    site, so the only deletion route a person has is one they cannot reach from
    the app that made their rooms.

    Looks for the method and the path in ONE file, not merely both somewhere
    under ios/: a client that deletes the account has to build both.
    """
    hits = []
    for path in (REPO / "ios").rglob("*.swift"):
        if any("Tests" in part for part in path.parts):
            continue  # a test referencing the route is not a route a person has
        src = path.read_text(encoding="utf-8", errors="replace")
        if '"DELETE"' in src and re.search(r"/account\b", src):
            hits.append(path.relative_to(REPO).as_posix())
    if hits:
        return True, "reaches DELETE /account from " + ", ".join(sorted(hits))
    return False, (
        "no shipping Swift file issues DELETE /account — the route is live and "
        "the app cannot reach it (App Review 5.1.1(v))"
    )


# ── Gate 2 ───────────────────────────────────────────────────────────────────

def check_live_site_name():
    """G2-01 — the deployed <title> must match the repo's."""
    layout = _read("web/src/app/layout.tsx")
    m = re.search(r'title:\s*"([^"]+)"', layout)
    if not m:
        raise RuntimeError("could not find the title in layout.tsx")
    expected = m.group(1)
    html = _fetch("https://thegoodguest.web.app/")
    m2 = re.search(r"<title>([^<]*)</title>", html, re.I)
    live = m2.group(1).strip() if m2 else "(none)"
    if live == expected:
        return True, f"live title matches repo: {live!r}"
    return False, f"live serves {live!r}, repo has {expected!r} — web not deployed since the name landed"


check_live_site_name.tag = NET


def check_ios_fcm_registration():
    """G2-05 — the phone must actually obtain an FCM token, not just be able to
    send one. The wire has been finished on both sides since the backend
    threading landed; what is missing is registration, so the parameter defaults
    to nil on every call and terminal-state push reaches nobody."""
    ios = REPO / "ios"
    wants = ("FirebaseMessaging", "registerForRemoteNotifications")
    found = {w: [] for w in wants}
    for path in ios.rglob("*.swift"):
        src = path.read_text(encoding="utf-8", errors="replace")
        for w in wants:
            if w in src:
                found[w].append(path.relative_to(REPO).as_posix())
    missing = [w for w in wants if not found[w]]
    if missing:
        return False, f"no {' and no '.join(missing)} anywhere under ios/"
    return True, "registers: " + "; ".join(f"{w} in {found[w][0]}" for w in wants)

# ── Gate 3 ───────────────────────────────────────────────────────────────────

RETENTION_FILES = [
    "web/src/app/privacy/page.tsx",
    "infra/eventarc_setup.sh",
    "services/api-public/account_deletion.py",
]


def check_retention_claim():
    """G3-01 — the false "7 days" upload-bookkeeping claim must leave all three files."""
    stale = []
    for rel in RETENTION_FILES:
        for i, line in enumerate(_read(rel).splitlines(), 1):
            if re.search(r"\b7[- ]day", line, re.I) and re.search(r"upload|session|bookkeep", line, re.I):
                stale.append(f"{rel}:{i}")
    if stale:
        return False, "still claims 7 days in " + ", ".join(stale)
    return True, "no 7-day upload-bookkeeping claim remains in the three files"


def check_per_room_deletion():
    """G3-03 — a per-room delete route must exist on api-public.

    The path must END at the room identifier. `DELETE /scenes/{id}/design_spec`
    removes the arrangement document, not the room, and an earlier version of
    this check accepted it — which would have reported the item finished while
    the gap it names was wide open.
    """
    src = _read("services/api-public/public_server.py")
    room_delete = re.compile(r"^/(scenes|rooms)/\{[a-z_]+\}$")
    found = []
    for m in re.finditer(r'@app\.delete\(\s*\n?\s*"([^"]+)"', src):
        path = m.group(1)
        found.append(path)
        if room_delete.match(path):
            return True, f"route exists: DELETE {path}"
    others = ", ".join(p for p in found if p != "/account") or "none"
    return False, (
        "no DELETE on a room itself — blocks every sharing rung above the card "
        f"(other delete routes, which do not count: {others})"
    )


# ── Gate 4 ───────────────────────────────────────────────────────────────────

def check_alerting():
    """G4-01 — at least one alert policy or uptime check must exist."""
    pol = _run(["gcloud", "monitoring", "policies", "list", "--format=value(name)"]).strip()
    up = _run(["gcloud", "monitoring", "uptime", "list-configs", "--format=value(name)"]).strip()
    n = len([x for x in pol.splitlines() if x]) + len([x for x in up.splitlines() if x])
    if n:
        return True, f"{n} alert policy/uptime check(s) configured"
    return False, "no alert policies and no uptime checks — nothing reports failure"


check_alerting.tag = NET


def check_python_ci():
    """G4-02 — the latest python.yml run must have concluded success."""
    out = _run([
        "gh", "run", "list", "--workflow=python.yml", "--limit", "1",
        "--json", "conclusion,createdAt,headBranch",
    ])
    runs = json.loads(out)
    if not runs:
        return False, "no python.yml runs found"
    r = runs[0]
    if r.get("conclusion") == "success":
        return True, f"latest run green ({r['createdAt'][:10]} on {r['headBranch']})"
    return False, f"latest run {r.get('conclusion')} ({r['createdAt'][:10]} on {r['headBranch']})"


check_python_ci.tag = NET


def check_unrestricted_api_key():
    """G4-05 — no browser key should allow the full API surface unrestricted."""
    out = _run(["gcloud", "services", "api-keys", "list", "--format=json"])
    wide = []
    for k in json.loads(out):
        r = k.get("restrictions") or {}
        if "browserKeyRestrictions" not in r:
            continue
        targets = r.get("apiTargets")
        referrers = (r.get("browserKeyRestrictions") or {}).get("allowedReferrers")
        if not targets or not referrers:
            wide.append(f"{k.get('displayName')} ({len(targets) if targets else 'all'} APIs)")
    if wide:
        return False, "unrestricted browser key: " + "; ".join(wide)
    return True, "every browser key is referrer- and API-restricted"


check_unrestricted_api_key.tag = NET


# ── registry ─────────────────────────────────────────────────────────────────

CHECKS = {
    "G1-02": check_privacy_manifest,
    "G1-05": check_web_base_url,
    "G1-08": check_ios_account_deletion,
    "G2-01": check_live_site_name,
    "G2-05": check_ios_fcm_registration,
    "G3-01": check_retention_claim,
    "G3-03": check_per_room_deletion,
    "G4-01": check_alerting,
    "G4-02": check_python_ci,
    "G4-05": check_unrestricted_api_key,
}


def punchlist_ids() -> list[str]:
    """Every ID the punchlist declares, in file order."""
    return re.findall(r"^### (G\d-\d\d) ", PUNCHLIST.read_text(encoding="utf-8"), re.M)


def orphaned_checks() -> list[str]:
    """IDs with a probe but no punchlist entry.

    The loop below walks the punchlist, so a probe whose entry has been deleted
    is never called again — it does not fail, it just stops existing. Two sat
    that way for weeks. Reported rather than tolerated: either the entry came
    back, or the probe should go.
    """
    return sorted(set(CHECKS) - set(punchlist_ids()))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("filter", nargs="?", help="an ID (G3-01) or gate prefix (G3)")
    ap.add_argument("--offline", action="store_true", help="skip checks that hit the network")
    args = ap.parse_args()

    orphans = orphaned_checks()
    ids = punchlist_ids()
    if not ids:
        print("no punchlist entries found — is docs/punchlist.md intact?", file=sys.stderr)
        return 2
    if args.filter:
        ids = [i for i in ids if i == args.filter or i.startswith(args.filter)]
        if not ids:
            print(f"no punchlist entry matches {args.filter!r}", file=sys.stderr)
            return 2

    done, open_, unknown, manual = [], [], [], []

    for pid in ids:
        fn = CHECKS.get(pid)
        if fn is None:
            manual.append(pid)
            continue
        if args.offline and getattr(fn, "tag", None) == NET:
            unknown.append((pid, "skipped (--offline)"))
            continue
        try:
            ok, detail = fn()
        except Exception as e:  # a broken probe is never a pass
            unknown.append((pid, f"check failed: {e}"))
            continue
        (done if ok else open_).append((pid, detail))

    def emit(label: str, rows: list[tuple[str, str]]) -> None:
        if not rows:
            return
        print(f"\n{label}")
        for pid, detail in rows:
            print(f"  {pid}  {detail}")

    emit("DONE — the punchlist entry can be deleted (your call, not the script's):", done)
    emit("OPEN — verified still outstanding:", open_)
    emit("UNKNOWN — could not tell; NOT the same as done:", unknown)

    if manual:
        print(f"\nMANUAL — no automated check ({len(manual)}): {', '.join(manual)}")

    if orphans:
        print(
            f"\nSTALE — {len(orphans)} probe(s) registered for entries the punchlist no "
            f"longer declares: {', '.join(orphans)}\n"
            "  Delete the probe, or restore the entry it was written for.",
            file=sys.stderr,
        )

    print(
        f"\n{len(done)} done · {len(open_)} open · {len(unknown)} unknown · "
        f"{len(manual)} manual · {len(ids)} entries"
    )
    # Exit 0 whenever every check ran. Outstanding work is the expected state of a
    # punchlist, not an error; a probe that could not run, or one registered for
    # an entry that no longer exists, is worth a non-zero.
    return 1 if unknown or orphans else 0


if __name__ == "__main__":
    sys.exit(main())
