--[[----------------------------------------------------------------------------

MaskBridgeInfoProvider.lua

Section shown in Lightroom's Plug-in Manager. It answers two questions that
otherwise cost a support round-trip each:

  1. "Is Mask Bridge working?" — engine, models and server state, all visible
     without starting a batch. A user whose install is broken should not have
     to launch a job to discover it.

  2. "What do I send you?" — one self-contained diagnostic report, on the
     clipboard, ready to paste into a support email.

The report body is deliberately English whatever the interface language: it is
read by support, not by the user, and a half-translated report is harder to
triage than an English one. Only the surrounding UI is localized.

------------------------------------------------------------------------------]]

local LrView = import 'LrView'
local LrDialogs = import 'LrDialogs'
local LrHttp = import 'LrHttp'
local LrTasks = import 'LrTasks'
local LrPathUtils = import 'LrPathUtils'
local LrFileUtils = import 'LrFileUtils'
local LrSystemInfo = import 'LrSystemInfo'
local LrApplication = import 'LrApplication'
local LrLocalization = import 'LrLocalization'
local LrFunctionContext = import 'LrFunctionContext'
local LrBinding = import 'LrBinding'

local MaskBridgeUtils = require 'MaskBridgeUtils'
local MaskBridgeConfig = require 'MaskBridgeConfig'

-- ============================================================================
-- Small helpers
-- ============================================================================

-- Every probe below touches the filesystem, the network or the SDK, and this
-- panel must render even when one of them is broken — a diagnostic tool that
-- fails on a broken install is worthless.
local function safe(fn, fallback)
    local ok, value = LrTasks.pcall(fn)
    if ok and value ~= nil then return value end
    return fallback
end

local function fileInfo(path)
    local attrs = LrFileUtils.fileAttributes(path)
    if not attrs or not attrs.fileSize then return nil end
    return string.format("%.1f MB", attrs.fileSize / 1048576)
end

