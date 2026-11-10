/// A room's own screen, and the moment it is ready.
///
/// `RoomScreen` is every state a room passes through before it is ready —
/// sending, being rebuilt, paused, held by today's limit, refused, missing
/// files — drawn as three steps, the guest's sentence and at most two actions.
/// What it says is `RoomStatusCopy`'s; this file only draws it.
///
/// `ReadyScreen` is the arrival: the room itself by lamplight, on dusk, the
/// website's closing image carried onto the phone. A signed-in person opens it
/// on the web; a guest is offered sign-in, because the web cannot show an
/// anonymous phone's rooms (RoomHistory.webHandoffLands).
///
/// Read by: RootFlowView (both), the gallery.

import SwiftUI

// MARK: - A room on its way, or one that needs you

struct RoomScreen: View {
    let title: String
    let status: RoomStatus
    var onAction: (RoomAction) -> Void = { _ in }

    @State private var showsDetails = false
    @State private var confirmingDiscard = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                Text(title)
                    .rsFont(.display, size: 32, cap: .display)
                    .tracking(-0.6)
                    .foregroundStyle(Color.rsInk)
                    .fixedSize(horizontal: false, vertical: true)
                    .accessibilityAddTraits(.isHeader)

                RoomStepsView(steps: status.steps)
                    .padding(EdgeInsets(top: 18, leading: 16, bottom: 18, trailing: 18))
                    .background(Color.rsSurface, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
                    .shadow(color: Color.rsInk.opacity(0.05), radius: 14, y: 8)
                    .padding(.top, 22)

                if let note = status.note {
                    Label {
                        Text(note)
                            .rsFont(.ui, size: 15)
                            .foregroundStyle(Color.rsInk2)
                            .fixedSize(horizontal: false, vertical: true)
                    } icon: {
                        Image(systemName: "info.circle")
                            .font(.system(size: 15))
                            .foregroundStyle(Color.rsInk2)
                    }
                    .padding(.top, 14)
                    .padding(.horizontal, 4)
                }

                GuestVoice(status.guest)
                    .padding(.top, 26)
                    .padding(.horizontal, 4)

                if let details = status.details {
                    DisclosureGroup(isExpanded: $showsDetails) {
                        Text("The send stopped with: \(details). If you write to us, this line helps.")
                            .rsFont(.ui, size: 14)
                            .foregroundStyle(Color.rsInk2)
                            .textSelection(.enabled)
                            .fixedSize(horizontal: false, vertical: true)
                            .padding(.top, 6)
                    } label: {
                        Text("Details")
                            .rsFont(.ui, size: 15, weight: .semibold)
                            .foregroundStyle(Color.rsInk)
                    }
                    .tint(Color.rsInk)
                    .padding(.top, 20)
                    .padding(.horizontal, 4)
                }
            }
            .padding(.horizontal, 16)
            .padding(.top, 4)
            .padding(.bottom, 24)
        }
        .background(GroundBackground())
        .navigationBarTitleDisplayMode(.inline)
        .safeAreaInset(edge: .bottom, spacing: 0) {
            if status.primary != nil || status.secondary != nil {
                actions
            }
        }
        // Letting a scan go deletes it from the phone, and it is the one action
        // here that cannot be taken back, so it asks first — as stopping a
        // scan and discarding at review do.
        .confirmationDialog(RoomScreen.discardTitle, isPresented: $confirmingDiscard, titleVisibility: .visible) {
            Button(RoomScreen.discardConfirm, role: .destructive) { onAction(.discard) }
            Button("Keep it", role: .cancel) {}
        } message: {
            Text(RoomScreen.discardMessage)
        }
    }

    static let discardTitle = "Let this scan go?"
    static let discardConfirm = "Let it go"
    static let discardMessage = "It’s deleted from this phone and the room isn’t sent. Sending it later means walking the room again."

    /// Every button goes through here, so the one that cannot be undone asks
    /// first wherever it appears.
    private func perform(_ action: RoomAction) {
        if action == .discard {
            confirmingDiscard = true
        } else {
            onAction(action)
        }
    }

    private var actions: some View {
        VStack(spacing: 2) {
            if let primary = status.primary {
                Button { perform(primary.action) } label: {
                    HStack(spacing: 10) {
                        if primary.busy { ProgressView().tint(.white) }
                        Text(primary.label)
                    }
                }
                .buttonStyle(RSPrimaryButtonStyle())
                .disabled(!primary.enabled)
                .opacity(primary.enabled ? 1 : 0.4)
            }
            if let secondary = status.secondary {
                Button(secondary.label) { perform(secondary.action) }
                    .buttonStyle(RSQuietButtonStyle())
            }
        }
        .padding(.horizontal, 20)
        .padding(.top, 12)
        .padding(.bottom, 4)
        .background(Color.rsGround.ignoresSafeArea(edges: .bottom))
    }
}

