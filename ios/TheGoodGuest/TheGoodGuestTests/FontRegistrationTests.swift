/// The bundled faces resolve, and the variable axes the type roles set
/// actually reach the font.
///
/// A missing or misnamed face does not crash: Core Text quietly substitutes
/// the system font, and the screen ships in SF with nobody noticing. These
/// tests are what notices — every PostScript name `RSFont.Face` hands out must
/// name a real face once `RSFontFiles` has registered the files.

import CoreText
import SwiftUI
import XCTest
@testable import TheGoodGuest

final class FontRegistrationTests: XCTestCase {

    override func setUp() {
        super.setUp()
        RSFontFiles.registerAll()
    }

    func testEveryBundledFileIsFoundAndRegisters() {
        XCTAssertEqual(RSFontFiles.registerAll(), [],
                       "these font files are missing from the bundle or failed to register")
    }

    func testEveryNamedFaceResolves() {
        let weights: [Font.Weight] = [.ultraLight, .thin, .light, .regular, .medium, .semibold, .bold, .heavy, .black]
        var names = Set([RSFont.Face.serifDefault, RSFont.Face.serifItalicDefault,
                         RSFont.Face.sansDefault, RSFont.Face.monoDefault])
        for w in weights {
            names.insert(RSFont.Face.serif(w))
            names.insert(RSFont.Face.serifItalic(w))
            names.insert(RSFont.Face.sans(w))
            names.insert(RSFont.Face.mono(w))
        }
        for name in names.sorted() {
            XCTAssertNotNil(UIFont(name: name, size: 17), "\(name) does not resolve")
        }
    }

    func testEachRoleDrawsInItsOwnFamily() {
        XCTAssertEqual(RSFont.uiFont(role: .display, size: 34, weight: nil).familyName, "Newsreader")
        XCTAssertEqual(RSFont.uiFont(role: .guest, size: 19, weight: nil).familyName, "Newsreader")
        XCTAssertEqual(RSFont.uiFont(role: .ui, size: 17, weight: nil).familyName, "Albert Sans")
        XCTAssertEqual(RSFont.uiFont(role: .mono, size: 13, weight: nil).familyName, "JetBrains Mono")
    }

    func testTheGuestIsItalicAndTitlesAreNot() {
        let guest = RSFont.uiFont(role: .guest, size: 19, weight: nil)
        let title = RSFont.uiFont(role: .display, size: 34, weight: nil)
        XCTAssertTrue(guest.fontDescriptor.symbolicTraits.contains(.traitItalic))
        XCTAssertFalse(title.fontDescriptor.symbolicTraits.contains(.traitItalic))
    }

    func testTitlesAreLightByDefaultAndWeightsReachTheAxis() {
        XCTAssertEqual(axis("wght", of: RSFont.uiFont(role: .display, size: 34, weight: nil)), 300)
        XCTAssertEqual(axis("wght", of: RSFont.uiFont(role: .ui, size: 17, weight: .semibold)), 600)
        XCTAssertEqual(axis("wght", of: RSFont.uiFont(role: .mono, size: 13, weight: nil)), 500)
    }

    func testTheSerifsOpticalSizeFollowsThePointSizeWithinItsRange() {
        XCTAssertEqual(axis("opsz", of: RSFont.uiFont(role: .display, size: 40, weight: nil)), 40)
        XCTAssertEqual(axis("opsz", of: RSFont.uiFont(role: .display, size: 96, weight: nil)), 72)
        XCTAssertEqual(axis("opsz", of: RSFont.uiFont(role: .guest, size: 15, weight: nil)), 15)
    }

    /// The value Core Text reports for one variation axis of a font.
    private func axis(_ tag: String, of font: UIFont) -> CGFloat? {
        let id = tag.utf8.reduce(UInt32(0)) { ($0 << 8) | UInt32($1) }
        guard let variation = CTFontCopyVariation(font as CTFont) as? [NSNumber: NSNumber] else { return nil }
        return variation[NSNumber(value: id)].map { CGFloat($0.doubleValue) }
    }
}
