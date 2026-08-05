/// The live floor plan's language decisions (chunk RP-7), as pure tables per
/// the house pattern (RoomPlanWire, WaitFlowState): what a box is called, what
/// a "new piece" moment says, how RoomPlan's sparse instructions sound in the
/// guest's voice, which line the capture screen speaks when several compete,
/// and how the census maps onto the §3 coverage ticks.
///
/// Two honesty rules run through every table:
///   • CONFIDENCE GATES NAMING. The spike's one category error (a wardrobe
///     shipped as "refrigerator") carried LOW confidence — honest of RoomPlan,
///     so the app keeps it honest: low-confidence pieces get no box label and
///     a hedged moment line, never a confidently spoken wrong name.
///   • UNKNOWN DEGRADES QUIETLY. Category and instruction tokens are strings
///     (String(describing:)) so a future RoomPlan case flows through and lands
///     in the generic treatment instead of crashing or being mislabeled.
///
/// Read by: CaptureManager (moments + guidance publishing), FloorPlanView
/// (labels), LiveCaptureView (the spoken line), RootFlowView (coverage ticks),
/// FloorPlanVoiceTests (pins).

import Foundation

/// A newly detected object as the moment pipeline sees it (didAdd delta).
nonisolated struct FloorPlanPiece: Equatable, Sendable {
    let id: UUID
    let categoryToken: String
    let confidence: FloorPlanConfidence
}

