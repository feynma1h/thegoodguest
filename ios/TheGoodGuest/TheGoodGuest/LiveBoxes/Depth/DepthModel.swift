/// Finding, describing and running the depth models a build carries, for the
/// live boxes' depth sources — DEBUG-only (decision 0295).
///
/// THE CONTRACT. A depth model is a Core ML package named `depth_<name>`,
/// dropped into `LiveBoxes/Model/` (gitignored) like the detector export and
/// compiled into the bundle by whatever is there. It takes ONE colour image at
/// the fixed size its description gives, and returns ONE single-channel map —
/// a multi-array [1, 1, H, W] or [1, H, W] in Float16 or Float32, or a
/// greyscale image. Its user-defined metadata says what the map is:
///   • `depth.kind` — `disparity` (relative inverse depth: larger is nearer,
///     known only up to scale and shift), `depth` (relative depth: larger is
///     farther, up to scale) or `metric` (metres);
///   • `depth.name`, `depth.source`, `depth.license` — what the log shows and
///     the log records.
/// Everything is read from the model and nothing from its file name, with one
/// exception: a package without `depth.kind` is `disparity`, which is what
/// Apple's conversion of Depth Anything V2 is.
///
/// A MODEL'S OWN CONFIDENCE. A model may also return its own per-pixel
/// confidence, larger meaning surer, as a second single-channel output. Its
/// metadata then names both: `depth.output` the map, `depth.confidence` the
/// confidence. DA3 Small's export does.
///
/// The map covers the model's whole input at its own resolution: the centre of
/// map pixel (i, j) is input point ((i + ½)·W_in/W_map, (j + ½)·H_in/H_map).
///
/// Read by: LiveBoxesSession, DepthSource, LiveBoxesDepthTests, LiveBoxesModelTests.

#if DEBUG

import CoreML
import CoreVideo
import Foundation

/// What a depth model's map holds.
nonisolated enum DepthKind: String, Sendable, Codable, CaseIterable {
    /// Relative inverse depth: larger is nearer; true only up to scale and shift.
    case disparity
    /// Relative depth: larger is farther; true only up to scale.
    case depth
    /// Metres.
    case metric
}

nonisolated struct BundledDepthModel: Sendable, Equatable, Identifiable {
    /// The file stem, e.g. `depth_da2_small`: what the model is chosen by.
    let stem: String
    let url: URL
    var id: String { stem }
}

/// What a depth model says about itself.
nonisolated struct DepthModelInfo: Sendable, Equatable, Codable {
    static let kindKey = "depth.kind"
    static let nameKey = "depth.name"
    static let sourceKey = "depth.source"
    static let licenseKey = "depth.license"
    static let outputKey = "depth.output"
    static let confidenceKey = "depth.confidence"

    var name: String
    var kind: DepthKind
    var source: String?
    var license: String?

    /// From a model's user-defined metadata; nil when `depth.kind` names no
    /// kind. A model that carries no name is called by its file stem.
    static func parse(_ metadata: [String: String], stem: String) -> DepthModelInfo? {
        var kind = DepthKind.disparity
        if let raw = metadata[kindKey] {
            guard let named = DepthKind(rawValue: raw.trimmingCharacters(in: .whitespaces).lowercased()) else {
                return nil
            }
            kind = named
        }
        let name = metadata[nameKey].flatMap { $0.isEmpty ? nil : $0 } ?? stem
        return DepthModelInfo(name: name, kind: kind, source: metadata[sourceKey], license: metadata[licenseKey])
    }
}

nonisolated enum DepthCatalog {
    /// Depth models are recognised by this file-name prefix.
    static let prefix = "depth_"

    /// Compiled depth models in `bundle`, by stem.
    static func bundled(in bundle: Bundle = .main) -> [BundledDepthModel] {
        (bundle.urls(forResourcesWithExtension: "mlmodelc", subdirectory: nil) ?? [])
            .map { BundledDepthModel(stem: $0.deletingPathExtension().lastPathComponent, url: $0) }
            .filter { $0.stem.hasPrefix(prefix) }
            .sorted { $0.stem < $1.stem }
    }

    /// What `model` says about itself, read from its description without
    /// loading it for any compute unit: a model is described before it is chosen.
    static func describe(_ model: BundledDepthModel) async throws -> DepthModelInfo {
        let description = try await MLModelAsset(url: model.url).modelDescription
        let metadata = description.metadata[.creatorDefinedKey] as? [String: String] ?? [:]
        guard let info = DepthModelInfo.parse(metadata, stem: model.stem) else {
            throw DepthLoadError.unknownKind(metadata[DepthModelInfo.kindKey] ?? "")
        }
        return info
    }
}

