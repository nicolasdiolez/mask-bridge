"""Windows, 8 November 2026: 1.2.0 added to a Lightroom still running a 1.1.1
engine read the shared state file, showed "AI ready" and sent Generate to the
old engine, which answered "License required" on every photo.

The plugin now only treats an engine of its own version as ready, and replaces
any other one (no version, or another version) before starting its own.
Lua 5.1 via lupa, on the SDK double used by the Matte tests.
"""
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[2]
STATE = (PLUGIN / "backend" / ".server_state.json").as_posix()

# In-memory engines keyed by port, an LrHttp double that answers for them, a
# state file served from the SDK double's `files`, and a launcher that starts
# "our" engine the way the real one does: new port, new token, new state.
ENGINE_DOUBLE = '''
    state_path = ...
    j = require 'dkjson'
    engines = {}; events = {}; posts = {}; log_lines = {}; launches = 0; slept = 0
    our_version = require('MaskBridgeConfig').VERSION

    function set_state(port, token, pid)
        files[state_path] = j.encode({port = port, token = token, pid = pid})
    end
    function run_engine(port, version, pid, token, opts)
        engines[port] = {version = version, pid = pid, alive = true,
            obeys = not (opts and opts.ignores_shutdown)}
        set_state(port, token, pid)
    end

    local sdk_open = io.open
    io.open = function(p, mode)
        if p == state_path then
            local body = files[p]
            if type(body) ~= "string" then return nil end
            return {read = function() return body end, close = function() end}
        end
        if p:match("maskbridge_debug%.log$") then
            return {write = function(_, s) log_lines[#log_lines + 1] = s end, close = function() end}
        end
        return sdk_open(p, mode)
    end

    local function split(url)
        local port, path = url:match("^http://127%.0%.0%.1:(%d+)(/.*)$")
        return tonumber(port), path
    end
    http = {
        get = function(url, headers)
            local port, path = split(url)
            local token = headers and headers[1] and headers[1].value
            events[#events + 1] = {kind = "get", port = port, path = path, token = token}
            local e = engines[port]
            if not e or not e.alive then return nil end
            if path == "/health" then
                return j.encode({status = "ok", version = e.version, pid = e.pid, models_loaded = true})
            elseif path == "/shutdown" then
                if e.obeys then e.alive = false; files[state_path] = nil end
                return '{"status":"shutting_down"}'
            end
        end,
        post = function(url, body, headers)
            local port, path = split(url)
            posts[#posts + 1] = {port = port, path = path}
            return '{"status":"success"}', {status = 200}
        end,
    }
    local sdk_import = import
    function import(n) if n == "LrHttp" then return http end return sdk_import(n) end

    local tasks = import 'LrTasks'
    tasks.sleep = function(s)
        slept = slept + s
        if s == 20 then utils._shuttingDown = true end   -- end MaskBridgeInit's keep-alive loop
    end
    tasks.execute = function(cmd)
        launches = launches + 1
        events[#events + 1] = {kind = "launch", slept = slept}
        run_engine(9877, our_version, 2000, "our-token")
    end

    -- sdk_double replaces getServerPort/httpPost on its copy: load a pristine one.
    package.loaded.MaskBridgeUtils = nil
    utils = require 'MaskBridgeUtils'
    files[plugin_path .. "/backend/maskbridge_engine/maskbridge_engine"] = true
    files[plugin_path .. "/backend/models/rfdetr_seg_medium.onnx"] = true
'''


@pytest.fixture
def lua():
    runtime = pytest.importorskip("lupa.lua51").LuaRuntime(unpack_returned_tuples=True)
    runtime.globals().plugin_path = PLUGIN.as_posix()
    runtime.execute((Path(__file__).with_name("sdk_double.lua")).read_text())
    runtime.execute(ENGINE_DOUBLE, STATE)
    return runtime


def events(lua):
    return [dict(e.items()) for e in lua.globals().events.values()]


def log(lua):
    return "".join(lua.globals().log_lines.values())


# --- Readiness ------------------------------------------------------------------

@pytest.mark.parametrize("version", [None, "1.1.1", "1.3.0"])
def test_engine_of_another_release_is_not_ready(lua, version):
    lua.globals().run_engine(9876, version, 1111, "old-token")
    utils = lua.globals().utils
    assert utils.isServerRunning() is False
    assert utils.isEngineReady() is False
    # Nothing is sent to it: its answer ("License required" for 1.1.1) can
    # never reach the Dashboard.
    body, err = utils.httpPost("/process", "{}")
    assert body is None and err == "Server not running"
    assert len(lua.globals().posts) == 0


