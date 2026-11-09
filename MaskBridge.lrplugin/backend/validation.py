"""Shared, side-effect-free validation helpers for the Mask Bridge backend.

Deliberately import-light (stdlib only, no logging/file setup) so it can be
imported from both the CLI entry point (cli.py) and the HTTP server (server.py)
without pulling in side effects such as log-file creation.
"""
import os
import tempfile
from atomic_io import distinct_output

# Maximum number of images allowed in a single batch manifest
MAX_BATCH_SIZE = 1000

def _get_sensitive_dirs():
    base = [
        '/etc', '/System', '/usr', '/bin', '/sbin', '/var',
        '/Library/LaunchAgents', '/Library/LaunchDaemons',
        '/Library/Keychains', '/Library/Preferences',
        '/Library/PrivilegedHelperTools', '/Library/Security',
        'C:\\Windows', 'C:\\Program Files', 'C:\\Program Files (x86)', 'C:\\ProgramData'
    ]
    if os.name == 'nt':
        base.extend(os.environ.get(name, '') for name in
                    ('SystemRoot', 'ProgramFiles', 'ProgramFiles(x86)', 'ProgramW6432', 'ProgramData'))
    home = os.path.expanduser('~')
    if home and os.path.isdir(home):
        home_sensitive = [
            os.path.join(home, '.ssh'),
            os.path.join(home, '.gnupg'),
            os.path.join(home, '.aws'),
            os.path.join(home, '.config'),
            os.path.join(home, '.bashrc'),
            os.path.join(home, '.zshrc'),
            os.path.join(home, '.profile'),
            os.path.join(home, '.zprofile'),
            os.path.join(home, '.bash_profile'),
            os.path.join(home, 'Library', 'LaunchAgents'),
            os.path.join(home, 'Library', 'Keychains'),
        ]
        appdata = os.environ.get('APPDATA')
        if appdata:
            home_sensitive.append(os.path.join(appdata, 'Microsoft', 'Windows', 'Start Menu', 'Programs', 'Startup'))
        for p in home_sensitive:
            base.append(p)
    return tuple(base)


# Directories that are never valid targets for file operations
SENSITIVE_DIRS = _get_sensitive_dirs()


def _with_resolved_forms(paths):
    """Each path plus its symlink-resolved form, deduplicated.

    macOS puts /etc, /var and /tmp behind symlinks into /private, so comparing
    an already-realpath()'d candidate against the literal '/etc' never matched:
    the blocklist below silently protected nothing on the product's own main
    platform (/etc/passwd resolves to /private/etc/passwd and sailed through).
    """
    out = set()
    for path in paths:
        if not path:
            continue
        out.add(path)
        try:
            out.add(os.path.realpath(path))
        except OSError:
            pass  # a blocklist entry that does not exist here is simply inert
    return tuple(sorted(out))


_SENSITIVE_RESOLVED = _with_resolved_forms(SENSITIVE_DIRS)

# Temp locations the plugin legitimately writes to, and which MUST win over the
# blocklist above. The Dashboard stages Preview renditions in
# <temp>/maskbridge_preview_* and the matte pipeline its renders in
# <temp>/maskbridge_matte_*; on macOS that temp directory lives at
# /var/folders/..., i.e. inside the '/var' branch we just started blocking for
# real. Without this allowance, fixing the /etc hole would take Preview and the
# whole matte feature down with it.
#
# /var/folders is listed explicitly as well as tempfile's answer: the server
# inherits TMPDIR from Lightroom, but a future launch path that does not would
# otherwise silently reject every Preview.
_TEMP_ROOTS = _with_resolved_forms((
    tempfile.gettempdir(),
    '/var/folders' if os.path.isdir('/var/folders') else None,
))


def _is_within(resolved, root):
    """True when ``resolved`` is ``root`` itself or lives under it."""
    resolved, root = os.path.normcase(resolved), os.path.normcase(root)
    return resolved == root or resolved.startswith(root + os.sep)


def validate_path(path, param_name='path'):
    """Validate that a file path is safe for processing.

    Rejects null bytes and paths resolving into sensitive OS directories.
    Returns the resolved real path. Raises ValueError with a descriptive
    message on failure.
    """
    if not path or not isinstance(path, str):
        raise ValueError(f"Empty or invalid {param_name}")
    if '\x00' in path:
        raise ValueError(f"Null byte in {param_name}")
    if os.name == 'nt':
        windows_path = path.replace('/', '\\')
        # Accept normal long Win32/UNC paths; device namespaces and alternate
        # data streams have no place in image IO. No system access is attempted.
        if windows_path.startswith(('\\\\?\\', '\\\\.\\', '\\??\\')):
            raise ValueError(f"Device namespace in {param_name}")
        _, tail = os.path.splitdrive(windows_path)
        if ':' in tail or any(os.path.isreserved(part) for part in tail.split('\\') if part):
            raise ValueError(f"Reserved Windows path in {param_name}")
    resolved = os.path.realpath(path)
    # Allowance before blocklist: the temp roots sit inside /var on macOS.
    for allowed in _TEMP_ROOTS:
        if _is_within(resolved, allowed):
            return resolved
    for sensitive in _SENSITIVE_RESOLVED:
        if _is_within(resolved, sensitive):
            raise ValueError(f"{param_name} resolves to a protected system directory")
    return resolved


