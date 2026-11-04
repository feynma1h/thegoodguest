/// Pins for the live-boxes runtime's pure parts: the cost arithmetic behind
/// every number in the session log, the log's shape (and what it must never
/// hold), why a detection got no dot, RoomPlan's boxes and the two comparisons
/// against them (switched off), and the detector catalogue's behaviour when no
/// model was bundled.

import simd
import XCTest
@testable import TheGoodGuest

final class LiveBoxesRuntimeTests: XCTestCase {

    // MARK: - Cost

    func test_percentile_isNearestRank() {
        XCTAssertNil(Percentile.of([], 0.5))
        XCTAssertEqual(Percentile.of([5], 0.95), 5)
        let values = (1...20).map(Double.init)
        XCTAssertEqual(Percentile.of(values, 0.5), 10)
        XCTAssertEqual(Percentile.of(values, 0.95), 19)
        XCTAssertEqual(Percentile.of(values.reversed(), 1), 20)
    }

    func test_latency_readsOnlyTheLastThirtySeconds() throws {
        var meter = CostMeter()
        meter.notePass(at: 0, timing: PassTiming(predict: 500))
        for k in 1...10 { meter.notePass(at: 40 + Double(k), timing: PassTiming(predict: Double(k))) }
        let latency = try XCTUnwrap(meter.predictLatency(now: 50))
        XCTAssertEqual(latency.p50, 5)
        XCTAssertEqual(latency.p95, 10)
    }

    func test_detectionRate_countsPassesOverTheWindow_orTheTimeElapsed() {
        var meter = CostMeter()
        for k in 0..<50 { meter.notePass(at: Double(k) * 0.2, timing: PassTiming()) }
        XCTAssertEqual(meter.detectionRate(now: 10, startedAt: 0), 5, accuracy: 0.01)
        // Two seconds in, a full ten-second window would read a fifth of the truth.
        var early = CostMeter()
        for k in 0..<10 { early.notePass(at: Double(k) * 0.2, timing: PassTiming()) }
        XCTAssertEqual(early.detectionRate(now: 2, startedAt: 0), 5, accuracy: 0.01)
    }

    func test_detectorRuns_twicePerSecond() {
        XCTAssertEqual(DetectionPacing.passesPerSecond, 2)
        XCTAssertEqual(DetectionPacing.interval, 0.5, accuracy: 1e-12)
    }

    func test_passGate_namesTheFirstGateThatHoldsAFrame() {
        func gate(pipeline: Bool = true, busy: Bool = false, interval: Double = 0.2, since: Double = 1,
                  tracking: Bool = true, depth: Bool = true) -> PassGate? {
            PassGate.holding(hasPipeline: pipeline, busy: busy, interval: interval, sinceLastStart: since,
                             trackingNormal: tracking, hasDepth: depth)
        }
        XCTAssertNil(gate())
        XCTAssertEqual(gate(pipeline: false, busy: true, depth: false), .noDetector)
        XCTAssertEqual(gate(busy: true, tracking: false), .passRunning)
        XCTAssertEqual(gate(since: 0.1), .paced)
        XCTAssertNil(gate(since: .infinity), "the first pass of a session is never paced")
        XCTAssertEqual(gate(tracking: false, depth: false), .tracking)
        XCTAssertEqual(gate(depth: false), .noDepth)
    }

    func test_frameRate_countsTheLastTwoSeconds() {
        var meter = CostMeter()
        for k in 0..<600 { meter.noteFrame(at: Double(k) / 60) }
        XCTAssertEqual(meter.frameRate(now: 599.0 / 60), 60, accuracy: 1)
    }

    func test_memoryReading_splitsTheFootprint_andItsHeapIsMallocs() throws {
        let before = try XCTUnwrap(MemoryReading.current())
        XCTAssertGreaterThan(before.footprintMB, 0)
        XCTAssertGreaterThan(before.heapMB, 0)
        for part in [before.graphicsMB, before.neuralMB, before.mediaMB] {
            XCTAssertGreaterThanOrEqual(part, 0)
        }
        // 64 MB held by malloc, every page of it written.
        let held = [UInt8](repeating: 1, count: 64 << 20)
        let after = try withExtendedLifetime(held) { try XCTUnwrap(MemoryReading.current()) }
        XCTAssertGreaterThanOrEqual(after.heapMB - before.heapMB, 60)
        XCTAssertGreaterThanOrEqual(after.footprintMB - before.footprintMB, 60)
    }

