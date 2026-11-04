/// Pins for which objects get a dot: the sighting rule that keeps ghosts out,
/// one dot per object whatever it was called in turn, a rug that is a table's
/// shadow, the table whose box reaches its whole top, an object that needs a
/// walk round, and the one name the vocabulary leaves to the room that live
/// boxes boxes anyway.

import simd
import XCTest
@testable import TheGoodGuest

final class LiveBoxesDotTests: XCTestCase {

    private let a = UUID(), b = UUID()

    
    /// A point `offset` points right of the screen's centre.
    func test_aRugBoxedOnATablesSilhouette_isTheTablesShadow_butARugBesideItIsNot() {
        let table = GravityBox(center: SIMD3(0, 0.21, 0), size: SIMD3(1.2, 0.42, 0.6), yaw: 0)
        let onIt = GravityBox(center: SIMD3(0.05, 0.13, 0.02), size: SIMD3(1.4, 0.26, 0.7), yaw: 0)
        let beside = GravityBox(center: SIMD3(2.5, 0.02, 0), size: SIMD3(1.5, 0.04, 1.0), yaw: 0)
        XCTAssertTrue(DotRules.shadowsTable(label: "RUG", box: onIt, tables: [table]))
        XCTAssertTrue(DotRules.shadowsTable(label: "MAT", box: onIt, tables: [table]))
        XCTAssertFalse(DotRules.shadowsTable(label: "RUG", box: beside, tables: [table]))
        XCTAssertFalse(DotRules.shadowsTable(label: "CHAIR", box: onIt, tables: [table]), "only floor coverings")
    }

    private func track(_ label: String, at c: SIMD3<Float>, hits: Int, misses: Int = 0, arc: Int = 90,
                       size: SIMD3<Float> = SIMD3(0.4, 0.2, 0.4), id: UUID = UUID()) -> TrackSummary {
        TrackSummary(id: id, label: label, name: label.lowercased(), bestScore: 0.8, hits: hits, misses: misses, arcDegrees: arc,
                     confirmed: true, box: GravityBox(center: c, size: size, yaw: 0))
    }

    func test_aSecondTrackOfOnePillow_getsNoDot_butTwoPillowsApartDo() {
        let kept = track("CUSHION", at: SIMD3(1.3, 0.2, -2.1), hits: 60)
        let twin = track("CUSHION", at: SIMD3(1.3, 0.2, -2.0), hits: 6)
        let apart = track("CUSHION", at: SIMD3(2.4, 0.2, -2.1), hits: 20)
        let chair = track("CHAIR", at: SIMD3(1.3, 0.2, -2.1), hits: 8)
        let dots = DotRules.dotted([kept, twin, apart, chair], boxed: []).map(\.id)
        XCTAssertTrue(dots.contains(kept.id))
        XCTAssertFalse(dots.contains(twin.id), "the same pillow, seen fewer times")
        XCTAssertTrue(dots.contains(apart.id), "a different pillow")
        XCTAssertTrue(dots.contains(chair.id), "another kind of thing")
    }

    func test_aTrackOfABoxedObject_getsNoDot_whateverItsSightings() {
        let boxed = track("CUSHION", at: SIMD3(1.3, 0.2, -2.1), hits: 3)
        let twin = track("CUSHION", at: SIMD3(1.3, 0.2, -2.0), hits: 40)
        let dots = DotRules.dotted([boxed, twin], boxed: [boxed.id])
        XCTAssertTrue(dots.isEmpty)
    }

    func test_oneCupboardNamedTwoWays_getsTheDotOfTheBetterSeenName_onlyWhenClearlyBetter() {
        let size = SIMD3<Float>(0.6, 1.2, 0.5)
        let cabinet = track("CABINET", at: SIMD3(1, 0.6, -2), hits: 30, misses: 10, size: size)
        let storage = track("STORAGE", at: SIMD3(1.05, 0.6, -2), hits: 17, misses: 26, size: size)
        let dots = DotRules.dotted([cabinet, storage], boxed: []).map(\.id)
        XCTAssertEqual(dots, [cabinet.id], "clearly better seen")
        let close = track("STORAGE", at: SIMD3(1.05, 0.6, -2), hits: 28, misses: 12, size: size)
        let both = DotRules.dotted([cabinet, close], boxed: []).map(\.id)
        XCTAssertEqual(Set(both), [cabinet.id, close.id], "too close to call: both keep their dots")
    }

