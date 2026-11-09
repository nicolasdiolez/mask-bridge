"""Per-user runtime directories with real Windows ACLs, not POSIX mode emulation."""
import os
from pathlib import Path
import sys


def ensure_private_directory(directory):
    directory = Path(directory).absolute()
    # Do not retarget a junction/symlink's ACL or publish secrets through it.
    for parent in (directory, *directory.parents):
        if parent.is_symlink() or (os.name == 'nt' and parent.is_junction()):
            raise OSError('Runtime directory must not traverse a link or junction')
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name != 'nt':
        directory.chmod(0o700)
        return str(directory)

    import ctypes
    from ctypes import wintypes as w
    advapi = ctypes.WinDLL('advapi32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetCurrentProcess.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    advapi.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, ctypes.POINTER(w.HANDLE)]
    advapi.GetTokenInformation.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD)]
    advapi.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(w.LPWSTR)]
    advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [w.LPCWSTR, w.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
    advapi.GetSecurityDescriptorDacl.argtypes = [ctypes.c_void_p, ctypes.POINTER(w.BOOL), ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(w.BOOL)]
    advapi.SetNamedSecurityInfoW.argtypes = [w.LPWSTR, ctypes.c_int, w.DWORD, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    advapi.SetNamedSecurityInfoW.restype = w.DWORD
    token = w.HANDLE()
    if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), 8, ctypes.byref(token)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        size = w.DWORD()
        advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
        buffer = ctypes.create_string_buffer(size.value)
        if not advapi.GetTokenInformation(token, 1, buffer, size, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        sid_pointer = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]
        sid = w.LPWSTR()
        if not advapi.ConvertSidToStringSidW(sid_pointer, ctypes.byref(sid)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            sddl = f'D:P(A;OICI;FA;;;{sid.value})(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)'
        finally:
            kernel.LocalFree(sid)
    finally:
        kernel.CloseHandle(token)
    descriptor = ctypes.c_void_p()
    if not advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(descriptor), None):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        present, defaulted, dacl = w.BOOL(), w.BOOL(), ctypes.c_void_p()
        if not advapi.GetSecurityDescriptorDacl(descriptor, ctypes.byref(present), ctypes.byref(dacl), ctypes.byref(defaulted)):
            raise ctypes.WinError(ctypes.get_last_error())
        error = advapi.SetNamedSecurityInfoW(str(directory), 1, 0x80000004, None, None, dacl, None)
        if error:
            raise ctypes.WinError(error)
    finally:
        kernel.LocalFree(descriptor)
    return str(directory)


def user_state_dir():
    if sys.platform == 'win32':
        # The Lightroom launcher passes its SDK-resolved appData location,
        # including redirected profiles. Standalone CLI uses the OS default.
        directory = os.environ.get('MASKBRIDGE_STATE_DIR')
        if not directory:
            base = os.environ.get('APPDATA') or str(Path.home() / 'AppData/Roaming')
            directory = str(Path(base) / 'MaskBridge/Runtime-v2')
    else:
        directory = str(Path.home() / 'Library/Application Support/MaskBridge')
    return ensure_private_directory(directory)