    func test_stateDurations_accumulatePerState() {
        var d = StateDurations()
        d.note("nominal", at: 0)
        d.note("nominal", at: 5)
        d.note("fair", at: 60)
        d.note("serious", at: 200)
        let totals = d.durations(until: 300)
        XCTAssertEqual(totals["nominal"], 60)
        XCTAssertEqual(totals["fair"], 140)
        XCTAssertEqual(totals["serious"], 100)
        XCTAssertEqual(d.current, "serious")
    }

    // MARK: - The log

    private func log() -> SessionLog {
        var log = SessionLog(startedAt: "2026-09-15T10:00:00Z",
                             device: .init(model: "iPhone17,1", system: "iOS 26.5", app: "1.0 (1)", optimized: true),
                             lift: DepthLiftParameters(), fusion: FusionParameters())
        log.passes = (0..<10).map {
            SessionLog.Pass(t: Double($0) * 0.2, timing: PassTiming(preprocess: 2, predict: Double(10 + $0)),
                            detections: 4, lifted: 2, excluded: 1, turn: 1)
        }
        log.tracks = [SessionLog.Track(id: "a", label: "LAMP", name: "table lamp", names: ["table lamp": 1.4],
                                       bestScore: 0.7, hits: 2, misses: 0, arcDegrees: 40, firstSeen: 0.2,
                                       lastSeen: 1.8, confirmed: true,
                                       box: SessionLog.Box(GravityBox(center: SIMD3(1, 0.3, -1),
                                                                      size: SIMD3(0.3, 0.6, 0.3), yaw: 0.1)))]
        var misses = MissTally()
        misses.add([DetectionMiss(name: "cocktail table", reason: .onlySurfaces, score: 0.8, at: SIMD3(0.6, 0, 0.3))])
        log.misses = misses.entries
        return log
    }

    func test_log_summary_readsPassesAndStates() throws {
        var tracking = StateDurations()
        tracking.note("normal", at: 0)
        var thermal = StateDurations()
        thermal.note("nominal", at: 0)
        var roomPlan = StateDurations()
        roomPlan.note("on", at: 0)
        roomPlan.note("off", at: 1)
        let summary = log().summarised(now: 2, tracking: tracking, thermal: thermal, roomPlan: roomPlan)
        XCTAssertEqual(summary.passes, 10)
        XCTAssertEqual(summary.meanPassRate, 5)
        XCTAssertEqual(summary.predictP50, 14)
        XCTAssertEqual(summary.predictP95, 19)
        XCTAssertEqual(summary.roomPlanOnSeconds, 1)
        XCTAssertEqual(summary.trackingSeconds["normal"], 2)
        XCTAssertEqual(summary.confirmedTracks, 1)
    }

    func test_aPassThatCouldNotRun_isCounted_butNeverTimed() {
        func result(predict: Double, failure: String? = nil) -> PassResult {
            PassResult(time: 0, timing: PassTiming(predict: predict), detections: 3, lifted: 1, excluded: 0,
                       turn: .clockwise, tracks: [], failure: failure)
        }
        var log = log()
        XCTAssertTrue(log.record(result(predict: 30), at: 2.0))
        XCTAssertFalse(log.record(result(predict: 0, failure: "prediction failed"), at: 2.2))
        XCTAssertFalse(log.record(result(predict: 0, failure: "prediction failed"), at: 2.4))
        XCTAssertFalse(log.record(result(predict: 0, failure: "unexpected output shapes"), at: 2.6))
        XCTAssertEqual(log.passes.count, 11)
        XCTAssertEqual(log.passes.last?.timing.predict, 30)
        XCTAssertEqual(log.failedPasses, 3)
        XCTAssertEqual(log.events.filter { $0.kind == "pass failed" }.map(\.value),
                       ["prediction failed", "unexpected output shapes"], "a repeated reason is written once")
        let summary = log.summarised(now: 2.75, tracking: StateDurations(), thermal: StateDurations(),
                                     roomPlan: StateDurations())
        XCTAssertEqual(summary.passes, 11)
        XCTAssertEqual(summary.failedPasses, 3)
        XCTAssertEqual(summary.meanPassRate, 4, "failures are not passes per second")
        XCTAssertEqual(summary.predictP50, 15, "a 0 ms failure never enters the latency")
    }

