"""Exercise the dashboard's Lua callbacks with SDK-shaped bindings."""
import re
from pathlib import Path

import pytest

SOURCE = (Path(__file__).resolve().parents[2] / 'MaskBridgeDashboard.lua').read_text(encoding='utf-8')


def runtime():
    lua = pytest.importorskip('lupa.lua51').LuaRuntime(unpack_returned_tuples=True)
    lua.execute('''
        function LOC(s) return s end
        props={photoCount=7,serverRunning=true}
        prefs={}; saved=0; errors=0; reopened=0; closed=0
        answer='cancel'
        LrTasks={pcall=pcall}
        LrDialogs={confirm=function() return answer end,showError=function() errors=errors+1 end}
        MaskBridgeUtils={isWindows=function() return true end,isDashboardOpen=function() return false end,
            startOperation=function(name,fn) fn() end}
        props.closeDialog=function() closed=closed+1 end
        function showDashboard() reopened=reopened+1 end
        function saveSettings() saved=saved+1 end
    ''')
    return lua


def test_generate_binding_uses_properties_not_sdk_binder():
    lua = runtime()
    binding = re.search(r'enabled = LrView.bind \{ keys = \{ "photoCount", "serverRunning" \}, operation = (function\(\).*?end) \}', SOURCE, re.S)
    assert binding
    callback = lua.execute('return ' + binding.group(1))
    # The SDK passes a binder, not a table containing the property values.
    binder = lua.table()
    assert callback(binder, True, True) is True
    for key, invalid in [('serverRunning', False), ('photoCount', 0)]:
        old = lua.globals().props[key]
        lua.globals().props[key] = invalid
        assert callback(binder, invalid, True) is False
        lua.globals().props[key] = old


def test_preview_and_matte_only_need_a_selection():
    lua = runtime()
    bindings = re.findall(r'enabled = LrView.bind \{ keys = \{ "photoCount" \}, operation = (function\(\).*?end) \}', SOURCE, re.S)
    assert len(bindings) == 2  # Preview Mask, Lightroom masks (Matte)
    for code in bindings:
        callback = lua.execute('return ' + code)
        assert callback(lua.table()) is True
        lua.globals().props.photoCount = 0
        assert callback(lua.table()) is False
        lua.globals().props.photoCount = 7


def test_layout_compacts_and_handles_missing_window_metrics():
    lua = runtime()
    lua.execute('LrSystemInfo={appWindowSize=function() return 1400,1000 end}')
    code = SOURCE[SOURCE.index('local function getDashboardLayout()'):SOURCE.index('-- On Windows Win32')]
    callback = lua.execute(code + '\nreturn getDashboardLayout')
    large = callback()
    lua.execute('LrSystemInfo.appWindowSize=function() return {width=900,height=600} end')
    small = callback()
    assert small.height < large.height
    assert small.viewportWidth < large.viewportWidth
    assert small.contentWidth < small.viewportWidth
    assert small.frameKey != large.frameKey
    lua.execute('LrSystemInfo.appWindowSize=function() error("not available") end')
    assert callback().height >= 280


def test_macos_frame_does_not_restore_a_taller_dashboard_after_window_shrink():
    lua = runtime()
    lua.execute('''
        MaskBridgeUtils.isWindows=function() return false end
        windowHeight=949
        LrSystemInfo={appWindowSize=function() return 1400,windowHeight end}
    ''')
    code = SOURCE[SOURCE.index('local function getDashboardLayout()'):SOURCE.index('-- On Windows Win32')]
    layout = lua.execute(code + '\nreturn getDashboardLayout')
    tall = layout()
    lua.globals().windowHeight = 790  # Still normal width/mode, shorter content.
    short = layout()
    assert short.viewportWidth == tall.viewportWidth
    assert short.height < tall.height
    assert short.frameKey != tall.frameKey
    lua.globals().windowHeight = 791
    assert layout().frameKey == short.frameKey  # Minor resize keeps saved position.
    lua.globals().windowHeight = 949
    assert layout().frameKey == tall.frameKey
    lua.execute('MaskBridgeUtils.isWindows=function() return true end')
    windows_tall = layout()
    lua.globals().windowHeight = 790
    windows_short = layout()
    assert windows_short.height < windows_tall.height
    assert windows_short.frameKey == windows_tall.frameKey  # Windows restores no stale height.


def test_empty_selection_does_not_expand_to_whole_filmstrip():
    lua = runtime()
    lua.execute('''
        active=nil; listCalls=0
        selected={{id=1},{id=2}}
        catalog={getTargetPhoto=function() return active end,
            getTargetPhotos=function() listCalls=listCalls+1; return selected end}
    ''')
    helper = SOURCE[SOURCE.index('local function getSelectedPhotos('):SOURCE.index('local function runPreviewWork(')]
    callback = lua.execute(helper + '\nreturn getSelectedPhotos')
    assert len(callback(lua.globals().catalog)) == 0
    assert lua.globals().listCalls == 0
    lua.execute('active=selected[1]')
    assert len(callback(lua.globals().catalog)) == 2
    assert lua.globals().listCalls == 1
    # Only the guarded helper may ask Lightroom for the whole target list.
    assert SOURCE.count('catalog:getTargetPhotos()') == 1


