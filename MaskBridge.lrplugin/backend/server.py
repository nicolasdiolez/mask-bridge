"""
Mask Bridge - Local HTTP Server
Keeps AI models loaded in memory for fast inference.
Listens on localhost only (127.0.0.1) for security.
"""
import argparse
from functools import wraps
from atomic_io import atomic_json, atomic_write, distinct_output
import hmac
import json
import os
import secrets
import sys
import time
import traceback
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
import logging
import unicodedata

# Setup file-based logging with rotation (max 5MB, keep 2 backups).
# The log lives in the plugin root; a locked-down install (read-only plugin
# directory) must degrade to the system temp dir instead of crashing the
# server at import time.
from logging.handlers import RotatingFileHandler
import tempfile
from runtime_paths import user_state_dir, ensure_private_directory
if sys.platform == 'win32':
    _log_dir = user_state_dir()
elif getattr(sys, 'frozen', False):
    # PyInstaller OneDir: exe is at backend/maskbridge_engine/maskbridge_engine.exe
    # log goes to the plugin root (3 levels up from exe)
    _log_dir = os.path.dirname(os.path.dirname(os.path.dirname(sys.executable)))
else:
    _log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '..')
if not os.access(_log_dir, os.W_OK):
    _log_dir = tempfile.gettempdir()
_log_file = os.path.join(_log_dir, 'server_debug.log')
_log_fmt = logging.Formatter('%(asctime)s | %(levelname)s | %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
try:
    _file_handler = RotatingFileHandler(_log_file, maxBytes=5*1024*1024, backupCount=2, delay=True)
except OSError:
    _file_handler = logging.StreamHandler()
_file_handler.setFormatter(_log_fmt)
logging.basicConfig(level=logging.INFO, handlers=[_file_handler], force=True)
logger = logging.getLogger('MaskBridgeServer')

# Ensure unbuffered output for logging visibility in frozen apps
# (sys.stdout/stderr can be None when launched from a GUI parent without a console)
if sys.stdout:
    sys.stdout.reconfigure(line_buffering=True)
if sys.stderr:
    sys.stderr.reconfigure(line_buffering=True)

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(__file__))

import math

from inference_engine import get_engine
import dashboard_window
# The plugin only talks to an engine of its own version: an engine left running
# by another release shares the same state file. Single source: cli.VERSION.
from cli import VERSION as ENGINE_VERSION

# Shared, side-effect-free validation helpers (path safety + manifest typing)
from validation import validate_path as _validate_path, normalize_manifest, parse_exclude, validate_request


# Global engine instance (loaded once, reused)
_engine = None
_model_dir = None

# Heartbeat tracking for anti-zombie protection
_last_health_ping = time.time()
_heartbeat_timeout = 60  # seconds without ping before auto-shutdown
_heartbeat_enabled = True  # Can be disabled via --no-heartbeat flag
_heartbeat_lock = threading.Lock()  # Guards _last_health_ping (multi-threaded server)


def _touch_heartbeat():
    """Record a heartbeat ping (thread-safe)."""
    global _last_health_ping
    with _heartbeat_lock:
        _last_health_ping = time.time()


def _health_payload():
    """/health answer (GET and POST). `version` lets the plugin recognise an
    engine started by another Mask Bridge release and replace it."""
    return {
        'status': 'ok',
        'version': ENGINE_VERSION,
        'models_loaded': _engine is not None and getattr(_engine, '_models_loaded', False),
        'pid': os.getpid(),
        'heartbeat_timeout': _heartbeat_timeout if _heartbeat_enabled else None
    }


# Lock for thread-safe engine loading
_engine_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Request authentication
#
# Binding to 127.0.0.1 keeps remote hosts out, but NOT other local processes,
# and not the user's own browser: any web page can POST to a localhost port it
# guesses (the range here is only 100 wide). Reading the reply is blocked by the
# same-origin policy, but the side effects still happen: an unauthenticated
# caller could make /matte or /merge-alpha overwrite arbitrary user files with a
# PNG, keep the engine busy, or stop it.
#
# Every endpoint therefore requires a per-run secret, written next to the port
# file with owner-only permissions. /health is exempt so the "is the engine up?"
# path stays bulletproof: it exposes nothing actionable, and it still refuses
# browser-originated requests via the Origin check below.
# ---------------------------------------------------------------------------
_auth_token = None
AUTH_HEADER = 'X-MaskBridge-Token'
AUTH_EXEMPT_PATHS = frozenset({'/health'})


