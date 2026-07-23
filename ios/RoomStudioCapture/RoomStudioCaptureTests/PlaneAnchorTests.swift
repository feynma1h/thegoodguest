/// Unit tests for ARPlaneAnchor → proto conversion (decision 0066).
///
/// No AR session required — the pure PlaneAnchorExtractor functions take
/// simd/primitive inputs, mirroring PoseTests' approach. The invariants
/// pinned here are the ones the backend shell stage joins on: pose is
/// world_from_anchor with proto (x,y,z,w) quaternion order, boundary is
/// flattened (x,z) pairs, alignment/classification map losslessly, and
/// BundleAssembler carries the set into bundle.pb verbatim.

import ARKit
import SwiftProtobuf
import XCTest
import simd
@testable import RoomStudioCapture

final class PlaneAnchorTests: XCTestCase {

    // MARK: - Pose from transform

    /// Hand-derived: +90° about X with a known translation. The rotation
    /// carries anchor-local +Y (the plane normal) to world +Z — the wall
    /// orientation the backend reconstructs. Quat (x,y,z,w) =
    /// (sin45°, 0, 0, cos45°); position is column 3 verbatim.
    func testPoseFromTransform_90degAboutX() {
        let q = simd_quatf(angle: .pi / 2, axis: simd_float3(1, 0, 0))
        var t = matrix_float4x4(q)
        t.columns.3 = simd_float4(0.5, -1.2, 2.0, 1)

        let pose = PlaneAnchorExtractor.pose(fromTransform: t)
        let r = Float(1.0 / 2.0.squareRoot())
        XCTAssertEqual(pose.posX,  0.5, accuracy: 1e-5)
        XCTAssertEqual(pose.posY, -1.2, accuracy: 1e-5)
        XCTAssertEqual(pose.posZ,  2.0, accuracy: 1e-5)
        XCTAssertEqual(pose.quatX, r,   accuracy: 1e-5, "quat_x")
        XCTAssertEqual(pose.quatY, 0,   accuracy: 1e-5, "quat_y")
        XCTAssertEqual(pose.quatZ, 0,   accuracy: 1e-5, "quat_z")
        XCTAssertEqual(pose.quatW, r,   accuracy: 1e-5, "quat_w (real part)")

        // Semantic check, not just components: the extracted quaternion
        // must map anchor +Y to world +Z (rotate, compare).
        let extracted = simd_quatf(ix: pose.quatX, iy: pose.quatY, iz: pose.quatZ, r: pose.quatW)
        let normal = extracted.act(simd_float3(0, 1, 0))
        XCTAssertEqual(normal.x, 0, accuracy: 1e-5)
        XCTAssertEqual(normal.y, 0, accuracy: 1e-5)
        XCTAssertEqual(normal.z, 1, accuracy: 1e-5)
    }

    func testPoseFromTransform_unitNorm() {
        let q = simd_quatf(angle: 1.1, axis: simd_normalize(simd_float3(0.3, 0.8, -0.5)))
        let t = matrix_float4x4(q)
        let pose = PlaneAnchorExtractor.pose(fromTransform: t)
        let norm = sqrt(
            pose.quatX * pose.quatX + pose.quatY * pose.quatY
            + pose.quatZ * pose.quatZ + pose.quatW * pose.quatW
        )
        XCTAssertEqual(norm, 1.0, accuracy: 1e-3, "backend rejects non-unit quats")
    }

    // MARK: - Boundary flattening

    func testFlattenBoundary_dropsYKeepsOrder() {
        let verts = [
            simd_float3(-1.0, 0.001, -0.5),
            simd_float3( 1.0, -0.002, -0.5),
            simd_float3( 1.0, 0.0,     0.5),
        ]
        let flat = PlaneAnchorExtractor.flattenBoundary(verts)
        XCTAssertEqual(flat.count, 6, "one (x,z) pair per vertex")
        XCTAssertEqual(flat, [-1.0, -0.5, 1.0, -0.5, 1.0, 0.5], "x,z pairs in vertex order")
        XCTAssertEqual(flat.count % 2, 0, "even length by construction")
    }

    func testFlattenBoundary_emptyIsEmpty() {
        XCTAssertEqual(PlaneAnchorExtractor.flattenBoundary([]), [])
    }

    // MARK: - Alignment mapping

    func testAlignmentMapping() {
        XCTAssertEqual(PlaneAnchorExtractor.alignment(from: .horizontal), .horizontal)
        XCTAssertEqual(PlaneAnchorExtractor.alignment(from: .vertical), .vertical)
    }

    // MARK: - Classification mapping

