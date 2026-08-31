/// DEBUG-only screen gallery: renders exactly one screen, in isolation, from
/// fixtures — so every surface in the app can be photographed in every state it
/// can reach, without staging the state that would normally produce it.
///
/// WHY THIS EXISTS: most of the app's screens cannot be reached on demand. The
/// home notices need a terminally failed upload record, a bundle mid-flight and
/// a failed rooms fetch — three independent conditions, one of which requires a
/// real capture to have failed. The desk's rate limit needs the server to
/// refuse a mint. The doorway needs a room to have finished rebuilding. Every
/// one of them is a design surface someone has to be able to LOOK at, and the
/// iOS test policy is explicit that a green suite says nothing about rendering:
/// layout claims at accessibility sizes have to be verified by screenshot, and
/// three review passes previously claimed coverage they did not have.
///
/// So this is the screenshot half of that policy, made repeatable.
///
/// ONE ENTRY IS ONE STATE, NOT ONE SCREEN. A screen photographed in one of the
/// several states it can reach has been photographed in none of the others, and
/// the ones nobody looks at are exactly where the defects are: a two-line
/// closing sentence, a wrapped title or a singular/plural swap moves everything
/// under it. So the catalogue enumerates the state space — every case of every
/// enum a screen switches on, and every combination of the values those cases
/// carry that changes what is drawn. Where an associated value does NOT change
/// the drawing, that is recorded in the note rather than given an entry.
///
/// IT COMPOSES, IT DOES NOT IMITATE. Each screen is built the way `RootFlowView`
/// builds it — the home variants are built from a `HomeDay` and compose their
/// own sentence through the real resolver, the desk renders `DeskCopy`'s own
/// table, the recovery screen reads `FailureCopy`'s. A photograph taken here is
/// a photograph of the shipping layout. If a state can only be reached by
/// hand-assembling a lookalike, the state is not reachable, and that is a
/// finding rather than an entry.
///
/// EVERY FIXTURE IS PINNED TO A FIXED CLOCK. `GalleryClock.now` is a constant,
/// and every date a screen renders is derived from it — so "4 MIN SO FAR",
/// "RESETS 29 Aug, 04:20" and the house's stamps are the same pixels on every
/// run. Wired to `Date()` these shots drifted: the rate-limit line reads "later
/// today" or "tomorrow" depending on what time the capture pass happened to run.
///
/// HOW TO DRIVE IT, following `StagingHooks`' launch-argument convention:
///
///     xcrun simctl launch <udid> com.thegoodguest.TheGoodGuest \
///         -rs.gallery.screen home-needsyou
///
/// Pair it with `xcrun simctl ui <udid> content_size accessibility-extra-extra-extra-large`
/// to photograph the accessibility sizes, which is where this app's layout
/// defects have actually lived (decisions 0224, 0238 and 0266).
///
/// `ScreenGallery.screens` is the catalogue and the ONE list — the capture
/// script enumerates it rather than carrying its own copy, so a screen added
/// here is photographed without touching anything else.
///
/// Compiled out of release builds entirely. Nothing here runs in the live app:
/// the app entry point consults `requestedScreen` and falls through to
/// `RootFlowView` whenever the argument is absent.

#if DEBUG

import AVFoundation
import SwiftUI

// MARK: - Catalogue

enum ScreenGallery {

    /// The launch argument / UserDefaults key, matching StagingHooks' `-rs.*` shape.
    static let defaultsKey = "rs.gallery.screen"

    /// The screen this launch was asked for, or nil for the ordinary app.
    static var requestedScreen: String? {
        guard let raw = UserDefaults.standard.string(forKey: defaultsKey) else { return nil }
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed
    }

    /// One photographable state.
    struct Entry {
        let id: String
        /// Which screen this is a state OF. The contact sheet groups on it, so
        /// two states of one screen are read side by side rather than found by
        /// scrolling — and it is stated rather than parsed out of the id, which
        /// would make `fail-incomplete` and `fail-rescan` a group called "fail"
        /// only by luck of naming.
        let group: String
        let title: String
        /// What state this is, and what makes it different from its neighbours.
        let note: String
        /// When to photograph it, in seconds after launch.
        ///
        /// A NUMBER RATHER THAN A FLAG, because several screens play a timeline
        /// and the interesting frame is at a particular moment in it, not
        /// "after it settles": the splash has two beats worth having, and home's
        /// menu peek is out between about 2.0 s and 3.5 s and gone by 5.2 s.
        var delay: Double = 2
        /// Render with Reduce Motion on. The environment value is what the
        /// screens actually read, so setting it is the real input rather than a
        /// second code path — see `ScreenGalleryView`.
        var reduceMotion = false
    }