    func test_aLoadOvertakenByStop_installsNothing() {
        var loads = LoadTickets()
        let load = loads.next()
        XCTAssertTrue(loads.isCurrent(load))
        _ = loads.next()   // stop()
        XCTAssertFalse(loads.isCurrent(load), "nothing installs after stop")
    }

    func test_log_isNumbersAndGeometry_andRoundTrips() throws {
        let data = try log().encoded()
        let text = try XCTUnwrap(String(data: data, encoding: .utf8))
        for field in ["\"schema\" : \"live-boxes-log\\/1\"", "\"passes\"", "\"tracks\"", "\"yawDegrees\""] {
            XCTAssertTrue(text.contains(field), field)
        }
        let decoded = try JSONDecoder().decode(SessionLog.self, from: data)
        XCTAssertEqual(decoded.passes.count, 10)
        XCTAssertEqual(decoded.tracks.first?.label, "LAMP")
    }

    func test_log_hasNoFieldThatCouldCarryPixelsOrAPerson() {
        // A structural pin: no property anywhere in the document's type tree is
        // named for image data, masks, rasters or people.
        let forbidden = ["image", "mask", "raster", "rgb", "jpeg", "png", "photo", "person", "people", "face"]
        var names: [String] = []
        func collect(_ value: Any) {
            for child in Mirror(reflecting: value).children {
                if let label = child.label { names.append(label.lowercased()) }
                collect(child.value)
            }
        }
        collect(log())
        for name in names {
            XCTAssertFalse(forbidden.contains { name.contains($0) }, "log field '\(name)'")
        }
    }

    // MARK: - Why no dot

    func test_missReason_forEveryRole_andNeverForAPerson() {
        func reason(_ name: String, liftingRoomPlan: Bool = true) -> MissReason? {
            MissReason.unlifted(DetectorVocabulary.role(for: name), liftsRoomPlanCategories: liftingRoomPlan)
        }
        XCTAssertNil(reason("person"), "nothing is kept about a person")
        XCTAssertEqual(reason("door"), .partOfTheRoom)
        XCTAssertEqual(reason("window"), .partOfTheRoom)
        XCTAssertEqual(reason("chair", liftingRoomPlan: false), .leftToRoomPlan, "the handling, where RoomPlan boxes them")
        XCTAssertNil(reason("chair"), "lifted by the detector")
        XCTAssertNil(reason("lamp"), "a target is always lifted")
        for rejection in LiftRejection.allCases {
            XCTAssertEqual(MissReason(rejection).rawValue, rejection.rawValue)
        }
    }

