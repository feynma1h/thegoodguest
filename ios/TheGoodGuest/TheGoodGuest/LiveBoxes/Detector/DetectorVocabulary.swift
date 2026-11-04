/// What each detector class name MEANS to live boxes — the one
/// table, DEBUG-only (decision 0295).
///
/// THE NAMES ARE THE DETECTOR'S OWN. Prompt-free YOLOE carries a built-in
/// vocabulary (the Recognize Anything tag list), and nothing here invents a
/// class: where the list lacks a word — rug, cushion, artwork, coffee table —
/// a near-synonym it does have is mapped onto that word (carpet → RUG, pillow →
/// CUSHION, picture frame and poster → ARTWORK, cocktail table → COFFEE TABLE).
/// Writing a new name would need a text encoder, and the only one this model
/// accepts is research-licensed.
///
/// THIS TABLE IS ALSO THE EXPORT'S VOCABULARY. The exported model is restricted
/// to exactly these names, in this order (0295 records the rebuild), because
/// the full 4,585-name head is four times slower and its FP16 class indices
/// are wrong above 2048. The model's own metadata carries the names it was
/// built with; a name the table does not know degrades to `.absorber` and is
/// counted on screen, so the two cannot drift apart silently.
///
/// Four roles:
///   • target — the long tail. Boxed.
///   • roomPlanCategory — one of RoomPlan's 16. Lifted and fused but hidden by
///     default: RoomPlan already boxes it, and the pair is how the detector's
///     geometry is checked against RoomPlan's on real furniture.
///   • excluded — people and animals. Never boxed, never logged as geometry;
///     their pixels are removed from every other object (0089).
///   • absorber — structure, scenes and small clutter. It exists so a wall or
///     a book is named for what it is rather than as the nearest target.
///
/// Read by: DetectorPipeline, TrackSummary, LiveBoxesVocabularyTests,
/// LiveBoxesLiftingTests and LiveBoxesModelTests.

#if DEBUG

import Foundation

nonisolated enum DetectorRole: Equatable, Sendable {
    /// `flat`: a floor covering, which the supporting-surface filter must keep.
    /// `roomPlanOverlap`: RoomPlan categories a box of this kind may duplicate.
    case target(label: String, flat: Bool, roomPlanOverlap: Set<String>)
    /// `category`: RoomPlan's own token (`String(describing:)` of the case).
    case roomPlanCategory(label: String, category: String)
    case excluded
    case absorber

    var label: String? {
        switch self {
        case .target(let label, _, _), .roomPlanCategory(let label, _): return label
        case .excluded, .absorber: return nil
        }
    }

    /// Whether detections in this role are lifted into 3D at all.
    var isLifted: Bool {
        switch self {
        case .target, .roomPlanCategory: return true
        case .excluded, .absorber: return false
        }
    }

    /// Whether a detection in this role is lifted, given whether RoomPlan's
    /// own categories are being checked against RoomPlan. They are off by
    /// default: RoomPlan boxes them already, and in a furnished room they were
    /// a third of all the tracks a review walk carried.
    func isLifted(includingRoomPlanCategories: Bool) -> Bool {
        if case .roomPlanCategory = self { return includingRoomPlanCategories }
        return isLifted
    }

    /// Whether a detection in this role can stand before another object and
    /// hide it: a thing or a person — not the room, and not a floor covering,
    /// which lies under everything.
    var canHide: Bool {
        switch self {
        case .target(_, let flat, _): return !flat
        case .roomPlanCategory, .excluded: return true
        case .absorber: return false
        }
    }
}