    static let screens: [Entry] = [

        // Home. HomeDay is needsYou x hasUnseenArrival x hasRoomInFlight x
        // roomCount x isFirstRun, and `HomeLineResolver` collapses it to four
        // tones in a fixed priority order. What is enumerated here is every
        // sentence the resolver can produce — including the three the count
        // decides, which is where the singular and the never-a-zero rule live.
        //
        // Photographed at 6 s: the menu peek is out from about 2 s and gone by
        // 5.2 s, so a shorter wait photographs a transient. The peek has its
        // own entries below.
        .init(id: "home-first", group: "Home", title: "First run",
              note: "No sentence at all — there is nothing yet to report, and the space goes to the support line teaching how to walk a room.",
              delay: 6),
        .init(id: "home-quiet", group: "Home", title: "Ordinary day, many rooms",
              note: "A standing fact, pointing at the house. Muted ink, no accent.",
              delay: 6),
        .init(id: "home-one-room", group: "Home", title: "Ordinary day, one room",
              note: "The singular: \"one room\", spelled, not \"1 rooms\". The count branch an eye skips and a screenshot does not.",
              delay: 6),
        .init(id: "home-none-sent", group: "Home", title: "Ordinary day, nothing sent",
              note: "A known zero, said plainly. This is the one place a zero is honest, because the phone asked and got an answer.",
              delay: 6),
        .init(id: "home-trouble", group: "Home", title: "Rooms unreachable",
              note: "An unknown count. States no number and never a zero — the same refusal RoomsLoadState makes, carried into the sentence.",
              delay: 6),
        .init(id: "home-flight", group: "Home", title: "A room in flight",
              note: "Gold, quiet, pointing at the desk.",
              delay: 6),
        .init(id: "home-arrival", group: "Home", title: "Arrival",
              note: "Gold, pointing at the doorway. Outranks the flight below it.",
              delay: 6),
        .init(id: "home-needsyou", group: "Home", title: "Needs you, and a flight",
              note: "Rust. Mentions the flight in a subordinate clause while routing to Notes — one sentence, one destination.",
              delay: 6),
        .init(id: "home-needsyou-only", group: "Home", title: "Needs you, alone",
              note: "The same tone with nothing in flight, so the clause is gone. Four words, and the shortest line home can show.",
              delay: 6),

        // The menu peek: the once-per-launch hint that the mark is a way in. It
        // is a timeline, so it is photographed at a moment rather than at rest,
        // and its reduced-motion path is genuinely different — the row appears
        // whole instead of being uncovered.
        .init(id: "home-peek", group: "Menu peek", title: "The peek, out",
              note: "The dotted leader and MENU, uncovered from behind the mark. Plays once per launch, about 2.0 to 3.5 s in.",
              delay: 2.4),
        .init(id: "home-peek-reduced", group: "Menu peek", title: "The peek, reduce motion",
              note: "Same information, no movement: the row is simply present for as long as it would have been readable. The mask animation is skipped entirely.",
              delay: 2.4, reduceMotion: true),
        .init(id: "home-peek-after", group: "Menu peek", title: "After it retracts",
              note: "What home looks like from 5.2 s onward, and for the rest of the launch. The mark is left exactly as the brand draws it.",
              delay: 6),

        // The contents: four rows, always the same four. What varies is the
        // mono status column and its tone, which `Contents.rows` decides —
        // including the blank a count the phone cannot vouch for must produce.
        .init(id: "contents-quiet", group: "Contents", title: "Quiet day",
              note: "The whole map as a table of contents. Every column filled, nothing accented.",
              delay: 2),
        .init(id: "contents-eventful", group: "Contents", title: "Eventful day",
              note: "Rust on Notes, gold on the desk. \"2 NEED YOU\" is the plural verb agreement.",
              delay: 2),
        .init(id: "contents-nocount", group: "Contents", title: "The house declines its count",
              note: "The house row's column is BLANK and its leaders are gone with it — a dotted rule to an empty column points at nothing. \"1 NEEDS YOU\" is the singular.",
              delay: 2),
        .init(id: "contents-news", group: "Contents", title: "News, and one room",
              note: "Notes reads NEWS in gold rather than rust: an arrival is not a decision. \"1 ROOM\" is the house's singular.",
              delay: 2),
        .init(id: "contents-firstrun", group: "Contents", title: "Nothing sent yet",
              note: "\"NO ROOMS YET\" — a known zero, in words. Distinct from the blank above, which is a zero the phone cannot claim.",
              delay: 2),

        // The desk. DeskState is six cases, three of which carry values that
        // change what is drawn. Every combination that changes the drawing is
        // here. NOT here, deliberately: `checkFailed`'s `anchor`. The status
        // line for that case is fixed and the guest line reads only `stopped`,
        // so the anchor it carries is never rendered.
        .init(id: "desk-sending", group: "The desk", title: "Sending",
              note: "Gold status. Leaving is free, and the line says so rather than the button implying it.",
              delay: 2),
        .init(id: "desk-working", group: "The desk", title: "At the desk",
              note: "The ordinary rebuild. Elapsed only, coarse, counted from the server's clock — never an estimate.",
              delay: 2),
        .init(id: "desk-working-long", group: "The desk", title: "At the desk, taking a while",
              note: "Past the threshold the copy turns candid. Same status line, a different sentence — the one desk state where the guest volunteers that it is slow.",
              delay: 2),
        .init(id: "desk-working-noanchor", group: "The desk", title: "At the desk, no clock yet",
              note: "Before the first successful poll there is no server anchor, so the status states the place and stops. No elapsed figure is invented.",
              delay: 2),
        .init(id: "desk-working-noanchor-long", group: "The desk", title: "Taking a while, no clock yet",
              note: "Both at once: the candid line with nothing to count from. The two values are independent, and this is the corner they make.",
              delay: 2),
        .init(id: "desk-paused", group: "The desk", title: "Paused",
              note: "Finally has a surface — it used to be a state you could only see by being trapped in it. Nothing for the user to do, said plainly.",
              delay: 2),
        .init(id: "desk-limited-tomorrow", group: "The desk", title: "Today's limit, tomorrow",
              note: "The cap, with the reset on another day. Prose says roughly when; the mono stamp says exactly, in the device's own time zone.",
              delay: 2),
        .init(id: "desk-limited-today", group: "The desk", title: "Today's limit, later today",
              note: "Same state, same day. The branch that must never read \"tomorrow\" for a reset a few hours off.",
              delay: 2),
        .init(id: "desk-limited-hour", group: "The desk", title: "Today's limit, about an hour",
              note: "Under two hours. The line narrows as the reset approaches; the stamp beneath does not change form.",
              delay: 2),
        .init(id: "desk-limited-soon", group: "The desk", title: "Today's limit, under an hour",
              note: "The nearest branch. Still no countdown — the phone reports the instant it was given, not a clock it is running.",
              delay: 2),
        .init(id: "desk-limited-unknown", group: "The desk", title: "Today's limit, no time given",
              note: "The server did not say when. The line promises no time and the mono stamp is absent entirely, so the screen loses its one exact fact.",
              delay: 2),
        .init(id: "desk-retry", group: "The desk", title: "Didn't leave the phone",
              note: "The one desk state with an action, because retrying genuinely works. A bordered capsule, not a filled button — the desk has no primary.",
              delay: 2),
        .init(id: "desk-checkfailed", group: "The desk", title: "Can't check, still trying",
              note: "Uploaded, but the status check is not landing. No action: the loop is still trying, so there is nothing to tap.",
              delay: 2),
        .init(id: "desk-checkfailed-stopped", group: "The desk", title: "Can't check, gave up",
              note: "The same state once the loop stops. All a Bool changes here: a sentence, and a \"Look again\" that appears.",
              delay: 2),
        .init(id: "desk-clear", group: "The desk", title: "Clear",
              note: "The ordinary state, and it has to be the screen's best one — most days nothing is in flight.",
              delay: 2),

        // Notes: four NoteKinds, each its own card, plus the three countClause
        // branches the incomplete note can take and the two the arrival card can.
        .init(id: "notes-upload-failed", group: "Notes", title: "Upload failed, with a reason",
              note: "The persisted reason, in mono and selectable — the only diagnostic the user has. \"Got it\" is permanent.",
              delay: 2),
        .init(id: "notes-upload-failed-bare", group: "Notes", title: "Upload failed, no reason",
              note: "The same note when nothing was persisted. The mono line is absent rather than blank or \"unknown\".",
              delay: 2),
        .init(id: "notes-processing-failed", group: "Notes", title: "Processing failed",
              note: "The pipeline finished hard-failed. Owns it — \"not something you did\" — and names no cause, because none is honestly available.",
              delay: 2),
        .init(id: "notes-send-failed", group: "Notes", title: "Send refused",
              note: "Refused in a way retrying cannot fix, so the card says trying again won't move it rather than offering a button that would.",
              delay: 2),
        .init(id: "notes-incomplete-many", group: "Notes", title: "Incomplete, several files",
              note: "The one note whose action opens a screen rather than acknowledging. \"3 files\" is the plural.",
              delay: 2),
        .init(id: "notes-incomplete-one", group: "Notes", title: "Incomplete, one file",
              note: "The singular clause. Same card, same action, one word different.",
              delay: 2),
        .init(id: "notes-incomplete-none", group: "Notes", title: "Incomplete, no count",
              note: "The server can omit the paths. Degrades to \"Some of it\" — \"0 files didn't arrive\" is both false and absurd.",
              delay: 2),
        .init(id: "notes-full", group: "Notes", title: "Needs you, and news",
              note: "Both sections. Failures first: an arrival is pleasant and a failure is unresolved, and leading with the pleasant one buries the point.",
              delay: 2),
        .init(id: "notes-news-open", group: "Notes", title: "News, openable",
              note: "The arrival card with somewhere to go. The gold CTA is the light-semantic peak outside the doorway itself.",
              delay: 2),
        .init(id: "notes-news", group: "Notes", title: "News, nowhere to open",
              note: "No web origin configured. The card still reports the arrival, because it happened — it just offers no tap that lands nowhere.",
              delay: 2),
        .init(id: "notes-quiet", group: "Notes", title: "Quiet",
              note: "The ordinary case. No illustration and no reassurance — an empty Notes screen is not a state that needs softening.",
              delay: 2),

        // The house: RoomsLoadState's four states, plus the stale flag and
        // canOpenWeb. The rows carry all three room treatments in every loaded
        // shot.
        .init(id: "rooms-list", group: "The house", title: "Rooms, nowhere to open",
              note: "No web origin: every chevron is hidden and no row is tappable, rather than offering taps that land nowhere.",
              delay: 2),
        .init(id: "rooms-openable", group: "The house", title: "Rooms, openable",
              note: "With a web origin the two READY rooms gain a chevron and a tap. The processing and failed rows do not — there is nothing to open yet.",
              delay: 2),
        .init(id: "rooms-stale", group: "The house", title: "Rooms, possibly stale",
              note: "The refresh line above the list. Says \"might be\" — the phone does not know that it is.",
              delay: 2),
        .init(id: "rooms-empty", group: "The house", title: "Empty",
              note: "Genuinely none sent, and the phone asked. Distinct from being unable to ask.",
              delay: 2),
        .init(id: "rooms-loading", group: "The house", title: "Loading",
              note: "Nothing known yet. Idle renders identically — the two are one state to this screen.",
              delay: 2),
        .init(id: "rooms-unreachable", group: "The house", title: "Unreachable",
              note: "The phone could not ask. Declines to guess at a count rather than rendering an empty list, and offers a retry.",
              delay: 2),

        // The capture flow.
        .init(id: "guidance", group: "Before you start", title: "Camera not yet asked",
              note: "What the scan button opens. Permission is requested here, in context, on the gold CTA — never at launch.",
              delay: 2),
        .init(id: "guidance-denied", group: "Before you start", title: "Camera refused",
              note: "The CTA becomes Open Settings, with its glyph. Reached at first render now, rather than one tap later.",
              delay: 2),
        .init(id: "capture-start", group: "Capturing", title: "Nothing measured yet",
              note: "The first seconds: tracking fine, all three coverage ticks empty, no plan drawn. Nothing is claimed about a room not yet seen.",
              delay: 2),
        .init(id: "capture", group: "Capturing", title: "Tracking is fine",
              note: "The room drawing itself in ink. The readout is MUTED here, in the same ink as the coverage labels: the ordinary state is the quiet one.",
              delay: 2),
        .init(id: "capture-slow", group: "Capturing", title: "Going too fast",
              note: "The readout takes colour and the mesh pauses — the sketch stops rather than drawing something the tracker does not trust.",
              delay: 2),
        .init(id: "capture-finding", group: "Capturing", title: "Finding the room",
              note: "Initializing or relocalizing. Shares its colour with \"too fast\" and is told apart by the words, which is why the dot that used to carry it is gone.",
              delay: 2),
        .init(id: "capture-dark", group: "Capturing", title: "Too dark to see",
              note: "The readout in the lost colour, the mesh dimmed, and an override line that outranks anything the guest would otherwise say.",
              delay: 2),
        .init(id: "gotroom", group: "I've got the room", title: "The single joyful beat",
              note: "Holds 1.8 s, then review. The one moment in the capture flow with nothing to decide.",
              delay: 2.6),
        .init(id: "review", group: "Review", title: "A clean capture",
              note: "The built room's own floor plan, the census and the metrics. Send leads; the rescan sits above it so the filled button lands at one height on every screen.",
              delay: 2),
        .init(id: "review-sketch", group: "Review", title: "No plan, no census",
              note: "A capture whose room did not ship. Falls back to the generic sketch and shows no census — that line describes what the server will see, so it must not appear.",
              delay: 2),
        .init(id: "review-preparing", group: "Review", title: "Still packing",
              note: "Transient, so the send stays in the primary slot, disabled and dimmed, rather than swapping the destructive rescan under the user's finger when the bundle lands.",
              delay: 2),
        .init(id: "review-cannot-send", group: "Review", title: "Nothing to send",
              note: "The rescan is promoted to primary and the send is withheld — better than letting the backend refuse it and reporting that as a broken upload.",
              delay: 2),
        .init(id: "review-thin", group: "Review", title: "Thin coverage (dormant)",
              note: "BUILT AND UNREACHABLE: thinCoverage is never set true. Photographed so the designed treatment can be judged, not as something the screen can say today.",
              delay: 2),

        // Arrival: canOpenWeb x signedIntoWeb is four screens, and the pair
        // changes both the control and the caption under it.
        .init(id: "doorway", group: "The doorway", title: "Openable, signed in",
              note: "The peak. Gold CTA, and the caption adds that you are already signed in over there.",
              delay: 2.8),
        .init(id: "doorway-unsigned", group: "The doorway", title: "Openable, not signed in",
              note: "Same CTA, shorter caption. The claim about being signed in is dropped rather than softened — an anonymous UID does not carry across devices.",
              delay: 2.8),
        .init(id: "doorway-noweb-signed", group: "The doorway", title: "No web origin, signed in",
              note: "The CTA is gone entirely rather than shown as a control that does nothing. The caption points at the computer instead.",
              delay: 2.8),
        .init(id: "doorway-noweb", group: "The doorway", title: "No web origin, not signed in",
              note: "The one corner with nothing to promise: it points at signing in, because for an unlinked user there is no computer where this room exists.",
              delay: 2.8),

        // Recovery: FailureCopy.Resend is four states, and each changes both
        // buttons AND the body copy. The count clause is the second axis.
        .init(id: "fail-incomplete", group: "What's missing", title: "Re-send available",
              note: "The files are on this phone, so the screen promises a re-send. The only state that promises anything.",
              delay: 2),
        .init(id: "fail-one", group: "What's missing", title: "Re-send available, one file",
              note: "The singular count clause. Same promise, one word.",
              delay: 2),
        .init(id: "fail-inflight", group: "What's missing", title: "Sending",
              note: "The primary reads \"Sending...\", disabled and dimmed at the call site — a bare .disabled() on the shared style is invisible, which is a defect a screenshot caught and reading did not.",
              delay: 2),
        .init(id: "fail-failed", group: "What's missing", title: "The re-send failed",
              note: "The offer stands, because the files are still here — and the rescan moves UP into the secondary slot, replacing \"Not now\", as the real alternative.",
              delay: 2),
        .init(id: "fail-rescan", group: "What's missing", title: "Rescan only",
              note: "The bytes are gone. The count is stated as a fact and the only path is a full pass — naming a count must not imply files that can be sent.",
              delay: 2),
        .init(id: "fail-none", group: "What's missing", title: "Rescan only, no count",
              note: "The server named nothing usable, so the count degrades out of the sentence entirely.",
              delay: 2),

        // Identity.
        .init(id: "profile", group: "You", title: "A guest",
              note: "The device ID as proof of continuity, wrapped rather than truncated. The pinned action invites sign-in.",
              delay: 2),
        .init(id: "profile-linked", group: "You", title: "Signed in",
              note: "The action slot is EMPTY and the closing line stands alone — the screen loses its filled button entirely, which is the state the pinned-action rule is least often tested against.",
              delay: 2),
        .init(id: "profile-noid", group: "You", title: "No ID yet",
              note: "Offline first launch. The card says so rather than showing a placeholder that would be copyable as an identity, and the copy button is gone with it.",
              delay: 2),
        // Deletion. Seven states, and the reason each is here rather than one
        // "delete screen" entry is 0270: the state space is where the defects
        // are. Three of these are wordings that read correctly in isolation and
        // wrongly beside each other — see DeleteAccountCopy's honesty rules.
        .init(id: "delete-confirm", group: "Delete everything", title: "The ask",
              note: "The only state that confirms again before sending. Says plainly that there is no copy and no undo.",
              delay: 2),
        .init(id: "delete-working", group: "Delete everything", title: "Running",
              note: "The one state with NO primary and no way out — the request is on the wire and a chevron would promise a cancellation that does not exist.",
              delay: 2),
        .init(id: "delete-done", group: "Delete everything", title: "Gone, with an inventory",
              note: "States what THIS pass removed, never what the account held. The distinction is invisible here and load-bearing in the next entry.",
              delay: 2),
        .init(id: "delete-done-empty", group: "Delete everything", title: "Gone, nothing left to take",
              note: "A resumed deletion: the first call did the work and this one found zero. Must not read as \"you had nothing\" — the sentence allows for an earlier attempt.",
              delay: 2),
        .init(id: "delete-done-notrevoked", group: "Delete everything", title: "Gone, but Apple was not told",
              note: "The Sign in with Apple token could not be revoked. TN3194 says delete anyway and tell the person to finish it in Settings, so this is the ONE done state that asks for something.",
              delay: 2),
        .init(id: "delete-partial", group: "Delete everything", title: "Stopped part-way",
              note: "Nothing the user owns has gone, so the words deleted/gone/removed cannot appear. The count it DID reach is deliberately not stated.",
              delay: 2),
        .init(id: "delete-failed", group: "Delete everything", title: "Failed",
              note: "Says nothing was left half-deleted, which the route guarantees. The frightening reading is the wrong one and is also the easy one to write.",
              delay: 2),
        .init(id: "delete-noid", group: "Delete everything", title: "No ID yet",
              note: "Offline first launch. The primary is disabled rather than hidden — a vanished button reads as an app that offers no deletion at all.",
              delay: 2),
        .init(id: "whysignin", group: "Why sign in", title: "Several rooms",
              note: "Auto-presented once. Its whole argument is a count, asserted twice — in the sentence and in the checklist.",
              delay: 2),
        .init(id: "whysignin-one", group: "Why sign in", title: "One room",
              note: "The sentence reads \"one room\" and the checklist reads \"Your 1 rooms\": the two count words are not written in one place.",
              delay: 2),

        // Outside the flow.
        .init(id: "unsupported", group: "No depth camera", title: "The root gate",
              note: "Honest, and offers nothing to do. Pro-only is a design decision, not a failure to support.",
              delay: 2),
        .init(id: "splash-name", group: "The splash", title: "The name",
              note: "Beat one: the name is on screen long enough to be read before anything moves.",
              delay: 1.6),
        .init(id: "splash-mark", group: "The splash", title: "The mark",
              note: "Beat two: the word has closed on its own \"oo\" and opened into the mark. One progress value drives both, so the letters cannot arrive where the rings are not.",
              delay: 3.7),
        .init(id: "splash-name-reduced", group: "The splash", title: "The name, reduce motion",
              note: "The name, shown. Until this pass it was not: one progress value drives the letters and the mark, and the reduced path set it to 1 up front, drawing the name already collapsed onto its own anchor.",
              delay: 1.6, reduceMotion: true),
        .init(id: "splash-mark-reduced", group: "The splash", title: "The mark, reduce motion",
              note: "The same two beats, separated by a fade rather than a morph — the gather IS the motion, so there is nothing left to cross-fade between. Same order, same total length.",
              delay: 3.4, reduceMotion: true),
        .init(id: "qr", group: "QR bridge", title: "Built, blocked on deep links",
              note: "The code encodes nothing and the caption says so. Kept photographable so the surface does not rot unseen.",
              delay: 2),
    ]
}

