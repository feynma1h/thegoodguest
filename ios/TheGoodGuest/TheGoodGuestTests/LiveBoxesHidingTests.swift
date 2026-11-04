/// Pins for what hides a dot or a box: a surface in front that is not the
/// object's own face, a wall between the camera and the object (but not an
/// opening, a furniture front or a camera pressed against it), the few frames
/// of agreement it takes to hide or return, the readable-points rule that
/// leaves a box as it was when too few points can be read, and the memory of
/// what was visible from a place.

import simd
import XCTest
@testable import TheGoodGuest

final class LiveBoxesHidingTests: XCTestCase {

    private let a = UUID(), b = UUID()

    func test_aSurfaceInFront_blocksAnObject_butItsOwnFrontFaceDoesNot() {
        // A sofa 3 m away, 1 m from centre to front: LiDAR reading 2.1 m is its own front.
        XCTAssertFalse(BoxOcclusion.isBlocked(depth: 3, measured: 2.1, radius: 1))
        // A wall at 1.2 m with the sofa behind it.
        XCTAssertTrue(BoxOcclusion.isBlocked(depth: 3, measured: 1.2, radius: 1))
        XCTAssertFalse(BoxOcclusion.isBlocked(depth: 3, measured: 0, radius: 1), "no reading, no verdict")
    }

    func test_anObjectHidesAfterAFewBlockedFrames_andReturnsAfterAFewClear() {
        var o = BoxOcclusion()
        XCTAssertFalse(o.update(a, blocked: true, at: 0))
        XCTAssertFalse(o.update(a, blocked: true, at: 0.1))
        XCTAssertTrue(o.hidden.isEmpty, "a flicker")
        XCTAssertTrue(o.update(a, blocked: true, at: 0.16), "it hid")
        XCTAssertEqual(o.hidden, [a])
        XCTAssertFalse(o.update(a, blocked: false, at: 0.2))
        XCTAssertEqual(o.hidden, [a], "one clear frame is not enough")
        XCTAssertTrue(o.update(a, blocked: false, at: 0.31), "it returned")
        XCTAssertTrue(o.hidden.isEmpty)
        o.update(b, blocked: true, at: 1); o.update(b, blocked: true, at: 1.2)
        o.keep(only: [a])
        XCTAssertTrue(o.hidden.isEmpty, "gone objects are forgotten")
    }

    func test_aWallBetweenTheCameraAndABox_hidesItEvenWhenTheBoxStandsAgainstTheFarSide() throws {
        // A wall at z = -3 spanning x -4...4: 8 m wide, 2.6 m tall; a cupboard against its far side.
        let wall = VerticalSurface(normal: SIMD2(0, 1), offset: -3, along: -4...4, heights: 0...2.6)
        let camera = SIMD3<Float>(0, 1.4, 0), cupboard = SIMD3<Float>(0.5, 0.7, -3.3)
        let found = try XCTUnwrap(BoxOcclusion.crossing(from: camera, to: cupboard, walls: [wall]))
        XCTAssertEqual(found.at.z, -3, accuracy: 0.001)
        XCTAssertEqual(found.wall, 0)
        // The depth read there is the plane itself (3 m along the axis): blocked.
        XCTAssertTrue(BoxOcclusion.isBlocked(wallDepth: 3.0, measured: 3.05))
        // Through a doorway the read goes on to the cupboard (3.9 m): not blocked.
        XCTAssertFalse(BoxOcclusion.isBlocked(wallDepth: 3.0, measured: 3.9))
        // Something nearer than the plane does not confirm it: a false plane in the room.
        XCTAssertFalse(BoxOcclusion.isBlocked(wallDepth: 3.0, measured: 1.8))
        XCTAssertFalse(BoxOcclusion.isBlocked(wallDepth: nil, measured: 3.0))
    }

    func test_aBoxOnTheCamerasSideOfAWall_isNotBehindIt() {
        let wall = VerticalSurface(normal: SIMD2(0, 1), offset: -3, along: -4...4, heights: 0...2.6)
        let camera = SIMD3<Float>(0, 1.4, 0)
        XCTAssertNil(BoxOcclusion.crossing(from: camera, to: SIMD3(0.5, 0.7, -2.9), walls: [wall]), "in the same room")
        XCTAssertNil(BoxOcclusion.crossing(from: camera, to: SIMD3(0.5, 0.7, -3.05), walls: [wall]), "within 10 cm: the wall's own face")
        XCTAssertNil(BoxOcclusion.crossing(from: camera, to: SIMD3(9, 0.7, -3.3), walls: [wall]), "past the end of the wall")
    }

    func test_aPlaneThatIsNotAWall_orACameraTooCloseToOne_hidesNothing() {
        let camera = SIMD3<Float>(0, 1.4, 0), beyond = SIMD3<Float>(0.5, 0.7, -3.3)
        // A furniture front: 0.8 m wide, 0.9 m tall.
        let front = VerticalSurface(normal: SIMD2(0, 1), offset: -2, along: -0.4...0.4, heights: 0...0.9)
        XCTAssertNil(BoxOcclusion.crossing(from: camera, to: beyond, walls: [front]))
        // A real wall, but the camera is 10 cm from its plane.
        let wall = VerticalSurface(normal: SIMD2(0, 1), offset: -0.1, along: -4...4, heights: 0...2.6)
        XCTAssertNil(BoxOcclusion.crossing(from: camera, to: beyond, walls: [wall]), "plane error decides the side")
        let clear = VerticalSurface(normal: SIMD2(0, 1), offset: -0.5, along: -4...4, heights: 0...2.6)
        XCTAssertEqual(BoxOcclusion.crossing(from: camera, to: beyond, walls: [front, clear])?.wall, 1, "the index is the list's")
    }

