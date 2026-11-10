/// The picture of a room, wherever one is drawn: its card, its own screen,
/// the moment it is ready.
///
/// THREE TIERS, best first, and each one honest about what it is:
///   1. The server's STILL of the finished room (`still_url`, or
///      `still_night_url` by lamplight), when the API sends one. Rendered by
///      the server with the website's look; the app only caches it.
///   2. The room's MEASURED OUTLINE: the floor polygon from the room's shell,
///      which `GET /scenes/{id}/assets` already returns, drawn in ink with its
///      overall size. Fetched once per room and kept, because a shell does not
///      change.
///   3. A plain tile, when neither exists yet. No stand-in picture is invented.
///
/// The operator chose the server still on 2026-11-10; the server side is its
/// own piece of work, so until it ships every room shows tier 2.
///
/// Read by: HomeScreen (cards), RoomScreen, ReadyScreen. Pinned by:
/// RoomOutlineTests (the geometry and the size).

import Combine
import os
import SwiftUI
import UIKit

// MARK: - The outline, as geometry

/// A room's floor outline, squared to the frame and scaled into a unit box,
/// with its overall size.
nonisolated struct RoomOutline: Equatable, Codable {
    /// The outline's corners in a 0...1 box, aspect preserved, in order.
    let points: [CGPoint]
    /// The overall size in metres, longer side first.
    let length: Double
    let width: Double

    /// "4.40 × 3.60 m" — the room's overall extent, a measurement.
    var sizeText: String {
        String(format: "%.2f × %.2f m", length, width)
    }

    /// Build the outline from the shell's floor polygon. Points are
    /// `[x, y, z]` (RoomPlan's world points) or `[x, z]` (the older closure),
    /// in metres. Nil when there is no area to draw.
    ///
    /// SQUARED TO THE ROOM, not to the world: the room is turned so its
    /// minimum-area bounding rectangle is level, which is how a person reads a
    /// plan, and that rectangle is the size reported.
    static func make(polygon: [[Double]]) -> RoomOutline? {
        let floor: [CGPoint] = polygon.compactMap { p in
            switch p.count {
            case 2: return CGPoint(x: p[0], y: p[1])
            case 3...: return CGPoint(x: p[0], y: p[2])
            default: return nil
            }
        }
        guard floor.count >= 3 else { return nil }

        var best: (angle: CGFloat, area: CGFloat, w: CGFloat, h: CGFloat)?
        for i in floor.indices {
            let a = floor[i], b = floor[(i + 1) % floor.count]
            let dx = b.x - a.x, dy = b.y - a.y
            guard dx * dx + dy * dy > 1e-8 else { continue }
            let angle = atan2(dy, dx)
            let turned = floor.map { rotate($0, by: -angle) }
            let xs = turned.map(\.x), ys = turned.map(\.y)
            let w = (xs.max() ?? 0) - (xs.min() ?? 0)
            let h = (ys.max() ?? 0) - (ys.min() ?? 0)
            let area = w * h
            if best == nil || area < best!.area - 1e-9 {
                best = (angle, area, w, h)
            }
        }
        guard let best, best.w > 0.01, best.h > 0.01 else { return nil }

        // Long side across the frame, as a plan is usually read.
        var turn = -best.angle
        if best.h > best.w { turn -= .pi / 2 }
        let turned = floor.map { rotate($0, by: turn) }
        let xs = turned.map(\.x), ys = turned.map(\.y)
        let minX = xs.min()!, minY = ys.min()!
        let w = xs.max()! - minX, h = ys.max()! - minY
        let scale = 1 / max(w, h)
        let offX = (1 - w * scale) / 2, offY = (1 - h * scale) / 2
        let unit = turned.map { CGPoint(x: ($0.x - minX) * scale + offX, y: ($0.y - minY) * scale + offY) }
        return RoomOutline(points: unit,
                           length: Double(max(best.w, best.h)),
                           width: Double(min(best.w, best.h)))
    }

    private static func rotate(_ p: CGPoint, by angle: CGFloat) -> CGPoint {
        CGPoint(x: p.x * cos(angle) - p.y * sin(angle), y: p.x * sin(angle) + p.y * cos(angle))
    }
}

/// The outline as a shape, inset into whatever frame it is given.
struct RoomOutlineShape: Shape {
    let outline: RoomOutline

