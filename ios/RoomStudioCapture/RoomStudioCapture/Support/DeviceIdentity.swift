/// Stable per-device identity for CaptureBundle.device.device_id.
///
/// A UUID minted on first use and persisted in the iOS Keychain
/// (kSecClassGenericPassword). The backend requires a non-empty device_id
/// and rejects bundles without one as failed_invalid ("device_id_missing")
/// — the historical hardware_id fallback was removed.
///
/// Keychain accessibility is AfterFirstUnlockThisDeviceOnly:
///   - readable during background relaunches (anything after first unlock),
///     matching the CAFUFA posture of the capture files (decision 0042);
///   - ThisDeviceOnly: never synced via iCloud Keychain and never restored
///     onto different hardware — a restored backup minting a fresh id is
///     correct, because it IS a different device.
///
/// If the Keychain write fails (should not happen in practice), the minted
/// UUID is still returned and cached for this process, so device_id is
/// always non-empty; identity would then churn across launches rather than
/// break the capture path.
///
/// Consumers: BundleAssembler.makeDevice().

import Foundation
import Security

enum DeviceIdentity {

    private static let service =
        (Bundle.main.bundleIdentifier ?? "com.roomstudio.RoomStudioCapture") + ".device-identity"
    private static let account = "device_id"

    private static let lock = NSLock()
    private static var cached: String?

    /// Return the stable device UUID, minting and persisting it on first use.
    static func deviceId() -> String {
        lock.lock()
        defer { lock.unlock() }
        if let cached { return cached }
        if let existing = read() {
            cached = existing
            return existing
        }
        let value = mintAndStore()
        cached = value
        return value
    }

    // MARK: - Keychain plumbing

    private static func read() -> String? {
        let query: [String: Any] = [
            kSecClass as String:       kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecReturnData as String:  true,
            kSecMatchLimit as String:  kSecMatchLimitOne,
        ]
        var item: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &item) == errSecSuccess,
              let data  = item as? Data,
              let value = String(data: data, encoding: .utf8),
              !value.isEmpty
        else { return nil }
        return value
    }

    private static func mintAndStore() -> String {
        let fresh = UUID().uuidString.lowercased()
        let attrs: [String: Any] = [
            kSecClass as String:          kSecClassGenericPassword,
            kSecAttrService as String:    service,
            kSecAttrAccount as String:    account,
            kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly,
            kSecValueData as String:      Data(fresh.utf8),
        ]
        let status = SecItemAdd(attrs as CFDictionary, nil)
        if status == errSecDuplicateItem, let existing = read() {
            // Lost a write race — prefer the value that actually persisted.
            return existing
        }
        // Success, or a non-duplicate failure (fresh value used unpersisted).
        return fresh
    }
}