nonisolated enum DepthLoadError: Error, Equatable, CustomStringConvertible {
    case unknownKind(String)
    case noImageInput
    case noSingleMap
    case mapUnreadable(String)

    var description: String {
        switch self {
        case .unknownKind(let kind): return "depth.kind '\(kind)' is not disparity, depth or metric"
        case .noImageInput:          return "the model has no image input of a fixed size"
        case .noSingleMap:           return "the model's outputs are not one map, or a map and its confidence"
        case .mapUnreadable(let why): return "the map could not be read: \(why)"
        }
    }
}

nonisolated enum DepthModelOutputs {
    /// Which of a model's single-channel outputs is the map, and which its own
    /// confidence: the ones its metadata names, else the only map there is.
    /// Nil when that names no output, or two, or leaves the map ambiguous.
    static func choose(maps: Set<String>, metadata: [String: String]) -> (map: String, confidence: String?)? {
        let confidence = metadata[DepthModelInfo.confidenceKey]
        if let confidence, !maps.contains(confidence) { return nil }
        let others = maps.subtracting([confidence].compactMap { $0 })
        guard let map = metadata[DepthModelInfo.outputKey] ?? (others.count == 1 ? others.first : nil),
              others.contains(map) else { return nil }
        return (map, confidence)
    }
}

/// One prediction: the map, and the model's own confidence when it has one.
nonisolated struct DepthPrediction: Sendable {
    let map: DepthModelMap
    let confidence: DepthModelMap?
}

/// One map a depth model returned: row-major, top row first.
nonisolated struct DepthModelMap: Sendable, Equatable {
    let width: Int
    let height: Int
    let values: [Float]

    init(width: Int, height: Int, values: [Float]) {
        precondition(values.count == width * height)
        self.width = width
        self.height = height
        self.values = values
    }

    /// A single-channel prediction as values: a multi-array whose leading
    /// dimensions are all 1, or a one-component pixel buffer.
    static func read(_ value: MLFeatureValue) throws -> DepthModelMap {
        if let array = value.multiArrayValue {
            let shape = array.shape.map(\.intValue)
            guard shape.count >= 2, shape.dropLast(2).allSatisfy({ $0 == 1 }) else {
                throw DepthLoadError.mapUnreadable("shape \(shape)")
            }
            return DepthModelMap(width: shape[shape.count - 1], height: shape[shape.count - 2],
                                 values: DetectorArrays.floats(array))
        }
        if let buffer = value.imageBufferValue { return try read(buffer) }
        throw DepthLoadError.noSingleMap
    }

    /// A one-component pixel buffer's values, whatever its row padding.
    static func read(_ buffer: CVPixelBuffer) throws -> DepthModelMap {
        let w = CVPixelBufferGetWidth(buffer), h = CVPixelBufferGetHeight(buffer)
        let format = CVPixelBufferGetPixelFormatType(buffer)
        CVPixelBufferLockBaseAddress(buffer, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(buffer, .readOnly) }
        guard let base = CVPixelBufferGetBaseAddress(buffer) else { throw DepthLoadError.mapUnreadable("no pixels") }
        let stride = CVPixelBufferGetBytesPerRow(buffer)
        var values = [Float](repeating: 0, count: w * h)
        func each(_ read: (UnsafeRawPointer, Int) -> Float) {
            for y in 0..<h {
                let row = UnsafeRawPointer(base.advanced(by: y * stride))
                for x in 0..<w { values[y * w + x] = read(row, x) }
            }
        }
        switch format {
        case kCVPixelFormatType_OneComponent8:
            each { Float($0.load(fromByteOffset: $1, as: UInt8.self)) }
        case kCVPixelFormatType_OneComponent16Half, kCVPixelFormatType_DepthFloat16,
             kCVPixelFormatType_DisparityFloat16:
            each { Float($0.loadUnaligned(fromByteOffset: $1 * 2, as: Float16.self)) }
        case kCVPixelFormatType_OneComponent32Float, kCVPixelFormatType_DepthFloat32,
             kCVPixelFormatType_DisparityFloat32:
            each { $0.loadUnaligned(fromByteOffset: $1 * 4, as: Float.self) }
        default:
            throw DepthLoadError.mapUnreadable("pixel format \(format)")
        }
        return DepthModelMap(width: w, height: h, values: values)
    }
}

