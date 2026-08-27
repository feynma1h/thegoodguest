/// DEBUG-only screen gallery: renders exactly one screen, in isolation, from
/// fixtures — so every surface in the app can be photographed without staging
/// the state that would normally produce it.
///
/// WHY THIS EXISTS: most of the app's screens cannot be reached on demand. The
/// home notices need a terminally failed upload record, a bundle mid-flight and
/// a failed rooms fetch — three independent conditions, one of which requires a
/// real capture to have failed. The wait and failure screens need a round trip
/// to the backend. The doorway needs a room to have finished rebuilding. Every
/// one of them is a design surface someone has to be able to LOOK at, and the
/// iOS test policy is explicit that a green suite says nothing about rendering:
/// layout claims at accessibility sizes have to be verified by screenshot, and
/// three review passes previously claimed coverage they did not have.
///
/// So this is the screenshot half of that policy, made repeatable. It composes
/// each screen the same way `RootFlowView` composes it — the home variants are
/// built from a `HomeDay` and compose their own sentence through the real
/// resolver, so a photograph taken here is a photograph of the shipping routing
/// and not of a hand-written string.
///
/// HOW TO DRIVE IT, following `StagingHooks`' launch-argument convention:
///
///     xcrun simctl launch <udid> com.roomstudio.RoomStudioCapture \
///         -rs.gallery.screen home-needsyou
///
/// Pair it with `xcrun simctl ui <udid> content_size accessibility-extra-extra-extra-large`
/// to photograph the accessibility sizes, which is where this app's layout
/// defects have actually lived (decisions 0224 and 0238).
///
/// `ScreenGallery.screens` is the catalogue and the ONE list — the capture
/// script enumerates it rather than carrying its own copy, so a screen added
/// here is photographed without touching anything else.
///
/// Compiled out of release builds entirely. Nothing here runs in the live app:
/// the app entry point consults `requestedScreen` and falls through to
/// `RootFlowView` whenever the argument is absent.

