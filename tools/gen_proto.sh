#!/usr/bin/env bash
# Generate Python and Swift bindings from the capture-bundle proto.
#
#   ./tools/gen_proto.sh
#
# Outputs:
#   packages/schemas/roomstudio_schemas/capture_bundle_pb2.py     (Python)
#   packages/schemas/roomstudio_schemas/capture_bundle_pb2.pyi    (Python stubs, if mypy-protobuf present)
#   ios/RoomStudioCapture/Generated/CaptureBundle.pb.swift        (Swift, if protoc-gen-swift present)
#
# Tooling:
#   - protoc (3.21+):   brew install protobuf
#   - Swift plugin:     brew install swift-protobuf
#   - Python stubs:     pip install mypy-protobuf
#
# The Swift output dir doesn't exist yet (no iOS project yet); the script
# creates it on demand so the iOS app can drop in alongside this without
# any further setup.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

PROTO_DIR="packages/schemas"
PROTO_FILES=("${PROTO_DIR}/capture_bundle.proto")

# Python out
PY_OUT="packages/schemas/roomstudio_schemas"
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

# Swift out (best-effort; the iOS project consumes this when it exists)
SWIFT_OUT="ios/RoomStudioCapture/Generated"
echo "=== Swift ==="
if command -v protoc-gen-swift >/dev/null 2>&1; then
    mkdir -p "${SWIFT_OUT}"
    protoc \
        --proto_path="${PROTO_DIR}" \
        --swift_out="${SWIFT_OUT}" \
        --swift_opt=Visibility=Public \
        "${PROTO_FILES[@]}"
    echo "  -> ${SWIFT_OUT}/CaptureBundle.pb.swift"
else
    echo "  (skipped: protoc-gen-swift not installed; 'brew install swift-protobuf')"
fi

echo "Done."
