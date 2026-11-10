/// Review: the room you got, before it is sent.
///
/// THE 2026-11-10 REDESIGN folds "I've got the room" into review's title: the
/// 1.8 s screen of its own is gone, and the success haptic plays here instead.
/// The plan is drawn in ink on a light inset with the room's overall size as
/// terracotta annotations; the facts say what will be rebuilt — walls and
/// doors, and the pieces boxed, since an unboxed piece does not appear (0323).
///
/// LEAVING IS DISCARDING, and says so: the old "Not now" dropped the capture
/// with no way back. The close button asks first.
///
/// What it says is `ReviewCopy`'s (pure, tested); this file only draws it.
///
/// Read by: RootFlowView, the gallery. Pinned by: ReviewCopyTests.

import SwiftUI

// MARK: - The copy

nonisolated struct ReviewContent: Equatable {
    let title: String
    let facts: [String]
    /// Shown in the plan's place when there is no plan to draw.
    var noPlanTitle: String? = nil
    var noPlanDetail: String? = nil
    let guest: String
    /// The filled button sends; when nothing can be sent it rescans instead.
    let canSend: Bool
    let isPreparing: Bool
}

nonisolated enum ReviewCopy {

    /// Everything review says about one capture.
    ///
    /// - census: the BUILT room's census, present exactly when a RoomPlan room
    ///   ships with the bundle (tier LIDAR_ROOMPLAN).
    /// - boxes: the pieces the person boxed, or nil in a build that cannot box.
    static func content(frames: Int, tier: RSCaptureTier, census: RoomCensus?, hasPlan: Bool,
                        boxes: Int?, isPreparing: Bool, assemblyFailure: String?) -> ReviewContent {
        if frames == 0 {
            return ReviewContent(title: "I didn’t catch enough to send.", facts: [],
                                 noPlanTitle: "Nothing measured yet",
                                 noPlanDetail: "That pass ended before I could see the room.",
                                 guest: "Let’s walk it again — it only takes a couple of minutes.",
                                 canSend: false, isPreparing: false)
        }
        if let assemblyFailure {
            return ReviewContent(title: "I couldn’t pack this one up.", facts: [photos(frames, tier)],
                                 noPlanTitle: "Nothing to send",
                                 noPlanDetail: "The scan couldn’t be packed for sending (\(assemblyFailure)).",
                                 guest: "Let’s walk the room again.",
                                 canSend: false, isPreparing: false)
        }
        var facts: [String] = []
        if let census { facts.append(structure(census)) }
        if let boxes { facts.append(boxes == 1 ? "1 piece boxed" : "\(boxes) pieces boxed") }
        facts.append(photos(frames, tier))

        let camera = tier == .arkitOnly
        return ReviewContent(
            title: "I’ve got the room.",
            facts: facts,
            noPlanTitle: hasPlan ? nil : (camera ? "Measured with the camera" : "No floor plan from this pass"),
            noPlanDetail: hasPlan ? nil : (camera
                ? "This iPhone has no LiDAR, so there’s no floor plan on the phone. I’ll work out the walls from the photos once it’s sent."
                : "The walls didn’t close into a plan on the phone. I’ll work them out from the photos once it’s sent."),
            guest: isPreparing
                ? "Packing it up — one moment before it can travel."
                : (camera
                    ? "Send it, and I’ll start rebuilding it. Rooms measured by camera come out a little less exact."
                    : "Send it, and I’ll start rebuilding it. You can put the phone down once it’s on its way."),
            canSend: !isPreparing,
            isPreparing: isPreparing
        )
    }

    /// "13 walls and 2 doors" — what the walls came to. Windows and openings
    /// join it only when there are some.
    static func structure(_ census: RoomCensus) -> String {
        var parts = [counted(census.walls, "wall", "walls")]
        if census.doors > 0 { parts.append(counted(census.doors, "door", "doors")) }
        if census.windows > 0 { parts.append(counted(census.windows, "window", "windows")) }
        if census.openings > 0 { parts.append(counted(census.openings, "opening", "openings")) }
        if parts.count == 1 { return parts[0] }
        return parts.dropLast().joined(separator: ", ") + " and " + parts.last!
    }

    /// "126 photos, measured with LiDAR".
    static func photos(_ frames: Int, _ tier: RSCaptureTier) -> String {
        let with = tier == .arkitOnly ? "the camera" : "LiDAR"
        return "\(counted(frames, "photo", "photos")), measured with \(with)"
    }

    private static func counted(_ n: Int, _ one: String, _ many: String) -> String {
        "\(n) \(n == 1 ? one : many)"
    }
}

