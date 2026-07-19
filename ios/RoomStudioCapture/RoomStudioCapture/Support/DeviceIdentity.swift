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
///   - ThisDeviceOnly excludes this item from device backup/restore onto
///     different hardware (a separate mechanism from iCloud Keychain sync,
///     which this item was never opted into anyway — kSecAttrSynchronizable
///     is left unset). Concretely: restoring an iCloud/Finder backup from
///     one iPhone onto a new one does NOT carry this UUID over; the new
///     phone mints its own on first launch. Correct, because it IS a
///     different device — restoring the SAME phone from its own backup
///     (e.g. after an erase) is unaffected, since that's not a hardware change.
///
/// If the Keychain write fails (should not happen in practice), the minted
/// UUID is still returned and cached for this process, so device_id is
/// always non-empty; identity would then churn across launches rather than
/// break the capture path.
///
/// Consumers: BundleAssembler.makeDevice().

import Foundation
import Security
import os

enum DeviceIdentity {

    private static let logger = Logger(subsystem: "com.roomstudio.RoomStudioCapture", category: "DeviceIdentity")

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
        switch status {
        case errSecSuccess:
            break
        case errSecDuplicateItem:
            // Lost a write race — prefer the value that actually persisted.
            if let existing = read() { return existing }
        default:
            // Genuine write failure — the minted UUID is used for this launch only
            // and won't survive relaunch. Logged so a persistent failure (e.g. a
            // Keychain access-group misconfiguration) is observable in production
            // rather than silently churning device_id across launches forever.
            logger.error("[DeviceIdentity] Keychain write failed (status=\(status, privacy: .public)); using unpersisted id for this launch")
        }
        return fresh
    }
}
