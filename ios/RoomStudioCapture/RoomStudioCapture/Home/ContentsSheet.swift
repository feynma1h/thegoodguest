/// The contents — the whole map of the app, behind the mark.
///
/// A book's table of contents rather than a tab bar: serif entries, dot
/// leaders, a mono truth on the right. It is reached by tapping the mark in
/// home's header and by no other route, which is why home teaches it once on
/// first run.
///
/// WHY NOT TABS. A tab bar states four destinations permanently, in the chrome,
/// on every screen — which is exactly the dashboard the product spent its whole
/// design avoiding. This states the same four, but only when asked, and it can
/// say something true about each one on the way past. A tab bar cannot tell you
/// that two things need you; a contents page can, and then gets out of the way.
///
/// THE STATUS COLUMN CAN BE BLANK, and that is the honesty constraint rather
/// than a layout accident. A count the phone cannot vouch for is not rendered
/// at all — never a zero, never a dash that reads as none. `Contents.rows`
/// decides that; this file only draws what it is given.
///
/// The claim sits at the foot as a colophon: the contents is the one place the
/// thesis can be restated without competing with home's own copy of it.
///
/// Read by: RootFlowView, presented from HomeView's mark.

import SwiftUI

struct ContentsSheet: View {
    var day: HomeDay = HomeDay()
    var onOpen: (ContentsEntry) -> Void = { _ in }
    var onClose: () -> Void = {}

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header

            VStack(spacing: 0) {
                ForEach(Contents.rows(for: day), id: \.entry) { row in
                    ContentsRowView(row: row) { onOpen(row.entry) }
                }
            }
            .padding(.top, 22)

            Spacer(minLength: 30)

            colophon
        }
        .padding(.horizontal, 26)
        .padding(.top, 22)
        .padding(.bottom, 14)
        .frame(maxWidth: .infinity, alignment: .topLeading)
        .modifier(RSScrollableScreen(background: Color.rsSurface))
    }

    private var header: some View {
        HStack {
            Mark(size: 24)
            Spacer()
            Button(action: onClose) {
                Image(systemName: "xmark")
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(Color.rsInkMuted)
                    .frame(width: 32, height: 32)
                    .background(Color.rsInk.opacity(0.06), in: Circle())
            }
            .accessibilityLabel("Close")
        }
    }

    /// The thesis, restated where it does not compete with home's copy of it.
    private var colophon: some View {
        Text("Every home holds a version of itself you've never seen.")
            .rsFont(.guest, size: 14)
            .foregroundStyle(Color.rsInkFaint)
            .lineSpacing(2)
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: .infinity, alignment: .leading)
    }
}

// MARK: - One row

/// A contents line: serif title, dot leaders, mono truth.
///
/// The leaders are drawn rather than typed — a run of periods would be read
/// aloud by VoiceOver and would not survive a title that wraps. At accessibility
/// sizes the row stacks instead, because leaders between two stacked blocks
/// point at nothing.
private struct ContentsRowView: View {
    let row: ContentsRow
    var onTap: () -> Void = {}

    @Environment(\.dynamicTypeSize) private var typeSize

    var body: some View {
        Button(action: onTap) {
            VStack(alignment: .leading, spacing: 6) {
                if typeSize.isAccessibilitySize {
                    title
                    if let status = row.status { statusText(status) }
                } else {
                    HStack(alignment: .firstTextBaseline, spacing: 10) {
                        title
                        // Leaders only when they lead somewhere. A dotted rule
                        // running the width of the row to an empty column
                        // points at nothing, which is exactly the impression
                        // the blank-not-zero rule exists to avoid.
                        if let status = row.status {
                            Leaders()
                            statusText(status)
                        } else {
                            Spacer(minLength: 0)
                        }
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.vertical, 14)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .overlay(alignment: .bottom) {
            Rectangle().fill(Color.rsHairline).frame(height: 1)
        }
        .accessibilityLabel(row.status.map { "\(row.entry.title), \($0)" } ?? row.entry.title)
    }

    private var title: some View {
        Text(row.entry.title)
            .rsFont(.display, size: 20, weight: .medium)
            .foregroundStyle(Color.rsInk)
            .fixedSize(horizontal: false, vertical: true)
    }

    private func statusText(_ status: String) -> some View {
        Text(status)
            .rsFont(.mono, size: 10.5, weight: .semibold)
            .tracking(1.1)
            .foregroundStyle(ink)
            .fixedSize(horizontal: false, vertical: true)
    }

    /// Rust only when something needs a decision, gold only for light arriving.
    private var ink: Color {
        switch row.tone {
        case .needsYou: return .rsAction
        case .arrival:  return .rsGoldInk
        case .quiet:    return .rsInkFaint
        }
    }
}

/// The dot leaders. A drawn dotted rule rather than typed periods, so VoiceOver
/// does not read them and a long title cannot break them across a line.
private struct Leaders: View {
    var body: some View {
        Rectangle()
            .fill(Color.clear)
            .frame(height: 1)
            .frame(minWidth: 12)
            .overlay(
                Line()
                    .stroke(style: StrokeStyle(lineWidth: 1.5, lineCap: .round, dash: [1.5, 5]))
                    .foregroundStyle(Color.rsInk.opacity(0.28))
            )
            .accessibilityHidden(true)
    }

    private struct Line: Shape {
        func path(in rect: CGRect) -> Path {
            var p = Path()
            p.move(to: CGPoint(x: rect.minX, y: rect.midY))
            p.addLine(to: CGPoint(x: rect.maxX, y: rect.midY))
            return p
        }
    }
}

// MARK: - Previews

#Preview("Quiet day") {
    ContentsSheet(day: HomeDay(roomCount: 6))
}

#Preview("Eventful day") {
    ContentsSheet(day: HomeDay(needsYou: 2, hasRoomInFlight: true, roomCount: 9))
}

#Preview("The house declines its count") {
    ContentsSheet(day: HomeDay(needsYou: 1, roomCount: nil))
}
