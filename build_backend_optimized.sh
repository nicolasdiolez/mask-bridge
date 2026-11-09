#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
BUILD_PYTHON="${MASKBRIDGE_PYTHON:-.venv-release/bin/python}"
exec "$BUILD_PYTHON" tools/release/release.py build
