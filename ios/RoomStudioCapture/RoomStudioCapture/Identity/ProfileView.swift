/// Profile — identity, framed warmly (design spec §8). You are someone from first
/// launch; your ID is shown as proof of continuity. "A guest, so far" frames the
/// anonymous state as warm, not incomplete. The ID is mono (machine data) and
/// copyable, so continuity is provable. Sign in with Apple LINKS the identity
/// rather than replacing it — no room is lost. Sign-out deliberately lives on the
/// web; the phone only ever gains identity.
///
/// Restyle of the existing SignInSheet; the spine integration binds `uid`/
/// `isLinked` to AuthManager and routes the Apple button through
/// AuthManager.linkAppleAccount (decision 0051/0064). Device SIWA stays
/// enrollment-gated.

import SwiftUI

struct ProfileView: View {
    /// The real UID, or nil when sign-in hasn't landed yet (offline first launch).
    /// Required and OPTIONAL by design: no default, so a fabricated identity can
    /// never be rendered by accident — and nil renders an honest "not ready" state
    /// rather than a placeholder string masquerading as an ID (which would also be
    /// copyable to the pasteboard).
    var uid: String?
    var isLinked: Bool = false
    var onClose: () -> Void = {}

    @State private var copied = false
    @State private var showSignIn = false

    var body: some View {
        VStack(spacing: 0) {
            header

            // Scrollable: at accessibility sizes the intro copy alone fills the
            // screen, pushing the ID card and the sign-in action off the bottom.
            ScrollView {
                VStack(spacing: 0) {
                    Mark(height: 34)
                        .padding(.top, 6)

                    Text(isLinked ? "Signed in" : "A guest, so far")
                        .rsFont(.guest, size: 18)
                        .foregroundStyle(Color.rsInk)
                        .padding(.top, 14)

                    Text("This device is already someone — your rooms are tied to the ID below. Sign in to keep them safe across devices.")
                        .font(RSFont.ui(.subheadline))
                        .foregroundStyle(Color.rsInkMuted)
                        .multilineTextAlignment(.center)
                        .fixedSize(horizontal: false, vertical: true)
                        .padding(.top, 6)
                        .padding(.horizontal, 20)

                    idCard
                        .padding(.top, 22)

                    if !isLinked {
                        // Opens the real, conflict-aware sign-in flow (SignInSheet →
                        // AuthManager.linkAppleAccount). The native Apple button lives
                        // inside that sheet — we don't fake it here.
                        Button { showSignIn = true } label: {
                            Text("Sign in to keep your rooms")
                                .font(RSFont.ui(.headline, weight: .semibold))
                                .foregroundStyle(Color.rsSurface)
                                .multilineTextAlignment(.center)
                                .fixedSize(horizontal: false, vertical: true)
                                .frame(maxWidth: .infinity)
                                .padding(.vertical, 15)
                                .background(Color.rsInk, in: RoundedRectangle(cornerRadius: 13, style: .continuous))
                        }
                        .padding(.top, 16)
                    }

                    Text("Signing out lives on the web — this app only ever remembers you")
                        .font(RSFont.ui(.footnote))
                        .foregroundStyle(Color.rsInkFaint)
                        .multilineTextAlignment(.center)
                        .fixedSize(horizontal: false, vertical: true)
                        .padding(.top, 28)
                        .padding(.bottom, 14)
                }
                .padding(.top, 16)
            }
        }
        .padding(.horizontal, 26)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .rsParchmentScreen()
        .sheet(isPresented: $showSignIn) { SignInSheet() }
    }

    private var header: some View {
        HStack(spacing: 10) {
            Button(action: onClose) {
                Image(systemName: "chevron.left")
                    .font(.system(size: 18, weight: .medium))
                    .foregroundStyle(Color.rsInkMuted)
            }
            Text("You")
                .rsFont(.display, size: 17, weight: .medium)
                .foregroundStyle(Color.rsInk)
            Spacer()
        }
        .padding(.top, 8)
    }

    private var idCard: some View {
        HStack(spacing: 10) {
            VStack(alignment: .leading, spacing: 3) {
                Eyebrow("Your ID")
                if let uid {
                    Text(uid)
                        // Wraps rather than truncates: a partial ID can't serve as
                        // proof of identity continuity, which is this card's job.
                        .rsFont(.mono, size: 13.5, weight: .medium, maxSize: 20)
                        .fixedSize(horizontal: false, vertical: true)
                        .foregroundStyle(Color.rsInk)
                } else {
                    Text("Not ready yet — I'll have it once I reach the desk.")
                        .font(RSFont.ui(.footnote))
                        .foregroundStyle(Color.rsInkMuted)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            Spacer()
            if let uid {
                Button {
                    UIPasteboard.general.string = uid
                    withAnimation { copied = true }
                    DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) {
                        withAnimation { copied = false }
                    }
                } label: {
                    Image(systemName: copied ? "checkmark" : "doc.on.doc")
                        .font(.system(size: 14, weight: .medium))
                        .foregroundStyle(copied ? Color.rsAffirm : Color.rsInk)
                        .frame(width: 34, height: 34)
                        .background(Color.rsInk.opacity(0.08), in: RoundedRectangle(cornerRadius: 9, style: .continuous))
                }
                .accessibilityLabel("Copy your ID")
            }
        }
        .padding(14)
        .background(Color.rsInk.opacity(0.05), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).stroke(Color.rsHairline, lineWidth: 1))
    }
}

#Preview {
    ProfileView(uid: "rs_a4f9-2c7e-91d0")
}