// MARK: - Fixtures

/// One clock for the whole gallery.
///
/// Every date any screen renders is derived from this, so a re-shoot produces
/// the same pixels. Wired to `Date()` these fixtures drifted in ways that read
/// as changes to the app: the desk's rate-limit line says "later today" or
/// "tomorrow" depending on the hour the capture pass ran, and the house's
/// stamps switch between a clock time and a date at midnight.
///
/// Built through `Calendar.current` rather than from an absolute instant,
/// because the copy branches that matter — same day versus not — are decided in
/// the device's own time zone, and a fixture pinned to UTC would land on a
/// different branch on a differently configured machine.
private enum GalleryClock {
    static let now: Date = {
        var c = DateComponents()
        c.year = 2026; c.month = 8; c.day = 28
        c.hour = 14; c.minute = 20
        return Calendar.current.date(from: c) ?? Date(timeIntervalSinceReferenceDate: 841_242_000)
    }()

    /// A server anchor far enough back that the elapsed clock reads as a real
    /// wait: 4 min 28 s, which `elapsedPhrase` renders as "4 min".
    static var anchor: Date { now.addingTimeInterval(-268) }

    static var resetsTomorrow: Date { now.addingTimeInterval(14 * 3600) }
    static var resetsToday: Date { now.addingTimeInterval(5 * 3600) }
    static var resetsInAnHour: Date { now.addingTimeInterval(5_400) }
    static var resetsSoon: Date { now.addingTimeInterval(1_500) }
}

