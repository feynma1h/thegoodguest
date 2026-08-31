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

REASON CODES ARE CHECKED BY IDENTITY, NOT JUST VALIDITY. Every code below was
wrong in the draft this manifest was written from, in the specific way that is
easy to miss: the codes are per-category and several are plausible for any given
category, so a copied example lints, parses, and is refused at upload as
ITMS-91055. Two of the three shipped here differ from that draft — see the
comments on each — and pinning the exact string is what stops a future edit
reverting to the plausible one.

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
# neighbour. Changing the app's behaviour means changing these together.
EXPECTED_REASONS = {
    # 54BD.1 is "only accessible to the app itself". NOT CA92.1, which is the
    # App Group case — this app has no app-groups entitlement and no
    # UserDefaults(suiteName:), only `.standard`.
    "NSPrivacyAccessedAPICategoryUserDefaults": {"54BD.1"},
    # Both uses are real: absolute in-app timestamps on the capture bundle
    # (35F9.1) and elapsed time in the camera-pose throttle (0A2A.1).
    "NSPrivacyAccessedAPICategorySystemBootTime": {"35F9.1", "0A2A.1"},
    # DDA9.1 is "files inside the app container". NOT C617.1, which is for
    # files the user granted access to through a document picker — there is no
    # document picker in this app, and the swept directory is
    # applicationSupportDirectory.
    "NSPrivacyAccessedAPICategoryFileTimestamp": {"DDA9.1"},
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


def test_reason_codes_are_well_formed(manifest):
    for entry in manifest["NSPrivacyAccessedAPITypes"]:
        for code in entry["NSPrivacyAccessedAPITypeReasons"]:
            assert re.fullmatch(r"[0-9A-F]{2}[0-9A-Z]{2}\.\d", code), (
                f"{code!r} is not Apple's reason-code shape"
            )


def test_the_two_corrected_codes_do_not_come_back(manifest):
    """CA92.1 and C617.1 both lint, both parse, and both are wrong here.

    They are what the drafted manifest carried, so they are exactly what a
    future edit working from that draft would restore.
    """
    all_codes = {
        code
        for entry in manifest["NSPrivacyAccessedAPITypes"]
        for code in entry["NSPrivacyAccessedAPITypeReasons"]
    }
    assert "CA92.1" not in all_codes, "CA92.1 is the App Group reason; this app has none"
    assert "C617.1" not in all_codes, "C617.1 is the document-picker reason; there is no picker"


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
