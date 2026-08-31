/// Notes — needs-you first, news below.
///
/// Everything home used to report lives here. A note is a room that has
/// finished and failed: nothing further happens to it on its own, and the only
/// thing left is for the user to know, and sometimes to decide.
///
/// TWO SECTIONS, AND THE ORDER IS THE POINT. Needs-you carries the only
/// actions; news carries the only good thing that happens. When both are
/// present the needs-you items come first, because an arrival is pleasant and a
/// failure is unresolved, and a screen that leads with the pleasant one is
/// burying the thing it exists to surface.
///
/// "GOT IT" IS PERMANENT. Acknowledging a note removes it for good — not for
/// this launch. The old banner returned on every launch until the flight was
/// finished with, which was a deliberate hedge against someone dismissing a
/// failure without reading it. That hedge is spent: a note is not a banner
/// interrupting a screen the user came to for something else, it is a screen
/// they navigated to on purpose, having been told by home's sentence that
/// something needed them. Someone who arrives here and taps "Got it" has read
/// it. The haptic fires once, when the failure happens — never again on arrival.
///
/// WHAT IS NOT BUILT YET. The design gives news a past — an "EARLIER" list of
/// observed facts ("the July 12 room reached your desk", "you sent two rooms in
/// one day"). That needs the phone to remember what it previously saw and diff
/// successive fetches, which nothing in the app does today. It is deferred
/// deliberately, and the section simply does not render rather than showing an
/// empty shell. See the operator ruling recorded in the session notes.
///
/// Read by: RootFlowView, from home's sentence and the contents sheet.

import SwiftUI

// MARK: - What a note says

/// The copy for each kind of note, as pure functions.
///
/// Separated from the view for the reason `FailureCopy` already is: these are
/// the sentences that tell someone their room did not arrive, the count and the
/// plural have to be right, and a table test catches what an eye does not.
///
/// Pinned by: NotesCopyTests.
nonisolated enum NoteCopy {

    static func title(_ kind: NoteKind) -> String {
        switch kind {
        case .uploadFailed:      return "One room didn't make it up"
        case .processingFailed:  return "One room didn't survive the trip"
        case .sendFailedTerminal: return "I couldn't send one room up"
        case .incompleteUpload:  return "One room didn't all make it up"
        }
    }

    static func body(_ kind: NoteKind) -> String {
        switch kind {
        case .uploadFailed:
            return "A scan stalled on its way to the desk. It's still here on your phone, safe."
        case .processingFailed:
            return "There's nothing there I could honestly show you — and it's not something you did."
        case .sendFailedTerminal:
            return "Something on my end refused it. That's my fault, not yours, and trying again won't move it."
        case .incompleteUpload(let missingCount):
            return countClause(missingCount) + " I still have the room here on your phone."
        }
    }

    /// The one note whose action opens a screen rather than acknowledging.
    static func actionLabel(_ kind: NoteKind) -> String {
        kind.isAcknowledgeOnly ? "Got it" : "See what's missing"
    }

    /// Shared so the singular and the zero-degrade cannot differ between
    /// callers. The server can omit the paths entirely, and "0 files didn't
    /// arrive" is both false and absurd.
    private static func countClause(_ missingCount: Int) -> String {
        switch missingCount {
        case ..<1:  return "Some of it didn't finish the trip to the desk."
        case 1:     return "One file didn't finish the trip to the desk."
        default:    return "\(missingCount) files didn't finish the trip to the desk."
        }
    }
}

// MARK: - The screen

struct NotesView: View {
    /// Terminal failures waiting to be acknowledged, newest first.
    var needsYou: [NoteKind] = []
    /// A room that has arrived and not been stepped into. The one piece of good
    /// news the phone can honestly report.
    var arrival: String?
    /// Whether the arrival can actually be opened — false with no web origin
    /// configured, in which case the card informs rather than offering a tap
    /// that lands nowhere.
    var canOpenArrival: Bool = false
    var onAcknowledge: (NoteKind) -> Void = { _ in }
    var onOpenNote: (NoteKind) -> Void = { _ in }
    var onOpenArrival: () -> Void = {}
    var onClose: () -> Void = {}

    private var isEmpty: Bool { needsYou.isEmpty && arrival == nil }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            ScreenHeader(title: "Notes", onClose: onClose)

            if isEmpty {
                quiet
            } else {
                if !needsYou.isEmpty {
                    Eyebrow("Needs you")
                        .rsBelowHeader()
                    VStack(spacing: 12) {
                        ForEach(Array(needsYou.enumerated()), id: \.offset) { _, kind in
                            NoteCard(kind: kind,
                                     onAct: { kind.isAcknowledgeOnly
                                         ? onAcknowledge(kind) : onOpenNote(kind) })
                        }
                    }
                    .padding(.top, 12)
                }

                if let arrival {
                    Eyebrow("News")
                        .padding(.top, needsYou.isEmpty ? 26 : 30)
                    ArrivalCard(text: arrival,
                                canOpen: canOpenArrival,
                                onOpen: onOpenArrival)
                        .padding(.top, 12)
                }
            }