def destination_runtime(windows=True):
    lua = runtime()
    lua.globals().windows = windows
    lua.execute('''
        MaskBridgeUtils.isWindows=function() return windows end
        props.outputPath='original-images'; props.maskOutputPath='original-masks'
        LrFunctionContext={callWithContext=function(name,fn) fn({}) end}
        LrBinding={makePropertyTable=function() return {} end}
        LrView={bind=function(value) return value end}
        f=setmetatable({}, {__index=function(_,kind)
            return function(_,spec) spec.kind=kind; return spec end
        end})
        panelCalls=0; modalCalls=0; browse=false; failModal=false
        LrDialogs.runOpenPanel=function(spec)
            panelCalls=panelCalls+1; panelSpec=spec
            if chosenPath then return {chosenPath} end
        end
        LrDialogs.presentModalDialog=function(spec)
            modalCalls=modalCalls+1
            assert(closed==1, 'Floating dashboard must close before modal')
            if failModal then error('modal failed') end
            if browse then spec.contents[2].action()
            else spec.contents.bind_to_object.path=editedPath end
            return answer
        end
    ''')
    wrapper = SOURCE[SOURCE.index('        local function settingsDialog('):SOURCE.index('        local function editFormatOptions(')]
    helpers = SOURCE[SOURCE.index('        local function editDestination('):SOURCE.index('        local layout = getDashboardLayout()')]
    callbacks = lua.execute(wrapper + helpers + '\nreturn {choose=chooseDestination,field=destinationField,text=dashboardTextField}')
    return lua, callbacks


@pytest.mark.parametrize('key', ['outputPath', 'maskOutputPath'])
@pytest.mark.parametrize('answer,new_path', [('ok', 'E:/café 日本'), ('cancel', 'E:/discarded'), ('ok', '')])
def test_windows_destination_edits_commit_only_on_ok(key, answer, new_path):
    lua, callbacks = destination_runtime()
    old = lua.globals().props[key]
    lua.globals().answer, lua.globals().editedPath = answer, new_path
    callbacks.choose(key, 'Destination')
    assert lua.globals().props[key] == (new_path if answer == 'ok' else old)
    other = 'maskOutputPath' if key == 'outputPath' else 'outputPath'
    assert lua.globals().props[other] == ('original-masks' if other == 'maskOutputPath' else 'original-images')
    assert lua.globals().closed == lua.globals().reopened == 1


def test_windows_destination_browser_stages_changes_and_cancel_preserves_path():
    lua, callbacks = destination_runtime()
    lua.execute("browse=true; chosenPath='E:/chosen'; answer='cancel'")
    callbacks.choose('outputPath', 'Destination')
    assert lua.globals().props.outputPath == 'original-images'
    assert lua.globals().panelSpec.canChooseFiles is False
    assert lua.globals().panelSpec.canChooseDirectories is True
    assert lua.globals().closed == lua.globals().reopened == 1


def test_windows_destination_modal_failure_preserves_path_and_reopens():
    lua, callbacks = destination_runtime()
    lua.execute('failModal=true')
    callbacks.choose('outputPath', 'Destination')
    assert lua.globals().props.outputPath == 'original-images'
    assert lua.globals().errors == 1
    assert lua.globals().closed == lua.globals().reopened == 1


def test_macos_destination_keeps_inline_field_and_direct_folder_chooser():
    lua, callbacks = destination_runtime(windows=False)
    field = callbacks.field('maskOutputPath', 'same as images', 300)
    assert field.kind == 'edit_field'
    assert field.value == field.tooltip == 'maskOutputPath'
    assert field.placeholder_string == 'same as images'
    lua.globals().chosenPath = 'E:/café 日本'
    callbacks.choose('maskOutputPath', 'Destination')
    assert lua.globals().props.maskOutputPath == 'E:/café 日本'
    assert lua.globals().panelCalls == 1
    assert lua.globals().modalCalls == lua.globals().closed == lua.globals().reopened == 0


def test_windows_destination_has_no_edit_field_in_floating_focus_scope():
    _, callbacks = destination_runtime()
    field = callbacks.field('maskOutputPath', 'same as images', 300)
    assert field.kind == 'static_text'
    assert field.tooltip == 'maskOutputPath'
    assert field.title.transform('') == 'same as images'
    assert field.title.transform('E:/café 日本') == 'E:/café 日本'


@pytest.mark.parametrize('key', ['newPresetName', 'customClasses', 'excludeClasses', 'customResolution'])
@pytest.mark.parametrize('answer', ['ok', 'cancel'])
def test_windows_other_text_edits_use_modal_transaction(key, answer):
    lua, callbacks = destination_runtime()
    lua.globals().props[key] = 'original'
    lua.globals().answer = answer
    if key == 'newPresetName':
        lua.execute('''windowsPresetDraft='original'
            function showDashboard()
                reopened=reopened+1
                props.newPresetName=windowsPresetDraft
            end''')
    lua.execute('''LrDialogs.presentModalDialog=function(spec)
        assert(closed==1)
        spec.contents.bind_to_object.value='café 日本'
        return answer
    end''')
    field = callbacks.text(key, 'Edit', lua.table_from({'fill_horizontal': 1}))
    assert field.kind == 'row'
    assert field[1].kind == 'static_text'
    assert field[2].kind == 'push_button'
    field[2].action()
    assert lua.globals().props[key] == ('café 日本' if answer == 'ok' else 'original')
    assert lua.globals().closed == lua.globals().reopened == 1
    assert lua.globals().props.outputPath == 'original-images'