def test_engine_of_our_release_is_ready_and_used(lua):
    lua.globals().run_engine(9877, lua.globals().our_version, 2000, "our-token")
    utils = lua.globals().utils
    assert utils.isServerRunning() is True and utils.isEngineReady() is True
    assert utils.httpPost("/process", "{}") == '{"status":"success"}'
    assert dict(lua.globals().posts[1].items()) == {"port": 9877, "path": "/process"}


# --- Starting -------------------------------------------------------------------

@pytest.mark.parametrize("version", [None, "1.1.1"])
def test_start_stops_the_foreign_engine_first(lua, version):
    lua.globals().run_engine(9876, version, 1111, "old-token")
    utils = lua.globals().utils
    assert utils.startServer(None) is True
    seen = events(lua)
    shutdown = [i for i, e in enumerate(seen) if e.get("path") == "/shutdown"]
    launch = [i for i, e in enumerate(seen) if e["kind"] == "launch"]
    assert len(shutdown) == 1 and len(launch) == 1 and shutdown[0] < launch[0]
    assert seen[shutdown[0]]["port"] == 9876 and seen[shutdown[0]]["token"] == "old-token"
    assert lua.globals().engines[9876].alive is False
    # Ours now answers, and requests go to it.
    assert utils.isEngineReady() is True
    assert utils.httpPost("/process", "{}") == '{"status":"success"}'
    assert lua.globals().posts[1].port == 9877
    text = log(lua)
    assert f"is version {version or 'unknown'}, not {lua.globals().our_version}: asking it to stop" in text
    assert "Previous engine stopped after 0.5s" in text


def test_init_replaces_the_engine_left_by_an_earlier_release(lua):
    # LrInitPlugin of 1.2.0 runs while the 1.1.1 engine is still up.
    lua.globals().run_engine(9876, "1.1.1", 1111, "old-token")
    lua.execute('dofile(plugin_path .. "/MaskBridgeInit.lua")')
    seen = events(lua)
    paths = [e.get("path") or e["kind"] for e in seen]
    assert paths.index("/shutdown") < paths.index("launch")
    assert lua.globals().launches == 1
    assert lua.globals().utils.isEngineReady() is True


def test_start_still_runs_ours_when_the_foreign_engine_ignores_shutdown(lua):
    lua.globals().run_engine(9876, "1.1.1", 1111, "old-token", lua.table_from({"ignores_shutdown": True}))
    utils = lua.globals().utils
    assert utils.startServer(None) is True
    launch = next(e for e in events(lua) if e["kind"] == "launch")
    assert launch["slept"] <= 3.0                       # bounded wait before starting ours
    assert lua.globals().engines[9876].alive is True    # left to its heartbeat watchdog
    assert utils.isEngineReady() is True
    assert utils.httpPost("/process", "{}") == '{"status":"success"}'
    assert lua.globals().posts[1].port == 9877
    assert "still answering after 3s; starting ours anyway" in log(lua)


def test_engine_of_our_release_is_reused_without_restart(lua):
    lua.globals().run_engine(9877, lua.globals().our_version, 2000, "our-token")
    assert lua.globals().utils.startServer(None) is True
    assert lua.globals().launches == 0
    assert all(e.get("path") != "/shutdown" for e in events(lua))
    assert log(lua) == ""


def test_cold_start_sends_no_shutdown(lua):
    assert lua.globals().utils.startServer(None) is True
    assert lua.globals().launches == 1
    assert all(e.get("path") != "/shutdown" for e in events(lua))
    assert log(lua) == ""


# --- Stopping (unchanged) -------------------------------------------------------

def test_lightroom_quit_stops_our_engine_with_its_token(lua):
    lua.globals().run_engine(9877, lua.globals().our_version, 2000, "our-token")
    lua.execute('dofile(plugin_path .. "/MaskBridgeShutdown.lua")')
    shutdown = [e for e in events(lua) if e.get("path") == "/shutdown"]
    assert len(shutdown) == 1 and shutdown[0]["port"] == 9877 and shutdown[0]["token"] == "our-token"
    assert lua.globals().engines[9877].alive is False
    assert lua.globals().utils.isServerRunning() is False


def test_reload_restarts_our_engine(lua):
    lua.globals().run_engine(9877, lua.globals().our_version, 2000, "our-token")
    utils = lua.globals().utils
    utils.stopServer(None)
    assert lua.globals().engines[9877].alive is False
    assert utils.startServer(None) is True
    assert lua.globals().launches == 1
    assert [e.get("path") for e in events(lua)].count("/shutdown") == 1