            Spacer(minLength: 20)
        }
        .rsScreenInsets()
        .frame(maxWidth: .infinity, alignment: .topLeading)
        .modifier(RSScrollableScreen(background: nil))
    }

    /// Says only that there is nothing, and promises where the something will
    /// appear. No illustration and no reassurance — an empty Notes screen is
    /// the ordinary case, not a state that needs softening.
    private var quiet: some View {
        Text("Nothing new — I'll say so here when there is.")
            .rsFont(.guest, size: 16)
            .foregroundStyle(Color.rsInkMuted)
            .fixedSize(horizontal: false, vertical: true)
            .rsBelowHeader()
    }
}

// MARK: - Cards

/// A needs-you note. Dark ink, because this is the one thing on the screen that
/// is unresolved — the same surface the failure banner used.
private struct NoteCard: View {
    let kind: NoteKind
    var onAct: () -> Void = {}

    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            // Top-aligned: at accessibility sizes the title wraps and a centred
            // glyph comes to rest in the middle of it, reading as punctuation.
            HStack(alignment: .top, spacing: 9) {
                Image(systemName: "exclamationmark.triangle")
                    .font(.system(size: 14, weight: .medium))
                    .foregroundStyle(Color.rsGoldLight)
                    .frame(height: 20, alignment: .center)
                Text(NoteCopy.title(kind))
                    .font(RSFont.ui(.subheadline, weight: .semibold))
                    .foregroundStyle(Color.rsOnDark)
                    .fixedSize(horizontal: false, vertical: true)
                    .multilineTextAlignment(.leading)
            }

            GuestLine(NoteCopy.body(kind), size: 13.5, onDark: true)
                .fixedSize(horizontal: false, vertical: true)

            if case .uploadFailed(let reason) = kind, let reason {
                Text(reason)
                    .rsFont(.mono, size: 10, maxSize: 13, cap: .mono)
                    .foregroundStyle(Color.rsOnDark.opacity(0.5))
                    .textSelection(.enabled)
                    .padding(.top, 2)
            }

            Button(action: onAct) {
                Text(NoteCopy.actionLabel(kind))
                    .font(RSFont.ui(.footnote, weight: .semibold))
                    .foregroundStyle(Color.rsInk)
                    .padding(.horizontal, 14).padding(.vertical, 7)
                    .background(Capsule().fill(Color.rsSurface))
            }
            .padding(.top, 5)
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.rsInk, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
    }
}

/// The arrival. Gold, because gold means light — this is the one card in the
/// app that reports a room having arrived somewhere other than the doorway.
private struct ArrivalCard: View {
    let text: String
    var canOpen: Bool = false
    var onOpen: () -> Void = {}

    var body: some View {
        VStack(alignment: .leading, spacing: 9) {
            GuestLine(text, size: 15.5)
                .fixedSize(horizontal: false, vertical: true)

            if canOpen {
                Button(action: onOpen) {
                    HStack(spacing: 7) {
                        Text("Step into it")
                        Image(systemName: "arrow.right")
                            .font(.system(size: 12, weight: .semibold))
                    }
                    .font(RSFont.ui(.footnote, weight: .semibold))
                    .foregroundStyle(Color(rsHex: 0x2a2114))
                    .padding(.horizontal, 14).padding(.vertical, 7)
                    .background(Capsule().fill(Color.rsGold))
                }
                Text("Opens your desk in the browser")
                    .font(RSFont.ui(.footnote))
                    .foregroundStyle(Color.rsInkFaint)
            } else {
                // No web origin configured: the card still reports the arrival,
                // because it happened — it just does not offer a tap that lands
                // nowhere.
                Text("It's waiting on your computer whenever you are.")
                    .font(RSFont.ui(.footnote))
                    .foregroundStyle(Color.rsInkFaint)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(15)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.rsGold.opacity(0.14), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous)
            .stroke(Color.rsGold.opacity(0.45), lineWidth: 1))
    }
}

// MARK: - Previews

#Preview("A full day") {
    NotesView(needsYou: [.uploadFailed(reason: "blob_unreadable_at_remint_manifest"),
                         .incompleteUpload(missingCount: 3)],
              arrival: "Yesterday's room is on your desk.",
              canOpenArrival: true)
}

#Preview("News only") {
    NotesView(arrival: "This morning's room is on your desk.")
}

#Preview("Quiet") {
    NotesView()
}