def _user_state_dir() -> str:
    """Per-user directory for runtime state.

    The Lua client resolves the same location (runtimeStateCandidates in
    MaskBridgeUtils.lua), so both sides must keep agreeing on it.
    """
    return user_state_dir()


def _runtime_state_dir(preferred: str) -> str:
    """Where to publish .server_port and .server_token.

    Normally the backend directory, which is the first place the Lua client
    looks. A plugin installed read-only (a shared
    /Library/Application Support/Adobe/Lightroom/Modules, a mounted disk image,
    a locked-down managed Mac) used to take an uncaught PermissionError here and
    kill the server at startup; the plugin then silently fell back to one
    PyInstaller cold start per image, with the traceback in a temp file nobody
    reads. Mirrors what the logging setup above already does for its own file.
    """
    if sys.platform == 'win32':
        return _user_state_dir()
    if os.access(preferred, os.W_OK):
        return preferred
    try:
        fallback = _user_state_dir()
    except OSError as exc:
        logger.error("No writable location for the port/token files: %s", exc)
        raise
    logger.warning("Plugin directory is not writable (%s) — publishing the port "
                   "and token to %s instead", preferred, fallback)
    return fallback


def _write_auth_token(directory: str) -> str:
    """Generate this run's secret and persist it for the Lightroom client."""
    global _auth_token
    if sys.platform == 'win32':
        ensure_private_directory(directory)
    _auth_token = secrets.token_urlsafe(32)
    token_file = os.path.join(directory, '.server_token')
    # Create owner-only from the start: open()+chmod left the secret readable
    # by every local account for the moment in between.
    atomic_write(token_file, _auth_token.encode("ascii"))
    return token_file


def _write_port_file(directory: str, port: int) -> str:
    """Publish the listening port. This is the client's 'server is up' signal."""
    port_file = os.path.join(directory, '.server_port')
    atomic_write(port_file, str(port).encode("ascii"))
    atomic_json(os.path.join(directory, '.server_state.json'),
                {"port": port, "token": _auth_token, "pid": os.getpid()})
    return port_file


def _remove_own_state(state_dir: str, port_file: str, token_file: str) -> None:
    """Remove this engine's state files on exit, unless the state record now
    names another engine: a newer release that replaced this one shares the
    same files, and deleting them would make the plugin believe its own
    engine had stopped."""
    state_path = os.path.join(state_dir, '.server_state.json')
    try:
        with open(state_path, encoding='utf-8') as f:
            owner = json.load(f).get('pid')
    except (OSError, ValueError, AttributeError):
        owner = None
    if owner is not None and owner != os.getpid():
        logger.info(f"State record now belongs to pid {owner}; leaving it in place")
        return
    for stale in (port_file, token_file, state_path):
        try:
            os.remove(stale)
        except FileNotFoundError:
            pass


def get_or_load_engine(model_dir: str):
    """Get or lazily load the inference engine (thread-safe)."""
    global _engine, _model_dir
    
    # Fast check
    if _engine is not None and _model_dir == model_dir:
        return _engine
        
    with _engine_lock:
        # Double-check inside lock
        if _engine is None or _model_dir != model_dir:
            logger.info(f"Loading models from {model_dir}...")
            start = time.time()
            try:
                _engine = get_engine(model_dir)
                logger.info(f"Models loaded in {time.time() - start:.1f}s")
                _model_dir = model_dir
            except Exception as e:
                logger.error(f"Failed to load models: {e}")
                traceback.print_exc()
                raise e
    return _engine


def start_heartbeat_watchdog(server):
    """Start background thread that monitors heartbeat and auto-shutdowns if idle.
    
    This prevents zombie processes when Lightroom crashes without calling /shutdown.
    The watchdog checks every 10 seconds if the last health ping was too long ago.
    """
    if not _heartbeat_enabled:
        logger.info("Heartbeat watchdog disabled")
        return

    def watchdog(http_server):
        logger.info(f"Heartbeat watchdog started (timeout: {_heartbeat_timeout}s)")

        while True:
            time.sleep(10)  # Check every 10 seconds

            # Opportunistic RAM housekeeping: release the BiRefNet session after
            # 1 hour without a Fine detail request (reloads lazily).
            if _engine is not None:
                try:
                    _engine.maybe_unload_birefnet()
                except Exception:
                    pass

            with _heartbeat_lock:
                last_ping = _last_health_ping
            elapsed = time.time() - last_ping
            with _active_requests_lock:
                active = _active_requests
            if elapsed > _heartbeat_timeout and not active:
                logger.info(f"No heartbeat for {elapsed:.0f}s, auto-shutting down...")
                # Graceful shutdown of the server loop
                http_server.shutdown()
                break
    
    thread = threading.Thread(target=watchdog, args=(server,), daemon=True)
    thread.start()


