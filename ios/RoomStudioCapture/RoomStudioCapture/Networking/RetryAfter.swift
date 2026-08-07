/// `Retry-After` parsing, in one place.
///
/// WHY IT IS ITS OWN TYPE: two independent paths now honor a server-directed
/// wait — the blob PUTs (GCS sends Retry-After on 408/429/503) and the
/// `/upload_session` mint (api-public sends it on the per-UID daily quota 429,
/// decision 0087). They were written months apart and the second was about to
/// re-implement RFC 9110 §10.2.3 a second time. Same rule the pose math follows
/// on the Python side: one implementation, imported, never re-derived.
///
/// Read by: BlobUploadManager, UploadSessionClient. Pinned by: RetryAfterTests.

import Foundation

nonisolated enum RetryAfter {

    /// Parse a `Retry-After` header value into a wait interval.
    ///
    /// Two wire forms: delta-seconds ("120") and HTTP-date
    /// ("Wed, 21 Oct 2015 07:28:00 GMT"). Returns nil for an absent or malformed
    /// value — callers fall back to their own backoff schedule. An HTTP-date
    /// already in the past yields 0 (the wait has elapsed).
    static func parse(_ headerValue: String?, now: Date) -> TimeInterval? {
        guard let raw = headerValue?.trimmingCharacters(in: .whitespaces), !raw.isEmpty else {
            return nil
        }
        if let seconds = TimeInterval(raw) {
            return (seconds.isFinite && seconds >= 0) ? seconds : nil
        }
        let formatter = DateFormatter()
        formatter.locale     = Locale(identifier: "en_US_POSIX")
        formatter.timeZone   = TimeZone(identifier: "GMT")
        formatter.dateFormat = "EEE, dd MMM yyyy HH:mm:ss zzz"
        guard let date = formatter.date(from: raw) else { return nil }
        return max(0, date.timeIntervalSince(now))
    }

    /// Parse an ISO-8601 instant emitted by the Python backend.
    ///
    /// `datetime.isoformat()` writes the offset as `+00:00` (never `Z`) and
    /// includes microseconds only when they are non-zero, so BOTH forms appear on
    /// the wire from the same endpoint. The fractional part carries no meaning for
    /// a quota that rolls at midnight, so it is stripped rather than parsed — the
    /// same treatment ScenePoller gives `created_at`.
    static func parseISO8601(_ value: String?) -> Date? {
        guard let raw = value?.trimmingCharacters(in: .whitespaces), !raw.isEmpty else { return nil }
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        if let date = formatter.date(from: raw) { return date }
        // Strip a fractional-seconds component and retry: "…T00:00:00.123456+00:00".
        if let dot = raw.firstIndex(of: "."),
           let offsetStart = raw[dot...].firstIndex(where: { $0 == "+" || $0 == "-" || $0 == "Z" }) {
            return formatter.date(from: String(raw[raw.startIndex..<dot]) + String(raw[offsetStart...]))
        }
        return nil
    }
}
