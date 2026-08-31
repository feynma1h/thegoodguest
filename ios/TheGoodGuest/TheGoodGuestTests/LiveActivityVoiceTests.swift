/// Pins the Live Activity's copy and its MIRRORING of the in-app wait screens.
///
/// The extension's views cannot be unit-tested from here (a different target, a
/// system-rendered surface), which is exactly why every word lives in a pure
/// table instead of inside three SwiftUI bodies. What this pins is that the table
/// is complete, honest, and says the same things the app says — a Lock Screen
/// contradicting the screen the user just left is the failure that matters, and
/// it is the one nobody would catch by reading.

import XCTest
@testable import TheGoodGuest

final class LiveActivityVoiceTests: XCTestCase {

    private let allStages: [RoomActivityStage] = [
        .preparing, .sending(sent: 3, total: 10), .sending(sent: 0, total: 0),
        .finalizing, .queued, .analyzing, .ready, .paused,
        .failed(.upload), .failed(.processing), .failed(.incomplete),
    ]

    // MARK: - Completeness

    func test_everyStageHasWordsAndAMark() {
        for stage in allStages {
            XCTAssertFalse(RoomActivityVoice.title(stage).isEmpty, "no title for \(stage)")
            XCTAssertFalse(RoomActivityVoice.line(stage).isEmpty, "no line for \(stage)")
            XCTAssertFalse(RoomActivityVoice.compact(stage).isEmpty, "no compact for \(stage)")
            XCTAssertFalse(RoomActivityVoice.symbol(stage).isEmpty, "no symbol for \(stage)")
        }
    }

    func test_glanceCopyStaysShort() {
        // The Dynamic Island's compact slot is a handful of points wide and the
        // Lock Screen card is two lines. Copy that outgrows them truncates.
        //
        // The 70 below is the bound the design set; the longest line actually
        // shipped is ~49. A new line near 70 is unverified territory — the
        // shipped set was screenshot-checked, that bound was not — so treat a
        // near-miss here as a prompt to re-screenshot, not as a pass.
        for stage in allStages {
            XCTAssertLessThanOrEqual(RoomActivityVoice.compact(stage).count, 4,
                                     "compact too long for \(stage)")
            XCTAssertLessThanOrEqual(RoomActivityVoice.title(stage).count, 44,
                                     "title too long for \(stage)")
            XCTAssertLessThanOrEqual(RoomActivityVoice.line(stage).count, 70,
                                     "line too long for \(stage)")
        }
    }

    // MARK: - Mirroring the app

    func test_titlesMirrorTheInAppSurfaces() {
        // the desk's own titles.
        XCTAssertEqual(RoomActivityVoice.title(.sending(sent: 3, total: 10)), "Sending your room")
        XCTAssertEqual(RoomActivityVoice.title(.queued), "Getting in line")
        XCTAssertEqual(RoomActivityVoice.title(.analyzing), "Making sense of your room")
        // DoorwayView's arrival line.
        XCTAssertEqual(RoomActivityVoice.title(.ready), "Your room is ready.")
        // FailureView's own headlines, verbatim.
        XCTAssertEqual(RoomActivityVoice.title(.failed(.upload)), "I couldn't get it up to the desk.")
        XCTAssertEqual(RoomActivityVoice.title(.failed(.processing)), "The scan didn't survive the trip.")
        XCTAssertEqual(RoomActivityVoice.title(.failed(.incomplete)), "The room didn't all make it up")
    }

    // MARK: - Voice rules

    func test_noPromiseOfANotification() {
        // Push is not built (enrollment-gated), so "I'll let you know" would be a
        // promise nothing can keep — the same rule the desk's long-running line follows.
        for stage in allStages {
            let text = (RoomActivityVoice.title(stage) + " " + RoomActivityVoice.line(stage)).lowercased()
            for banned in ["i'll knock", "notify", "notification", "i'll let you know", "i'll ping"] {
                XCTAssertFalse(text.contains(banned), "\(stage) promises a notification: \(banned)")
            }
        }
    }

    func test_noETAAndNoBlame() {
        for stage in allStages {
            let text = (RoomActivityVoice.title(stage) + " " + RoomActivityVoice.line(stage)).lowercased()
            for banned in ["minutes left", "seconds left", "estimated", "eta", "you should have",
                           "you didn't", "your fault", "try scanning slower"] {
                XCTAssertFalse(text.contains(banned), "\(stage) breaks a voice rule: \(banned)")
            }
        }
    }

    func test_pausedSaysWhereTheResumeActuallyHappens() {
        // Waiting on the Lock Screen does nothing; opening the app is what moves it.
        XCTAssertTrue(RoomActivityVoice.line(.paused).lowercased().contains("open me"),
                      "paused must name the action that actually resumes the upload")
    }