/// The three steps, each with its mark and at most one line under it.
struct RoomStepsView: View {
    let steps: [RoomStep]

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            ForEach(Array(steps.enumerated()), id: \.offset) { index, step in
                HStack(alignment: .top, spacing: 14) {
                    VStack(spacing: 0) {
                        StepMark(mark: step.mark)
                        if index < steps.count - 1 {
                            Rectangle()
                                .fill(Color.rsHairline)
                                .frame(width: 1)
                                .frame(maxHeight: .infinity)
                                .padding(.vertical, 3)
                        }
                    }
                    VStack(alignment: .leading, spacing: 3) {
                        Text(step.title)
                            .rsFont(.ui, size: 16, weight: step.mark == .waiting ? .medium : .semibold)
                            .foregroundStyle(step.mark == .waiting ? Color.rsInk2 : Color.rsInk)
                            .fixedSize(horizontal: false, vertical: true)
                        if let detail = step.detail {
                            Text(detail)
                                .rsFont(.ui, size: 14)
                                .foregroundStyle(Color.rsInk2)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                    .padding(.top, 1)
                    .padding(.bottom, index < steps.count - 1 ? 18 : 0)
                    Spacer(minLength: 0)
                }
                .accessibilityElement(children: .combine)
                .accessibilityLabel(accessibility(step))
            }
        }
    }

    private func accessibility(_ step: RoomStep) -> String {
        let state: String = switch step.mark {
        case .done: "done"
        case .now: "happening now"
        case .waiting: "not yet"
        case .paused: "paused"
        case .attention: "needs you"
        }
        return [step.title, step.detail, state].compactMap { $0 }.joined(separator: ", ")
    }
}

private struct StepMark: View {
    let mark: RoomStep.Mark
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var breathe = false

    var body: some View {
        ZStack {
            switch mark {
            case .done:
                Circle().fill(Color.rsInk)
                Image(systemName: "checkmark")
                    .font(.system(size: 11, weight: .bold))
                    .foregroundStyle(Color.white)
            case .now:
                Circle().strokeBorder(Color.rsInk, lineWidth: 1.5)
                Circle().fill(Color.rsInk)
                    .frame(width: 8, height: 8)
                    .scaleEffect(breathe ? 1.0 : 0.75)
                    .onAppear {
                        guard !reduceMotion else { return }
                        withAnimation(.easeInOut(duration: 1.1).repeatForever(autoreverses: true)) { breathe = true }
                    }
            case .waiting:
                Circle().strokeBorder(Color.rsInk.opacity(0.22), lineWidth: 1.5)
            case .paused:
                Circle().strokeBorder(Color.rsInk, lineWidth: 1.5)
                Image(systemName: "pause.fill")
                    .font(.system(size: 8, weight: .bold))
                    .foregroundStyle(Color.rsInk)
            case .attention:
                Circle().fill(Color.rsSurface)
                Circle().strokeBorder(Color.rsInk, lineWidth: 1.5)
                Image(systemName: "exclamationmark")
                    .font(.system(size: 10, weight: .heavy))
                    .foregroundStyle(Color.rsInk)
            }
        }
        .frame(width: 22, height: 22)
        .accessibilityHidden(true)
    }
}

// MARK: - The room, ready

