/// Boxes as one triangle mesh of their edges, and the layer that draws it —
/// DEBUG-only (decision 0295).
///
/// Every box is twelve thin, solid square rods along its own axes, reaching
/// `thickness` past the corners so the rods meet. Positions are world
/// coordinates; indices are 32-bit.
///
/// ONE ENTITY PER LAYER, HOWEVER MANY BOXES. Each layer is one RealityKit
/// `LowLevelMesh` whose buffers are allocated once and rewritten in place,
/// under one material made once: on the phone memory rose about 35 MB with
/// every box that started being drawn, and never came back, when each box was
/// its own twelve entities and material.
///
/// Read by: LiveBoxesARHost, LiveBoxesPresentationTests.

#if DEBUG

import RealityKit
import UIKit
import simd

nonisolated enum BoxWireframe {
    static let edgesPerBox = 12
    static let verticesPerBox = edgesPerBox * 8
    static let indicesPerBox = edgesPerBox * 36

    /// The twelve faces' triangles of one rod, over its eight corners
    /// numbered by (x, y, z) bits.
    private static let rod: [UInt32] = [
        0, 1, 3, 0, 3, 2,   4, 6, 7, 4, 7, 5,   // −x, +x
        0, 4, 5, 0, 5, 1,   2, 3, 7, 2, 7, 6,   // −y, +y
        0, 2, 6, 0, 6, 4,   1, 5, 7, 1, 7, 3,   // −z, +z
    ]

    static func mesh(_ boxes: [GravityBox], thickness t: Float) -> (positions: [SIMD3<Float>], indices: [UInt32]) {
        var positions: [SIMD3<Float>] = []
        var indices: [UInt32] = []
        positions.reserveCapacity(boxes.count * verticesPerBox)
        indices.reserveCapacity(boxes.count * indicesPerBox)
        for box in boxes {
            let h = box.size / 2
            // Each edge: its centre and the axis it runs along.
            var rods: [(centre: SIMD3<Float>, axis: Int)] = []
            for sy in [Float(-1), 1] {
                for sz in [Float(-1), 1] { rods.append((SIMD3(0, sy * h.y, sz * h.z), 0)) }
            }
            for sx in [Float(-1), 1] {
                for sz in [Float(-1), 1] { rods.append((SIMD3(sx * h.x, 0, sz * h.z), 1)) }
            }
            for sx in [Float(-1), 1] {
                for sy in [Float(-1), 1] { rods.append((SIMD3(sx * h.x, sy * h.y, 0), 2)) }
            }
            let world = box.transform
            for r in rods {
                var half = SIMD3<Float>(repeating: t / 2)
                half[r.axis] = h[r.axis] + t / 2
                let base = UInt32(positions.count)
                for corner in 0..<8 {
                    let s = SIMD3<Float>(corner & 4 == 0 ? -1 : 1, corner & 2 == 0 ? -1 : 1, corner & 1 == 0 ? -1 : 1)
                    let w = world * SIMD4(r.centre + s * half, 1)
                    positions.append(SIMD3(w.x, w.y, w.z))
                }
                indices += rod.map { base + $0 }
            }
        }
        return (positions, indices)
    }
}

/// Everything one layer draws, as a single entity with a single mesh.
@MainActor
final class MeshLayer {
    let entity: ModelEntity
    private var mesh: LowLevelMesh
    private var vertexCapacity: Int
    private var indexCapacity: Int
    /// The boxes drawn now.
    private var shown: [GravityBox]?

    init?(material: UnlitMaterial, vertexCapacity: Int = 64 * BoxWireframe.verticesPerBox,
          indexCapacity: Int = 64 * BoxWireframe.indicesPerBox) {
        guard let mesh = Self.makeMesh(vertices: vertexCapacity, indices: indexCapacity),
              let resource = try? MeshResource(from: mesh) else { return nil }
        self.mesh = mesh
        self.vertexCapacity = vertexCapacity
        self.indexCapacity = indexCapacity
        entity = ModelEntity(mesh: resource, materials: [material])
        entity.isEnabled = false
    }

    private static func makeMesh(vertices: Int, indices: Int) -> LowLevelMesh? {
        let descriptor = LowLevelMesh.Descriptor(
            vertexCapacity: vertices,
            vertexAttributes: [LowLevelMesh.Attribute(semantic: .position, format: .float3, offset: 0)],
            vertexLayouts: [LowLevelMesh.Layout(bufferIndex: 0, bufferStride: 12)],
            indexCapacity: indices,
            indexType: .uint32)
        return try? LowLevelMesh(descriptor: descriptor)
    }

    /// Draw exactly these boxes, every edge whole. Nothing is rebuilt while
    /// they are unchanged.
    func show(boxes: [GravityBox], thickness: Float) {
        if let shown, shown == boxes { return }
        let (positions, indices) = BoxWireframe.mesh(boxes, thickness: thickness)
        show(positions: positions, indices: indices)
        shown = boxes
    }

    /// Draw exactly this mesh. The buffers are reallocated only if it outgrows them.
    func show(positions: [SIMD3<Float>], indices: [UInt32]) {
        shown = nil
        guard !indices.isEmpty else {
            entity.isEnabled = false
            return
        }
        if positions.count > vertexCapacity || indices.count > indexCapacity {
            var vertices = vertexCapacity, faces = indexCapacity
            while vertices < positions.count || faces < indices.count {
                vertices *= 2
                faces *= 2
            }
            guard let bigger = Self.makeMesh(vertices: vertices, indices: faces),
                  let resource = try? MeshResource(from: bigger) else { return }
            mesh = bigger
            vertexCapacity = vertices
            indexCapacity = faces
            entity.model?.mesh = resource
        }
        mesh.replaceUnsafeMutableBytes(bufferIndex: 0) { raw in
            let floats = raw.bindMemory(to: Float.self)
            for (i, p) in positions.enumerated() {
                floats[3 * i] = p.x
                floats[3 * i + 1] = p.y
                floats[3 * i + 2] = p.z
            }
        }
        mesh.replaceUnsafeMutableIndices { raw in
            let out = raw.bindMemory(to: UInt32.self)
            for (i, index) in indices.enumerated() { out[i] = index }
        }
        var lo = SIMD3<Float>(repeating: .greatestFiniteMagnitude), hi = -lo
        for p in positions {
            lo = simd_min(lo, p)
            hi = simd_max(hi, p)
        }
        mesh.parts.replaceAll([LowLevelMesh.Part(indexCount: indices.count, topology: .triangle,
                                                 bounds: BoundingBox(min: lo, max: hi))])
        entity.isEnabled = true
    }
}

#endif