nonisolated enum FloorPlanVoice {

    // MARK: - Category naming (RoomPlan's 16-category vocabulary, 0076 Q4)

    /// (box label, moment noun) per category token. The label is machine data
    /// (mono, uppercase); the noun is the guest speaking.
    private nonisolated static let categories: [String: (label: String, noun: String)] = [
        "storage":      ("STORAGE", "a cabinet"),
        "refrigerator": ("FRIDGE", "a refrigerator"),
        "stove":        ("STOVE", "a stove"),
        "bed":          ("BED", "a bed"),
        "sink":         ("SINK", "a sink"),
        "washerDryer":  ("WASHER", "a washer"),
        "toilet":       ("TOILET", "a toilet"),
        "bathtub":      ("BATH", "a bathtub"),
        "oven":         ("OVEN", "an oven"),
        "dishwasher":   ("DISHWASHER", "a dishwasher"),
        "table":        ("TABLE", "a table"),
        "sofa":         ("SOFA", "a sofa"),
        "chair":        ("CHAIR", "a chair"),
        "fireplace":    ("FIREPLACE", "a fireplace"),
        "television":   ("TV", "a television"),
        "stairs":       ("STAIRS", "the stairs"),
    ]

    /// The mono label drawn inside a box rect, or nil to draw the box
    /// unlabeled: low confidence (the wardrobe/"refrigerator" rule) and
    /// unknown categories stay quiet.
    nonisolated static func boxLabel(categoryToken: String, confidence: FloorPlanConfidence) -> String? {
        guard confidence != .low else { return nil }
        return categories[categoryToken]?.label
    }

    /// The guest's line when a new piece lands on the plan. Named only at
    /// medium+ confidence for a known category; otherwise the hedge.
    nonisolated static func momentLine(categoryToken: String, confidence: FloorPlanConfidence) -> String {
        guard confidence != .low, let noun = categories[categoryToken]?.noun else {
            return "Something new — noted."
        }
        return "\(noun.prefix(1).uppercased() + noun.dropFirst()) — noted."
    }

    /// Which of a delta's pieces are genuinely new (order-preserving) — the
    /// dedupe that keeps a moment from re-firing for an already-announced id.
    nonisolated static func unannounced(_ pieces: [FloorPlanPiece], seen: Set<UUID>) -> [FloorPlanPiece] {
        pieces.filter { !seen.contains($0.id) }
    }

    // MARK: - Instruction relay (RoomCaptureSession.Instruction tokens)

    /// RoomPlan's guidance in the guest's voice — plain, never blaming (§3).
    /// "normal" and unknown cases return nil: guidance stands down.
    nonisolated static func guidanceLine(instructionToken: String) -> String? {
        switch instructionToken {
        case "moveCloseToWall":  return "A little closer to that wall, when you can."
        case "moveAwayFromWall": return "A step back from the wall — I'll see it better."
        case "slowDown":         return "Slower, just a touch."
        case "turnOnLight":      return "A bit more light would help me see."
        case "lowTexture":       return "Show me an edge or a corner — something with shape."
        default:                 return nil
        }
    }

    /// How long a guidance line holds the floor after it arrives. RoomPlan
    /// clears guidance itself (.normal), so this is the belt for a stale line
    /// that never got cleared — measured cadence is ~one instruction per scan
    /// (0076 Q6), so 8 s of steering per event is sparse, not chatty.
    nonisolated static let guidanceHoldSec: TimeInterval = 8
    /// How long a "new piece" moment holds the floor.
    nonisolated static let momentHoldSec: TimeInterval = 3.5

    // MARK: - The "enough" confirmation (§3's third legible thing)

    /// The census has settled into a room: a closed room's worth of walls, a
    /// floor, and nothing new for `censusSettleSec`. Spike measurement: the
    /// full census by ~27 s, stable thereafter (0076 Q6) — so a quiet census
    /// is signal, not silence.
    nonisolated static func censusStable(walls: Int, floors: Int, sinceChange: TimeInterval) -> Bool {
        walls >= 4 && floors >= 1 && sinceChange >= censusSettleSec
    }

    nonisolated static let censusSettleSec: TimeInterval = 12

    /// Honest about what "stable" certifies: the census stopped growing, not
    /// that every corner is covered — so it invites finishing without
    /// asserting completeness.
    nonisolated static let censusStableLine =
        "I've got the bones of the room. Keep going for detail, or finish when you're ready."

    // MARK: - The one spoken line (priority table)

    /// Which line the capture screen speaks. Precedence:
    ///   1. fresh guidance   — RoomPlan is actively steering; nothing outranks it
    ///   2. fresh moment     — a new piece just landed
    ///   3. census stable    — the "enough" confirmation
    ///   4. the default coaching line
    /// (The too-dark override lives above this table, in LiveCaptureView —
    /// tracking truth outranks everything the guest might say.)
    nonisolated static func liveGuestLine(guidance: String?, guidanceAge: TimeInterval,
                              moment: String?, momentAge: TimeInterval,
                              censusIsStable: Bool, defaultLine: String) -> String {
        if let guidance, guidanceAge < guidanceHoldSec { return guidance }
        if let moment, momentAge < momentHoldSec { return moment }
        if censusIsStable { return censusStableLine }
        return defaultLine
    }

    // MARK: - Coverage ticks (§3; the task-#13 wiring RootFlowView waited on)

    /// The three ticks from the live census + measured corner adjacencies.
    /// "Full" means A CLOSED ROOM'S WORTH (4 walls, 4 corners), not "all of
    /// yours" — the denominator is the minimum closure, the one honest
    /// constant when the room's true count is unknowable mid-scan. The floor
    /// is binary: RoomPlan either has one or it doesn't.
    nonisolated static func coverage(census: RoomCensus?, cornerCount: Int)
        -> (floor: SurfaceCoverage, walls: SurfaceCoverage, corners: SurfaceCoverage)
    {
        guard let census else { return (.empty, .empty, .empty) }
        return (census.floors >= 1 ? .full : .empty,
                quarters(census.walls),
                quarters(cornerCount))
    }

    private nonisolated static func quarters(_ n: Int) -> SurfaceCoverage {
        switch n {
        case ..<1:  return .empty
        case ..<4:  return .partial(Double(n) / 4)
        default:    return .full
        }
    }
}
