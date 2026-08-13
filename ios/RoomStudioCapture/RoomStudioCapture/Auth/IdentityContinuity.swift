/// What it means when Firebase has no current user at launch.
///
/// `AuthManager.signInIfNeeded()` guards decision 0036's no-churn invariant
/// with one condition: `Auth.auth().currentUser != nil`. That condition is
/// true of a first run and equally true of an install whose stored credential
/// was discarded — and the app's response to both is to mint a fresh
/// anonymous user, which Firebase then persists over whatever was there.
/// Decision 0139 measured that happening twice on one phone.
///
/// This reading tells the two apart from state the app already holds, using
/// signals that live in different places and fail independently:
///
///   - the device UUID (Keychain, same access group as Firebase's credential),
///   - capture records (Application Support, outside the Keychain entirely).
///
/// A missing credential beside a readable device UUID means the Keychain is
/// answering and Firebase's item is genuinely gone. A missing credential
/// beside a missing device UUID, on an install that carries capture records,
/// means the Keychain is not answering at all — a different fault with a
/// different cure, and the one branch that is recoverable by waiting.
///
/// Read by: AuthManager.signInIfNeeded (logging only — this reading does not
/// decide whether to sign in; see decision 0141 for the question it raises).
enum IdentityContinuity {

    enum Reading: Equatable {
        /// A Firebase user is present. Nothing to report.
        case continuous
        /// No user, and no trace of this install having captured before.
        case firstRun
        /// No user, but the device UUID reads back: the Keychain is working
        /// and the stored credential is gone. Every scene the old UID owns is
        /// about to become unreachable from this install.
        case credentialLost
        /// No user and no device UUID, on an install that has capture records:
        /// the Keychain is not answering. The credential may still be intact.
        case keychainUnavailable
    }

    /// Classify the launch. Pure; every input is a fact the caller has already
    /// gathered, so this stays testable without Firebase or a Keychain.
    static func read(hasFirebaseUser: Bool,
                     hasDeviceIdentity: Bool,
                     hasCaptureRecords: Bool) -> Reading {
        if hasFirebaseUser { return .continuous }
        if hasDeviceIdentity { return .credentialLost }
        return hasCaptureRecords ? .keychainUnavailable : .firstRun
    }

    /// True when the reading describes an install that has lost an identity it
    /// used to have — the cases worth a fault-level log and, per decision 0141,
    /// the cases a person may need to be told about.
    static func isLoss(_ reading: Reading) -> Bool {
        reading == .credentialLost || reading == .keychainUnavailable
    }
}
