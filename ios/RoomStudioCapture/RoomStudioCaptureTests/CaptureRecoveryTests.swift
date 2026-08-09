/// Pins CaptureRecovery — the decision of whether a `failed_incomplete` capture
/// can honestly be offered a re-send.
///
/// WHY THIS EXISTS: the screen's promise is downstream of this table. Decision
/// 0084's honesty constraint used to be absolute ("never promise a re-upload,
/// there is none"); with force_remint it became CONDITIONAL, and a conditional
/// invariant is only as good as the condition. Every way the condition can be
/// false — the bytes gone, the paths unknown, nothing named — is a way the
/// button lies, so each one is a row here.
///
/// Decisions: 0084 (the coordinator + the honesty constraint), 0116
/// (force_remint), 0040 (bundle.pb is never a Phase-1 upload).

import XCTest
@testable import RoomStudioCapture

final class CaptureRecoveryTests: XCTestCase {

    private let manifest = [
        "frames/000000.jpg", "frames/000001.jpg", "frames/000002.jpg",
        "depth/000000.f32", "bundle.pb",
    ]

    /// Everything on disk.
    private let allPresent: (String) -> Bool = { _ in true }

    // MARK: - The offer

    func testOffersAReSendWhenEveryNamedFileIsOnDisk() {
        let plan = CaptureRecovery.plan(
            missingPaths: ["frames/000001.jpg", "depth/000000.f32"],
            manifestPaths: manifest,
            fileExists: allPresent
        )
        XCTAssertEqual(plan, .resend(blobs: ["depth/000000.f32", "frames/000001.jpg"]))
    }

    /// Sorted and de-duplicated: the same list must produce the same manifest
    /// whatever order the server happened to answer in, because that manifest is
    /// the server's own idempotency key.
    func testBlobListIsDeterministic() {
        let a = CaptureRecovery.plan(
            missingPaths: ["frames/000002.jpg", "frames/000000.jpg", "frames/000002.jpg"],
            manifestPaths: manifest, fileExists: allPresent)
        let b = CaptureRecovery.plan(
            missingPaths: ["frames/000000.jpg", "frames/000002.jpg"],
            manifestPaths: manifest, fileExists: allPresent)
        XCTAssertEqual(a, b)
        XCTAssertEqual(a, .resend(blobs: ["frames/000000.jpg", "frames/000002.jpg"]))
    }

    // MARK: - bundle.pb is never a Phase-1 blob (decision 0040)

    /// The ordering invariant at its source. bundle.pb's arrival in GCS is the
    /// ingest signal, so it must be the LAST thing sent; the executor sends it
    /// through the Phase-1 gate, never alongside the blobs. If the server ever
    /// names it (it cannot today — its arrival is what ran the check that
    /// produced this failure), it must not become an ordinary blob upload.
    func testBundlePbIsNeverInTheBlobList() {
        let plan = CaptureRecovery.plan(
            missingPaths: ["bundle.pb", "frames/000000.jpg"],
            manifestPaths: manifest, fileExists: allPresent)
        XCTAssertEqual(plan, .resend(blobs: ["frames/000000.jpg"]))
    }

    /// bundle.pb ALONE is not a re-send: there would be no blob to send before
    /// it, and re-PUTting the finalize by itself asks ingest to re-check a set
    /// of files nothing has changed.
    func testBundlePbAloneIsNotAReSend() {
        XCTAssertEqual(
            CaptureRecovery.plan(missingPaths: ["bundle.pb"],
                                 manifestPaths: manifest, fileExists: allPresent),
            .rescanOnly(.serverNamedNoPaths))
    }

