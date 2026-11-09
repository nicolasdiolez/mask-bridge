local LrDialogs = import 'LrDialogs'
local LrView = import 'LrView'
local LrBinding = import 'LrBinding'

local LrFunctionContext = import 'LrFunctionContext'
local LrApplication = import 'LrApplication'
local LrTasks = import 'LrTasks'
local LrPathUtils = import 'LrPathUtils'
local LrFileUtils = import 'LrFileUtils'
local LrExportSession = import 'LrExportSession'
local LrProgressScope = import 'LrProgressScope'
local LrColor = import 'LrColor'
local LrPrefs = import 'LrPrefs'
local LrHttp = import 'LrHttp'
local LrSystemInfo = import 'LrSystemInfo'

local MaskBridgeUtils = require 'MaskBridgeUtils'
local MaskBridgeConfig = require 'MaskBridgeConfig'
local MaskBridgeMatte = dofile(LrPathUtils.child(_PLUGIN.path, "MaskBridgeMatte.lua"))
local json = dofile(LrPathUtils.child(_PLUGIN.path, "dkjson.lua"))

-- Localization helper (LOC is a global provided by Lightroom SDK)
-- LOC("$$$/Path/Key=Default English text") returns the localized string


-- Debug mode from centralized config
local DEBUG_MODE = MaskBridgeConfig.DEBUG_MODE
local function logMsg(msg)
    if not DEBUG_MODE then return end
    local logPath = MaskBridgeUtils.getLogPath("maskbridge_debug.log")
    local f = io.open(logPath, "a")
    if f then
        f:write(os.date("%H:%M:%S") .. " | DASHBOARD: " .. tostring(msg) .. "\n")
        f:close()
    end
end

-- Forward declarations
local findPython3

-- Get plugin path (using Utils)
local function getPluginPath()
    return MaskBridgeUtils.getPluginPath()
end

local function getModelDir()
    return MaskBridgeUtils.getModelDir()
end

-- =============================================================================
-- System Information & Notifications
-- =============================================================================

-- Play a system notification sound on macOS (no-op on Windows)
-- Respects the enableSounds preference (default: true)
local function playNotificationSound(success)
    local prefs = LrPrefs.prefsForPlugin()
    if prefs.enableSounds == false then return end
    if not WIN_ENV then
        local sound = success
            and "/System/Library/Sounds/Glass.aiff"
            or "/System/Library/Sounds/Basso.aiff"
        LrTasks.startAsyncTask(function()
            LrTasks.execute('afplay "' .. sound .. '" &')
        end)
    end
end

-- Settings persistence
local prefs = LrPrefs.prefsForPlugin()

-- ============================================================================
-- Engine results: /process sends stable warning codes (WARNING_* in
-- backend/inference_engine.py), worded here in the Lightroom language.
-- ============================================================================
local EngineResult = {}

function EngineResult.warningText(code, result)
    if code == "no_detection" then
        return LOC("$$$/MaskBridge/Warning/NoDetection=No object of the selected classes was detected.")
    elseif code == "unknown_classes" then
        local ignored = type(result) == "table" and type(result.ignored_classes) == "table"
            and table.concat(result.ignored_classes, ", ") or ""
        return LOC("$$$/MaskBridge/Warning/UnknownClasses=Unknown classes ignored: ^1", ignored)
    elseif code == "fine_detail_unavailable" then
        return LOC("$$$/MaskBridge/Warning/FineDetailUnavailable=HD unavailable for this photo: standard mask kept.")
    end
    return tostring(code)
end

-- No object detected: the engine still writes the mask (it is the right mask
-- for that photo), but it is not counted as a generated mask.
function EngineResult.isEmpty(result)
    return type(result) == "table" and tonumber(result.detections) == 0
end

function EngineResult.emptyLine(count)
    return LOC("$$$/MaskBridge/Processing/EmptyMasks=^1 photo(s) with no object detected (mask saved without a subject).", count)
end

local function saveSettings(props)
    prefs.cat_humans = props.cat_humans
    prefs.cat_cars = props.cat_cars
    prefs.cat_animals = props.cat_animals
    prefs.cat_furniture = props.cat_furniture
    prefs.cat_electronics = props.cat_electronics
    prefs.cat_vegetation = props.cat_vegetation
    prefs.customClasses = props.customClasses
    prefs.excludeClasses = props.excludeClasses
    prefs.am_invert = props.am_invert
    prefs.am_birefnet_refine = props.am_birefnet_refine
    prefs.am_masks_only = props.am_masks_only
    prefs.am_export_alpha = props.am_export_alpha
    prefs.namingPattern = props.namingPattern
    prefs.imageNamingPattern = props.imageNamingPattern
    prefs.imageNamingCustomPrefix = props.imageNamingCustomPrefix
    prefs.maxResolution = props.maxResolution
    prefs.customResolution = props.customResolution
    prefs.exportFormat = props.exportFormat
    prefs.tiffBitDepth = props.tiffBitDepth
    prefs.tiffCompression = props.tiffCompression
    prefs.jpegQuality = props.jpegQuality
    prefs.sensitivity = props.sensitivity
    prefs.smoothing = props.smoothing
    prefs.outputPath = props.outputPath
    prefs.maskOutputPath = props.maskOutputPath
    prefs.enableSounds = props.enableSounds
    prefs.matteType = props.matteType
    logMsg("Settings saved. Format=" .. tostring(props.exportFormat))
end

local function loadSettings(props)
    if prefs.cat_humans ~= nil then props.cat_humans = prefs.cat_humans end
    if prefs.cat_cars ~= nil then props.cat_cars = prefs.cat_cars end
    if prefs.cat_animals ~= nil then props.cat_animals = prefs.cat_animals end
    if prefs.cat_furniture ~= nil then props.cat_furniture = prefs.cat_furniture end
    if prefs.cat_electronics ~= nil then props.cat_electronics = prefs.cat_electronics end
    if prefs.cat_vegetation ~= nil then props.cat_vegetation = prefs.cat_vegetation end
    if prefs.customClasses ~= nil then props.customClasses = prefs.customClasses end
    if prefs.excludeClasses ~= nil then props.excludeClasses = prefs.excludeClasses end
    if prefs.am_invert ~= nil then props.am_invert = prefs.am_invert end
    if prefs.am_birefnet_refine ~= nil then props.am_birefnet_refine = prefs.am_birefnet_refine end
    if prefs.am_masks_only ~= nil then props.am_masks_only = prefs.am_masks_only end
    if prefs.am_export_alpha ~= nil then props.am_export_alpha = prefs.am_export_alpha end
    if prefs.namingPattern ~= nil then props.namingPattern = prefs.namingPattern end
    if prefs.imageNamingPattern ~= nil then props.imageNamingPattern = prefs.imageNamingPattern end
    if prefs.imageNamingCustomPrefix ~= nil then props.imageNamingCustomPrefix = prefs.imageNamingCustomPrefix end
    if prefs.maxResolution ~= nil then props.maxResolution = prefs.maxResolution end
    if prefs.jpegQuality ~= nil then props.jpegQuality = prefs.jpegQuality end
    if prefs.sensitivity ~= nil then props.sensitivity = prefs.sensitivity end
    if prefs.smoothing ~= nil then props.smoothing = prefs.smoothing end
    if prefs.outputPath ~= nil then props.outputPath = prefs.outputPath end
    if prefs.maskOutputPath ~= nil then props.maskOutputPath = prefs.maskOutputPath end
    if prefs.exportFormat ~= nil then props.exportFormat = prefs.exportFormat end
    if prefs.customResolution ~= nil then props.customResolution = prefs.customResolution end
    if prefs.tiffBitDepth ~= nil then props.tiffBitDepth = prefs.tiffBitDepth end
    if prefs.tiffCompression ~= nil then props.tiffCompression = prefs.tiffCompression end
    if prefs.enableSounds ~= nil then props.enableSounds = prefs.enableSounds end
    if prefs.matteType ~= nil then props.matteType = prefs.matteType end
end

-- Preset system
local function getPresets()
    if prefs.presets == nil then
        prefs.presets = {}
    end
    return prefs.presets
end

local function savePreset(name, props)
    local presets = getPresets()
    presets[name] = {
        cat_humans = props.cat_humans,
        cat_cars = props.cat_cars,
        cat_animals = props.cat_animals,
        cat_furniture = props.cat_furniture,
        cat_electronics = props.cat_electronics,
        cat_vegetation = props.cat_vegetation,
        customClasses = props.customClasses,
        excludeClasses = props.excludeClasses,
        am_invert = props.am_invert,
        am_birefnet_refine = props.am_birefnet_refine,
        am_masks_only = props.am_masks_only,
        am_export_alpha = props.am_export_alpha,
        maxResolution = props.maxResolution,
        customResolution = props.customResolution,
        namingPattern = props.namingPattern,
        imageNamingPattern = props.imageNamingPattern,
        imageNamingCustomPrefix = props.imageNamingCustomPrefix,
        exportFormat = props.exportFormat,
        tiffBitDepth = props.tiffBitDepth,
        tiffCompression = props.tiffCompression,
        jpegQuality = props.jpegQuality,
        sensitivity = props.sensitivity,
        smoothing = props.smoothing,
    }
    prefs.presets = presets
end

local function loadPreset(name, props)
    local presets = getPresets()
    local preset = presets[name]
    if preset then
        if preset.cat_humans ~= nil then props.cat_humans = preset.cat_humans end
        if preset.cat_cars ~= nil then props.cat_cars = preset.cat_cars end
        if preset.cat_animals ~= nil then props.cat_animals = preset.cat_animals end
        if preset.cat_furniture ~= nil then props.cat_furniture = preset.cat_furniture end
        if preset.cat_electronics ~= nil then props.cat_electronics = preset.cat_electronics end
        if preset.cat_vegetation ~= nil then props.cat_vegetation = preset.cat_vegetation end
        if preset.customClasses ~= nil then props.customClasses = preset.customClasses end
        if preset.excludeClasses ~= nil then props.excludeClasses = preset.excludeClasses end
        if preset.am_invert ~= nil then props.am_invert = preset.am_invert end
        if preset.am_birefnet_refine ~= nil then props.am_birefnet_refine = preset.am_birefnet_refine end
        if preset.am_masks_only ~= nil then props.am_masks_only = preset.am_masks_only end
        if preset.am_export_alpha ~= nil then props.am_export_alpha = preset.am_export_alpha end
        if preset.maxResolution ~= nil then props.maxResolution = preset.maxResolution end
        if preset.customResolution ~= nil then props.customResolution = preset.customResolution end
        if preset.namingPattern ~= nil then props.namingPattern = preset.namingPattern end
        if preset.imageNamingPattern ~= nil then props.imageNamingPattern = preset.imageNamingPattern end
        if preset.imageNamingCustomPrefix ~= nil then props.imageNamingCustomPrefix = preset.imageNamingCustomPrefix end
        if preset.exportFormat ~= nil then props.exportFormat = preset.exportFormat end
        if preset.tiffBitDepth ~= nil then props.tiffBitDepth = preset.tiffBitDepth end
        if preset.tiffCompression ~= nil then props.tiffCompression = preset.tiffCompression end
        if preset.jpegQuality ~= nil then props.jpegQuality = preset.jpegQuality end
        if preset.sensitivity ~= nil then props.sensitivity = preset.sensitivity end
        if preset.smoothing ~= nil then props.smoothing = preset.smoothing end
    end
end

local function deletePreset(name)
    local presets = getPresets()
    presets[name] = nil
    prefs.presets = presets
end

local function getPresetNames()
    local presets = getPresets()
    local names = {}
    for name, _ in pairs(presets) do
        table.insert(names, { title = name, value = name })
    end
    table.sort(names, function(a, b) return a.title < b.title end)
    return names
end

-- Check if AI models are installed
-- (LrFileUtils.exists returns false or "file"/"directory" — never nil,
-- so a `~= nil` comparison would always be true)
local function checkModelsInstalled()
    local modelDir = getModelDir()
    local rfdetr = LrPathUtils.child(modelDir, "rfdetr_seg_medium.onnx")
    return LrFileUtils.exists(rfdetr) and true or false
end



-- ============================================================================
-- Server Mode (managed by MaskBridgeUtils)
-- ============================================================================

local function isServerRunning()
    return MaskBridgeUtils.isServerRunning()
end

-- Removed isServerStarting as it does not exist in MaskBridgeUtils

local function getServerPort()
    return MaskBridgeUtils.getServerPort()
end

-- Start the Python server in background
local function startServer()
    return MaskBridgeUtils.startServer(logMsg)
end

-- Stop the server
local function stopServer()
    MaskBridgeUtils.stopServer(logMsg)
end

-- Send HTTP POST request to server (returns response table or nil)
local function httpPost(endpoint, data)
    return MaskBridgeUtils.httpPost(endpoint, data)
end

-- ============================================================================
-- Backend Engine Selection (fallback for when server not available)
-- ============================================================================

-- Get backend engine path (standalone binary or python script)
local function getBackendEngine()
    return MaskBridgeUtils.getBackendEngineInfo()
end

-- Find Python3 (cross-platform) - Only needed for script mode
findPython3 = function()
    return MaskBridgeUtils.findPython3()
end

-- Open file (cross-platform)
local function openFile(path)
    MaskBridgeUtils.openPath(path)
end

-- Check Python dependencies
local function checkPythonDeps()
    local engineType, enginePath = getBackendEngine()

    -- If we have a standalone binary, dependencies are built-in
    if engineType == "binary" then
        return true, LOC("$$$/MaskBridge/Status/BinaryMode=✓ Standalone engine detected"), "binary"
    end

    local python3 = findPython3()

    -- Check if Python is available
    local redirNull = MaskBridgeUtils.isWindows() and " 2>nul" or " 2>/dev/null"
    local pythonCheck = LrTasks.execute('"' .. python3 .. '" --version' .. redirNull)
    if pythonCheck ~= 0 then
        return false, LOC("$$$/MaskBridge/Error/PythonNotFound=Python 3 not found. Please install Python 3.10+"),
            "python"
    end

    -- Check required packages
    local importCheck = '"' .. python3 .. '" -c "import onnxruntime, cv2, numpy"' .. redirNull
    local pkgStatus = LrTasks.execute(importCheck)
    if pkgStatus ~= 0 then
        return false,
            LOC(
                "$$$/MaskBridge/Error/MissingPackages=Missing Python packages (onnxruntime, opencv-python-headless, numpy)."),
            "packages"
    end

    return true, LOC("$$$/MaskBridge/Status/DepsOK=✓ Python dependencies OK"), "script"
