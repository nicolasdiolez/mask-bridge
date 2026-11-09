local LrPathUtils = import 'LrPathUtils'
local LrFileUtils = import 'LrFileUtils'
local LrTasks = import 'LrTasks'
local MaskBridgeConfig = require 'MaskBridgeConfig'

local MaskBridgeUtils = {}

-- Lightroom tasks cooperate at yields. Claim before starting the task, and
-- retain ownership through all workers and catalogue cleanup.
local operation = nil
local reservedOutputs = {}

function MaskBridgeUtils.beginOperation(name)
    if operation then return nil end
    operation = { name = name }
    reservedOutputs = {}
    return operation
end

function MaskBridgeUtils.endOperation(token)
    if token == operation then operation = nil; reservedOutputs = {} end
end

function MaskBridgeUtils.isBusy() return operation ~= nil end

function MaskBridgeUtils.snapshot(props)
    local result = {}
    local iterator, state, first
    if type(props.pairs) == "function" then
        iterator, state, first = props:pairs()
    else
        iterator, state, first = pairs(props)
    end
    for key, value in iterator, state, first do result[key] = value end
    return result
end

function MaskBridgeUtils.runInline(fn) return fn() end

-- Lua 5.1 cannot yield from a generic-for iterator. Creating an export
-- session there makes Lightroom reject it as a call on the main UI task.
-- Keep SDK work in ordinary function bodies, with a bounded active batch.
function MaskBridgeUtils.forEachExportRendition(photos, settings, batchSize, progress, consume)
    assert(batchSize >= 1 and batchSize == math.floor(batchSize), "Invalid export batch size")
    local LrExportSession = import 'LrExportSession'
    for first = 1, #photos, batchSize do
        if progress:isCanceled() then break end
        local chunk = {}
        for i = first, math.min(#photos, first + batchSize - 1) do
            chunk[#chunk + 1] = photos[i]
        end
        local session = LrExportSession({photosToExport=chunk, exportSettings=settings})
        -- Drain the batch already started even after cancellation. The consumer
        -- waits for each render and deletes canceled output; no new batch starts.
        for _, rendition in session:renditions() do consume(rendition) end
    end
end

function MaskBridgeUtils.startOperation(name, fn)
    local token = MaskBridgeUtils.beginOperation(name)
    local dialogs = import 'LrDialogs'
    if not token then
        dialogs.showBezel(LOC("$$$/MaskBridge/Operation/Busy=A Mask Bridge operation is already running."), 3)
        return
    end
    LrTasks.startAsyncTask(function()
        local ok, err = LrTasks.pcall(fn)
        MaskBridgeUtils.endOperation(token)
        if not ok then dialogs.showError(tostring(err)) end
    end)
end

-- Keep existing files, including originals and symlinks to originals. Reserve
-- the final name before a worker yields so two workers cannot choose it.
function MaskBridgeUtils.uniqueOutputPath(path)
    local stem = LrPathUtils.removeExtension(path)
    local extension = path:sub(#stem + 1)
    local candidate, index = path, 1
    while LrFileUtils.exists(candidate) or reservedOutputs[candidate:lower()] do
        index = index + 1
        candidate = stem .. "_" .. index .. extension
    end
    reservedOutputs[candidate:lower()] = true
    return candidate
end

-- Naming Constants
MaskBridgeUtils.NAMING_STANDARD = "standard"     -- .mask.png
MaskBridgeUtils.NAMING_UNDERSCORE = "underscore" -- _mask.png
MaskBridgeUtils.NAMING_HYPHEN = "hyphen"         -- -mask.png
MaskBridgeUtils.NAMING_SUFFIX = "suffix"         -- _MaskBridge.png

-- Dashboard mode flag: when true, Dashboard handles AI processing,
-- so ExportProvider acts as a passthrough (just lets LR render files).
MaskBridgeUtils._dashboardMode = false

function MaskBridgeUtils.setDashboardMode(enabled)
    MaskBridgeUtils._dashboardMode = enabled
end

-- Single-dashboard guard. The Dashboard menu item (both the Library and the
-- File > Export entries) re-runs MaskBridgeDashboard.lua on every click; without
-- this, each click would stack another floating dashboard. We track the live
-- dashboard here — this state persists because the module is require-cached for
-- the plugin session — and expose its 'toFront' so a repeat launch just raises
-- the existing window. A monotonic token guards the close handler so a stale
-- window cannot clear the state after a newer one already registered (this
-- happens with the Windows close/reopen workaround in the export flows).
MaskBridgeUtils._dashboardToken = nil
MaskBridgeUtils._dashboardClose = nil

function MaskBridgeUtils.isDashboardOpen()
    return MaskBridgeUtils._dashboardToken ~= nil
end

-- Register a freshly-opened dashboard and its close function.
-- Returns a token the caller must pass to clearDashboard() on close.
function MaskBridgeUtils.registerDashboard(closeFn)
    MaskBridgeUtils._dashboardToken = (MaskBridgeUtils._dashboardToken or 0) + 1
    MaskBridgeUtils._dashboardClose = closeFn
    return MaskBridgeUtils._dashboardToken
end

-- Clear the live-dashboard state, but only if `token` still identifies the
-- current dashboard (a newer one may have taken over via close/reopen).
function MaskBridgeUtils.clearDashboard(token)
    if MaskBridgeUtils._dashboardToken == token then
        MaskBridgeUtils._dashboardToken = nil
        MaskBridgeUtils._dashboardClose = nil
    end
end

-- Close the existing dashboard (if any). Used when re-launching from the menu:
-- the SDK's toFront does NOT reliably restore a minimized floating dialog (on
-- either platform), so instead of trying to raise the old window we close it
-- and open a fresh, frontmost one. pcall-protected against a stale reference.
function MaskBridgeUtils.closeDashboard()
    if MaskBridgeUtils._dashboardClose then
        pcall(MaskBridgeUtils._dashboardClose)
    end
end

-- Cross-platform detection
function MaskBridgeUtils.isWindows()
    return WIN_ENV == true
end

-- Generate mask path based on pattern
function MaskBridgeUtils.getMaskPath(directory, filenameStem, pattern, maskDirectory)
    local suffix = ".mask.png" -- Default standard

    if pattern == MaskBridgeUtils.NAMING_UNDERSCORE then
        suffix = "_mask.png"
    elseif pattern == MaskBridgeUtils.NAMING_HYPHEN then
        suffix = "-mask.png"
    elseif pattern == MaskBridgeUtils.NAMING_SUFFIX then
        suffix = "_MaskBridge.png"
    end

    -- If separate mask directory is provided, use it
    if maskDirectory and maskDirectory ~= "" then
        return LrPathUtils.child(maskDirectory, filenameStem .. suffix)
    end

    return LrPathUtils.child(directory, filenameStem .. suffix)
end

-- Sanitize a mask label for use in filenames: remove special chars,
-- replace spaces with underscores. Exposed so callers can dedupe on the
-- SANITIZED form (two different raw names can collapse to the same label).
function MaskBridgeUtils.sanitizeLabel(maskLabel)
    local safeLabel = maskLabel or "mask"
    -- Preserve UTF-8; reject only filesystem metacharacters and controls.
    safeLabel = safeLabel:gsub('[%z\1-\31<>:"/\\|?*]', "_"):gsub("%s+", "_"):gsub("[%. ]+$", "")
    if safeLabel == "" then safeLabel = "mask" end
    return safeLabel
end

-- Generate mask path with a label suffix (for individual multi-mask exports)
-- e.g., "photo_Subject.mask.png" or "photo_Sky.mask.png"
function MaskBridgeUtils.getMaskPathWithLabel(directory, filenameStem, pattern, maskLabel, maskDirectory)
    local labeledStem = filenameStem .. "_" .. MaskBridgeUtils.sanitizeLabel(maskLabel)
    return MaskBridgeUtils.getMaskPath(directory, labeledStem, pattern, maskDirectory)
end

-- Apply TIFF bit depth + compression onto an exportSettings table.
-- Single source of truth: Dashboard and Matte used two divergent key sets
-- (LR_tiff_bitDepth/compressionMethod vs LR_tiff_bitsPerChannel/compressionType),
-- so at least one flow silently ignored the user's TIFF settings. The SDK keys
-- are LR_export_bitDepth and LR_tiff_compressionMethod; the legacy aliases are
-- also set (harmless when unknown) as a belt-and-braces for older LR versions.
function MaskBridgeUtils.applyTiffSettings(exportSettings, bitDepth, compression)
    local depth = (bitDepth == 8) and 8 or 16
    exportSettings.LR_export_bitDepth = depth
    exportSettings.LR_tiff_bitDepth = depth
    local method = "compressionMethod_LZW"
    if compression == "None" then
        method = "compressionMethod_None"
    elseif compression == "ZIP" then
        method = "compressionMethod_ZIP"
    end
    exportSettings.LR_tiff_compressionMethod = method
end

-- Normalize path for Windows
function MaskBridgeUtils.normalizePath(path)
    if MaskBridgeUtils.isWindows() then
        return string.gsub(path, "/", "\\")
    end
    return path
end

-- Find Python 3
function MaskBridgeUtils.findPython3()
    if MaskBridgeUtils.isWindows() then
        -- Windows: check PATH first
        local windowsPaths = { "python", "python3" }
        for _, p in ipairs(windowsPaths) do
            if LrTasks.execute('"' .. p .. '" --version 2>nul') == 0 then
                return p
            end
        end
        -- Try Windows Store / AppData locations
        local home = LrPathUtils.getStandardFilePath('home')
        local localAppData = home and LrPathUtils.child(home, "AppData/Local") or ""
        local commonWinPaths = {
            LrPathUtils.child(localAppData, "Programs/Python/Python312/python.exe"),
            LrPathUtils.child(localAppData, "Programs/Python/Python311/python.exe"),
            LrPathUtils.child(localAppData, "Programs/Python/Python310/python.exe"),
        }
        for _, p in ipairs(commonWinPaths) do
            if LrFileUtils.exists(p) then return p end
        end
    else
        -- macOS
        local macPaths = { "/opt/homebrew/bin/python3", "/usr/local/bin/python3", "/usr/bin/python3" }
        for _, p in ipairs(macPaths) do
            if LrFileUtils.exists(p) then return p end
        end
    end
    return MaskBridgeUtils.isWindows() and "python" or "python3"
end

-- Get plugin path
function MaskBridgeUtils.getPluginPath()
    return _PLUGIN.path
end

-- Get model directory
function MaskBridgeUtils.getModelDir()
    return LrPathUtils.child(MaskBridgeUtils.getPluginPath(), "backend/models")
end

-- Escape argument for safe shell command execution (cross-platform)
function MaskBridgeUtils.shellEscape(str)
    if not str then return '""' end
    str = tostring(str)
    if MaskBridgeUtils.isWindows() then
        -- cmd expands percent variables even inside quotes; fail explicitly
        -- in the legacy CLI path. Normal HTTP processing supports these names.
        if str:find('[%%!"%z\r\n]') then error("This path requires the running AI server (unsupported shell character)") end
        return '"' .. str .. '"'
    else
        return "'" .. string.gsub(str, "'", "'\\''") .. "'"
    end
end

-- Safe cross-platform file or directory opener
function MaskBridgeUtils.openPath(path)
    if not path or path == "" then return end
    LrTasks.startAsyncTask(function()
        if MaskBridgeUtils.isWindows() then
            LrTasks.execute('start "" ' .. MaskBridgeUtils.shellEscape(MaskBridgeUtils.normalizePath(path)))
        else
            LrTasks.execute('open ' .. MaskBridgeUtils.shellEscape(path))
        end
    end)
end

-- Execute command with proper quoting.
-- Callers embed output redirections in cmd themselves; the old optional
-- logFile parameter was never used and its Windows quoting was broken.
function MaskBridgeUtils.executeCommand(cmd)
    if MaskBridgeUtils.isWindows() then
        return LrTasks.execute('cmd /d /v:off /s /c "' .. cmd .. '"')
    end
    return LrTasks.execute(cmd)
end

-- Get backend engine classification ("binary" or "script") and absolute path
function MaskBridgeUtils.getBackendEngineInfo()
    local backendDir = LrPathUtils.child(MaskBridgeUtils.getPluginPath(), "backend")
    local binaryName = MaskBridgeUtils.isWindows() and "maskbridge_engine.exe" or "maskbridge_engine"
    
    local binaryPath = LrPathUtils.child(LrPathUtils.child(backendDir, "maskbridge_engine"), binaryName)
    if not LrFileUtils.exists(binaryPath) then
        binaryPath = LrPathUtils.child(backendDir, binaryName)
    end
    
    if LrFileUtils.exists(binaryPath) then
        return "binary", binaryPath
    else
        local cliPath = LrPathUtils.child(backendDir, "cli.py")
        return "script", cliPath
    end
end

-- Get Binary/Python execution command string for the backend engine
function MaskBridgeUtils.getBackendEngine()
    local engineType, enginePath = MaskBridgeUtils.getBackendEngineInfo()
    if engineType == "binary" then
        return MaskBridgeUtils.shellEscape(MaskBridgeUtils.normalizePath(enginePath))
    else
        local python3 = MaskBridgeUtils.findPython3()
        return string.format('%s %s', MaskBridgeUtils.shellEscape(python3), MaskBridgeUtils.shellEscape(MaskBridgeUtils.normalizePath(enginePath)))
    end
end

-- Server Port Management
--
-- The server publishes .server_port and .server_token next to the backend, but
-- a plugin installed read-only (shared Modules folder, mounted disk image,
-- managed Mac) cannot be written to; the backend then falls back to the
-- per-user application-support directory. Both locations are resolved here,
-- backend first, so the normal install is unchanged and the locked-down one
-- still finds its server instead of silently degrading to a PyInstaller cold
-- start per image.
--
-- Deliberately not cached: which location is live depends on where the running
-- server could write, and that can change between two starts.
local function runtimeStateCandidates(name)
    if MaskBridgeUtils.isWindows() then
        -- The SDK resolves redirected appData folders. The launcher passes
        -- exactly this location to Python; never trust shared plugin state.
        local base = assert(LrPathUtils.getStandardFilePath('appData'), "Windows appData unavailable")
        return { LrPathUtils.child(base, "MaskBridge/Runtime-v2/" .. name) }
    end
    local candidates = {
        LrPathUtils.child(MaskBridgeUtils.getPluginPath(), "backend/" .. name),
    }
    local home = LrPathUtils.getStandardFilePath('home')
    if home then
        candidates[2] = LrPathUtils.child(home,
            "Library/Application Support/MaskBridge/" .. name)
    end
    return candidates
end

function MaskBridgeUtils.getLogPath(name)
    if MaskBridgeUtils.isWindows() then return runtimeStateCandidates(name)[1] end
    return LrPathUtils.child(_PLUGIN.path, name)
end

-- Existing file wins; otherwise the canonical backend location, so callers
-- always get a usable path to report or to delete.
local function resolveRuntimeState(name)
    local candidates = runtimeStateCandidates(name)
    for _, path in ipairs(candidates) do
        if LrFileUtils.exists(path) then return path end
    end
    return candidates[1]
end

-- Remove a runtime file from BOTH locations: a stale port file left in the
-- other one would make isServerRunning() poll a dead port forever.
local function deleteRuntimeState(name)
    for _, path in ipairs(runtimeStateCandidates(name)) do
        if LrFileUtils.exists(path) then LrFileUtils.delete(path) end
    end
end

local function readRuntimeState()
    local json = dofile(LrPathUtils.child(_PLUGIN.path, "dkjson.lua"))
    for _, path in ipairs(runtimeStateCandidates(".server_state.json")) do
        local f = io.open(path, "r")
        if f then
            local body = f:read("*all"); f:close()
            local record = json.decode(body)
            if type(record) == "table" and type(record.port) == "number"
                and record.port == math.floor(record.port) and record.port > 0 and record.port < 65536
                and type(record.token) == "string" and record.token:match("^[%w_-]+$") then
                return record
            end
        end
    end
end

function MaskBridgeUtils.getServerPortFile()
    return resolveRuntimeState(".server_port")
end

-- Per-run shared secret written by the server next to the port file. Every
-- endpoint except /health requires it: binding to 127.0.0.1 keeps remote hosts
-- out but not other local processes, nor a web page POSTing to a guessed
-- localhost port (see the rationale in server.py). Cached after the first read
-- and invalidated on every start/stop so a restarted server is never addressed
-- with the previous run's token.
local SERVER_TOKEN = nil

-- Token of the last state record whose engine proved to be ours; httpPost
-- sends nothing to any other engine.
local verifiedToken = nil

function MaskBridgeUtils.getServerTokenFile()
    return resolveRuntimeState(".server_token")
end

function MaskBridgeUtils.forgetServerToken()
    SERVER_TOKEN = nil
    verifiedToken = nil
end

function MaskBridgeUtils.getServerToken()
    local record = readRuntimeState()
    return record and record.token
end

function MaskBridgeUtils.getServerPort()
    local record = readRuntimeState()
    return record and record.port
end

-- Any engine answering for this state record, whatever its version.
local function probeHealth(state)
    local http = import 'LrHttp'
    local ok, body = LrTasks.pcall(function()
        return http.get(string.format("http://127.0.0.1:%d/health", state.port), nil, 2)
    end)
    if not ok or not body then return nil end
    local json = dofile(LrPathUtils.child(_PLUGIN.path, "dkjson.lua"))
    local decoded, health = pcall(json.decode, body)
    if decoded and type(health) == "table" and health.status == "ok" and health.pid == state.pid then
        return health
    end
end

-- Every Mask Bridge release with this plugin id shares the state file. An
-- engine started by another release (8 November 2026: a 1.1.1 engine still
-- running when 1.2.0 was added without quitting Lightroom) is not ours: it
-- may speak another protocol, and 1.1.1 answered "License required".
local function isOwnEngine(health)
    return health.version == MaskBridgeConfig.VERSION
end

-- Always-on plugin log for engine lifecycle events that the user cannot see.
local function engineLog(msg)
    local f = io.open(MaskBridgeUtils.getLogPath("maskbridge_debug.log"), "a")
    if f then
        f:write(os.date("%H:%M:%S") .. " | ENGINE: " .. tostring(msg) .. "\n")
        f:close()
    end
end

function MaskBridgeUtils.getServerHealth()
    local state = readRuntimeState()
    if not state then return nil end
    local health = probeHealth(state)
    if health and isOwnEngine(health) then
        verifiedToken = state.token
        return health
    end
end

function MaskBridgeUtils.isServerRunning()
    return MaskBridgeUtils.getServerHealth() ~= nil
end

function MaskBridgeUtils.isEngineReady()
    local health = MaskBridgeUtils.getServerHealth()
    return health ~= nil and health.models_loaded == true
end

local _serverStarting = false

function MaskBridgeUtils.isServerStarting()
    return _serverStarting
end

-- Windows engine launch (1.2.0). Microsoft Defender classified the former
-- launcher (a hidden script interpreter given an encoded script) as
-- Trojan:Win32/ClickFix and deleted it, so the engine never started. No
-- script interpreter, encoded command or encoded path is used any more.
--
-- Two steps keep the W08 guarantees:
--   1. launch.cmd, written as UTF-8 in the state directory, runs the engine
--      with --spawn-server. chcp 65001 makes cmd read the following lines as
--      UTF-8, delayed expansion is off and every % is doubled, so no user path
--      is interpreted. The engine then starts its own server process with
--      CreateProcessW (no shell, no console window) and exits.
--   2. The command handed to LrTasks.execute (cmd /c) is pure ASCII: the
--      literal path of launch.cmd when it is ASCII without % or !, otherwise
--      %APPDATA%\Adobe\Lightroom\MaskBridge\Runtime-v2\launch.cmd, which cmd
--      expands internally without any code page loss. A leading @ keeps the
--      quoted path intact whether or not cmd strips outer quotes.
-- The launcher checks a nonce given on the command line (exit code 9 when it
-- differs), so a %APPDATA% that does not lead to the SDK's appData folder
-- fails visibly instead of running another, older launch.cmd. A non-ASCII
-- appData folder that is not %APPDATA%\Adobe\Lightroom (profile redirected
-- by policy elsewhere) is refused: cmd cannot be given its path losslessly.
--
-- Pure: no SDK call. Returns the launch.cmd content, the ASCII command and
-- the literal launch.cmd path to write. Errors carry a user-readable reason.
local LAUNCH_NONCE_MISMATCH = 9

local function checkedWindowsPath(label, path)
    if type(path) ~= "string" or path == "" then
        error("Mask Bridge cannot start the engine: no " .. label .. " path", 0)
    end
    -- Windows paths cannot contain a double quote; control characters or a
    -- line break would end the command line of launch.cmd.
    if path:find('["%z\1-\31\127]') then
        error("Mask Bridge cannot start the engine: the " .. label
            .. " path contains a quote or a control character: " .. path, 0)
    end
    return path
end

function MaskBridgeUtils.windowsLaunchFiles(binaryPath, modelDir, stateDir, appDataPath, nonce)
    checkedWindowsPath("engine", binaryPath)
    checkedWindowsPath("model folder", modelDir)
    checkedWindowsPath("state folder", stateDir)
    if type(nonce) ~= "string" or not nonce:match("^%x+$") then
        error("Mask Bridge cannot start the engine: invalid launch nonce", 0)
    end
    if binaryPath:sub(-1) == "\\" then
        error("Mask Bridge cannot start the engine: invalid engine path " .. binaryPath, 0)
    end
    -- A backslash before the closing quote would escape it for the engine's
    -- command-line parser: "C:\dir\" becomes C:\dir".
    local function directory(path)
        if path:sub(-1) == "\\" then return path .. "." end
        return path
    end
    local function quoted(path)
        return '"' .. (path:gsub("%%", "%%%%")) .. '"'
    end
    stateDir = directory(stateDir)
    local content = table.concat({
        "@echo off",
        "setlocal DisableDelayedExpansion",
        'if not "%~1"=="' .. nonce .. '" exit /b ' .. LAUNCH_NONCE_MISMATCH,
        -- Full path: Lightroom's PATH may lack System32.
        '"%SystemRoot%\\System32\\chcp.com" 65001 >nul',
        quoted(binaryPath) .. " --spawn-server --model-dir " .. quoted(directory(modelDir))
            .. " --state-dir " .. quoted(stateDir)
            .. " >" .. quoted(stateDir .. "\\launch.log") .. " 2>&1",
        "exit /b %errorlevel%",
        "",
    }, "\r\n")
    local launcherPath = stateDir .. "\\launch.cmd"
    local target
    if not launcherPath:find("[^\32-\126]") and not launcherPath:find("[%%!]") then
        target = launcherPath
    else
        local suffix = "\\MaskBridge\\Runtime-v2"
        local appData = type(appDataPath) == "string" and appDataPath:gsub("\\+$", "") or nil
        if not appData or stateDir ~= appData .. suffix
            or appData:lower():sub(-#"\\adobe\\lightroom") ~= "\\adobe\\lightroom" then
            error("Mask Bridge cannot start the engine from this Windows profile folder "
                .. "(non-ASCII path outside %APPDATA%\\Adobe\\Lightroom): " .. stateDir, 0)
        end
        target = "%APPDATA%\\Adobe\\Lightroom" .. suffix .. "\\launch.cmd"
    end
    return content, '@"' .. target .. '" ' .. nonce, launcherPath
end

-- Write launch.cmd and read it back: a launcher that is missing or truncated
-- must stop the start now, not after the 90 s wait.
local function writeWindowsLauncher(path, content)
    local f, err = io.open(path, "wb")
    if not f then error("Mask Bridge cannot write the engine launcher " .. path .. ": " .. tostring(err), 0) end
    local written, werr = f:write(content)
    f:close()
    local r = io.open(path, "rb")
    local back = r and r:read("*a")
    if r then r:close() end
    if not written or back ~= content then
        error("Mask Bridge cannot write the engine launcher " .. path .. ": " .. tostring(werr or "content differs"), 0)
    end
end

-- Ask an engine of another release to stop, with its own token (as
-- stopServer does), and wait a few seconds for it to go quiet. If it keeps
-- answering, ours starts anyway: it writes a new state record, and the old
-- one exits by itself once nothing sends it heartbeats (60 s).
local FOREIGN_STOP_POLLS = 6 -- x 0.5 s
local function retireForeignEngine()
    local state = readRuntimeState()
    if not state then return end
    local health = probeHealth(state)
    if not health or isOwnEngine(health) then return end
    engineLog(string.format("Engine on port %d (pid %s) is version %s, not %s: asking it to stop",
        state.port, tostring(state.pid), tostring(health.version or "unknown"), MaskBridgeConfig.VERSION))
    local http = import 'LrHttp'
    LrTasks.pcall(function()
        http.get(string.format("http://127.0.0.1:%d/shutdown", state.port),
            { { field = "X-MaskBridge-Token", value = state.token } }, 2)
    end)
    for i = 1, FOREIGN_STOP_POLLS do
        LrTasks.sleep(0.5)
        if not probeHealth(state) then
            engineLog("Previous engine stopped after " .. (i * 0.5) .. "s")
            return true
        end
    end
    engineLog("Previous engine still answering after " .. (FOREIGN_STOP_POLLS * 0.5)
        .. "s; starting ours anyway (the old one exits without heartbeat within 60 s)")
    return false
end

function MaskBridgeUtils.startServer(logMsg)
    -- Already running
    if MaskBridgeUtils.isServerRunning() then
        if logMsg then logMsg("Server already running on port " .. tostring(MaskBridgeUtils.getServerPort())) end
        return true
    end

    -- Already starting (prevent duplicate starts)
    if _serverStarting then
        if logMsg then logMsg("Server already starting, skipping duplicate start") end
        for i = 1, 180 do
            LrTasks.sleep(0.5)
            if MaskBridgeUtils.isServerRunning() then return true end
            if not _serverStarting then return false end
        end
        return false
    end

    _serverStarting = true
    local ok, result = LrTasks.pcall(function()

    retireForeignEngine()

    -- Clear stale port AND token from BOTH candidate locations before starting.
    -- A leftover token in the backend directory would otherwise shadow the one
    -- the new server just wrote to the fallback location, and every request
    -- would 401 against a server that is running perfectly well.
    deleteRuntimeState(".server_state.json")
    deleteRuntimeState(".server_port")
    deleteRuntimeState(".server_token")
    if logMsg then logMsg("Cleared stale port/token files") end

    -- The new server mints a fresh token; keeping the previous one cached would
    -- make every request 401 until the plugin is reloaded.
    MaskBridgeUtils.forgetServerToken()

    local backendDir = LrPathUtils.child(MaskBridgeUtils.getPluginPath(), "backend")
    local modelDir = MaskBridgeUtils.getModelDir()

    -- OneDir Structure: backend/maskbridge_engine/maskbridge_engine(.exe)
    local binaryName = MaskBridgeUtils.isWindows() and "maskbridge_engine.exe" or "maskbridge_engine"
    local binaryPath = LrPathUtils.child(LrPathUtils.child(backendDir, "maskbridge_engine"), binaryName)

    -- Backward compatibility check (if old structure exists)
    if not LrFileUtils.exists(binaryPath) then
        binaryPath = LrPathUtils.child(backendDir, binaryName)
    end

    local cmd
    local logPath
    if MaskBridgeConfig.DEBUG_MODE then
        logPath = LrPathUtils.child(LrPathUtils.parent(_PLUGIN.path), "server_debug.log")
    else
        logPath = MaskBridgeUtils.isWindows() and "NUL" or "/dev/null"
    end

    if LrFileUtils.exists(binaryPath) then
        -- Prefer Standalone Binary
        if MaskBridgeUtils.isWindows() then
            -- The engine gets the exact SDK appData location (W03), the one
            -- runtimeStateCandidates reads.
            local base = assert(LrPathUtils.getStandardFilePath('appData'), "Windows appData unavailable")
            local stateDir = MaskBridgeUtils.normalizePath(LrPathUtils.child(base, "MaskBridge/Runtime-v2"))
            local nonce = string.format("%x%07x", os.time(), math.random(0, 0xFFFFFFF))
            local content, command, launcherPath = MaskBridgeUtils.windowsLaunchFiles(
                MaskBridgeUtils.normalizePath(binaryPath), MaskBridgeUtils.normalizePath(modelDir),
                stateDir, MaskBridgeUtils.normalizePath(base), nonce)
            LrFileUtils.createAllDirectories(stateDir)
            writeWindowsLauncher(launcherPath, content)
            cmd = command
        else
            cmd = string.format('%s --server --preload --model-dir %s >> %s 2>&1 &',
                MaskBridgeUtils.shellEscape(binaryPath), MaskBridgeUtils.shellEscape(modelDir), MaskBridgeUtils.shellEscape(logPath))
        end
    else
        -- Fallback to Python Script
        if MaskBridgeUtils.isWindows() then
            if logMsg then logMsg("Binary not found: " .. binaryPath) end
            return false
        end

        local serverScript = LrPathUtils.child(backendDir, "server.py")
        local python3 = MaskBridgeUtils.findPython3()

        if not LrFileUtils.exists(serverScript) then
            if logMsg then logMsg("Server script not found: " .. serverScript) end
            return false
        end

        cmd = string.format('%s %s --preload --model-dir %s >> %s 2>&1 &',
            MaskBridgeUtils.shellEscape(python3), MaskBridgeUtils.shellEscape(serverScript),
            MaskBridgeUtils.shellEscape(modelDir), MaskBridgeUtils.shellEscape(logPath))
    end

    if logMsg then logMsg("Starting server: " .. cmd) end
    -- On Windows the launcher returns once the engine has started its server:
    -- a non-zero code (engine refused its folders, launcher not found, nonce
    -- mismatch) ends the wait instead of letting it run to the timeout.
    local launchStatus = nil
    LrTasks.startAsyncTask(function()
        launchStatus = LrTasks.execute(cmd)
    end)

    -- Wait for startup (max 90s)
    for i = 1, 180 do
        LrTasks.sleep(0.5)
        if MaskBridgeUtils.isServerRunning() then
            if logMsg then logMsg("Server started on port " .. tostring(MaskBridgeUtils.getServerPort())) end
            _serverStarting = false
            return true
        end
        if MaskBridgeUtils.isWindows() and launchStatus ~= nil and launchStatus ~= 0 then
            engineLog("Engine launcher failed with exit code " .. tostring(launchStatus))
            if logMsg then logMsg("Engine launcher failed with exit code " .. tostring(launchStatus)) end
            _serverStarting = false
            return false
        end
    end

    if logMsg then logMsg("Server failed to start within timeout") end
    _serverStarting = false
    return false
    end)
    _serverStarting = false
    if not ok then
        engineLog("Server startup failed: " .. tostring(result))
        if logMsg then logMsg("Server startup failed: " .. tostring(result)) end
    end
    return ok and result == true
end

-- Send POST request to server (optimized with LrHttp, curl fallback)
function MaskBridgeUtils.httpPost(endpoint, data)
    local state = readRuntimeState()
    if not state then
        return nil, "Server not running"
    end
    -- Never send a request to an engine of another release (one /health
    -- round-trip per new state record, none afterwards).
    if state.token ~= verifiedToken then
        MaskBridgeUtils.getServerHealth()
        if state.token ~= verifiedToken then return nil, "Server not running" end
    end
    local port = state.port

    local url = string.format("http://127.0.0.1:%d%s", port, endpoint)

    -- Per-run auth token: without it the server answers 401 on every endpoint
    -- but /health (see MaskBridgeUtils.getServerToken).
    local token = state.token

    -- Try LrHttp first (faster - no disk I/O or shell spawning)
    local LrHttp = import 'LrHttp'
    if LrHttp then
        local headers = {
            { field = "Content-Type", value = "application/json" }
        }
        if token then
            table.insert(headers, { field = "X-MaskBridge-Token", value = token })
        end

        -- LrHttp.post returns (body, headersTable) — the HTTP status lives in
        -- headersTable.status, NOT in a third return value. Reading a third
        -- value left status always nil, so every request fell through to the
        -- curl fallback below and was sent (and processed) TWICE.
        -- Signature: LrHttp.post(url, body, headers, method, timeout).
        local LrTasks = import 'LrTasks'
        local ok, body, status = LrTasks.pcall(function()
            local respBody, respHdrs = LrHttp.post(url, data, headers, "POST", 120)
            return respBody, respHdrs and tonumber(respHdrs.status)
        end)

        if ok and status == 200 and body then
            return body
        elseif ok and status and status ~= 200 then
            -- If it's a JSON response (like processing errors), return it so the caller can parse it.
            -- Otherwise return nil with status code.
            if body and (body:find("^%s*{") or body:find("^%s*%[")) then
                return body, "HTTP status " .. tostring(status)
            else
                return nil, "HTTP status " .. tostring(status)
            end
        end
        -- The action may have completed even if its response was lost. Never
        -- replay a mutation automatically after an uncertain transport result.
        return nil, "Server response unavailable; check the result before retrying."
    end

    return nil, "Lightroom HTTP service unavailable"
end

-- Windows: Lightroom shows floating dialogs as unowned topmost windows, so the
-- dashboard covered every other application. The engine re-parents it to
-- Lightroom's main window (backend/dashboard_window.py). Best effort: if this
-- fails, the dashboard stays usable, only topmost as before. The window may
-- not be visible yet when onShow runs, hence the short retry.
function MaskBridgeUtils.attachDashboardWindow(isOpen, logMsg)
    if not MaskBridgeUtils.isServerRunning() then
        if logMsg then logMsg("Dashboard window: engine not running, left topmost") end
        return false
    end
    for _ = 1, 10 do
        if not isOpen() then return false end
        local body = MaskBridgeUtils.httpPost("/dashboard-window", "{}")
        local attached = body and tonumber(body:match('"attached"%s*:%s*(%d+)'))
        if attached and attached > 0 then
            if logMsg then logMsg("Dashboard window attached to Lightroom") end
            return true
        end
        LrTasks.sleep(0.3)
    end
    if logMsg then logMsg("Dashboard window: not attached, left topmost") end
    return false
end

-- Stop Server (waits for actual shutdown, cleans up port file)
function MaskBridgeUtils.stopServer(logMsg)
    -- Read before /shutdown: an exiting engine deletes its state record.
    local state = readRuntimeState()
    local port = MaskBridgeUtils.getServerPort()
    if not port then
        if logMsg then logMsg("No server port found, nothing to stop") end
        return
    end

    -- Use LrHttp.get for shutdown (safe — no fork crash risk like curl via LrTasks.execute).
    -- /shutdown is token-protected: without it any web page could stop the engine.
    local LrHttp = import 'LrHttp'
    local url = string.format("http://127.0.0.1:%d/shutdown", port)
    local shutdownHeaders = nil
    local token = MaskBridgeUtils.getServerToken()
    if token then
        shutdownHeaders = { { field = "X-MaskBridge-Token", value = token } }
    end
    LrTasks.pcall(function()
        LrHttp.get(url, shutdownHeaders, 2) -- 2s timeout
    end)
    if logMsg then logMsg("Server shutdown requested on port " .. port) end

    -- Wait for server to actually stop (max 5s), whatever its version
    for i = 1, 10 do
        LrTasks.sleep(0.5)
        if not (state and probeHealth(state)) then
            if logMsg then logMsg("Server confirmed stopped after " .. (i * 0.5) .. "s") end
            break
        end
    end

    -- Clean up port file (both locations) so startServer() can restart cleanly
    deleteRuntimeState(".server_state.json")
    deleteRuntimeState(".server_port")
    if logMsg then logMsg("Port file cleaned up") end

    -- Reset starting flag so startServer() won't be blocked
    _serverStarting = false
    MaskBridgeUtils.forgetServerToken()
end

return MaskBridgeUtils
