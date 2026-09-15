"""The privacy manifest must keep describing the app that actually ships.

WHY THIS IS A TEST. `PrivacyInfo.xcprivacy` is required in the bundle for App
Store submission, and it is the kind of file that is written once and then goes
quietly out of date — which is this repo's documented recurring failure, applied
to a file Apple reads at upload. The failure is silent in the direction that
matters: adding one `volumeAvailableCapacity` call somewhere in `ios/` makes the
manifest incomplete, nothing in the iOS suite notices, the build is green, and
the rejection arrives as ITMS-91053 after a submission.

So the cross-check below is the point of the file. It scans the app source for
each of Apple's five required-reason API families and asserts the manifest
declares EXACTLY the categories that are actually used — neither fewer (an
undeclared call is a rejection) nor more (a declared category with no call is a
claim about the app that is not true).

REASON CODES ARE CHECKED TWICE: AGAINST APPLE'S TABLE, AND BY IDENTITY. Apple
publishes every code under exactly one category, and upload refuses a code that
is not valid for the category it is declared under (ITMS-91055) however well its
description seems to fit. Within a category the codes are neighbours with
different terms — who may declare them, what may leave the device — and upload
cannot tell whether the one declared is what the app does, so each is also
pinned to its use with the reason it fits and its neighbours do not. The table
is taken from Apple's page, never recalled or copied from a summary: a
description read against the wrong line of that list is plausible, lints,
parses, and is exactly the error this guards against (decision 0298).

Read by: CI's root job, via `testpaths` in pyproject.toml.
"""
from __future__ import annotations

import plistlib
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
MANIFEST = REPO / "ios/TheGoodGuest/TheGoodGuest/PrivacyInfo.xcprivacy"
IOS_SOURCE = REPO / "ios/TheGoodGuest"

# Apple's five required-reason API families, and the symbols that reach each.
# A category is "used" when any of its symbols appears in non-comment source.
API_FAMILIES = {
    "NSPrivacyAccessedAPICategoryUserDefaults": ("UserDefaults",),
    "NSPrivacyAccessedAPICategorySystemBootTime": (
        "CACurrentMediaTime", "systemUptime", "mach_absolute_time",
    ),
    "NSPrivacyAccessedAPICategoryFileTimestamp": (
        "contentModificationDateKey", "creationDateKey", "attributesOfItem",
        "NSFileModificationDate", "contentAccessDateKey",
    ),
    "NSPrivacyAccessedAPICategoryDiskSpace": (
        "volumeAvailableCapacity", "volumeTotalCapacity", "systemFreeSize",
        "statfs", "NSFileSystemFreeSize",
    ),
    "NSPrivacyAccessedAPICategoryActiveKeyboards": (
        "activeInputModes", "UITextInputMode",
    ),
}

# The reason each category is declared WITH, and why that code and not a
# neighbour in the same category. Changing the app's behaviour means changing
# these together; VALID_REASONS below is what each code covers.
EXPECTED_REASONS = {
    # CA92.1: information only the app itself reads and writes. Every call is
    # on `UserDefaults.standard` — no app-groups entitlement, no
    # UserDefaults(suiteName:) — so NOT 1C8F.1, the App Group reason.
    "NSPrivacyAccessedAPICategoryUserDefaults": {"CA92.1"},
    # 35F9.1: elapsed time between events in the app, and timers — and of what
    # is read under it, only that elapsed time may leave the device. Both uses
    # are that: the capture window, which BundleAssembler writes counted from
    # capture start rather than as read, and the camera-pose throttle's 20 Hz
    # gate. NOT 8FFB.1, which is for computing absolute timestamps: those may
    # leave the device, but boot time and anything else derived from it may not.
    "NSPrivacyAccessedAPICategorySystemBootTime": {"35F9.1"},
    # C617.1: metadata of files inside the app's own container, which is what
    # CaptureStorageSweeper reads to age out captures in
    # applicationSupportDirectory. NOT DDA9.1, which is for showing a file's
    # timestamp to the person — the sweeper shows nothing — and NOT 3B52.1,
    # for files the user granted access to through a picker.
    "NSPrivacyAccessedAPICategoryFileTimestamp": {"C617.1"},
}


def _swift_sources():
    """Every Swift file in the app, excluding the test target."""
    for path in IOS_SOURCE.rglob("*.swift"):
        if any("Tests" in part for part in path.parts):
            continue
        yield path