struct ReadyScreen: View {
    let roomTitle: String
    var sceneId: String?
    var stillURL: URL? = nil
    var stillNightURL: URL? = nil
    /// Signed in, with a web origin: the room opens on the web.
    let canOpenWeb: Bool
    /// The room's web address, for sharing to another device.
    var shareURL: URL? = nil
    /// Play the arrival (haptic and knock) once, when the room has just landed.
    var isArrival = false
    var onOpen: () -> Void = {}
    var onSignIn: () -> Void = {}
    var onScanAnother: () -> Void = {}
    var onDone: () -> Void = {}

    @ObservedObject private var pictures = RoomPictureStore.shared

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                RoomPicture(sceneId: sceneId, stillURL: stillURL, stillNightURL: stillNightURL, night: true)
                    .frame(height: 340)
                    .clipShape(RoundedRectangle(cornerRadius: 26, style: .continuous))

                Text("Your room is ready.")
                    .rsFont(.display, size: 38, cap: .display)
                    .tracking(-0.9)
                    .foregroundStyle(Color.rsOnDusk)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.top, 24)
                    .accessibilityAddTraits(.isHeader)

                HStack(alignment: .firstTextBaseline, spacing: 12) {
                    if let sceneId, let outline = pictures.outlines[sceneId] {
                        MeasureText(outline.sizeText, onDusk: true)
                    }
                    Text(roomTitle)
                        .rsFont(.ui, size: 14)
                        .foregroundStyle(Color.rsOnDusk2)
                }
                .padding(.top, 8)

                GuestVoice(canOpenWeb
                           ? "It’s ready. Come in when you have a minute."
                           : "It’s ready, and it’s yours. Sign in, and I can show it to you on any screen.",
                           onDark: true)
                    .padding(.top, 22)
            }
            .padding(.horizontal, 16)
            .padding(.top, 4)
            .padding(.bottom, 24)
        }
        .background(Color.rsDusk.ignoresSafeArea())
        .toolbarBackground(Color.rsDusk, for: .navigationBar)
        .toolbarColorScheme(.dark, for: .navigationBar)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            if canOpenWeb, let shareURL {
                ToolbarItem(placement: .topBarTrailing) {
                    ShareLink(item: shareURL) {
                        Image(systemName: "square.and.arrow.up")
                    }
                    .accessibilityLabel("Send the room's link to another device")
                }
            }
        }
        .safeAreaInset(edge: .bottom, spacing: 0) { actions }
        .onAppear {
            guard isArrival else { return }
            RSHaptics.fire(.roomReady)
            RSSound.play(.readyKnock)
        }
    }

    private var actions: some View {
        VStack(spacing: 6) {
            if canOpenWeb {
                Button(action: onOpen) {
                    HStack(spacing: 8) {
                        Text("Open the room")
                        Image(systemName: "arrow.up.right")
                            .font(.system(size: 15, weight: .semibold))
                    }
                }
                .buttonStyle(RSPrimaryButtonStyle(onDusk: true))
                Text("Opens in Safari. If it asks, sign in with the same Apple ID or Google account.")
                    .rsFont(.ui, size: 13)
                    .foregroundStyle(Color.rsOnDusk2)
                    .multilineTextAlignment(.center)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.horizontal, 8)
                Button("Scan another room", action: onScanAnother)
                    .buttonStyle(RSQuietButtonStyle(onDark: true))
            } else {
                Button("Sign in to open it", action: onSignIn)
                    .buttonStyle(RSPrimaryButtonStyle(onDusk: true))
                Text("Your rooms live on this iPhone for now. Sign in with Apple or Google, and this one opens on your computer too.")
                    .rsFont(.ui, size: 13)
                    .foregroundStyle(Color.rsOnDusk2)
                    .multilineTextAlignment(.center)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.horizontal, 8)
                Button("Not now", action: onDone)
                    .buttonStyle(RSQuietButtonStyle(onDark: true))
            }
        }
        .padding(.horizontal, 20)
        .padding(.top, 12)
        .padding(.bottom, 4)
        .background(Color.rsDusk.ignoresSafeArea(edges: .bottom))
    }
}
