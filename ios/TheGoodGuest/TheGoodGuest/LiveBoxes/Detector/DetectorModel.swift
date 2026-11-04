/// Finding and loading the detector export at run time — DEBUG-only
/// (decision 0295).
///
/// THE MODEL IS NOT IN THE REPOSITORY. Its code and weights are AGPL-3.0 and
/// this repository is public and all-rights-reserved, so the export lives
/// outside git and is dropped into `LiveBoxes/Model/` (gitignored) before a
/// build; Xcode compiles whatever is there into the app bundle. Everything here
/// therefore treats the model as OPTIONAL: it is discovered by file name in the
/// bundle and loaded by URL, never through the class Xcode would generate, so a
/// checkout without the file builds, tests, and runs live boxes with the
/// detector reported missing.
///
/// Outputs are identified by RANK (3-D detections, 4-D prototypes) rather than
/// by name, because the converter names them after graph nodes that change
/// between exports.
///
/// Read by: LiveBoxesSession, DetectorPipeline, LiveBoxesModelTests, LiveBoxesRuntimeTests.

#if DEBUG

import CoreML
import Foundation

nonisolated struct BundledDetector: Sendable, Equatable, Identifiable {
    /// The file stem, e.g. `yoloe26s_pf_app_640`.
    let name: String
    let url: URL
    var id: String { name }
}

nonisolated enum DetectorCatalog {
    /// Exports are recognised by this file-name prefix.
    static let prefix = "yoloe"
    /// The export live boxes opens with when it is present.
    static let preferred = "yoloe26s_pf_app_640"

    /// Compiled detector models in `bundle`, by name.
    static func bundled(in bundle: Bundle = .main) -> [BundledDetector] {
        (bundle.urls(forResourcesWithExtension: "mlmodelc", subdirectory: nil) ?? [])
            .map { BundledDetector(name: $0.deletingPathExtension().lastPathComponent, url: $0) }
            .filter { $0.name.hasPrefix(prefix) }
            .sorted { $0.name < $1.name }
    }

    /// The model to open: the requested one if present, then the preferred
    /// one, then the first found.
    static func choose(_ available: [BundledDetector], requested: String?) -> BundledDetector? {
        available.first { $0.name == requested }
            ?? available.first { $0.name == preferred }
            ?? available.first
    }
}

/// Where Core ML may run the detector. Named for what a reader of the log
/// needs to know, not for the enum's spelling.
nonisolated enum ComputeChoice: String, CaseIterable, Sendable, Codable {
    case all
    case neuralEngine
    case gpu
    case cpu

    var units: MLComputeUnits {
        switch self {
        case .all:          return .all
        case .neuralEngine: return .cpuAndNeuralEngine
        case .gpu:          return .cpuAndGPU
        case .cpu:          return .cpuOnly
        }
    }

    var title: String {
        switch self {
        case .all:          return "Any (Core ML decides)"
        case .neuralEngine: return "Neural Engine"
        case .gpu:          return "GPU"
        case .cpu:          return "CPU"
        }
    }
}

nonisolated enum DetectorLoadError: Error, Equatable, CustomStringConvertible {
    case metadataUnreadable
    case notEndToEnd
    case inputUnrecognised
    case outputsUnrecognised

    var description: String {
        switch self {
        case .metadataUnreadable:  return "the model carries no class names or input size"
        case .notEndToEnd:         return "the export is not the end-to-end head"
        case .inputUnrecognised:   return "the model has no image input"
        case .outputsUnrecognised: return "the model's outputs are not detections and prototypes"
        }
    }
}

