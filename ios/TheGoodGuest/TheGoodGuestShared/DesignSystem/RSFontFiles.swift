/// The three bundled typefaces, registered with Core Text at launch.
///
/// Newsreader (titles and the guest's voice), Albert Sans (everything you
/// operate) and JetBrains Mono (measurements only) are the website's faces,
/// shipped as their variable-font files under `TheGoodGuestShared/Fonts/`
/// with each family's SIL Open Font License beside it. The folder is in both
/// targets, so the app and the Live Activity extension carry the same files.
///
/// REGISTERED IN CODE, not through `UIAppFonts`: the extension's Info.plist
/// is a partial plist merged at build time, and one call from each entry point
/// is easier to see and to test than two plist arrays that must agree with a
/// folder. Registering twice is harmless — Core Text reports the face as
/// already registered and nothing changes — so callers need not coordinate.
///
/// Read by: TheGoodGuestApp.init, TheGoodGuestLiveActivityBundle.init,
/// RSFont (which names the faces). Pinned by: FontRegistrationTests.

import CoreText
import Foundation

enum RSFontFiles {

    /// The files under `Fonts/`, without extension.
    static let files = [
        "Newsreader-Variable",
        "Newsreader-Italic-Variable",
        "AlbertSans-Variable",
        "JetBrainsMono-Variable",
    ]

    /// Register every bundled face for this process. Returns the files that
    /// could not be found or registered, so a test can say which.
    @discardableResult
    static func registerAll(in bundle: Bundle = .main) -> [String] {
        var failed: [String] = []
        for name in files {
            guard let url = bundle.url(forResource: name, withExtension: "ttf") else {
                failed.append(name)
                continue
            }
            var error: Unmanaged<CFError>?
            if !CTFontManagerRegisterFontsForURL(url as CFURL, .process, &error),
               let cfError = error?.takeRetainedValue(),
               CFErrorGetCode(cfError) != CTFontManagerError.alreadyRegistered.rawValue {
                failed.append(name)
            }
        }
        return failed
    }
}