    // MARK: - Finalizing (decisions 0110 / 0111)

    /// The stage exists to stop the card claiming "sending" once the count is
    /// complete, so it must not itself read as an upload still in flight, and it
    /// must carry no count — `counter` is nil here, which is the point.
    func test_finalizingDoesNotReadAsStillSending() {
        XCTAssertEqual(RoomActivityVoice.title(.finalizing), "Signing it in")
        XCTAssertNil(RoomActivityVoice.counter(.finalizing),
                     "a count here would be the completed-count-labelled-in-progress bug again")
        XCTAssertNil(RoomActivityStage.finalizing.fraction,
                     "no progress bar: there is one file left and no honest fraction of it")
    }

    /// THE 0110 CONSTRAINT: the OS can hold the finalize for many minutes, and we
    /// cannot read the delay. So the copy must name the action that releases it
    /// (opening the app resets the delay to 0) without claiming a time.
    func test_finalizingNamesTheActionAndClaimsNoTime() {
        let line = RoomActivityVoice.line(.finalizing).lowercased()
        XCTAssertTrue(line.contains("open me"),
                      "must name the action that resets the background-launch delay")
        for timeClaim in ["almost", "any moment", "nearly done", "soon", "a few seconds"] {
            XCTAssertFalse(line.contains(timeClaim), "time claim: \(timeClaim)")
            XCTAssertFalse(RoomActivityVoice.title(.finalizing).lowercased().contains(timeClaim),
                           "time claim in title: \(timeClaim)")
        }
    }

    /// It is NOT `.paused`: that stage promises the upload has stopped and will
    /// resume on open. The finalize may well land on its own, so the weaker hedge
    /// is the honest one.
    func test_finalizingDoesNotClaimTheUploadStopped() {
        let text = (RoomActivityVoice.title(.finalizing) + " " + RoomActivityVoice.line(.finalizing)).lowercased()
        XCTAssertFalse(text.contains("paused"))
        XCTAssertFalse(text.contains("stopped"))
        XCTAssertFalse(text.contains("i'll pick it up"))
    }

    func test_sendingDoesNotTellTheUserToStayInTheApp() {
        // The upload runs on a background URLSession; staying in the app is not
        // required, and after a deferral it is exactly what prevents recovery.
        let text = RoomActivityVoice.line(.sending(sent: 1, total: 2)).lowercased()
        XCTAssertFalse(text.contains("keep the app open"))
        XCTAssertFalse(text.contains("stay in the app"))
    }

    // MARK: - Machine data

    func test_counterOnlyWhereThereIsAnHonestCount() {
        XCTAssertEqual(RoomActivityVoice.counter(.sending(sent: 128, total: 385)), "128 of 385")
        XCTAssertNil(RoomActivityVoice.counter(.sending(sent: 0, total: 0)),
                     "an unknown total must not render as '0 of 0'")
        XCTAssertNil(RoomActivityVoice.counter(.analyzing))
        XCTAssertNil(RoomActivityVoice.counter(.ready))
    }

    func test_compactShowsPercentWhileSending() {
        XCTAssertEqual(RoomActivityVoice.compact(.sending(sent: 50, total: 100)), "50%")
        XCTAssertEqual(RoomActivityVoice.compact(.sending(sent: 385, total: 385)), "100%")
        XCTAssertEqual(RoomActivityVoice.compact(.ready), "✓")
    }

    // MARK: - The rule of gold

    func test_goldIsLightSemanticOnly() {
        // Gold is the doorway/"enough" moment — never a generic accent, and never
        // success/error decoration. Only `.ready` may carry it.
        XCTAssertEqual(RoomActivityVoice.tint(.ready), .rsGold)
        for stage in allStages where stage != .ready {
            XCTAssertNotEqual(RoomActivityVoice.tint(stage), .rsGold,
                              "\(stage) must not use gold")
        }
    }

    func test_failureIsInkNotRed() {
        for failure: RoomActivityFailure in [.upload, .processing, .incomplete] {
            XCTAssertEqual(RoomActivityVoice.tint(.failed(failure)), .rsInk)
        }
    }

    // MARK: - Accessibility

    func test_accessibilityLabelReadsAsOneSentenceAndIncludesTheCount() {
        let label = RoomActivityVoice.accessibilityLabel(.sending(sent: 128, total: 385))
        XCTAssertTrue(label.contains("Sending your room"))
        XCTAssertTrue(label.contains("128 of 385"))
        XCTAssertTrue(label.contains("On its way up"))
        // Stages without a count must not manufacture one.
        XCTAssertFalse(RoomActivityVoice.accessibilityLabel(.ready).contains(" of "))
    }
}
