/// DEBUG-only screen gallery: renders exactly one screen, in isolation, from
/// fixtures — so every surface in the app can be photographed in every state it
/// can reach, without staging the state that would normally produce it.
///
/// WHY THIS EXISTS: most of the app's screens cannot be reached on demand. A
/// room held by today's limit needs the server to refuse a mint; the ready
/// moment needs a room to finish rebuilding; the missing-files state needs a
/// real capture to have lost files. Every one of them is a design surface
/// someone has to be able to LOOK at, and the iOS test policy is explicit that
/// a green suite says nothing about rendering.
///
/// ONE ENTRY IS ONE STATE, NOT ONE SCREEN (0270). The catalogue enumerates the
/// state space — every case of every table a screen draws from, and every
/// value that changes what is drawn.
///
/// IT COMPOSES, IT DOES NOT IMITATE. Each screen is built from the same pure
/// tables RootFlowView uses — home from `RoomCards`, a room from
/// `RoomStatusCopy`, review from `ReviewCopy` — so a photograph here is a
/// photograph of the shipping layout. Rebuilt for the 2026-11-10 redesign.
///
/// EVERY FIXTURE IS PINNED TO A FIXED CLOCK (`GalleryClock.now`), so elapsed
/// times, reset times and room names are the same pixels on every run. The
/// camera behind the scan screen is the example room's picture: the simulator
/// has no camera, and a dusk void would photograph a screen nobody sees.
///
/// HOW TO DRIVE IT:
///
///     xcrun simctl launch <udid> com.thegoodguest.TheGoodGuest \
///         -rs.gallery.screen home-rooms
///
/// `ScreenGallery.screens` is the catalogue and the ONE list — the capture
/// script enumerates it rather than carrying its own copy.
///
/// Compiled out of release builds entirely.

#if DEBUG