/// A loaded export and what it says about itself. Used from one queue.
nonisolated final class LoadedDetector: @unchecked Sendable {
    let name: String
    let model: MLModel
    let info: DetectorModelInfo
    let compute: ComputeChoice
    let inputName: String
    let detectionsName: String
    let prototypesName: String

    private init(name: String, model: MLModel, info: DetectorModelInfo, compute: ComputeChoice,
                 inputName: String, detectionsName: String, prototypesName: String) {
        self.name = name
        self.model = model
        self.info = info
        self.compute = compute
        self.inputName = inputName
        self.detectionsName = detectionsName
        self.prototypesName = prototypesName
    }

    static func load(_ bundled: BundledDetector, compute: ComputeChoice) throws -> LoadedDetector {
        let configuration = MLModelConfiguration()
        configuration.computeUnits = compute.units
        let model = try MLModel(contentsOf: bundled.url, configuration: configuration)
        let description = model.modelDescription
        let metadata = description.metadata[.creatorDefinedKey] as? [String: String] ?? [:]
        guard let info = DetectorModelInfo.parse(metadata) else { throw DetectorLoadError.metadataUnreadable }
        guard info.endToEnd else { throw DetectorLoadError.notEndToEnd }
        guard let input = description.inputDescriptionsByName.first(where: { $0.value.type == .image })?.key
        else { throw DetectorLoadError.inputUnrecognised }
        let ranks = description.outputDescriptionsByName.mapValues {
            $0.multiArrayConstraint?.shape.count ?? 0
        }
        guard let detections = ranks.first(where: { $0.value == 3 })?.key,
              let prototypes = ranks.first(where: { $0.value == 4 })?.key
        else { throw DetectorLoadError.outputsUnrecognised }
        return LoadedDetector(name: bundled.name, model: model, info: info, compute: compute,
                              inputName: input, detectionsName: detections, prototypesName: prototypes)
    }
}

nonisolated enum DetectorArrays {
    /// A multi-array's values as Float in row-major index order, whatever its
    /// storage type and strides.
    ///
    /// STORAGE ORDER IS NOT INDEX ORDER. An output the Neural Engine hands
    /// back can be padded — its strides are not the contiguous ones — and a
    /// copy in storage order then shifts every row after the first: on the
    /// phone that read box coordinates as scores. Every element is read at
    /// its own offset, Σ index·stride.
    static func floats(_ array: MLMultiArray) -> [Float] {
        let shape = array.shape.map(\.intValue)
        let strides = array.strides.map(\.intValue)
        switch array.dataType {
        case .float32: return read(array, Float.self, shape: shape, strides: strides) { $0 }
        case .float16: return read(array, Float16.self, shape: shape, strides: strides) { Float($0) }
        case .double: return read(array, Double.self, shape: shape, strides: strides) { Float($0) }
        default: return (0..<array.count).map { array[$0].floatValue }
        }
    }

    /// The contiguous strides of `shape`: each dimension's step is the product
    /// of the sizes after it.
    static func contiguousStrides(_ shape: [Int]) -> [Int] {
        var strides = [Int](repeating: 1, count: shape.count)
        for d in stride(from: shape.count - 2, through: 0, by: -1) { strides[d] = strides[d + 1] * shape[d + 1] }
        return strides
    }

    /// "[1, 300, 38] strides [11400, 38, 1] float32" — what the log records of
    /// an output's layout.
    static func layout(_ array: MLMultiArray) -> String {
        let type: String
        switch array.dataType {
        case .float32: type = "float32"
        case .float16: type = "float16"
        case .double: type = "double"
        default: type = "type \(array.dataType.rawValue)"
        }
        return "\(array.shape.map(\.intValue)) strides \(array.strides.map(\.intValue)) \(type)"
    }

    private static func read<T: MLShapedArrayScalar>(_ array: MLMultiArray, _ type: T.Type, shape: [Int], strides: [Int],
                                _ convert: (T) -> Float) -> [Float] {
        let n = array.count
        let lastOffset = zip(shape, strides).reduce(0) { $0 + ($1.0 - 1) * $1.1 }
        return array.withUnsafeBufferPointer(ofType: T.self) { buffer in
            if strides == contiguousStrides(shape), buffer.count >= n { return buffer.prefix(n).map(convert) }
            guard lastOffset < buffer.count, strides.allSatisfy({ $0 > 0 }) else {
                // Storage that does not cover its own strides: Core ML's indexed access.
                return (0..<n).map { array[$0].floatValue }
            }
            var out = [Float](repeating: 0, count: n)
            var index = [Int](repeating: 0, count: shape.count)
            for i in 0..<n {
                var offset = 0
                for d in shape.indices { offset += index[d] * strides[d] }
                out[i] = convert(buffer[offset])
                var d = shape.count - 1
                while d >= 0 {
                    index[d] += 1
                    if index[d] < shape[d] { break }
                    index[d] = 0
                    d -= 1
                }
            }
            return out
        }
    }
}

#endif