end

-- Resolve the effective export resolution from props. The custom value comes
-- from an edit_field, so it may be a string, empty, or outside the documented
-- 100-10000 px range — a raw `resolution > 0` on a string would error.
local function getEffectiveResolution(props)
    local resolution = props.maxResolution
    if resolution == -1 then
        resolution = tonumber(props.customResolution) or 2048
        resolution = math.floor(resolution)
        if resolution < 100 then resolution = 100 end
        if resolution > 10000 then resolution = 10000 end
    end
    return resolution
end

-- Format time duration for display
local function formatDuration(seconds)
    if seconds < 60 then
        return string.format("%ds", math.floor(seconds))
    elseif seconds < 3600 then
        return string.format("%dm %ds", math.floor(seconds / 60), math.floor(seconds % 60))
    else
        return string.format("%dh %dm", math.floor(seconds / 3600), math.floor((seconds % 3600) / 60))
    end
end

-- ============================================================================
-- Shared request builders (Preview + Generate)
-- One source of truth so the two flows can never drift apart again.
-- ============================================================================

-- Build the prompts list from the category checkboxes + custom classes.
local function buildPrompts(props)
    local prompts = {}
    if props.cat_humans then table.insert(prompts, "person") end
    if props.cat_cars then table.insert(prompts, "vehicle") end
    if props.cat_animals then table.insert(prompts, "animal") end
    if props.cat_furniture then table.insert(prompts, "furniture") end
    if props.cat_electronics then table.insert(prompts, "electronics") end
    if props.cat_vegetation then table.insert(prompts, "plant") end
    if props.customClasses and props.customClasses ~= "" then
        for class in string.gmatch(props.customClasses, "[^,]+") do
            local trimmed = class:match("^%s*(.-)%s*$")
            if trimmed ~= "" then table.insert(prompts, trimmed) end
        end
    end
    return prompts
end

-- JSON payload for the server /process endpoint.
local function buildProcessPayload(props, prompts, imagePath, maskPath, comparison)
    return json.encode({
        image = imagePath,
        output = maskPath,
        prompts = prompts,
        model_dir = getModelDir(),
        threshold = (100 - props.sensitivity) / 100,
        smoothing = props.smoothing or 0,
        invert = props.am_invert and true or false,
        edge_refine = false, -- fast mode = hard mask; soft edges come from BiRefNet only
        birefnet_refine = props.am_birefnet_refine == true,
        exclude = props.excludeClasses,
        comparison = comparison or nil,
    })
end

-- CLI argument string mirroring the /process payload (server-down fallback).
local function buildEngineArgs(props, prompts, imagePath, maskPath)
    local promptsStr = table.concat(prompts, ",")
    local args = string.format(
        '--image %s --output %s --prompts %s --model-dir %s --threshold %.2f --smoothing %d',
        MaskBridgeUtils.shellEscape(MaskBridgeUtils.normalizePath(imagePath)),
        MaskBridgeUtils.shellEscape(MaskBridgeUtils.normalizePath(maskPath)),
        MaskBridgeUtils.shellEscape(promptsStr),
        MaskBridgeUtils.shellEscape(MaskBridgeUtils.normalizePath(getModelDir())),
        (100 - props.sensitivity) / 100,
        props.smoothing or 0
    )
    if props.am_invert then args = args .. " --invert" end
    -- Redundant with the new CLI default, kept so an older binary still
    -- produces the hard mask.
    args = args .. " --no-edge-refine"
    if props.am_birefnet_refine == true then args = args .. " --birefnet-refine" end
    if props.excludeClasses and props.excludeClasses ~= "" then
        args = args .. ' --exclude ' .. MaskBridgeUtils.shellEscape(props.excludeClasses)
    end
    return args
end

-- How many images to keep in flight during a batch.
--
-- The backend server is threaded and one inference does not saturate a modern
-- CPU, so the AI step parallelises well: measured on an M2 Pro (8 performance
-- cores), 8 images at 2048px took 2.97s sequential vs 1.43s on 3 workers.
-- Deliberately conservative — the curve flattens quickly, each image in flight
-- costs backend RAM, and an underpowered machine must not thrash. Set the cap
-- to 1 to make batches strictly sequential again.
local MAX_AI_WORKERS = 3
local function getWorkerCount(props)
    -- Fine detail serialises on a single BiRefNet session backend-side, so extra
    -- workers there would only queue while holding full-resolution images.
    if props.am_birefnet_refine == true then return 1 end

    local cpus = 4
    pcall(function()
        local n = LrSystemInfo.numCPUs()
        if type(n) == "number" and n > 0 then cpus = n end
    end)
    local n = math.floor(cpus / 3)
    if n < 1 then n = 1 end
    if n > MAX_AI_WORKERS then n = MAX_AI_WORKERS end
    return n
end

-- Quick Preview: process single photo and show result
-- getTargetPhotos returns the whole filmstrip when Lightroom has no selection.
-- Require an active photo before accepting that list for any dashboard action.
local function getSelectedPhotos(catalog)
    if not catalog:getTargetPhoto() then return {} end
    return catalog:getTargetPhotos()
end

local function runPreviewWork(props, catalog)
    if not checkModelsInstalled() then
        LrDialogs.showError(LOC(
            "$$$/MaskBridge/Error/ModelsNotInstalled=AI models are missing. Please reinstall Mask Bridge."))
        return
    end

    local selectedPhotos = getSelectedPhotos(catalog)
    if #selectedPhotos == 0 then
        LrDialogs.showError(LOC("$$$/MaskBridge/Error/NoPhotosSelected=No photos selected."))
        return
    end

    -- Use only the first photo for preview
    local previewPhoto = { selectedPhotos[1] }

    -- Re-entrance guard: a second click during a run would race the first
    -- (shared dashboard-mode flag, concurrent pipelines)
    if props._previewRunning then
        LrDialogs.showBezel(LOC("$$$/MaskBridge/Preview/AlreadyRunning=Preview already running..."), 2)
        return
    end
    props._previewRunning = true

    MaskBridgeUtils.runInline(function()
        -- Wait for server if not running
        if not isServerRunning() then
            local waitScope = LrProgressScope({
                title = LOC("$$$/MaskBridge/Preview/StartingServer=Mask Bridge - Starting AI Server...")
            })

            -- Only try to start server if models are installed
            if checkModelsInstalled() then
                startServer()
            end

            -- Step 1: Wait for HTTP Server to respond (should be fast now)
            waitScope:setCaption(LOC("$$$/MaskBridge/Preview/Connecting=Connecting to server..."))
            local serverConnected = false
            for i = 1, 40 do -- 20 seconds max for process start
                if isServerRunning() then
                    serverConnected = true
                    break
                end
                waitScope:setPortionComplete(i, 40)
                LrTasks.sleep(0.5)
            end

            -- Step 2: Wait for Models to Load (Async)
            if serverConnected then
                waitScope:setCaption(LOC(
                    "$$$/MaskBridge/Preview/LoadingModels=Loading AI models into memory (this happens once)..."))
                -- Poll /health endpoint to check 'models_loaded' flag
                local modelsReady = false
                local lastResponse = ""
                for i = 1, 140 do -- 70 seconds max for model loading
                    local response = httpPost("/health", "{}")
                    if response then
                        lastResponse = response
                        -- Safe decode and log
                        -- Aggressive sanitize: keep only content between first { and last }
                        local cleanResponse = response:match("({.*})")
                        if not cleanResponse then cleanResponse = response end -- Fallback

                        local status, data = pcall(json.decode, cleanResponse)

                        -- Fallback: Regex check if JSON decode fails
                        if not status or not data then
                            logMsg("JSON Decode Error: " .. tostring(data))
                            if cleanResponse:find('"models_loaded"%s*:%s*true') then
                                logMsg("Fallback: Regex confirmed models_loaded=true")
                                modelsReady = true
                                break
                            end
                        end

                        if status and data then
                            -- DEBUG LOG (Log every 5s)
                            if (i % 10 == 0) then logMsg("Health check response: " .. response) end

                            if data.models_loaded == true then
                                modelsReady = true
                                break
                            end
                        else
                            logMsg("Failed to decode health response: " .. tostring(response))
                        end
                    end
                    waitScope:setPortionComplete(i, 140)
                    LrTasks.sleep(0.5)
                end

                if not modelsReady then
                    logMsg("Model loading timed out (70s). Last response: " .. tostring(lastResponse))
                    LrDialogs.showError(LOC(
                        "$$$/MaskBridge/Error/ModelTimeout=AI models took too long to load. Using fallback mode."))
                end
            else
                LrDialogs.showError(LOC("$$$/MaskBridge/Error/ServerFailed=AI server failed to start. Using slow mode."))
            end

            waitScope:done()
        end

        -- Build prompts (shared builder — same list as Generate)
        local prompts = buildPrompts(props)

        if #prompts == 0 then
            props._previewRunning = false
            LrDialogs.showError(LOC(
                "$$$/MaskBridge/Error/NoClassesSelected=No object class selected.\nCheck at least one category or enter a custom class."))
            return
        end

        -- Create unique temp folder for this preview (timestamp + random:
        -- two runs in the same second must not share a directory)
        local tempDir = LrPathUtils.getStandardFilePath('temp')
        local previewDir = LrPathUtils.child(tempDir, "maskbridge_preview_" .. os.time() .. "_" .. math.random(10000))
        LrFileUtils.createDirectory(previewDir)

        -- Export settings for preview (smaller for speed)
        local exportSettings = {
            am_internalRender = true,
            LR_collisionHandling = "rename",
            LR_export_destinationType = "specificFolder",
            LR_export_destinationPathPrefix = previewDir,
            LR_export_useSubfolder = false,
            LR_format = "JPEG",
            LR_jpeg_quality = 0.8,
            LR_outputSharpeningOn = false,
            LR_size_doConstrain = true,
            LR_size_maxHeight = 1024,
            LR_size_maxWidth = 1024,
            LR_size_resizeType = "longEdge",
        }

        local progressScope = LrProgressScope({
            title = LOC("$$$/MaskBridge/Preview/Title=Mask Bridge - Preview")
        })
        progressScope:setCaption(LOC("$$$/MaskBridge/Preview/Exporting=Exporting preview image..."))

        -- Prevent ExportProvider from also processing (we handle it here).
        -- Yield-safe pcall + guaranteed reset on every path: a failed export must
        -- never leave the flag stuck, or File > Export AI processing silently
        -- becomes a no-op until the plugin reloads.
        MaskBridgeUtils.setDashboardMode(true)

        local exportSession = LrExportSession({
            photosToExport = previewPhoto,
            exportSettings = exportSettings,
        })

        local exportOk, exportErr = LrTasks.pcall(function()
            exportSession:doExportOnCurrentTask()
        end)

        local imagePath, maskPath
        if exportOk then
            for _, rendition in exportSession:renditions() do
                local success, path = rendition:waitForRender()
                if success then
                    imagePath = path
                    local stem = LrPathUtils.removeExtension(LrPathUtils.leafName(path))
                    maskPath = LrPathUtils.child(previewDir, stem .. ".mask.png")
                end
            end
        else
            logMsg("Preview export error: " .. tostring(exportErr))
        end

        MaskBridgeUtils.setDashboardMode(false)

        if not imagePath then
            props._previewRunning = false
            progressScope:done()
            LrFileUtils.delete(previewDir)
            LrDialogs.showError(LOC("$$$/MaskBridge/Preview/ExportFailed=Preview export failed."))
            return
        end

        progressScope:setCaption(LOC("$$$/MaskBridge/Preview/Processing=Processing with AI..."))

        local startTime = os.time()
        local status = -1
        local comparisonPath = nil -- Will hold overlay image path if generated

        -- Check server status with detailed logging
        local serverRunning = isServerRunning()
        local serverPort = getServerPort()
        logMsg("Server check: running=" .. tostring(serverRunning) .. ", port=" .. tostring(serverPort))

        -- Try server mode first (fast - models already loaded)
        if serverRunning then
            logMsg("Using server mode for preview")

            -- Shared payload builder + comparison=true to get the overlay image
            local jsonData = buildProcessPayload(props, prompts, imagePath, maskPath, true)

            local response, err = httpPost("/process", jsonData)
            logMsg("Server response: " .. tostring(response))
            if response then
                local ok, result = pcall(json.decode, response)
                if ok and result and type(result) == "table" then
                    if result.status == "success" then
                        status = 0
                        if result.comparison then
                            comparisonPath = result.comparison
                        end
                    else
                        local errorMsg = result.message or result.error or "Unknown error"
                        logMsg("Server processing failed: " .. errorMsg)
                        LrDialogs.showError(LOC("$$$/MaskBridge/Error/ServerError=Server error: ^1", errorMsg))
                        status = 1
                    end
                else
                    logMsg("JSON decode failed on /process response: " .. tostring(response))
                    status = 1
                end
            else
                logMsg("HTTP request failed: " .. tostring(err))
                status = 1
            end
        else
            -- Fallback: direct script execution (slow - reloads models)
            logMsg("Server not running, using direct execution (slow)")

            -- Warn user about slower processing
            progressScope:setCaption(LOC("$$$/MaskBridge/Preview/SlowMode=Processing (slow mode - AI reloading)..."))

            -- Shared args builder + preview-only --comparison flag
            local args = buildEngineArgs(props, prompts, imagePath, maskPath) .. " --comparison"
            local backendCmd = MaskBridgeUtils.getBackendEngine()
            local cmd = string.format('%s %s', backendCmd, args)

            status = MaskBridgeUtils.executeCommand(cmd, nil)

            -- CLI comparison output path (must match server naming: _overlay.jpg)
            comparisonPath = maskPath:gsub("%.png$", "_overlay.jpg")
        end

        local elapsed = os.time() - startTime

        progressScope:done()

        if status == 0 and LrFileUtils.exists(maskPath) then
            -- Show non-blocking bezel notification and immediately open result
            LrDialogs.showBezel(
                LOC("$$$/MaskBridge/Preview/SuccessBezel=Mask generated in ^1s — Opening preview...", elapsed),
                2
            )
            -- Open overlay comparison if available, otherwise open mask + original
            if comparisonPath and LrFileUtils.exists(comparisonPath) then
                openFile(comparisonPath)
            else
                openFile(imagePath)
                openFile(maskPath)
            end
        else
            -- Detailed error message
            local errorMsg = LOC("$$$/MaskBridge/Preview/FailedDetail=Preview failed — no mask was created (status ^1).",
                tostring(status))
            logMsg("Preview failed: status=" .. tostring(status) .. ", maskPath=" .. tostring(maskPath))
            LrDialogs.showError(errorMsg)
        end

        -- Cleanup after 30 seconds
        LrTasks.startAsyncTask(function()
            LrTasks.sleep(30)
            if LrFileUtils.exists(imagePath) then LrFileUtils.delete(imagePath) end
            if LrFileUtils.exists(maskPath) then LrFileUtils.delete(maskPath) end
            if comparisonPath and LrFileUtils.exists(comparisonPath) then LrFileUtils.delete(comparisonPath) end
            -- Cleanup empty preview directory
            LrFileUtils.delete(previewDir)
        end)

        props._previewRunning = false
    end)