_processing_slots = threading.BoundedSemaphore(3)
_active_requests = 0
_active_requests_lock = threading.Lock()


def validated_handler(function):
    @wraps(function)
    def call(self, params):
        global _active_requests
        try:
            validate_request(params)
        except ValueError as exc:
            self.send_json({"status": "error", "error": str(exc)}, 400)
            return
        heavy = function.__name__ in {"handle_process", "handle_batch", "handle_matte", "handle_merge_alpha"}
        if heavy and not _processing_slots.acquire(blocking=False):
            self.send_json({"status": "error", "error": "Engine busy; retry after current work completes"}, 503)
            return
        with _active_requests_lock:
            _active_requests += 1
        try:
            return function(self, params)
        except (TypeError, ValueError, OverflowError) as exc:
            self.send_json({"status": "error", "error": str(exc)}, 400)
        finally:
            with _active_requests_lock:
                _active_requests -= 1
            _touch_heartbeat()
            if heavy:
                _processing_slots.release()
    return call


class BoundedHTTPServer(ThreadingHTTPServer):
    """Bound connections as well as costly work; slow clients cannot grow threads."""
    daemon_threads = True
    def __init__(self, *args, **kwargs):
        self._connection_slots = threading.BoundedSemaphore(16)
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        if not self._connection_slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        request.settimeout(15)
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._connection_slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._connection_slots.release()