/// Synthetic, and obviously so: no real capture, no real identity. The rooms
/// carry the three states the row treatment distinguishes.
private enum GalleryFixture {

    static var rooms: [RoomSummary] { RoomSummary.samples(now: GalleryClock.now) }

    static let uid = "gallery-fixture-not-a-real-uid"

    static let failureReason = "blob_unreadable_at_remint_manifest"

    static let verdict = "Here's your capture. Send it, and I'll start making sense of it on your desk."
}

// MARK: - Home, composed the way the flow composes it

/// Home, from a HomeDay. The screen composes its own sentence through the real
/// resolver, so a photograph here is a photograph of the shipping routing and
/// not of a hand-written string.
/// The deletion screen at one state.
///
/// `perform` never returns and `signOut` does nothing, so a photographed state
/// stays the state it was asked for — a gallery entry that could advance would
/// photograph whatever it reached rather than what it names.
private struct GalleryDelete: View {
    let state: DeleteAccountState
    var uid: String? = GalleryFixture.uid

    var body: some View {
        DeleteAccountView(
            uid: uid,
            perform: { _ in
                try? await Task.sleep(nanoseconds: .max)
                return .failure(.unavailable)
            },
            signOut: {},
            initialState: state
        )
    }
}

private struct GalleryHome: View {
    var day: HomeDay

