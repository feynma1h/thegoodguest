/// Google's sign-in button, drawn to sit beside Apple's as its equal: the same
/// height and shape, white with Google's one-point outline, and Google's own G.
///
/// WHY NOT THE SDK'S BUTTON. GoogleSignInSwift's button is a fixed 40pt
/// rectangle with a drop shadow; next to Apple's 54pt pill it read as the
/// lesser option, and Google's branding guidelines ask for the opposite — the
/// Google button "at least as prominently as other third party sign-in
/// options", "approximately the same size". The guidelines allow a custom
/// button that keeps the standard-colour G on white, the wording, a white fill
/// with a #747775 one-point inside stroke and #1F1F1F text, in a pill or a
/// rectangle.
///
/// THE G IS GOOGLE'S, never redrawn: it is read from the GoogleSignIn SDK's own
/// resource bundle, the same image the SDK's button draws. A test pins that it
/// resolves, so an SDK update that moves it fails there rather than shipping a
/// button without its mark.
///
/// Read by: AccountSheet.

import SwiftUI
import UIKit

struct GoogleSignInPill: View {
    var disabled: Bool = false
    var action: () -> Void

    static let height: CGFloat = 54

    /// Google's G, from the SDK's bundle inside the app.
    static var logo: UIImage? {
        guard let url = Bundle.main.url(forResource: "GoogleSignIn_GoogleSignIn", withExtension: "bundle"),
              let bundle = Bundle(url: url) else { return nil }
        return UIImage(named: "google", in: bundle, with: nil)
    }

    var body: some View {
        Button(action: action) {
            HStack(spacing: 12) {
                if let logo = Self.logo {
                    Image(uiImage: logo)
                        .resizable()
                        .frame(width: 20, height: 20)
                        .accessibilityHidden(true)
                }
                Text("Sign in with Google")
                    .rsFont(.ui, size: 17, weight: .medium)
                    .foregroundStyle(Color(rsHex: 0x1F1F1F))
                    .lineLimit(1)
                    .minimumScaleFactor(0.8)
            }
            .padding(.horizontal, 16)
            .frame(maxWidth: .infinity, minHeight: Self.height)
            .background(Color.white, in: Capsule())
            .overlay(Capsule().strokeBorder(Color(rsHex: 0x747775), lineWidth: 1))
            .contentShape(Capsule())
        }
        .buttonStyle(.plain)
        .rsControlLabel()
        .disabled(disabled)
        .opacity(disabled ? 0.45 : 1)
    }
}