import AVFoundation
import SwiftUI
import UIKit

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

    /// `-rs.gallery.bold YES`: render as with Bold Text on. The simulator has
    /// no switch for it (`simctl ui` sets appearance, contrast and size), so
    /// the scene's traits say it, which is what the setting itself changes;
    /// every hosting controller reads `legibilityWeight` from them. Setting
    /// the SwiftUI environment value instead changed no pixel on the screens.
    static var boldText: Bool { UserDefaults.standard.bool(forKey: "rs.gallery.bold") }

    @MainActor static func applyBoldText() {
        guard boldText else { return }
        for case let scene as UIWindowScene in UIApplication.shared.connectedScenes {
            scene.traitOverrides.legibilityWeight = .bold
        }
    }

    /// One photographable state.
    struct Entry {
        let id: String
        /// Which screen this is a state OF; the contact sheet groups on it.
        let group: String
        let title: String
        /// What state this is, and what makes it different from its neighbours.
        let note: String
        /// When to photograph it, in seconds after launch.
        var delay: Double = 3
        /// Render with Reduce Motion on (set on the device by the script).
        var reduceMotion = false
    }

    static let screens: [Entry] = [

        // Launch.
        .init(id: "splash-name", group: "Launch", title: "The name",
              note: "The name, in ink, its rings in terracotta, on the ground.", delay: 1.6),
        .init(id: "splash-mark", group: "Launch", title: "The mark",
              note: "The word has closed on its own rings and left the mark.", delay: 3.7),
        .init(id: "splash-name-reduced", group: "Launch", title: "The name, reduce motion",
              note: "The same two beats, separated by a fade.", delay: 1.6, reduceMotion: true),
        .init(id: "splash-mark-reduced", group: "Launch", title: "The mark, reduce motion",
              note: "The second beat under Reduce Motion.", delay: 3.4, reduceMotion: true),

        // Home: RoomCards' states.
        .init(id: "home-first", group: "Home", title: "First run",
              note: "A known zero: the server said none and nothing is on its way. The example room, the line, the button."),
        .init(id: "home-rooms", group: "Home", title: "Your rooms",
              note: "Six rooms, newest first: each with its outline, its size and where it is. The count is the server's."),
        .init(id: "home-one-room", group: "Home", title: "One room",
              note: "No count line for a list you can see is one long."),
        .init(id: "home-loading", group: "Home", title: "Looking for your rooms",
              note: "The server has not answered: grey shapes, no number."),
        .init(id: "home-unreachable", group: "Home", title: "Couldn't ask",
              note: "Refuses to guess a count, and offers to try again."),
        .init(id: "home-stale", group: "Home", title: "Maybe out of date",
              note: "A refresh failed: the last list stays, and says it might be old."),
        .init(id: "home-sending", group: "Home", title: "A room sending",
              note: "The flight's card on top: the first of three steps, and the guest."),
        .init(id: "home-flight", group: "Home", title: "A room being rebuilt",
              note: "The second step, with the time since the server anchor."),
        .init(id: "home-arrival", group: "Home", title: "A room just arrived",
              note: "New, until it is opened."),
        .init(id: "home-needsyou", group: "Home", title: "Rooms that need you",
              note: "A room held by today's limit and a scan from an earlier launch that stalled: weight and a mark, not colour."),

        // A room on its way.
        .init(id: "room-sending", group: "A room on its way", title: "Sending",
              note: "Leaving is free, said once."),
        .init(id: "room-working", group: "A room on its way", title: "Being rebuilt",
              note: "Elapsed, counted from the server's clock — never an estimate."),
        .init(id: "room-working-long", group: "A room on its way", title: "Taking a while",
              note: "The candid line, past the threshold."),
        .init(id: "room-working-noclock", group: "A room on its way", title: "No clock yet",
              note: "Before the first poll there is no anchor: the step has no time under it."),
        .init(id: "room-working-noclock-long", group: "A room on its way", title: "Taking a while, no clock",
              note: "Both at once."),
        .init(id: "room-paused", group: "A room on its way", title: "Paused",
              note: "Nothing to do, said plainly."),
        .init(id: "room-retry", group: "A room on its way", title: "Didn't leave the phone",
              note: "Retrying genuinely works; letting it go frees the scan."),
        .init(id: "room-checkfailed", group: "A room on its way", title: "Can't check, still trying",
              note: "No action while the loop is still trying."),
        .init(id: "room-checkfailed-stopped", group: "A room on its way", title: "Can't check, stopped",
              note: "The loop stopped: Check again appears."),

        // Today's limit.
        .init(id: "room-limit-tomorrow", group: "Today's limit", title: "Tomorrow",
              note: "The reset on another day, at the server's time, in the reader's clock."),
        .init(id: "room-limit-today", group: "Today's limit", title: "Later today",
              note: "Must never read tomorrow for a reset a few hours off."),
        .init(id: "room-limit-hour", group: "Today's limit", title: "About an hour",
              note: "Under two hours."),
        .init(id: "room-limit-soon", group: "Today's limit", title: "Under an hour",
              note: "The nearest branch; still no countdown."),
        .init(id: "room-limit-unknown", group: "Today's limit", title: "No time given",
              note: "The server named none: no note, and the send is offered."),

        // A room that needs you.
        .init(id: "room-upload-failed", group: "Needs you", title: "Stalled, with a reason",
              note: "The diagnostic behind Details; the button that frees the scan says so."),
        .init(id: "room-upload-failed-bare", group: "Needs you", title: "Stalled, no reason",
              note: "No Details when nothing was persisted."),
        .init(id: "room-processing-failed", group: "Needs you", title: "Couldn't be rebuilt",
              note: "Owns it, names no cause."),
        .init(id: "room-send-refused", group: "Needs you", title: "Refused",
              note: "Retrying cannot fix it, so no retry is offered."),
        .init(id: "room-missing", group: "Needs you", title: "Missing files, re-send",
              note: "The files are on this phone: the one state that promises a re-send."),
        .init(id: "room-missing-one", group: "Needs you", title: "One file missing",
              note: "The singular."),
        .init(id: "room-missing-sending", group: "Needs you", title: "Sending what's missing",
              note: "The primary is busy and dimmed."),
        .init(id: "room-missing-failed", group: "Needs you", title: "The re-send failed",
              note: "The offer stands; the rescan is the alternative."),
        .init(id: "room-missing-rescan", group: "Needs you", title: "Rescan only",
              note: "The bytes are gone: a count, and a full pass."),
        .init(id: "room-missing-none", group: "Needs you", title: "Rescan only, no count",
              note: "The server named nothing usable."),
        .init(id: "room-listed-processing", group: "Needs you", title: "A listed room, rebuilding",
              note: "A room from the list that is not this phone's flight."),
        .init(id: "room-listed-failed", group: "Needs you", title: "A listed room, failed",
              note: "A failed room from the list."),

        // Ready.
        .init(id: "ready", group: "Your room is ready", title: "Signed in",
              note: "The room by lamplight (its outline until the server renders a still), Open the room, and the honest Safari line."),
        .init(id: "ready-guest", group: "Your room is ready", title: "A guest",
              note: "The web cannot show an anonymous phone's rooms, so it offers sign-in."),
        .init(id: "ready-still", group: "Your room is ready", title: "With its picture",
              note: "The server's still, at its own 4:3 — wider than the picture's slot on every phone, so it must crop and never widen the screen."),

        // Account.
        .init(id: "account-guest", group: "Account", title: "A guest",
              note: "Sign in with Apple or Google; this iPhone's ID; privacy; delete."),
        .init(id: "account-linked", group: "Account", title: "Signed in",
              note: "The linked state is reachable now, with the other provider offered."),
        .init(id: "account-noid", group: "Account", title: "No ID yet",
              note: "Offline first launch: says so, no copy button."),
        .init(id: "account-failed", group: "Account", title: "Sign-in didn't finish",
              note: "The failure line, in ink with a mark, not red."),
        .init(id: "account-conflict", group: "Account", title: "That account has a home",
              note: "The system alert, with keep as the safe default.", delay: 4),

        // Deletion.
        .init(id: "delete-confirm", group: "Delete everything", title: "The ask",
              note: "No copy and no undo, said plainly."),
        .init(id: "delete-working", group: "Delete everything", title: "Running",
              note: "No back button: a cancellation does not exist."),
        .init(id: "delete-done", group: "Delete everything", title: "Gone, with an inventory",
              note: "What this pass removed."),
        .init(id: "delete-done-empty", group: "Delete everything", title: "Gone, nothing left",
              note: "Allows for an earlier attempt."),
        .init(id: "delete-done-notrevoked", group: "Delete everything", title: "Gone, Apple not told",
              note: "The one done state that asks for something."),
        .init(id: "delete-partial", group: "Delete everything", title: "Stopped part-way",
              note: "Nothing the person owns has gone."),
        .init(id: "delete-failed", group: "Delete everything", title: "Failed",
              note: "Nothing was left half-deleted."),
        .init(id: "delete-noid", group: "Delete everything", title: "No ID yet",
              note: "The primary is disabled, not hidden."),

        // Before you start.
        .init(id: "guidance", group: "Before you start", title: "LiDAR iPhone",
              note: "Five tips (boxing where boxes exist), the device line, privacy."),
        .init(id: "guidance-camera", group: "Before you start", title: "iPhone without LiDAR",
              note: "Every iPhone scans: this one measures with its camera, and says so."),
        .init(id: "guidance-denied", group: "Before you start", title: "Camera refused",
              note: "Open Settings, and why."),

        // Scanning. The camera is a stand-in (the simulator has none).
        .init(id: "capture-start", group: "Scanning", title: "Nothing measured yet",
              note: "Tracking, the empty plan card, no coverage."),
        .init(id: "capture", group: "Scanning", title: "Tracking",
              note: "The plan drawing itself in lamplight, coverage filling."),
        .init(id: "capture-slow", group: "Scanning", title: "Moving too fast",
              note: "The dot dims and the plan pauses."),
        .init(id: "capture-finding", group: "Scanning", title: "Finding the room",
              note: "Initializing or relocalizing."),
        .init(id: "capture-dark", group: "Scanning", title: "Too dark to see",
              note: "The override line outranks the guest."),
        .init(id: "capture-camera", group: "Scanning", title: "Without LiDAR",
              note: "No plan card and no coverage: RoomPlan needs LiDAR."),

        // Review.
        .init(id: "review", group: "Review", title: "I've got the room",
              note: "The plan in ink with its size in terracotta, the facts, Send it."),
        .init(id: "review-noplan", group: "Review", title: "No plan from this pass",
              note: "LiDAR, but RoomPlan shipped no room: no census, no plan."),
        .init(id: "review-packing", group: "Review", title: "Packing it up",
              note: "The send waits for the bundle, busy and dimmed."),
        .init(id: "review-nothing", group: "Review", title: "Nothing to send",
              note: "Scan again is the primary."),
        .init(id: "review-camera", group: "Review", title: "Without LiDAR",
              note: "Measured with the camera, said once."),
    ]
}

