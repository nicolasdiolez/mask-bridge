#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
BUILD_PYTHON="${MASKBRIDGE_PYTHON:-.venv-release/bin/python}"
# Packaging verifies the existing engine. Build and sign are explicit earlier steps.
for argument in "$@"; do
    case "$argument" in
        --skip-build) ;;
        --candidate) exec "$BUILD_PYTHON" tools/release/release.py package --candidate ;;
        *) echo "Unknown argument: $argument" >&2; exit 1 ;;
    esac
done
exec "$BUILD_PYTHON" tools/release/release.py package