def _code_lines(path: Path) -> str:
    """Source with line comments stripped.

    Load-bearing rather than tidy: the generated `capture_bundle.pb.swift`
    mentions CACurrentMediaTime and mach_absolute_time in a docstring, and a
    scan that counted those would demand declarations for APIs the app may not
    call. The same trap runs the other way for DiskSpace, where a passing
    mention in a comment would manufacture a category out of nothing.
    """
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.lstrip()
        if stripped.startswith(("//", "///", "*", "/*")):
            continue
        out.append(line.split("//")[0])
    return "\n".join(out)


@pytest.fixture(scope="module")
def manifest():
    assert MANIFEST.exists(), (
        f"{MANIFEST.relative_to(REPO)} is missing — App Store submission "
        "requires it in the bundle"
    )
    with MANIFEST.open("rb") as fh:
        return plistlib.load(fh)


@pytest.fixture(scope="module")
def used_categories():
    """Which required-reason categories the shipping source actually reaches."""
    blobs = {p: _code_lines(p) for p in _swift_sources()}
    used = {}
    for category, symbols in API_FAMILIES.items():
        hits = sorted(
            p.relative_to(REPO).as_posix()
            for p, text in blobs.items()
            if any(s in text for s in symbols)
        )
        if hits:
            used[category] = hits
    return used


# ── The file itself ──────────────────────────────────────────────────────────

def test_the_manifest_parses(manifest):
    assert isinstance(manifest, dict)


def test_it_sits_where_the_app_target_will_bundle_it():
    """Beside the app's own sources, so the synchronized group carries it.

    Verified once by building and finding it at the .app root; pinned here so a
    reorganisation cannot move it somewhere that still lints and never ships.
    """
    assert MANIFEST.parent == REPO / "ios/TheGoodGuest/TheGoodGuest"


def test_no_tracking_is_claimed(manifest):
    assert manifest["NSPrivacyTracking"] is False
    assert manifest["NSPrivacyTrackingDomains"] == []


# ── The cross-check: the manifest against the source ─────────────────────────

def test_every_used_api_category_is_declared(manifest, used_categories):
    declared = {e["NSPrivacyAccessedAPIType"] for e in manifest["NSPrivacyAccessedAPITypes"]}
    missing = sorted(set(used_categories) - declared)
    detail = "; ".join(f"{c} used in {used_categories[c][0]}" for c in missing)
    assert not missing, (
        f"required-reason API used but not declared: {detail}. "
        "An undeclared category is ITMS-91053 at upload, not a warning."
    )


def test_no_category_is_declared_that_the_app_does_not_use(manifest, used_categories):
    declared = {e["NSPrivacyAccessedAPIType"] for e in manifest["NSPrivacyAccessedAPITypes"]}
    extra = sorted(declared - set(used_categories))
    assert not extra, (
        f"declared but unused: {extra}. The manifest states what this app does; "
        "an entry with no call site behind it is a claim that is not true."
    )


def test_disk_space_and_keyboards_stay_absent(used_categories):
    """Both are easy to acquire by accident and neither is used today.

    DiskSpace especially: CaptureRecovery's behaviour makes it look likely, and
    the labels document calls that out. Stated as its own test so the day one
    appears, the failure names the reason rather than only the count.
    """
    for category in ("NSPrivacyAccessedAPICategoryDiskSpace",
                     "NSPrivacyAccessedAPICategoryActiveKeyboards"):
        assert category not in used_categories, (
            f"{category} is now used ({used_categories.get(category)}) — declare it "
            "in PrivacyInfo.xcprivacy with the reason code that matches the use"
        )


# ── Reason codes ─────────────────────────────────────────────────────────────

