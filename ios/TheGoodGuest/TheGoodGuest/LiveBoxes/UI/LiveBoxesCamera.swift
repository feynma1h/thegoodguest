/// The camera behind the Scan screen, with a box to take for every object the
/// person wants — DEBUG-only (decision 0295).
///
/// Decision 0295 first said live boxes never run during a capture; decision 0301
/// lets them, on one condition: a `LiveBoxesSession` rides the CAPTURE's own
/// ARSession, fed frames by `CaptureManager.frameTap`, so there is one session
/// and the bundle is produced exactly as it is without this view. The boxes the
/// person made and kept enter the bundle, once, as the capture stops
/// (`CaptureManager.keptBoxes`, decision 0320); the stills below never do.
///
/// TAP A DOT, BOXED. Every object found wears a dot; tapping one boxes that
/// object. No names are drawn: a detection's label can be wrong.
///
/// A BOX IS CURRENT, THEN SETTLED. The box just made is current: it breathes
/// and keeps easing toward the detector's fit, so walking round it improves it.
/// "Looks good", or boxing the next object, settles it: it stops changing for
/// good, with a soft tap and a check. Big objects seen from one side, and glass
/// the outlines have not pinned, say so: "Walk around it to finish the box".
///
/// TAKING A BOX BACK. A chip, "N boxes", opens a strip of stills, newest first;
/// tapping one points to its box (a pulse over it, or a glow on the edge to turn
/// toward) and offers Remove. "Box added" and "Box removed" both carry Undo.
/// The scan's own Finish stays LiveCaptureView's, and is the only one.
///
/// Read by: RootFlowView (the Scan screen's camera layer).

#if DEBUG

import Combine
import SwiftUI
import simd

struct LiveBoxesCamera: View {
    let capture: CaptureManager
    @StateObject private var session = LiveBoxesSession()
    @StateObject private var thumbs = BoxThumbs()
    @State private var overlay = ProjectedOverlay()
    /// The boxes made, as `CaptureManager` reads them when the capture stops.
    @State private var ledger = KeptLedger()
    /// The objects the person has boxed, newest first, and the one still being worked on.
    @State private var boxed: Set<UUID> = []
    @State private var order: [UUID] = []
    @State private var current: UUID?
    @State private var toast: LiveBoxesPresentation.Toast?
    @State private var stripOpen = false
    @State private var selected: UUID?
    @State private var check: UUID?

    /// The box being worked on, if its object is still there.
    private var working: UUID? {
        current.flatMap { id in session.tracks.contains { $0.id == id } ? id : nil }
    }

    private var needsWalkAround: Bool {
        LiveBoxesPresentation.needsWalkAround(working.flatMap { id in session.tracks.first { $0.id == id } })
    }

    var body: some View {
        ZStack {
            LiveBoxesARHost(session: capture.arSession,
                            scene: LiveBoxesPresentation.scene(session.tracks, boxed: boxed, current: current,
                                                               locked: working != nil,
                                                               tops: session.latestSight?.tops ?? []),
                            overlay: overlay,
                            thumbs: thumbs, locate: selected,
                            onNote: { session.note("occlusion", $0) },
                            sight: { session.latestSight })
                // Lines and camera ease out together toward the bottom, where the guest's words and Finish sit.
                .mask(LinearGradient(stops: [.init(color: .white, location: 0),
                                             .init(color: .white, location: 0.6),
                                             .init(color: .white.opacity(0.3), location: 0.88)],
                                     startPoint: .top, endPoint: .bottom))
            OverlayLayer(overlay: overlay, activate: { box($0) })
            LocatorGlow(overlay: overlay)
            PickedGlow(overlay: overlay)
            CheckLayer(overlay: overlay, id: check)
            toastView
            controls
        }
        .animation(.easeOut(duration: 0.2), value: toast)
        .animation(.easeOut(duration: 0.2), value: stripOpen)
        .animation(.easeOut(duration: 0.2), value: current)
        .ignoresSafeArea()
        .onChange(of: boxed) { _, now in ledger.record(now, at: Int64(CACurrentMediaTime() * 1_000_000)) }
        .onAppear {
            capture.frameTap = session.driver
            capture.keptBoxes = { [session, ledger] in
                LiveBoxesPresentation.kept(session.tracks, boxed: ledger.boxed, madeAt: ledger.madeAt,
                                           now: Int64(CACurrentMediaTime() * 1_000_000),
                                           tops: session.latestSight?.tops ?? [])
            }
            session.start()
        }
        .onDisappear {
            capture.frameTap = nil
            capture.keptBoxes = nil
            session.stop()
        }
    }