// MARK: - The screen

struct ReviewView: View {
    let content: ReviewContent
    var floorPlan: FloorPlanSnapshot? = nil
    var onSend: () -> Void = {}
    var onRescan: () -> Void = {}
    var onDiscard: () -> Void = {}

    @State private var confirmingDiscard = false

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    Text(content.title)
                        .rsFont(.display, size: 34, cap: .display)
                        .tracking(-0.7)
                        .foregroundStyle(Color.rsInk)
                        .fixedSize(horizontal: false, vertical: true)
                        .padding(.horizontal, 4)
                        .accessibilityAddTraits(.isHeader)

                    stage
                        .frame(height: 290)
                        .background(Color.rsInset, in: RoundedRectangle(cornerRadius: 24, style: .continuous))
                        .clipShape(RoundedRectangle(cornerRadius: 24, style: .continuous))
                        .padding(.top, 18)

                    VStack(alignment: .leading, spacing: 8) {
                        ForEach(content.facts, id: \.self) { fact in
                            Label {
                                Text(fact)
                                    .rsFont(.ui, size: 15)
                                    .foregroundStyle(Color.rsInk)
                                    .fixedSize(horizontal: false, vertical: true)
                            } icon: {
                                Image(systemName: "checkmark")
                                    .font(.system(size: 12, weight: .bold))
                                    .foregroundStyle(Color.rsInk2)
                            }
                        }
                    }
                    .padding(.top, 16)
                    .padding(.horizontal, 4)

                    GuestVoice(content.guest)
                        .padding(.top, 22)
                        .padding(.horizontal, 4)
                }
                .padding(.horizontal, 16)
                .padding(.top, 4)
                .padding(.bottom, 24)
            }
            .background(GroundBackground())
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button { confirmingDiscard = true } label: { Image(systemName: "xmark") }
                        .accessibilityLabel("Discard this scan")
                }
            }
            .safeAreaInset(edge: .bottom, spacing: 0) { actions }
        }
        .tint(Color.rsInk)
        .confirmationDialog("Discard this scan?", isPresented: $confirmingDiscard, titleVisibility: .visible) {
            Button("Discard scan", role: .destructive) { onDiscard() }
            Button("Keep it", role: .cancel) {}
        } message: {
            Text("It hasn’t been sent, so nothing of it is kept.")
        }
    }

    @ViewBuilder
    private var stage: some View {
        if let floorPlan, !floorPlan.isEmpty, content.noPlanTitle == nil {
            FloorPlanCanvas(snapshot: floorPlan, animated: false, backdrop: .rsInset,
                            padding: 44, style: .ink, showsDimensions: true)
                .padding(8)
        } else {
            VStack(spacing: 6) {
                Image(systemName: "map")
                    .font(.system(size: 26, weight: .light))
                    .foregroundStyle(Color.rsInk2)
                    .padding(.bottom, 6)
                if let title = content.noPlanTitle {
                    Text(title)
                        .rsFont(.ui, size: 16, weight: .semibold)
                        .foregroundStyle(Color.rsInk)
                }
                if let detail = content.noPlanDetail {
                    Text(detail)
                        .rsFont(.ui, size: 14)
                        .foregroundStyle(Color.rsInk2)
                        .multilineTextAlignment(.center)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            .padding(24)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
    }

    private var actions: some View {
        VStack(spacing: 2) {
            if content.canSend {
                Button("Send it") { onSend() }
                    .buttonStyle(RSPrimaryButtonStyle())
                Button("Scan again") { onRescan() }
                    .buttonStyle(RSQuietButtonStyle())
            } else if content.isPreparing {
                Button { } label: {
                    HStack(spacing: 10) { ProgressView().tint(.white); Text("Packing it up") }
                }
                .buttonStyle(RSPrimaryButtonStyle())
                .disabled(true)
                .opacity(0.4)
                Button("Scan again") { onRescan() }
                    .buttonStyle(RSQuietButtonStyle())
            } else {
                Button("Scan again") { onRescan() }
                    .buttonStyle(RSPrimaryButtonStyle())
                Button("Discard") { onDiscard() }
                    .buttonStyle(RSQuietButtonStyle())
            }
        }
        .padding(.horizontal, 20)
        .padding(.top, 12)
        .padding(.bottom, 4)
        .background(Color.rsGround.ignoresSafeArea(edges: .bottom))
    }
}