    func test_aJudgmentSeparatesTooFewPointsFromTheMiddleOfTheBand() {
        XCTAssertEqual(BoxOcclusion.judge(blocked: 2, of: 3), .unreadable, "ask what was remembered")
        XCTAssertEqual(BoxOcclusion.judge(blocked: 5, of: 9), .unsure, "leave the box as it was")
        XCTAssertEqual(BoxOcclusion.judge(blocked: 8, of: 9), .blocked)
        XCTAssertEqual(BoxOcclusion.judge(blocked: 1, of: 9), .clear)
    }

    func test_whatWasVisibleFromAPlace_isRememberedForThatPlaceAndTheNext() {
        var memory = VisibilityMemory()
        let spot = SIMD3<Float>(1.0, 1.4, 2.0)
        XCTAssertNil(memory.verdict(a, from: spot), "nothing remembered yet")
        memory.note(a, from: spot, blocked: false)
        XCTAssertEqual(memory.verdict(a, from: spot), false)
        XCTAssertEqual(memory.verdict(a, from: spot + SIMD3(0.1, 0.3, -0.1)), false, "the same cell, another height")
        XCTAssertEqual(memory.verdict(a, from: spot + SIMD3(0.5, 0, 0)), false, "the next cell")
        XCTAssertNil(memory.verdict(a, from: spot + SIMD3(1.6, 0, 0)), "too far to say")
        XCTAssertNil(memory.verdict(b, from: spot), "another box")
    }

    func test_theNearestMemoryWins_aNewerReadingOverridesIt_andGoneBoxesAreForgotten() {
        var memory = VisibilityMemory()
        memory.note(a, from: SIMD3(0.2, 1.4, 0.2), blocked: true)     // the cell the camera is in
        memory.note(a, from: SIMD3(0.6, 1.4, 0.2), blocked: false)    // the next one
        XCTAssertEqual(memory.verdict(a, from: SIMD3(0.3, 1.4, 0.3)), true, "this cell over the next")
        memory.note(a, from: SIMD3(0.3, 1.4, 0.3), blocked: false)
        XCTAssertEqual(memory.verdict(a, from: SIMD3(0.2, 1.4, 0.2)), false, "a newer reading from here overrides")
        memory.keep(only: [b])
        XCTAssertNil(memory.verdict(a, from: SIMD3(0.2, 1.4, 0.2)))
    }

    func test_aBoxsMemoryIsBounded() {
        var memory = VisibilityMemory()
        for i in 0..<(VisibilityMemory.cellsPerBox + 50) {
            memory.note(a, from: SIMD3(Float(i) * VisibilityMemory.cell * 3, 1.4, 0), blocked: i % 2 == 0)
        }
        XCTAssertNil(memory.verdict(a, from: SIMD3(0, 1.4, 0)), "the oldest cell was dropped")
        XCTAssertNotNil(memory.verdict(a, from: SIMD3(Float(VisibilityMemory.cellsPerBox + 49) * VisibilityMemory.cell * 3, 1.4, 0)))
    }

    func test_aVerdictNeedsEnoughPoints_andLeavesTheMiddleAlone() {
        XCTAssertNil(BoxOcclusion.verdict(blocked: 1, of: 1), "one corner is not a verdict")
        XCTAssertNil(BoxOcclusion.verdict(blocked: 3, of: 3), "too few readable points")
        XCTAssertEqual(BoxOcclusion.verdict(blocked: 7, of: 9), true, "a wall across the box")
        XCTAssertEqual(BoxOcclusion.verdict(blocked: 2, of: 9), false, "a corner behind a doorframe")
        XCTAssertNil(BoxOcclusion.verdict(blocked: 5, of: 9), "in between: as it was")
    }

    func test_aBoxInTheMiddleOfTheBand_keepsItsState() {
        var o = BoxOcclusion()
        o.update(a, blocked: BoxOcclusion.verdict(blocked: 8, of: 9), at: 0)
        o.update(a, blocked: BoxOcclusion.verdict(blocked: 8, of: 9), at: 0.2)
        XCTAssertEqual(o.hidden, [a])
        for i in 0..<10 { o.update(a, blocked: BoxOcclusion.verdict(blocked: 5, of: 9), at: 0.3 + Double(i) * 0.1) }
        XCTAssertEqual(o.hidden, [a], "a middling reading neither shows nor hides it")
    }

    func test_theRangeShare_widensTheSlackForADepthThatIsOffByPercents() {
        // 6 m away, radius 0.5: slack is 0.5 + 0.25 + 0.18. A surface at 5.2 m is the object's own front.
        XCTAssertFalse(BoxOcclusion.isBlocked(depth: 6, measured: 5.2, radius: 0.5))
        XCTAssertTrue(BoxOcclusion.isBlocked(depth: 6, measured: 4.9, radius: 0.5))
    }

    
    /// A point `offset` points right of the screen's centre.
}