// MARK: - Fixtures

/// One clock for the whole gallery: 28 August 2026, 14:20, in the device's
/// own time zone, so the same-day branches land the same way on any machine.
private enum GalleryClock {
    static let now: Date = {
        var c = DateComponents()
        c.year = 2026; c.month = 8; c.day = 28
        c.hour = 14; c.minute = 20
        return Calendar.current.date(from: c) ?? Date(timeIntervalSinceReferenceDate: 841_242_000)
    }()
    static var anchor: Date { now.addingTimeInterval(-268) }
    static var longAnchor: Date { now.addingTimeInterval(-26 * 60) }
    static var resetsTomorrow: Date { now.addingTimeInterval(14 * 3600) }
    static var resetsToday: Date { now.addingTimeInterval(5 * 3600) }
    static var resetsInAnHour: Date { now.addingTimeInterval(5_400) }
    static var resetsSoon: Date { now.addingTimeInterval(1_500) }
    static func daysAgo(_ d: Int, hour: Int = 10) -> Date {
        let day = Calendar.current.date(byAdding: .day, value: -d, to: now) ?? now
        return Calendar.current.date(bySettingHour: hour, minute: 15, second: 0, of: day) ?? day
    }
}

/// Synthetic, and obviously so: no real capture, no real identity.
private enum GalleryFixture {
    static let uid = "k7QeR2xLm9TfA8vB3nWc9fA2"
    static let failureReason = "blob_unreadable_at_remint_manifest"

