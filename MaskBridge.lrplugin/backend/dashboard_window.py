"""Keep the Mask Bridge dashboard above Lightroom only (Windows).

On Windows, Lightroom Classic shows ``LrDialogs.presentFloatingDialog`` windows
as unowned ``WS_EX_TOPMOST`` windows, so the dashboard stays above every other
application. The SDK has no option for this. The engine, already running beside
Lightroom, gives the dashboard Lightroom's main window as owner and drops the
topmost flag: an owned window still stays above its owner and minimises with it,
but goes behind other applications.

Only visible windows titled exactly like the dashboard and owned by a
``Lightroom.exe`` process are touched. The dashboard is re-created after each
export, so the plugin asks again every time it is shown.
"""
import os
import sys

DASHBOARD_TITLE = 'Mask Bridge'
LIGHTROOM_EXE = 'lightroom.exe'
WS_EX_TOPMOST = 0x00000008

GW_OWNER = 4
GWL_EXSTYLE = -20
GWLP_HWNDPARENT = -8
HWND_NOTOPMOST = -2
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x0001, 0x0002, 0x0010
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def plan(windows, title=DASHBOARD_TITLE, exe=LIGHTROOM_EXE):
    """Return ``(dashboard_hwnd, lightroom_main_hwnd)`` pairs to fix.

    ``windows`` describes top-level windows as dicts with ``hwnd``, ``title``,
    ``pid``, ``exe`` (image base name), ``owner``, ``exstyle``, ``visible`` and
    ``area``. A dashboard qualifies when it is a visible, unowned, topmost
    Lightroom window with the exact dashboard title; its owner becomes the
    largest unowned visible Lightroom window of the same process. ``exe`` is
    only overridden by tests driving their own windows.
    """
    lightroom = [w for w in windows if w['visible'] and w['exe'].lower() == exe]
    pairs = []
    for window in lightroom:
        if window['title'] != title or window['owner'] or not window['exstyle'] & WS_EX_TOPMOST:
            continue
        mains = [m for m in lightroom
                 if m['pid'] == window['pid'] and m['hwnd'] != window['hwnd']
                 and not m['owner'] and 'Lightroom' in m['title']]
        if mains:
            pairs.append((window['hwnd'], max(mains, key=lambda m: m['area'])['hwnd']))
    return pairs


def _user32():
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL('user32', use_last_error=True)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [proc, wintypes.LPARAM]
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetWindow.restype = wintypes.HWND
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                    wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    return ctypes, wintypes, user32, kernel32, proc


def _top_level_windows():
    ctypes, wintypes, user32, kernel32, proc = _user32()
    exe_by_pid = {}

    def exe_name(pid):
        if pid not in exe_by_pid:
            name = ''
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if handle:
                try:
                    size = wintypes.DWORD(1024)
                    buffer = ctypes.create_unicode_buffer(size.value)
                    if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                        name = os.path.basename(buffer.value)
                finally:
                    kernel32.CloseHandle(handle)
            exe_by_pid[pid] = name
        return exe_by_pid[pid]

    windows = []

    def visit(hwnd, _):
        length = user32.GetWindowTextLengthW(hwnd)
        text = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, text, length + 1)
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        windows.append({
            'hwnd': hwnd, 'title': text.value, 'pid': pid.value, 'exe': exe_name(pid.value),
            'owner': user32.GetWindow(hwnd, GW_OWNER) or 0,
            'exstyle': user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE),
            'visible': bool(user32.IsWindowVisible(hwnd)),
            'area': max(0, rect.right - rect.left) * max(0, rect.bottom - rect.top),
        })
        return True

    user32.EnumWindows(proc(visit), 0)
    return windows, user32


def attach_dashboard(title=DASHBOARD_TITLE, exe=LIGHTROOM_EXE):
    """Re-parent the topmost dashboard to Lightroom; report what was changed."""
    if sys.platform != 'win32':
        return {'status': 'unsupported', 'found': 0, 'attached': 0}
    windows, user32 = _top_level_windows()
    pairs = plan(windows, title, exe)
    attached = 0
    for dashboard, owner in pairs:
        user32.SetWindowLongPtrW(dashboard, GWLP_HWNDPARENT, owner)
        user32.SetWindowPos(dashboard, HWND_NOTOPMOST, 0, 0, 0, 0,
                            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
        # Count only what Windows confirms, not what was requested.
        if (user32.GetWindow(dashboard, GW_OWNER) == owner
                and not user32.GetWindowLongPtrW(dashboard, GWL_EXSTYLE) & WS_EX_TOPMOST):
            attached += 1
    return {'status': 'ok', 'found': len(pairs), 'attached': attached}
