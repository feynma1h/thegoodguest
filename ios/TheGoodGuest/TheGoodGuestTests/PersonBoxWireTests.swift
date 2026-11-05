/// Pins for the boxes in the capture bundle (decisions 0320, 0321): which kept
/// boxes are written, in what form, and that a bundle with none is unchanged.

import simd
import SwiftProtobuf
import XCTest
@testable import TheGoodGuest

final class PersonBoxWireTests: XCTestCase {

    private func kept(_ label: String = "chair", at c: SIMD3<Float> = SIMD3(1.5, 0.45, -2.25), yaw: Float = 0.5,
                      size: SIMD3<Float> = SIMD3(0.5, 0.9, 0.6), made: Int64 = 5_000_000,
                      id: UUID = UUID()) -> KeptBox {
        KeptBox(id: id, detectorLabel: label, center: c, yaw: yaw, size: size, madeAtDeviceUs: made)
    }

    func test_aKeptBox_isWrittenWithEveryFieldAndItsTimeSinceCaptureStart() {
        let id = UUID()
        let wire = PersonBoxWire.messages([kept("dining table", id: id)], startedAtDeviceUs: 2_000_000)
        XCTAssertEqual(wire.count, 1)
        let m = wire[0]
        XCTAssertEqual(m.boxID, id.uuidString.lowercased())
        XCTAssertEqual(m.detectorLabel, "dining table")
        XCTAssertEqual([m.centerX, m.centerY, m.centerZ], [1.5, 0.45, -2.25])
        XCTAssertEqual(m.yawRad, 0.5)
        XCTAssertEqual([m.sizeX, m.sizeY, m.sizeZ], [0.5, 0.9, 0.6])
        XCTAssertEqual(m.createdAtDeviceUs, 3_000_000, "since capture start, never the device-boot reading (0298)")
    }

    func test_boxesAreWrittenInTheOrderTheyWereMade() {
        let wire = PersonBoxWire.messages([kept("b", made: 9), kept("a", made: 3), kept("c", made: 6)], startedAtDeviceUs: 0)
        XCTAssertEqual(wire.map(\.detectorLabel), ["a", "c", "b"])
    }

    func test_aBoxThatCannotBeAnObjectIsLeftOut_notRepaired() {
        let bad: [KeptBox] = [
            kept(at: SIMD3(.nan, 0, 0)),
            kept(yaw: .infinity),
            kept(size: SIMD3(0.04, 0.5, 0.5)),
            kept(size: SIMD3(0.5, 6.1, 0.5)),
            kept(size: SIMD3(0.5, 0.5, 0)),
        ]
        XCTAssertTrue(PersonBoxWire.messages(bad, startedAtDeviceUs: 0).isEmpty)
        XCTAssertEqual(PersonBoxWire.messages([kept(size: SIMD3(0.05, 6, 0.05))], startedAtDeviceUs: 0).count, 1,
                       "the range's own ends are allowed")
    }

    func test_aRepeatedId_keepsTheFirstBox() {
        let id = UUID()
        let wire = PersonBoxWire.messages([kept("second", made: 2, id: id), kept("first", made: 1, id: id)], startedAtDeviceUs: 0)
        XCTAssertEqual(wire.map(\.detectorLabel), ["first"])
    }

    func test_pastTheLimit_theEarliestBoxesAreKept_andTheBundleIsNotRejected() {
        let many = (0..<(PersonBoxWire.maxBoxes + 5)).map { kept("n\($0)", made: Int64($0)) }
        let wire = PersonBoxWire.messages(many.reversed(), startedAtDeviceUs: 0)
        XCTAssertEqual(wire.count, PersonBoxWire.maxBoxes)
        XCTAssertEqual(wire.first?.detectorLabel, "n0")
        XCTAssertEqual(wire.last?.detectorLabel, "n\(PersonBoxWire.maxBoxes - 1)")
    }

    // MARK: Through the assembler

    private func bundle(boxes: [KeptBox]) throws -> RSCaptureBundle {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("person-box-test-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: dir) }
        let assembler = BundleAssembler(
            bundleId: UUID(), tier: .arkitOnly,
            startedAtDeviceUs: 1_000_000, endedAtDeviceUs: 9_000_000, startedAtWallUs: 3_000,
            frames: [], planeAnchors: [], personBoxes: boxes, roomPlan: nil, outputDir: dir)
        let url = try assembler.write(userId: "test-user")
        return try RSCaptureBundle(serializedBytes: Data(contentsOf: url))
    }

    func test_theBundleCarriesTheKeptBoxes_withoutTouchingTheSchemaVersion() throws {
        let parsed = try bundle(boxes: [kept("chair", made: 4_000_000), kept("sofa", made: 6_000_000)])
        XCTAssertEqual(parsed.personBoxes.map(\.detectorLabel), ["chair", "sofa"])
        XCTAssertEqual(parsed.personBoxes.map(\.createdAtDeviceUs), [3_000_000, 5_000_000])
        XCTAssertEqual(parsed.schemaVersion, "1")
    }

    func test_aBundleWithNoKeptBoxes_carriesNone() throws {
        XCTAssertTrue(try bundle(boxes: []).personBoxes.isEmpty)
    }
}
