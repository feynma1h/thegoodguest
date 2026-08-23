/// Home's re-entry row: the way back into a room that is still being rebuilt.
///
/// Without it, leaving the wait was one-way — the room keeps processing but no
/// surface could ever show it again, so "leaving is free" was false.
///
/// It renders in `HomeView`'s `notice` slot, inside the scroll area. It used to
/// be stacked in the wrapper above `HomeView`, which is the position decision
/// 0224 measured: at accessibility sizes a notice there takes the height the
/// pinned scan action needs, and the action truncates. Content scrolls; only the
/// action is pinned.
///
/// The row states a fact and offers one move, so the whole row is the control —
/// there is no second affordance to compete with the scan action for the eye.

import SwiftUI

struct ReEntryRow: View {
    var onOpen: () -> Void = {}

    var body: some View {
        Button(action: onOpen) {
            // .top, not centred: at accessibility sizes the line wraps to
            // several lines, and a vertically centred dot and chevron come to
            // rest in the middle of them — the dot reading as punctuation and
            // the chevron as though it pointed at one word. Decision 0224.
            HStack(alignment: .top, spacing: 9) {
                Circle()
                    .fill(Color.rsGold)
                    .frame(width: 7, height: 7)
                    .frame(height: 18, alignment: .center)
                Text("One room is on its way — check on it")
                    .font(RSFont.ui(.subheadline, weight: .medium))
                    .foregroundStyle(Color.rsInk)
                    .fixedSize(horizontal: false, vertical: true)
                    .multilineTextAlignment(.leading)
                Spacer(minLength: 6)
                Image(systemName: "chevron.right")
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(Color.rsInk.opacity(0.4))
                    .frame(height: 18, alignment: .center)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, 14)
            .padding(.vertical, 11)
            .background(Color.rsSurface.opacity(0.9), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).stroke(Color.rsHairline, lineWidth: 1))
        }
        .buttonStyle(.plain)
    }
}

#Preview("Re-entry row") {
    VStack {
        ReEntryRow()
        Spacer()
    }
    .padding(26)
    .frame(maxWidth: .infinity, maxHeight: .infinity)
    .rsParchmentScreen()
}