def parse_exclude(value):
    """Normalize an exclude parameter (CSV string or list) into a clean list.

    Entries are stripped and lowercased so natural input like "bench, chair"
    matches COCO class names exactly. Returns None when nothing remains.
    """
    if not value:
        return None
    if isinstance(value, (list, tuple)):
        items = [str(c).strip().lower() for c in value]
    else:
        items = [c.strip().lower() for c in str(value).split(',')]
    items = [c for c in items if c]
    return items or None


def normalize_manifest(manifest):
    """Validate batch-manifest field types and return normalized parameters.

    Raises ValueError with a descriptive message on malformed input so callers
    can surface a clean error instead of crashing on a bad type (e.g. a
    non-numeric "smoothing" or an "images" value that is not a list).
    """
    if not isinstance(manifest, dict):
        raise ValueError("manifest must be a JSON object")
    prompts = manifest.get('prompts', [])
    if not isinstance(prompts, list):
        raise ValueError("manifest.prompts must be a list")
    images = manifest.get('images', [])
    if not isinstance(images, list):
        raise ValueError("manifest.images must be a list")
    if len(images) > MAX_BATCH_SIZE:
        raise ValueError(f"Batch exceeds maximum limit of {MAX_BATCH_SIZE} images")
    if not all(isinstance(prompt, str) and 0 < len(prompt) <= 200 for prompt in prompts):
        raise ValueError("manifest.prompts must contain nonempty strings")
    sources, destinations = [], set()
    for item in images:
        if not isinstance(item, dict):
            raise ValueError("Each manifest image must be an object")
        sources.append(validate_path(item.get('input'), 'input'))
    for item in images:
        output = validate_path(item.get('output'), 'output')
        distinct_output(output, *sources)
        if output.casefold() in destinations:
            raise ValueError("Duplicate output paths in manifest")
        destinations.add(output.casefold())
    for key in ('invert', 'edge_refine', 'birefnet_refine'):
        if key in manifest and type(manifest[key]) is not bool:
            raise ValueError(f"manifest.{key} must be a boolean")
    exclude = manifest.get('exclude', '') or ''
    if not isinstance(exclude, str):
        raise ValueError("manifest.exclude must be a string")
    try:
        threshold = float(manifest.get('threshold', 0.35))
    except (TypeError, ValueError):
        raise ValueError("manifest.threshold must be a number")
    # Same guards as the /process endpoint: NaN/Inf fall back to the default,
    # out-of-range values are clamped to the valid probability range.
    if threshold != threshold or threshold in (float('inf'), float('-inf')):
        threshold = 0.35
    threshold = max(0.0, min(1.0, threshold))
    try:
        smoothing = int(manifest.get('smoothing', 0))
    except (TypeError, ValueError):
        raise ValueError("manifest.smoothing must be an integer")
    return {
        'prompts': prompts,
        'invert': bool(manifest.get('invert', False)),
        'threshold': threshold,
        'smoothing': max(0, min(15, smoothing)),
        'exclude': exclude,
        'images': images,
        # Product default is the fast hard mask; guided-filter refinement is an
        # explicit opt-in (matches the /process endpoint and the Dashboard).
        'edge_refine': bool(manifest.get('edge_refine', False)),
        'birefnet_refine': bool(manifest.get('birefnet_refine', False)),
    }


def validate_request(params):
    """Shared request shape check, before slicing, hashing or path operations."""
    if not isinstance(params, dict):
        raise ValueError("Request must be a JSON object")
    for key in ('image', 'input', 'output', 'model_dir', 'manifest', 'reference',
                'rgb_path', 'mask_path', 'output_path'):
        if key in params and not (key == 'reference' and params[key] is None):
            if not isinstance(params[key], str) or len(params[key]) > 32768:
                raise ValueError(f"{key} must be a bounded string")
    for key in ('invert', 'comparison', 'edge_refine', 'birefnet_refine'):
        if key in params and type(params[key]) is not bool:
            raise ValueError(f"{key} must be a boolean")
    if 'prompts' in params:
        prompts = params['prompts']
        if isinstance(prompts, str):
            prompts = prompts.split(',')
        if not isinstance(prompts, list) or len(prompts) > 200 or not all(
                isinstance(p, str) and 0 < len(p) <= 200 for p in prompts):
            raise ValueError("prompts must be a list of class names")
    if 'exclude' in params and params['exclude'] is not None:
        exclude = params['exclude']
        if not isinstance(exclude, (str, list)) or (isinstance(exclude, list) and not all(isinstance(p, str) for p in exclude)):
            raise ValueError("exclude must contain class names")