    func test_missTally_countsByNameReasonAndFloorCell_mostFrequentFirst() throws {
        var tally = MissTally()
        let table = SIMD3<Float>(0.6, 0.1, 0.3)
        tally.add([
            DetectionMiss(name: "cocktail table", reason: .onlySurfaces, score: 0.7, at: table),
            DetectionMiss(name: "cocktail table", reason: .onlySurfaces, score: 0.9, at: table + SIMD3(0.1, 0, 0.1)),
            DetectionMiss(name: "cocktail table", reason: .onlySurfaces, score: 0.8, at: table + SIMD3(0.02, 0, 0)),
            DetectionMiss(name: "door", reason: .partOfTheRoom, score: 0.6, at: nil),
            DetectionMiss(name: "door", reason: .partOfTheRoom, score: 0.5, at: nil),
            // The same name and reason across the room is another object.
            DetectionMiss(name: "cocktail table", reason: .onlySurfaces, score: 0.4, at: SIMD3(2.2, 0.1, 2.1)),
            DetectionMiss(name: "cocktail table", reason: .tooUnsure, score: 0.45, at: table),
        ])
        let entries = tally.entries
        XCTAssertEqual(entries.map(\.count), [3, 2, 1, 1])
        let glass = try XCTUnwrap(entries.first)
        XCTAssertEqual(glass.name, "cocktail table")
        XCTAssertEqual(glass.reason, "only surfaces under it")
        XCTAssertEqual(glass.bestScore, 0.9)
        let at = try XCTUnwrap(glass.at)
        XCTAssertEqual(at[0], 0.64, accuracy: 1e-5)
        XCTAssertEqual(at[2], 0.3333, accuracy: 1e-4)
        XCTAssertEqual(entries[1].name, "door")
        XCTAssertNil(entries[1].at, "no depth said where")
        XCTAssertEqual(entries[2].reason, "only surfaces under it", "ties by name, then by reason")
        XCTAssertEqual(entries[3].reason, "too unsure to start a box")
    }

    func test_medianDepth_readsOnlyWhatWasMeasuredWithConfidence() {
        // A 5 × 5 map: depth 1 m, a 3 m reading in the middle at low
        // confidence, and nothing measured down the left column.
        var depth = [Float](repeating: 1, count: 25)
        var confidence = [UInt8](repeating: 2, count: 25)
        depth[12] = 3
        confidence[12] = 0
        for y in 0..<5 { depth[y * 5] = 0 }
        let grid = DepthGrid(width: 5, height: 5, depth: depth, confidence: confidence)
        XCTAssertEqual(grid.medianDepth(x: 2, y: 2, radius: 1, minimumConfidence: 1), 1)
        XCTAssertEqual(grid.medianDepth(x: 2, y: 2, radius: 0, minimumConfidence: 0), 3)
        XCTAssertNil(grid.medianDepth(x: 2, y: 2, radius: 0, minimumConfidence: 1))
        XCTAssertNil(grid.medianDepth(x: 0, y: 2, radius: 0, minimumConfidence: 0), "unmeasured")
    }

    func test_logFileName_isTheStartTime() {
        var c = DateComponents()
        c.year = 2026; c.month = 9; c.day = 15; c.hour = 9; c.minute = 5; c.second = 7
        let date = Calendar.current.date(from: c)!
        XCTAssertEqual(SessionLog.fileName(startedAt: date), "live-boxes-20260915-090507.json")
    }

    // MARK: - RoomPlan

    func test_roomPlanBox_readsYawFromTheTransformsFirstColumn() throws {
        var t = matrix_float4x4(simd_quatf(angle: 0.4, axis: SIMD3(0, 1, 0)))
        t.columns.3 = SIMD4(1, 0.5, -2, 1)
        let box = try XCTUnwrap(RoomPlanBox(id: UUID(), category: "table", confidence: .high,
                                            transform: t, dimensions: SIMD3(1.2, 0.75, 0.8)))
        XCTAssertEqual(box.box.yaw, 0.4, accuracy: 1e-5)
        XCTAssertEqual(box.box.size, SIMD3(1.2, 0.75, 0.8))
        XCTAssertEqual(box.box.center, SIMD3(1, 0.5, -2))
        let flat = matrix_float4x4(simd_quatf(angle: .pi / 2, axis: SIMD3(0, 0, 1)))
        XCTAssertNil(RoomPlanBox(id: UUID(), category: "table", confidence: .high,
                                 transform: flat, dimensions: SIMD3(1, 1, 1)), "not upright")
    }

    private let shelfOnStorage = RoomPlanBox(id: UUID(), category: "storage", confidence: .high,
                                             transform: matrix_float4x4(columns: (SIMD4(1, 0, 0, 0), SIMD4(0, 1, 0, 0),
                                                                                  SIMD4(0, 0, 1, 0), SIMD4(0, 0.9, 0, 1))),
                                             dimensions: SIMD3(0.8, 1.8, 0.35))!

