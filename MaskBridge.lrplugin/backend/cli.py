from atomic_io import atomic_json, distinct_output
"""
Mask Bridge CLI - Batch Mode Support
Supports both single image and batch processing for maximum speed.
Now includes embedded HTTP server for fast repeated inference.
"""
import argparse
import logging
import sys
import os
import json
import traceback
import time
import urllib.request
import ssl
import hashlib
import threading
import socket
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

sys.path.append(os.path.dirname(__file__))

# Shared, side-effect-free validation helpers (path safety + manifest typing)
from validation import validate_path, normalize_manifest

# Version
VERSION = "1.2.0"

# ============================================================================
# Model Download (integrated for standalone binary)
# ============================================================================

MODELS = {
    # RF-DETR Segmentation (Unified Model)
    # Source: PierreMarieCurie/rf-detr-onnx (HuggingFace)
    # Model: Medium - 432x432 input (Apache 2.0)
    "rfdetr_seg_medium.onnx": "https://huggingface.co/PierreMarieCurie/rf-detr-onnx/resolve/main/rfdetr-seg-medium.onnx",
}

# Expected file sizes (minimum bytes) for quick integrity check
# Optional fine-detail model (BiRefNet). Bundled with the plugin package; it
# has no public download URL (custom fp16 conversion), so it is deliberately
# NOT in MODELS — when missing, Fine detail mode falls back to the standard
# mask and the remedy is reinstalling Mask Bridge, not --download-models.
BIREFNET_MODEL = "birefnet_lite_fp16.onnx"

MODEL_MIN_SIZES = {
    "rfdetr_seg_medium.onnx": 90_000_000,   # ~100MB (Validation estimate)
    "birefnet_lite_fp16.onnx": 100_000_000, # fp16 ~114MB
}


MODEL_SHA256 = {
    "rfdetr_seg_medium.onnx": "70aa3794bf5e1a74689a909dd98a5aff8b31f675b6716561117b88a3c1541f25",
    "birefnet_lite_fp16.onnx": "c86fd67ea1b4706b70907109727f4eb9e7a6ff9696f1498ed37a62224f72c4b5",
}