class MaskBridgeHandler(BaseHTTPRequestHandler):
    """HTTP request handler for Mask Bridge server."""
    
    def log_message(self, format, *args):
        """Override to use custom logging."""
        logger.debug(f"{args[0]}")
    
    def send_json(self, data: dict, status: int = 200):
        """Send JSON response."""
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', 'http://127.0.0.1')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))

    def _authorized(self, path: str) -> bool:
        """Reject anything that is not the local Lightroom client (see _auth_token).

        A browser always attaches Origin to a cross-origin request and cannot
        set a custom header without passing a CORS preflight we never approve;
        the Lua client sends the token and no Origin. Checking both closes the
        drive-by path even for endpoints exempt from the token.
        """
        if self.headers.get('Origin'):
            return False
        if path in AUTH_EXEMPT_PATHS:
            return True
        presented = self.headers.get(AUTH_HEADER, '')
        return bool(_auth_token) and hmac.compare_digest(presented, _auth_token)

    # Body bytes we are willing to swallow from a rejected caller. Enough for
    # any legitimate request, far below MAX_REQUEST_SIZE so an unauthenticated
    # client can never make us buffer 10 MB.
    REJECT_DRAIN_LIMIT = 64 * 1024

    def reject_unauthorized(self):
        """Answer 401, draining the request body first.

        Closing the socket while the client is still writing its body surfaces
        as a connection reset instead of the 401 we meant to send, so read (and
        throw away) a bounded amount before replying.
        """
        try:
            pending = int(self.headers.get('Content-Length', 0))
        except (TypeError, ValueError):
            pending = 0
        if 0 < pending <= self.REJECT_DRAIN_LIMIT:
            try:
                self.rfile.read(pending)
            except Exception:
                pass
        self.send_json({'error': 'Unauthorized'}, 401)

    def do_GET(self):
        """Handle GET requests."""
        parsed = urlparse(self.path)

        if not self._authorized(parsed.path):
            self.reject_unauthorized()
            return

        if parsed.path == '/health':
            # Health check endpoint - also serves as heartbeat
            _touch_heartbeat()
            self.send_json(_health_payload())
        
        elif parsed.path == '/shutdown':
            # Graceful shutdown
            self.send_json({'status': 'shutting_down'})
            logger.info("Shutdown requested, exiting...")
            # Schedule shutdown after response is sent
            import threading
            threading.Thread(target=lambda: self.server.shutdown(), daemon=True).start()
        
        else:
            self.send_json({'error': 'Unknown endpoint'}, 404)
    
    # Maximum request body size: 10 MB (manifest files + paths can be large)
    MAX_REQUEST_SIZE = 10 * 1024 * 1024

    def do_POST(self):
        """Handle POST requests."""
        parsed = urlparse(self.path)

        # Authenticate BEFORE touching the heartbeat or reading the body: an
        # unauthenticated caller must not be able to keep the engine alive, nor
        # make us buffer up to MAX_REQUEST_SIZE on its behalf.
        if not self._authorized(parsed.path):
            self.reject_unauthorized()
            return

        # Any request is a sign of life: without this, a long batch with the
        # Dashboard closed (no /health polling) would trip the 60s watchdog
        # and kill the server mid-batch.
        _touch_heartbeat()

        # Read request body with size limit. Guard against a malformed or
        # negative Content-Length header (a bad client should not crash the handler).
        try:
            content_length = int(self.headers.get('Content-Length', 0))
        except (TypeError, ValueError):
            self.send_json({'error': 'Invalid Content-Length header'}, 400)
            return
        if content_length < 0:
            self.send_json({'error': 'Invalid Content-Length header'}, 400)
            return
        if content_length > self.MAX_REQUEST_SIZE:
            self.send_json({'error': f'Request too large (max {self.MAX_REQUEST_SIZE // (1024*1024)}MB)'}, 413)
            return
        try:
            body = self.rfile.read(content_length).decode('utf-8')
        except UnicodeDecodeError:
            self.send_json({'error': 'Request body is not valid UTF-8'}, 400)
            return

        try:
            params = json.loads(body) if body else {}
        except json.JSONDecodeError:
            self.send_json({'error': 'Invalid JSON'}, 400)
            return
        
        if not isinstance(params, dict):
            self.send_json({'error': 'Request must be a JSON object'}, 400)
            return

        # Support POST for /health (Lua httpPost compatibility)
        if parsed.path == '/health':
            _touch_heartbeat()
            self.send_json(_health_payload())
            return
        
        if parsed.path == '/process':
            # Process single image
            self.handle_process(params)
        
        elif parsed.path == '/batch':
            # Process batch of images
            self.handle_batch(params)
        
        elif parsed.path == '/merge-alpha':
            # Merge RGB + mask → RGBA PNG (no AI inference)
            self.handle_merge_alpha(params)

        elif parsed.path == '/matte':
            # Lightroom matte render → grayscale mask PNG (no AI inference).
            # Previously CLI-only: each photo of a matte batch paid a PyInstaller
            # cold start (~1-3s); the running server does it in milliseconds.
            self.handle_matte(params)

        elif parsed.path == '/dashboard-window':
            # Windows: Lightroom makes floating dialogs topmost over every app
            self.handle_dashboard_window()

        else:
            self.send_json({'error': 'Unknown endpoint'}, 404)
    
    @validated_handler
    def handle_process(self, params: dict):
        """Process a single image."""
        required = ['image', 'output', 'prompts', 'model_dir']
        for key in required:
            if key not in params:
                self.send_json({'error': f'Missing required parameter: {key}'}, 400)
                return
        
        # Preserve exact paths. NTFS can hold distinct NFC and NFD names.

        # Path safety validation
        try:
            _validate_path(params['image'], 'image')
            _validate_path(params['output'], 'output')
            _validate_path(params['model_dir'], 'model_dir')
        except ValueError as e:
            self.send_json({'error': f'Invalid path: {e}'}, 400)
            return

        image_file = params.get('image', 'unknown')
        image_basename = os.path.basename(image_file)

        # Validate parameter ranges (guard against NaN/Inf)
        try:
            threshold = float(params.get('threshold', 0.35))
            if math.isnan(threshold) or math.isinf(threshold):
                threshold = 0.35
            threshold = max(0.0, min(1.0, threshold))
        except (ValueError, TypeError):
            threshold = 0.35
        try:
            smoothing = int(params.get('smoothing', 0))
            smoothing = max(0, min(15, smoothing))
        except (ValueError, TypeError):
            smoothing = 0

        try:
            start = time.time()
            engine = get_or_load_engine(params['model_dir'])

            logger.info(f"Processing: {image_basename} | threshold={threshold}, smoothing={smoothing}")

            outcome = engine.process_image(
                image_path=params['image'],
                output_path=params['output'],
                prompts=params['prompts'] if isinstance(params['prompts'], list) else params['prompts'].split(','),
                invert=params.get('invert', False),
                threshold=threshold,
                smoothing=smoothing,
                exclude_classes=parse_exclude(params.get('exclude')),
                # Product default is the fast hard mask; edge_refine (guided
                # filter) is an explicit API opt-in, matching the Dashboard.
                edge_refine=params.get('edge_refine', False),
                birefnet_refine=params.get('birefnet_refine', False),
            )
            
            elapsed = time.time() - start
            comparison_path = None
            
            # Generate comparison/overlay image if requested
            if params.get('comparison', False) and os.path.exists(params['output']):
                comparison_path = os.path.splitext(params['output'])[0] + '_overlay.jpg'
                engine.create_comparison_image(params['image'], params['output'], comparison_path)
            
            if os.path.exists(params['output']):
                logger.info(f"OK: {image_basename} in {elapsed:.2f}s")
                response = {
                    'status': 'success',
                    'output': params['output'],
                    'time': round(elapsed, 2)
                }
                if isinstance(outcome, dict):
                    response.update(outcome)
                if comparison_path and os.path.exists(comparison_path):
                    response['comparison'] = comparison_path
                self.send_json(response)
            else:
                logger.warning(f"FAIL: {image_basename} — output not created")
                self.send_json({'status': 'error', 'message': 'Output not created', 'file': image_basename}, 500)
        
        except Exception as e:
            traceback.print_exc()
            err_msg = str(e)
            logger.error(f"FAIL: {image_basename} — {err_msg}")
            self.send_json({'status': 'error', 'message': err_msg, 'file': image_basename}, 500)
    
    @validated_handler
    def handle_batch(self, params: dict):
        """Process batch of images from manifest."""
        if 'manifest' not in params:
            self.send_json({'error': 'Missing manifest parameter'}, 400)
            return

        manifest_path = params['manifest']
        model_dir = params.get('model_dir', os.path.join(os.path.dirname(__file__), 'models'))

        # Path safety validation
        try:
            _validate_path(manifest_path, 'manifest')
            _validate_path(model_dir, 'model_dir')
        except ValueError as e:
            self.send_json({'error': f'Invalid path: {e}'}, 400)
            return

        try:
            with open(manifest_path, 'r', encoding='utf-8') as f:
                manifest = json.load(f)

            cfg = normalize_manifest(manifest)

            engine = get_or_load_engine(model_dir)

            prompts = cfg['prompts']
            invert = cfg['invert']
            threshold = cfg['threshold']
            smoothing = cfg['smoothing']
            exclude_str = cfg['exclude']
            images = cfg['images']
            edge_refine = cfg['edge_refine']
            birefnet_refine = cfg['birefnet_refine']

            exclude_classes = parse_exclude(exclude_str)
            
            results = {'success': 0, 'failed': 0, 'details': []}
            total = len(images)
            result_path = os.path.splitext(manifest_path)[0] + '.result.json'
            
            logger.info(f"Processing batch: {total} images, threshold={threshold}, smoothing={smoothing}")
            start_time = time.time()
            
            for i, item in enumerate(images, 1):
                input_path = item.get('input')
                output_path = item.get('output')
                
                if not input_path or not output_path:
                    results['failed'] += 1
                    results['details'].append({'input': input_path, 'status': 'error', 'message': 'Missing path'})
                    continue

                try:
                    _validate_path(input_path, 'batch item input')
                    _validate_path(output_path, 'batch item output')
                except ValueError as e:
                    results['failed'] += 1
                    results['details'].append({'input': input_path, 'status': 'error', 'message': f'Invalid path: {e}'})
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
                        results['success'] += 1
                        results['details'].append({
                            'input': input_path, 
                            'output': output_path, 
                            'status': 'ok', 
                            'time': round(elapsed, 2)
                        })
                        logger.info(f"  [{i}/{total}] OK {os.path.basename(input_path)} ({elapsed:.1f}s)")
                    else:
                        results['failed'] += 1
                        results['details'].append({'input': input_path, 'status': 'error', 'message': 'Output not created'})
                        logger.warning(f"  [{i}/{total}] FAIL {os.path.basename(input_path)}")

                except Exception as e:
                    results['failed'] += 1
                    results['details'].append({'input': input_path, 'status': 'error', 'message': str(e)})
                    logger.error(f"  [{i}/{total}] FAIL {os.path.basename(input_path)}: {e}")
                
                # Write intermediate results for Lua polling
                distinct_output(result_path, manifest_path, *(entry['input'] for entry in images))
                atomic_json(result_path, results)
            
            total_time = time.time() - start_time
            logger.info(f"Batch complete: {results['success']}/{total} in {total_time:.1f}s")
            
            self.send_json({
                'status': 'complete',
                'success': results['success'],
                'failed': results['failed'],
                'total_time': round(total_time, 2),
                'result_file': result_path
            })

        except ValueError as e:
            # Malformed JSON or invalid manifest field types -> client error
            self.send_json({'status': 'error', 'message': f'Invalid manifest: {e}'}, 400)
        except Exception as e:
            traceback.print_exc()
            self.send_json({'status': 'error', 'message': str(e)}, 500)

    @validated_handler
    def handle_matte(self, params: dict):
        """Convert a Lightroom matte render (black bg / white mask) to a grayscale PNG.

        No AI inference runs: the render was produced by Lightroom under the
        user's control.
        """
        required = ['input', 'output']
        for key in required:
            if key not in params:
                self.send_json({'error': f'Missing required parameter: {key}'}, 400)
                return

        input_path = params['input']
        output_path = params['output']
        reference_path = params.get('reference')

        try:
            _validate_path(input_path, 'input')
            _validate_path(output_path, 'output')
            if reference_path:
                _validate_path(reference_path, 'reference')
        except ValueError as e:
            self.send_json({'error': f'Invalid path: {e}'}, 400)
            return

        try:
            start = time.time()
            from inference_engine import MaskBridgeEngine
            MaskBridgeEngine.process_matte_to_alpha(
                input_path, output_path,
                invert=bool(params.get('invert', False)),
                reference_path=reference_path,
            )
            elapsed = time.time() - start

            if os.path.exists(output_path):
                logger.info(f"Matte OK: {os.path.basename(output_path)} in {elapsed:.2f}s")
                self.send_json({
                    'status': 'success',
                    'output': output_path,
                    'time': round(elapsed, 2)
                })
            else:
                self.send_json({'status': 'error', 'message': 'Output not created'}, 500)

        except Exception as e:
            traceback.print_exc()
            logger.error(f"Matte FAIL: {str(e)}")
            self.send_json({'status': 'error', 'message': str(e)}, 500)

    @validated_handler
    def handle_merge_alpha(self, params: dict):
        """Merge RGB image + grayscale mask into a 32-bit RGBA PNG.

        This is a lightweight image operation (no AI inference).
        """
        required = ['rgb_path', 'mask_path', 'output_path']
        for key in required:
            if key not in params:
                self.send_json({'error': f'Missing required parameter: {key}'}, 400)
                return
        
        # Normalize Unicode paths
        rgb_path = params['rgb_path']
        mask_path = params['mask_path']
        output_path = params['output_path']

        # Path safety validation
        try:
            _validate_path(rgb_path, 'rgb_path')
            _validate_path(mask_path, 'mask_path')
            _validate_path(output_path, 'output_path')
        except ValueError as e:
            self.send_json({'error': f'Invalid path: {e}'}, 400)
            return

        try:
            start = time.time()
            from inference_engine import MaskBridgeEngine
            MaskBridgeEngine.merge_rgb_mask_to_rgba(rgb_path, mask_path, output_path)
            elapsed = time.time() - start
            
            if os.path.exists(output_path):
                logger.info(f"Alpha merge OK: {os.path.basename(output_path)} in {elapsed:.2f}s")
                self.send_json({
                    'status': 'success',
                    'output': output_path,
                    'time': round(elapsed, 2)
                })
            else:
                self.send_json({'status': 'error', 'message': 'Output not created'}, 500)
        
        except Exception as e:
            traceback.print_exc()
            logger.error(f"Alpha merge FAIL: {str(e)}")
            self.send_json({'status': 'error', 'message': str(e)}, 500)

    def handle_dashboard_window(self):
        """Windows: keep the floating dashboard above Lightroom only."""
        try:
            result = dashboard_window.attach_dashboard()
        except Exception as e:
            logger.error(f"Dashboard window FAIL: {e}")
            self.send_json({'status': 'error', 'message': str(e)}, 500)
            return
        if result['found']:
            logger.info(f"Dashboard window: {result['attached']}/{result['found']} attached to Lightroom")
        self.send_json(result)