    /// Outlines, in metres, for the fixture rooms.
    static let outlines: [String: [[Double]]] = [
        "s1": [[0, 0], [4.4, 0], [4.4, 3.6], [1.2, 3.6], [1.2, 2.9], [0, 2.9]],
        "s2": [[0, 0], [3.85, 0], [3.85, 3.1], [2.5, 3.1], [2.5, 3.45], [1.3, 3.45], [1.3, 3.1], [0, 3.1]],
        "s3": [[0, 0], [5.2, 0], [5.2, 4.1], [0, 4.1]],
        "s4": [[0, 0], [2.3, 0], [2.3, -0.2], [3.3, -0.2], [3.3, 2.95], [0, 2.95]],
        "s5": [[0, 0], [4.05, 0], [4.05, 3.4], [0, 3.4]],
        "s6": [[0, 0], [3.6, 0], [3.6, 2.4], [2.9, 3.1], [0, 3.1]],
    ]

    static func room(_ id: String, _ sentAt: Date, _ status: SceneStatus) -> RoomSummary {
        RoomSummary(id: id, bundleId: "b-\(id)",
                    title: RoomHistory.title(sentAt: sentAt, now: GalleryClock.now, withTime: false),
                    status: status, sentAt: sentAt)
    }

    static var rooms: [RoomSummary] {
        [room("s1", GalleryClock.daysAgo(0, hour: 9), .ready),
         room("s2", GalleryClock.daysAgo(1), .ready),
         room("s3", GalleryClock.daysAgo(8), .ready),
         room("s4", GalleryClock.daysAgo(16), .failedIncomplete),
         room("s5", GalleryClock.daysAgo(25), .ready),
         room("s6", GalleryClock.daysAgo(38), .ready)]
    }

    @MainActor static func seedPictures() {
        for (id, polygon) in outlines {
            if let outline = RoomOutline.make(polygon: polygon) {
                RoomPictureStore.shared.seed(sceneId: id, outline: outline)
            }
        }
        // A room with its still, at the server's own shape (1600 x 1200, 4:3):
        // the example room's picture, cropped to it. The simulator has no
        // server; the shape is the point, being wider than the slot it fills.
        if let polygon = outlines["s1"], let outline = RoomOutline.make(polygon: polygon),
           let room = UIImage(named: "ExampleRoom") {
            let size = CGSize(width: 1600, height: 1200)
            let format = UIGraphicsImageRendererFormat()
            format.scale = 1
            let still = UIGraphicsImageRenderer(size: size, format: format).image { _ in
                let scale = max(size.width / room.size.width, size.height / room.size.height)
                let drawn = CGSize(width: room.size.width * scale, height: room.size.height * scale)
                room.draw(in: CGRect(origin: CGPoint(x: (size.width - drawn.width) / 2,
                                                     y: (size.height - drawn.height) / 2), size: drawn))
            }
            RoomPictureStore.shared.seed(sceneId: "s7", outline: outline, still: still, night: true)
        }
    }

