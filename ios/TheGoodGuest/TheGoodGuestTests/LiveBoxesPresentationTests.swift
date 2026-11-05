/// Pins for what the camera layer draws: the scene is a dot for every found
/// object and a box for every boxed one, all alike and unnamed; a table's box
/// reaches its top; one object at a time wears a dot; and a box is twelve solid
/// rods.

import simd
import XCTest
@testable import TheGoodGuest

final class LiveBoxesPresentationTests: XCTestCase {

    private func track(_ label: String, at c: SIMD3<Float>, hits: Int, misses: Int = 0, arc: Int = 90,
                       size: SIMD3<Float> = SIMD3(0.4, 0.2, 0.4), id: UUID = UUID()) -> TrackSummary {
        TrackSummary(id: id, label: label, name: label.lowercased(), bestScore: 0.8, hits: hits, misses: misses, arcDegrees: arc,
                     confirmed: true, box: GravityBox(center: c, size: size, yaw: 0))
    }

    // MARK: What the bundle carries

    func test_theBundleCarriesTheBoxesDrawn_namedByTheDetector_andNothingElse() {
        let lamp = track("LAMP", at: SIMD3(0, 0.5, -2), hits: 10)
        let toy = track("TOY", at: SIMD3(1, 0.1, -2), hits: 10)
        let kept = LiveBoxesPresentation.kept([lamp, toy], boxed: [lamp.id], madeAt: [lamp.id: 42], now: 99)
        XCTAssertEqual(kept.map(\.id), [lamp.id], "an object with only a dot is not sent")
        XCTAssertEqual(kept.first?.detectorLabel, "lamp", "the detector's own name, not the vocabulary's label")
        XCTAssertEqual(kept.first?.madeAtDeviceUs, 42)
        let drawn = LiveBoxesPresentation.scene([lamp, toy], boxed: [lamp.id], current: nil).boxes.first?.box
        XCTAssertEqual(kept.first?.center, drawn?.center)
        XCTAssertEqual(kept.first?.size, drawn?.size)
        XCTAssertEqual(kept.first?.yaw, drawn?.yaw)
    }

    func test_aBoxedObjectFusionMergedAway_isNotSent() {
        let gone = UUID()
        let lamp = track("LAMP", at: SIMD3(0, 0.5, -2), hits: 10)
        let kept = LiveBoxesPresentation.kept([lamp], boxed: [lamp.id, gone], madeAt: [:], now: 99)
        XCTAssertEqual(kept.map(\.id), [lamp.id])
        XCTAssertEqual(kept.first?.madeAtDeviceUs, 99, "with no time on record it is stamped now")
    }

    func test_nothingBoxed_sendsNothing() {
        let lamp = track("LAMP", at: SIMD3(0, 0.5, -2), hits: 10)
        XCTAssertTrue(LiveBoxesPresentation.kept([lamp], boxed: [], madeAt: [:], now: 0).isEmpty)
    }

    func test_nothingFound_drawsNothing() {
        XCTAssertEqual(LiveBoxesPresentation.scene([], boxed: [UUID()], current: nil), LiveBoxesScene())
    }

    func test_everyObjectFoundWearsADot_andABoxedOneWearsABoxInstead() {
        let lamp = track("LAMP", at: SIMD3(0, 0.5, -2), hits: 10)
        let toy = track("TOY", at: SIMD3(1, 0.1, -2), hits: 10)
        let scene = LiveBoxesPresentation.scene([lamp, toy], boxed: [lamp.id], current: lamp.id)
        XCTAssertEqual(scene.dots.filter { !$0.boxed }.map(\.id), [toy.id])
        XCTAssertEqual(scene.boxes.map(\.id), [lamp.id])
        XCTAssertEqual(scene.boxes.first?.current, true)
    }

    func test_oneObjectAtATime_whileABoxIsBeingWorkedOn_noOtherObjectWearsADot() {
        let lamp = track("LAMP", at: SIMD3(0, 0.5, -2), hits: 10)
        let toy = track("TOY", at: SIMD3(1, 0.1, -2), hits: 10)
        let scene = LiveBoxesPresentation.scene([lamp, toy], boxed: [lamp.id], current: lamp.id, locked: true)
        XCTAssertTrue(scene.dots.filter { !$0.boxed }.isEmpty)
        XCTAssertEqual(scene.boxes.count, 1, "the box itself stays")
    }

