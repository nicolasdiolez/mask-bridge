"""Keep the floating dashboard above Lightroom only (Windows)."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import dashboard_window as dw  # noqa: E402


def window(hwnd, title, pid=10, exe='Lightroom.exe', owner=0, topmost=False, visible=True, area=100):
    return {'hwnd': hwnd, 'title': title, 'pid': pid, 'exe': exe, 'owner': owner,
            'exstyle': dw.WS_EX_TOPMOST if topmost else 0, 'visible': visible, 'area': area}


MAIN = window(1, 'catalogue - Adobe Photoshop Lightroom Classic - Library', area=10_000)


def test_topmost_dashboard_is_attached_to_lightroom_main_window():
    windows = [MAIN, window(2, 'Mask Bridge', topmost=True),
               window(3, 'Lightroom', owner=1, area=50_000)]  # owned helper, never an owner
    assert dw.plan(windows) == [(2, 1)]


@pytest.mark.parametrize('dashboard', [
    window(2, 'Mask Bridge', topmost=True, exe='chrome.exe'),        # a browser tab titled like us
    window(2, 'Mask Bridge', topmost=True, pid=11),                  # no Lightroom window in its process
    window(2, 'Mask Bridge'),                                        # already not topmost
    window(2, 'Mask Bridge', topmost=True, owner=1),                 # already owned
    window(2, 'Mask Bridge', topmost=True, visible=False),
    window(2, 'Mask Bridge - Export', topmost=True),                 # other dialogs keep Lightroom's choice
])
def test_only_unowned_topmost_lightroom_dashboard_is_touched(dashboard):
    assert dw.plan([MAIN, dashboard]) == []


def test_largest_lightroom_window_becomes_the_owner():
    second = window(4, 'Lightroom Classic - secondary display', area=20_000)
    assert dw.plan([MAIN, second, window(2, 'Mask Bridge', topmost=True)]) == [(2, 4)]


def test_other_platforms_are_left_alone(monkeypatch):
    monkeypatch.setattr(dw.sys, 'platform', 'darwin')
    monkeypatch.setattr(dw, '_top_level_windows', lambda: pytest.fail('must not enumerate'))
    assert dw.attach_dashboard() == {'status': 'unsupported', 'found': 0, 'attached': 0}


def test_only_confirmed_changes_are_counted(monkeypatch):
    class User32:
        def SetWindowLongPtrW(self, *args): pass
        def SetWindowPos(self, *args): pass
        def GetWindow(self, hwnd, cmd): return 0          # Windows refused the new owner
        def GetWindowLongPtrW(self, hwnd, index): return 0
    monkeypatch.setattr(dw.sys, 'platform', 'win32')
    monkeypatch.setattr(dw, '_top_level_windows',
                        lambda: ([MAIN, window(2, 'Mask Bridge', topmost=True)], User32()))
    assert dw.attach_dashboard() == {'status': 'ok', 'found': 1, 'attached': 0}


@pytest.mark.skipif(sys.platform != 'win32', reason='Win32 windows')
def test_real_topmost_window_is_reowned_and_no_longer_topmost():
    ctypes, wintypes, user32, _, _ = dw._user32()
    user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                       ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                       wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.DestroyWindow.argtypes = [wintypes.HWND]
    ws_visible_popup = 0x10000000 | 0x80000000
    exe = os.path.basename(sys.executable).lower()
    # Off-screen so nothing flashes on the desktop; unique titles avoid other processes.
    main = user32.CreateWindowExW(0, 'STATIC', f'Lightroom test owner {os.getpid()}', ws_visible_popup,
                                  -32000, -32000, 200, 200, None, None, None, None)
    title = f'Mask Bridge test {os.getpid()}'
    dash = user32.CreateWindowExW(dw.WS_EX_TOPMOST, 'STATIC', title, ws_visible_popup,
                                  -32000, -32000, 100, 100, None, None, None, None)
    try:
        assert main and dash
        assert dw.attach_dashboard(title, exe) == {'status': 'ok', 'found': 1, 'attached': 1}
        assert user32.GetWindow(dash, dw.GW_OWNER) == main
        assert not user32.GetWindowLongPtrW(dash, dw.GWL_EXSTYLE) & dw.WS_EX_TOPMOST
        # Idempotent: an attached dashboard is not touched again.
        assert dw.attach_dashboard(title, exe)['found'] == 0
    finally:
        for hwnd in (dash, main):
            if hwnd:
                user32.DestroyWindow(hwnd)
