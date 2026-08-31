/// Pins the WIRE SHAPE of `force_remint` (decision 0116).
///
/// WHY THIS EXISTS AS A BYTES TEST: the whole reason the field is Optional is
/// what it does to the request an ordinary mint sends. Every deployed capture
/// path — the first send, the 401 retry, the 5xx ladder, the staleness re-mint —
/// must keep posting the exact 0035 body it posts today, because that body is
/// what the serving revision was verified against. A test that only checked
/// "the flag was passed" could not tell a request that omits the key from one
/// that sends `force_remint: false`, and the difference is precisely the risk.

import XCTest
@testable import TheGoodGuest

final class UploadSessionForceRemintTests: XCTestCase {

    private let manifest = [
        UploadManifestEntry(relativePath: "frames/000000.jpg", expectedSizeBytes: 1024),
        UploadManifestEntry(relativePath: "bundle.pb", expectedSizeBytes: 256),
    ]

    private func body(forceRemint: Bool, fcmToken: String? = nil) throws -> [String: Any] {
        let data = try UploadSessionClient.encodedRequestBody(
            manifest: manifest, fcmToken: fcmToken, forceRemint: forceRemint)
        return try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
    }

    /// THE COMPATIBILITY PIN. An ordinary mint's body must be byte-shape
    /// identical to the deployed contract: the key is absent, not false, not null.
    func testOrdinaryMintDoesNotPutTheKeyOnTheWireAtAll() throws {
        let json = try body(forceRemint: false)
        XCTAssertNil(json.index(forKey: "force_remint"),
                     "an ordinary mint must send no force_remint key: \(json)")
        XCTAssertNotNil(json["manifest"])
    }

    /// And the raw bytes carry no mention of it — `index(forKey:)` above would
    /// pass for a key whose value happened to serialise oddly.
    func testOrdinaryMintBytesNeverMentionForceRemint() throws {
        let data = try UploadSessionClient.encodedRequestBody(
            manifest: manifest, fcmToken: nil, forceRemint: false)
        let text = try XCTUnwrap(String(data: data, encoding: .utf8))
        XCTAssertFalse(text.contains("force_remint"), text)
    }

    func testForcedMintSendsTrue() throws {
        let json = try body(forceRemint: true)
        XCTAssertEqual(json["force_remint"] as? Bool, true, "\(json)")
    }

    /// The manifest is unchanged by the flag: it still answers "WHAT do I intend
    /// to upload", which is the separation decision 0116 is built on.
    func testTheFlagDoesNotDisturbTheManifest() throws {
        for force in [false, true] {
            let json = try body(forceRemint: force)
            let entries = try XCTUnwrap(json["manifest"] as? [[String: Any]])
            XCTAssertEqual(entries.count, 2)
            XCTAssertEqual(entries.first?["relative_path"] as? String, "frames/000000.jpg")
            XCTAssertEqual(entries.first?["expected_size_bytes"] as? Int, 1024)
        }
    }

    /// fcm_token keeps its own independent nil/present behaviour — the new field
    /// must not have changed how the existing optional encodes.
    func testFcmTokenIsStillOmittedWhenNil_andSentWhenPresent() throws {
        XCTAssertNil(try body(forceRemint: false).index(forKey: "fcm_token"))
        XCTAssertEqual(try body(forceRemint: false, fcmToken: "tok")["fcm_token"] as? String, "tok")
    }
}