/// A loaded depth model. Used from one queue.
nonisolated final class LoadedDepthModel: @unchecked Sendable {
    let stem: String
    let info: DepthModelInfo
    let model: MLModel
    let compute: ComputeChoice
    let inputName: String
    let inputWidth: Int
    let inputHeight: Int
    let outputName: String
    /// The output holding the model's own confidence, when it has one.
    let confidenceName: String?

    private init(stem: String, info: DepthModelInfo, model: MLModel, compute: ComputeChoice, inputName: String,
                 inputWidth: Int, inputHeight: Int, outputName: String, confidenceName: String?) {
        self.stem = stem
        self.info = info
        self.model = model
        self.compute = compute
        self.inputName = inputName
        self.inputWidth = inputWidth
        self.inputHeight = inputHeight
        self.outputName = outputName
        self.confidenceName = confidenceName
    }

    static func load(_ bundled: BundledDepthModel, compute: ComputeChoice) throws -> LoadedDepthModel {
        let configuration = MLModelConfiguration()
        configuration.computeUnits = compute.units
        let model = try MLModel(contentsOf: bundled.url, configuration: configuration)
        let description = model.modelDescription
        let metadata = description.metadata[.creatorDefinedKey] as? [String: String] ?? [:]
        guard let info = DepthModelInfo.parse(metadata, stem: bundled.stem) else {
            throw DepthLoadError.unknownKind(metadata[DepthModelInfo.kindKey] ?? "")
        }
        guard let input = description.inputDescriptionsByName.first(where: { $0.value.type == .image }),
              let constraint = input.value.imageConstraint, constraint.pixelsWide > 0, constraint.pixelsHigh > 0
        else { throw DepthLoadError.noImageInput }
        let maps = description.outputDescriptionsByName.filter { _, output in
            switch output.type {
            case .multiArray:
                let shape = output.multiArrayConstraint?.shape.map(\.intValue) ?? []
                return shape.isEmpty || (shape.count >= 2 && shape.dropLast(2).allSatisfy { $0 == 1 })
            case .image:
                return output.imageConstraint.map { $0.pixelFormatType != kCVPixelFormatType_32BGRA
                    && $0.pixelFormatType != kCVPixelFormatType_32ARGB } ?? false
            default:
                return false
            }
        }
        guard let outputs = DepthModelOutputs.choose(maps: Set(maps.keys), metadata: metadata)
        else { throw DepthLoadError.noSingleMap }
        return LoadedDepthModel(stem: bundled.stem, info: info, model: model, compute: compute, inputName: input.key,
                                inputWidth: constraint.pixelsWide, inputHeight: constraint.pixelsHigh,
                                outputName: outputs.map, confidenceName: outputs.confidence)
    }

    /// The map for one rendered input, and the model's own confidence.
    func predict(_ input: CVPixelBuffer) throws -> DepthPrediction {
        let features = try MLDictionaryFeatureProvider(dictionary: [inputName: MLFeatureValue(pixelBuffer: input)])
        let output = try model.prediction(from: features)
        guard let value = output.featureValue(for: outputName) else { throw DepthLoadError.noSingleMap }
        var confidence: DepthModelMap?
        if let confidenceName {
            guard let own = output.featureValue(for: confidenceName) else { throw DepthLoadError.noSingleMap }
            confidence = try DepthModelMap.read(own)
        }
        return DepthPrediction(map: try DepthModelMap.read(value), confidence: confidence)
    }
}

#endif