    static func home(_ rooms: RoomsLoadState, flight: SurfacePlacement? = nil,
                     earlier: Bool = false) -> HomeContent {
        RoomCards.content(
            rooms: rooms,
            flight: flight.map { HomeFlight(bundleId: "b-flight", placement: $0, sentAt: GalleryClock.now.addingTimeInterval(-600)) },
            earlierFailure: earlier ? HomeEarlierFailure(bundleId: "b-old", reason: failureReason) : nil,
            now: GalleryClock.now)
    }
}

// MARK: - The gallery itself

struct ScreenGalleryView: View {
    let screen: String

    init(screen: String) {
        self.screen = screen
        // Before the first frame, so the photographed state is the seeded one.
        MainActor.assumeIsolated { GalleryFixture.seedPictures() }
    }

    var body: some View {
        content
            .onAppear { ScreenGallery.applyBoldText() }
    }

    @ViewBuilder
    private var content: some View {
        let now = GalleryClock.now
        let today = "The 28 August room"
        switch screen {

        // Launch
        case "splash-name", "splash-mark", "splash-name-reduced", "splash-mark-reduced":
            SplashView()

        // Home
        case "home-first":       home(GalleryFixture.home(.loaded(rooms: [], stale: false)))
        case "home-rooms":       home(GalleryFixture.home(.loaded(rooms: GalleryFixture.rooms, stale: false)))
        case "home-one-room":    home(GalleryFixture.home(.loaded(rooms: [GalleryFixture.rooms[0]], stale: false)))
        case "home-loading":     home(GalleryFixture.home(.loading))
        case "home-unreachable": home(GalleryFixture.home(.failed(reason: "offline")))
        case "home-stale":       home(GalleryFixture.home(.loaded(rooms: GalleryFixture.rooms, stale: true)))
        case "home-sending":
            home(GalleryFixture.home(.loaded(rooms: Array(GalleryFixture.rooms.dropFirst()), stale: false),
                                     flight: .desk(.sending)))
        case "home-flight":
            home(GalleryFixture.home(.loaded(rooms: Array(GalleryFixture.rooms.dropFirst()), stale: false),
                                     flight: .desk(.working(anchor: GalleryClock.anchor, longRunning: false))))
        case "home-arrival":
            home(GalleryFixture.home(.loaded(rooms: GalleryFixture.rooms, stale: false), flight: .doorway))
        case "home-needsyou":
            home(GalleryFixture.home(.loaded(rooms: Array(GalleryFixture.rooms.dropFirst()), stale: false),
                                     flight: .desk(.rateLimited(resetsAt: GalleryClock.resetsTomorrow)),
                                     earlier: true))

        // A room on its way
        case "room-sending":        room(today, RoomStatusCopy.onItsWay(.sending, now: now))
        case "room-working":        room(today, RoomStatusCopy.onItsWay(.working(anchor: GalleryClock.anchor, longRunning: false), now: now))
        case "room-working-long":   room(today, RoomStatusCopy.onItsWay(.working(anchor: GalleryClock.longAnchor, longRunning: true), now: now))
        case "room-working-noclock": room(today, RoomStatusCopy.onItsWay(.working(anchor: nil, longRunning: false), now: now))
        case "room-working-noclock-long": room(today, RoomStatusCopy.onItsWay(.working(anchor: nil, longRunning: true), now: now))
        case "room-paused":         room(today, RoomStatusCopy.onItsWay(.paused, now: now))
        case "room-retry":          room(today, RoomStatusCopy.onItsWay(.retryableSendFailure, now: now))
        case "room-checkfailed":    room(today, RoomStatusCopy.onItsWay(.checkFailed(anchor: GalleryClock.anchor, stopped: false), now: now))
        case "room-checkfailed-stopped": room(today, RoomStatusCopy.onItsWay(.checkFailed(anchor: GalleryClock.anchor, stopped: true), now: now))

        // Today's limit
        case "room-limit-tomorrow": room(today, RoomStatusCopy.onItsWay(.rateLimited(resetsAt: GalleryClock.resetsTomorrow), now: now))
        case "room-limit-today":    room(today, RoomStatusCopy.onItsWay(.rateLimited(resetsAt: GalleryClock.resetsToday), now: now))
        case "room-limit-hour":     room(today, RoomStatusCopy.onItsWay(.rateLimited(resetsAt: GalleryClock.resetsInAnHour), now: now))
        case "room-limit-soon":     room(today, RoomStatusCopy.onItsWay(.rateLimited(resetsAt: GalleryClock.resetsSoon), now: now))
        case "room-limit-unknown":  room(today, RoomStatusCopy.onItsWay(.rateLimited(resetsAt: nil), now: now))

        // Needs you
        case "room-upload-failed":      room(today, RoomStatusCopy.needsYou(.uploadFailed(reason: GalleryFixture.failureReason)))
        case "room-upload-failed-bare": room(today, RoomStatusCopy.needsYou(.uploadFailed(reason: nil)))
        case "room-processing-failed":  room(today, RoomStatusCopy.needsYou(.processingFailed))
        case "room-send-refused":       room(today, RoomStatusCopy.needsYou(.sendFailedTerminal))
        case "room-missing":         room(today, RoomStatusCopy.missing(missingCount: 3, resend: .available))
        case "room-missing-one":     room(today, RoomStatusCopy.missing(missingCount: 1, resend: .available))
        case "room-missing-sending": room(today, RoomStatusCopy.missing(missingCount: 3, resend: .inFlight))
        case "room-missing-failed":  room(today, RoomStatusCopy.missing(missingCount: 3, resend: .failed))
        case "room-missing-rescan":  room(today, RoomStatusCopy.missing(missingCount: 14, resend: .unavailable))
        case "room-missing-none":    room(today, RoomStatusCopy.missing(missingCount: 0, resend: .unavailable))
        case "room-listed-processing":
            room("The 27 August room", RoomStatusCopy.listed(.processing, sentAt: GalleryClock.anchor, now: now))
        case "room-listed-failed":
            room("The 12 August room", RoomStatusCopy.listed(.failed, sentAt: GalleryClock.daysAgo(16), now: now))

        // Ready
        case "ready":
            NavigationStack {
                ReadyScreen(roomTitle: today, sceneId: "s1", canOpenWeb: true,
                            shareURL: URL(string: "https://thegoodguest.web.app/room?bundle=b-s1"))
            }
        case "ready-guest":
            NavigationStack {
                ReadyScreen(roomTitle: today, sceneId: "s1", canOpenWeb: false)
            }
        case "ready-still":
            NavigationStack {
                ReadyScreen(roomTitle: today, sceneId: "s7", canOpenWeb: true,
                            shareURL: URL(string: "https://thegoodguest.web.app/room?bundle=b-s7"))
            }

        // Account
        case "account-guest":    AccountSheet(uidOverride: .some(GalleryFixture.uid), linkedOverride: false)
        case "account-linked":   AccountSheet(uidOverride: .some(GalleryFixture.uid), linkedOverride: true)
        case "account-noid":     AccountSheet(uidOverride: .some(nil), linkedOverride: false)
        case "account-failed":
            AccountSheet(uidOverride: .some(GalleryFixture.uid), linkedOverride: false,
                         initialFailure: "Sign-in didn’t finish. Nothing changed on this iPhone; try again.")
        case "account-conflict":
            AccountSheet(uidOverride: .some(GalleryFixture.uid), linkedOverride: false, showsConflict: true)

        // Deletion
        case "delete-confirm":   delete(.confirm)
        case "delete-working":   delete(.working)
        case "delete-done":
            delete(.done(AccountDeletionCounts(rooms: 6, conversations: 3, conversationMessages: 41,
                                               designSpecs: 2, uploadSessions: 9, files: 214), .revoked))
        case "delete-done-empty":      delete(.done(AccountDeletionCounts(), .notLinked))
        case "delete-done-notrevoked": delete(.done(AccountDeletionCounts(rooms: 6, conversations: 3, files: 214), .notRevoked))
        case "delete-partial":         delete(.partial(AccountDeletionCounts(files: 40)))
        case "delete-failed":          delete(.failed(.serverError(500)))
        case "delete-noid":            delete(.confirm, uid: nil)

        // Before you start
        case "guidance":        GuidanceSheet(cameraStatus: { .notDetermined }, hasLidar: true, showsBoxingTip: true)
        case "guidance-camera": GuidanceSheet(cameraStatus: { .notDetermined }, hasLidar: false, showsBoxingTip: true)
        case "guidance-denied": GuidanceSheet(cameraStatus: { .denied }, hasLidar: true, showsBoxingTip: true)

        // Scanning
        case "capture-start":
            GalleryCapture(floor: .empty, walls: .empty, corners: .empty, drawn: false)
        case "capture":         GalleryCapture()
        case "capture-slow":    GalleryCapture(tracking: .slowDown)
        case "capture-finding": GalleryCapture(tracking: .finding)
        case "capture-dark":    GalleryCapture(tracking: .tooDark)
        case "capture-camera":  GalleryCapture(showsPlan: false)

        // Review
        case "review":
            ReviewView(content: ReviewCopy.content(frames: 126, tier: .lidarRoomplan,
                                                   census: RoomCensus(objects: 9, walls: 13, doors: 2, windows: 1, openings: 0, floors: 1),
                                                   hasPlan: true, boxes: 2, isPreparing: false, assemblyFailure: nil),
                       floorPlan: .previewRoom)
        case "review-noplan":
            ReviewView(content: ReviewCopy.content(frames: 48, tier: .lidarArkit, census: nil, hasPlan: false,
                                                   boxes: 2, isPreparing: false, assemblyFailure: nil))
        case "review-packing":
            ReviewView(content: ReviewCopy.content(frames: 126, tier: .lidarRoomplan,
                                                   census: RoomCensus(objects: 9, walls: 13, doors: 2, windows: 1, openings: 0, floors: 1),
                                                   hasPlan: true, boxes: 2, isPreparing: true, assemblyFailure: nil),
                       floorPlan: .previewRoom)
        case "review-nothing":
            ReviewView(content: ReviewCopy.content(frames: 0, tier: .lidarRoomplan, census: nil, hasPlan: false,
                                                   boxes: nil, isPreparing: false, assemblyFailure: nil))
        case "review-camera":
            ReviewView(content: ReviewCopy.content(frames: 131, tier: .arkitOnly, census: nil, hasPlan: false,
                                                   boxes: 2, isPreparing: false, assemblyFailure: nil))

        default:
            unknown
        }
    }

