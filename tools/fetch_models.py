#!/usr/bin/env python3
"""Download the two ONNX models Mask Bridge needs and verify them.

The models are too large for Git. They are published as assets of the
`models-v1` GitHub release and land in MaskBridge.lrplugin/backend/models/.
A file already present with the right SHA-256 is kept as is; a download is
written to a temporary file, checked, then moved into place.

    python tools/fetch_models.py            # download what is missing
    python tools/fetch_models.py --check    # verify only, download nothing

Standard library only. Set MASKBRIDGE_MODELS_URL (or --base-url) to use a mirror.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import ssl
import sys
import tempfile
import urllib.request
from pathlib import Path

DEFAULT_BASE_URL = "https://github.com/nicolasdiolez/mask-bridge/releases/download/models-v1/"

# name: (sha256, size in bytes). Must match MODEL_SHA256 in backend/cli.py.
MODELS = {
    "rfdetr_seg_medium.onnx": (
        "70aa3794bf5e1a74689a909dd98a5aff8b31f675b6716561117b88a3c1541f25",
        141_118_014,
    ),
    "birefnet_lite_fp16.onnx": (
        "c86fd67ea1b4706b70907109727f4eb9e7a6ff9696f1498ed37a62224f72c4b5",
        114_591_985,
    ),
}

ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = ROOT / "MaskBridge.lrplugin" / "backend" / "models"


def sha256_of(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def ssl_context() -> ssl.SSLContext:
    try:
        import certifi  # present in the locked build environment
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def download(url: str, dest: Path, expected_sha: str, expected_size: int) -> None:
    fd, tmp_name = tempfile.mkstemp(prefix=".download-", suffix=".tmp", dir=dest.parent)
    tmp = Path(tmp_name)
    digest = hashlib.sha256()
    received = 0
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "mask-bridge-fetch-models"})
        with os.fdopen(fd, "wb") as out, urllib.request.urlopen(
            request, timeout=120, context=ssl_context()
        ) as response:
            while chunk := response.read(1 << 20):
                out.write(chunk)
                digest.update(chunk)
                received += len(chunk)
                print(f"\r  {received / 1e6:7.1f} / {expected_size / 1e6:.1f} MB", end="", flush=True)
        print()
        if received != expected_size or digest.hexdigest() != expected_sha:
            raise RuntimeError(
                f"{dest.name}: got {received} bytes, sha256 {digest.hexdigest()}; "
                f"expected {expected_size} bytes, sha256 {expected_sha}"
            )
        os.replace(tmp, dest)
    finally:
        if tmp.exists():
            tmp.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="verify present models, download nothing")
    parser.add_argument("--base-url", default=os.environ.get("MASKBRIDGE_MODELS_URL", DEFAULT_BASE_URL))
    args = parser.parse_args()
    base_url = args.base_url if args.base_url.endswith("/") else args.base_url + "/"

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    failures = 0
    for name, (sha, size) in MODELS.items():
        dest = MODELS_DIR / name
        if dest.is_file() and dest.stat().st_size == size and sha256_of(dest) == sha:
            print(f"ok       {name}")
            continue
        if args.check:
            state = "wrong checksum" if dest.exists() else "missing"
            print(f"{state:8} {name}")
            failures += 1
            continue
        print(f"fetching {name}")
        try:
            download(base_url + name, dest, sha, size)
            print(f"ok       {name}")
        except Exception as exc:  # report every model, then fail
            print(f"failed   {name}: {exc}", file=sys.stderr)
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
