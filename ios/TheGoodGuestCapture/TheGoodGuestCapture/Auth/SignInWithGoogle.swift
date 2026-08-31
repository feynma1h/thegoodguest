/// Google Sign-In support for account linking (decisions 0094/0118) — the
/// pieces kept out of AuthManager and SignInSheet so they are unit-testable
/// without a configured FirebaseApp, a GIDSignIn singleton, or a network.
///
/// The load-bearing piece is `preflight`: GoogleSignIn raises an NSException
/// (an uncatchable crash from Swift) at sign-in time when the app's Info.plist
/// does not register the reversed-client-ID URL scheme it needs for the
/// redirect back into the app. The scheme lives in the COMMITTED
/// TheGoodGuestCapture-Info.plist while the client ID lives in the GITIGNORED
/// GoogleService-Info.plist, so the two can drift (a stale local plist, a
/// regenerated OAuth client). Preflight checks the derived scheme against the
/// bundle's registrations and refuses with a readable message instead of
/// crashing; a test pins that the two files currently agree.
///
/// Read by: SignInSheet (preflight before GIDSignIn), AuthLinkingTests (pins).

import Foundation

nonisolated enum SignInWithGoogle {

    /// Verdict on whether the Google sign-in flow can be started safely.
    enum Preflight: Equatable {
        /// Config present and the redirect scheme is registered.
        case ready(reversedScheme: String)
        /// GoogleService-Info.plist carries no CLIENT_ID — the plist predates
        /// the project's iOS OAuth client (re-download it from the Firebase
        /// console) or Firebase is not configured at all.
        case missingClientID
        /// The derived redirect scheme is not in CFBundleURLTypes — starting
        /// the flow would crash inside GoogleSignIn.
        case schemeNotRegistered(expected: String)
    }

    /// Decide whether the Google flow may start. Pure — callers pass the
    /// client ID from FirebaseApp options and the bundle's registered schemes.
    static func preflight(
        clientID: String?,
        registeredURLSchemes: [String]
    ) -> Preflight {
        guard let clientID, let scheme = reversedClientID(fromClientID: clientID) else {
            return .missingClientID
        }
        guard registeredURLSchemes.contains(scheme) else {
            return .schemeNotRegistered(expected: scheme)
        }
        return .ready(reversedScheme: scheme)
    }

    /// Derive the redirect URL scheme from an iOS OAuth client ID:
    /// "NNN-xxx.apps.googleusercontent.com" → "com.googleusercontent.apps.NNN-xxx".
    /// Returns nil for anything not shaped like a Google iOS client ID — a
    /// malformed value must fail preflight, not produce a scheme that can
    /// never match.
    static func reversedClientID(fromClientID clientID: String) -> String? {
        let suffix = ".apps.googleusercontent.com"
        guard clientID.hasSuffix(suffix) else { return nil }
        let identifier = clientID.dropLast(suffix.count)
        guard !identifier.isEmpty else { return nil }
        return "com.googleusercontent.apps.\(identifier)"
    }

    /// Every URL scheme the bundle registers via CFBundleURLTypes, flattened.
    static func registeredURLSchemes(in bundle: Bundle) -> [String] {
        let urlTypes = bundle.object(forInfoDictionaryKey: "CFBundleURLTypes")
            as? [[String: Any]] ?? []
        return urlTypes.flatMap { $0["CFBundleURLSchemes"] as? [String] ?? [] }
    }
}