    func test_theCatTreeAndNightstandOfTheWalk_areOneObject_withOneDot() {
        // Both from the 2026-11-01 LiDAR walk: boxes 20 cm apart, hit shares 0.63 and 0.73.
        let tree = track("CAT TREE", at: SIMD3(0.2, -0.4, -4.5), hits: 12, misses: 7, size: SIMD3(0.56, 1.28, 0.48))
        let stand = track("NIGHTSTAND", at: SIMD3(0.2, -0.8, -4.3), hits: 35, misses: 13, size: SIMD3(0.53, 0.93, 0.46))
        let dots = DotRules.dotted([tree, stand], boxed: []).map(\.id)
        XCTAssertEqual(dots, [stand.id])
    }

    func test_aChairTuckedUnderATable_keepsItsDot_andSoDoesTheTable() {
        let table = track("TABLE", at: SIMD3(0, 0.4, -1), hits: 20, misses: 5, size: SIMD3(1.4, 0.75, 0.8))
        let chair = track("CHAIR", at: SIMD3(0, 0.45, -0.7), hits: 60, misses: 2, size: SIMD3(0.45, 0.93, 0.45))
        let dots = DotRules.dotted([table, chair], boxed: []).map(\.id)
        XCTAssertEqual(Set(dots), [table.id, chair.id], "different kinds of furniture")
    }

    func test_aBoxedFurnitureTrack_takesTheDotOfADifferentlyNamedTwin_andOtherThingsKeepTheirs() {
        let size = SIMD3<Float>(0.6, 1.2, 0.5)
        let boxed = track("CAT TREE", at: SIMD3(1, 0.6, -2), hits: 6, size: size)
        let twin = track("NIGHTSTAND", at: SIMD3(1, 0.6, -2), hits: 40, size: size)
        let lamp = track("LAMP", at: SIMD3(1, 0.6, -2), hits: 40, size: size)
        let dots = DotRules.dotted([boxed, twin, lamp], boxed: [boxed.id]).map(\.id)
        XCTAssertEqual(dots, [lamp.id], "a lamp is not furniture, whatever it overlaps")
    }

    func test_aTablesBox_reachesToTheWholeOfItsTop_alongItsOwnAxes() {
        // A fit of the near end: 60 × 74 × 70 cm, turned 26°; the top is a 160 × 80 plane at 0.75 m turned the same.
        let yaw: Float = 26 * .pi / 180
        let fit = GravityBox(center: SIMD3(0.3, 0.37, 0), size: SIMD3(0.6, 0.74, 0.7), yaw: yaw)
        let axis = fit.planXAxis
        let top = HorizontalSurface(kind: .support, height: 0.75,
                                    extent: PlanRectangle(center: SIMD2(0.3, 0) - axis * 0.5, axis: axis, halfExtents: SIMD2(0.8, 0.4)))
        let box = TableTop.extended(fit, tops: [top])
        XCTAssertEqual(box.yaw, fit.yaw, accuracy: 1e-4, "the fit's turn, not the plane's")
        XCTAssertGreaterThan(box.size.x, 1.55)
        XCTAssertGreaterThan(box.size.z, 0.75)
        XCTAssertEqual(box.maxY, 0.75, accuracy: 0.01)
        XCTAssertEqual(box.minY, fit.minY, accuracy: 0.01)
        // Never smaller: a plane inside the fit leaves it as it was.
        let small = HorizontalSurface(kind: .support, height: 0.75,
                                      extent: PlanRectangle(center: SIMD2(0.3, 0), axis: axis, halfExtents: SIMD2(0.2, 0.2)))
        XCTAssertEqual(TableTop.extended(fit, tops: [small]).size.x, fit.size.x, accuracy: 0.01)
    }

    func test_aPlaneThatRunsAnotherWay_isLeftAlone() {
        let fit = GravityBox(center: SIMD3(0, 0.37, 0), size: SIMD3(0.6, 0.74, 0.7), yaw: 0)
        let axis = SIMD2<Float>(cos(30 * .pi / 180), sin(30 * .pi / 180))
        let tilted = HorizontalSurface(kind: .support, height: 0.75,
                                       extent: PlanRectangle(center: SIMD2(0, 0), axis: axis, halfExtents: SIMD2(0.8, 0.5)))
        XCTAssertEqual(TableTop.extended(fit, tops: [tilted]), fit, "30° off is a partial plane, not the table")
        let low = HorizontalSurface(kind: .support, height: 0.45,
                                    extent: PlanRectangle(center: SIMD2(0, 0), axis: SIMD2(1, 0), halfExtents: SIMD2(0.8, 0.4)))
        let huge = HorizontalSurface(kind: .support, height: 0.75,
                                     extent: PlanRectangle(center: SIMD2(0, 0), axis: SIMD2(1, 0), halfExtents: SIMD2(2.5, 1)))
        let away = HorizontalSurface(kind: .support, height: 0.75,
                                     extent: PlanRectangle(center: SIMD2(3, 0), axis: SIMD2(1, 0), halfExtents: SIMD2(0.8, 0.4)))
        XCTAssertEqual(TableTop.extended(fit, tops: [low, huge, away]), fit, "wrong height, not a table, not under it")
    }

