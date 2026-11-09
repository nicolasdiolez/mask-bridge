local LrPathUtils = import 'LrPathUtils'
local LrTasks = import 'LrTasks'
local LrFileUtils = import 'LrFileUtils'
local LrDialogs = import 'LrDialogs'
local LrBinding = import 'LrBinding'
local LrView = import 'LrView'
local LrPrefs = import 'LrPrefs'
local LrProgressScope = import 'LrProgressScope'

local MaskBridgeUtils = require 'MaskBridgeUtils'
local MaskBridgeConfig = require 'MaskBridgeConfig'

local json = dofile(LrPathUtils.child(_PLUGIN.path, "dkjson.lua"))

local MaskBridgeExportProvider = {}

-- Debug mode from centralized config
local DEBUG_MODE = MaskBridgeConfig.DEBUG_MODE

-- Cross-platform detection (using Utils)
local function isWindows()
    return MaskBridgeUtils.isWindows()
end

-- REQUIRED FIELDS
MaskBridgeExportProvider.exportPresetFields = {
    { key = 'am_prompts',    default = 'person' },
    { key = 'am_invert',     default = false },
    { key = 'am_masks_only', default = false },
    { key = 'am_export_alpha', default = false },
    { key = 'am_birefnet_refine', default = false },
    { key = 'am_naming',     default = 'standard' },
}

-- Logging function (only in debug mode)
local function logMsg(msg)
    if not DEBUG_MODE then return end
    local logPath = MaskBridgeUtils.getLogPath("maskbridge_debug.log")
    local f = io.open(logPath, "a")
    if f then
        f:write(os.date("%H:%M:%S") .. " | PROVIDER: " .. tostring(msg) .. "\n")
        f:close()
    end
end

-- Plugin section at the top of the File > Export dialog.
-- The SDK hook is sectionsForTopOfDialog — the previous name
-- (sectionsForVisualAppearance) is not part of the export service provider
-- API, so Lightroom never displayed this panel: File > Export always masked
-- "person" with no way to change anything.
-- Exposes the preset fields the processing code actually consumes
-- (prompts, invert, masks-only, alpha, naming).
function MaskBridgeExportProvider.sectionsForTopOfDialog(f, propertyTable)
    return {
        {
            title = "Mask Bridge",
            f:row {
                f:static_text {
                    title = LOC("$$$/MaskBridge/ExportProvider/Hint=Use the Dashboard to configure your masks."),
                    font = "small",
                },
            },
            f:row {
                f:static_text {
                    title = LOC("$$$/MaskBridge/ExportDialog/Prompts=Objects to mask (prompts):"),
                    alignment = "right",
                    width = LrView.share "label_width",
                },
                f:edit_field {
                    value = LrView.bind("am_prompts"),
                    validate = function(view, value)
                        if value == "" then
                            return false, value,
                                LOC("$$$/MaskBridge/ExportDialog/PromptsValidation=Please enter at least one object (e.g. car, person).")
                        end
                        return true, value
                    end,
                    fill_horizontal = 1,
                },
            },
            f:row {
                f:static_text {
                    title = LOC("$$$/MaskBridge/ExportDialog/InvertMask=Invert mask:"),
                    alignment = "right",
                    width = LrView.share "label_width",
                },
                f:checkbox {
                    title = LOC("$$$/MaskBridge/ExportDialog/MaskSelection=Mask selection (White=Object)"),
                    value = LrView.bind("am_invert"),
                },
            },
            f:row {
                f:static_text {
                    title = "",
                    width = LrView.share "label_width",
                },
                f:checkbox {
                    title = LOC("$$$/MaskBridge/Dashboard/Options/MasksOnly=Masks only (skip processed images)"),
                    value = LrView.bind("am_masks_only"),
                },
            },
            f:row {
                f:static_text {
                    title = "",
                    width = LrView.share "label_width",
                },
                f:checkbox {
                    title = LOC("$$$/MaskBridge/Dashboard/Options/ExportAlpha=Export with Transparency (PNG Alpha)"),
                    value = LrView.bind("am_export_alpha"),
                },
            },
            f:row {
                f:static_text {
                    title = "",
                    width = LrView.share "label_width",
                },
                f:checkbox {
                    -- Same key as the Dashboard checkbox (already translated ×9)
                    title = LOC("$$$/MaskBridge/Dashboard/Options/BiRefNet=Fine detail (hair/fur) — slower"),
                    value = LrView.bind("am_birefnet_refine"),
                },
            },
            f:row {
                f:static_text {
                    title = LOC("$$$/MaskBridge/Dashboard/Output/Naming=Naming:"),
                    alignment = "right",
                    width = LrView.share "label_width",
                },
                f:popup_menu {
                    value = LrView.bind("am_naming"),
                    items = {
                        { title = LOC("$$$/MaskBridge/Naming/Standard=Standard (.mask.png)"),     value = "standard" },
                        { title = LOC("$$$/MaskBridge/Naming/Underscore=Underscore (_mask.png)"), value = "underscore" },
                        { title = LOC("$$$/MaskBridge/Naming/Hyphen=Hyphen (-mask.png)"),         value = "hyphen" },
                        { title = LOC("$$$/MaskBridge/Naming/Suffix=Suffix (_MaskBridge.png)"),     value = "suffix" },
                    },
                },
            },
        },
    }