def file_sha256(path):
    with open(path, "rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def format_size(size_bytes):
    """Format bytes to human readable string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"


def log_message(log_file, message, progress=None):
    """Write message to both stdout and log file."""
    if progress is not None:
        # Special progress format for Lua parser
        print(f"[PROGRESS] {int(progress)}%", flush=True)
    else:
        print(message, flush=True)
        
    if log_file:
        try:
            if progress is not None:
                log_file.write(f"[PROGRESS] {int(progress)}%\n")
            else:
                log_file.write(message + "\n")
            log_file.flush()
        except Exception:
            pass


def download_file(url: str, dest: str, log_file=None) -> bool:
    """Download file with progress using only standard library."""
    log_message(log_file, f"Downloading {os.path.basename(dest)}...")
    log_message(log_file, f"  URL: {url}")
    log_message(log_file, f"  Dest: {dest}")
    
    import tempfile
    destination = dest
    parent = os.path.dirname(os.path.abspath(destination))
    os.makedirs(parent, exist_ok=True)
    fd, dest = tempfile.mkstemp(prefix=".maskbridge-download-", suffix=".tmp", dir=parent)
    os.close(fd)

    # SSL Context setup with multiple fallback strategies
    ssl_context = None
    ca_bundle_path = None
    
    # Strategy 1: Check for bundled cacert.pem in PyInstaller frozen exe
    if getattr(sys, 'frozen', False):
        # Running as compiled exe
        bundle_dir = sys._MEIPASS if hasattr(sys, '_MEIPASS') else os.path.dirname(sys.executable)
        possible_paths = [
            os.path.join(bundle_dir, 'certifi', 'cacert.pem'),
            os.path.join(bundle_dir, 'cacert.pem'),
            os.path.join(os.path.dirname(sys.executable), 'cacert.pem'),
        ]
        for path in possible_paths:
            if os.path.exists(path):
                ca_bundle_path = path
                log_message(log_file, f"  Using frozen CA bundle: {path}")
                break
    
    # Strategy 2: Try certifi package
    if not ca_bundle_path:
        try:
            import certifi
            ca_bundle_path = certifi.where()
            log_message(log_file, f"  Using certifi CA bundle: {ca_bundle_path}")
        except ImportError:
            log_message(log_file, "  certifi not found")
    
    # Create SSL context with our CA bundle
    if ca_bundle_path and os.path.exists(ca_bundle_path):
        try:
            ssl_context = ssl.create_default_context(cafile=ca_bundle_path)
        except Exception as e:
            log_message(log_file, f"  Warning: Could not use CA bundle: {e}")
    
    # Strategy 3: System default context
    if not ssl_context:
        log_message(log_file, "  Trying system SSL certificates...")
        try:
            ssl_context = ssl.create_default_context()
        except Exception as e:
            log_message(log_file, f"  Warning: System SSL failed: {e}")

    # If no SSL context could be created, fail with a clear error
    if not ssl_context:
        log_message(log_file, "  ERROR: No valid SSL context available. Please install certifi (pip install certifi) or check system certificates.")
        return False
    
    try:
        request = urllib.request.Request(
            url,
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        )
        
        # Open connection
        if ssl_context:
             response = urllib.request.urlopen(request, timeout=120, context=ssl_context)
        else:
             response = urllib.request.urlopen(request, timeout=120)
        
        total_size = int(response.headers.get('content-length', 0))
        log_message(log_file, f"  Size: {format_size(total_size)}")
        
        downloaded = 0
        block_size = 1024 * 1024  # 1 MB chunks
        
        # Ensure parent directory exists
        parent_dir = os.path.dirname(dest)
        if parent_dir and not os.path.exists(parent_dir):
            os.makedirs(parent_dir, exist_ok=True)
        
        with open(dest, 'wb') as f:
            while True:
                chunk = response.read(block_size)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                
                if total_size > 0:
                    pct = (downloaded / total_size) * 100
                    # Log progress for Lua to pick up
                    log_message(log_file, f"  {format_size(downloaded)} / {format_size(total_size)} ({pct:.0f}%)", progress=pct)
        
        response.close()
        
        name = os.path.basename(destination)
        expected = MODEL_SHA256.get(name)
        if expected is None or file_sha256(dest) != expected:
            raise ValueError("Downloaded model SHA-256 does not match this release")
        os.replace(dest, destination)
        final_size = os.path.getsize(destination)
        log_message(log_file, f"  OK: {os.path.basename(dest)} ({format_size(final_size)})")
        return True
        
    except Exception as e:
        error_msg = f"  ERROR: {type(e).__name__}: {e}"
        log_message(log_file, error_msg)
        if os.path.exists(dest):
            try:
                os.remove(dest)
            except OSError:
                pass
        return False


def download_models(model_dir: str) -> bool:
    """Download all AI models to the specified directory."""
    # Create model directory
    try:
        os.makedirs(model_dir, exist_ok=True)
    except Exception as e:
        logger.error(f"Cannot create directory {model_dir}: {e}")
        return False
    
    # Create log file for debugging
    log_path = os.path.join(model_dir, "maskbridge_download.log")
    log_file = None
    try:
        log_file = open(log_path, 'w', encoding='utf-8')
    except Exception:
        pass  # Continue without log file
    
    log_message(log_file, "=" * 50)
    log_message(log_file, "Mask Bridge - AI Model Downloader")
    log_message(log_file, "=" * 50)
    log_message(log_file, f"Target: {model_dir}")
    log_message(log_file, f"Python: {sys.executable}")
    log_message(log_file, f"Platform: {sys.platform}")
    log_message(log_file, f"Working dir: {os.getcwd()}")
    log_message(log_file, "")
    
    success = True
    for filename, url in MODELS.items():
        dest = os.path.join(model_dir, filename)
        
        if verify_model(dest, filename)[0]:
            log_message(log_file, f"OK (exists): {filename} ({format_size(os.path.getsize(dest))})")
            continue
        
        if not download_file(url, dest, log_file):
            success = False
    
    log_message(log_file, "")
    if success:
        log_message(log_file, "SUCCESS: All AI models ready!")
        sentinel_path = os.path.join(model_dir, "models_installed.txt")
        try:
            with open(sentinel_path, "w", encoding="utf-8") as f:
                f.write("Mask Bridge — RF-DETR Medium (rfdetr_seg_medium.onnx) "
                        "+ BiRefNet_lite (birefnet_lite_fp16.onnx) installed\n")
        except Exception as e:
            log_message(log_file, f"Warning: Could not write sentinel file: {e}")
    else:
        log_message(log_file, "ERROR: Some downloads failed. Check log above.")
    
    if log_file:
        log_file.close()
    
    return success


def verify_model(model_path: str, model_name: str) -> tuple:
    """Verify a model file exists and has expected minimum size.
    Returns (ok: bool, message: str)
    """
    if not os.path.exists(model_path):
        return False, f"NOT FOUND: {model_name}"
    
    size = os.path.getsize(model_path)
    min_size = MODEL_MIN_SIZES.get(model_name, 0)
    
    if size < min_size:
        return False, f"CORRUPT: {model_name} ({format_size(size)} < {format_size(min_size)} expected)"
    
    expected = MODEL_SHA256.get(model_name)
    if expected is None or file_sha256(model_path) != expected:
        return False, f"CORRUPT: {model_name} (SHA-256 mismatch)"
    return True, f"OK: {model_name} ({format_size(size)})"


def run_healthcheck(model_dir: str) -> bool:
    """Run comprehensive health check and print diagnostics."""
    print(f"\n{'='*50}")
    print(f"Mask Bridge v{VERSION} - Health Check")
    print(f"{'='*50}\n")
    
    # System info
    print(f"Python: {sys.version}")
    print(f"Platform: {sys.platform}")
    print(f"Model dir: {model_dir}\n")
    
    # Check ONNX Runtime
    try:
        import onnxruntime as ort
        providers = ort.get_available_providers()
        print(f"ONNX Runtime: {ort.__version__}")
        print(f"Available providers: {', '.join(providers)}")
        # Report what the engine will ACTUALLY use, not what the machine merely
        # offers. The old line advertised "GPU acceleration: Available" whenever
        # CoreML existed, which sent support chasing an accelerator we
        # deliberately do not use (it measured 1.8x slower on RF-DETR).
        from inference_engine import _providers, _intra_op_threads
        active = _providers()
        print(f"In use: {', '.join(active)} | {_intra_op_threads()} intra-op threads")
        if 'CoreMLExecutionProvider' in active:
            print("  CoreML forced via MASKBRIDGE_ORT_PROVIDERS (not the default)")
        else:
            print("  CPU by design: CoreML refuses RF-DETR's decoder and measured slower")
        print()
    except ImportError:
        print("ONNX Runtime: [X] NOT INSTALLED")
        print("  Run: pip install onnxruntime\n")
        return False
    
    # Check models
    print("Models:")
    all_ok = True
    for model_name in MODELS.keys():
        model_path = os.path.join(model_dir, model_name)
        ok, msg = verify_model(model_path, model_name)
        print(f"  {msg}")
        if not ok:
            all_ok = False

    # Optional fine-detail model: report it, but don't fail the check and
    # don't point at --download-models (which cannot restore it).
    ok, msg = verify_model(os.path.join(model_dir, BIREFNET_MODEL), BIREFNET_MODEL)
    if ok:
        print(f"  {msg}")
    else:
        print(f"  {msg} (optional: Fine detail mode falls back to the "
              f"standard mask - reinstall Mask Bridge to restore)")

    print()
    if all_ok:
        print("[OK] All checks passed - ready to use!")
    else:
        print("[X] Issues detected - run: --download-models")
    
    return all_ok


# ============================================================================
# Image Processing
# ============================================================================

def process_single(args):
    """Process a single image."""
    from inference_engine import get_engine

    # Path safety validation (reject null bytes / protected system dirs)
    try:
        validate_path(args.image, 'image')
        validate_path(args.output, 'output')
        validate_path(args.model_dir, 'model_dir')
    except ValueError as e:
        logger.error(f"Invalid path: {e}")
        return False

    engine = get_engine(args.model_dir)

    # Parse exclude classes if provided
    exclude_classes = None
    if hasattr(args, 'exclude') and args.exclude:
        exclude_classes = [c.strip().lower() for c in args.exclude.split(",") if c.strip()]
    
    engine.process_image(
        image_path=args.image,
        output_path=args.output,
        prompts=args.prompts.split(","),
        invert=args.invert,
        threshold=args.threshold,
        smoothing=args.smoothing,
        # Product default is the fast hard mask: guided-filter refinement is an
        # explicit opt-in (--edge-refine); --no-edge-refine is kept for
        # backward compatibility and still wins if both are passed.
        edge_refine=args.edge_refine and not args.no_edge_refine,
        birefnet_refine=getattr(args, 'birefnet_refine', False),
        exclude_classes=exclude_classes,
    )

    # Generate comparison image if requested
    if args.comparison and os.path.exists(args.output):
        comparison_path = args.output.replace('.png', '_overlay.jpg')
        engine.create_comparison_image(args.image, args.output, comparison_path)
        logger.info(f"COMPARISON: {comparison_path}")
    
    return os.path.exists(args.output)


def process_batch(args):
    """Process multiple images from a JSON manifest file.
    
    Manifest format:
    {
        "prompts": ["person", "car"],
        "invert": false,
        "threshold": 0.35,
        "smoothing": 5,
        "images": [
            {"input": "/path/to/image.jpg", "output": "/path/to/mask.png"},
            ...
        ]
    }
    """
    from inference_engine import get_engine

    try:
        validate_path(args.batch, 'batch')
        with open(args.batch, 'r', encoding='utf-8') as f:
            manifest = json.load(f)
        cfg = normalize_manifest(manifest)
    except (ValueError, OSError) as e:
        # Malformed JSON, invalid manifest field types, unsafe path, or unreadable file
        logger.error(f"Invalid manifest: {e}")
        return False

    prompts = cfg["prompts"]
    invert = cfg["invert"]
    threshold = cfg["threshold"]
    smoothing = cfg["smoothing"]
    exclude_str = cfg["exclude"]
    images = cfg["images"]
    edge_refine = cfg["edge_refine"]
    birefnet_refine = cfg["birefnet_refine"]

    # Parse exclude classes
    exclude_classes = []
    if exclude_str:
        exclude_classes = [c.strip().lower() for c in exclude_str.split(",") if c.strip()]
    
    if not images:
        logger.warning("No images in manifest")
        return False
    
    # Load engine ONCE
    engine = get_engine(args.model_dir)
    
    results = {"success": 0, "failed": 0, "details": []}
    total = len(images)
    
    logger.info(f"Processing {total} images...")
    start_time = time.time()
    
    for i, item in enumerate(images, 1):
        input_path = item.get("input")
        output_path = item.get("output")
        
        if not input_path or not output_path:
            results["failed"] += 1
            results["details"].append({"input": input_path, "status": "error", "message": "Missing path"})
            continue

        try:
            validate_path(input_path, "batch item input")
            validate_path(output_path, "batch item output")
        except ValueError as e:
            results["failed"] += 1
            results["details"].append({"input": input_path, "status": "error", "message": f"Invalid path: {e}"})
            logger.warning(f"  [{i}/{total}] REJECTED path for {input_path}: {e}")
            continue
        
        try:
            img_start = time.time()
            engine.process_image(
                image_path=input_path,
                output_path=output_path,
                prompts=prompts,
                invert=invert,
                threshold=threshold,
                smoothing=smoothing,
                exclude_classes=exclude_classes,
                edge_refine=edge_refine,
                birefnet_refine=birefnet_refine,
            )

            if os.path.exists(output_path):
                elapsed = time.time() - img_start
                results["success"] += 1
                results["details"].append({"input": input_path, "output": output_path, "status": "ok", "time": round(elapsed, 2)})
                logger.info(f"  [{i}/{total}] OK {os.path.basename(input_path)} ({elapsed:.1f}s)")
            else:
                results["failed"] += 1
                results["details"].append({"input": input_path, "status": "error", "message": "Output not created"})
                logger.warning(f"  [{i}/{total}] FAIL {os.path.basename(input_path)}")

        except Exception as e:
            results["failed"] += 1
            results["details"].append({"input": input_path, "status": "error", "message": str(e)})
            logger.error(f"  [{i}/{total}] FAIL {os.path.basename(input_path)}: {e}")
    
    total_time = time.time() - start_time
    avg_time = total_time / total if total > 0 else 0
    
    logger.info(f"Batch complete: {results['success']}/{total} success")
    logger.info(f"Total time: {total_time:.1f}s ({avg_time:.1f}s/image)")
    
    # Write results to manifest path with .result.json suffix
    result_path = os.path.splitext(args.batch)[0] + ".result.json"
    distinct_output(result_path, args.batch, *(entry['input'] for entry in images))
    atomic_json(result_path, results)
    logger.info(f"Results saved to: {result_path}")
    
    sys.exit(0 if results["failed"] == 0 else 1)


# ============================================================================
# Detached server launch (Windows plugin launcher)
# ============================================================================

def spawn_server(model_dir, state_dir, popen=None):
    """Start ``--server --preload`` as a detached process and return at once.

    The Lightroom plugin on Windows runs a small .cmd file that calls the
    engine with ``--spawn-server``; the engine itself then creates the
    server process. No shell and no other program is involved, so user paths
    (accents, CJK, ``%``, ``!``, ``&``) reach CreateProcessW unchanged, and
    the server gets no console window. Returns the process exit code.
    """
    import subprocess
    from runtime_paths import ensure_private_directory

    popen = popen or subprocess.Popen
    if not model_dir or not os.path.isdir(model_dir):
        print(f"Mask Bridge: model directory not found: {model_dir}", file=sys.stderr)
        return 2
    if not state_dir:
        print("Mask Bridge: --spawn-server requires --state-dir", file=sys.stderr)
        return 2
    try:
        # Same private directory the server would create (Windows ACL, no
        # junction): a failure is reported here rather than by a silent child.
        state_dir = ensure_private_directory(os.path.abspath(state_dir))
    except OSError as exc:
        print(f"Mask Bridge: cannot use state directory {state_dir}: {exc}", file=sys.stderr)
        return 3
    model_dir = os.path.abspath(model_dir)
    if getattr(sys, 'frozen', False):
        command = [sys.executable]
    else:
        command = [sys.executable, os.path.abspath(__file__)]
    command += ['--server', '--preload', '--model-dir', model_dir]
    env = dict(os.environ)
    env['MASKBRIDGE_STATE_DIR'] = state_dir
    # Start an independent PyInstaller instance rather than a sub-process of
    # this one, which exits immediately (PyInstaller 6.9 and later).
    env['PYINSTALLER_RESET_ENVIRONMENT'] = '1'
    options = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL, close_fds=True, shell=False, env=env)
    if sys.platform == 'win32':
        options['creationflags'] = (subprocess.CREATE_NO_WINDOW
                                    | subprocess.CREATE_NEW_PROCESS_GROUP)
    else:
        options['start_new_session'] = True
    try:
        process = popen(command, **options)
    except OSError as exc:
        print(f"Mask Bridge: cannot start the engine server: {exc}", file=sys.stderr)
        return 4
    print(f"Mask Bridge: engine server started (pid {process.pid})")
    return 0


# ============================================================================
# Main Entry Point
# ============================================================================

    return results["failed"] == 0

def main():
    # Windows consoles default to a legacy codepage (cp1252/cp850) that cannot
    # encode ✓/✗ or some accented filename characters — a bare print() then
    # kills the process with UnicodeEncodeError. Degrade to '?' instead.
    for stream in (sys.stdout, sys.stderr):
        if stream and hasattr(stream, 'reconfigure'):
            stream.reconfigure(errors='replace')

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)s | %(message)s',
        datefmt='%H:%M:%S'
    )

    parser = argparse.ArgumentParser(
        description="Mask Bridge CLI - AI Mask Generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Download models:    maskbridge_engine --download-models
  Single image:       maskbridge_engine --image photo.jpg --output mask.png --prompts person,car
  Batch processing:   maskbridge_engine --batch manifest.json
        """
    )
    parser.add_argument("--model-dir", help="Model directory", 
                        default=os.path.join(os.path.dirname(__file__), "models"))
    
    # Info/diagnostic modes
    parser.add_argument("--build-info", action="store_true", help="Print embedded build provenance")
    parser.add_argument("--self-test", action="store_true", help="Run synthetic model and output smoke tests")
    parser.add_argument("--version", action="store_true", help="Show version info")
    parser.add_argument("--healthcheck", action="store_true", help="Run setup diagnostics")
    
    # Download models mode
    parser.add_argument("--download-models", action="store_true",
                        help="Download AI models (run this first!)")
    
    # Server mode (embedded HTTP server)
    parser.add_argument("--server", action="store_true",
                        help="Start embedded HTTP server for fast repeated inference")
    parser.add_argument("--port", type=int, default=9876, help="Server port (default: 9876)")
    parser.add_argument("--preload", action="store_true", help="Preload AI models on server start")
    parser.add_argument("--spawn-server", action="store_true",
                        help="Start the server (--server --preload) as a detached process and exit")
    parser.add_argument("--state-dir", help="Runtime state directory for --spawn-server")

    # Single image mode
    parser.add_argument("--image", help="Input image path")
    parser.add_argument("--output", help="Output mask path")
    parser.add_argument("--prompts", help="Comma-separated prompts")
    parser.add_argument("--invert", action="store_true", help="Invert mask")
    parser.add_argument("--threshold", type=float, default=0.35, help="Detection threshold (0-1)")
    parser.add_argument("--smoothing", type=int, default=0, help="Edge smoothing level (0-15)")
    parser.add_argument("--edge-refine", action="store_true",
                        help="Opt-in guided-filter edge refinement (soft contour-aware border). "
                             "Default: hard binary mask")
    parser.add_argument("--no-edge-refine", action="store_true",
                        help="(Deprecated, kept for compatibility) Force the hard binary mask; "
                             "this is already the default")
    parser.add_argument("--birefnet-refine", action="store_true",
                        help="Fine-detail mode: BiRefNet matting-grade alpha (hair/fur); "
                             "adds several seconds per image (hardware-dependent)")
    parser.add_argument("--comparison", action="store_true",
                        help="Generate side-by-side comparison image")
    parser.add_argument("--exclude", help="Comma-separated classes to exclude from detection")
    parser.add_argument("--mode", choices=["detect", "matte", "alpha"], default="detect",
                        help="Processing mode: 'detect' for AI segmentation, 'matte' for Lightroom matte conversion, 'alpha' for RGB+mask merge")
    parser.add_argument("--reference", help="Reference image path for two-pass matte difference mode")
    parser.add_argument("--mask", help="Mask image path (for --mode alpha: grayscale mask to use as alpha channel)")
    
    # Batch mode
    parser.add_argument("--batch", help="Path to batch manifest JSON file")
    
    args = parser.parse_args()
    
    try:
        # Version info
        if args.build_info:
            try:
                from build_info import BUILD_INFO
            except ImportError:
                BUILD_INFO = {"build": "source"}
            print(json.dumps(BUILD_INFO))
            return
        elif args.self_test:
            import tempfile
            import numpy as np
            from PIL import Image
            from inference_engine import get_engine, MaskBridgeEngine
            for name in MODEL_SHA256:
                ok, message = verify_model(os.path.join(args.model_dir, name), name)
                if not ok: raise ValueError(message)
            with tempfile.TemporaryDirectory(prefix="maskbridge-selftest-") as tmp:
                source, mask, alpha = [os.path.join(tmp, name) for name in ("source.png", "mask.png", "alpha.png")]
                Image.new("RGB", (96, 64), (96, 128, 160)).save(source)
                engine = get_engine(args.model_dir)
                engine.process_image(source, mask, ["person"])
                MaskBridgeEngine.merge_rgb_mask_to_rgba(source, mask, alpha)
                with Image.open(alpha) as result:
                    assert result.mode == "RGBA" and result.size == (96, 64)
                # Exercise HD session loading/decoding without user photo input.
                with engine._birefnet_lock:
                    assert engine._load_birefnet_locked(), "Fine-detail model failed to load"
                    sample = engine._birefnet_alpha(np.zeros((64, 96, 3), dtype=np.uint8))
                    assert sample.shape == (64, 96) and np.isfinite(sample).all()
            print("Synthetic engine self-test passed")
            return
        elif args.version:
            print(f"Mask Bridge v{VERSION}")
            print(f"Python: {sys.version.split()[0]}")
            print(f"Platform: {sys.platform}")
            sys.exit(0)
        
        # Health check
        elif args.healthcheck:
            success = run_healthcheck(args.model_dir)
            sys.exit(0 if success else 1)

        # Download models mode
        elif args.download_models:
            success = download_models(args.model_dir)
            sys.exit(0 if success else 1)
        
        # Detached server launch (Windows plugin launcher)
        elif args.spawn_server:
            sys.exit(spawn_server(args.model_dir, args.state_dir))

        # Server mode
        elif args.server:
            from server import run_server
            run_server(args.port, args.model_dir, args.preload)
            sys.exit(0)
        
        # Batch mode
        elif args.batch:
            sys.exit(0 if process_batch(args) else 1)
        
        # Matte conversion mode (no AI models needed)
        elif getattr(args, 'mode', 'detect') == 'matte' and args.image and args.output:
            from inference_engine import MaskBridgeEngine
            try:
                validate_path(args.image, 'image')
                validate_path(args.output, 'output')
                if getattr(args, 'reference', None):
                    validate_path(args.reference, 'reference')
                MaskBridgeEngine.process_matte_to_alpha(
                    args.image, args.output, invert=args.invert,
                    reference_path=getattr(args, 'reference', None)
                )
                logger.info(f"SUCCESS: {args.output}")
                sys.exit(0)
            except Exception as e:
                logger.error(f"MATTE ERROR: {e}")
                sys.exit(1)
        
        # Alpha merge mode (RGB + mask → RGBA PNG, no AI models needed)
        elif getattr(args, 'mode', 'detect') == 'alpha' and args.image and args.mask and args.output:
            from inference_engine import MaskBridgeEngine
            try:
                validate_path(args.image, 'image')
                validate_path(args.mask, 'mask')
                validate_path(args.output, 'output')
                MaskBridgeEngine.merge_rgb_mask_to_rgba(args.image, args.mask, args.output)
                logger.info(f"SUCCESS: {args.output}")
                sys.exit(0)
            except Exception as e:
                logger.error(f"ALPHA MERGE ERROR: {e}")
                sys.exit(1)
        
        # Single image mode (AI detection)
        elif args.image and args.output and args.prompts:
            if process_single(args):
                logger.info(f"SUCCESS: {args.output}")
                sys.exit(0)
            else:
                logger.error("FAILURE: Output not created")
                sys.exit(1)
        
        # No valid arguments
        else:
            parser.print_help()
            sys.exit(1)
            
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()

