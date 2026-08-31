/// Restores the swipe-back gesture on a NavigationStack whose bars are hidden.
///
/// THE PROBLEM. UIKit owns the interactive pop gesture, and it disables it
/// whenever the navigation bar is hidden — the gesture is conceptually attached
/// to the back button, so with no bar there is nothing for it to be the shortcut
/// FOR. SwiftUI exposes no way to say otherwise: neither
/// `.navigationBarHidden(true)` nor `.toolbar(.hidden, for: .navigationBar)`
/// keeps it, and both were measured failing on device-class simulator before
/// this was written.
///
/// WHY WE HIDE THE BAR AT ALL. Every pushed screen in this app sets its own
/// title in the guest's display serif, with the mark or a back chevron beside
/// it. A system navigation bar cannot render that without losing the voice, so
/// the bar goes and the screens draw their own headers. That is a deliberate
/// trade, and this file is the cost of it.
///
/// WHY IT MATTERS. The back chevron is not a substitute. Swiping from the left
/// edge is how people go back on iOS, and it is the one affordance a sheet
/// still had after the contents stopped being one — losing it would have made
/// the pushed screen strictly worse to leave than the sheet it replaced.
///
/// HOW. A zero-size view walks up the responder chain to the enclosing
/// `UINavigationController` and hands its pop recogniser a delegate that says
/// yes whenever there is something to pop back to. Deliberately NOT an
/// `extension UINavigationController` overriding `viewDidLoad` — the usual
/// recipe on the internet — because overriding in an extension is not
/// supported, applies to every navigation controller the process ever creates
/// including ones inside system sheets, and has no scope limit.
///
/// The `count > 1` check is what stops the gesture fighting the root: at the
/// bottom of the stack there is nothing behind home, and a recogniser that
/// always said yes would swallow horizontal drags there.

import SwiftUI
import UIKit

extension View {
    /// Give this navigation stack its swipe-back gesture even with the bar
    /// hidden. Applied once, on the stack's root.
    func rsBackSwipe() -> some View {
        background(BackSwipeEnabler().frame(width: 0, height: 0))
    }
}

private struct BackSwipeEnabler: UIViewRepresentable {
    func makeUIView(context: Context) -> UIView { EnablerView() }
    func updateUIView(_ uiView: UIView, context: Context) {}
}

private final class EnablerView: UIView {
    /// Held here because `interactivePopGestureRecognizer.delegate` is weak —
    /// without an owner the shim deallocates immediately and the gesture goes
    /// back to being disabled, silently.
    private let shim = PopShim()

    override func didMoveToWindow() {
        super.didMoveToWindow()
        guard let nav = enclosingNavigationController else { return }
        shim.navigation = nav
        nav.interactivePopGestureRecognizer?.delegate = shim
        nav.interactivePopGestureRecognizer?.isEnabled = true
    }

    private var enclosingNavigationController: UINavigationController? {
        var responder: UIResponder? = next
        while let current = responder {
            if let nav = current as? UINavigationController { return nav }
            responder = current.next
        }
        return nil
    }
}

private final class PopShim: NSObject, UIGestureRecognizerDelegate {
    weak var navigation: UINavigationController?

    func gestureRecognizerShouldBegin(_ gestureRecognizer: UIGestureRecognizer) -> Bool {
        (navigation?.viewControllers.count ?? 0) > 1
    }

    /// A pushed screen that scrolls horizontally would otherwise have to choose
    /// between its own gesture and this one. Nothing in this app does today,
    /// but allowing simultaneous recognition keeps the edge swipe working if
    /// one ever appears.
    func gestureRecognizer(
        _ gestureRecognizer: UIGestureRecognizer,
        shouldRecognizeSimultaneouslyWith other: UIGestureRecognizer
    ) -> Bool { true }
}
