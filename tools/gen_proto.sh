#!/usr/bin/env bash
# Generate Python and Swift bindings from the capture-bundle proto.
#
#   ./tools/gen_proto.sh
#
# Outputs:
#   packages/schemas/thegoodguest_schemas/capture_bundle_pb2.py     (Python)
#   packages/schemas/thegoodguest_schemas/capture_bundle_pb2.pyi    (Python stubs, if mypy-protobuf present)
#   ios/TheGoodGuestCapture/TheGoodGuestCapture/Generated/capture_bundle.pb.swift  (Swift, if protoc-gen-swift present)
#
# Tooling:
#   - protoc:           brew install protobuf   (libprotoc 35.0 or newer)
#   - Swift plugin:     brew install swift-protobuf
#   - Python stubs:     pip install mypy-protobuf
#
# Note the two version lines are different things: protoc reports libprotoc
# 35.0, while the generated Python declares "Protobuf Python Version: 7.35.0"
# and enforces it at import via ValidateProtobufRuntimeVersion. A runtime older
# than that fails at import, not at generation — which is the failure mode
# decision 0021 chased through two service images.
#
# Both outputs are committed. The script creates the Swift output directory on
# demand, so a fresh checkout regenerates without any setup step.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

PROTO_DIR="packages/schemas"
PROTO_FILES=("${PROTO_DIR}/capture_bundle.proto")

# Python out
PY_OUT="packages/schemas/thegoodguest_schemas"
mkdir -p "${PY_OUT}"

echo "=== Python ==="
PROTOC_PY_ARGS=(
    --proto_path="${PROTO_DIR}"
    --python_out="${PY_OUT}"
)
if command -v protoc-gen-mypy >/dev/null 2>&1; then
    PROTOC_PY_ARGS+=(--mypy_out="${PY_OUT}")
    echo "  (with mypy stubs)"
else
    echo "  (no mypy-protobuf; install via 'pip install mypy-protobuf' for .pyi stubs)"
fi
protoc "${PROTOC_PY_ARGS[@]}" "${PROTO_FILES[@]}"
echo "  -> ${PY_OUT}/capture_bundle_pb2.py"

# Swift out (best-effort; skipped if protoc-gen-swift is not installed)
SWIFT_OUT="ios/TheGoodGuestCapture/TheGoodGuestCapture/Generated"
echo "=== Swift ==="
if command -v protoc-gen-swift >/dev/null 2>&1; then
    mkdir -p "${SWIFT_OUT}"
    protoc \
        --proto_path="${PROTO_DIR}" \
        --swift_out="${SWIFT_OUT}" \
        --swift_opt=Visibility=Public \
        "${PROTO_FILES[@]}"
    echo "  -> ${SWIFT_OUT}/capture_bundle.pb.swift"
else
    echo "  (skipped: protoc-gen-swift not installed; 'brew install swift-protobuf')"
fi

echo "Done."