end

-- Main process function
function MaskBridgeExportProvider.processRenderedPhotos(functionContext, exportContext)
    -- When Dashboard drives the export, it handles AI processing itself.
    -- Skip here to avoid duplicate processing (each image processed 2x).
    if exportContext.propertyTable.am_internalRender == true then
        logMsg("DASHBOARD MODE: Skipping ExportProvider AI processing")
        return
    end
    local token = MaskBridgeUtils.beginOperation("file-export")
    if not token then
        for _, rendition in exportContext:renditions() do
            rendition:renditionIsDone(false, "Another Mask Bridge operation is running")
        end
        return
    end
    functionContext:addCleanupHandler(function() MaskBridgeUtils.endOperation(token) end)
    logMsg("ENTRY POINT: processRenderedPhotos CALLED")

    local exportSession = exportContext.exportSession
    exportContext.propertyTable.LR_collisionHandling = "rename"
    local propertyTable = MaskBridgeUtils.snapshot(exportContext.propertyTable)
    local prefs = MaskBridgeUtils.snapshot(LrPrefs.prefsForPlugin())

    -- Top-left progress bar. A configureProgress scope belongs to the
    -- RENDERING sequence: Lightroom closes it as soon as the last photo is
    -- rendered, so it vanished while masks were still being generated.
    -- A standalone scope (same pattern as the Dashboard) lives for the whole
    -- render+AI loop; functionContext guarantees cleanup on any error.
    -- Reuses the Dashboard i18n keys — no new translations.
    local nPhotos = exportSession:countRenditions()
    local progressScope = LrProgressScope({
        title = LOC("$$$/MaskBridge/Processing/Title=Mask Bridge - Processing"),
        functionContext = functionContext,
    })

    LrDialogs.showBezel(LOC("$$$/MaskBridge/Processing/AIInProgress=Mask Bridge: AI processing in progress..."), 5)

    -- Standalone binary when present, python3+cli.py otherwise — end-user
    -- machines have no Python, so the binary must be preferred here too.
    local backendCmd = MaskBridgeUtils.getBackendEngine()
    local modelDir = MaskBridgeUtils.getModelDir()
    local isServer = MaskBridgeUtils.isServerRunning() or MaskBridgeUtils.startServer(logMsg)

    if isServer then
        logMsg("SERVER MODE: Connected")
    else
        logMsg("CLI MODE: Server not running")
    end

    for i, rendition in exportContext:renditions() do
        progressScope:setPortionComplete(i - 1, nPhotos)
        local success, renditionPath = rendition:waitForRender()
        if progressScope:isCanceled() then break end
        local originalPath = rendition.photo:getRawMetadata('path')
        if success and originalPath and renditionPath:lower() == originalPath:lower() then
            rendition:renditionIsDone(false, "The rendered path is an original photo; it was preserved")
            success = false
        end
        if success then
            logMsg("JPEG Rendered: " .. renditionPath)
            local dir = LrPathUtils.parent(renditionPath)
            local stem = LrPathUtils.removeExtension(LrPathUtils.leafName(renditionPath))
            progressScope:setCaption(LOC(
                "$$$/MaskBridge/Processing/ProcessingImage=Processing ^1/^2: ^3...",
                i, nPhotos, stem))
            -- local maskPath = LrPathUtils.child(dir, stem .. ".mask.png")
            local namingPattern = propertyTable.am_naming or MaskBridgeUtils.NAMING_STANDARD
            local maskPath = MaskBridgeUtils.uniqueOutputPath(MaskBridgeUtils.getMaskPath(dir, stem, namingPattern))

            local prompts = propertyTable.am_prompts or "person"
            local invert = propertyTable.am_invert
            local birefnetRefine = propertyTable.am_birefnet_refine == true

            -- Read Dashboard settings from global preferences so File > Export
            -- honors the same sensitivity/smoothing/exclusions the user tuned
            -- there (they were previously ignored on this path).
            -- Preferences were frozen when this export started.
            local smoothing = prefs.smoothing or MaskBridgeConfig.DEFAULT_SMOOTHING
            local threshold = MaskBridgeConfig.DEFAULT_THRESHOLD
            if type(prefs.sensitivity) == "number" then
                threshold = (100 - prefs.sensitivity) / 100
            end
            local excludeClasses = prefs.excludeClasses or ""
            logMsg("READ PREFS: smoothing=" .. tostring(smoothing)
                .. " threshold=" .. tostring(threshold)
                .. " exclude=" .. tostring(excludeClasses)
                .. " birefnet=" .. tostring(birefnetRefine))

            local status = -1
            local errorDetail = nil

            if isServer then
                -- Server Mode export (Much faster)
                logMsg("Sending to server...")
                local data = {
                    image = renditionPath,
                    output = maskPath,
                    prompts = prompts,
                    model_dir = modelDir,
                    invert = invert and true or false,
                    threshold = threshold,
                    smoothing = smoothing,
                    exclude = excludeClasses,
                    edge_refine = false, -- product default: fast hard mask (same as Dashboard)
                    birefnet_refine = birefnetRefine,
                }
                local jsonData = json.encode(data)

                local response = MaskBridgeUtils.httpPost("/process", jsonData)
                local decoded = response and json.decode(response)
                if type(decoded) == "table" and decoded.status == "success" then
                    status = 0
                elseif response then
                    logMsg("Server error: " .. tostring(response))
                    status = 1
                    -- Parse error details from server response
                    local ok, parsed = pcall(json.decode, response)
                    if ok and parsed then
                        if parsed.message then
                            errorDetail = parsed.message
                        elseif parsed.error then
                            errorDetail = parsed.error
                        end
                    end
                else
                    logMsg("Server error: no response")
                    status = 1
                    errorDetail = "no_response"
                end
            else
                -- CLI fallback. Every argument goes through shellEscape: prompts
                -- and excludeClasses are free-text UI fields, and a photo path
                -- can legitimately contain a quote on macOS.
                local args = string.format(
                    '--image %s --output %s --prompts %s --model-dir %s --threshold %.2f --smoothing %d',
                    MaskBridgeUtils.shellEscape(MaskBridgeUtils.normalizePath(renditionPath)),
                    MaskBridgeUtils.shellEscape(MaskBridgeUtils.normalizePath(maskPath)),
                    MaskBridgeUtils.shellEscape(prompts),
                    MaskBridgeUtils.shellEscape(MaskBridgeUtils.normalizePath(modelDir)),
                    threshold, smoothing)

                if invert then args = args .. " --invert" end
                if birefnetRefine then args = args .. " --birefnet-refine" end
                if excludeClasses ~= "" then
                    args = args .. ' --exclude ' .. MaskBridgeUtils.shellEscape(excludeClasses)
                end
                logMsg("Executing: " .. backendCmd .. " " .. args)
                status = MaskBridgeUtils.executeCommand(backendCmd .. " " .. args, nil)
            end

            logMsg("Status: " .. tostring(status) .. ", errorDetail: " .. tostring(errorDetail))

            if status == 0 and LrFileUtils.exists(maskPath) then
                local outputsComplete = true
                logMsg("SUCCESS: Mask generated")

                -- Alpha Export feature: merge RGB + mask → RGBA PNG
                -- (preset field, same as the checkbox in this dialog — not the
                -- Dashboard's global preference)
                if propertyTable.am_export_alpha then
                    logMsg("Alpha Export: rgb=" .. tostring(renditionPath) .. " mask=" .. tostring(maskPath))
                    local alphaOutputPath = MaskBridgeUtils.getMaskPath(dir, stem, namingPattern)
                    alphaOutputPath = MaskBridgeUtils.uniqueOutputPath(string.gsub(alphaOutputPath, "%.png$", "_alpha.png"))
                    logMsg("Alpha output: " .. alphaOutputPath)

                    local alphaStatus = -1
                    if isServer then
                        local port = MaskBridgeUtils.getServerPort()
                        if port then
                            local alphaData = json.encode({
                                rgb_path = renditionPath,
                                mask_path = maskPath,
                                output_path = alphaOutputPath,
                            })
                            logMsg("Alpha POST /merge-alpha: " .. alphaData)
                            local alphaResponse = MaskBridgeUtils.httpPost("/merge-alpha", alphaData)
                            logMsg("Alpha response: " .. tostring(alphaResponse))
                            if alphaResponse and type(json.decode(alphaResponse)) == "table" and json.decode(alphaResponse).status == "success" then
                                alphaStatus = 0
                            end
                        else
                            logMsg("Alpha: no server port")
                        end
                    end

                    if alphaStatus ~= 0 and not isServer then
                        local backendCmd = MaskBridgeUtils.getBackendEngine()
                        if backendCmd then
                            local alphaCmd = string.format(
                                '%s --mode alpha --image %s --mask %s --output %s',
                                backendCmd,
                                MaskBridgeUtils.shellEscape(MaskBridgeUtils.normalizePath(renditionPath)),
                                MaskBridgeUtils.shellEscape(MaskBridgeUtils.normalizePath(maskPath)),
                                MaskBridgeUtils.shellEscape(MaskBridgeUtils.normalizePath(alphaOutputPath))
                            )
                            logMsg("Alpha CLI: " .. alphaCmd)
                            alphaStatus = MaskBridgeUtils.executeCommand(alphaCmd, nil)
                        else
                            logMsg("Alpha: getBackendEngine() returned nil")
                        end
                    end

                    if alphaStatus == 0 and LrFileUtils.exists(alphaOutputPath) then
                        logMsg("Alpha OK: " .. alphaOutputPath)
                    else
                        outputsComplete = false
                        logMsg("Alpha FAILED (status=" .. tostring(alphaStatus) .. ")")
                    end
                end

                if propertyTable.am_masks_only and outputsComplete then
                    logMsg("MODE ONLY MASKS: Deleting JPEG " .. renditionPath)
                    LrFileUtils.delete(renditionPath)
                end
                rendition:renditionIsDone(outputsComplete, outputsComplete and nil or "Mask saved, alpha export failed")
            else
                logMsg("FAILURE: Mask missing or Python error")
                -- CLEANUP: remove the JPEG that Lightroom just created
                if LrFileUtils.exists(renditionPath) then
                    logMsg("CLEANUP: Deleting JPEG due to failure: " .. renditionPath)
                    LrFileUtils.delete(renditionPath)
                end

                local errMsg
                if errorDetail == "no_response" then
                    errMsg = LOC("$$$/MaskBridge/Error/ServerDown=AI server not responding. Please restart the plugin.")
                else
                    errMsg = LOC("$$$/MaskBridge/Error/AIFailed=AI processing failed. Check the plugin log for details.")
                end
                rendition:renditionIsDone(false, errMsg)
            end
        else
            logMsg("FAILED to render JPEG")
        end
    end
    progressScope:done()
    logMsg("EXIT POINT: processRenderedPhotos FINISHED")
end

return MaskBridgeExportProvider