    // MARK: Builders

    private func home(_ content: HomeContent) -> some View {
        NavigationStack { HomeScreen(content: content) }.tint(Color.rsInk)
    }

    private func room(_ title: String, _ status: RoomStatus) -> some View {
        NavigationStack {
            Color.rsGround
                .navigationTitle("Your rooms")
                .navigationDestination(isPresented: .constant(true)) {
                    RoomScreen(title: title, status: status)
                }
        }
        .tint(Color.rsInk)
    }

    private func delete(_ state: DeleteAccountState, uid: String? = GalleryFixture.uid) -> some View {
        NavigationStack {
            Color.rsGround
                .navigationTitle("Account")
                .navigationDestination(isPresented: .constant(true)) {
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
        .tint(Color.rsInk)
    }

    /// An unrecognised id is stated plainly rather than photographed as blank.
    private var unknown: some View {
        VStack(spacing: 10) {
            Text("No screen with id")
                .rsFont(.ui, size: 16, weight: .semibold)
                .foregroundStyle(Color.rsInk)
            Text(screen)
                .rsFont(.ui, size: 13)
                .foregroundStyle(Color.rsInk2)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .rsGroundScreen()
    }
}

/// The scan screen needs a live feed object, so it gets its own wrapper to
/// own one for the view's lifetime. The camera is the example room's picture.
private struct GalleryCapture: View {
    var tracking: TrackingQuality = .good
    var floor: SurfaceCoverage = .full
    var walls: SurfaceCoverage = .partial(0.62)
    var corners: SurfaceCoverage = .partial(0.5)
    var drawn = true
    var showsPlan = true

    @StateObject private var feed = FloorPlanFeed()

    var body: some View {
        LiveCaptureView(
            state: CaptureHUDState(
                tracking: tracking,
                guestLine: showsPlan
                    ? "Move slowly — I’ll draw the room as you go."
                    : "Move slowly and keep the walls in view — I’m measuring with the camera.",
                floor: floor, walls: walls, corners: corners
            ),
            feed: feed,
            showsPlan: showsPlan,
            cameraLayer: AnyView(
                Image("ExampleRoom")
                    .resizable()
                    .aspectRatio(contentMode: .fill)
                    .ignoresSafeArea()
            )
        )
        .onAppear {
            if drawn { feed.publish(snapshot: .previewRoom) }
            feed.publish(camera: .previewCamera)
        }
    }
}

#Preview("Gallery · unknown id") {
    ScreenGalleryView(screen: "home-all")
}

#endif
