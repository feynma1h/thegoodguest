/// The contents — the whole map of the app, behind the mark.
///
/// A book's table of contents rather than a tab bar: serif entries, dot
/// leaders, a mono truth on the right. It is reached by tapping the mark in
/// home's header and by no other route.
///
/// A SCREEN, NOT A SHEET. A sheet is something that happens TO the screen you
/// are on and is dismissed by swiping it away; this is a place, and the way
/// back out is the way you came in. It also lets the contents push onward to
/// the four screens it lists without stacking a sheet on a sheet.
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
/// Read by: RootFlowView, pushed from HomeView's mark.

import SwiftUI

struct ContentsScreen: View {
    var day: HomeDay = HomeDay()
    var onOpen: (ContentsEntry) -> Void = { _ in }
    var onBack: () -> Void = {}

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header

            VStack(spacing: 0) {
                ForEach(Contents.rows(for: day), id: \.entry) { row in
                    ContentsRowView(row: row) { onOpen(row.entry) }
                }
            }
            // The rows pad themselves by 14; without accounting for it the
            // first entry sat lower than every other screen's first line.
            .rsBelowHeader(ownInset: 14)

            Spacer(minLength: 30)

            colophon
        }
        .rsScreenInsets()
        .frame(maxWidth: .infinity, alignment: .topLeading)
        .modifier(RSScrollableScreen(background: Color.rsSurface))
    }

    /// A back chevron, not a close cross. The contents is a place you went to,
    /// so the way out is the way you came — which is the whole reason this
    /// stopped being a sheet.
    private var header: some View {
        ScreenHeaderFrame {
            BackChevron(action: onBack)
            ChromeMark()
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
    ContentsScreen(day: HomeDay(roomCount: 6))
}

#Preview("Eventful day") {
    ContentsScreen(day: HomeDay(needsYou: 2, hasRoomInFlight: true, roomCount: 9))
}

#Preview("The house declines its count") {
    ContentsScreen(day: HomeDay(needsYou: 1, roomCount: nil))
}