#if DEBUG

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

    /// Every photographable screen: id, the caption a reader needs, and whether
    /// the screen animates on arrival (the capture script waits longer for those
    /// rather than photographing a half-played bloom).
    struct Entry {
        let id: String
        let title: String
        let note: String
        var settles = false
    }

    static let screens: [Entry] = [
        // ── Home: the claim, one sentence, one action. ──────────────────────
        .init(id: "home-first",    title: "Home · first run",
              note: "The claim, the support line, and the whisper that teaches where things live."),
        .init(id: "home-quiet",    title: "Home · ordinary day",
              note: "A standing fact, pointing at the house. The claim has not moved."),
        .init(id: "home-flight",   title: "Home · a room in flight",
              note: "Gold, quiet, pointing at the desk."),
        .init(id: "home-arrival",  title: "Home · arrival",
              note: "Gold, pointing at the doorway. The app's peak moment finally reaches home."),
        .init(id: "home-needsyou", title: "Home · something needs you",
              note: "Rust, pointing at Notes — and mentioning the flight without routing to it."),
        .init(id: "home-trouble",  title: "Home · rooms unreachable",
              note: "The count is unknown, so the sentence states no number and never a zero."),

        // ── The contents, behind the mark ───────────────────────────────────
        .init(id: "contents-quiet",    title: "Contents · quiet day",
              note: "The whole map as a table of contents. Four entries, always the same four."),
        .init(id: "contents-eventful", title: "Contents · eventful day",
              note: "Rust only for what needs you; the desk reports its own count."),
        .init(id: "contents-nocount",  title: "Contents · the house declines",
              note: "A count the phone cannot vouch for is blank — never zero."),

        // ── The desk. BUILT, not yet wired — the post-send surface still
        //    routes to the old wait screens. Photographable so the copy and
        //    the layout can be judged before it replaces them. ─────────────
        .init(id: "desk-sending", title: "The desk · sending",
              note: "Leaving is free, and the line says so rather than the button implying it."),
        .init(id: "desk-working", title: "The desk · at the desk",
              note: "Elapsed only, coarse, from the server's clock. No orb, no pill."),
        .init(id: "desk-paused",  title: "The desk · paused",
              note: "Finally has a surface. Nothing for the user to do, said plainly."),
        .init(id: "desk-limited", title: "The desk · today's limit",
              note: "Also finally has a surface. The only useful fact is when it lifts."),
        .init(id: "desk-retry",   title: "The desk · didn't leave the phone",
              note: "The one desk state with an action — retrying genuinely works."),
        .init(id: "desk-clear",   title: "The desk · clear",
              note: "The ordinary state, and it has to be the screen's best one."),

        // ── Notes ───────────────────────────────────────────────────────────
        .init(id: "notes-full",  title: "Notes · needs you, and news",
              note: "Failures first, the arrival below. Got it is permanent."),
        .init(id: "notes-news",  title: "Notes · news only",
              note: "The arrival card when nothing is wrong."),
        .init(id: "notes-quiet", title: "Notes · quiet",
              note: "The ordinary case. No illustration, no reassurance."),

        // ── The other history surface ───────────────────────────────────────
        .init(id: "rooms-list",        title: "The house",
              note: "The rooms that landed, and the thesis at its permanent address. No scan action."),
        .init(id: "rooms-stale",       title: "The house · stale",
              note: "The same stale line the strip carries, on the full list."),
        .init(id: "rooms-empty",       title: "The house · empty",
              note: "Genuinely none sent — distinct from not being able to ask."),
        .init(id: "rooms-loading",     title: "The house · loading",
              note: "Nothing known yet."),
        .init(id: "rooms-unreachable", title: "The house · unreachable",
              note: "The phone could not ask. It does not claim there are none."),

        // ── The capture flow ────────────────────────────────────────────────
        .init(id: "guidance",  title: "Before you start",
              note: "What the scan button opens. Camera permission is asked here, in context."),
        .init(id: "capture",   title: "Capturing",
              note: "The room drawing itself in ink. Tracking pill, coverage ticks, one spoken line."),
        .init(id: "capture-dark", title: "Capturing · too dark",
              note: "Tracking truth outranks anything the guest would otherwise say."),
        .init(id: "gotroom",   title: "I've got the room",
              note: "The single joyful beat. Holds 1.8 s, then review.", settles: true),
        .init(id: "review",    title: "Review",
              note: "The sketch, the capture metrics, and one honest chance to scan again."),

        // ── Waiting ─────────────────────────────────────────────────────────
        .init(id: "wait-sending",   title: "Sending",
              note: "Nothing has arrived yet, so no arrival claim and no clock."),
        .init(id: "wait-analyzing", title: "Analyzing",
              note: "Uploaded. The clock counts from the server's own start time."),
        .init(id: "wait-long",      title: "Still working",
              note: "Candid when it runs long. No ETA — the pipeline gives the phone none."),
        .init(id: "wait-trouble",   title: "Can't reach the studio",
              note: "The room is safe; the check is not landing."),
        .init(id: "wait-paused",    title: "Paused",
              note: "Resumes next launch. Nothing to do now — which the home row does not say."),
        .init(id: "wait-limited",   title: "Daily limit",
              note: "Not a failure treatment. The only useful fact is when it lifts."),

        // ── Arrival and failure ─────────────────────────────────────────────
        .init(id: "doorway",         title: "The doorway",
              note: "The arrival. Never auto-navigates — the user chooses to step through.", settles: true),
        .init(id: "fail-incomplete", title: "Incomplete upload",
              note: "Names the missing count. Offers a re-send only when the bytes are provably still here."),
        .init(id: "fail-rescan",     title: "Incomplete · rescan only",
              note: "The same screen when the files are gone. It promises nothing."),
        .init(id: "fail-terminal",   title: "Terminal failure",
              note: "Nothing survived. The deepest ink surface, one path out."),
        .init(id: "fail-upload",     title: "Upload failed",
              note: "The send broke, not the scan. Carries the only diagnostic the user has."),

        // ── Identity ────────────────────────────────────────────────────────
        .init(id: "profile",   title: "You",
              note: "The device ID as proof of continuity. Signing out lives on the web."),
        .init(id: "whysignin", title: "Why sign in",
              note: "Auto-presented once. Its whole argument is a count."),

        // ── Outside the flow ────────────────────────────────────────────────
        .init(id: "unsupported", title: "No depth camera",
              note: "The root gate. Honest, and offers nothing to do."),
        .init(id: "splash",      title: "The splash",
              note: "The name resolving into the mark. Plays over the launch work, not in front of it.",
              settles: true),
        .init(id: "qr",          title: "QR bridge",
              note: "Built, but blocked on deep links. The code encodes nothing."),
    ]
}

// MARK: - Fixtures

/// Synthetic, and obviously so: no real capture, no real identity. The rooms
/// carry the three states the row treatment distinguishes.
private enum GalleryFixture {

    static var rooms: [RoomSummary] { RoomSummary.samples() }

    static let uid = "gallery-fixture-not-a-real-uid"

    static let failureReason = "blob_unreadable_at_remint_manifest"

    /// A server anchor far enough back that the elapsed clock reads as a real wait.
    static var anchor: Date { Date().addingTimeInterval(-268) }
}

// MARK: - Home, composed the way the flow composes it

/// Home, from a HomeDay. The screen composes its own sentence through the real
/// resolver, so a photograph here is a photograph of the shipping routing and
/// not of a hand-written string.
private struct GalleryHome: View {
    var day: HomeDay

    var body: some View { HomeView(day: day) }
}

/// The capture screen needs a live feed object, so it gets its own wrapper to
/// own one for the view's lifetime rather than rebuilding it every render.
private struct GalleryCapture: View {
    var tracking: TrackingQuality = .good

    @StateObject private var feed = FloorPlanFeed()

    var body: some View {
        LiveCaptureView(
            state: CaptureHUDState(
                tracking: tracking,
                guestLine: "Move slowly and I'll sketch the room as you go.",
                floor: .full, walls: .partial(0.62), corners: .partial(0.5)
            ),
            feed: feed
        )
        .onAppear {
            feed.publish(snapshot: .previewRoom)
            feed.publish(camera: .previewCamera)
        }
    }
}

