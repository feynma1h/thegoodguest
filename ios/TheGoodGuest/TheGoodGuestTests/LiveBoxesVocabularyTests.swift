/// Pins for what the detector's class names mean to the review view: the
/// near-synonym mappings the charter settled (a word the built-in vocabulary
/// lacks is reached through one it has), people and animals never boxed, every
/// RoomPlan token a real RoomPlan category, and the vocabulary staying inside
/// the bound where an FP16 export's class indices are exact.

import XCTest
@testable import TheGoodGuest

final class LiveBoxesVocabularyTests: XCTestCase {

    private func label(_ name: String) -> String? { DetectorVocabulary.role(for: name).label }

    func test_names_areUnique() {
        let names = DetectorVocabulary.entries.map(\.name)
        XCTAssertEqual(Set(names).count, names.count)
    }

    func test_vocabulary_staysWhereFP16ClassIndicesAreExact() {
        // Float16 represents every integer only up to 2048; beyond it the
        // exported class index silently becomes a neighbour's.
        XCTAssertLessThan(DetectorVocabulary.entries.count, 2048)
    }

    func test_missingWords_areReachedThroughNamesTheListHas() {
        XCTAssertEqual(label("carpet"), "RUG")
        XCTAssertEqual(label("pillow"), "CUSHION")
        XCTAssertEqual(label("throw pillow"), "CUSHION")
        XCTAssertEqual(label("picture frame"), "ARTWORK")
        XCTAssertEqual(label("poster"), "ARTWORK")
        XCTAssertEqual(label("cocktail table"), "COFFEE TABLE")
        XCTAssertEqual(label("houseplant"), "PLANT")
        XCTAssertEqual(label("computer monitor"), "MONITOR")
        XCTAssertEqual(label("side table"), "SIDE TABLE")
        XCTAssertEqual(label("bookshelf"), "SHELF")
        XCTAssertEqual(label("mirror"), "MIRROR")
        XCTAssertEqual(label("curtain"), "CURTAIN")
        XCTAssertEqual(label("table lamp"), "LAMP")
    }

    func test_floorCoverings_areFlat_andNothingElseIs() {
        for (name, role) in DetectorVocabulary.entries {
            guard case .target(let l, let flat, _) = role else { continue }
            XCTAssertEqual(flat, l == "RUG" || l == "MAT", "\(name) → \(l)")
        }
    }

    func test_peopleAndAnimals_areExcluded_andNeverLifted() {
        for name in ["person", "man", "woman", "child", "boy", "girl", "baby", "toddler", "cat", "dog"] {
            XCTAssertEqual(DetectorVocabulary.role(for: name), .excluded, name)
            XCTAssertFalse(DetectorVocabulary.role(for: name).isLifted, name)
        }
    }

    func test_roomPlansOwnCategories_areLiftedOnlyWhenAskedFor() {
        let chair = DetectorVocabulary.role(for: "chair")
        guard case .roomPlanCategory = chair else { return XCTFail("chair is one of RoomPlan's") }
        XCTAssertFalse(chair.isLifted(includingRoomPlanCategories: false))
        XCTAssertTrue(chair.isLifted(includingRoomPlanCategories: true))
        XCTAssertTrue(DetectorVocabulary.role(for: "lamp").isLifted(includingRoomPlanCategories: false))
        XCTAssertFalse(DetectorVocabulary.role(for: "person").isLifted(includingRoomPlanCategories: true))
    }

    func test_namesThatCanBeAPersonsBody_areExcluded() {
        // A person scoring under the threshold can still fire one of these on
        // their own body; boxing it would box the person (0089).
        for name in ["face", "hand", "foot", "leg", "arm", "head", "chest"] {
            XCTAssertEqual(DetectorVocabulary.role(for: name), .excluded, name)
        }
    }

    func test_everyRoomPlanToken_isARoomPlanCategory() {
        // RoomPlan's 16, as `String(describing:)` spells them (FloorPlanVoice's table).
        let roomPlan: Set<String> = ["storage", "refrigerator", "stove", "bed", "sink", "washerDryer",
                                     "toilet", "bathtub", "oven", "dishwasher", "table", "sofa", "chair",
                                     "fireplace", "television", "stairs"]
        for (name, role) in DetectorVocabulary.entries {
            switch role {
            case .target(_, _, let overlap):
                XCTAssertTrue(overlap.isSubset(of: roomPlan), "\(name): \(overlap)")
            case .roomPlanCategory(_, let category):
                XCTAssertTrue(roomPlan.contains(category), "\(name): \(category)")
            case .excluded, .absorber:
                break
            }
        }
    }

    func test_labels_areUppercaseMachineData() {
        for (name, role) in DetectorVocabulary.entries {
            guard let l = role.label else { continue }
            XCTAssertFalse(l.isEmpty, name)
            XCTAssertEqual(l, l.uppercased(), name)
        }
    }

    func test_anUnknownName_degradesToAnAbsorber() {
        XCTAssertEqual(DetectorVocabulary.role(for: "rocket ship"), .absorber)
        XCTAssertFalse(DetectorVocabulary.knows("rocket ship"))
        XCTAssertTrue(DetectorVocabulary.knows("lamp"))
    }
}