nonisolated enum DetectorVocabulary {

    private static func target(_ label: String, flat: Bool = false, _ overlap: String...) -> DetectorRole {
        .target(label: label, flat: flat, roomPlanOverlap: Set(overlap))
    }

    private static func roomPlan(_ label: String, _ category: String) -> DetectorRole {
        .roomPlanCategory(label: label, category: category)
    }

    /// Every exported name, in export order, with its role.
    static let entries: [(name: String, role: DetectorRole)] = [
        // Light
        ("lamp", target("LAMP")),
        ("table lamp", target("LAMP")),
        ("bedside lamp", target("LAMP")),
        ("wall lamp", target("LAMP")),
        ("lamp shade", target("LAMP")),
        ("chandelier", target("CEILING LIGHT")),
        ("light fixture", target("CEILING LIGHT")),
        ("droplight", target("CEILING LIGHT")),
        ("lantern", target("LAMP")),
        ("paper lantern", target("LAMP")),
        ("ceiling fan", target("CEILING FAN")),
        ("floor fan", target("FAN")),
        ("fan", target("FAN")),
        // Plants
        ("houseplant", target("PLANT")),
        ("plant", target("PLANT")),
        ("bonsai", target("PLANT")),
        ("cactus", target("PLANT")),
        ("succulent", target("PLANT")),
        ("flower", target("PLANT")),
        ("vase", target("VASE")),
        ("glass vase", target("VASE")),
        ("pot", target("POT")),
        ("flower basket", target("PLANT")),
        // Floor coverings
        ("carpet", target("RUG", flat: true)),
        ("floor mat", target("MAT", flat: true)),
        ("doormat", target("MAT", flat: true)),
        ("bath mat", target("MAT", flat: true)),
        ("mat", target("MAT", flat: true)),
        ("yoga mat", target("MAT", flat: true)),
        // Windows and textiles
        ("curtain", target("CURTAIN")),
        ("blind", target("BLIND")),
        ("shower curtain", target("CURTAIN")),
        ("pillow", target("CUSHION")),
        ("throw pillow", target("CUSHION")),
        ("blanket", target("BLANKET")),
        ("throw", target("BLANKET")),
        ("quilt", target("BLANKET")),
        ("duvet", target("BLANKET")),
        // Walls
        ("mirror", target("MIRROR")),
        ("bathroom mirror", target("MIRROR")),
        ("picture frame", target("ARTWORK")),
        ("photo frame", target("ARTWORK")),
        ("poster", target("ARTWORK")),
        ("movie poster", target("ARTWORK")),
        ("oil painting", target("ARTWORK")),
        ("watercolor painting", target("ARTWORK")),
        ("art print", target("ARTWORK")),
        ("canvas", target("ARTWORK")),
        ("decorative picture", target("ARTWORK")),
        ("picture", target("ARTWORK")),
        ("mural", target("ARTWORK")),
        ("tapestry", target("ARTWORK")),
        ("sculpture", target("SCULPTURE")),
        ("statue", target("SCULPTURE")),
        ("figurine", target("SCULPTURE")),
        ("wall clock", target("CLOCK")),
        ("clock", target("CLOCK")),
        ("alarm clock", target("CLOCK")),
        // Screens and instruments
        ("computer monitor", target("MONITOR", "television")),
        ("monitor", target("MONITOR", "television")),
        ("computer screen", target("MONITOR", "television")),
        ("laptop", target("LAPTOP")),
        ("desktop computer", target("COMPUTER")),
        ("computer tower", target("COMPUTER")),
        ("printer", target("PRINTER")),
        ("speaker", target("SPEAKER")),
        ("stereo", target("SPEAKER")),
        ("projector", target("PROJECTOR")),
        ("projection screen", target("PROJECTION SCREEN", "television")),
        ("musical keyboard", target("PIANO")),
        ("piano", target("PIANO")),
        ("guitar", target("GUITAR")),
        // Storage
        ("shelf", target("SHELF", "storage")),
        ("bookshelf", target("SHELF", "storage")),
        ("bookcase", target("SHELF", "storage")),
        ("side cabinet", target("CABINET", "storage")),
        ("tv cabinet", target("CABINET", "storage")),
        ("file cabinet", target("CABINET", "storage")),
        ("drawer", target("DRAWERS", "storage")),
        // A torso as readily as a trunk: excluded where it stands in the export order.
        ("chest", .excluded),
        ("coatrack", target("COAT RACK")),
        ("wine rack", target("RACK", "storage")),
        // Tables
        ("side table", target("SIDE TABLE", "table")),
        ("nightstand", target("NIGHTSTAND", "table", "storage")),
        ("cocktail table", target("COFFEE TABLE", "table")),
        ("glass table", target("TABLE", "table")),
        ("round table", target("TABLE", "table")),
        ("writing desk", target("DESK", "table")),
        ("computer desk", target("DESK", "table")),
        ("office desk", target("DESK", "table")),
        // Seats
        ("armchair", target("ARMCHAIR", "chair", "sofa")),
        ("stool", target("STOOL", "chair")),
        ("bar stool", target("STOOL", "chair")),
        ("bench", target("BENCH", "chair", "sofa")),
        ("footrest", target("OTTOMAN", "chair", "sofa")),
        ("bean bag chair", target("BEAN BAG", "chair", "sofa")),
        ("beanbag", target("BEAN BAG", "chair", "sofa")),
        ("rocking chair", target("CHAIR", "chair")),
        ("office chair", target("CHAIR", "chair")),
        ("computer chair", target("CHAIR", "chair")),
        ("swivel chair", target("CHAIR", "chair")),
        // Beds
        ("headboard", target("HEADBOARD", "bed")),
        ("mattress", target("MATTRESS", "bed")),
        ("cradle", target("CRIB", "bed")),
        ("infant bed", target("CRIB", "bed")),
        ("cat bed", target("PET BED")),
        ("dog bed", target("PET BED")),
        // Climate and cleaning
        ("heater", target("HEATER")),
        ("radiator", target("RADIATOR")),
        ("air conditioner", target("AIR CONDITIONER")),
        ("humidifier", target("HUMIDIFIER")),
        ("vacuum", target("VACUUM")),
        // Containers and small furnishings
        ("basket", target("BASKET")),
        ("laundry basket", target("BASKET")),
        ("storage box", target("BOX")),
        ("box", target("BOX")),
        ("bin", target("BIN")),
        ("recycling bin", target("BIN")),
        ("candle", target("CANDLE")),
        ("candle holder", target("CANDLE")),
        ("christmas tree", target("CHRISTMAS TREE")),
        ("stuffed toy", target("TOY")),
        ("teddy", target("TOY")),
        ("toy", target("TOY")),
        ("dollhouse", target("DOLLHOUSE")),
        ("cat tree", target("CAT TREE")),
        ("treadmill", target("TREADMILL")),
        ("stationary bicycle", target("EXERCISE BIKE")),
        ("bicycle", target("BICYCLE")),
        ("towel", target("TOWEL")),
        ("towel bar", target("TOWEL")),
        ("umbrella", target("UMBRELLA")),
        ("luggage", target("LUGGAGE")),
        ("backpack", target("BACKPACK")),

        // RoomPlan's own categories
        ("cabinet", roomPlan("STORAGE", "storage")),
        ("kitchen cabinet", roomPlan("STORAGE", "storage")),
        ("bathroom cabinet", roomPlan("STORAGE", "storage")),
        ("dresser", roomPlan("STORAGE", "storage")),
        ("closet", roomPlan("STORAGE", "storage")),
        ("fridge", roomPlan("FRIDGE", "refrigerator")),
        ("stove", roomPlan("STOVE", "stove")),
        ("gas stove", roomPlan("STOVE", "stove")),
        ("oven", roomPlan("OVEN", "oven")),
        ("microwave", roomPlan("OVEN", "oven")),
        ("dish washer", roomPlan("DISHWASHER", "dishwasher")),
        ("washing machine", roomPlan("WASHER", "washerDryer")),
        ("washer", roomPlan("WASHER", "washerDryer")),
        ("sink", roomPlan("SINK", "sink")),
        ("kitchen sink", roomPlan("SINK", "sink")),
        ("bathroom sink", roomPlan("SINK", "sink")),
        ("toilet bowl", roomPlan("TOILET", "toilet")),
        ("toilet seat", roomPlan("TOILET", "toilet")),
        ("bath", roomPlan("BATH", "bathtub")),
        ("shower", .absorber),
        ("table", roomPlan("TABLE", "table")),
        ("dinning table", roomPlan("TABLE", "table")),
        ("kitchen table", roomPlan("TABLE", "table")),
        ("couch", roomPlan("SOFA", "sofa")),
        ("loveseat", roomPlan("SOFA", "sofa")),
        ("chair", roomPlan("CHAIR", "chair")),
        ("bed", roomPlan("BED", "bed")),
        ("bunk bed", roomPlan("BED", "bed")),
        ("canopy bed", roomPlan("BED", "bed")),
        ("daybed", roomPlan("BED", "bed")),
        ("fireplace", roomPlan("FIREPLACE", "fireplace")),
        ("television", roomPlan("TV", "television")),
        ("stairs", roomPlan("STAIRS", "stairs")),

        // Excluded: never boxed, pixels removed from everything else
        ("person", .excluded),
        ("man", .excluded),
        ("woman", .excluded),
        ("child", .excluded),
        ("boy", .excluded),
        ("girl", .excluded),
        ("baby", .excluded),
        ("toddler", .excluded),
        ("teenager", .excluded),
        ("adult", .excluded),
        ("businessman", .excluded),
        ("business woman", .excluded),
        ("crowd", .excluded),
        ("face", .excluded),
        ("hand", .excluded),
        ("foot", .excluded),
        ("leg", .excluded),
        ("arm", .excluded),
        ("head", .excluded),
        ("cat", .excluded),
        ("dog", .excluded),
        ("pet", .excluded),
        ("bird", .excluded),

        // Absorbers: structure, scenes, clutter
        ("wall", .absorber),
        ("floor", .absorber),
        ("ceiling", .absorber),
        ("window", .absorber),
        ("window frame", .absorber),
        ("window sill", .absorber),
        ("door", .absorber),
        ("doorway", .absorber),
        ("room", .absorber),
        ("living room", .absorber),
        ("bedroom", .absorber),
        ("kitchen", .absorber),
        ("bathroom", .absorber),
        ("dining room", .absorber),
        ("home interior", .absorber),
        ("interior design", .absorber),
        ("home", .absorber),
        ("apartment", .absorber),
        ("hardwood floor", .absorber),
        ("wood floor", .absorber),
        ("tile wall", .absorber),
        ("light", .absorber),
        ("lighting", .absorber),
        ("light switch", .absorber),
        ("electric outlet", .absorber),
        ("vent", .absorber),
        ("thermostat", .absorber),
        ("home decor", .absorber),
        ("decor", .absorber),
        ("furniture", .absorber),
        ("book", .absorber),
        ("remote", .absorber),
        ("phone", .absorber),
        ("smartphone", .absorber),
        ("cup", .absorber),
        ("bottle", .absorber),
        ("bowl", .absorber),
        ("plate", .absorber),
        ("tissue", .absorber),
        ("cloth", .absorber),
        ("clothing", .absorber),
        ("shoe", .absorber),
        ("bag", .absorber),
        ("paper towel", .absorber),
        ("toilet paper", .absorber),
    ]

    private static let byName: [String: DetectorRole] = Dictionary(
        entries.map { ($0.name, $0.role) }, uniquingKeysWith: { first, _ in first })

    /// The role of a detector class name; unknown names are absorbers.
    static func role(for name: String) -> DetectorRole {
        byName[name] ?? .absorber
    }

    /// Whether the table knows the name at all.
    static func knows(_ name: String) -> Bool { byName[name] != nil }
}

#endif