end

local function runPreview(props, catalog)
    local frozen = MaskBridgeUtils.snapshot(props)
    MaskBridgeUtils.startOperation("preview", function() runPreviewWork(frozen, catalog) end)
end

-- Floating dialogs are sized at opening. Keep the scroll document and viewport
-- widths consistent: fill_horizontal alone does not stretch the document on Windows.
local function getDashboardLayout()
    local isWin = MaskBridgeUtils.isWindows()
    local appW, appH = 1200, 800
    local ok, w, h = pcall(LrSystemInfo.appWindowSize)
    if ok then
        if type(w) == "table" then h = w.height or w.h or w[2]; w = w.width or w.w or w[1] end
        if type(w) == "number" and w > 0 then appW = w end
        if type(h) == "number" and h > 0 then appH = h end
    end
    local compact = appW < 1100 or appH < 760
    local viewportWidth = compact and 480 or 560
    local height = math.max(280, math.min(isWin and 680 or 760, appH - 220))
    local frameKey = compact and "MaskBridgeDashboard_v12_compact" or "MaskBridgeDashboard_v12_normal"
    if not isWin then
        -- Cocoa restores the whole saved frame even when the new scroll view is
        -- shorter, leaving a blank area below it. Keep frames for matching view
        -- heights, in 40-point steps to bound the number of saved geometries.
        height = math.floor(height / 40) * 40
        frameKey = frameKey .. "_mac_h" .. tostring(height)
    end
    return {
        viewportWidth = viewportWidth,
        contentWidth = viewportWidth - (isWin and 26 or 22),
        height = height,
        frameKey = frameKey,
    }
end

-- On Windows Win32, '&' is an accelerator mnemonic prefix and is stripped in titles/labels unless escaped as '&&'.
local function escapeAmpersand(str)
    if MaskBridgeUtils.isWindows() and str then
        return (string.gsub(str, "&", "&&"))
    end
    return str
end