    /// Known classes map to the proto's lowercase canon; .none (any
    /// status) is "" = unclassified — never a guess.
    func testClassificationMapping() {
        XCTAssertEqual(PlaneAnchorExtractor.classificationString(from: .wall), "wall")
        XCTAssertEqual(PlaneAnchorExtractor.classificationString(from: .floor), "floor")
        XCTAssertEqual(PlaneAnchorExtractor.classificationString(from: .ceiling), "ceiling")
        XCTAssertEqual(PlaneAnchorExtractor.classificationString(from: .table), "table")
        XCTAssertEqual(PlaneAnchorExtractor.classificationString(from: .seat), "seat")
        XCTAssertEqual(PlaneAnchorExtractor.classificationString(from: .window), "window")
        XCTAssertEqual(PlaneAnchorExtractor.classificationString(from: .door), "door")
        XCTAssertEqual(PlaneAnchorExtractor.classificationString(from: .none(.notAvailable)), "")
        XCTAssertEqual(PlaneAnchorExtractor.classificationString(from: .none(.undetermined)), "")
        XCTAssertEqual(PlaneAnchorExtractor.classificationString(from: .none(.unknown)), "")
    }

    // MARK: - Full assembly

    func testPlaneAnchorAssembly_allFields() {
        let q = simd_quatf(angle: .pi / 2, axis: simd_float3(1, 0, 0))
        var t = matrix_float4x4(q)
        t.columns.3 = simd_float4(1.0, 0.2, -3.0, 1)

        let anchor = PlaneAnchorExtractor.planeAnchor(
            transform:        t,
            center:           simd_float3(0.1, 0.0, -0.2),
            extentWidth:      3.25,
            extentHeight:     2.5,
            rotationOnYRad:   0.125,
            alignment:        .vertical,
            classification:   "wall",
            boundaryVertices: [simd_float3(-1, 0, -1), simd_float3(1, 0, 1)]
        )

        XCTAssertEqual(anchor.centerX, 0.1, accuracy: 1e-6)
        XCTAssertEqual(anchor.centerY, 0.0, accuracy: 1e-6)
        XCTAssertEqual(anchor.centerZ, -0.2, accuracy: 1e-6)
        XCTAssertEqual(anchor.extentWidth, 3.25, accuracy: 1e-6)
        XCTAssertEqual(anchor.extentHeight, 2.5, accuracy: 1e-6)
        XCTAssertEqual(anchor.rotationOnYRad, 0.125, accuracy: 1e-6)
        XCTAssertEqual(anchor.alignment, .vertical)
        XCTAssertEqual(anchor.classification, "wall")
        XCTAssertEqual(anchor.boundaryXz, [-1, -1, 1, 1])
        XCTAssertEqual(anchor.pose.posZ, -3.0, accuracy: 1e-5)
    }

    // MARK: - BundleAssembler carries planes into bundle.pb

    /// The end of the client-side chain: a written bundle.pb parses back
    /// with the anchor set verbatim, and an empty set stays empty (the
    /// wire shape every pre-plane bundle already has).
    func testBundleAssembler_roundTripsPlaneAnchors() throws {
        let dir = FileManager.default.temporaryDirectory
            .appendingPathComponent("plane-anchor-test-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: dir) }

        let anchor = PlaneAnchorExtractor.planeAnchor(
            transform:        matrix_float4x4(diagonal: simd_float4(1, 1, 1, 1)),
            center:           simd_float3(0, 0, 0),
            extentWidth:      2.0,
            extentHeight:     1.5,
            rotationOnYRad:   0,
            alignment:        .horizontal,
            classification:   "floor",
            boundaryVertices: []
        )

        let assembler = BundleAssembler(
            bundleId:          UUID(),
            tier:              .arkitOnly,
            startedAtDeviceUs: 1_000,
            endedAtDeviceUs:   2_000,
            startedAtWallUs:   3_000,
            frames:            [],
            planeAnchors:      [anchor],
            outputDir:         dir
        )
        let url = try assembler.write(userId: "test-user")
        let parsed = try RSCaptureBundle(serializedBytes: Data(contentsOf: url))

        XCTAssertEqual(parsed.planeAnchors.count, 1)
        XCTAssertEqual(parsed.planeAnchors[0].classification, "floor")
        XCTAssertEqual(parsed.planeAnchors[0].alignment, .horizontal)
        XCTAssertEqual(parsed.planeAnchors[0].extentWidth, 2.0, accuracy: 1e-6)
        XCTAssertEqual(parsed.planeAnchors[0].pose.quatW, 1.0, accuracy: 1e-6)
    }

    func testBundleAssembler_emptyPlanesStaysEmpty() throws {
        let dir = FileManager.default.temporaryDirectory
            .appendingPathComponent("plane-anchor-test-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: dir) }

        let assembler = BundleAssembler(
            bundleId:          UUID(),
            tier:              .arkitOnly,
            startedAtDeviceUs: 1_000,
            endedAtDeviceUs:   2_000,
            startedAtWallUs:   3_000,
            frames:            [],
            planeAnchors:      [],
            outputDir:         dir
        )
        let url = try assembler.write(userId: "test-user")
        let parsed = try RSCaptureBundle(serializedBytes: Data(contentsOf: url))
        XCTAssertTrue(parsed.planeAnchors.isEmpty)
    }
}