    func test_duplicate_needsACategoryTheBoxCanBe_andRealOverlap() {
        let shelf = GravityBox(center: SIMD3(0.02, 0.9, 0), size: SIMD3(0.78, 1.75, 0.33), yaw: 0)
        XCTAssertEqual(RoomPlanMatch.duplicatedCategory(shelf, overlap: ["storage"], among: [shelfOnStorage]), "storage")
        XCTAssertNil(RoomPlanMatch.duplicatedCategory(shelf, overlap: ["table"], among: [shelfOnStorage]))
        let lampBeside = GravityBox(center: SIMD3(1.0, 0.8, 0), size: SIMD3(0.3, 1.6, 0.3), yaw: 0)
        XCTAssertNil(RoomPlanMatch.duplicatedCategory(lampBeside, overlap: ["storage"], among: [shelfOnStorage]))
    }

    func test_agreement_readsErrorsOverTheQuarterTurn() throws {
        // The same shelf described turned by a quarter: identical boxes.
        let turned = GravityBox(center: SIMD3(0, 0.9, 0), size: SIMD3(0.35, 1.8, 0.8), yaw: .pi / 2)
        let match = try XCTUnwrap(RoomPlanMatch.agreement(turned, category: "storage", among: [shelfOnStorage]))
        XCTAssertEqual(match.agreement.yawDegrees, 0, accuracy: 0.01)
        XCTAssertEqual(match.agreement.extentErrors.max() ?? 1, 0, accuracy: 1e-4)
        XCTAssertEqual(match.agreement.iou, 1, accuracy: 1e-3)
        XCTAssertNil(RoomPlanMatch.agreement(turned, category: "table", among: [shelfOnStorage]))
    }

    // MARK: - RoomPlan stays out of it

    func test_roomPlanComparisons_areSwitchedOff_andTheDetectorLiftsItsCategories() {
        XCTAssertFalse(RoomPlanClasses.boxedByRoomPlan, "no RoomPlan box is used for what the person boxes")
        XCTAssertNil(MissReason.unlifted(DetectorVocabulary.role(for: "chair"),
                                         liftsRoomPlanCategories: !RoomPlanClasses.boxedByRoomPlan))
    }

    func test_theDetector_boxesWhatTheVocabularyLeavesToTheRoom_whenPromoted() {
        XCTAssertEqual(DetectorVocabulary.role(for: "furniture"), .absorber)
        XCTAssertEqual(DetectorPipeline.role(for: "furniture"),
                       .target(label: "FURNITURE", flat: false, roomPlanOverlap: []))
        XCTAssertEqual(DetectorPipeline.role(for: "chair"), DetectorVocabulary.role(for: "chair"), "nothing else changes")
        XCTAssertTrue(DetectorPipeline.startsCutOffObjects, "an object the frame cuts off may start a box")
    }

    // MARK: - Catalogue

    func test_catalogue_withNoBundledModel_findsNothing_andChoosesNothing() {
        // The test bundle carries no export: a checkout without the model.
        let found = DetectorCatalog.bundled(in: Bundle(for: LiveBoxesRuntimeTests.self))
        XCTAssertTrue(found.isEmpty)
        XCTAssertNil(DetectorCatalog.choose([], requested: nil))
    }

    func test_catalogue_prefersTheRequestedThenThePreferredModel() {
        let url = URL(fileURLWithPath: "/tmp")
        let models = ["yoloe26n_pf_app_640", DetectorCatalog.preferred, "yoloe26s_pf_app_512"]
            .map { BundledDetector(name: $0, url: url) }
        XCTAssertEqual(DetectorCatalog.choose(models, requested: "yoloe26s_pf_app_512")?.name, "yoloe26s_pf_app_512")
        XCTAssertEqual(DetectorCatalog.choose(models, requested: "gone")?.name, DetectorCatalog.preferred)
        XCTAssertEqual(DetectorCatalog.choose(Array(models.prefix(1)), requested: nil)?.name, "yoloe26n_pf_app_640")
    }
}