# Apple's reason codes, under the one category each is published in: the
# NSPrivacyAccessedAPIType page, read 2026-09-15 rather than recalled. The notes
# are summaries so a failure reads without a browser; the page is the authority,
# and it also says what each code lets leave the device.
VALID_REASONS = {
    "NSPrivacyAccessedAPICategoryFileTimestamp": {
        "DDA9.1": "display file timestamps to the person using the device",
        "C617.1": "metadata of files in the app, App Group or CloudKit container",
        "3B52.1": "metadata of files the user granted access to",
        "0A2A.1": "a third-party SDK's wrapper around the API",
    },
    "NSPrivacyAccessedAPICategorySystemBootTime": {
        "35F9.1": "elapsed time between events in the app, or timers",
        "8FFB.1": "absolute timestamps for events in the app",
        "3D61.1": "an optional bug report the person chooses to submit",
    },
    "NSPrivacyAccessedAPICategoryDiskSpace": {
        "85F4.1": "display disk space to the person using the device",
        "E174.1": "check there is room to write, or delete files when space is low",
        "7D9E.1": "an optional bug report the person chooses to submit",
        "B728.1": "a health research app warning participants of low space",
    },
    "NSPrivacyAccessedAPICategoryActiveKeyboards": {
        "3EC4.1": "a custom keyboard app",
        "54BD.1": "customize the interface for the active keyboard",
    },
    "NSPrivacyAccessedAPICategoryUserDefaults": {
        "CA92.1": "information only the app itself can access",
        "1C8F.1": "information shared within the app's App Group",
        "C56D.1": "a third-party SDK's wrapper around the API",
        "AC6B.1": "MDM managed configuration and feedback keys",
    },
}

# "This reason may only be declared by third-party SDKs." An app that wraps an
# API for its own use — DismissedBundles over UserDefaults, say — is not one.
SDK_ONLY_REASONS = {"0A2A.1", "C56D.1"}


def test_each_category_carries_the_reason_that_matches_its_use(manifest):
    by_category = {
        e["NSPrivacyAccessedAPIType"]: set(e["NSPrivacyAccessedAPITypeReasons"])
        for e in manifest["NSPrivacyAccessedAPITypes"]
    }
    for category, expected in EXPECTED_REASONS.items():
        assert by_category.get(category) == expected, (
            f"{category} declares {by_category.get(category)}, expected {expected} — "
            "see EXPECTED_REASONS for why this code and not a neighbour"
        )


def test_every_declared_code_is_one_its_category_publishes(manifest):
    """A code from another category is refused at upload, however apt it reads.

    Codes from every category share one shape, so only Apple's table can tell
    which category a code belongs to. The failure names that category, since
    a code that reads right under the wrong one is the usual way in.
    """
    home = {code: cat for cat, reasons in VALID_REASONS.items() for code in reasons}
    wrong = []
    for entry in manifest["NSPrivacyAccessedAPITypes"]:
        category = entry["NSPrivacyAccessedAPIType"]
        valid = VALID_REASONS.get(category, {})
        for code in entry["NSPrivacyAccessedAPITypeReasons"]:
            if code in valid:
                continue
            where = (
                f"belongs to {home[code]} ({VALID_REASONS[home[code]][code]})"
                if code in home else "is not a reason code Apple publishes"
            )
            wrong.append(
                f"{category} declares {code}, which {where}; "
                f"this category's codes are {sorted(valid)}"
            )
    assert not wrong, "refused at upload as ITMS-91055:\n" + "\n".join(wrong)


def test_no_reason_reserved_for_third_party_sdks_is_declared(manifest):
    declared = {
        code
        for entry in manifest["NSPrivacyAccessedAPITypes"]
        for code in entry["NSPrivacyAccessedAPITypeReasons"]
    }
    assert not declared & SDK_ONLY_REASONS, (
        f"{sorted(declared & SDK_ONLY_REASONS)} may only be declared by a "
        "third-party SDK, in its own manifest — never by the app"
    )


def test_the_reason_table_gives_every_code_one_category():
    """The table has the shape of Apple's, which is what makes it a lookup.

    The five categories API_FAMILIES scans for, every code in Apple's format,
    no code under two categories, and the SDK-only codes among them.
    """
    assert set(VALID_REASONS) == set(API_FAMILIES)
    codes = [code for reasons in VALID_REASONS.values() for code in reasons]
    assert len(codes) == len(set(codes)), "a code is listed under two categories"
    for code in codes:
        assert re.fullmatch(r"[0-9A-F]{2}[0-9A-Z]{2}\.\d", code), (
            f"{code!r} is not Apple's reason-code shape"
        )
    assert SDK_ONLY_REASONS <= set(codes)


# ── Collected data types ─────────────────────────────────────────────────────