def test_macos_text_controls_preserve_original_options():
    options = {'width_in_chars': 5, 'immediate': True, 'enabled': False, 'visible': False}
    lua, callbacks = destination_runtime(windows=False)
    field = callbacks.text('customResolution', 'Size', lua.table_from(options))
    assert field.kind == 'edit_field'
    assert field.value == 'customResolution'
    for key, value in options.items():
        assert field[key] == value


def test_floating_dashboard_has_no_unwrapped_edit_fields():
    # Prevent another field from silently reintroducing the Windows Tab hang.
    view = SOURCE[SOURCE.index('        local layout = getDashboardLayout()'):]
    assert 'f:edit_field' not in view


def test_windows_custom_size_visibility_is_applied_to_leaf_controls():
    lua, callbacks = destination_runtime()
    field = callbacks.text('customResolution', 'Size', lua.table_from({'visible': False, 'enabled': False}))
    assert field[1].visible is False
    assert field[2].visible is False
    assert field[2].enabled is False


UTILS = (Path(__file__).resolve().parents[2] / 'MaskBridgeUtils.lua').read_text(encoding='utf-8')
ATTACH = UTILS[UTILS.index('function MaskBridgeUtils.attachDashboardWindow('):UTILS.index('-- Stop Server (waits')]


def attach_runtime(running=True, attach_on=None, close_after=None):
    lua = pytest.importorskip('lupa.lua51').LuaRuntime(unpack_returned_tuples=True)
    lua.execute('''
        posts=0; sleeps=0; open=true; running=%s; attachOn=%s; closeAfter=%s
        LrTasks={sleep=function() sleeps=sleeps+1 end}
        MaskBridgeUtils={isServerRunning=function() return running end,
            httpPost=function(endpoint, body)
                assert(endpoint=='/dashboard-window' and body=='{}')
                posts=posts+1
                if closeAfter and posts>=closeAfter then open=false end
                if attachOn and posts>=attachOn then return '{"status": "ok", "found": 1, "attached": 1}' end
                return '{"status": "ok", "found": 0, "attached": 0}'
            end}
    ''' % ('true' if running else 'false', attach_on or 'nil', close_after or 'nil'))
    lua.execute(ATTACH)
    return lua, lua.eval('function() return MaskBridgeUtils.attachDashboardWindow(function() return open end, nil) end')


def test_dashboard_window_attaches_once_visible():
    lua, attach = attach_runtime(attach_on=3)
    assert attach() is True
    assert lua.globals().posts == 3


def test_dashboard_window_gives_up_and_stays_usable():
    lua, attach = attach_runtime()
    assert attach() is False
    assert lua.globals().posts == 10


def test_dashboard_window_needs_the_engine_and_an_open_dashboard():
    lua, attach = attach_runtime(running=False)
    assert attach() is False and lua.globals().posts == 0
    lua, attach = attach_runtime(close_after=2)
    assert attach() is False and lua.globals().posts == 2


ON_SHOW = SOURCE[SOURCE.index('            onShow = function(dialogFunctions)'):SOURCE.index('            windowWillClose = function()')]
ATTACH_ON_SHOW = ON_SHOW[ON_SHOW.index('                if MaskBridgeUtils.isWindows() then\n                    LrTasks.startAsyncTask'):
                         ON_SHOW.index('                -- macOS: show the welcome here')]


@pytest.mark.parametrize('windows', [True, False])
def test_dashboard_show_attaches_once_the_engine_runs(windows):
    lua = pytest.importorskip('lupa.lua51').LuaRuntime(unpack_returned_tuples=True)
    lua.globals().windows = windows
    lua.execute('''
        props={_dialogOpen=true, _serverStartupDone=false}; checks=0; sleeps=0; attached=0
        function logMsg() end
        LrTasks={startAsyncTask=function(fn) fn() end, sleep=function() sleeps=sleeps+1 end}
        MaskBridgeUtils={isWindows=function() return windows end,
            isServerRunning=function() checks=checks+1; return checks>=3 end,
            attachDashboardWindow=function(isOpen, log)
                attached=attached+1; isOpenAtAttach=isOpen(); stillOpen=isOpen
                assert(log==logMsg)
            end}
    ''')
    lua.execute(ATTACH_ON_SHOW)
    g = lua.globals()
    if not windows:
        assert g.attached == 0 and g.checks == 0
        return
    assert (g.attached, g.sleeps) == (1, 2)  # Waited for the engine, then attached once.
    assert g.isOpenAtAttach is True
    g.props._dialogOpen = False
    assert g.stillOpen() is False  # The retry loop sees the dashboard close.