    func path(in rect: CGRect) -> Path {
        var path = Path()
        let side = min(rect.width, rect.height)
        let origin = CGPoint(x: rect.midX - side / 2, y: rect.midY - side / 2)
        for (i, p) in outline.points.enumerated() {
            let q = CGPoint(x: origin.x + p.x * side, y: origin.y + p.y * side)
            if i == 0 { path.move(to: q) } else { path.addLine(to: q) }
        }
        path.closeSubpath()
        return path
    }
}

// MARK: - Fetching the outline

/// One question to the API: the floor polygon of a room's shell.
actor SceneShellClient {
    static let shared = SceneShellClient()

    private let baseURL: URL
    private let urlSession: URLSession

    init(baseURL: URL = NetworkConfig.apiPublicBaseURL, urlSession: URLSession = .shared) {
        self.baseURL = baseURL
        self.urlSession = urlSession
    }

    private struct Body: Decodable {
        struct Shell: Decodable {
            struct Floor: Decodable { let polygon: [[Double]]? }
            let floor: Floor?
        }
        let shell: Shell?
    }

    /// The polygon, nil when the room has no shell floor yet, or throws when
    /// the question could not be asked.
    func floorPolygon(sceneId: String,
                      tokenProvider: @Sendable () async throws -> String) async throws -> [[Double]]? {
        let url = baseURL.appendingPathComponent("scenes").appendingPathComponent(sceneId).appendingPathComponent("assets")
        func ask(_ token: String) async throws -> (Data, Int) {
            var request = URLRequest(url: url)
            request.timeoutInterval = 30
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
            let (data, response) = try await urlSession.data(for: request)
            return (data, (response as? HTTPURLResponse)?.statusCode ?? 0)
        }
        var (data, status) = try await ask(try await tokenProvider())
        if status == 401 { (data, status) = try await ask(try await tokenProvider()) }
        guard status == 200 else { throw URLError(.badServerResponse) }
        return try JSONDecoder().decode(Body.self, from: data).shell?.floor?.polygon
    }
}

// MARK: - The stores

/// Outlines and stills, kept on disk. An outline is fetched once per room; a
/// still once per launch, so a redrawn picture replaces a saved one.
@MainActor
final class RoomPictureStore: ObservableObject {
    static let shared = RoomPictureStore()

    @Published private(set) var outlines: [String: RoomOutline] = [:]
    @Published private(set) var stills: [String: UIImage] = [:]

    private var asked: Set<String> = []
    private let logger = Logger(subsystem: "com.thegoodguest.TheGoodGuest", category: "RoomPicture")
    private let tokenProvider: @Sendable () async throws -> String = {
        try await AuthManager.shared.signInIfNeeded()
        return try await AuthManager.shared.currentIDToken()
    }