    // MARK: Chrome

    private var visible: [UUID] { order.filter(boxed.contains) }

    private var controls: some View {
        VStack(spacing: 10) {
            Spacer()
            if stripOpen, !visible.isEmpty {
                BoxStrip(overlay: overlay, thumbs: thumbs, ids: visible, selected: selected,
                         select: select, remove: remove)
                    .transition(.opacity)
            }
            ZStack {
                HStack {
                    if !visible.isEmpty {
                        Button { toggleStrip() } label: {
                            Text(LiveBoxesPresentation.countLabel(visible.count))
                                .font(RSFont.ui(.footnote, weight: .semibold))
                                .foregroundStyle(Color.rsOnDusk)
                                .padding(.horizontal, 14).padding(.vertical, 9)
                                .background(Capsule().fill(Color.rsDusk.opacity(stripOpen ? 0.8 : 0.55)))
                        }
                    }
                    Spacer()
                }
                if let id = working {
                    VStack(spacing: 8) {
                        if needsWalkAround {
                            Text(LiveBoxesPresentation.walkAroundHint)
                                .font(RSFont.ui(.footnote, weight: .semibold))
                                .foregroundStyle(Color.rsOnDusk)
                                .padding(.horizontal, 12).padding(.vertical, 7)
                                .background(Capsule().fill(Color.rsDusk.opacity(0.62)))
                                .transition(.opacity)
                        }
                        HStack(spacing: 10) {
                            Button { settleCurrent(id) } label: {
                                Label("Looks good", systemImage: "checkmark")
                                    .font(RSFont.ui(.footnote, weight: .semibold))
                                    .foregroundStyle(Color.rsDusk)
                                    .padding(.horizontal, 16).padding(.vertical, 9)
                                    .background(Capsule().fill(BoxInk.white))
                            }
                            // A way out of a box that is not worth finishing.
                            Button { remove(id) } label: {
                                Image(systemName: "xmark")
                                    .font(.system(size: 12, weight: .bold))
                                    .foregroundStyle(Color.rsOnDusk)
                                    .frame(width: 34, height: 34)
                                    .background(Circle().fill(Color.rsDusk.opacity(0.62)))
                            }
                            .accessibilityLabel("Discard this box")
                        }
                    }
                    .transition(.opacity)
                }
            }
        }
        .padding(.horizontal, 22)
        .padding(.bottom, 252)
    }

    @ViewBuilder private var toastView: some View {
        if let toast {
            VStack {
                Button { undo(toast) } label: {
                    Text(toast.label)
                        .font(RSFont.ui(.footnote, weight: .semibold))
                        .foregroundStyle(Color.rsOnDusk)
                        .padding(.horizontal, 14).padding(.vertical, 9)
                        .background(Capsule().fill(Color.rsDusk.opacity(0.62)))
                }
                Spacer()
            }
            .padding(.top, 110)
            .transition(.opacity)
        }
    }

    // MARK: Actions

    /// Only an object that is found and not already boxed takes a box. The one
    /// being worked on settles as the next is boxed.
    private func box(_ id: UUID) {
        guard !boxed.contains(id), let track = session.tracks.first(where: { $0.id == id && $0.confirmed }) else { return }
        // A second track of an object already boxed is not boxed again.
        let fit = track.locked?.box ?? track.box
        guard !session.tracks.contains(where: { other in
            boxed.contains(other.id) && other.label == track.label
                && DotRules.overlapsAsSame(fit, other.locked?.box ?? other.box)
        }) else { return }
        if let was = current, was != id { settle(was) }
        boxed.insert(id)
        order.removeAll { $0 == id }
        order.insert(id, at: 0)
        current = id
        thumbs.capture(id)
        show(.added(id))
        UIImpactFeedbackGenerator(style: .rigid).impactOccurred(intensity: 0.5)
    }

    private func settleCurrent(_ id: UUID) {
        current = nil
        settle(id)
    }

    private func settle(_ id: UUID) {
        UIImpactFeedbackGenerator(style: .soft).impactOccurred()
        check = id
        Task {
            try? await Task.sleep(for: .seconds(0.7))
            if check == id { check = nil }
        }
    }

    private func remove(_ id: UUID) {
        guard boxed.remove(id) != nil else { return }
        if current == id { current = nil }
        selected = nil
        if boxed.isEmpty { stripOpen = false }
        show(.removed(id))
    }