// MARK: - The gallery itself

struct ScreenGalleryView: View {
    let screen: String

    var body: some View {
        switch screen {

        // Home
        case "home-first":    GalleryHome(day: HomeDay(isFirstRun: true))
        case "home-quiet":    GalleryHome(day: HomeDay(roomCount: 6))
        case "home-flight":   GalleryHome(day: HomeDay(hasRoomInFlight: true, roomCount: 6))
        case "home-arrival":  GalleryHome(day: HomeDay(hasUnseenArrival: true, roomCount: 6))
        case "home-needsyou": GalleryHome(day: HomeDay(needsYou: 1, hasRoomInFlight: true,
                                                       roomCount: 6))
        case "home-trouble":  GalleryHome(day: HomeDay(roomCount: nil))

        // The contents, and the screens home now points at
        case "contents-quiet":
            ContentsScreen(day: HomeDay(roomCount: 6))
        case "contents-eventful":
            ContentsScreen(day: HomeDay(needsYou: 2, hasRoomInFlight: true, roomCount: 9))
        case "contents-nocount":
            ContentsScreen(day: HomeDay(needsYou: 1, roomCount: nil))
        case "desk-sending":
            DeskView(state: .sending, roomTitle: "today's room")
        case "desk-working":
            DeskView(state: .working(anchor: GalleryFixture.anchor, longRunning: false),
                     roomTitle: "today's room")
        case "desk-paused":
            DeskView(state: .paused, roomTitle: "yesterday's room")
        case "desk-limited":
            DeskView(state: .rateLimited(resetsAt: GalleryFixture.anchor.addingTimeInterval(31_000)),
                     roomTitle: "today's room")
        case "desk-retry":
            DeskView(state: .retryableSendFailure, roomTitle: "today's room")
        case "desk-clear":
            DeskView(state: nil)
        case "notes-full":
            NotesView(needsYou: [.uploadFailed(reason: GalleryFixture.failureReason),
                                 .incompleteUpload(missingCount: 3)],
                      arrival: "Yesterday's room is on your desk.",
                      canOpenArrival: true)
        case "notes-news":
            NotesView(arrival: "This morning's room is on your desk.")
        case "notes-quiet":
            NotesView()

        // Rooms
        case "rooms-list":
            HouseView(state: .loaded(rooms: GalleryFixture.rooms, stale: false))
        case "rooms-stale":
            HouseView(state: .loaded(rooms: GalleryFixture.rooms, stale: true))
        case "rooms-empty":
            HouseView(state: .loaded(rooms: [], stale: false))
        case "rooms-loading":
            HouseView(state: .loading)
        case "rooms-unreachable":
            HouseView(state: .failed(reason: "offline"))

        // Capture flow
        case "guidance":     GuidanceSheet()
        case "capture":      GalleryCapture()
        case "capture-dark": GalleryCapture(tracking: .tooDark)
        case "gotroom":      GotTheRoomView()
        case "review":
            ReviewView(metrics: "126 frames · LiDAR + RoomPlan",
                       census: "9 objects · 13 walls · 2 doors",
                       floorPlan: .previewRoom,
                       verdict: "Here's your capture. Send it, and I'll start making sense of it on your desk.",
                       rescanLabel: "Scan again from scratch")

        // Waiting
        case "wait-sending":   WaitingView(phase: .sending)
        case "wait-analyzing": WaitingView(phase: .analyzing, anchor: GalleryFixture.anchor)
        case "wait-long":      WaitingView(phase: .longRunning, anchor: GalleryFixture.anchor)
        case "wait-trouble":   WaitingView(phase: .connectionTrouble, anchor: GalleryFixture.anchor)
        case "wait-paused":    WaitingView(phase: .sendPaused)
        case "wait-limited":
            WaitingView(phase: .sendRateLimited(resetsAt: GalleryFixture.anchor.addingTimeInterval(31_000)))

        // Arrival and failure
        case "doorway":
            DoorwayView(signedIntoWeb: true, canOpenWeb: true)
        case "fail-incomplete":
            // onBack, because that is how the flow reaches it: without it the
            // gallery photographed a screen with no header, which is not the
            // one that ships.
            FailureView(kind: .recoverable(missingCount: 3, resend: .available),
                        onBack: {})
        case "fail-rescan":
            FailureView(kind: .recoverable(missingCount: 14, resend: .unavailable),
                        onBack: {})
        case "fail-terminal":
            FailureView(kind: .terminal)
        case "fail-upload":
            FailureView(kind: .uploadFailed(reason: GalleryFixture.failureReason))

        // Identity
        case "profile":
            ProfileView(uid: GalleryFixture.uid)
        case "whysignin":
            WhySignInSheet(roomCount: 3)

        // Outside the flow
        case "unsupported": UnsupportedDeviceView()
        case "splash":      SplashView()
        case "qr":          QRBridgeView()

        default:
            unknown
        }
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

#Preview("Gallery · home, everything at once") {
    ScreenGalleryView(screen: "home-all")
}

#endif
