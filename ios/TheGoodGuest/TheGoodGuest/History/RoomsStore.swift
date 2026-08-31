/// The one place the app holds "what rooms has this identity sent?".
///
/// Owns a single GET /scenes fetch and publishes it to every surface that needs
/// it — the house, home's sentence, and the contents sheet's count. One store
/// rather than a fetch per surface, because the count the sign-in invitation
/// asserts and the rows the list draws must not be able to disagree.
///
/// THE STATE IS FOUR-WAY ON PURPOSE. "No rooms" and "could not ask" are
/// different answers and are never collapsed: `.loaded(rooms: [])` is the server
/// saying the caller has none, `.failed` is the phone not knowing. Every surface
/// downstream states something to the user about how many rooms they have, and
/// a surface that renders zero on a failed fetch tells them their rooms are gone
/// — the same family of lie decision 0216 removed from the identity screens, in
/// a cheaper costume.
///
/// A refresh that fails AFTER a success keeps the rooms it already had and marks
/// them stale rather than discarding them. Those rooms were really sent; the
/// only thing in doubt is whether the list is current, and that is what `stale`
/// says.
///
/// Scoped to the token, always (see ScenesListClient). There is no query here
/// for anyone else's rooms and there must not be one.
///
/// Read by: RootFlowView (the home strip + the rooms list + the sign-in
/// invitation's trigger).

import Combine
import Foundation
import os

// MARK: - Load state

/// What the app knows about the caller's rooms right now.
nonisolated enum RoomsLoadState: Equatable {
    /// Nothing asked yet.
    case idle
    /// First fetch in flight; nothing known.
    case loading
    /// The server answered. `[]` means genuinely none. `stale` marks a list that
    /// was current when it arrived and could not be refreshed since.
    case loaded(rooms: [RoomSummary], stale: Bool)
    /// The question could not be asked or answered. NOT zero rooms.
    case failed(reason: String)

    /// The rooms, or nil when they are not known.
    ///
    /// Optional deliberately: `[]` and "don't know" have to stay
    /// distinguishable at every call site, and a non-optional accessor that
    /// returned `[]` for `.failed` would quietly re-introduce exactly the
    /// collapse this type exists to prevent.
    var knownRooms: [RoomSummary]? {
        if case .loaded(let rooms, _) = self { return rooms }
        return nil
    }

    /// The count, or nil when it is not known. This is what the contents
    /// sheet's status column is made of, and why it goes blank rather than
    /// stating a zero when the fetch fails.
    var knownCount: Int? { knownRooms?.count }
}

// MARK: - Store

@MainActor
final class RoomsStore: ObservableObject {

    static let shared = RoomsStore()

    @Published private(set) var state: RoomsLoadState = .idle

    private let client: ScenesListClient
    private let tokenProvider: @Sendable () async throws -> String
    private let now: () -> Date

    /// Single-flight. Home's `.task` re-fires on every return to home and the
    /// rooms list refreshes on appear; without this a user bouncing between them
    /// would stack fetches that race to publish.
    private var inFlight: Task<Void, Never>?

    private let logger = Logger(subsystem: "com.thegoodguest.TheGoodGuest", category: "RoomsStore")

    init(
        client: ScenesListClient = .shared,
        now: @escaping () -> Date = { Date() },
        tokenProvider: @escaping @Sendable () async throws -> String = {
            // Same cold-launch order safety as ScenePoller: make sure the
            // anonymous user exists before asking for a token, rather than
            // assuming the launch sign-in already won the race.
            try await AuthManager.shared.signInIfNeeded()
            return try await AuthManager.shared.currentIDToken()
        }
    ) {
        self.client        = client
        self.now           = now
        self.tokenProvider = tokenProvider
    }

    // MARK: - Public API

    /// Fetch the caller's rooms, joining a fetch already in flight.
    ///
    /// Safe to call on every appearance: the payload is small, and a room the
    /// user just sent should show up when they come back to home.
    func refresh() async {
        if let inFlight {
            await inFlight.value
            return
        }
        let task = Task { await self.performFetch() }
        inFlight = task
        await task.value
        inFlight = nil
    }

    /// Drop everything known. Called when the identity changes underneath the
    /// app — the previous identity's rooms are not this one's, and showing them
    /// for even one frame would be the wrong answer to "are my rooms still
    /// here?".
    func clear() {
        inFlight?.cancel()
        inFlight = nil
        state = .idle
    }

    // MARK: - Private

    private func performFetch() async {
        let previous = state.knownRooms
        if previous == nil { state = .loading }

        do {
            let scenes = try await client.list(tokenProvider: tokenProvider)
            guard !Task.isCancelled else { return }
            state = .loaded(rooms: RoomHistory.summaries(from: scenes, now: now()), stale: false)
            logger.info("[RoomsStore] loaded \(scenes.count) scene(s)")
        } catch {
            guard !Task.isCancelled else { return }
            let reason = error.localizedDescription
            if let previous {
                // Keep what we know; say only that it may be out of date.
                state = .loaded(rooms: previous, stale: true)
                logger.info("[RoomsStore] refresh failed, keeping \(previous.count) known: \(reason, privacy: .public)")
            } else {
                state = .failed(reason: reason)
                logger.info("[RoomsStore] failed: \(reason, privacy: .public)")
            }
        }
    }
}
