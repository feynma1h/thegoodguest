/// The retired cream-era colour names, mapped onto the new palette while the
/// screens that still say them are rebuilt. NOTHING NEW may use these: each
/// rebuilt screen names an `RSColor` token, and this file is deleted in the
/// commit that rebuilds the last caller.
///
/// The mapping keeps meaning, not hue: the old rust "action" was the brand ink
/// and stays terracotta (the mark still reads it); the old gold was light and
/// becomes lamplight; the old muted and faint inks both become secondary ink,
/// because faint ink was used for small captions that must reach 4.5:1.

import SwiftUI

extension Color {
    static var rsBackground: Color { .rsGround }
    static var rsInkMuted: Color { .rsInk2 }
    static var rsInkFaint: Color { .rsInk2 }
    static var rsAction: Color { .rsTerracotta }
    static var rsActionPressed: Color { .rsTerracottaText }
    static var rsGold: Color { .rsLamp }
    static var rsGoldInk: Color { .rsInk }
    static var rsGoldLight: Color { .rsLamp }
    static var rsBlack: Color { .rsDusk }
    static var rsCaptureBase: Color { .rsDusk }
    static var rsCaptureRaised: Color { .rsRaised }
    static var rsOnDark: Color { .rsOnDusk }
    static var rsSensorGood: Color { .rsOnDusk2 }
    static var rsSensorWarn: Color { .rsLamp }
    static var rsSensorLost: Color { .rsOnDusk }
    static var rsAffirm: Color { .rsInk }
}
