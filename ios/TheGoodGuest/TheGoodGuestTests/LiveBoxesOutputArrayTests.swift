/// Pins for reading the detector's output arrays: every element at its own
/// stride offset, because an array the Neural Engine returns can be padded, and
/// a copy in storage order shifts every row after the first. On the phone that
/// read box coordinates as scores (a SPEAKER at 285.75).

import CoreML
import XCTest
@testable import TheGoodGuest

final class LiveBoxesOutputArrayTests: XCTestCase {

    /// A 1×3×4 array whose rows are padded to 6 in storage: element (0, r, c)
    /// holds r·10 + c, and every padding slot holds -999.
    private func paddedRows<T: BinaryFloatingPoint>(_ type: T.Type, dataType: MLMultiArrayDataType) throws -> MLMultiArray {
        let storage = UnsafeMutablePointer<T>.allocate(capacity: 18)
        for k in 0..<18 { storage[k] = -999 }
        for r in 0..<3 { for c in 0..<4 { storage[r * 6 + c] = T(r * 10 + c) } }
        return try MLMultiArray(dataPointer: storage, shape: [1, 3, 4], dataType: dataType, strides: [18, 6, 1],
                                deallocator: { $0.deallocate() })
    }

    func test_paddedOutputs_areReadByStride_notInStorageOrder() throws {
        let expected: [Float] = [0, 1, 2, 3, 10, 11, 12, 13, 20, 21, 22, 23]
        XCTAssertEqual(DetectorArrays.floats(try paddedRows(Float.self, dataType: .float32)), expected)
        XCTAssertEqual(DetectorArrays.floats(try paddedRows(Float16.self, dataType: .float16)), expected)
        XCTAssertEqual(DetectorArrays.floats(try paddedRows(Double.self, dataType: .double)), expected)
    }

    func test_contiguousOutputs_readStraightThrough() throws {
        let array = try MLMultiArray(shape: [1, 2, 3], dataType: .float32)
        for k in 0..<6 { array[k] = NSNumber(value: Float(k) * 0.5) }
        XCTAssertEqual(array.strides.map(\.intValue), DetectorArrays.contiguousStrides([1, 2, 3]))
        XCTAssertEqual(DetectorArrays.floats(array), [0, 0.5, 1, 1.5, 2, 2.5])
    }

    func test_layout_namesShapeStridesAndType() throws {
        XCTAssertEqual(DetectorArrays.layout(try paddedRows(Float.self, dataType: .float32)),
                       "[1, 3, 4] strides [18, 6, 1] float32")
        XCTAssertEqual(DetectorArrays.contiguousStrides([1, 32, 160, 160]), [819_200, 25_600, 160, 1])
    }
}