-- Last lines of a log file, without pulling the whole thing into memory: the
-- backend log rotates at 5 MB and only the tail is ever relevant.
local function tailFile(path, maxLines)
    local f = io.open(path, "rb")
    if not f then return nil end
    local size = f:seek("end") or 0
    local window = 24 * 1024
    local from = size > window and size - window or 0
    f:seek("set", from)
    local chunk = f:read("*all") or ""
    f:close()
    if from > 0 then
        chunk = (chunk:gsub("^[^\n]*\n", "")) -- drop the line we cut in half
    end
    local lines = {}
    for line in chunk:gmatch("[^\r\n]+") do
        lines[#lines + 1] = line
    end
    if #lines == 0 then return nil end
    local first = math.max(1, #lines - maxLines + 1)
    return table.concat(lines, "\n", first, #lines), #lines - first + 1
end

-- The backend logs at INFO to the plug-in root in every build, debug or not,
-- so this is the one log that is always there to attach.
local function serverLogPath()
    return MaskBridgeUtils.getLogPath("server_debug.log")
end

-- ============================================================================
-- Diagnostic report
-- ============================================================================

local function buildReport()
    local out = {}
    local function add(line) out[#out + 1] = line or "" end
    local function field(label, value)
        add(string.format("%-16s%s", label, tostring(value)))
    end

    add("Mask Bridge — diagnostic report")
    add("Generated " .. os.date("%Y-%m-%d %H:%M:%S"))
    add("")

    add("[Plug-in]")
    field("Version", MaskBridgeConfig.VERSION)
    field("Location", safe(MaskBridgeUtils.getPluginPath, "?"))
    field("Debug logging", MaskBridgeConfig.DEBUG_MODE and "on" or "off")
    add("")

    add("[Host]")
    field("Lightroom", safe(LrApplication.versionString, "?"))
    field("System", safe(LrSystemInfo.summaryString, "?"))
    field("Architecture", safe(LrSystemInfo.architecture, "?"))
    field("CPU cores", safe(LrSystemInfo.numCPUs, "?"))
    field("Memory", safe(function()
        return string.format("%.0f MB", LrSystemInfo.memSize() / 1048576)
    end, "?"))
    field("UI language", safe(LrLocalization.currentLanguage, "?"))
    add("")

    add("[Backend]")
    local engineCmd = safe(MaskBridgeUtils.getBackendEngine, "")
    -- getBackendEngine() falls back to "python3 cli.py" when the bundled
    -- binary is missing, which on a customer machine means a broken install.
    field("Engine", engineCmd:find("cli%.py")
        and "PYTHON FALLBACK — bundled binary not found"
        or "bundled binary")
    field("Command", engineCmd ~= "" and engineCmd or "?")
    local modelDir = safe(MaskBridgeUtils.getModelDir, "")
    for _, name in ipairs({ "rfdetr_seg_medium.onnx", "birefnet_lite_fp16.onnx" }) do
        local size = modelDir ~= "" and fileInfo(LrPathUtils.child(modelDir, name)) or nil
        field("Model", string.format("%-26s %s",
            name, size and ("OK  " .. size) or "MISSING"))
    end
    add("")

    add("[Server]")
    local port = safe(MaskBridgeUtils.getServerPort, nil)
    if port then
        field("Port", port)
        local ok, body = LrTasks.pcall(function()
            return LrHttp.get(string.format("http://127.0.0.1:%d/health", port), nil, 3)
        end)
        field("Health", (ok and body) and body or "no response")
    else
        field("Port", "no port file — server not running")
    end
    local tokenFile = safe(MaskBridgeUtils.getServerTokenFile, "")
    field("Auth token", (tokenFile ~= "" and LrFileUtils.exists(tokenFile)) and "present" or "absent")
    add("")

    add("[Backend log]")
    local logPath = serverLogPath()
    local tail, count = tailFile(logPath, 60)
    if tail then
        add(string.format("last %d lines of %s", count, logPath))
        add("")
        add(tail)
    else
        add("no log at " .. logPath)
    end

    return table.concat(out, "\n")
end

-- Best effort: the modal below shows the text either way, so a failure here
-- costs the user a Ctrl+A, not the report.
local function copyToClipboard(text)
    local tmpDir = safe(function() return LrPathUtils.getStandardFilePath('temp') end, nil)
    if not tmpDir then return false end
    local tmp = LrPathUtils.child(tmpDir, "maskbridge_diagnostic.txt")

    local f = io.open(tmp, "w")
    if not f then return false end
    f:write(text)
    f:close()

    local cmd
    if MaskBridgeUtils.isWindows() then
        -- Single quotes inside the double-quoted -Command argument: no nested
        -- double quotes to escape, unlike `cmd /c "clip < "path""`.
        cmd = string.format(
            [[powershell -NoProfile -Command "Get-Content -Raw -LiteralPath '%s' | Set-Clipboard"]],
            MaskBridgeUtils.normalizePath(tmp))
    else
        cmd = string.format('pbcopy < "%s"', tmp)
    end

    local status = safe(function() return LrTasks.execute(cmd) end, -1)
    LrFileUtils.delete(tmp)
    return status == 0
end

local function showReport()
    local report = buildReport()
    local copied = copyToClipboard(report)

    LrFunctionContext.callWithContext("maskBridgeDiagnostic", function(context)
        local props = LrBinding.makePropertyTable(context)
        props.report = report
        local f = LrView.osFactory()

        LrDialogs.presentModalDialog {
            title = LOC("$$$/MaskBridge/Info/ReportTitle=Mask Bridge — diagnostic report"),
            resizable = true,
            contents = f:column {
                bind_to_object = props,
                spacing = f:control_spacing(),
                f:static_text {
                    title = copied
                        and LOC("$$$/MaskBridge/Info/ReportCopied=The report has been copied to your clipboard. Paste it into your message to support.")
                        or LOC("$$$/MaskBridge/Info/ReportSelect=Select the text below, copy it, and paste it into your message to support."),
                    fill_horizontal = 1,
                },
                -- Multi-line + wrapping so a long log line looks folded rather
                -- than truncated. The value keeps its real newlines, so what
                -- the user copies is what buildReport produced.
                f:edit_field {
                    value = LrView.bind("report"),
                    width_in_chars = 88,
                    height_in_lines = 26,
                    wraps = true,
                    fill_horizontal = 1,
                },
            },
            actionVerb = LOC("$$$/MaskBridge/Info/Close=Close"),
            cancelVerb = "< exclude >",
        }
    end)
end

-- ============================================================================
-- Live status rows
-- ============================================================================

-- Runs off the UI thread: isServerRunning() does an HTTP round-trip with a 2s
-- timeout, and the Plug-in Manager must not freeze while it waits.
local function refreshStatus(props)
    props.mbServer = LOC("$$$/MaskBridge/Info/Checking=Checking…")
    LrTasks.startAsyncTask(function()
        local modelDir = safe(MaskBridgeUtils.getModelDir, "")
        local engineCmd = safe(MaskBridgeUtils.getBackendEngine, "")
        local modelsOK = modelDir ~= ""
            and LrFileUtils.exists(LrPathUtils.child(modelDir, "rfdetr_seg_medium.onnx"))
        props.mbEngine = (modelsOK and not engineCmd:find("cli%.py"))
            and LOC("$$$/MaskBridge/Info/EngineReady=Ready")
            or LOC("$$$/MaskBridge/Info/EngineMissing=Incomplete — reinstall Mask Bridge")

        local port = safe(MaskBridgeUtils.getServerPort, nil)
        local running = port and safe(MaskBridgeUtils.isServerRunning, false)
        props.mbServer = running
            and LOC("$$$/MaskBridge/Info/ServerRunning=Running (port ^1)", tostring(port))
            or LOC("$$$/MaskBridge/Info/ServerStopped=Stopped (starts on first use)")
    end)
end

local function sectionsForTopOfDialog(f, props)
    props.mbEngine = LOC("$$$/MaskBridge/Info/Checking=Checking…")
    props.mbServer = LOC("$$$/MaskBridge/Info/Checking=Checking…")
    refreshStatus(props)

    local labelWidth = 110

    local function statusRow(label, boundKey)
        return f:row {
            f:static_text { title = label, width = labelWidth },
            f:static_text {
                title = LrView.bind { key = boundKey, object = props },
                fill_horizontal = 1,
            },
        }
    end

    -- Bindings name their object explicitly, and everything lives in one
    -- column that carries bind_to_object: a dialog section is not itself a
    -- view, so binding properties belong on a real container (this is the
    -- shape Adobe's own ftp_upload sample uses).
    return {
        {
            title = LOC("$$$/MaskBridge/Info/Section=Status & support"),
            synopsis = LrView.bind { key = "mbServer", object = props },

            f:column {
                bind_to_object = props,
                fill_horizontal = 1,
                spacing = f:control_spacing(),

                f:row {
                    f:static_text {
                        title = LOC("$$$/MaskBridge/Info/Version=Version"),
                        width = labelWidth,
                    },
                    f:static_text { title = MaskBridgeConfig.VERSION, fill_horizontal = 1 },
                },
                f:row {
                    f:static_text {
                        title = LOC("$$$/MaskBridge/Info/License=Licence"),
                        width = labelWidth,
                    },
                    f:static_text {
                        title = LOC("$$$/MaskBridge/Info/OpenSource=Free and open source (MIT licence)"),
                        fill_horizontal = 1,
                    },
                },
                f:row {
                    spacing = f:control_spacing(),
                    f:spacer { width = labelWidth },
                    f:push_button {
                        title = LOC("$$$/MaskBridge/Info/SourceCode=Source code"),
                        action = function()
                            LrHttp.openUrlInBrowser(MaskBridgeConfig.SOURCE_URL)
                        end,
                    },
                    f:push_button {
                        title = LOC("$$$/MaskBridge/Dashboard/SupportProject=Support Mask Bridge"),
                        action = function()
                            LrHttp.openUrlInBrowser(MaskBridgeConfig.SUPPORT_URL)
                        end,
                    },
                },
                statusRow(LOC("$$$/MaskBridge/Info/Engine=AI engine"), "mbEngine"),
                statusRow(LOC("$$$/MaskBridge/Info/Server=Server"), "mbServer"),

                f:row {
                    spacing = f:control_spacing(),
                    f:push_button {
                        title = LOC("$$$/MaskBridge/Info/Refresh=Refresh"),
                        action = function() refreshStatus(props) end,
                    },
                    f:push_button {
                        title = LOC("$$$/MaskBridge/Info/CopyReport=Copy diagnostic report"),
                        action = function()
                            LrTasks.startAsyncTask(showReport)
                        end,
                    },
                    f:push_button {
                        title = LOC("$$$/MaskBridge/Info/Support=Contact support"),
                        action = function()
                            LrHttp.openUrlInBrowser(MaskBridgeConfig.CONTACT_URL)
                        end,
                    },
                },

                f:static_text {
                    title = LOC("$$$/MaskBridge/Info/Hint=Attach the diagnostic report to any support request: it carries your version, your system and the last backend messages."),
                    fill_horizontal = 1,
                },
            },
        },
    }
end

return {
    sectionsForTopOfDialog = sectionsForTopOfDialog,
}