def find_free_port(start_port: int = 9876) -> int:
    """Find a free port starting from start_port."""
    import socket
    for port in range(start_port, start_port + 100):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('127.0.0.1', port))
                return port
        except OSError:
            continue
    raise RuntimeError("No free port found")


def main():
    parser = argparse.ArgumentParser(description='Mask Bridge Local Server')
    parser.add_argument('--port', type=int, default=9876, help='Port to listen on')
    parser.add_argument('--model-dir', default=os.path.join(os.path.dirname(__file__), 'models'),
                        help='Model directory')
    parser.add_argument('--preload', action='store_true', help='Preload models on startup')
    args = parser.parse_args()
    
    # Find free port
    try:
        port = find_free_port(args.port)
    except RuntimeError as e:
        logger.error(f"Error: {e}")
        sys.exit(1)

    if port != args.port:
        logger.info(f"Port {args.port} busy, using {port}")
    
    # Write the auth token BEFORE the port file: the client treats the port file
    # as "server registered" and would otherwise race to a tokenless request.
    state_dir = _runtime_state_dir(os.path.dirname(__file__))
    token_file = _write_auth_token(state_dir)
    server = BoundedHTTPServer(('127.0.0.1', port), MaskBridgeHandler)
    port_file = _write_port_file(state_dir, port)

    # Preload models if requested (Async)
    if args.preload:
        logger.info("Preloading models (background)...")
        threading.Thread(target=get_or_load_engine, args=(args.model_dir,), daemon=True).start()

    # Start server
    logger.info(f"Mask Bridge server running on http://127.0.0.1:{port}")
    logger.info(f"PID: {os.getpid()}")
    logger.info("Ready for requests. Use /shutdown to stop.")
    
    # Start heartbeat watchdog (auto-shutdown if Lightroom disappears)
    start_heartbeat_watchdog(server)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Interrupted, shutting down...")
    finally:
        server.shutdown()
        server.server_close()
        _remove_own_state(state_dir, port_file, token_file)


