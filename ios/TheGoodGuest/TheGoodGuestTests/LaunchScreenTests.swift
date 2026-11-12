/// Pins that the launch screen is the ground, so a launch never flashes a
/// different colour before the splash's ground arrives.

import SwiftUI
import XCTest
@testable import TheGoodGuest

final class LaunchScreenTests: XCTestCase {

    func testTheLaunchScreenNamesItsColour() throws {
        let launch = try XCTUnwrap(Bundle.main.object(forInfoDictionaryKey: "UILaunchScreen") as? [String: Any])
        XCTAssertEqual(launch["UIColorName"] as? String, "LaunchGround")
    }

    func testTheLaunchColourIsTheGround() throws {
        let launch = try XCTUnwrap(UIColor(named: "LaunchGround"), "LaunchGround is missing from the asset catalog")
        let ground = UIColor(Color.rsGround)
        var l: (CGFloat, CGFloat, CGFloat, CGFloat) = (0, 0, 0, 0)
        var g: (CGFloat, CGFloat, CGFloat, CGFloat) = (0, 0, 0, 0)
        XCTAssertTrue(launch.getRed(&l.0, green: &l.1, blue: &l.2, alpha: &l.3))
        XCTAssertTrue(ground.getRed(&g.0, green: &g.1, blue: &g.2, alpha: &g.3))
        XCTAssertEqual(l.0, g.0, accuracy: 0.5 / 255)
        XCTAssertEqual(l.1, g.1, accuracy: 0.5 / 255)
        XCTAssertEqual(l.2, g.2, accuracy: 0.5 / 255)
        XCTAssertEqual(l.3, 1)
    }
}