# Apple's published set, fetched from the documentation rather than recalled.
# A value outside it is refused at upload.
VALID_DATA_TYPES = {
    "NSPrivacyCollectedDataTypeAdvertisingData", "NSPrivacyCollectedDataTypeAudioData",
    "NSPrivacyCollectedDataTypeBrowsingHistory", "NSPrivacyCollectedDataTypeCoarseLocation",
    "NSPrivacyCollectedDataTypeContacts", "NSPrivacyCollectedDataTypeCrashData",
    "NSPrivacyCollectedDataTypeCreditInfo", "NSPrivacyCollectedDataTypeCustomerSupport",
    "NSPrivacyCollectedDataTypeDeviceID", "NSPrivacyCollectedDataTypeEmailAddress",
    "NSPrivacyCollectedDataTypeEmailsOrTextMessages",
    "NSPrivacyCollectedDataTypeEnvironmentScanning", "NSPrivacyCollectedDataTypeFitness",
    "NSPrivacyCollectedDataTypeGameplayContent", "NSPrivacyCollectedDataTypeHands",
    "NSPrivacyCollectedDataTypeHead", "NSPrivacyCollectedDataTypeHealth",
    "NSPrivacyCollectedDataTypeName", "NSPrivacyCollectedDataTypeOtherDataTypes",
    "NSPrivacyCollectedDataTypeOtherDiagnosticData",
    "NSPrivacyCollectedDataTypeOtherFinancialInfo",
    "NSPrivacyCollectedDataTypeOtherUsageData",
    "NSPrivacyCollectedDataTypeOtherUserContactInfo",
    "NSPrivacyCollectedDataTypeOtherUserContent", "NSPrivacyCollectedDataTypePaymentInfo",
    "NSPrivacyCollectedDataTypePerformanceData", "NSPrivacyCollectedDataTypePhoneNumber",
    "NSPrivacyCollectedDataTypePhotosorVideos", "NSPrivacyCollectedDataTypePhysicalAddress",
    "NSPrivacyCollectedDataTypePreciseLocation",
    "NSPrivacyCollectedDataTypeProductInteraction",
    "NSPrivacyCollectedDataTypePurchaseHistory", "NSPrivacyCollectedDataTypeSearchHistory",
    "NSPrivacyCollectedDataTypeSensitiveInfo", "NSPrivacyCollectedDataTypeUserID",
}

VALID_PURPOSES = {
    "NSPrivacyCollectedDataTypePurposeAnalytics",
    "NSPrivacyCollectedDataTypePurposeAppFunctionality",
    "NSPrivacyCollectedDataTypePurposeDeveloperAdvertising",
    "NSPrivacyCollectedDataTypePurposeOther",
    "NSPrivacyCollectedDataTypePurposeProductPersonalization",
    "NSPrivacyCollectedDataTypePurposeThirdPartyAdvertising",
}


def test_every_declared_data_type_is_one_apple_publishes(manifest):
    # "PhotosorVideos" is Apple's own spelling, lowercase "or" and all. Two
    # separate sources guessed "PhotosOrVideos" and "Photosvideo" while this
    # was being written, and either would have been refused at upload.
    for entry in manifest["NSPrivacyCollectedDataTypes"]:
        assert entry["NSPrivacyCollectedDataType"] in VALID_DATA_TYPES


def test_every_purpose_is_one_apple_publishes(manifest):
    for entry in manifest["NSPrivacyCollectedDataTypes"]:
        for purpose in entry["NSPrivacyCollectedDataTypePurposes"]:
            assert purpose in VALID_PURPOSES


def test_nothing_is_collected_for_tracking(manifest):
    """Consistency with NSPrivacyTracking above.

    A data type flagged for tracking while the top-level flag is false is a
    contradiction inside one file, and it is the shape a copied SDK example
    arrives in.
    """
    for entry in manifest["NSPrivacyCollectedDataTypes"]:
        assert entry["NSPrivacyCollectedDataTypeTracking"] is False, (
            f"{entry['NSPrivacyCollectedDataType']} claims tracking while "
            "NSPrivacyTracking is false"
        )


def test_the_sensitive_types_this_app_handles_are_declared(manifest):
    """The three nobody may quietly drop.

    Photographs of a home's interior, its measured geometry, and the id
    everything is keyed to. If a future edit narrows the manifest, these are
    the entries whose removal would matter most and be least visible.
    """
    declared = {e["NSPrivacyCollectedDataType"] for e in manifest["NSPrivacyCollectedDataTypes"]}
    for required in (
        "NSPrivacyCollectedDataTypePhotosorVideos",
        "NSPrivacyCollectedDataTypeEnvironmentScanning",
        "NSPrivacyCollectedDataTypeUserID",
    ):
        assert required in declared