    func test_aTrackOfABoxedObject_getsNoDot_whateverItsSightings() {
        let boxed = track("CUSHION", at: SIMD3(1.3, 0.2, -2.1), hits: 3)
        let twin = track("CUSHION", at: SIMD3(1.3, 0.2, -2.0), hits: 40)
        let scene = LiveBoxesPresentation.scene([boxed, twin], boxed: [boxed.id], current: nil)
        XCTAssertTrue(scene.dots.filter { !$0.boxed }.isEmpty)
    }

    func test_everyBoxIsDrawnTheSameWay_nothingIsADimGuess() {
        // A glass table whose outlines pin nothing was once drawn dim; its box is like any other.
        let glass = TrackSummary(id: UUID(), label: "TABLE", name: "glass table", bestScore: 0.8, hits: 20, arcDegrees: 40,
                                 confirmed: true, seenThrough: true, outlinesPinned: false,
                                 box: GravityBox(center: SIMD3(0, 0.2, 0), size: SIMD3(1.2, 0.4, 0.6), yaw: 0))
        let scene = LiveBoxesPresentation.scene([glass], boxed: [glass.id], current: nil)
        XCTAssertEqual(scene.boxes.count, 1)
        XCTAssertEqual(scene.dots.first?.probes.count, 9, "and it is tested against walls like the rest")
    }

    func test_onlyATablesBoxIsExtendedToItsTop() {
        let at = SIMD3<Float>(0.3, 0.37, 0)
        let top = HorizontalSurface(kind: .support, height: 0.75,
                                    extent: PlanRectangle(center: SIMD2(0, 0), axis: SIMD2(1, 0), halfExtents: SIMD2(0.8, 0.4)))
        let desk = track("DESK", at: at, hits: 20, size: SIMD3(0.6, 0.74, 0.7))
        let chair = track("CHAIR", at: at + SIMD3(0, 0, 3), hits: 20, size: SIMD3(0.6, 0.74, 0.7))
        let scene = LiveBoxesPresentation.scene([desk, chair], boxed: [desk.id, chair.id], current: nil, tops: [top])
        let sizes = Dictionary(uniqueKeysWithValues: scene.boxes.map { ($0.id, $0.box.size.x) })
        XCTAssertEqual(sizes[desk.id] ?? 0, 1.6, accuracy: 0.05)
        XCTAssertEqual(sizes[chair.id] ?? 0, 0.6, accuracy: 0.01)
    }

    func test_theWords() {
        XCTAssertEqual(LiveBoxesPresentation.countLabel(1), "1 box")
        XCTAssertEqual(LiveBoxesPresentation.countLabel(3), "3 boxes")
        let id = UUID()
        XCTAssertEqual(LiveBoxesPresentation.Toast.added(id).label, "Box added  ·  Undo")
        XCTAssertEqual(LiveBoxesPresentation.Toast.removed(id).label, "Box removed  ·  Undo")
    }

    func test_aBoxNeedsAWalkAround_whenItIsBigAndSeenFromOneSide() {
        let big = track("TABLE", at: .zero, hits: 20, arc: 30, size: SIMD3(1.6, 0.74, 0.8))
        XCTAssertTrue(LiveBoxesPresentation.needsWalkAround(big))
        XCTAssertFalse(LiveBoxesPresentation.needsWalkAround(track("TABLE", at: .zero, hits: 20, arc: 90, size: SIMD3(1.6, 0.74, 0.8))))
        XCTAssertFalse(LiveBoxesPresentation.needsWalkAround(nil))
    }

    func test_aBoxIsTwelveSolidRods() {
        let box = GravityBox(center: SIMD3(1, 0.4, -1), size: SIMD3(0.6, 0.8, 0.4), yaw: 0.3)
        let (positions, indices) = BoxWireframe.mesh([box], thickness: 0.008)
        XCTAssertEqual(positions.count, BoxWireframe.verticesPerBox)
        XCTAssertEqual(indices.count, BoxWireframe.indicesPerBox)
        XCTAssertEqual(BoxWireframe.mesh([box, box], thickness: 0.008).positions.count, 2 * BoxWireframe.verticesPerBox)
        // Every rod reaches half a thickness past the box's own extent, so the rods meet at the corners.
        let local = positions.map { p -> SIMD3<Float> in
            let q = box.transform.inverse * SIMD4(p, 1)
            return SIMD3(q.x, q.y, q.z)
        }
        XCTAssertEqual(local.map(\.x).max() ?? 0, 0.3 + 0.004, accuracy: 1e-4)
        XCTAssertEqual(local.map(\.y).min() ?? 0, -0.4 - 0.004, accuracy: 1e-4)
    }
}