    var body: some View { HomeView(day: day) }
}

/// The capture screen needs a live feed object, so it gets its own wrapper to
/// own one for the view's lifetime rather than rebuilding it every render.
private struct GalleryCapture: View {
    var tracking: TrackingQuality = .good
    var floor: SurfaceCoverage = .full
    var walls: SurfaceCoverage = .partial(0.62)
    var corners: SurfaceCoverage = .partial(0.5)
    /// False for the opening seconds, when nothing has been measured and the
    /// plan would otherwise appear fully drawn on the first frame.
    var drawn = true

    @StateObject private var feed = FloorPlanFeed()

    var body: some View {
        LiveCaptureView(
            state: CaptureHUDState(
                tracking: tracking,
                guestLine: "Move slowly and I'll sketch the room as you go.",
                floor: floor, walls: walls, corners: corners
            ),
            feed: feed
        )
        .onAppear {
            if drawn { feed.publish(snapshot: .previewRoom) }
            feed.publish(camera: .previewCamera)
        }
    }
}

// MARK: - The gallery itself

struct ScreenGalleryView: View {
    let screen: String

    /// REDUCE MOTION IS NOT SET HERE, and cannot be.
    ///
    /// `\.accessibilityReduceMotion` is read-only in `EnvironmentValues` — it
    /// has a getter and no setter — so an entry that wants it gets it from the
    /// device instead: the capture script writes
    /// `com.apple.Accessibility ReduceMotionEnabled` before launching. That is
    /// the same switch a person flips, which makes it the more faithful input
    /// of the two anyway; it just cannot be scoped to one view, so the script
    /// has to order the passes rather than interleave them.
    var body: some View {
        switch screen {

        // Home
        case "home-first":         GalleryHome(day: HomeDay(isFirstRun: true))
        case "home-quiet":         GalleryHome(day: HomeDay(roomCount: 6))
        case "home-one-room":      GalleryHome(day: HomeDay(roomCount: 1))
        case "home-none-sent":     GalleryHome(day: HomeDay(roomCount: 0))
        case "home-trouble":       GalleryHome(day: HomeDay(roomCount: nil))
        case "home-flight":        GalleryHome(day: HomeDay(hasRoomInFlight: true, roomCount: 6))
        case "home-arrival":       GalleryHome(day: HomeDay(hasUnseenArrival: true, roomCount: 6))
        case "home-needsyou":      GalleryHome(day: HomeDay(needsYou: 1, hasRoomInFlight: true,
                                                            roomCount: 6))
        case "home-needsyou-only": GalleryHome(day: HomeDay(needsYou: 1, roomCount: 6))

        // The peek is home; only the moment it is photographed at differs.
        case "home-peek", "home-peek-reduced", "home-peek-after":
            GalleryHome(day: HomeDay(roomCount: 6))

        // The contents
        case "contents-quiet":
            ContentsScreen(day: HomeDay(roomCount: 6))
        case "contents-eventful":
            ContentsScreen(day: HomeDay(needsYou: 2, hasRoomInFlight: true, roomCount: 9))
        case "contents-nocount":
            ContentsScreen(day: HomeDay(needsYou: 1, roomCount: nil))
        case "contents-news":
            ContentsScreen(day: HomeDay(hasUnseenArrival: true, roomCount: 1))
        case "contents-firstrun":
            ContentsScreen(day: HomeDay(roomCount: 0))

        // The desk
        case "desk-sending":
            desk(.sending)
        case "desk-working":
            desk(.working(anchor: GalleryClock.anchor, longRunning: false))
        case "desk-working-long":
            desk(.working(anchor: GalleryClock.anchor, longRunning: true))
        case "desk-working-noanchor":
            desk(.working(anchor: nil, longRunning: false))
        case "desk-working-noanchor-long":
            desk(.working(anchor: nil, longRunning: true))
        case "desk-paused":
            desk(.paused, title: "yesterday's room")
        case "desk-limited-tomorrow":
            desk(.rateLimited(resetsAt: GalleryClock.resetsTomorrow))
        case "desk-limited-today":
            desk(.rateLimited(resetsAt: GalleryClock.resetsToday))
        case "desk-limited-hour":
            desk(.rateLimited(resetsAt: GalleryClock.resetsInAnHour))
        case "desk-limited-soon":
            desk(.rateLimited(resetsAt: GalleryClock.resetsSoon))
        case "desk-limited-unknown":
            desk(.rateLimited(resetsAt: nil))
        case "desk-retry":
            desk(.retryableSendFailure)
        case "desk-checkfailed":
            desk(.checkFailed(anchor: GalleryClock.anchor, stopped: false))
        case "desk-checkfailed-stopped":
            desk(.checkFailed(anchor: GalleryClock.anchor, stopped: true))
        case "desk-clear":
            DeskView(state: nil, now: GalleryClock.now)

        // Notes
        case "notes-upload-failed":
            NotesView(needsYou: [.uploadFailed(reason: GalleryFixture.failureReason)])
        case "notes-upload-failed-bare":
            NotesView(needsYou: [.uploadFailed(reason: nil)])
        case "notes-processing-failed":
            NotesView(needsYou: [.processingFailed])
        case "notes-send-failed":
            NotesView(needsYou: [.sendFailedTerminal])
        case "notes-incomplete-many":
            NotesView(needsYou: [.incompleteUpload(missingCount: 3)])
        case "notes-incomplete-one":
            NotesView(needsYou: [.incompleteUpload(missingCount: 1)])
        case "notes-incomplete-none":
            NotesView(needsYou: [.incompleteUpload(missingCount: 0)])
        case "notes-full":
            NotesView(needsYou: [.uploadFailed(reason: GalleryFixture.failureReason),
                                 .incompleteUpload(missingCount: 3)],
                      arrival: "Yesterday's room is on your desk.",
                      canOpenArrival: true)
        case "notes-news-open":
            NotesView(arrival: "This morning's room is on your desk.", canOpenArrival: true)
        case "notes-news":
            NotesView(arrival: "This morning's room is on your desk.")
        case "notes-quiet":
            NotesView()

        // The house
        case "rooms-list":
            house(.loaded(rooms: GalleryFixture.rooms, stale: false))
        case "rooms-openable":
            house(.loaded(rooms: GalleryFixture.rooms, stale: false), canOpenWeb: true)
        case "rooms-stale":
            house(.loaded(rooms: GalleryFixture.rooms, stale: true))
        case "rooms-empty":
            house(.loaded(rooms: [], stale: false))
        case "rooms-loading":
            house(.loading)
        case "rooms-unreachable":
            house(.failed(reason: "offline"))

        // The capture flow
        case "guidance":
            GuidanceSheet(cameraStatus: { .notDetermined })
        case "guidance-denied":
            GuidanceSheet(cameraStatus: { .denied })
        case "capture-start":
            GalleryCapture(floor: .empty, walls: .empty, corners: .empty, drawn: false)
        case "capture":
            GalleryCapture()
        case "capture-slow":
            GalleryCapture(tracking: .slowDown)
        case "capture-finding":
            GalleryCapture(tracking: .finding)
        case "capture-dark":
            GalleryCapture(tracking: .tooDark)
        case "gotroom":
            GotTheRoomView()
        case "review":
            ReviewView(metrics: "126 frames · LiDAR + RoomPlan",
                       census: "9 objects · 13 walls · 2 doors",
                       floorPlan: .previewRoom,
                       verdict: GalleryFixture.verdict,
                       rescanLabel: "Scan again from scratch")
        case "review-sketch":
            ReviewView(metrics: "48 frames · LiDAR",
                       verdict: GalleryFixture.verdict,
                       rescanLabel: "Scan again from scratch")
        case "review-preparing":
            ReviewView(metrics: "126 frames · LiDAR + RoomPlan",
                       census: "9 objects · 13 walls · 2 doors",
                       floorPlan: .previewRoom,
                       verdict: "Packing it up — one moment.",
                       isPreparing: true,
                       rescanLabel: "Scan again from scratch")
        case "review-cannot-send":
            ReviewView(metrics: "3 frames · LiDAR",
                       verdict: "I didn't get enough to send. Let's walk it again — it only takes a couple of minutes.",
                       canSend: false,
                       rescanLabel: "Scan again from scratch")
        case "review-thin":
            ReviewView(metrics: "48 frames · LiDAR + RoomPlan",
                       census: "2 objects · 3 walls",
                       verdict: GalleryFixture.verdict,
                       thinCoverage: true,
                       rescanLabel: "Scan again from scratch")

        // Arrival
        case "doorway":
            DoorwayView(signedIntoWeb: true, canOpenWeb: true)
        case "doorway-unsigned":
            DoorwayView(signedIntoWeb: false, canOpenWeb: true)
        case "doorway-noweb-signed":
            DoorwayView(signedIntoWeb: true, canOpenWeb: false)
        case "doorway-noweb":
            DoorwayView(signedIntoWeb: false, canOpenWeb: false)

        // Recovery. onBack, because that is how the flow reaches it: without it
        // the gallery photographed a screen with no header, which is not the
        // one that ships.
        case "fail-incomplete":
            FailureView(kind: .recoverable(missingCount: 3, resend: .available), onBack: {})
        case "fail-one":
            FailureView(kind: .recoverable(missingCount: 1, resend: .available), onBack: {})
        case "fail-inflight":
            FailureView(kind: .recoverable(missingCount: 3, resend: .inFlight), onBack: {})
        case "fail-failed":
            FailureView(kind: .recoverable(missingCount: 3, resend: .failed), onBack: {})
        case "fail-rescan":
            FailureView(kind: .recoverable(missingCount: 14, resend: .unavailable), onBack: {})
        case "fail-none":
            FailureView(kind: .recoverable(missingCount: 0, resend: .unavailable), onBack: {})

        // Identity
        case "profile":
            ProfileView(uid: GalleryFixture.uid)
        case "profile-linked":
            ProfileView(uid: GalleryFixture.uid, isLinked: true)
        case "profile-noid":
            ProfileView(uid: nil)
        case "delete-confirm":
            GalleryDelete(state: .confirm)
        case "delete-working":
            GalleryDelete(state: .working)
        case "delete-done":
            GalleryDelete(state: .done(AccountDeletionCounts(
                rooms: 6, conversations: 3, conversationMessages: 41,
                designSpecs: 2, uploadSessions: 9, files: 214), .revoked))
        case "delete-done-empty":
            GalleryDelete(state: .done(AccountDeletionCounts(), .notLinked))
        case "delete-done-notrevoked":
            GalleryDelete(state: .done(AccountDeletionCounts(
                rooms: 6, conversations: 3, files: 214), .notRevoked))
        case "delete-partial":
            GalleryDelete(state: .partial(AccountDeletionCounts(files: 40)))
        case "delete-failed":
            GalleryDelete(state: .failed(.serverError(500)))
        case "delete-noid":
            GalleryDelete(state: .confirm, uid: nil)
        case "whysignin":
            WhySignInSheet(roomCount: 3)
        case "whysignin-one":
            WhySignInSheet(roomCount: 1)

        // Outside the flow
        case "unsupported":
            UnsupportedDeviceView()
        case "splash-name", "splash-mark",
             "splash-name-reduced", "splash-mark-reduced":
            SplashView()
        case "qr":
            QRBridgeView()

        default:
            unknown
        }
    }