    private func undo(_ toast: LiveBoxesPresentation.Toast) {
        switch toast {
        case .added(let id):
            boxed.remove(id)
            if current == id { current = nil }
        case .removed(let id):
            boxed.insert(id)
        }
        self.toast = nil
    }

    private func show(_ next: LiveBoxesPresentation.Toast) {
        toast = next
        Task {
            try? await Task.sleep(for: .seconds(3.5))
            if toast == next { toast = nil }
        }
    }

    private func toggleStrip() {
        stripOpen.toggle()
        if !stripOpen { selected = nil }
    }

    /// Pick a card: point to its box for a few seconds, and offer Remove.
    private func select(_ id: UUID) {
        guard selected != id else {
            selected = nil
            return
        }
        selected = id
        let inView = overlay.dots.contains { $0.id == id && $0.boxed }
        Task {
            try? await Task.sleep(for: .seconds(inView ? 1.6 : 4))
            if selected == id { selected = nil }
        }
    }
}

// MARK: - The ledger

/// What the person has boxed, and when each was boxed, held where the capture can
/// read it at stop. A class, because the capture reads it from outside the view.
@MainActor
private final class KeptLedger {
    private(set) var boxed: Set<UUID> = []
    private(set) var madeAt: [UUID: Int64] = [:]

    /// Notes the set as it is now; an object newly in it is stamped `now`, and one
    /// taken out (and put back by Undo) keeps its first stamp.
    func record(_ now: Set<UUID>, at time: Int64) {
        for id in now where madeAt[id] == nil { madeAt[id] = time }
        boxed = now
    }
}

// MARK: - The strip

/// The boxes as small stills in one row, newest first. Tapping one selects it
/// and shows Remove on it alone.
private struct BoxStrip: View {
    @ObservedObject var overlay: ProjectedOverlay
    @ObservedObject var thumbs: BoxThumbs
    let ids: [UUID]
    let selected: UUID?
    let select: (UUID) -> Void
    let remove: (UUID) -> Void

    var body: some View {
        let inView = Set(overlay.dots.filter(\.boxed).map(\.id))
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 10) {
                ForEach(ids, id: \.self) { id in
                    card(id, inView: inView.contains(id))
                }
            }
            .padding(10)
        }
        .background(RoundedRectangle(cornerRadius: 22).fill(Color.rsDusk.opacity(0.5)))
    }

    private func card(_ id: UUID, inView: Bool) -> some View {
        let chosen = selected == id
        return Group {
            if let image = thumbs.images[id] {
                Image(uiImage: image).resizable().scaledToFill()
            } else {
                Color.rsOnDusk.opacity(0.18)
            }
        }
        .frame(width: 72, height: 72)
        .clipShape(RoundedRectangle(cornerRadius: 14))
        .opacity(inView || chosen ? 1 : 0.55)
        .overlay(RoundedRectangle(cornerRadius: 14).stroke(BoxInk.white.opacity(chosen ? 0.95 : 0), lineWidth: 2))
        .overlay(alignment: .topTrailing) {
            if chosen {
                Button { remove(id) } label: {
                    Image(systemName: "xmark")
                        .font(.system(size: 11, weight: .bold))
                        .foregroundStyle(Color.rsDusk)
                        .frame(width: 24, height: 24)
                        .background(Circle().fill(BoxInk.white))
                        .shadow(color: Color.rsDusk.opacity(0.3), radius: 2)
                        .frame(width: 44, height: 44)
                        .contentShape(Rectangle())
                }
                .accessibilityLabel("Remove box")
                .offset(x: 10, y: -10)
            }
        }
        .contentShape(Rectangle())
        .onTapGesture { select(id) }
        .accessibilityLabel("Box")
        .accessibilityAddTraits(.isButton)
    }
}

/// A brief check over a box as it settles.
private struct CheckLayer: View {
    @ObservedObject var overlay: ProjectedOverlay
    let id: UUID?

    var body: some View {
        ZStack {
            if let id, let dot = overlay.dots.first(where: { $0.id == id }) {
                Image(systemName: "checkmark.circle.fill")
                    .font(.system(size: 44))
                    .foregroundStyle(BoxInk.white)
                    .shadow(color: Color.rsDusk.opacity(0.35), radius: 4)
                    .position(dot.point)
                    .transition(.scale(scale: 0.6).combined(with: .opacity))
            }
        }
        .allowsHitTesting(false)
        .animation(.easeOut(duration: 0.2), value: id)
    }
}

#endif
