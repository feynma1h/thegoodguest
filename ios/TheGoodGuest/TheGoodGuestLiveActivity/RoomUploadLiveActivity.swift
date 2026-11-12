/// The capture Live Activity's surfaces: Lock Screen card, Dynamic Island
/// (expanded / compact / minimal). Design spec §5, translated the same way the
/// in-app screens were (decision 0072).
///
/// EVERY WORD COMES FROM `RoomActivityVoice`, every colour from the shared design
/// tokens. Nothing is written inline here — this file is layout only. That is
/// what keeps the Lock Screen from drifting away from the wait screen it mirrors,
/// and it is why the copy is testable from the app target's test bundle even
/// though these views are not.
///
/// THE RULE OF GOLD holds: gold appears only on `.ready` (the doorway moment),
/// via `RoomActivityVoice.tint`. Work in progress is rust; failure is ink.
///
/// SIZE DISCIPLINE: the Lock Screen card and the expanded island are the same
/// content at two widths, so they share `stageBody`. The compact and minimal
/// presentations get a symbol and at most four characters — a percentage while
/// sending, a mark otherwise.

import ActivityKit
import SwiftUI
import WidgetKit

struct RoomUploadLiveActivity: Widget {
    var body: some WidgetConfiguration {
        ActivityConfiguration(for: RoomActivityAttributes.self) { context in
            LockScreenCard(stage: context.state.stage, startedAt: context.attributes.startedAt)
                // White, like every card in the app. The system supplies its
                // own material behind this on some Lock Screens, so the tint is
                // stated rather than assumed.
                .activityBackgroundTint(Color.rsSurface)
                .activitySystemActionForegroundColor(Color.rsInk)
        } dynamicIsland: { context in
            let stage = context.state.stage
            return DynamicIsland {
                DynamicIslandExpandedRegion(.leading) {
                    Image(systemName: RoomActivityVoice.symbol(stage))
                        .font(.system(size: 20, weight: .regular))
                        .foregroundStyle(RoomActivityVoice.tint(stage, onDusk: true))
                        .padding(.leading, 4)
                }
                DynamicIslandExpandedRegion(.trailing) {
                    if let counter = RoomActivityVoice.counter(stage) {
                        Text(counter)
                            .rsFont(.ui, size: 13, weight: .medium)
                            .monospacedDigit()
                            .foregroundStyle(Color.rsOnDusk2)
                            .padding(.trailing, 4)
                    }
                }
                DynamicIslandExpandedRegion(.center) {
                    Text(RoomActivityVoice.title(stage))
                        .rsFont(.ui, size: 16, weight: .semibold)
                        .foregroundStyle(Color.rsOnDusk)
                        .lineLimit(2)
                        .multilineTextAlignment(.center)
                }
                DynamicIslandExpandedRegion(.bottom) {
                    VStack(spacing: 8) {
                        if let fraction = stage.fraction {
                            ProgressBar(fraction: fraction, tint: RoomActivityVoice.tint(stage, onDusk: true),
                                        track: Color.rsOnDusk.opacity(0.18))
                        }
                        Text(RoomActivityVoice.line(stage))
                            .rsFont(.guest, size: 15)
                            .foregroundStyle(Color.rsOnDusk)
                            .multilineTextAlignment(.center)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    .padding(.horizontal, 4)
                }
            } compactLeading: {
                Image(systemName: RoomActivityVoice.symbol(stage))
                    .foregroundStyle(RoomActivityVoice.tint(stage, onDusk: true))
            } compactTrailing: {
                Text(RoomActivityVoice.compact(stage))
                    .rsFont(.ui, size: 13, weight: .medium)
                    .monospacedDigit()
                    .foregroundStyle(RoomActivityVoice.tint(stage, onDusk: true))
            } minimal: {
                Image(systemName: RoomActivityVoice.symbol(stage))
                    .foregroundStyle(RoomActivityVoice.tint(stage, onDusk: true))
            }
            // The island is dark chrome by nature, so its accent stays inside the
            // stage's own tint rather than introducing a second accent colour.
            .keylineTint(RoomActivityVoice.tint(stage, onDusk: true))
        }
    }
}

// MARK: - Lock Screen

private struct LockScreenCard: View {
    let stage: RoomActivityStage
    let startedAt: Date

    var body: some View {
        HStack(alignment: .top, spacing: 14) {
            Image(systemName: RoomActivityVoice.symbol(stage))
                .font(.system(size: 18, weight: .regular))
                .foregroundStyle(Color.rsInk)
                .frame(width: 40, height: 40)
                .background(Color.rsInset, in: Circle())

            VStack(alignment: .leading, spacing: 5) {
                HStack(alignment: .firstTextBaseline) {
                    Text(RoomActivityVoice.title(stage))
                        .rsFont(stage == .ready ? .display : .ui, size: stage == .ready ? 22 : 16,
                                weight: stage == .ready ? .light : .semibold)
                        .foregroundStyle(Color.rsInk)
                        .lineLimit(2)
                        .fixedSize(horizontal: false, vertical: true)
                    Spacer(minLength: 8)
                    if let counter = RoomActivityVoice.counter(stage) {
                        Text(counter)
                            .rsFont(.ui, size: 13, weight: .medium)
                            .monospacedDigit()
                            .foregroundStyle(Color.rsInk2)
                            .layoutPriority(1)
                    }
                }

                Text(RoomActivityVoice.line(stage))
                    .rsFont(.guest, size: 15)
                    .foregroundStyle(Color.rsInk)
                    .fixedSize(horizontal: false, vertical: true)

                if let fraction = stage.fraction {
                    ProgressBar(fraction: fraction,
                                tint: Color.rsInk,
                                track: Color.rsInset)
                        .padding(.top, 3)
                }
            }
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        // One read instead of three fragments (title / line / counter).
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(RoomActivityVoice.accessibilityLabel(stage))
    }
}

// MARK: - Progress

/// A plain determinate bar. `ProgressView(value:)` is not used: its tint and
/// track cannot both be set to brand tokens across the Lock Screen and the
/// island's dark chrome, and this bar is four lines.
private struct ProgressBar: View {
    let fraction: Double
    let tint: Color
    let track: Color

    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .leading) {
                Capsule().fill(track)
                Capsule().fill(tint)
                    .frame(width: max(0, min(1, fraction)) * geo.size.width)
            }
        }
        .frame(height: 4)
        .accessibilityHidden(true)   // the card's combined label already says it
    }
}

// MARK: - Previews

#Preview("Lock Screen — sending", as: .content, using: RoomActivityAttributes.preview) {
    RoomUploadLiveActivity()
} contentStates: {
    RoomActivityState(stage: .preparing)
    RoomActivityState(stage: .sending(sent: 128, total: 385))
    RoomActivityState(stage: .analyzing)
    RoomActivityState(stage: .ready)
    RoomActivityState(stage: .paused)
    RoomActivityState(stage: .failed(.upload))
}

extension RoomActivityAttributes {
    fileprivate static var preview: RoomActivityAttributes {
        RoomActivityAttributes(bundleId: "preview-bundle", startedAt: .now)
    }
}