    private lazy var folder: URL = {
        let base = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
        let dir = base.appendingPathComponent("room-pictures", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }()

    init() {
        if let data = try? Data(contentsOf: outlinesFile),
           let saved = try? JSONDecoder().decode([String: RoomOutline].self, from: data) {
            outlines = saved
        }
    }

    private var outlinesFile: URL { folder.appendingPathComponent("outlines.json") }

    private static func stillKey(_ sceneId: String, night: Bool) -> String {
        sceneId + (night ? "-night" : "-day")
    }

    func still(sceneId: String, night: Bool) -> UIImage? {
        stills[Self.stillKey(sceneId, night: night)]
    }

    /// Ask for whatever this room can show. A ready room's outline never
    /// changes, so a saved one is never asked for again.
    ///
    /// A STILL IS FETCHED ONCE PER LAUNCH EVEN WHEN A COPY IS SAVED: the server
    /// redraws a room's picture at the same path after its furniture is merged
    /// (the moment the room becomes a diorama), and nothing in the API says
    /// when. The saved copy shows at once; a newer one replaces it. Its link
    /// is signed afresh on every call, so the cache is keyed by the room, never
    /// by the link.
    func ensure(sceneId: String, stillURL: URL?, stillNightURL: URL?) {
        for (url, night) in [(stillURL, false), (stillNightURL, true)] {
            let key = Self.stillKey(sceneId, night: night)
            let file = folder.appendingPathComponent(key + ".jpg")
            if stills[key] == nil, let data = try? Data(contentsOf: file), let image = UIImage(data: data) {
                stills[key] = image
            }
            guard let url, !asked.contains(key) else { continue }
            asked.insert(key)
            Task {
                guard let (data, response) = try? await URLSession.shared.data(from: url),
                      (response as? HTTPURLResponse)?.statusCode == 200,
                      let image = UIImage(data: data) else {
                    // Not asked again this launch; the next launch tries again.
                    asked.remove(key)
                    return
                }
                if (try? Data(contentsOf: file)) == data { return }
                try? data.write(to: file, options: .atomic)
                stills[key] = image
            }
        }
        guard outlines[sceneId] == nil, !asked.contains(sceneId) else { return }
        asked.insert(sceneId)
        let provider = tokenProvider
        Task {
            do {
                guard let polygon = try await SceneShellClient.shared.floorPolygon(sceneId: sceneId, tokenProvider: provider),
                      let outline = RoomOutline.make(polygon: polygon) else { return }
                outlines[sceneId] = outline
                if let data = try? JSONEncoder().encode(outlines) { try? data.write(to: outlinesFile, options: .atomic) }
            } catch {
                // Not asked again this launch; the next launch tries again.
                logger.info("[RoomPicture] no outline for \(sceneId, privacy: .public): \(error.localizedDescription, privacy: .public)")
            }
        }
    }

    #if DEBUG
    /// The gallery's fixtures: a picture without a network.
    func seed(sceneId: String, outline: RoomOutline? = nil, still: UIImage? = nil, night: Bool = false) {
        if let outline { outlines[sceneId] = outline }
        if let still { stills[Self.stillKey(sceneId, night: night)] = still }
        asked.insert(sceneId)
    }
    #endif
}

// MARK: - The view

/// A room's picture in a frame: the still, else the outline, else a tile.
/// What a picture has to ask for: the room, and which of its links exist.
private struct PictureAsk: Hashable {
    let sceneId: String?
    let day: Bool
    let night: Bool
}

struct RoomPicture: View {
    let sceneId: String?
    var stillURL: URL? = nil
    var stillNightURL: URL? = nil
    /// Lamplight: the night still, and the outline drawn for dusk.
    var night = false
    /// Draw the size under the outline (large frames only).
    var showsSize = false

    @ObservedObject private var store = RoomPictureStore.shared

    var body: some View {
        ZStack {
            Rectangle().fill(night ? Color.rsRaised : Color.rsInset)
            // By lamplight when asked and rendered; otherwise the day still,
            // which is still the room, before falling back to its outline.
            if let sceneId, let image = store.still(sceneId: sceneId, night: night)
                                         ?? store.still(sceneId: sceneId, night: false) {
                Image(uiImage: image)
                    .resizable()
                    .aspectRatio(contentMode: .fill)
                    .accessibilityLabel("Your room, rebuilt")
            } else if let sceneId, let outline = store.outlines[sceneId] {
                outlineView(outline)
            } else {
                Image(systemName: "square.dashed")
                    .font(.system(size: 18, weight: .regular))
                    .foregroundStyle(night ? Color.rsOnDusk2 : Color.rsInk2)
                    .accessibilityHidden(true)
            }
        }
        .clipped()
        // Keyed on whether a link exists, not only on the room: a picture is
        // drawn some seconds after a room is ready, so the link often arrives
        // on a later answer than the room did, and must be asked for then.
        .task(id: PictureAsk(sceneId: sceneId, day: stillURL != nil, night: stillNightURL != nil)) {
            if let sceneId {
                store.ensure(sceneId: sceneId, stillURL: stillURL, stillNightURL: stillNightURL)
            }
        }
    }

    @ViewBuilder
    private func outlineView(_ outline: RoomOutline) -> some View {
        GeometryReader { geo in
            let inset = min(geo.size.width, geo.size.height) * (showsSize ? 0.16 : 0.14)
            VStack(spacing: 10) {
                ZStack {
                    RoomOutlineShape(outline: outline)
                        .fill(night ? Color.rsRaised2 : Color.rsSurface)
                    RoomOutlineShape(outline: outline)
                        .stroke(night ? Color.rsOnDusk : Color.rsInk,
                                style: StrokeStyle(lineWidth: showsSize ? 2 : 1.5, lineJoin: .round))
                }
                .padding(inset)
                if showsSize {
                    MeasureText(outline.sizeText, size: 13, onDusk: night)
                        .padding(.bottom, 14)
                }
            }
            .frame(width: geo.size.width, height: geo.size.height)
        }
        .accessibilityElement()
        .accessibilityLabel("The room's measured outline, \(outline.sizeText.replacingOccurrences(of: " × ", with: " by "))")
    }
}