    func test_aBoxNeedsAWalkAround_whenItIsBigAndSeenFromOneSide_orIsGlassTheOutlinesHaveNotPinned() {
        let big = SIMD3<Float>(1.6, 0.74, 0.8), small = SIMD3<Float>(0.4, 0.4, 0.4)
        XCTAssertTrue(DotRules.needsMoreViews(track("TABLE", at: .zero, hits: 20, arc: 30, size: big)))
        XCTAssertFalse(DotRules.needsMoreViews(track("TABLE", at: .zero, hits: 20, arc: 90, size: big)), "seen round it")
        XCTAssertFalse(DotRules.needsMoreViews(track("CUSHION", at: .zero, hits: 20, arc: 20, size: small)), "small: one side will do")
        let glass = TrackSummary(id: UUID(), label: "TABLE", name: "glass table", bestScore: 0.8, hits: 20, arcDegrees: 120,
                                 confirmed: true, seenThrough: true, outlinesPinned: false,
                                 box: GravityBox(center: .zero, size: small, yaw: 0))
        XCTAssertTrue(DotRules.needsMoreViews(glass), "a side of its footprint is not pinned")
    }

    func test_aDotNeedsAFewMostlySuccessfulSightings_exceptGlass() {
        func t(_ hits: Int, _ misses: Int, through: Bool = false) -> TrackSummary {
            TrackSummary(id: UUID(), label: "TOY", name: "toy", bestScore: 0.8, hits: hits, misses: misses, arcDegrees: 40,
                         confirmed: true, seenThrough: through, box: GravityBox(center: .zero, size: SIMD3(0.3, 0.3, 0.3), yaw: 0))
        }
        XCTAssertFalse(DotRules.isWorthADot(t(2, 0)), "seen twice")
        XCTAssertFalse(DotRules.isWorthADot(t(8, 8)), "seen half the time")
        XCTAssertTrue(DotRules.isWorthADot(t(8, 2)))
        XCTAssertTrue(DotRules.isWorthADot(t(5, 3)))
        XCTAssertTrue(DotRules.isWorthADot(t(2, 0, through: true)), "glass is exempt")
    }

    func test_onlyATablesBoxIsExtended() {
        let at = SIMD3<Float>(0.3, 0.37, 0)
        let top = HorizontalSurface(kind: .support, height: 0.75,
                                    extent: PlanRectangle(center: SIMD2(0, 0), axis: SIMD2(1, 0), halfExtents: SIMD2(0.8, 0.4)))
        let desk = track("DESK", at: at, hits: 20, size: SIMD3(0.6, 0.74, 0.7))
        let chair = track("CHAIR", at: at + SIMD3(0, 0, 3), hits: 20, size: SIMD3(0.6, 0.74, 0.7))
        XCTAssertEqual(DotRules.box(of: desk, tops: [top]).size.x, 1.6, accuracy: 0.05)
        XCTAssertEqual(DotRules.box(of: chair, tops: [top]).size.x, 0.6, accuracy: 0.01)
    }

    func test_aFitOnTheNextObject_isAJump_butAGrowingBoxIsNot() {
        let box = GravityBox(center: SIMD3(0, 0.5, 0), size: SIMD3(0.5, 1, 0.5), yaw: 0)
        let beside = GravityBox(center: SIMD3(1.5, 0.5, 0), size: SIMD3(0.5, 1, 0.5), yaw: 0)
        let grown = GravityBox(center: SIMD3(0.25, 0.5, 0), size: SIMD3(1.0, 1, 0.5), yaw: 0)
        XCTAssertTrue(DotRules.isJump(from: box, to: beside))
        XCTAssertFalse(DotRules.isJump(from: box, to: grown), "the same object, fitted larger")
        XCTAssertFalse(DotRules.isJump(from: box, to: box))
    }
}