def run_server(port: int, model_dir: str, preload: bool = False):
    """Entry point for cli.py embedded server mode.

    This function allows cli.py (compiled to maskbridge_engine binary)
    to start the server without going through argparse.
    """
    # Simulate args for main logic
    import socket

    # Find free port
    actual_port = port
    for p in range(port, port + 100):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('127.0.0.1', p))
                actual_port = p
                break
        except OSError:
            continue

    if actual_port != port:
        logger.info(f"Port {port} busy, using {actual_port}")
    
    # Write port file - for PyInstaller, use the directory containing the executable
    # For development, use the script directory
    if getattr(sys, 'frozen', False):
        # PyInstaller bundle: write to parent of maskbridge_engine directory (= backend/)
        executable_dir = os.path.dirname(sys.executable)
        backend_dir = (os.path.dirname(executable_dir)
                       if os.path.basename(executable_dir) == 'maskbridge_engine' else executable_dir)
    else:
        # Development mode: script directory
        backend_dir = os.path.dirname(__file__)

    # Auth token first — the port file is the client's "server is up" signal.
    state_dir = _runtime_state_dir(backend_dir)
    token_file = _write_auth_token(state_dir)
    server = BoundedHTTPServer(('127.0.0.1', actual_port), MaskBridgeHandler)
    port_file = _write_port_file(state_dir, actual_port)
    logger.info(f"Port file: {port_file}")

    # Preload models if requested (Async)
    if preload:
        logger.info("Preloading models (background)...")
        threading.Thread(target=get_or_load_engine, args=(model_dir,), daemon=True).start()

    # Start server
    logger.info(f"Mask Bridge server running on http://127.0.0.1:{actual_port}")
    logger.info(f"PID: {os.getpid()}")
    logger.info("Ready for requests. Use /shutdown to stop.")
    
    # Start heartbeat watchdog (auto-shutdown if Lightroom disappears)
    start_heartbeat_watchdog(server)
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Interrupted, shutting down...")
    finally:
        server.shutdown()
        server.server_close()
        _remove_own_state(state_dir, port_file, token_file)


if __name__ == '__main__':
    main()