    /// The re-mint path-set always carries exactly one bundle.pb — both because
    /// the server's manifest grammar requires it and because its stored session
    /// was consumed by the upload that produced this failure.
    func testMintPathsAlwaysEndWithExactlyOneBundlePb() {
        XCTAssertEqual(CaptureRecovery.mintPaths(for: ["frames/000000.jpg"]),
                       ["frames/000000.jpg", "bundle.pb"])
        // Defensive: a caller that passed bundle.pb through anyway must not
        // produce a manifest the server rejects for having two.
        let paths = CaptureRecovery.mintPaths(for: ["bundle.pb", "frames/000000.jpg"])
        XCTAssertEqual(paths.filter { $0 == "bundle.pb" }.count, 1, "\(paths)")
        XCTAssertEqual(paths.last, "bundle.pb")
    }

    // MARK: - The refusals (each one is a way the button would lie)

    /// `missing_paths` is optional on the wire and the poller defaults it to [].
    func testRefusesWhenTheServerNamedNothing() {
        XCTAssertEqual(
            CaptureRecovery.plan(missingPaths: [], manifestPaths: manifest, fileExists: allPresent),
            .rescanOnly(.serverNamedNoPaths))
    }

    /// A path this capture's manifest never carried cannot be given a manifest
    /// entry, so it cannot be re-minted, so it cannot be promised.
    func testRefusesPathsThisCaptureNeverHad() {
        XCTAssertEqual(
            CaptureRecovery.plan(missingPaths: ["frames/999999.jpg"],
                                 manifestPaths: manifest, fileExists: allPresent),
            .rescanOnly(.pathsNotInThisCapture(["frames/999999.jpg"])))
    }

    /// THE CASE THE HONESTY CONSTRAINT IS ABOUT. Decision 0084's reaper retains
    /// the files on failed_incomplete precisely so this is rare — but an
    /// iCloud-migrated record (decision 0074) carries no blobs at all, and a
    /// storage sweep can take the directory. One absent file is enough: the
    /// bundle references it, so ingest will report it missing again.
    func testRefusesWhenAMissingFileIsGoneFromDisk() {
        let plan = CaptureRecovery.plan(
            missingPaths: ["frames/000000.jpg", "frames/000001.jpg"],
            manifestPaths: manifest,
            fileExists: { $0 != "frames/000001.jpg" }
        )
        XCTAssertEqual(plan, .rescanOnly(.filesGone(["frames/000001.jpg"])))
    }

    /// bundle.pb is checked with the blobs, not after them: it is re-sent on
    /// every recovery, so its absence blocks the re-send exactly as a blob's
    /// does. Without this the plan would offer a send that could deliver the
    /// blobs and then never fire the finalize that re-triggers ingest —
    /// stranding the capture in the same state it started in.
    func testRefusesWhenBundlePbItselfIsGone() {
        let plan = CaptureRecovery.plan(
            missingPaths: ["frames/000000.jpg"],
            manifestPaths: manifest,
            fileExists: { $0 != "bundle.pb" }
        )
        XCTAssertEqual(plan, .rescanOnly(.filesGone(["bundle.pb"])))
    }

    /// Refusal order: an unknown path is reported as unknown even if it is also
    /// absent from disk. Both are true; "we never had this" is the more precise
    /// statement and the one worth logging.
    func testUnknownPathsAreReportedBeforeMissingFiles() {
        let plan = CaptureRecovery.plan(
            missingPaths: ["frames/999999.jpg"],
            manifestPaths: manifest,
            fileExists: { _ in false }
        )
        XCTAssertEqual(plan, .rescanOnly(.pathsNotInThisCapture(["frames/999999.jpg"])))
    }

    /// The disk is consulted for every named blob, not just the first — a plan
    /// that short-circuits would offer a send that fails on the second file.
    func testEveryAbsentFileIsNamed() {
        let plan = CaptureRecovery.plan(
            missingPaths: ["frames/000000.jpg", "frames/000001.jpg", "frames/000002.jpg"],
            manifestPaths: manifest,
            fileExists: { $0 == "frames/000001.jpg" || $0 == "bundle.pb" }
        )
        XCTAssertEqual(plan, .rescanOnly(.filesGone(["frames/000000.jpg", "frames/000002.jpg"])))
    }
}
