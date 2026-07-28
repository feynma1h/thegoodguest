/// THROWAWAY SPIKE (board item 3 → board 7 design session input). Ships nothing.
///
/// One-screen operator UI for the co-run spike: camera preview off the SHARED
/// ARSession (ARSCNView renders it; RoomPlan does not get its own view — the
/// bare RoomCaptureSession is the production-intended shape), a big live
/// depth badge (the Q1 answer at a glance), phase-gated buttons for the probe
/// sequence, and a post-run summary with the CapturedRoom object list for the
/// operator walk.
///
/// Read by: the board-7 RoomPlan integration design session. Not product code.

import ARKit
import RoomPlan
import SceneKit
import SwiftUI

struct ARPreview: UIViewRepresentable {
    let session: ARSession

    func makeUIView(context: Context) -> ARSCNView {
        let v = ARSCNView(frame: .zero)
        v.session = session
        v.automaticallyUpdatesLighting = true
        return v
    }

    func updateUIView(_ uiView: ARSCNView, context: Context) {}
}

struct SpikeView: View {
    @StateObject private var c = SpikeController()

    var body: some View {
        VStack(spacing: 0) {
            ZStack(alignment: .bottomLeading) {
                ARPreview(session: c.arSession)
                    .frame(height: 280)
                    .clipped()
                depthOverlay
            }
            ScrollView {
                VStack(alignment: .leading, spacing: 10) {
                    if !RoomCaptureSession.isSupported {
                        Text("RoomPlan NOT SUPPORTED on this device")
                            .font(.headline)
                            .foregroundStyle(.red)
                    }
                    controls
                    Text("instruction: \(c.lastInstruction)   objects: \(c.objectsCountUI)  walls: \(c.wallsCountUI)")
                        .font(.system(size: 12, weight: .semibold, design: .monospaced))
                    Text(c.statusLines.joined(separator: "\n"))
                        .font(.system(size: 11, design: .monospaced))
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(8)
                        .background(Color(.secondarySystemBackground))
                        .cornerRadius(8)
                    if !c.summary.isEmpty {
                        Text(c.summary)
                            .font(.system(size: 12, weight: .semibold, design: .monospaced))
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(8)
                            .background(Color(.tertiarySystemBackground))
                            .cornerRadius(8)
                    }
                    if !c.objectRows.isEmpty {
                        VStack(alignment: .leading, spacing: 2) {
                            Text("CapturedRoom.objects")
                                .font(.system(size: 12, weight: .bold, design: .monospaced))
                            ForEach(Array(c.objectRows.enumerated()), id: \.offset) { _, row in
                                Text(row)
                                    .font(.system(size: 11, design: .monospaced))
                            }
                        }
                        .padding(8)
                        .background(Color(.secondarySystemBackground))
                        .cornerRadius(8)
                    }
                }
                .padding(12)
            }
        }
    }

    private var depthOverlay: some View {
        Text(c.depthBadge)
            .font(.system(size: 15, weight: .bold, design: .monospaced))
            .foregroundStyle(.white)
            .padding(.horizontal, 10)
            .padding(.vertical, 6)
            .background(depthColor.opacity(0.85))
            .cornerRadius(8)
            .padding(10)
    }

    private var depthColor: Color {
        switch c.depthGood {
        case .some(true): return .green
        case .some(false): return .red
        case .none: return .gray
        }
    }

    @ViewBuilder
    private var controls: some View {
        VStack(spacing: 8) {
            HStack {
                Picker("Mode", selection: $c.mode) {
                    ForEach(SpikeMode.allCases) { m in
                        Text(m.label).tag(m)
                    }
                }
                .pickerStyle(.segmented)
                .disabled(c.phase != .idle)
            }
            if c.mode != .solo {
                Toggle("RP first (don't pre-run ARKit)", isOn: $c.rpFirst)
                    .font(.system(size: 12))
                    .disabled(c.phase != .idle)
            }
            HStack(spacing: 8) {
                Button("Start") { c.startRun() }
                    .buttonStyle(.borderedProminent)
                    .disabled(c.phase != .idle)
                Button("Begin Room Scan") { c.beginRoomScan() }
                    .buttonStyle(.borderedProminent)
                    .tint(.orange)
                    .disabled(!(c.phase == .solo && c.mode != .solo))
                Button("Finish") { c.finishScan() }
                    .buttonStyle(.bordered)
                    .disabled(!(c.phase == .solo || c.phase == .rp || c.phase == .rpReasserted))
            }
            HStack(spacing: 8) {
                Button("Re-assert Depth") { c.reassertDepth() }
                    .buttonStyle(.bordered)
                    .tint(.green)
                    .disabled(!(c.phase == .rp || c.phase == .rpReasserted))
                Button("Interpose") { c.engageInterposerManually() }
                    .buttonStyle(.bordered)
                    .font(.footnote)
                    .disabled(!(c.phase == .rp || c.phase == .rpReasserted))
                Button("Take delegate") { c.takeDelegateBack() }
                    .buttonStyle(.bordered)
                    .font(.footnote)
                    .disabled(!(c.phase == .rp || c.phase == .rpReasserted))
                Button("New Run") { c.newRun() }
                    .buttonStyle(.bordered)
                    .disabled(c.phase != .finished)
            }
        }
    }
}