-- Main Dashboard
-- The Windows name editor closes/reopens the dashboard; keep its unsaved name
-- in memory until Save rather than writing a draft into persistent preferences.
local windowsPresetDraft = ""
local function showDashboard()
    logMsg("Attempting to open Dashboard...")
    LrFunctionContext.callWithContext("MaskBridgeDashboard", function(context)
        logMsg("Inside Context")
        local f = LrView.osFactory()
        local catalog = LrApplication.activeCatalog()
        local selectedPhotos = getSelectedPhotos(catalog)
        local props = LrBinding.makePropertyTable(context)

        -- Default values - Categories
        props.cat_humans = true
        props.cat_cars = false
        props.cat_animals = false
        props.cat_furniture = false
        props.cat_electronics = false
        props.cat_vegetation = false

        -- Advanced detection
        props.customClasses = ""
        props.excludeClasses = ""

        -- Options
        props.am_invert = false
        props.am_birefnet_refine = false -- Fine-detail mode (BiRefNet matting). Opt-in: ~+5s/image. Off by default. (Guided-filter "refine edges" removed.)
        props.am_masks_only = false
        props.am_export_alpha = false
        props.namingPattern = "standard"      -- Default naming: .mask.png
        props.imageNamingPattern = "original" -- Default: keep original filename
        props.imageNamingCustomPrefix = ""    -- Custom prefix for image naming
        props.photoCount = #selectedPhotos
        props.outputPath = LrPathUtils.getStandardFilePath('desktop')
        props.maskOutputPath = "" -- Default to empty (same as output path)

        -- Export settings
        props.maxResolution = 2048
        props.customResolution = 3000 -- Custom resolution value when "Custom" is selected
        props.exportFormat = "JPEG"   -- JPEG, TIFF, PNG
        props.tiffBitDepth = 16       -- 8 or 16
        props.tiffCompression = "LZW" -- None, LZW, ZIP
        props.jpegQuality = 90

        -- Detection settings
        -- Sensitivity maps to threshold as (100 - s) / 100, so the default
        -- derives from the single source of truth (DEFAULT_THRESHOLD 0.35 →
        -- sensitivity 65) and matches the backend default used by File > Export.
        props.sensitivity = 100 - math.floor(MaskBridgeConfig.DEFAULT_THRESHOLD * 100 + 0.5)
        props.smoothing = 0 -- 0-20, edge smoothing for consistency

        -- UX settings
        props.enableSounds = true -- Play notification sounds after batch processing

        -- Matte export settings
        props.matteType = "subject" -- Default mask type

        -- Load saved settings from previous session
        loadSettings(props)
        logMsg("Settings loaded")

        -- Preset management
        props.selectedPreset = ""
        props.newPresetName = MaskBridgeUtils.isWindows() and windowsPresetDraft or ""

        -- Model status
        props.modelsInstalled = checkModelsInstalled()

        logMsg("Models checked: " .. tostring(props.modelsInstalled))
        props.serverRunning = false -- Will be updated async to avoid blocking UI
        props.serverStatus = LOC("$$$/MaskBridge/Dashboard/ServerStatus/Starting=AI Starting...")
        props._dialogOpen = true
        props._serverStartupDone = false -- Flag: onShow startup attempt finished

        -- Python dependency check (async to avoid blocking)
        props.depsOK = true -- Assume OK, will update if not
        props.depsMessage = ""

        -- Server status polling is handled by the single unified loop in onShow
        -- (see windowShown callback below)

        LrTasks.startAsyncTask(function()
            local depsOK, depsMsg, _ = checkPythonDeps()
            props.depsOK = depsOK
            props.depsMessage = depsMsg
        end)

        -- Resolution options
        local resolutionItems = {
            { title = LOC("$$$/MaskBridge/Dashboard/Export/ResOriginal=Original"), value = 0 },
            { title = "4096 px",                                                    value = 4096 },
            { title = "2048 px",                                                    value = 2048 },
            { title = "1024 px",                                                    value = 1024 },
            { title = "512 px",                                                     value = 512 },
            { title = LOC("$$$/MaskBridge/Dashboard/Export/ResCustom=Custom"),     value = -1 },
        }

        -- Format options
        local formatItems = {
            { title = "JPEG", value = "JPEG" },
            { title = "TIFF", value = "TIFF" },
            { title = "PNG",  value = "PNG" },
        }

        -- TIFF bit depth options
        local tiffBitDepthItems = {
            { title = "8-bit",  value = 8 },
            { title = "16-bit", value = 16 },
        }

        -- TIFF compression options
        local tiffCompressionItems = {
            { title = "None", value = "None" },
            { title = "LZW",  value = "LZW" },
            { title = "ZIP",  value = "ZIP" },
        }

        -- ================================================================
        -- Matte Export
        -- ================================================================
        local function startMatteExportWork(props)
            logMsg("startMatteExport() called")
            saveSettings(props)
            local selectedPhotos = getSelectedPhotos(catalog)
            if #selectedPhotos == 0 then
                LrDialogs.showError(LOC("$$$/MaskBridge/Error/NoPhotosSelected=No photos selected."))
                return
            end

            -- Gather existing masks (async, must be in Develop context)
            local existingMasksItems = {}
            local existingMasksLookup = {} -- ID → name

            MaskBridgeUtils.runInline(function()
                -- Windows: the dashboard is a topmost floating window the SDK
                -- cannot lower (no toBack) and modals cannot be raised above
                -- (no level/parent), so the config + result dialogs below open
                -- *behind* it. Close it for the whole export and reopen at every
                -- exit point. macOS keeps it open (z-order works there).
                local hideDash = MaskBridgeUtils.isWindows() and props.closeDialog ~= nil
                if hideDash then props.closeDialog() end

                -- Switch to Develop + Masking to read existing masks
                existingMasksItems = MaskBridgeMatte.getExistingMasks()
                for _, item in ipairs(existingMasksItems) do
                    existingMasksLookup[item.value] = item.name
                end

                -- Now present the dialog (must be in async context)
                local matteMode = "new" -- "new" or "existing"
                local matteType = props.matteType or "subject"
                local existingMaskID = nil
                local enhancedDetection = true
                local maskTypeItems = MaskBridgeMatte.getMaskTypes()

                LrFunctionContext.callWithContext("MatteTypeChooser", function(ctx)
                    local mProps = LrBinding.makePropertyTable(ctx)
                    mProps.matteMode = "new"
                    mProps.matteType = matteType
                    mProps.existingMaskID = existingMasksItems[1] and existingMasksItems[1].value or ""

                    -- Mode items. "Existing Mask" targets one specific mask ID, which
                    -- only exists on the active photo (mask IDs are per-photo), so it is
                    -- offered only for a single-photo selection. For batches, the
                    -- per-photo modes (All Combined / All Individual / New AI Mask) apply.
                    local modeItems = {
                        { title = LOC("$$$/MaskBridge/Matte/ModeNew=New AI Mask"), value = "new" },
                    }
                    if #selectedPhotos == 1 then
                        table.insert(modeItems,
                            { title = LOC("$$$/MaskBridge/Matte/ModeExisting=Existing Mask"), value = "existing" })
                    end
                    table.insert(modeItems,
                        { title = LOC("$$$/MaskBridge/Matte/ModeAllCombined=All Masks (Combined)"), value = "all_combined" })
                    table.insert(modeItems,
                        { title = LOC("$$$/MaskBridge/Matte/ModeAllIndividual=All Masks (Individual)"), value = "all_individual" })

                    local hasExisting = #existingMasksItems > 0
                    local result = LrDialogs.presentModalDialog({
                        title = LOC("$$$/MaskBridge/Matte/Title=Export Lightroom Masks"),
                        contents = f:column {
                            spacing = 10,
                            bind_to_object = mProps,
                            width = 460,

                            -- Header Description
                            f:group_box {
                                title = LOC("$$$/MaskBridge/Matte/HeaderBox=Lightroom Native Mask Bridge"),
                                fill_horizontal = 1,
                                f:column {
                                    spacing = 4,
                                    fill_horizontal = 1,
                                    f:static_text {
                                        title = LOC("$$$/MaskBridge/Matte/Description=Extract Lightroom Classic AI masks (Subject, Sky, Background) into external grayscale PNGs or transparent cutouts."),
                                        height_in_lines = 2,
                                        fill_horizontal = 1,
                                        font = "<system/small>",
                                        text_color = LrColor(0.6, 0.6, 0.6),
                                    },
                                },
                            },

                            f:static_text {
                                title = LOC("$$$/MaskBridge/Matte/Fidelity=Estimated binary silhouettes. Soft opacity and gradients are not preserved. A recovery snapshot is saved before export."),
                                width_in_chars = 60, height_in_lines = 3,
                            },
                            -- Mode Selection Group
                            f:group_box {
                                title = LOC("$$$/MaskBridge/Matte/GroupOptions=Export Mode & Options"),
                                fill_horizontal = 1,
                                f:column {
                                    spacing = 8,
                                    fill_horizontal = 1,

                                    -- Mode selector
                                    f:row {
                                        fill_horizontal = 1,
                                        f:static_text {
                                            title = LOC("$$$/MaskBridge/Matte/LabelMode=Mode:"),
                                            width_in_chars = 12,
                                            font = "<system/bold>",
                                        },
                                        f:popup_menu {
                                            value = LrView.bind { bind_to_object = mProps, key = "matteMode" },
                                            items = modeItems,
                                            fill_horizontal = 1,
                                        },
                                    },

                                    -- New AI mask type (visible when mode = "new")
                                    f:row {
                                        fill_horizontal = 1,
                                        visible = LrView.bind { bind_to_object = mProps, key = "matteMode",
                                            transform = function(v) return v == "new" end },
                                        f:static_text {
                                            title = LOC("$$$/MaskBridge/Matte/LabelAIType=AI Type:"),
                                            width_in_chars = 12,
                                        },
                                        f:popup_menu {
                                            value = LrView.bind { bind_to_object = mProps, key = "matteType" },
                                            items = maskTypeItems,
                                            fill_horizontal = 1,
                                        },
                                    },

                                    -- Existing mask picker (visible when mode = "existing")
                                    f:row {
                                        fill_horizontal = 1,
                                        visible = LrView.bind { bind_to_object = mProps, key = "matteMode",
                                            transform = function(v) return v == "existing" end },
                                        f:static_text {
                                            title = LOC("$$$/MaskBridge/Matte/LabelMask=Mask:"),
                                            width_in_chars = 12,
                                        },
                                        f:popup_menu {
                                            value = LrView.bind { bind_to_object = mProps, key = "existingMaskID" },
                                            items = hasExisting and existingMasksItems
                                                or { { title = LOC("$$$/MaskBridge/Matte/NoMasks=(no masks found)"), value = "" } },
                                            fill_horizontal = 1,
                                            enabled = hasExisting,
                                        },
                                    },

                                    f:separator { fill_horizontal = 1 },

                                    -- Selection count badge
                                    f:row {
                                        fill_horizontal = 1,
                                        f:static_text {
                                            title = LOC("$$$/MaskBridge/Matte/PhotosSelected=^1 photo(s) selected", #selectedPhotos),
                                            font = "<system/small/bold>",
                                            text_color = LrColor(0.4, 0.7, 0.4),
                                        },
                                    },
                                },
                            },
                        },
                        actionVerb = LOC("$$$/MaskBridge/Matte/Export=Export Lightroom Masks"),
                    })

                    if result == "ok" then
                        matteMode = mProps.matteMode
                        matteType = mProps.matteType
                        existingMaskID = mProps.existingMaskID
                        -- "Existing Mask" with nothing to pick must not fall through
                        -- to the New AI branch silently
                        if matteMode == "existing" and (not existingMaskID or existingMaskID == "") then
                            LrDialogs.showError(LOC(
                                "$$$/MaskBridge/Matte/NoMaskSelected=No mask available on this photo.\nApply a mask in Develop first, or choose another mode."))
                            matteMode = nil
                        end
                    else
                        matteMode = nil -- cancelled
                    end
                end)

                if not matteMode then
                    if hideDash and not MaskBridgeUtils.isDashboardOpen() then showDashboard() end
                    return
                end

                -- Save preference
                props.matteType = matteType

                -- Output directory
                local outputDir = props.maskOutputPath
                if not outputDir or outputDir == "" then
                    outputDir = props.outputPath
                end

                -- Resolution
                local resolution = getEffectiveResolution(props)

                local options = {
                    resolution        = resolution,
                    invert            = props.am_invert,
                    namingPattern     = props.namingPattern or "standard",
                    masksOnly         = props.am_masks_only ~= false,
                    enhancedDetection = enhancedDetection,
                    imageNaming       = props.imageNamingPattern or "original",
                    imageNamingCustom = props.imageNamingCustomPrefix or "",
                    exportFormat      = props.exportFormat or "JPEG",
                    jpegQuality       = props.jpegQuality or 90,
                    tiffBitDepth      = props.tiffBitDepth or 16,
                    tiffCompression   = props.tiffCompression or "LZW",
                    imageOutputDir    = props.outputPath,
                    exportAlpha       = props.am_export_alpha == true,
                }

                -- Run the appropriate export
                local progressScope = LrProgressScope({
                    title = LOC("$$$/MaskBridge/Matte/Progress=Mask Bridge — Export Lightroom Masks")
                })
                options.progressScope = progressScope
                options.isCanceled = function() return progressScope:isCanceled() end

                local successCount, failCount = 0, 0
                -- Photos the AI could not detect the requested subject in
                -- (new-mask mode only). Reported as a clean skip, not a failure.
                local skippedCount, skippedNames = 0, {}
                -- Success message denominator: photos by default, but the
                -- Individual mode counts MASKS (several per photo)
                local totalUnits = #selectedPhotos

                if matteMode == "all_combined" then
                    -- All Combined mode: export all masks merged into one PNG per photo
                    local total = #selectedPhotos

                    for i, photo in ipairs(selectedPhotos) do
                        if progressScope:isCanceled() then break end
                        local fileName = photo:getFormattedMetadata('fileName') or "?"
                        progressScope:setCaption(LOC("$$$/MaskBridge/Processing/CaptionCombined=Combined ^1/^2: ^3", i, total, fileName))
                        progressScope:setPortionComplete(i - 1, total)

                        catalog:setSelectedPhotos(photo, { photo })
                        LrTasks.sleep(1)

                        -- Re-enumerate THIS photo's own masks (mask IDs are per-photo;
                        -- reusing the active photo's list fails on every other photo)
                        local photoMasks = MaskBridgeMatte.getExistingMasks()

                        options._batchIndex = i
                        local ok, result = MaskBridgeMatte.exportMatteAllCombined(
                            photo, photoMasks, outputDir, options
                        )
                        if ok then
                            successCount = successCount + 1
                        else
                            failCount = failCount + 1
                        end
                    end

                    progressScope:setPortionComplete(total, total)
                    progressScope:done()
                elseif matteMode == "all_individual" then
                    -- All Individual mode: export each mask separately per photo
                    local total = #selectedPhotos
                    totalUnits = 0

                    for i, photo in ipairs(selectedPhotos) do
                        if progressScope:isCanceled() then break end
                        local fileName = photo:getFormattedMetadata('fileName') or "?"
                        progressScope:setPortionComplete(i - 1, total)

                        catalog:setSelectedPhotos(photo, { photo })
                        LrTasks.sleep(1)

                        -- Re-enumerate THIS photo's own masks (mask IDs are per-photo;
                        -- reusing the active photo's list fails on every other photo)
                        local photoMasks = MaskBridgeMatte.getExistingMasks()
                        totalUnits = totalUnits + #photoMasks
                        progressScope:setCaption(LOC("$$$/MaskBridge/Processing/CaptionIndividual=Photo ^1/^2 (^3 masks): ^4",
                            i, total, #photoMasks, fileName))

                        options._batchIndex = i
                        local sc, fc = MaskBridgeMatte.exportMatteAllIndividual(
                            photo, photoMasks, outputDir, options
                        )
                        successCount = successCount + sc
                        failCount = failCount + fc
                    end

                    progressScope:setPortionComplete(total, total)
                    progressScope:done()
                elseif matteMode == "existing" and existingMaskID and existingMaskID ~= "" then
                    -- Existing mask mode: export selected mask for each photo
                    local maskName = existingMasksLookup[existingMaskID] or "mask"
                    local total = #selectedPhotos

                    for i, photo in ipairs(selectedPhotos) do
                        if progressScope:isCanceled() then break end
                        local fileName = photo:getFormattedMetadata('fileName') or "?"
                        progressScope:setCaption(LOC("$$$/MaskBridge/Processing/CaptionMask=Mask ^1/^2: ^3", i, total, fileName))
                        progressScope:setPortionComplete(i - 1, total)

                        catalog:setSelectedPhotos(photo, { photo })
                        LrTasks.sleep(1)

                        options._batchIndex = i
                        local ok, result = MaskBridgeMatte.exportMatteExisting(
                            photo, existingMaskID, maskName, outputDir, options
                        )
                        if ok then
                            successCount = successCount + 1
                        else
                            failCount = failCount + 1
                        end
                    end

                    progressScope:setPortionComplete(total, total)
                    progressScope:done()
                else
                    -- New AI mask mode. Lightroom 15.3+ computes Subject, Sky and
                    -- Background masks for the whole selection at once; other
                    -- types and older versions keep the per-photo path.
                    local exportBatch = MaskBridgeMatte.exportMattesBatch
                    if #selectedPhotos > 1 and MaskBridgeMatte.canBatchAI(matteType) then
                        exportBatch = MaskBridgeMatte.exportMattesBatchAI
                    end
                    successCount, failCount, skippedCount, skippedNames =
                        exportBatch(selectedPhotos, matteType, outputDir, options)
                end

                -- Show result and play notification sound.
                -- "Skipped" photos (AI found no matching subject) are NOT
                -- failures — they get a friendly, explanatory summary.
                if progressScope:isCanceled() then
                    playNotificationSound(false)
                    LrDialogs.showBezel(LOC("$$$/MaskBridge/Processing/CanceledWithCount=Batch canceled: ^1 masks generated.", successCount), 3)
                elseif failCount == 0 and skippedCount == 0 then
                    playNotificationSound(true)
                    LrDialogs.showBezel(
                        LOC("$$$/MaskBridge/Processing/BatchSuccess=✅ Masks: ^1/^2 exported", successCount, totalUnits), 3
                    )
                elseif failCount == 0 and skippedCount > 0 then
                    -- Everything that could be detected was exported; some
                    -- photos simply had no matching subject. Not an error.
                    playNotificationSound(true)
                    local skippedList = table.concat(skippedNames, ", ")
                    LrDialogs.message(
                        LOC("$$$/MaskBridge/Matte/ResultTitle=Export Lightroom Masks Complete"),
                        LOC("$$$/MaskBridge/Processing/BatchSkipped=^1 exported, ^2 skipped — no matching subject was found in: ^3",
                            successCount, skippedCount, skippedList),
                        "info"
                    )
                else
                    playNotificationSound(false)
                    -- Keep the existing failure message untouched and append the
                    -- skipped count (if any) on its own line — avoids changing
                    -- the already-translated BatchPartialFailureLog string.
                    local msg = LOC("$$$/MaskBridge/Processing/BatchPartialFailureLog=^1 success, ^2 failed.\nSee log: ^3",
                        successCount, failCount,
                        MaskBridgeUtils.getLogPath("matte_export.log"))
                    if skippedCount > 0 then
                        msg = msg .. "\n" .. LOC(
                            "$$$/MaskBridge/Processing/BatchSkippedSuffix=^1 skipped (no matching subject)", skippedCount)
                    end
                    LrDialogs.message(
                        LOC("$$$/MaskBridge/Matte/ResultTitle=Export Lightroom Masks Complete"),
                        msg
                    )
                end

                -- Reopen the dashboard now that all dialogs are dismissed.
                if hideDash and not MaskBridgeUtils.isDashboardOpen() then showDashboard() end
            end)
        end

        local function startMatteExport()
            local frozen = MaskBridgeUtils.snapshot(props)
            MaskBridgeUtils.startOperation("startMatteExport", function() startMatteExportWork(frozen) end)
        end

        -- ================================================================
        -- AI Mask Generation
        -- ================================================================
        local function startGenerationWork(props)
            logMsg("startGeneration() called")
            local selectedPhotos = getSelectedPhotos(catalog)
            if #selectedPhotos == 0 then
                LrDialogs.showError(LOC("$$$/MaskBridge/Error/NoPhotosSelected=No photos selected."))
                return
            end
            logMsg("Photos selected: " .. #selectedPhotos) -- DEBUG

            -- Save settings
            saveSettings(props)

            -- Check models
            logMsg("Checking models...")      -- DEBUG
            if not checkModelsInstalled() then
                logMsg("Models check FAILED") -- DEBUG
                LrDialogs.showError(LOC(
                    "$$$/MaskBridge/Error/ModelsNotInstalled=AI models are missing. Please reinstall Mask Bridge."))
                return
            end
            logMsg("Models check passed") -- DEBUG

            MaskBridgeUtils.runInline(function()
                -- Windows: hide the topmost floating dashboard for the whole
                -- generation so its result dialogs are not stuck behind it.
                -- Reopened at every exit point below. macOS is unchanged.
                local hideDash = MaskBridgeUtils.isWindows() and props.closeDialog ~= nil
                if hideDash then props.closeDialog() end

                -- Build prompts (shared builder — same list as Preview)
                local prompts = buildPrompts(props)

                if #prompts == 0 then
                    LrDialogs.showError(LOC(
                        "$$$/MaskBridge/Error/NoClassesSelected=No object class selected.\nCheck at least one category or enter a custom class."))
                    if hideDash and not MaskBridgeUtils.isDashboardOpen() then showDashboard() end
                    return
                end

                logMsg("Starting batch: " .. table.concat(prompts, ", "))

                -- Determine resolution (custom or preset)
                local resolution = getEffectiveResolution(props)

                -- Export settings - base
                local exportSettings = {
                    am_internalRender = true,
                    LR_collisionHandling = "rename",
                    LR_export_destinationType = "specificFolder",
                    LR_export_destinationPathPrefix = props.outputPath,
                    LR_export_useSubfolder = false,
                    LR_format = props.exportFormat,
                    LR_outputSharpeningOn = false,
                    LR_export_colorSpace = "sRGB",
                }

                -- Format-specific settings
                if props.exportFormat == "JPEG" then
                    exportSettings.LR_jpeg_quality = props.jpegQuality / 100
                elseif props.exportFormat == "TIFF" then
                    MaskBridgeUtils.applyTiffSettings(exportSettings, props.tiffBitDepth, props.tiffCompression)
                end
                -- PNG has no additional settings needed

                if props.am_masks_only and not props.am_export_alpha then
                    exportSettings.LR_format = "TIFF"
                    MaskBridgeUtils.applyTiffSettings(exportSettings, 8, "None")
                end

                -- Resolution constraint
                if resolution > 0 then
                    exportSettings.LR_size_doConstrain = true
                    exportSettings.LR_size_maxHeight = resolution
                    exportSettings.LR_size_maxWidth = resolution
                    exportSettings.LR_size_resizeType = "longEdge"
                else
                    exportSettings.LR_size_doConstrain = false
                end

                logMsg("Export session: " ..
                    #selectedPhotos .. " photos, format=" .. props.exportFormat .. ", res=" .. resolution)

                -- Pipeline Mode: Lightroom renders on its own task while this
                -- task consumes renditions as they land — the AI starts on
                -- photo 1 while photo 2+ still render.
                local processedCount = 0 -- masks with at least one detected object
                local emptyCount = 0 -- masks saved for photos with no object detected
                local failedCount = 0
                local failedDetails = {} -- "<file> — <reason>" per failure, for the summary
                local alphaCount = 0
                local warnings = {}
                local total = #selectedPhotos

                -- Determine effective mask output directory
                local maskDir = props.outputPath
                if props.maskOutputPath and props.maskOutputPath ~= "" then
                    maskDir = props.maskOutputPath
                    -- Ensure directory exists
                    if not LrFileUtils.exists(maskDir) then
                        LrFileUtils.createDirectory(maskDir)
                    end
                end

                local progressScope = LrProgressScope({
                    title = LOC(
                        "$$$/MaskBridge/Processing/Title=Mask Bridge - Processing")
                })
                progressScope:setCaption(LOC("$$$/MaskBridge/Processing/Starting=Starting export & process..."))

                -- Prevent ExportProvider from also processing (we handle it here).
                -- The whole rendition loop runs inside a yield-safe pcall so no
                -- error path can leave the flag stuck, or File > Export AI
                -- processing silently becomes a no-op until the plugin reloads.
                MaskBridgeUtils.setDashboardMode(true)

                -- Track timing
                local batchStartTime = os.time()
                local imageIndex = 0

                -- Pipeline: renditions() itself starts Lightroom's rendering
                -- (async) and streams renditions as they land, so the AI starts
                -- on photo 1 while photo 2+ still render. Do NOT also call
                -- doExportOnNewTask(): both start the render and Lightroom
                -- raises "startRendering: can not call twice on same session".
                --
                -- The AI step then runs on a small pool of workers instead of
                -- inline, so several images are in flight at once (see
                -- getWorkerCount). Lightroom tasks are cooperative: they only
                -- switch at a yield, so the shared counters below are never
                -- updated concurrently and need no locking.
                local aiQueue = {}
                local queueClosed = false
                local workersLive = 0
                local completedCount = 0
                local workerCount = getWorkerCount(props)
                logMsg("AI workers: " .. workerCount)

                -- One rendered file, from JPEG/TIFF to mask (+ optional alpha).
                local function processRendered(path, idx)
                    local dir = LrPathUtils.parent(path)
                    local stem = LrPathUtils.removeExtension(LrPathUtils.leafName(path))
                    local namingPattern = props.namingPattern or MaskBridgeUtils.NAMING_STANDARD

                    -- Calculate mask path (using separate directory if configured)
                    local maskPath = MaskBridgeUtils.uniqueOutputPath(MaskBridgeUtils.getMaskPath(dir, stem, namingPattern, props.maskOutputPath))

                    local processingSuccess = false
                    local noDetection = false
                    local failureReason = nil
                    local useServerMode = isServerRunning()

                    if useServerMode then
                        -- Shared payload builder (exact same request as Preview)
                        local jsonData = buildProcessPayload(props, prompts, path, maskPath, false)

                        local response, err = httpPost("/process", jsonData)
                        if response then
                            local ok, result = pcall(json.decode, response)
                            if ok and result and type(result) == "table" and (result.status == "success") then
                                processingSuccess = true
                                noDetection = EngineResult.isEmpty(result)
                                for _, warning in ipairs(type(result.warnings) == "table" and result.warnings or {}) do
                                    warnings[#warnings + 1] = stem .. " — " .. EngineResult.warningText(warning, result)
                                end
                            else
                                local errorMsg = (ok and result and (result.message or result.error)) or "Unknown error"
                                local errorFile = (ok and result and result.file) or stem
                                failureReason = errorMsg
                                logMsg("FAILED: " .. tostring(errorFile) .. " — " .. tostring(errorMsg) ..
                                    " | Response: " .. tostring(response) .. " | Err: " .. tostring(err))
                            end
                        else
                            failureReason = "HTTP request failed: " .. tostring(err)
                            logMsg("FAILED: " .. stem .. " — " .. failureReason)
                        end
                    else
                        -- CLI Fallback (Slow)
                        local args = buildEngineArgs(props, prompts, path, maskPath)
                        local backendCmd = MaskBridgeUtils.getBackendEngine()
                        local cmd = string.format('%s %s', backendCmd, args)

                        local status = MaskBridgeUtils.executeCommand(cmd, nil)
                        processingSuccess = (status == 0 and LrFileUtils.exists(maskPath))
                        if not processingSuccess then
                            failureReason = "engine exit " .. tostring(status)
                        end
                    end

                    if processingSuccess then
                        if noDetection then
                            emptyCount = emptyCount + 1
                        else
                            processedCount = processedCount + 1
                        end

                        -- Alpha Export feature: merge RGB + mask → RGBA PNG
                        if props.am_export_alpha then
                            progressScope:setCaption(LOC(
                                "$$$/MaskBridge/Processing/AlphaMerge=Alpha merge ^1/^2: ^3...",
                                idx, total, stem))
                            logMsg("Alpha Export: rgb=" .. tostring(path) .. " mask=" .. tostring(maskPath))

                            local alphaOutputPath = MaskBridgeUtils.getMaskPath(dir, stem, namingPattern, props.maskOutputPath)
                            alphaOutputPath = MaskBridgeUtils.uniqueOutputPath(string.gsub(alphaOutputPath, "%.png$", "_alpha.png"))
                            logMsg("Alpha output: " .. alphaOutputPath)

                            local alphaStatus = -1

                            -- Try server first
                            if useServerMode then
                                local port = MaskBridgeUtils.getServerPort()
                                if port then
                                    local alphaData = json.encode({
                                        rgb_path = path,
                                        mask_path = maskPath,
                                        output_path = alphaOutputPath,
                                    })
                                    logMsg("Alpha POST /merge-alpha: " .. alphaData)
                                    local alphaResponse, err = httpPost("/merge-alpha", alphaData)
                                    logMsg("Alpha response: " .. tostring(alphaResponse))
                                    if alphaResponse and type(json.decode(alphaResponse)) == "table" and json.decode(alphaResponse).status == "success" then
                                        alphaStatus = 0
                                    else
                                        logMsg("Server alpha failed: " .. tostring(err))
                                    end
                                else
                                    logMsg("Alpha: no server port, skipping server path")
                                end
                            end

                            -- CLI fallback
                            if alphaStatus ~= 0 and not useServerMode then
                                local backendCmd = MaskBridgeUtils.getBackendEngine()
                                if backendCmd then
                                    local alphaCmd = string.format(
                                        '%s --mode alpha --image %s --mask %s --output %s',
                                        backendCmd,
                                        MaskBridgeUtils.shellEscape(MaskBridgeUtils.normalizePath(path)),
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
                                alphaCount = alphaCount + 1
                                logMsg("Alpha OK: " .. alphaOutputPath)
                            else
                                failedCount = failedCount + 1
                                if noDetection then
                                    emptyCount = emptyCount - 1
                                else
                                    processedCount = processedCount - 1
                                end
                                table.insert(failedDetails, stem .. " — alpha export failed (mask saved)")
                                logMsg("Alpha FAILED (status=" .. tostring(alphaStatus) .. ") for " .. stem)
                            end
                        end

                        -- Delete original if requested (Masks Only mode)
                        if props.am_masks_only then
                            LrFileUtils.delete(path)
                        end
                    else
                        failedCount = failedCount + 1
                        table.insert(failedDetails, stem .. " — " .. (failureReason or "?"))
                        -- Cleanup: delete the exported source image on failure
                        if LrFileUtils.exists(path) then
                            LrFileUtils.delete(path)
                        end
                    end
                end

                -- Progress is driven by completions, not by submission order:
                -- with several images in flight they finish out of order.
                local function noteCompletion()
                    completedCount = completedCount + 1
                    local elapsed = os.time() - batchStartTime
                    local remaining = 0
                    if elapsed > 0 and completedCount > 0 then
                        remaining = (total - completedCount) * elapsed / completedCount
                    end
                    progressScope:setPortionComplete(completedCount, total)
                    progressScope:setCaption(LOC(
                        "$$$/MaskBridge/Processing/ProgressPipeline=Processing ^1/^2 • ^3 remaining",
                        completedCount, total, formatDuration(remaining)))
                end

                local function startWorker()
                    workersLive = workersLive + 1
                    LrTasks.startAsyncTask(function()
                        local workerOK, workerError = LrTasks.pcall(function()
                        while true do
                            local item = table.remove(aiQueue, 1)
                            if item then
                                if progressScope:isCanceled() then
                                    -- Cancelled: drop the render instead of masking it,
                                    -- same cleanup as a failure so nothing is left behind.
                                    if LrFileUtils.exists(item.path) then
                                        LrFileUtils.delete(item.path)
                                    end
                                else
                                    -- pcall per image: one bad file must not kill the
                                    -- worker, or the drain below would wait forever.
                                    local ok, err = LrTasks.pcall(function()
                                        processRendered(item.path, item.index)
                                    end)
                                    if not ok then
                                        failedCount = failedCount + 1
                                        table.insert(failedDetails, item.stem .. " — " .. tostring(err))
                                        logMsg("Worker error on " .. tostring(item.path) .. ": " .. tostring(err))
                                    end
                                end
                                noteCompletion()
                            elseif queueClosed then
                                break
                            else
                                LrTasks.sleep(0.05)
                            end
                        end
                        end)
                        workersLive = workersLive - 1
                        if not workerOK then
                            failedCount = failedCount + 1
                            failedDetails[#failedDetails + 1] = tostring(workerError)
                            logMsg("Worker stopped: " .. tostring(workerError))
                        end
                    end)
                end

                local wasCanceled = false
                local loopOk, loopErr = LrTasks.pcall(function()
                    for _ = 1, workerCount do startWorker() end

                    MaskBridgeUtils.forEachExportRendition(selectedPhotos, exportSettings,
                        workerCount * 2, progressScope, function(rendition)
                        while #aiQueue >= workerCount * 2 and not progressScope:isCanceled() do
                            if workersLive == 0 then error("No active AI workers") end
                            LrTasks.sleep(0.1)
                        end
                        local success, path = rendition:waitForRender()
                        imageIndex = imageIndex + 1

                        if progressScope:isCanceled() then
                            wasCanceled = true
                            if success and LrFileUtils.exists(path) then LrFileUtils.delete(path) end
                        elseif success then
                            table.insert(aiQueue, {
                                path = path,
                                index = imageIndex,
                                stem = LrPathUtils.removeExtension(LrPathUtils.leafName(path)),
                            })
                        else
                            -- Render failure (async export task): count it so the
                            -- final summary is truthful instead of silently short.
                            failedCount = failedCount + 1
                            table.insert(failedDetails, "photo " .. imageIndex .. " — render failed")
                            logMsg("Render failed for photo " .. imageIndex .. "/" .. total)
                        end
                    end)
                end)

                -- Drain before reporting, and drain even when the producer above
                -- failed: Lightroom already wrote those files, so abandoning them
                -- would leave images on disk with no mask and no cleanup.
                queueClosed = true
                -- Wait as long as images keep completing, however long the batch
                -- takes, but never hang the dialog on a worker that stopped
                -- reporting. Five minutes without a single completion cannot be
                -- legitimate work: even Fine detail is a few seconds per image.
                local lastSeen, idleWait = completedCount, 0
                while workersLive > 0 do
                    LrTasks.sleep(0.1)
                    if completedCount ~= lastSeen then
                        lastSeen, idleWait = completedCount, 0
                    else
                        idleWait = idleWait + 0.1
                        if idleWait > 300 then
                            wasCanceled = true
                            progressScope:cancel()
                            progressScope:setCaption(LOC("$$$/MaskBridge/Operation/Finishing=Stopping: waiting for active processing to finish safely..."))
                            idleWait = 0
                        end
                    end
                end

                for _, pending in ipairs(aiQueue) do
                    if LrFileUtils.exists(pending.path) then LrFileUtils.delete(pending.path) end
                end
                MaskBridgeUtils.setDashboardMode(false)

                if not loopOk then
                    progressScope:done()
                    logMsg("Batch export error: " .. tostring(loopErr))
                    LrDialogs.message(LOC("$$$/MaskBridge/PluginName=Mask Bridge"),
                        LOC("$$$/MaskBridge/Error/ExportFailed=Export failed. Check that the output folder exists and is writable.")
                            .. "\n\n" .. tostring(loopErr):gsub("</?AgErrorText>", ""), "warning")
                    if hideDash and not MaskBridgeUtils.isDashboardOpen() then showDashboard() end
                    return
                end

                wasCanceled = wasCanceled or progressScope:isCanceled()
                progressScope:done()

                local totalTime = os.time() - batchStartTime
                local emptyNote = emptyCount > 0 and ("\n" .. EngineResult.emptyLine(emptyCount)) or ""

                if #warnings > 0 then
                    LrDialogs.message(LOC("$$$/MaskBridge/PluginName=Mask Bridge"),
                        table.concat(warnings, "\n", 1, math.min(#warnings, 10)), "warning")
                end
                if wasCanceled then
                    playNotificationSound(false)
                    local cancelMsg = LOC("$$$/MaskBridge/Processing/CanceledWithCount=Batch canceled: ^1 masks generated.", processedCount)
                    LrDialogs.showBezel(cancelMsg .. emptyNote, 3)
                elseif failedCount == 0 and processedCount + emptyCount > 0 then
                    playNotificationSound(true)
                    local f = LrView.osFactory()
                    local resultMsg = LOC("$$$/MaskBridge/Processing/CompleteWithTime=Done! ^1 masks generated in ^2.",
                        processedCount, formatDuration(totalTime)) .. emptyNote
                    if alphaCount > 0 then
                        resultMsg = resultMsg .. "\n" .. LOC("$$$/MaskBridge/Processing/AlphaCount=+ ^1 alpha PNG(s) with transparency.", alphaCount)
                    elseif props.am_export_alpha then
                        resultMsg = resultMsg .. "\n" .. LOC(
                            "$$$/MaskBridge/Processing/AlphaNone=⚠ Alpha export was enabled but no alpha files were generated. See log: ^1",
                            MaskBridgeUtils.getLogPath("server_debug.log"))
                    end
                    local action = LrDialogs.presentModalDialog({
                        title = LOC("$$$/MaskBridge/PluginName=Mask Bridge"),
                        contents = f:column {
                            f:static_text {
                                title = resultMsg,
                                width_in_chars = 50,
                                height_in_lines = 4,
                            },
                        },
                        actionVerb = LOC("$$$/MaskBridge/Action/OpenFolder=Open Output Folder"),
                        cancelVerb = LOC("$$$/MaskBridge/Action/OK=OK"),
                    })
                    if action == "ok" then
                        -- Open Mask folder if specific, otherwise output folder
                        local folder = (props.maskOutputPath and props.maskOutputPath ~= "") and props.maskOutputPath or
                            props.outputPath
                        MaskBridgeUtils.openPath(folder)
                    end
                else
                    playNotificationSound(false)
                    local failMsg = LOC(
                        "$$$/MaskBridge/Processing/CompleteWithErrorsLog=Done.\nSuccess: ^1\nFailed: ^2\n\nSee log: ^3",
                        processedCount,
                        failedCount,
                        MaskBridgeUtils.getLogPath("server_debug.log")) .. emptyNote
                    -- Per-file failure details (filenames + backend reason are
                    -- data, not UI strings — no i18n key needed). Cap the list
                    -- so a huge batch cannot blow up the dialog.
                    if #failedDetails > 0 then
                        local shown = {}
                        for i = 1, math.min(#failedDetails, 8) do
                            table.insert(shown, "• " .. failedDetails[i])
                        end
                        if #failedDetails > 8 then
                            table.insert(shown, "• … +" .. (#failedDetails - 8))
                        end
                        failMsg = failMsg .. "\n\n" .. table.concat(shown, "\n")
                    end
                    LrDialogs.message(LOC("$$$/MaskBridge/PluginName=Mask Bridge"), failMsg, "warning")
                end

                -- Reopen the dashboard now that all dialogs are dismissed.
                if hideDash and not MaskBridgeUtils.isDashboardOpen() then showDashboard() end
            end)
        end

        local function startGeneration()
            local frozen = MaskBridgeUtils.snapshot(props)
            MaskBridgeUtils.startOperation("startGeneration", function() startGenerationWork(frozen) end)
        end

        -- A Windows floating window sits above modal dialogs. Close it while
        -- editing, then reopen once, preserving settings even when the user cancels.
        local function settingsDialog(name, fn)
            MaskBridgeUtils.startOperation(name, function()
                saveSettings(props)
                local reopen = MaskBridgeUtils.isWindows() and props.closeDialog ~= nil
                if reopen then props.closeDialog() end
                local ok, err = LrTasks.pcall(fn)
                saveSettings(props)
                if not ok then LrDialogs.showError(tostring(err)) end
                if reopen and not MaskBridgeUtils.isDashboardOpen() then showDashboard() end
            end)
        end

        local function editFormatOptions()
            LrFunctionContext.callWithContext("FormatOptions", function(ctx)
                local opts = LrBinding.makePropertyTable(ctx)
                opts.jpegQuality = props.jpegQuality
                opts.tiffBitDepth = props.tiffBitDepth
                opts.tiffCompression = props.tiffCompression
                local items = { bind_to_object = opts, width = 420, spacing = 10 }
                if props.exportFormat == "JPEG" then
                    items[#items + 1] = f:static_text { title = LOC("$$$/MaskBridge/Dashboard/Export/JPEGQuality=JPEG quality:") }
                    items[#items + 1] = f:row {
                        f:slider { value = LrView.bind("jpegQuality"), min = 50, max = 100, integral = true, fill_horizontal = 1 },
                        f:edit_field { value = LrView.bind("jpegQuality"), min = 50, max = 100, precision = 0, width_in_chars = 4 },
                    }
                elseif props.exportFormat == "TIFF" then
                    items[#items + 1] = f:static_text { title = LOC("$$$/MaskBridge/Dashboard/Export/BitDepth=Bit depth:") }
                    items[#items + 1] = f:popup_menu { value = LrView.bind("tiffBitDepth"), items = tiffBitDepthItems }
                    items[#items + 1] = f:static_text { title = LOC("$$$/MaskBridge/Dashboard/Export/Compression=Compression:") }
                    items[#items + 1] = f:popup_menu { value = LrView.bind("tiffCompression"), items = tiffCompressionItems }
                else
                    items[#items + 1] = f:static_text { title = LOC("$$$/MaskBridge/Dashboard/Export/PNGLossless=PNG uses lossless compression."), width = 400, height_in_lines = 2 }
                end
                local result = LrDialogs.presentModalDialog {
                    title = props.exportFormat .. " — " .. LOC("$$$/MaskBridge/Dashboard/Export/FormatOptions=Format options"),
                    contents = f:column(items),
                    actionVerb = LOC("$$$/MaskBridge/Action/OK=OK"),
                    cancelVerb = LOC("$$$/MaskBridge/Common/Cancel=Cancel"),
                }
                if result == "ok" then
                    props.jpegQuality = opts.jpegQuality
                    props.tiffBitDepth = opts.tiffBitDepth
                    props.tiffCompression = opts.tiffCompression
                end
            end)
        end

        -- Lightroom 15.2.1 on Windows can hang when Tab leaves a destination
        -- edit field inside this floating scroll view (also reproduced manually).
        -- Keep the paths visible here and edit them in a modal with its own focus
        -- scope. macOS retains its existing inline fields and folder chooser.
        local function editDestination(key, title)
            LrFunctionContext.callWithContext("DestinationOptions", function(ctx)
                local opts = LrBinding.makePropertyTable(ctx)
                opts.path = props[key] or ""
                local result = LrDialogs.presentModalDialog {
                    title = title,
                    contents = f:column {
                        bind_to_object = opts, width = 520, spacing = 10,
                        f:edit_field {
                            value = LrView.bind("path"), immediate = true,
                            fill_horizontal = 1,
                            placeholder_string = key == "maskOutputPath" and LOC("$$$/MaskBridge/Dashboard/Output/SameAsImages=(Same as destination folder)") or nil,
                        },
                        f:push_button {
                            title = LOC("$$$/MaskBridge/Dashboard/Output/Choose=Choose…"),
                            action = function()
                                local p = LrDialogs.runOpenPanel { canChooseFiles = false, canChooseDirectories = true, canCreateDirectories = true }
                                if p then opts.path = p[1] end
                            end,
                        },
                    },
                    actionVerb = LOC("$$$/MaskBridge/Action/OK=OK"),
                    cancelVerb = LOC("$$$/MaskBridge/Common/Cancel=Cancel"),
                }
                if result == "ok" then props[key] = opts.path end
            end)
        end

        local function destinationField(key, placeholder, width)
            if not MaskBridgeUtils.isWindows() then
                return f:edit_field { value = LrView.bind(key), tooltip = LrView.bind(key), fill_horizontal = 1, placeholder_string = placeholder }
            end
            return f:static_text {
                title = LrView.bind { key = key, transform = function(v) return v and v ~= "" and v or (placeholder or "") end },
                tooltip = LrView.bind(key), width = width, fill_horizontal = 1,
                height_in_lines = 1, truncation = "middle",
            }
        end

        local function chooseDestination(key, title)
            if MaskBridgeUtils.isWindows() then
                settingsDialog("destinationOptions", function() editDestination(key, title) end)
            else
                local p = LrDialogs.runOpenPanel({ canChooseDirectories = true, canCreateDirectories = true })
                if p then props[key] = p[1] end
            end
        end

        -- Other text controls share the same floating-window Tab defect on
        -- Windows (confirmed with the preset name). Keep every editable value
        -- in a modal focus scope there, without changing the Mac controls.
        local function dashboardTextField(key, title, options)
            options.value = LrView.bind(key)
            if not MaskBridgeUtils.isWindows() then return f:edit_field(options) end
            return f:row {
                fill_horizontal = options.fill_horizontal,
                visible = options.visible,
                f:static_text {
                    title = LrView.bind { key = key, transform = function(v)
                        return v ~= nil and v ~= "" and tostring(v) or (options.placeholder_string or "")
                    end },
                    tooltip = LrView.bind(key),
                    visible = options.visible,
                    fill_horizontal = 1, width_in_chars = options.width_in_chars or 12,
                    height_in_lines = 1, truncation = "middle",
                },
                f:push_button {
                    title = "…", tooltip = title, enabled = options.enabled, visible = options.visible,
                    action = function()
                        settingsDialog("textOptions", function()
                            LrFunctionContext.callWithContext("MaskBridgeTextOptions", function(context)
                                local edited = LrBinding.makePropertyTable(context)
                                edited.value = props[key]
                                local result = LrDialogs.presentModalDialog {
                                    title = title,
                                    contents = f:column {
                                        bind_to_object = edited, width = 520,
                                        f:edit_field {
                                            value = LrView.bind("value"), immediate = true,
                                            fill_horizontal = 1,
                                            placeholder_string = options.placeholder_string,
                                        },
                                    },
                                    actionVerb = LOC("$$$/MaskBridge/Action/OK=OK"),
                                    cancelVerb = LOC("$$$/MaskBridge/Common/Cancel=Cancel"),
                                }
                                if result == "ok" then
                                    props[key] = edited.value
                                    if key == "newPresetName" then windowsPresetDraft = edited.value end
                                end
                            end)
                        end)
                    end,
                },
            }
        end

        local layout = getDashboardLayout()
        local contents = f:column {
            spacing = f:control_spacing(),
            margin = 12,
            bind_to_object = props,
            fill_horizontal = 1,
            fill_vertical = 1,

            -- Header: Photo count + Python warning + AI Status
            f:row {
                f:static_text {
                    title = LrView.bind { key = "photoCount", transform = function(v)
                        return LOC("$$$/MaskBridge/Dashboard/PhotoCount=Selected photos: ^1", v)
                    end },
                    font = "<system/bold>"
                },
                f:spacer { fill_horizontal = 1 },
                -- AI status indicator (always visible, top-right)
                f:static_text {
                    title = "\226\151\143", -- ● filled circle; colour conveys state
                    font = "<system/bold>",
                    text_color = LrView.bind { key = "serverRunning", transform = function(v)
                        if v then return LrColor(0.2, 0.7, 0.3) else return LrColor(0.9, 0.6, 0) end
                    end },
                },
                f:static_text {
                    title = LrView.bind("serverStatus"),
                    tooltip = LrView.bind("depsMessage"),
                    font = "<system/bold>",
                    width_in_chars = 24,
                    text_color = LrView.bind { key = "serverRunning", transform = function(v)
                        if v then return LrColor(0.2, 0.7, 0.3) else return LrColor(0.9, 0.6, 0) end
                    end },
                },
            },

            f:spacer { height = 4 },

            -- Main area: scrollable content (left, 3 logical blocks) + action sidebar (right)
            f:row {
                fill_horizontal = 1,
                fill_vertical = 1,

                -- LEFT: 3 Logical Blocks in scrollable view
                f:scrolled_view {
                    horizontal_scroller = false,
                    vertical_scroller = true,
                    fill_vertical = 1,
                    fill_horizontal = 1,
                    width = layout.viewportWidth,
                    height = layout.height,
                    f:column {
                        spacing = 10,
                        width = layout.contentWidth,

                        -- =========================================================
                        -- 1. DETECTION & AI QUALITY (BLOC 1)
                        -- =========================================================
                        f:group_box {
                            title = escapeAmpersand(LOC("$$$/MaskBridge/Dashboard/Group/DetectionQuality=1. AI Detection & Quality")),
                            fill_horizontal = 1,
                            f:column {
                                spacing = 6,
                                fill_horizontal = 1,

                                -- Quality Mode Switcher (Standard vs HD Fine Detail)
                                f:row {
                                    fill_horizontal = 1,
                                    f:radio_button {
                                        title = LOC("$$$/MaskBridge/Dashboard/Mode/Standard=Standard (Fast)"),
                                        value = LrView.bind {
                                            key = "am_birefnet_refine",
                                            transform = function(v) return not v end
                                        },
                                        checked_value = true,
                                        action = function() props.am_birefnet_refine = false end,
                                    },
                                    f:radio_button {
                                        title = LOC("$$$/MaskBridge/Dashboard/Mode/FineDetail=HD (Fine Detail)"),
                                        value = LrView.bind("am_birefnet_refine"),
                                        checked_value = true,
                                        action = function() props.am_birefnet_refine = true end,
                                    },
                                },
                                f:row {
                                    fill_horizontal = 1,
                                    f:static_text {
                                        title = LrView.bind {
                                            key = "am_birefnet_refine",
                                            transform = function(v)
                                                if v then
                                                    return LOC("$$$/MaskBridge/Dashboard/Mode/FineDetailDescription=Hair strands, fur, feathers")
                                                else
                                                    return LOC("$$$/MaskBridge/Dashboard/Mode/StandardDesc=Binary masks for supported object classes")
                                                end
                                            end
                                        },
                                        font = "<system>",
                                        text_color = LrColor(0.35, 0.35, 0.35),
                                        fill_horizontal = 1,
                                    },
                                },

                                f:separator { fill_horizontal = 1 },

                                -- Categories to detect
                                f:static_text {
                                    title = LOC("$$$/MaskBridge/Dashboard/Objects/SelectPrompt=Objects to detect:"),
                                    font = "<system>",
                                },
                                f:row {
                                    fill_horizontal = 1,
                                    f:checkbox { title = LOC("$$$/MaskBridge/Dashboard/Objects/Humans=Humans"), value = LrView.bind("cat_humans"), fill_horizontal = 1 },
                                    f:checkbox { title = LOC("$$$/MaskBridge/Dashboard/Objects/Vehicles=Vehicles"), value = LrView.bind("cat_cars"), fill_horizontal = 1 },
                                    f:checkbox { title = LOC("$$$/MaskBridge/Dashboard/Objects/Animals=Animals"), value = LrView.bind("cat_animals"), fill_horizontal = 1 },
                                },
                                f:row {
                                    fill_horizontal = 1,
                                    f:checkbox { title = LOC("$$$/MaskBridge/Dashboard/Objects/Furniture=Furniture"), value = LrView.bind("cat_furniture"), fill_horizontal = 1 },
                                    f:checkbox { title = LOC("$$$/MaskBridge/Dashboard/Objects/Electronics=Electronics"), value = LrView.bind("cat_electronics"), fill_horizontal = 1 },
                                    f:checkbox { title = LOC("$$$/MaskBridge/Dashboard/Objects/Plants=Plants"), value = LrView.bind("cat_vegetation"), fill_horizontal = 1 },
                                },

                                -- Quick Presets
                                f:row {
                                    fill_horizontal = 1,
                                    f:static_text { title = LOC("$$$/MaskBridge/Dashboard/Objects/QuickPresets=Quick:"), width_in_chars = 6 },
                                    f:push_button {
                                        title = LOC("$$$/MaskBridge/Dashboard/Presets/Portrait=Portrait"),
                                        font = "<system>",
                                        action = function()
                                            props.cat_humans = true
                                            props.cat_cars = false
                                            props.cat_animals = false
                                            props.cat_furniture = false
                                            props.cat_electronics = false
                                            props.cat_vegetation = false
                                            LrDialogs.showBezel(
                                                LOC("$$$/MaskBridge/Dashboard/Presets/Applied=Preset: ^1",
                                                    LOC("$$$/MaskBridge/Dashboard/Presets/Portrait=Portrait")), 1)
                                        end,
                                    },
                                    f:push_button {
                                        title = LOC("$$$/MaskBridge/Dashboard/Presets/Product=Product"),
                                        font = "<system>",
                                        action = function()
                                            props.cat_humans = false
                                            props.cat_cars = false
                                            props.cat_animals = false
                                            props.cat_furniture = true
                                            props.cat_electronics = true
                                            props.cat_vegetation = false
                                            LrDialogs.showBezel(
                                                LOC("$$$/MaskBridge/Dashboard/Presets/Applied=Preset: ^1",
                                                    LOC("$$$/MaskBridge/Dashboard/Presets/Product=Product")), 1)
                                        end,
                                    },
                                    f:push_button {
                                        title = LOC("$$$/MaskBridge/Dashboard/Presets/Vehicle=Vehicle"),
                                        font = "<system>",
                                        action = function()
                                            props.cat_humans = false
                                            props.cat_cars = true
                                            props.cat_animals = false
                                            props.cat_furniture = false
                                            props.cat_electronics = false
                                            props.cat_vegetation = false
                                            LrDialogs.showBezel(
                                                LOC("$$$/MaskBridge/Dashboard/Presets/Applied=Preset: ^1",
                                                    LOC("$$$/MaskBridge/Dashboard/Presets/Vehicle=Vehicle")), 1)
                                        end,
                                    },
                                    f:push_button {
                                        title = LOC("$$$/MaskBridge/Dashboard/Presets/All=All"),
                                        font = "<system>",
                                        action = function()
                                            props.cat_humans = true
                                            props.cat_cars = true
                                            props.cat_animals = true
                                            props.cat_furniture = true
                                            props.cat_electronics = true
                                            props.cat_vegetation = true
                                            LrDialogs.showBezel(
                                                LOC("$$$/MaskBridge/Dashboard/Presets/Applied=Preset: ^1",
                                                    LOC("$$$/MaskBridge/Dashboard/Presets/All=All")), 1)
                                        end,
                                    },
                                },

                                f:separator { fill_horizontal = 1 },

                                -- Detection Tolerance Slider
                                f:row {
                                    fill_horizontal = 1,
                                    f:static_text { title = LOC("$$$/MaskBridge/Dashboard/Detection/Tolerance=Tolerance:"), width_in_chars = 10 },
                                    f:slider { value = LrView.bind("sensitivity"), min = 10, max = 90, integral = true, fill_horizontal = 1 },
                                    f:static_text {
                                        title = LrView.bind { key = "sensitivity", transform = function(v)
                                            if v < 45 then
                                                return LOC("$$$/MaskBridge/Dashboard/Detection/Strict=Strict")
                                            elseif v < 70 then
                                                return LOC("$$$/MaskBridge/Dashboard/Detection/Normal=Balanced")
                                            elseif v < 85 then
                                                return LOC("$$$/MaskBridge/Dashboard/Detection/Wide=Wide")
                                            else
                                                return LOC("$$$/MaskBridge/Dashboard/Detection/VeryWide=Maximum")
                                            end
                                        end },
                                        width_in_chars = 9,
                                        font = "<system/bold>",
                                    },
                                },
                            }
                        },

                        -- =========================================================
                        -- 2. FORMAT & DESTINATION (BLOC 2)
                        -- =========================================================
                        f:group_box {
                            title = escapeAmpersand(LOC("$$$/MaskBridge/Dashboard/Group/FormatDestination=2. Format & Destination")),
                            fill_horizontal = 1,
                            f:column {
                                spacing = 5,
                                fill_horizontal = 1,

                                f:checkbox { title = LOC("$$$/MaskBridge/Dashboard/Options/MasksOnly=Masks only (skip processed images)"), value = LrView.bind("am_masks_only") },
                                f:checkbox { title = LOC("$$$/MaskBridge/Dashboard/Output/AlphaFile=Also save transparent PNG"), value = LrView.bind("am_export_alpha") },
                                f:static_text {
                                    title = LrView.bind { keys = { "am_masks_only", "am_export_alpha" }, operation = function()
                                        local result = props.am_masks_only and LOC("$$$/MaskBridge/Dashboard/Output/OnlyMasks=Mask PNG")
                                            or LOC("$$$/MaskBridge/Dashboard/Output/ImageAndMask=Processed image + mask PNG")
                                        if props.am_export_alpha then result = result .. " + " .. LOC("$$$/MaskBridge/Dashboard/Output/TransparentPNG=transparent PNG") end
                                        return result
                                    end },
                                    width = layout.contentWidth - 24, height_in_lines = 2,
                                },
                                f:row {
                                    fill_horizontal = 1,
                                    f:static_text { title = LOC("$$$/MaskBridge/Dashboard/Export/Format=Format:"), width_in_chars = 10 },
                                    f:popup_menu { value = LrView.bind("exportFormat"), items = formatItems, width_in_chars = 8 },
                                    f:push_button {
                                        title = LOC("$$$/MaskBridge/Dashboard/Export/FormatOptions=Format options") .. "…",
                                        action = function() settingsDialog("formatOptions", editFormatOptions) end,
                                    },
                                },

                                -- Line 2: Resolution & Custom Size
                                f:row {
                                    fill_horizontal = 1,
                                    f:static_text { title = LOC("$$$/MaskBridge/Dashboard/Export/Resolution=Size:"), width_in_chars = 10 },
                                    f:popup_menu { value = LrView.bind("maxResolution"), items = resolutionItems, fill_horizontal = 1 },
                                    dashboardTextField("customResolution", LOC("$$$/MaskBridge/Dashboard/Export/Resolution=Size:"), {
                                        width_in_chars = 5,
                                        immediate = true,
                                        enabled = LrView.bind { key = "maxResolution", transform = function(v) return v == -1 end },
                                        visible = LrView.bind { key = "maxResolution", transform = function(v) return v == -1 end },
                                    }),
                                    f:static_text {
                                        title = "px",
                                        visible = LrView.bind { key = "maxResolution", transform = function(v) return v == -1 end },
                                    },
                                },

                                -- Destination Output Folders
                                f:static_text { title = LOC("$$$/MaskBridge/Dashboard/Output/Images=Destination Folder:"), font = "<system>" },
                                f:row {
                                    fill_horizontal = 1,
                                    destinationField("outputPath", nil, layout.contentWidth - 100),
                                    f:push_button {
                                        title = LOC("$$$/MaskBridge/Dashboard/Output/Choose=Choose…"),
                                        action = function()
                                            chooseDestination("outputPath", LOC("$$$/MaskBridge/Dashboard/Output/Images=Destination Folder:"))
                                        end
                                    }
                                },
                                f:static_text { title = LOC("$$$/MaskBridge/Dashboard/Output/Masks=Masks Folder (Optional):"), font = "<system>" },
                                f:row {
                                    fill_horizontal = 1,
                                    destinationField("maskOutputPath", LOC("$$$/MaskBridge/Dashboard/Output/SameAsImages=(Same as destination folder)"), layout.contentWidth - 100),
                                    f:push_button {
                                        title = LOC("$$$/MaskBridge/Dashboard/Output/Choose=Choose…"),
                                        action = function()
                                            chooseDestination("maskOutputPath", LOC("$$$/MaskBridge/Dashboard/Output/Masks=Masks Folder (Optional):"))
                                        end
                                    }
                                },

                                -- Transparency Alpha & Invert Mask options
                                f:checkbox {
                                    title = LOC("$$$/MaskBridge/Dashboard/Options/Invert=Invert mask (Select background)"),
                                    value = LrView.bind("am_invert"),
                                },

                                -- Mask naming pattern
                                f:row {
                                    fill_horizontal = 1,
                                    f:static_text { title = LOC("$$$/MaskBridge/Dashboard/Output/MaskNaming=Mask naming:"), width_in_chars = 12 },
                                    f:popup_menu {
                                        value = LrView.bind("namingPattern"),
                                        items = {
                                            { title = LOC("$$$/MaskBridge/Naming/Standard=Standard (.mask.png)"),     value = "standard" },
                                            { title = LOC("$$$/MaskBridge/Naming/Underscore=Underscore (_mask.png)"), value = "underscore" },
                                            { title = LOC("$$$/MaskBridge/Naming/Hyphen=Hyphen (-mask.png)"),         value = "hyphen" },
                                            { title = LOC("$$$/MaskBridge/Naming/Suffix=Suffix (_MaskBridge.png)"),     value = "suffix" },
                                        },
                                        fill_horizontal = 1,
                                    },
                                },
                            }
                        },

                        -- =========================================================
                        -- 3. PRESETS & ADVANCED OPTIONS (BLOC 3)
                        -- =========================================================
                        f:group_box {
                            title = escapeAmpersand(LOC("$$$/MaskBridge/Dashboard/Group/PresetsAdvanced=3. Presets & Advanced Options")),
                            fill_horizontal = 1,
                            f:column {
                                spacing = 4,
                                fill_horizontal = 1,

                                -- Presets Management
                                f:row {
                                    fill_horizontal = 1,
                                    f:static_text { title = LOC("$$$/MaskBridge/Dashboard/Presets/PresetLabel=Preset:"), width_in_chars = 6 },
                                    f:popup_menu {
                                        value = LrView.bind("selectedPreset"),
                                        items = LrView.bind { keys = { "selectedPreset" }, operation = function()
                                            local items = { { title = LOC("$$$/MaskBridge/Dashboard/Presets/Select=-- Select --"), value = "" } }
                                            for _, item in ipairs(getPresetNames()) do table.insert(items, item) end
                                            return items
                                        end },
                                        fill_horizontal = 1,
                                    },
                                    f:push_button { title = LOC("$$$/MaskBridge/Dashboard/Presets/Load=Load"), enabled = LrView.bind { key = "selectedPreset", transform = function(v) return v ~= "" end }, action = function()
                                        if props.selectedPreset ~= "" then
                                            loadPreset(props.selectedPreset, props)
                                            LrDialogs.showBezel(
                                                LOC("$$$/MaskBridge/Dashboard/Presets/Loaded=Preset loaded: ^1",
                                                    props.selectedPreset), 2)
                                        end
                                    end },
                                    f:push_button { title = LOC("$$$/MaskBridge/Dashboard/Presets/Delete=Delete"), enabled = LrView.bind { key = "selectedPreset", transform = function(v) return v ~= "" end }, action = function()
                                        if props.selectedPreset ~= "" then
                                            local result = LrDialogs.confirm(
                                                LOC("$$$/MaskBridge/Dashboard/Presets/DeleteConfirmTitle=Delete Preset?"),
                                                LOC("$$$/MaskBridge/Dashboard/Presets/DeleteConfirmMsg=Are you sure you want to delete preset '^1'?",
                                                    props.selectedPreset)
                                            )
                                            if result == "ok" then
                                                deletePreset(props.selectedPreset)
                                                props.selectedPreset = ""
                                                LrDialogs.showBezel(
                                                    LOC("$$$/MaskBridge/Dashboard/Presets/Deleted=Preset deleted"), 2)
                                            end
                                        end
                                    end },
                                },
                                f:row {
                                    fill_horizontal = 1,
                                    f:static_text { title = LOC("$$$/MaskBridge/Dashboard/Presets/NewName=Name:") },
                                    dashboardTextField("newPresetName", LOC("$$$/MaskBridge/Dashboard/Presets/NewName=Name:"), { fill_horizontal = 1, placeholder_string = LOC("$$$/MaskBridge/Dashboard/Presets/NamePlaceholder=New preset...") }),
                                    f:push_button { title = LOC("$$$/MaskBridge/Dashboard/Presets/Save=Save"), action = function()
                                        local name = props.newPresetName
                                        if name and name ~= "" then
                                            savePreset(name, props)
                                            props.newPresetName = ""
                                            windowsPresetDraft = ""
                                            props.selectedPreset = name
                                            LrDialogs.showBezel(
                                                LOC("$$$/MaskBridge/Dashboard/Presets/Saved=Preset saved: ^1", name), 2)
                                        else
                                            LrDialogs.showError(LOC("$$$/MaskBridge/Dashboard/Presets/NameRequired=Enter a name"))
                                        end
                                    end },
                                },

                                f:separator { fill_horizontal = 1 },

                                -- Custom classes & Exclude classes
                                f:static_text { title = LOC("$$$/MaskBridge/Dashboard/Advanced/CustomClasses=Additional classes:"), font = "<system>" },
                                f:row {
                                    fill_horizontal = 1,
                                    dashboardTextField("customClasses", LOC("$$$/MaskBridge/Dashboard/Advanced/CustomClasses=Additional classes:"), { fill_horizontal = 1, height_in_lines = 1, placeholder_string = "dog, bottle, chair..." }),
                                    f:push_button {
                                        title = LOC("$$$/MaskBridge/Dashboard/Advanced/ViewClassesShort=Classes ↗"),
                                        action = function()
                                            local lang = LOC("$$$/MaskBridge/LangCode=en")
                                            local docPath = LrPathUtils.child(getPluginPath(), "docs/DETECTION_CLASSES_" .. lang .. ".md")
                                            if not LrFileUtils.exists(docPath) then
                                                docPath = LrPathUtils.child(getPluginPath(), "docs/DETECTION_CLASSES_en.md")
                                            end
                                            if LrFileUtils.exists(docPath) then
                                                LrHttp.openUrlInBrowser("file://" .. docPath)
                                            else
                                                LrDialogs.showError(LOC("$$$/MaskBridge/Dashboard/Advanced/DocNotFound=Documentation not found: ^1", docPath))
                                            end
                                        end,
                                    },
                                },
                                f:static_text { title = LOC("$$$/MaskBridge/Dashboard/Advanced/ExcludeClasses=Exclude classes:"), font = "<system>" },
                                dashboardTextField("excludeClasses", LOC("$$$/MaskBridge/Dashboard/Advanced/ExcludeClasses=Exclude classes:"), { fill_horizontal = 1, height_in_lines = 1, placeholder_string = "bench, chair..." }),

                                f:separator { fill_horizontal = 1 },

                                -- Secondary options
                                f:checkbox {
                                    title = LOC("$$$/MaskBridge/Dashboard/Advanced/EnableSounds=Play sound on completion"),
                                    value = LrView.bind("enableSounds"),
                                },
                            }
                        },

                    }
                },

                -- RIGHT: Streamlined Action Buttons Sidebar
                f:column {
                    spacing = 8,
                    width = 180,
                    fill_vertical = 1,

                    -- Primary Action: Generate Masks
                    f:push_button {
                        title = LrView.bind { key = "photoCount", transform = function(v)
                            if v == 0 then
                                return LOC("$$$/MaskBridge/Dashboard/Action/NoPhotos=No photos selected")
                            elseif v == 1 then
                                return LOC("$$$/MaskBridge/Dashboard/Action/Generate1=Generate 1 mask")
                            else
                                return LOC("$$$/MaskBridge/Dashboard/Action/GenerateN=Generate ^1 masks", v)
                            end
                        end },
                        font = "<system/bold>",
                        fill_horizontal = 1,
                        enabled = LrView.bind { keys = { "photoCount", "serverRunning" }, operation = function()
                            return props.photoCount > 0 and props.serverRunning == true
                        end },
                        action = function() startGeneration() end
                    },

                    -- Secondary Action: Preview Mask
                    f:push_button {
                        title = LOC("$$$/MaskBridge/Dashboard/Action/Preview=Preview Mask"),
                        fill_horizontal = 1,
                        enabled = LrView.bind { keys = { "photoCount" }, operation = function()
                            return props.photoCount > 0
                        end },
                        action = function() runPreview(props, catalog) end
                    },

                    -- Tertiary Action: Lightroom Mask Bridge
                    f:push_button {
                        title = LOC("$$$/MaskBridge/Dashboard/Action/MatteClear=Lightroom masks (Matte)"),
                        tooltip = LOC("$$$/MaskBridge/Matte/Fidelity=Estimated binary silhouettes. Gradients and soft opacity are not preserved. A recovery snapshot is created before export."),
                        fill_horizontal = 1,
                        enabled = LrView.bind { keys = { "photoCount" }, operation = function()
                            return props.photoCount > 0
                        end },
                        action = function() startMatteExport() end
                    },

                    -- Mask Bridge is free: one discreet way to support it.
                    f:separator { fill_horizontal = 1 },
                    f:push_button {
                        title = LOC("$$$/MaskBridge/Dashboard/SupportProject=Support Mask Bridge"),
                        font = "<system/small>",
                        fill_horizontal = 1,
                        action = function()
                            LrHttp.openUrlInBrowser(MaskBridgeConfig.SUPPORT_URL)
                        end,
                    },

                    -- Server Maintenance Controls (Discreet section)
                    f:separator { fill_horizontal = 1 },
                    f:static_text {
                        title = LOC("$$$/MaskBridge/Dashboard/ServerControl/Title=AI Controls:"),
                        font = "<system>",
                        text_color = LrColor(0.35, 0.35, 0.35),
                    },
                    f:row {
                        fill_horizontal = 1,
                        f:push_button {
                            title = LOC("$$$/MaskBridge/Dashboard/Action/ReloadShort=Reload"),
                            font = "<system>",
                            fill_horizontal = 1,
                            action = function()
                                MaskBridgeUtils.startOperation("reload", function()
                                    logMsg("Reload AI requested")
                                    props.serverRunning = false
                                    props.serverStatus = LOC("$$$/MaskBridge/Dashboard/ServerStatus/Restarting=AI Restarting...")
                                    stopServer()
                                    local startupDone = false
                                    LrTasks.startAsyncTask(function()
                                        local elapsed = 0
                                        while not startupDone and props._dialogOpen do
                                            LrTasks.sleep(1)
                                            elapsed = elapsed + 1
                                            if not startupDone then
                                                props.serverStatus = LOC("$$$/MaskBridge/Dashboard/ServerStatus/RestartingElapsed=AI Restarting... (^1s)", elapsed)
                                            end
                                        end
                                    end)
                                    startServer()
                                    startupDone = true
                                    if MaskBridgeUtils.isEngineReady() then
                                        props.serverRunning = true
                                        props.serverStatus = LOC("$$$/MaskBridge/Dashboard/ServerStatus/Ready=AI Ready")
                                        LrDialogs.showBezel(LOC("$$$/MaskBridge/Dashboard/Action/ReloadConfirm=AI server reloaded successfully."), 3)
                                    else
                                        props.serverStatus = LOC("$$$/MaskBridge/Dashboard/ServerStatus/Offline=AI Offline")
                                    end
                                end)
                            end
                        },
                        f:push_button {
                            title = LOC("$$$/MaskBridge/Dashboard/Action/ShutdownShort=Stop"),
                            font = "<system>",
                            fill_horizontal = 1,
                            action = function()
                                MaskBridgeUtils.startOperation("stop", function()
                                    logMsg("Shutdown AI requested")
                                    props.serverRunning = false
                                    props.serverStatus = LOC("$$$/MaskBridge/Dashboard/ServerStatus/Offline=AI Offline")
                                    stopServer()
                                    LrDialogs.showBezel(LOC("$$$/MaskBridge/Dashboard/ServerStatus/Stopped=AI server stopped."), 3)
                                end)
                            end
                        },
                    },

                    f:separator { fill_horizontal = 1 },

                    -- Close Button (placed directly with sidebar controls so it is always visible)
                    f:push_button {
                        title = LOC("$$$/MaskBridge/Common/Close=Close"),
                        fill_horizontal = 1,
                        action = function()
                            if props.closeDialog then
                                props.closeDialog()
                            end
                        end
                    },

                    f:spacer { fill_vertical = 1 },
                },
            },

            f:spacer { height = 4 },

            -- Footer: copyright + contact + version
            f:row {
                fill_horizontal = 1,
                f:static_text {
                    title = "© 2026 Nicolas Diolez",
                    font = "<system/small>",
                    text_color = LrColor(0.5, 0.5, 0.5),
                },
                f:spacer { fill_horizontal = 1 },
                f:push_button {
                    title = LOC("$$$/MaskBridge/Dashboard/Footer/Contact=Contact"),
                    font = "<system/small>",
                    action = function()
                        LrHttp.openUrlInBrowser(MaskBridgeConfig.CONTACT_URL)
                    end,
                },
                f:spacer { fill_horizontal = 1 },
                f:static_text {
                        title = "v" .. MaskBridgeConfig.VERSION,
                    font = "<system/small>",
                    text_color = LrColor(0.5, 0.5, 0.5),
                },
            },
        }

        -- First-launch welcome message (only once, with "don't show again").
        -- WINDOWS: shown BEFORE the floating dashboard (call below) — the
        -- dashboard is a topmost floating window there, so a modal presented
        -- from onShow appeared *behind* it and was easy to miss.
        -- macOS: shown from onShow (its original timing) so the mac behaviour
        -- stays byte-for-byte unchanged.
        local function showWelcomeIfNeeded()
            if prefs.hasSeenWelcome then return end
            LrFunctionContext.callWithContext("WelcomeDialog", function(context)
                local welcomeProps = LrBinding.makePropertyTable(context)
                welcomeProps.dontShowAgain = false

                local result = LrDialogs.presentModalDialog({
                    title = LOC("$$$/MaskBridge/Welcome/Title=Welcome to Mask Bridge!"),
                    contents = f:column {
                        spacing = 10,
                        f:static_text {
                            title = LOC("$$$/MaskBridge/Welcome/Intro=Welcome to Mask Bridge!"),
                            font = "<system/bold>",
                        },
                        f:static_text {
                            title = LOC("$$$/MaskBridge/Welcome/Tips=Mask Bridge offers two powerful tools:") .. "\n\n\226\150\160 AI Mask \226\128\148 " .. LOC("$$$/MaskBridge/Welcome/TipsAI=Automatically detects objects in your photos using AI and generates mask files (grayscale or transparent PNG).") .. "\n\n\226\150\160 Lightroom Mask Export \226\128\148 " .. LOC("$$$/MaskBridge/Welcome/TipsMatte=Export existing Lightroom masks or create new ones on the fly, as image files (grayscale or transparent PNG).") .. "\n\n" .. LOC("$$$/MaskBridge/Welcome/TipsCTA=Choose your mode, select your objects, and export!"),
                            height_in_lines = 10,
                            width_in_chars = 50,
                        },
                        f:separator { fill_horizontal = 1 },
                        f:checkbox {
                            title = LOC("$$$/MaskBridge/Welcome/DontShow=Don't show this message again"),
                            value = LrView.bind { bind_to_object = welcomeProps, key = "dontShowAgain" },
                        },
                    },
                    actionVerb = LOC("$$$/MaskBridge/Welcome/GetStarted=Get Started"),
                })

                if result == "ok" or welcomeProps.dontShowAgain then
                    prefs.hasSeenWelcome = true
                end
            end)
        end

        -- Windows: show it now, before the topmost dashboard opens.
        if MaskBridgeUtils.isWindows() then
            showWelcomeIfNeeded()
        end

        -- Token identifying this dashboard for the single-dashboard guard.
        -- Set in onShow (when toFront is available), cleared in windowWillClose.
        local dashboardToken

        props.dialogRef = LrDialogs.presentFloatingDialog(_PLUGIN, {
            title = "Mask Bridge",
            contents = contents,
            save_frame = layout.frameKey, -- distinct compact/normal geometry, no stale v11 frame

            -- Native SDK callback: triggered when photo selection changes
            -- This replaces the manual polling task and detects ALL selection changes
            selectionChangeObserver = function()
                local newPhotos = getSelectedPhotos(catalog)
                props.photoCount = #newPhotos
                logMsg("Selection changed: " .. props.photoCount .. " photos")
                -- macOS keeps the original behaviour: bring the dashboard to
                -- front on selection change. On Windows this made it cover
                -- whatever the user had just opened (e.g. File > Export) — the
                -- floating dialog is already a topmost window there — so skip it.
                if not MaskBridgeUtils.isWindows() and props.toFront then
                    props.toFront()
                end
            end,

            -- Native SDK callback: triggered when source (folder/collection) changes
            sourceChangeObserver = function()
                local newPhotos = getSelectedPhotos(catalog)
                props.photoCount = #newPhotos
                logMsg("Source changed: " .. props.photoCount .. " photos")
            end,

            onShow = function(dialogFunctions)
                -- dialogFunctions is a table with 'toFront' and 'close' functions
                props.toFront = dialogFunctions.toFront
                props.closeDialog = dialogFunctions.close

                -- Register as THE live dashboard (single-dashboard guard): a
                -- repeat menu launch closes this one and opens a fresh, frontmost
                -- dashboard (toFront can't restore a minimized window). We store
                -- the close fn for that. Cleared by token in windowWillClose.
                dashboardToken = MaskBridgeUtils.registerDashboard(dialogFunctions.close)

                -- Windows: once the engine is up, keep this window above
                -- Lightroom only instead of above every application. The
                -- dashboard is re-created after each export, so this runs on
                -- every show.
                if MaskBridgeUtils.isWindows() then
                    LrTasks.startAsyncTask(function()
                        -- Only the engine is needed, not the rest of the
                        -- startup task below.
                        while props._dialogOpen and not props._serverStartupDone
                                and not MaskBridgeUtils.isServerRunning() do
                            LrTasks.sleep(0.5)
                        end
                        MaskBridgeUtils.attachDashboardWindow(function() return props._dialogOpen end, logMsg)
                    end)
                end

                -- macOS: show the welcome here (original timing) so the mac
                -- behaviour is unchanged. Windows already showed it above,
                -- before the dashboard, to avoid it being hidden behind.
                if not MaskBridgeUtils.isWindows() then
                    showWelcomeIfNeeded()
                end

                -- Start server in background for fast processing
                LrTasks.startAsyncTask(function()
                    if checkModelsInstalled() and not isServerRunning() then
                        props.serverStatus = LOC("$$$/MaskBridge/Dashboard/ServerStatus/Starting=AI Starting...")
                        -- Show elapsed time during startup so user knows it's working
                        local startupDone = false
                        LrTasks.startAsyncTask(function()
                            local elapsed = 0
                            while not startupDone and props._dialogOpen do
                                LrTasks.sleep(1)
                                elapsed = elapsed + 1
                                if not startupDone then
                                    props.serverStatus = LOC("$$$/MaskBridge/Dashboard/ServerStatus/StartingElapsed=AI Starting... (^1s)", elapsed)
                                end
                            end
                        end)
                        startServer()
                        -- startServer() may return early if another startup is in progress (Init).
                        -- Keep waiting until the server is actually reachable.
                        for i = 1, 180 do
                            if isServerRunning() then break end
                            LrTasks.sleep(0.5)
                        end
                        startupDone = true
                    end
                    -- Update status immediately after server start attempt
                    if MaskBridgeUtils.isEngineReady() then
                        props.serverRunning = true
                        props.serverStatus = LOC("$$$/MaskBridge/Dashboard/ServerStatus/Ready=AI Ready")
                    end
                    -- Signal that startup attempt is done (unblocks polling loop)
                    props._serverStartupDone = true
                end)

                -- Unified server status polling (single loop, pcall-protected)
                -- Replaces two separate polling loops that caused concurrent crashes
                LrTasks.startAsyncTask(function()
                    -- Wait for onShow server startup to complete before polling
                    while props._dialogOpen and not props._serverStartupDone do
                        LrTasks.sleep(1)
                    end
                    -- Main polling loop with pcall protection. A single failed
                    -- health check is debounced (Windows health checks can miss
                    -- transiently), so the indicator never flickers to orange
                    -- while the server is actually up and serving requests.
                    local fails = 0
                    while props._dialogOpen do
                        local ok, running = LrTasks.pcall(MaskBridgeUtils.isEngineReady)
                        if ok then
                            if running then
                                fails = 0
                                if props.serverRunning ~= true then
                                    props.serverRunning = true
                                    props.serverStatus = LOC("$$$/MaskBridge/Dashboard/ServerStatus/Ready=AI Ready")
                                end
                            else
                                fails = fails + 1
                                if fails >= 2 and props.serverRunning ~= false then
                                    props.serverRunning = false
                                    if props._serverStartupDone then
                                        props.serverStatus = LOC("$$$/MaskBridge/Dashboard/ServerStatus/Offline=AI Offline")
                                    end
                                end
                            end
                        end
                        LrTasks.sleep(3)
                    end
                end)
            end,

            windowWillClose = function()
                logMsg("Dashboard closing...")
                -- Release the single-dashboard slot (only if still ours — a
                -- newer dashboard from close/reopen may have taken over).
                if dashboardToken then MaskBridgeUtils.clearDashboard(dashboardToken) end
                props._dialogOpen = false -- Stop polling loop
                saveSettings(props)
                -- We no longer stop the server here.
                -- It will stay alive for fast re-opens and auto-shutdown
                -- via Python watchdog when Lightroom closes.
            end
        })
    end)
end

-- Single-dashboard guard: both menu items (Library + File > Export) run this
-- file, and it re-runs on every click. Ensure exactly one dashboard, always
-- visible and frontmost: if one already exists (possibly minimized or behind
-- other windows), close it first — the SDK's toFront cannot reliably restore a
-- minimized floating dialog — then open a fresh one. save_frame restores it to
-- its last position. (Cross-platform: applies on macOS and Windows.)
if MaskBridgeUtils.isDashboardOpen() then
    MaskBridgeUtils.closeDashboard()
end
showDashboard()