    // MARK: Builders

    /// Every desk state on the one fixed clock, so the elapsed phrase and the
    /// reset stamp are the same pixels on every run.
    private func desk(_ state: DeskState, title: String = "today's room") -> some View {
        DeskView(state: state, roomTitle: title, now: GalleryClock.now)
    }

    /// Likewise the house: its stamps switch between a clock time and a date at
    /// midnight, which would make an overnight re-shoot look like a change.
    private func house(_ state: RoomsLoadState, canOpenWeb: Bool = false) -> some View {
        HouseView(state: state, canOpenWeb: canOpenWeb, now: GalleryClock.now)
    }

    /// An unrecognised id is stated plainly rather than silently photographed as
    /// a blank screen — a blank frame in a contact sheet reads as a real screen
    /// that renders nothing, which is a much more expensive misunderstanding.
    private var unknown: some View {
        VStack(spacing: 10) {
            Text("No screen with id")
                .font(RSFont.ui(.callout, weight: .semibold))
                .foregroundStyle(Color.rsInk)
            Text(screen)
                .rsFont(.mono, size: 13)
                .foregroundStyle(Color.rsAction)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .rsParchmentScreen()
    }
}

#Preview("Gallery · unknown id") {
    ScreenGalleryView(screen: "home-all")
}

#endif
