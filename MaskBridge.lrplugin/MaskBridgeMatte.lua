-- Mask Bridge — Matte Export Module
-- Exports native Lightroom masks as grayscale PNG (matte) files.
--
-- Workflow:
--   1. Save original develop settings
--   2. Switch to Develop, open masking
--   3. createNewMask("aiSelection", subtype) → auto-select
--   4. Push globals to black (Exposure=-5, etc.)
--   5. Push local mask to white (local_Exposure=4, etc.)
--   6. Export JPEG render → black bg / white mask
--   7. Cleanup: delete temp mask, restore settings
--   8. Python process_matte_to_alpha → grayscale PNG
--
-- Requires: Develop module, LrDevelopController, LrExportSession

local LrApplication       = import 'LrApplication'
local LrTasks             = import 'LrTasks'
local LrPathUtils         = import 'LrPathUtils'
local LrFileUtils         = import 'LrFileUtils'
local LrDevelopController = import 'LrDevelopController'
local LrApplicationView   = import 'LrApplicationView'
local LrExportSession     = import 'LrExportSession'
local LrDialogs           = import 'LrDialogs'
local LrProgressScope     = import 'LrProgressScope'
local LrDate              = import 'LrDate'

local MaskBridgeUtils       = require 'MaskBridgeUtils'
local json                  = dofile(LrPathUtils.child(_PLUGIN.path, "dkjson.lua"))

local MaskBridgeMatte       = {}

-- ============================================================================
-- Logging
-- ============================================================================

local logPath             = MaskBridgeUtils.getLogPath("matte_export.log")

local function log(msg)
    local f = io.open(logPath, "a")
    if f then
        f:write(os.date("%H:%M:%S") .. " | MATTE: " .. tostring(msg) .. "\n")
        f:close()
    end
end

local function logSection(title)
    log("")
    log("── " .. title .. " ──")
end

-- Current size of the matte log in bytes (0 if absent). Pure Lua io.
local function logFileSize()
    local f = io.open(logPath, "r")
    if not f then return 0 end
    local size = f:seek("end") or 0
    f:close()
    return size
end

-- Start a new export entry in the log. APPENDS (so a batch keeps every photo's
-- trace and per-photo failures stay visible) instead of truncating per call;
-- truncates once only when the log passes ~1 MB so it can't grow without bound.
-- Debug-only: no effect on the export itself.
local function writeLogHeader(title)
    local mode = (logFileSize() > 1024 * 1024) and "w" or "a"
    local f = io.open(logPath, mode)
    if f then
        f:write("\n=== " .. title .. " ===\n" .. os.date() .. "\n\n")
        f:close()
    end
end

-- Switch to Develop only when not already there — avoids a fixed ~2s no-op
-- on every export (and, in batch, on every photo since we stay in Develop).
-- Note: switchToModule when already in Develop does NOT reload the photo
-- (setSelectedPhotos does), so skipping it is safe for batch mask creation.
local function ensureDevelopModule()
    if LrApplicationView.getCurrentModuleName() ~= "develop" then
        LrApplicationView.switchToModule("develop")
        LrTasks.sleep(1.5)
        log("Switched to Develop module")
    else
        log("Already in Develop module (switch skipped)")
    end
end

-- ============================================================================
-- Global settings for matte render (push everything to black)
-- ============================================================================

local BLACK_GLOBALS = {
    Exposure2012   = -5,
    Contrast2012   = -100,
    Highlights2012 = -100,
    Shadows2012    = -100,
    Whites2012     = -100,
    Blacks2012     = -100,
    Clarity2012    = -100,
    Vibrance       = -100,
    Saturation     = -100,
    Dehaze         = -100,
    Texture        = -100,
}

-- Softer globals for enhanced two-pass mode: keeps dark pixels above zero
-- so the difference between passes is detectable even in shadows
local BLACK_GLOBALS_ENHANCED = {
    Exposure2012   = -2,
    Contrast2012   = -100,
    Highlights2012 = -100,
    Shadows2012    = 0,
    Whites2012     = -100,
    Blacks2012     = 0,
    Clarity2012    = -100,
    Vibrance       = -100,
    Saturation     = -100,
    Dehaze         = -100,
    Texture        = -100,
}

-- Local parameters to push mask area to white
-- These are the local_* parameter names for setValue()
local WHITE_LOCAL_PARAMS = {
    { param = "local_Exposure",   value = 4 },
    { param = "local_Contrast",   value = 100 },
    { param = "local_Highlights", value = 100 },
    { param = "local_Shadows",    value = 100 },
    { param = "local_Whites",     value = 100 },
    { param = "local_Blacks",     value = 100 },
    { param = "local_Clarity",    value = 100 },
}

-- ============================================================================
-- Internal helpers
-- ============================================================================

-- Lightroom shares snapshots between a master and its virtual copies. Use
-- the catalog-unique photo identifier, never the filename or editable copy
-- name, so one view cannot replace another view's recovery settings.
local function recoverySnapshotName(photo)
    local id = photo.localIdentifier
    if type(id) ~= "number" or id <= 0 or id ~= math.floor(id) or id == math.huge then
        error("Cannot identify photo for recovery snapshot; no matte settings were applied")
    end
    return "Mask Bridge - Before export [" .. string.format("%.0f", id) .. "]"
end

local function createRecoverySnapshot(photo)
    local name = recoverySnapshotName(photo)
    local created = photo:createDevelopSnapshot(name, true)
    if created then log("Recovery snapshot: " .. name) end
    return created
end

-- Save current develop settings as a snapshot for safe restoration
local function saveCurrentState(photo)
    local settings = photo:getDevelopSettings()
    log("Saved develop state (" .. (settings and "OK" or "nil") .. ")")
    return settings
end

-- Restore develop settings using applyDevelopSettings (works for globals)
local function restoreState(photo, savedSettings, catalog)
    if not savedSettings then
        log("WARNING: no saved settings to restore")
        return
    end
    local executed = false
    local status = catalog:withWriteAccessDo("Matte restore", function()
        photo:applyDevelopSettings(savedSettings, "MaskBridge Matte Restore")
        executed = true
    end, { timeout = 30 })
    if status ~= "executed" or not executed then
        error("Could not restore Lightroom settings. Use the '" .. recoverySnapshotName(photo) .. "' snapshot before continuing.")
    end
    LrTasks.sleep(0.2)
    log("Develop settings restored")
end

-- Push global parameters to extreme black via applyDevelopSettings
-- When enhanced=true, uses softer settings to preserve dark pixel differences
local function pushGlobalsToBlack(photo, catalog, enhanced)
    local globals = enhanced and BLACK_GLOBALS_ENHANCED or BLACK_GLOBALS
    logSection("Push globals to black" .. (enhanced and " (enhanced)" or ""))
    local status = catalog:withWriteAccessDo("Matte black globals", function()
        photo:applyDevelopSettings(globals, "MaskBridge Matte Black")
    end, { timeout = 10 })
    if status ~= "executed" then error("Catalogue busy: no matte settings applied") end
    LrTasks.sleep(0.5)

    -- Verify
    local s = photo:getDevelopSettings()
    log("Verify: Exposure2012=" .. tostring(s.Exposure2012)
        .. " Blacks2012=" .. tostring(s.Blacks2012)
        .. " Saturation=" .. tostring(s.Saturation))
end

-- Safely delete a temp mask created during matte export.
-- Uses mask ID comparison (not position) to find the new mask.
-- Called after restoring globals; failure must prevent a contaminated RGB export.
local function deleteTempMask(maskIDsBefore, photo)
    -- NOTE: LrTasks.sleep() yields, and yielding across a pcall boundary throws
    -- "Yielding is not allowed within a C or metamethod call" (Lua 5.1). So we
    -- find + delete inside pcall, but keep the sleep OUTSIDE it.
    local idToDelete = nil
    local okFind = pcall(function()
        local masksNow = LrDevelopController.getAllMasks()
        if masksNow then
            for _, m in ipairs(masksNow) do
                if not maskIDsBefore[m.ID] then
                    idToDelete = m.ID
                    break
                end
            end
        end
    end)
    if not okFind then
        error("Cannot inspect temporary mask cleanup. Use the '" .. recoverySnapshotName(photo) .. "' snapshot.")
    end
    if idToDelete then
        local okDel = pcall(function() LrDevelopController.deleteMask(idToDelete) end)
        LrTasks.sleep(0.3)
        if not okDel then
            error("Cannot remove temporary mask. Use the '" .. recoverySnapshotName(photo) .. "' snapshot.")
        end
        for _, mask in ipairs(LrDevelopController.getAllMasks() or {}) do
            if mask.ID == idToDelete then
                error("Temporary mask still present. Use the '" .. recoverySnapshotName(photo) .. "' snapshot.")
            end
        end
        log("Deleted temp mask: " .. tostring(idToDelete))
    end
end

-- Push local mask adjustments to white via startTracking/setValue/stopTracking
local function assertTarget(photo, maskID)
    if LrApplication.activeCatalog():getTargetPhoto() ~= photo then
        error("The selected photo changed during export. Export stopped safely.")
    end
    if maskID and LrDevelopController.getSelectedMask() ~= maskID then
        error("The selected mask changed during export. Export stopped safely.")
    end
end

local function pushLocalToWhite(photo)
    local maskID = LrDevelopController.getSelectedMask()
    assertTarget(photo, maskID)
    for _, entry in ipairs(WHITE_LOCAL_PARAMS) do
        local ok, err = LrTasks.pcall(function()
            assertTarget(photo, maskID)
            LrDevelopController.startTracking(entry.param)
            LrTasks.sleep(0.1)
            assertTarget(photo, maskID)
            LrDevelopController.setValue(entry.param, entry.value)
            LrTasks.sleep(0.1)
        end)
        local stopped, stopError = LrTasks.pcall(LrDevelopController.stopTracking)
        if not ok then error(err) end
        if not stopped then error(stopError) end
        LrTasks.sleep(0.2)
        assertTarget(photo, maskID)
    end
end

local function applyLongEdge(exportSettings, resolution)
    if resolution and resolution > 0 then
        exportSettings.LR_size_doConstrain = true
        exportSettings.LR_size_maxHeight   = resolution
        exportSettings.LR_size_maxWidth    = resolution
        exportSettings.LR_size_resizeType  = "longEdge"
    else
        exportSettings.LR_size_doConstrain = false
    end
    return exportSettings
end

-- Render settings of the black/white matte (and its reference): 16-bit TIFF
local function matteRenderSettings(tempDir, resolution)
    return applyLongEdge({
        LR_export_destinationType       = "specificFolder",
        LR_export_destinationPathPrefix = tempDir,
        LR_export_useSubfolder          = false,
        am_internalRender              = true,
        LR_format                       = "TIFF",
        LR_tiff_bitDepth                = 16,
        LR_tiff_compressionMethod       = "compressionMethod_None",
        LR_jpeg_quality                 = 0.95,
        LR_outputSharpeningOn           = false,
        LR_export_colorSpace            = "sRGB",
    }, resolution)
end

-- Render settings of the clean (unmodified) image in the user's format
local function cleanRenderSettings(tempDir, options)
    local format = options.exportFormat or "JPEG"
    local exportSettings = {
        LR_export_destinationType       = "specificFolder",
        LR_export_destinationPathPrefix = tempDir,
        LR_export_useSubfolder          = false,
        am_internalRender              = true,
        LR_collisionHandling            = "rename",
        LR_format                       = format,
        LR_outputSharpeningOn           = false,
        LR_export_colorSpace            = "sRGB",
    }
    if format == "JPEG" then
        exportSettings.LR_jpeg_quality = (options.jpegQuality or 90) / 100
    elseif format == "TIFF" then
        MaskBridgeUtils.applyTiffSettings(exportSettings, options.tiffBitDepth or 16,
            options.tiffCompression or "LZW")
    end
    return applyLongEdge(exportSettings, options.resolution or 2048)
end

-- Export a single photo to a temp directory as JPEG
local function exportToTemp(photo, tempDir, resolution)
    local exportSettings = matteRenderSettings(tempDir, resolution)

    -- Prevent ExportProvider from also processing. Yield-safe pcall +
    -- guaranteed reset: a failed export must never leave the flag stuck
    -- (it would silently disable File > Export AI processing).
    MaskBridgeUtils.setDashboardMode(true)

    local renderedPath = nil
    local ok, err = LrTasks.pcall(function()
        local session = LrExportSession({
            photosToExport = { photo },
            exportSettings = exportSettings,
        })

        session:doExportOnCurrentTask()

        for _, rendition in session:renditions() do
            local success, path = rendition:waitForRender()
            if success then
                renderedPath = path
            end
        end
    end)

    MaskBridgeUtils.setDashboardMode(false)
    if not ok then
        log("WARNING: matte render export failed: " .. tostring(err))
    end

    return renderedPath
end

-- Export a clean (unmodified) image of the photo to a temp directory
local function exportCleanImage(photo, tempDir, options)
    local exportSettings = cleanRenderSettings(tempDir, options)

    -- Same flag discipline as exportToTemp: pcall + guaranteed reset
    MaskBridgeUtils.setDashboardMode(true)

    local renderedPath = nil
    local ok, err = LrTasks.pcall(function()
        local session = LrExportSession({
            photosToExport = { photo },
            exportSettings = exportSettings,
        })

        session:doExportOnCurrentTask()

        for _, rendition in session:renditions() do
            local success, path = rendition:waitForRender()
            if success then
                renderedPath = path
            end
        end
    end)

    MaskBridgeUtils.setDashboardMode(false)
    if not ok then
        log("WARNING: clean image export failed: " .. tostring(err))
    end
    return renderedPath
end

local function convertMatteToPNG(inputPath, outputPath, invert, referencePath)
    -- Try the HTTP server first: the CLI path pays a PyInstaller cold start
    -- (~1-3s) PER PHOTO, which dominated matte batches. Same server-first /
    -- CLI-fallback pattern as mergeAlpha below.
    local port = MaskBridgeUtils.getServerPort()
    if port then
        local jsonData = json.encode({
            input = inputPath,
            output = outputPath,
            invert = invert and true or false,
            reference = referencePath,
        })
        log("convertMatte POST /matte: " .. jsonData)
        local response = MaskBridgeUtils.httpPost("/matte", jsonData)
        log("convertMatte response: " .. tostring(response))
        local decoded = response and json.decode(response)
        if type(decoded) == "table" and decoded.status == "success" then
            return LrFileUtils.exists(outputPath) and true or false
        end
        log("convertMatte server failed; request will not be replayed")
        return false
    else
        log("convertMatte: no server port, going to CLI")
    end

    local backendCmd = MaskBridgeUtils.getBackendEngine()

    local cmd = string.format(
        '%s --mode matte --image %s --output %s',
        backendCmd,
        MaskBridgeUtils.shellEscape(MaskBridgeUtils.normalizePath(inputPath)),
        MaskBridgeUtils.shellEscape(MaskBridgeUtils.normalizePath(outputPath))
    )

    if invert then cmd = cmd .. " --invert" end
    if referencePath then
        cmd = cmd .. string.format(' --reference %s', MaskBridgeUtils.shellEscape(MaskBridgeUtils.normalizePath(referencePath)))
    end

    log("Python cmd: " .. cmd)
    local status = MaskBridgeUtils.executeCommand(cmd, nil)
    log("Python exit: " .. tostring(status))

    return status == 0 and LrFileUtils.exists(outputPath)
end

-- Merge RGB image + grayscale mask into a 32-bit RGBA PNG (transparent background)
-- Tries HTTP server first (production), falls back to CLI binary/python3 (dev)
local function mergeAlpha(rgbPath, maskPath, outputPath)
    log("mergeAlpha: rgb=" .. tostring(rgbPath) .. " mask=" .. tostring(maskPath) .. " out=" .. tostring(outputPath))

    -- Try HTTP server first (production path)
    local port = MaskBridgeUtils.getServerPort()
    if port then
        local jsonData = json.encode({
            rgb_path = rgbPath,
            mask_path = maskPath,
            output_path = outputPath,
        })
        log("mergeAlpha POST /merge-alpha: " .. jsonData)
        local response = MaskBridgeUtils.httpPost("/merge-alpha", jsonData)
        log("mergeAlpha response: " .. tostring(response))
        local decoded = response and json.decode(response)
        if type(decoded) == "table" and decoded.status == "success" then
            local exists = LrFileUtils.exists(outputPath)
            log("mergeAlpha server OK, file exists=" .. tostring(exists))
            return exists
        end
        log("mergeAlpha server failed; request will not be replayed")
        return false
    else
        log("mergeAlpha: no server port, going to CLI")
    end

    -- Fallback: CLI binary or python3
    local backendCmd = MaskBridgeUtils.getBackendEngine()
    if not backendCmd then
        log("mergeAlpha FAILED: getBackendEngine() returned nil")
        return false
    end
    local cmd = string.format(
        '%s --mode alpha --image %s --mask %s --output %s',
        backendCmd,
        MaskBridgeUtils.shellEscape(MaskBridgeUtils.normalizePath(rgbPath)),
        MaskBridgeUtils.shellEscape(MaskBridgeUtils.normalizePath(maskPath)),
        MaskBridgeUtils.shellEscape(MaskBridgeUtils.normalizePath(outputPath))
    )

    log("mergeAlpha CLI: " .. cmd)
    local status = MaskBridgeUtils.executeCommand(cmd, nil)
    log("mergeAlpha CLI exit: " .. tostring(status))

    return status == 0 and LrFileUtils.exists(outputPath)
end

-- Helper: perform the alpha export step (export clean PNG + merge with mask)
-- Called from exportMatte*, returns the alpha output path or nil
local function performAlphaExport(photo, maskPath, outputDir, stem, options, tempDir)
    logSection("Alpha Export: Export clean source as PNG")
    log("Alpha: maskPath=" .. tostring(maskPath) .. " outputDir=" .. tostring(outputDir) .. " stem=" .. tostring(stem))

    -- Force PNG for the clean source (no JPEG artifacts on transparent edges)
    local alphaOptions = {}
    for k, v in pairs(options) do alphaOptions[k] = v end
    alphaOptions.exportFormat = "PNG"

    local cleanPath = exportCleanImage(photo, tempDir, alphaOptions)
    if not cleanPath then
        log("Alpha FAILED: exportCleanImage returned nil (tempDir=" .. tostring(tempDir) .. ")")
        return nil
    end
    log("Alpha: cleanPath=" .. cleanPath)

    -- Verify source files exist before merge
    if not LrFileUtils.exists(cleanPath) then
        log("Alpha FAILED: cleanPath does not exist: " .. cleanPath)
        return nil
    end
    if not LrFileUtils.exists(maskPath) then
        log("Alpha FAILED: maskPath does not exist: " .. maskPath)
        return nil
    end

    -- Build alpha output path: stem_alpha.png
    local alphaOutputPath = MaskBridgeUtils.uniqueOutputPath(LrPathUtils.child(outputDir, stem .. "_alpha.png"))
    log("Alpha: output=" .. alphaOutputPath)

    logSection("Alpha Export: Merge RGB + mask → RGBA")
    local mergeOk = mergeAlpha(cleanPath, maskPath, alphaOutputPath)
    log("Alpha: mergeAlpha returned " .. tostring(mergeOk))

    -- Cleanup intermediate clean image
    if LrFileUtils.exists(cleanPath) then
        LrFileUtils.delete(cleanPath)
    end

    if mergeOk then
        log("Alpha OK: " .. alphaOutputPath)
        return alphaOutputPath
    else
        log("Alpha FAILED: merge returned false for " .. stem)
        return nil
    end
end

--- Publish a staged render without deleting any existing destination.
local function safeMoveOverwrite(src, dest)
    if LrFileUtils.exists(dest) then return false, "Destination already exists; it was preserved" end
    local destDir = LrPathUtils.parent(dest)
    if destDir and not LrFileUtils.exists(destDir) then LrFileUtils.createAllDirectories(destDir) end
    local ok, moved, message = LrTasks.pcall(LrFileUtils.move, src, dest)
    if not ok or not moved then return false, tostring(message or moved) end
    if not LrFileUtils.exists(dest) then return false, "Destination missing after move" end
    return true
end

--- Remove the per-export temp directories (best effort)
local function cleanupTempDirs(tempDir, tempDirRef)
    if tempDir and LrFileUtils.exists(tempDir) then LrFileUtils.delete(tempDir) end
    if tempDirRef and LrFileUtils.exists(tempDirRef) then LrFileUtils.delete(tempDirRef) end
end

-- ============================================================================
-- Shared matte pipeline
-- ============================================================================
-- The three per-photo export modes (New AI / Existing / All Combined) share
-- the same 10-step skeleton — save state, Develop, black globals, optional
-- reference render, white locals, render, restore, convert, clean image,
-- alpha — and differ ONLY in how the mask(s) get selected and boosted. They
-- used to be three near-identical copies (~500 lines) that had already
-- started to drift (divergent TIFF keys); this pipeline is the single copy.
--
-- hooks:
--   logTitle          string — writeLogHeader title
--   prepareTitle      string — Step 3 log section label
--   prepare(ctx)      -> ok[, errMsg[, status]]
--       Runs after goToMasking, BEFORE globals go black: create or select
--       the mask(s). `status` is passed through to the caller (e.g.
--       "no_detection" for a clean skip).
--   boost(ctx)        -> ok[, errMsg]
--       Runs after the reference render: push the mask local(s) to white.
--   afterRestore(ctx) optional — cleanup once settings are restored
--       (e.g. delete the temp AI mask).
--
-- ctx carries { photo, catalog, options, stem } for the hooks.
local function runMattePipeline(photo, outputDir, options, hooks)
    options = options or {}
    local catalog = LrApplication.activeCatalog()
    local stem = LrPathUtils.removeExtension(photo:getFormattedMetadata('fileName') or "unknown")
    local savedSettings, restored, ctx, cleanupAttempted
    local tempDir, tempDirRef
    local function restore()
        if savedSettings and not restored then
            restoreState(photo, savedSettings, catalog)
            restored = true
        end
    end
    local function cleanupMask()
        if not cleanupAttempted and ctx and hooks.afterRestore and catalog:getTargetPhoto() == photo then
            -- Do not repeat a deletion after an uncertain SDK response.
            cleanupAttempted = true
            hooks.afterRestore(ctx)
        end
    end
    local ok, success, result, status = LrTasks.pcall(function()
        writeLogHeader(hooks.logTitle)
        assertTarget(photo)
        if options.isCanceled and options.isCanceled() then return false, "Canceled", "canceled" end
        savedSettings = saveCurrentState(photo)
        if not savedSettings then error("Cannot save Lightroom settings") end
        local snapshotCreated = false
        local lockStatus = catalog:withWriteAccessDo("Mask Bridge recovery snapshot", function()
            snapshotCreated = createRecoverySnapshot(photo)
        end, { timeout = 10 })
        if lockStatus ~= "executed" or not snapshotCreated then
            error("Cannot create recovery snapshot; no matte settings were applied")
        end
        local base = LrPathUtils.getStandardFilePath('temp')
        local suffix = os.time() .. "_" .. math.random(1000000)
        tempDir = LrPathUtils.child(base, "maskbridge_matte_" .. suffix)
        LrFileUtils.createDirectory(tempDir)
        local enhanced = options.enhancedDetection or false
        if enhanced then
            tempDirRef = LrPathUtils.child(base, "maskbridge_matte_ref_" .. suffix)
            LrFileUtils.createDirectory(tempDirRef)
        end
        ensureDevelopModule()
        assertTarget(photo)
        LrDevelopController.goToMasking()
        LrTasks.sleep(0.5)
        assertTarget(photo)
        ctx = { photo = photo, catalog = catalog, options = options, stem = stem }
        local prepared, message, prepareStatus = hooks.prepare(ctx)
        if not prepared then return false, message, prepareStatus end
        assertTarget(photo)
        pushGlobalsToBlack(photo, catalog, enhanced)
        local reference
        if enhanced then
            reference = exportToTemp(photo, tempDirRef, options.resolution or 2048)
            if not reference then error("Reference render failed") end
        end
        assertTarget(photo)
        local boosted, boostError = hooks.boost(ctx)
        if not boosted then error(boostError or "Mask selection failed") end
        assertTarget(photo)
        local rendered = exportToTemp(photo, tempDir, options.resolution or 2048)
        if not rendered then error("Matte render failed") end
        restore()
        -- Applying the saved globals does not remove a newly created AI mask.
        -- Remove its white local adjustments before exporting any clean RGB.
        cleanupMask()
        if options.isCanceled and options.isCanceled() then return false, "Canceled", "canceled" end
        local output = options._outputPath or MaskBridgeUtils.uniqueOutputPath(
            MaskBridgeMatte._getMaskOutputPath(outputDir, stem, options.namingPattern or "standard"))
        if not convertMatteToPNG(rendered, output, options.invert, reference) then
            error("Matte conversion failed")
        end
        if not options.masksOnly then
            local clean = exportCleanImage(photo, tempDir, options)
            if not clean then error("Mask saved, but the requested image render failed") end
            local destination = MaskBridgeUtils.uniqueOutputPath(LrPathUtils.child(
                options.imageOutputDir or outputDir,
                MaskBridgeMatte._getImageFilename(stem, options, options._batchIndex)))
            local moved, moveError = safeMoveOverwrite(clean, destination)
            if not moved then error("Mask saved, but image export failed: " .. tostring(moveError)) end
        end
        if options.exportAlpha and not performAlphaExport(photo, output, outputDir, stem, options, tempDir) then
            error("Mask saved, but the requested alpha export failed")
        end
        return true, output, "ok"
    end)
    -- Finally: errors in tracking, hooks, rendering or conversion all pass here.
    LrTasks.pcall(LrDevelopController.stopTracking)
    local restoreOK, restoreError = LrTasks.pcall(restore)
    if restoreOK then
        local cleanupOK, cleanupError = LrTasks.pcall(cleanupMask)
        if not cleanupOK then ok, success = false, cleanupError end
    end
    LrTasks.pcall(function() cleanupTempDirs(tempDir, tempDirRef) end)
    if not restoreOK then return false, tostring(restoreError), "restore_failed" end
    if not ok then return false, tostring(success), "error" end
    return success, result, status
end

-- ============================================================================
-- Main export function — NEW AI mask
-- ============================================================================

--- Export a native Lightroom mask as a grayscale PNG file (creates new AI mask).
--- @param photo       LrPhoto  — the photo to export
--- @param maskSubtype string   — "subject", "sky", "background", "objects", "people", "landscape"
--- @param outputDir   string   — directory where the grayscale PNG will be written
--- @param options     table    — { resolution=2048, invert=false, namingPattern="standard" }
--- @return boolean, string, string — success, outputPath/message, status
---         status is "ok" on success, "no_detection" when the AI found no
---         matching subject (clean skip), or nil for a hard error.
function MaskBridgeMatte.exportMatte(photo, maskSubtype, outputDir, options)
    -- Snapshot of pre-existing mask IDs, filled by prepare, consumed by
    -- afterRestore to delete only the mask this export created.
    local maskIDsBefore = {}

    return runMattePipeline(photo, outputDir, options, {
        logTitle = "Matte Export (New AI)",
        prepareTitle = "Create mask",

        prepare = function(ctx)
            log("Mask type: aiSelection/" .. maskSubtype)

            local masksBefore = LrDevelopController.getAllMasks()
            local countBefore = masksBefore and #masksBefore or 0
            if masksBefore then
                for _, m in ipairs(masksBefore) do
                    maskIDsBefore[m.ID] = true
                end
            end
            log("Masks before: " .. countBefore)

            LrDevelopController.createNewMask("aiSelection", maskSubtype)

            -- Wait for AI computation. When Lightroom's AI finds nothing matching
            -- the subtype (e.g. "sky" on a photo with no sky) it creates NO new
            -- mask — so a timeout here almost always means "nothing detected",
            -- not a real failure. Poll a short window so subjectless photos fail
            -- fast and get skipped cleanly instead of stalling a whole batch.
            log("Waiting for AI mask computation...")
            local maskCreated = false
            local maxWaitSteps = 20 -- 20 × 0.25s = ~5 seconds
            for i = 1, maxWaitSteps do
                LrTasks.sleep(0.25)
                local masksAfter = LrDevelopController.getAllMasks()
                local countAfter = masksAfter and #masksAfter or 0
                if countAfter > countBefore then
                    maskCreated = true
                    log("Mask created after " .. (i * 0.25) .. "s (total: " .. countAfter .. ")")
                    break
                end
            end

            if not maskCreated then
                -- Clean "skip" (status "no_detection"), NOT an error, so the
                -- batch summary can say "no <subtype> detected".
                log("INFO: no '" .. maskSubtype .. "' detected (no mask created after "
                    .. (maxWaitSteps * 0.25) .. "s)")
                return false, "No " .. maskSubtype .. " detected", "no_detection"
            end

            -- The new mask is auto-selected (confirmed by v13a)
            log("Selected mask: " .. tostring(LrDevelopController.getSelectedMask()))
            return true
        end,

        boost = function(ctx)
            pushLocalToWhite(ctx.photo)
            -- Verify persistence
            local settings = ctx.photo:getDevelopSettings()
            local masks = settings.MaskGroupBasedCorrections
            if masks and masks[#masks] then
                log("Verify: last mask LocalExposure2012=" .. tostring(masks[#masks].LocalExposure2012))
            end
            return true
        end,

        afterRestore = function(ctx)
            deleteTempMask(maskIDsBefore, photo)
        end,
    })
end

-- ============================================================================
-- Export function — EXISTING mask
-- ============================================================================

--- Export an existing Lightroom mask as a grayscale PNG file.
--- Uses selectMask(id) instead of createNewMask().
--- @param photo       LrPhoto  — the photo to export
--- @param maskID      string   — ID of the existing mask (from getAllMasks())
--- @param maskName    string   — name for logging
--- @param outputDir   string   — directory where the grayscale PNG will be written
--- @param options     table    — { resolution=2048, invert=false, namingPattern="standard" }
--- @return boolean, string     — success, outputPath or error message
function MaskBridgeMatte.exportMatteExisting(photo, maskID, maskName, outputDir, options)
    return runMattePipeline(photo, outputDir, options, {
        logTitle = "Matte Export (Existing Mask)",
        prepareTitle = "Select existing mask",

        prepare = function(ctx)
            log("Existing mask: " .. tostring(maskName) .. " (ID=" .. tostring(maskID) .. ")")

            -- selectMask(id) — single argument (confirmed v13b)
            LrDevelopController.selectMask(maskID)
            LrTasks.sleep(0.5)

            local selectedMask = LrDevelopController.getSelectedMask()
            log("Selected mask: " .. tostring(selectedMask))

            if selectedMask ~= maskID then
                log("ERROR: could not select mask " .. tostring(maskID))
                return false, "Could not select mask"
            end
            return true
        end,

        boost = function(ctx)
            pushLocalToWhite(ctx.photo)
            -- Verify persistence
            local settings = ctx.photo:getDevelopSettings()
            local masks = settings.MaskGroupBasedCorrections
            if masks then
                for i, m in ipairs(masks) do
                    if m.CorrectionID == maskID then
                        log("Verify: mask[" .. i .. "] LocalExposure2012=" .. tostring(m.LocalExposure2012))
                    end
                end
            end
            return true
        end,
    })
end

-- ============================================================================
-- Export function — ALL EXISTING masks COMBINED into one PNG
-- ============================================================================

--- Export all existing Lightroom masks combined as a single grayscale PNG.
--- Selects each mask, pushes its locals to white, then exports one render.
--- @param photo       LrPhoto  — the photo to export
--- @param masks       table    — array of { value=maskID, name=maskName } from getExistingMasks()
--- @param outputDir   string   — directory where the grayscale PNG will be written
--- @param options     table    — { resolution=2048, invert=false, namingPattern="standard" }
--- @return boolean, string     — success, outputPath or error message
function MaskBridgeMatte.exportMatteAllCombined(photo, masks, outputDir, options)
    if #masks == 0 then
        log("ERROR: no masks to combine")
        return false, "No masks found"
    end

    return runMattePipeline(photo, outputDir, options, {
        logTitle = "Matte Export (All Combined)",
        prepareTitle = "Open masking",

        prepare = function(ctx)
            log("Masks to combine: " .. #masks)
            return true
        end,

        boost = function(ctx)
            local boostedCount = 0
            for i, mask in ipairs(masks) do
                log("Selecting mask " ..
                    i .. "/" .. #masks .. ": " .. tostring(mask.name) .. " (ID=" .. tostring(mask.value) .. ")")
                LrDevelopController.selectMask(mask.value)
                LrTasks.sleep(0.5)

                local selectedMask = LrDevelopController.getSelectedMask()
                log("  Selected: " .. tostring(selectedMask))

                if selectedMask == mask.value then
                    pushLocalToWhite(ctx.photo)
                    boostedCount = boostedCount + 1
                    log("  Locals boosted for mask " .. i)
                else
                    log("  WARNING: could not select mask " .. tostring(mask.value))
                end
            end

            -- With zero boosted masks the render would be all black and the
            -- export would "succeed" with an empty PNG — fail explicitly instead
            if boostedCount ~= #masks then
                log("ERROR: could not select any of the " .. #masks .. " masks")
                return false, "Could not select any mask"
            end
            return true
        end,
    })
end
-- ============================================================================
-- Export function — ALL EXISTING masks INDIVIDUALLY (one PNG per mask)
-- ============================================================================

--- Export all existing Lightroom masks individually as separate grayscale PNGs.
--- Each mask gets its own file with the mask name in the filename.
--- @param photo       LrPhoto  — the photo to export
--- @param masks       table    — array of { value=maskID, name=maskName } from getExistingMasks()
--- @param outputDir   string   — directory where the grayscale PNGs will be written
--- @param options     table    — { resolution=2048, invert=false, namingPattern="standard" }
--- @return number, number      — successCount, failCount
function MaskBridgeMatte.exportMatteAllIndividual(photo, masks, outputDir, options)
    options = options or {}

    log("")
    log("=== Matte Export (All Individual) ===")
    log("Photo: " .. tostring(photo:getFormattedMetadata('fileName')))
    log("Masks to export: " .. #masks)

    local successCount = 0
    local failCount = 0
    local stem = LrPathUtils.removeExtension(photo:getFormattedMetadata('fileName') or "unknown")
    local namingPattern = options.namingPattern or "standard"

    -- Labels already used for this photo: two masks with the same (sanitized)
    -- name would otherwise overwrite each other's files
    local usedLabels = {}
    -- Successfully exported masks, kept for the per-mask alpha merges below
    local exportedMasks = {}

    for i, mask in ipairs(masks) do
        log("")
        log("── Individual mask " .. i .. "/" .. #masks .. ": " .. tostring(mask.name) .. " ──")

        local label = MaskBridgeUtils.sanitizeLabel(mask.name)
        if options.isCanceled and options.isCanceled() then break end
        local baseLabel, index = label, 1
        while usedLabels[label:lower()] do
            index = index + 1
            label = baseLabel .. "_" .. index
        end
        usedLabels[label:lower()] = true
        local labeledOutputPath = MaskBridgeUtils.uniqueOutputPath(MaskBridgeUtils.getMaskPathWithLabel(
            outputDir, stem, namingPattern, label))

        -- Per-mask run exports the mask only: the clean image and the alpha
        -- merges are handled once per photo after the loop. They were previously
        -- re-rendered for every mask, and every alpha overwrote the previous one
        -- on the same <stem>_alpha.png path.
        local maskOptions = {}
        for k, v in pairs(options) do maskOptions[k] = v end
        maskOptions._batchIndex = i
        maskOptions.masksOnly = true
        maskOptions.exportAlpha = false
        maskOptions._outputPath = labeledOutputPath

        local ok, result = MaskBridgeMatte.exportMatteExisting(
            photo, mask.value, mask.name, outputDir, maskOptions
        )

        if ok then
            successCount = successCount + 1
            table.insert(exportedMasks, { path = labeledOutputPath, label = label })
            log("✅ Mask " .. i .. " exported: " .. tostring(labeledOutputPath))
        else
            failCount = failCount + 1
            log("❌ Mask " .. i .. " failed: " .. tostring(result))
        end
    end

    -- Once per photo: clean source image and/or labeled alpha cutouts
    local imageFailed = false
    local alphaFailed = {}
    if #exportedMasks > 0 and (not options.masksOnly or options.exportAlpha) then
        local tempBase = LrPathUtils.getStandardFilePath('temp')
        local tempDir = LrPathUtils.child(tempBase,
            "maskbridge_matte_ind_" .. os.time() .. "_" .. math.random(10000))
        LrFileUtils.createDirectory(tempDir)

        if not options.masksOnly then
            logSection("All Individual: export clean source image (once)")
            local cleanPath = exportCleanImage(photo, tempDir, options)
            if cleanPath then
                local imgName = MaskBridgeMatte._getImageFilename(stem, options, options._batchIndex)
                local imgDir = options.imageOutputDir or outputDir
                local imgOutputPath = MaskBridgeUtils.uniqueOutputPath(LrPathUtils.child(imgDir, imgName))
                local moved, moveErr = safeMoveOverwrite(cleanPath, imgOutputPath)
                if moved then
                    log("Image exported: " .. imgOutputPath)
                else
                    imageFailed = true
                    log("WARNING: failed to export clean image to " .. imgOutputPath .. " (" .. tostring(moveErr) .. ")")
                end
            else
                imageFailed = true
                log("WARNING: clean image export failed")
            end
        end

        if options.exportAlpha then
            logSection("All Individual: alpha merge per mask (one clean render)")
            local alphaOptions = {}
            for k, v in pairs(options) do alphaOptions[k] = v end
            alphaOptions.exportFormat = "PNG"
            local cleanPath = exportCleanImage(photo, tempDir, alphaOptions)
            if cleanPath then
                for _, m in ipairs(exportedMasks) do
                    if options.isCanceled and options.isCanceled() then break end
                    local alphaOut = MaskBridgeUtils.uniqueOutputPath(LrPathUtils.child(outputDir, stem .. "_" .. m.label .. "_alpha.png"))
                    local okMerge = mergeAlpha(cleanPath, m.path, alphaOut)
                    if not okMerge then alphaFailed[m.path] = true end
                    log((okMerge and "Alpha OK: " or "Alpha FAILED: ") .. alphaOut)
                end
                if LrFileUtils.exists(cleanPath) then
                    LrFileUtils.delete(cleanPath)
                end
            else
                for _, m in ipairs(exportedMasks) do alphaFailed[m.path] = true end
                log("WARNING: alpha clean render failed — alphas skipped")
            end
        end

        LrFileUtils.delete(tempDir)
    end

    log("")
    for _, m in ipairs(exportedMasks) do
        if imageFailed or alphaFailed[m.path] then
            successCount = successCount - 1
            failCount = failCount + 1
        end
    end
    log(string.format("All Individual complete: %d/%d success, %d failed", successCount, #masks, failCount))
    return successCount, failCount
end

-- ============================================================================
-- Helpers & UI data
-- ============================================================================

--- Build mask output path using the shared naming convention from MaskBridgeUtils.
--- This ensures matte exports follow the same naming as RF-DETR exports.
function MaskBridgeMatte._getMaskOutputPath(outputDir, stem, namingPattern)
    return MaskBridgeUtils.getMaskPath(outputDir, stem, namingPattern)
end

--- Compute the image output filename based on the image naming pattern.
--- @param stem     string — original photo filename stem
--- @param options  table  — { imageNaming, imageNamingCustom, exportFormat }
--- @param index    number — batch index (for custom prefix numbering)
--- @return string         — filename with extension (no directory)
function MaskBridgeMatte._getImageFilename(stem, options, index)
    local format = options.exportFormat or "JPEG"
    local ext = ".jpg"
    if format == "TIFF" then
        ext = ".tif"
    elseif format == "PNG" then
        ext = ".png"
    end

    local naming = options.imageNaming or "original"

    if naming == "custom" then
        local prefix = MaskBridgeUtils.sanitizeLabel(options.imageNamingCustom or "image")
        if prefix == "" then prefix = "image" end
        return string.format("%s_%03d%s", prefix, index or 1, ext)
    elseif naming == "date" then
        return os.date("%Y%m%d_%H%M%S") .. ext
    end

    -- "original" (default)
    return stem .. ext
end

--- Get available AI mask types for the UI
function MaskBridgeMatte.getMaskTypes()
    return {
        { title = LOC("$$$/MaskBridge/Matte/MaskType/Subject=Subject"),       value = "subject" },
        { title = LOC("$$$/MaskBridge/Matte/MaskType/Sky=Sky"),               value = "sky" },
        { title = LOC("$$$/MaskBridge/Matte/MaskType/Background=Background"), value = "background" },
        { title = LOC("$$$/MaskBridge/Matte/MaskType/People=People"),         value = "people" },
        { title = LOC("$$$/MaskBridge/Matte/MaskType/Objects=Objects"),       value = "objects" },
        { title = LOC("$$$/MaskBridge/Matte/MaskType/Landscape=Landscape"),   value = "landscape" },
    }
end

--- Get existing masks on the current photo (must be in Develop + Masking)
--- @return table  — array of { title="Mask 1 (Subject)", value=maskID }
function MaskBridgeMatte.getExistingMasks()
    ensureDevelopModule()
    LrDevelopController.goToMasking()
    LrTasks.sleep(0.5)

    local allMasks = LrDevelopController.getAllMasks()
    if not allMasks or #allMasks == 0 then
        return {}
    end

    local items = {}
    for _, m in ipairs(allMasks) do
        local toolInfo = ""
        if m.Tools and m.Tools[1] then
            local t = m.Tools[1]
            if t.Type == "aiSelection" then
                toolInfo = " (" .. (t.Subtype or "AI") .. ")"
            elseif t.Type then
                toolInfo = " (" .. t.Type .. ")"
            end
        end
        table.insert(items, {
            title = (m.Name or "?") .. toolInfo,
            value = m.ID,
            name  = m.Name or "mask",
        })
    end

    return items
end

--- Export mattes for multiple photos (sequential — Develop must be active)
--- @param photos      table   — array of LrPhoto
--- @param maskSubtype string  — "subject", "sky", etc.
--- @param outputDir   string  — output directory
--- @param options     table   — { resolution, invert, namingPattern, progressScope }
--- @return number, number, number, table — successCount, failCount, skippedCount, skippedNames
---         skipped = photos where the AI found no matching subject (not errors)
function MaskBridgeMatte.exportMattesBatch(photos, maskSubtype, outputDir, options)
    options             = options or {}

    local progressScope = options.progressScope or LrProgressScope({
        title = LOC("$$$/MaskBridge/Matte/BatchProgressTitle=Mask Bridge — Export Lightroom Masks")
    })

    local total         = #photos
    local successCount  = 0
    local failCount     = 0
    local skippedCount  = 0
    local skippedNames  = {}

    for i, photo in ipairs(photos) do
        if progressScope:isCanceled() then
            log("Batch cancelled at " .. i .. "/" .. total)
            break
        end

        local fileName = photo:getFormattedMetadata('fileName') or "?"
        progressScope:setCaption(LOC("$$$/MaskBridge/Matte/BatchProgressCaption=Mask ^1/^2: ^3", i, total, fileName))
        progressScope:setPortionComplete(i - 1, total)

        -- Select this photo in catalog
        local catalog = LrApplication.activeCatalog()
        catalog:setSelectedPhotos(photo, { photo })
        LrTasks.sleep(1) -- let Develop update

        options._batchIndex = i
        local ok, result, status = MaskBridgeMatte.exportMatte(photo, maskSubtype, outputDir, options)
        if ok then
            successCount = successCount + 1
            log("Batch " .. i .. "/" .. total .. ": ✅ " .. fileName)
        elseif status == "no_detection" then
            -- AI found no matching subject — a clean skip, not a failure
            skippedCount = skippedCount + 1
            table.insert(skippedNames, fileName)
            log("Batch " .. i .. "/" .. total .. ": ⏭ " .. fileName .. " — " .. tostring(result))
        else
            failCount = failCount + 1
            log("Batch " .. i .. "/" .. total .. ": ❌ " .. fileName .. " — " .. tostring(result))
        end
    end

    progressScope:setPortionComplete(total, total)
    progressScope:done()

    log(string.format("Batch complete: %d/%d success, %d skipped, %d failed",
        successCount, total, skippedCount, failCount))
    return successCount, failCount, skippedCount, skippedNames
end

-- ============================================================================
-- Batch AI masks (Lightroom Classic 15.3+)
-- ============================================================================
-- A plug-in preset carrying only the DESCRIPTION of the mask is applied to a
-- group of photos, Lightroom recomputes the AI mask of each photo, and every
-- render phase is one grouped export: no Develop module, no slider tracking,
-- no per-photo navigation. Observed on Lightroom Classic 15.6 (2026-10-01):
--   * a mask copied with its photo-bound fields (InputDigest, MaskDigest,
--     MaskID, FullMaskSize, Origin...) keeps the SOURCE silhouette on every
--     photo while needsUpdateAISettings() stays false: never copy them;
--   * the updateAISettings argument of catalog:applyDevelopPreset left the
--     masks outdated; catalog:updateAISettings(photos) recomputes them;
--   * nothing detected: ErrorReason ~= 0 and no MaskDigest;
--   * applyDevelopSettings(saved) keeps the added mask; restoring with the
--     saved MaskGroupBasedCorrections list (or {}) removes it;
--   * exporting a photo whose AI settings are outdated opens the modal
--     "AI Updates Recommended" window: such a photo is never rendered here.
-- People, Objects and Landscape need a choice in the Masking panel: they keep
-- the per-photo path.

local BATCH_MASKS = {
    subject    = { MaskSubType = 1, MaskName = "Subject 1" },
    sky        = { MaskSubType = 2, MaskName = "Sky 1" },
    background = { MaskSubType = 0, MaskSubCategoryID = 22, MaskName = "Background 1" },
}
local BATCH_PRESET_VERSION = 1
local BATCH_CORRECTION_SYNC_ID = "4D61736B4272696467654261746368C1"
local BATCH_MASK_SYNC_ID       = "4D61736B4272696467654261746368D1"
local BATCH_GROUP_SIZE  = 8   -- photos modified at the same time
local BATCH_RENDER_SIZE = 4   -- photos per export session (bounded rendering)
local BATCH_LOCAL_WHITE = { "LocalExposure2012", "LocalContrast2012", "LocalHighlights2012",
    "LocalShadows2012", "LocalWhites2012", "LocalBlacks2012", "LocalClarity2012" }

local function now()
    return (LrDate.currentTime and LrDate.currentTime()) or os.time()
end

local function maskList(settings)
    return (settings and settings.MaskGroupBasedCorrections) or {}
end

local function findBatchCorrection(settings)
    for _, correction in ipairs(maskList(settings)) do
        if correction.CorrectionSyncID == BATCH_CORRECTION_SYNC_ID then return correction end
    end
end

local function needsAIUpdate(photo)
    local ok, needs = LrTasks.pcall(function() return photo:needsUpdateAISettings() end)
    return not ok or needs == true
end

--- Settings of the batch preset: one correction, mask description only,
--- every white local at its maximum (1 = +4 EV / +100).
function MaskBridgeMatte._batchPresetValues(maskSubtype)
    local def = assert(BATCH_MASKS[maskSubtype], "Unsupported batch mask type")
    local correction = {
        What = "Correction", CorrectionActive = true, CorrectionAmount = 1,
        CorrectionName = "Mask Bridge", CorrectionSyncID = BATCH_CORRECTION_SYNC_ID,
        CorrectionMasks = { {
            What = "Mask/Image", MaskActive = true, MaskName = def.MaskName,
            MaskBlendMode = 0, MaskInverted = false, MaskSyncID = BATCH_MASK_SYNC_ID,
            MaskValue = 1, MaskVersion = 1, MaskSubType = def.MaskSubType,
            MaskSubCategoryID = def.MaskSubCategoryID,
            ReferencePoint = "0.500000 0.500000", ErrorReason = 0,
        } },
    }
    for _, key in ipairs(BATCH_LOCAL_WHITE) do correction[key] = 1 end
    return { MaskGroupBasedCorrections = { correction } }
end

local function batchPreset(maskSubtype)
    local name = string.format("Mask Bridge batch %s v%d", maskSubtype, BATCH_PRESET_VERSION)
    for _, preset in ipairs(LrApplication.getDevelopPresetsForPlugin(_PLUGIN) or {}) do
        if preset:getName() == name then return preset end
    end
    local preset = LrApplication.addDevelopPresetForPlugin(_PLUGIN, name,
        MaskBridgeMatte._batchPresetValues(maskSubtype))
    if not preset then error("Cannot create the Mask Bridge mask preset") end
    return preset
end

--- True when this mask type can be computed for many photos at once.
function MaskBridgeMatte.canBatchAI(maskSubtype)
    if not BATCH_MASKS[maskSubtype] then return false end
    local version = LrApplication.versionTable and LrApplication.versionTable() or {}
    local major, minor = version.major or 0, version.minor or 0
    return major > 15 or (major == 15 and minor >= 3)
end

-- Render `entries` (one grouped export per BATCH_RENDER_SIZE photos) and
-- store each rendered path in entry[key]. Renditions are matched by photo.
local function renderEntries(entries, settings, key, progress)
    if #entries == 0 then return end
    settings.LR_collisionHandling = "rename"
    local byPhoto, photos = {}, {}
    for _, entry in ipairs(entries) do
        byPhoto[entry.photo] = entry
        photos[#photos + 1] = entry.photo
    end
    MaskBridgeUtils.setDashboardMode(true)
    local ok, err = LrTasks.pcall(MaskBridgeUtils.forEachExportRendition, photos, settings,
        BATCH_RENDER_SIZE, progress, function(rendition)
            local rendered, path = rendition:waitForRender()
            local entry = byPhoto[rendition.photo]
            if entry and rendered and path then entry[key] = path end
        end)
    MaskBridgeUtils.setDashboardMode(false)
    if not ok then error(err) end
end

local function restoreBatchGroup(catalog, mutated)
    if #mutated == 0 then return end
    local status = catalog:withWriteAccessDo("Matte restore", function()
        for _, entry in ipairs(mutated) do
            local settings = {}
            for k, v in pairs(entry.saved) do settings[k] = v end
            -- Without an explicit list Lightroom keeps the added mask
            settings.MaskGroupBasedCorrections = entry.saved.MaskGroupBasedCorrections or {}
            entry.photo:applyDevelopSettings(settings, "MaskBridge Matte Restore")
        end
    end, { timeout = 60 })
    for _, entry in ipairs(mutated) do
        local current = entry.photo:getDevelopSettings()
        local restored = status == "executed" and current ~= nil
            and not findBatchCorrection(current)
            and #maskList(current) == #maskList(entry.saved)
        if restored then
            for key in pairs(BLACK_GLOBALS) do
                local a, b = current[key], entry.saved[key]
                if type(a) == "number" and type(b) == "number" then
                    if math.abs(a - b) > 1e-6 then restored = false end
                elseif a ~= b then
                    restored = false
                end
            end
        end
        if not restored then
            entry.restoreFailed = true
            log("ERROR restore not confirmed: " .. tostring(entry.name))
        end
    end
end

local function runBatchGroup(entries, preset, maskSubtype, outputDir, options, progress)
    local catalog = LrApplication.activeCatalog()
    local enhanced = options.enhancedDetection or false
    local base = LrPathUtils.getStandardFilePath('temp')
    local tempDir = LrPathUtils.child(base, "maskbridge_batch_" .. os.time() .. "_" .. math.random(1000000))
    local mutated = {}
    local function finish(entry, status, message)
        if not entry.status then entry.status, entry.message = status, message end
    end
    local function live()
        local list = {}
        for _, entry in ipairs(entries) do if not entry.status then list[#list + 1] = entry end end
        return list
    end
    local function photosOf(list)
        local photos = {}
        for _, entry in ipairs(list) do photos[#photos + 1] = entry.photo end
        return photos
    end
    local function canceled() return options.isCanceled and options.isCanceled() end
    local function phase(title)
        log(string.format("Batch phase: %s (%d photos)", title, #live()))
        return now()
    end
    local function done(title, started)
        log(string.format("Batch phase done: %s in %.2fs", title, now() - started))
    end

    local ok, err = LrTasks.pcall(function()
        for _, dir in ipairs({ "", "/clean", "/alpha", "/ref", "/matte" }) do
            LrFileUtils.createAllDirectories(tempDir .. dir)
        end
        local t = phase("save state")
        for _, entry in ipairs(entries) do
            entry.name = entry.photo:getFormattedMetadata('fileName') or "?"
            entry.stem = LrPathUtils.removeExtension(entry.name)
            entry.saved = entry.photo:getDevelopSettings()
            if not entry.saved then finish(entry, "error", "Cannot save Lightroom settings") end
        end
        local status = catalog:withWriteAccessDo("Mask Bridge recovery snapshot", function()
            for _, entry in ipairs(live()) do
                if not createRecoverySnapshot(entry.photo) then
                    finish(entry, "error", "Cannot create recovery snapshot; no matte settings were applied")
                end
            end
        end, { timeout = 30 })
        if status ~= "executed" then error("Catalogue busy: no matte settings applied") end
        done("save state", t)

        -- Clean renders BEFORE any change: they cannot carry matte settings.
        if not options.masksOnly then
            t = phase("clean image render")
            renderEntries(live(), cleanRenderSettings(tempDir .. "/clean", options), "clean", progress)
            done("clean image render", t)
        end
        if options.exportAlpha then
            local alphaOptions = {}
            for k, v in pairs(options) do alphaOptions[k] = v end
            alphaOptions.exportFormat = "PNG"
            t = phase("alpha source render")
            renderEntries(live(), cleanRenderSettings(tempDir .. "/alpha", alphaOptions), "alphaSource", progress)
            done("alpha source render", t)
        end
        if canceled() then return end

        t = phase("black globals")
        local globals = enhanced and BLACK_GLOBALS_ENHANCED or BLACK_GLOBALS
        status = catalog:withWriteAccessDo("Matte black globals", function()
            for _, entry in ipairs(live()) do
                mutated[#mutated + 1] = entry
                entry.photo:applyDevelopSettings(globals, "MaskBridge Matte Black")
            end
        end, { timeout = 30 })
        if status ~= "executed" then error("Catalogue busy: no matte settings applied") end
        done("black globals", t)
        if enhanced then
            t = phase("reference render")
            renderEntries(live(), matteRenderSettings(tempDir .. "/ref", options.resolution or 2048), "reference", progress)
            done("reference render", t)
            if canceled() then return end
            for _, entry in ipairs(live()) do
                if not entry.reference then finish(entry, "error", "Reference render failed") end
            end
        end
        if canceled() then return end

        t = phase("AI mask")
        local step = now()
        status = catalog:withWriteAccessDo("Mask Bridge batch mask", function()
            catalog:applyDevelopPreset(photosOf(live()), preset, _PLUGIN, 100, true)
        end, { timeout = 60 })
        if status ~= "executed" then error("Catalogue busy: mask not applied") end
        log(string.format("  preset applied in %.2fs", now() - step))
        step = now()
        status = catalog:withWriteAccessDo("Mask Bridge AI update", function()
            catalog:updateAISettings(photosOf(live()))
        end, { timeout = 180 })
        if status ~= "executed" then error("Catalogue busy: AI masks not computed") end
        log(string.format("  updateAISettings returned in %.2fs", now() - step))
        step = now()
        local deadline = now() + 30 + 3 * #live()
        local pending
        repeat
            pending = 0
            for _, entry in ipairs(live()) do
                if needsAIUpdate(entry.photo) then pending = pending + 1 end
            end
            if pending > 0 then LrTasks.sleep(0.25) end
        until pending == 0 or now() > deadline or canceled()
        log(string.format("  AI results ready after %.2fs more (%d still pending)", now() - step, pending))
        for _, entry in ipairs(live()) do
            local settings = entry.photo:getDevelopSettings()
            local correction = findBatchCorrection(settings)
            local mask = correction and correction.CorrectionMasks and correction.CorrectionMasks[1]
            if needsAIUpdate(entry.photo) then
                finish(entry, "error", "Lightroom did not finish the AI mask")
            elseif not mask or correction.LocalExposure2012 ~= 1 then
                finish(entry, "error", "Mask settings not applied")
            elseif (tonumber(mask.ErrorReason) or 0) ~= 0 or not mask.MaskDigest then
                finish(entry, "no_detection", "No " .. maskSubtype .. " detected")
            elseif math.abs((settings.Exposure2012 or 0) - globals.Exposure2012) > 1e-6 then
                finish(entry, "error", "Matte settings not applied")
            end
        end
        done("AI mask", t)
        if canceled() then return end

        t = phase("matte render")
        renderEntries(live(), matteRenderSettings(tempDir .. "/matte", options.resolution or 2048), "matte", progress)
        if canceled() then return end
        for _, entry in ipairs(live()) do
            if not entry.matte then finish(entry, "error", "Matte render failed") end
        end
        done("matte render", t)
    end)

    -- Finally: every changed photo goes back to its saved settings.
    local restoreOK, restoreError = LrTasks.pcall(restoreBatchGroup, catalog, mutated)
    if not restoreOK then
        log("ERROR batch restore: " .. tostring(restoreError))
        for _, entry in ipairs(mutated) do entry.restoreFailed = true end
    end
    if not ok then log("ERROR batch group: " .. tostring(err)) end

    for _, entry in ipairs(entries) do
        if entry.restoreFailed then
            entry.status, entry.message = "restore_failed",
                "Could not restore Lightroom settings. Use the '" .. recoverySnapshotName(entry.photo) .. "' snapshot."
        elseif not ok then
            finish(entry, "error", tostring(err))
        end
    end

    -- Publication, with the photos back in their own state.
    for _, entry in ipairs(live()) do
        if canceled() then finish(entry, "canceled", "Canceled") else
            local output = MaskBridgeUtils.uniqueOutputPath(
                MaskBridgeMatte._getMaskOutputPath(outputDir, entry.stem, options.namingPattern or "standard"))
            if not convertMatteToPNG(entry.matte, output, options.invert, entry.reference) then
                finish(entry, "error", "Matte conversion failed")
            elseif not options.masksOnly then
                local destination = MaskBridgeUtils.uniqueOutputPath(LrPathUtils.child(
                    options.imageOutputDir or outputDir,
                    MaskBridgeMatte._getImageFilename(entry.stem, options, entry.index)))
                local moved, moveError = false, "Image render failed"
                if entry.clean then moved, moveError = safeMoveOverwrite(entry.clean, destination) end
                if not moved then finish(entry, "error", "Mask saved, but image export failed: " .. tostring(moveError)) end
            end
            if not entry.status and options.exportAlpha then
                local alphaPath = MaskBridgeUtils.uniqueOutputPath(LrPathUtils.child(outputDir, entry.stem .. "_alpha.png"))
                if not (entry.alphaSource and mergeAlpha(entry.alphaSource, output, alphaPath)) then
                    finish(entry, "error", "Mask saved, but the requested alpha export failed")
                end
            end
            finish(entry, "ok", output)
        end
    end
    for _, entry in ipairs(entries) do finish(entry, "canceled", "Canceled") end
    LrTasks.pcall(function()
        if LrFileUtils.exists(tempDir) then LrFileUtils.delete(tempDir) end
    end)
end

--- Export mattes for many photos at once (Lightroom Classic 15.3+, see
--- canBatchAI). Same contract as exportMattesBatch.
--- @return number, number, number, table — successCount, failCount, skippedCount, skippedNames
function MaskBridgeMatte.exportMattesBatchAI(photos, maskSubtype, outputDir, options)
    options = options or {}
    local progressScope = options.progressScope or LrProgressScope({
        title = LOC("$$$/MaskBridge/Matte/BatchProgressTitle=Mask Bridge — Export Lightroom Masks")
    })
    if not options.isCanceled then
        options.isCanceled = function() return progressScope:isCanceled() end
    end
    writeLogHeader("Matte Export (Batch AI, " .. tostring(maskSubtype) .. ")")
    local started = now()
    local total = #photos
    local successCount, failCount, skippedCount, skippedNames = 0, 0, 0, {}
    local preset = batchPreset(maskSubtype)

    -- Nothing here needs Develop. Left open on the active photo, Develop
    -- starts its own AI pass on it when the preset lands, and Lightroom then
    -- shows a modal "Can't apply requested adjustments ... an AI process is
    -- running on them" (LrC 15.6) although the batch result is correct.
    if LrApplicationView.getCurrentModuleName() == "develop" then
        LrApplicationView.switchToModule("library")
        LrTasks.sleep(0.5)
        log("Switched to Library module for the batch")
    end

    for first = 1, total, BATCH_GROUP_SIZE do
        if options.isCanceled() then
            log("Batch cancelled before photo " .. first .. "/" .. total)
            break
        end
        local entries = {}
        for i = first, math.min(total, first + BATCH_GROUP_SIZE - 1) do
            entries[#entries + 1] = { photo = photos[i], index = i }
        end
        local last = first + #entries - 1
        progressScope:setCaption(LOC("$$$/MaskBridge/Matte/BatchProgressCaption=Mask ^1/^2: ^3", last, total,
            photos[first]:getFormattedMetadata('fileName') or "?"))
        progressScope:setPortionComplete(first - 1, total)
        runBatchGroup(entries, preset, maskSubtype, outputDir, options, progressScope)
        local canceledCount = 0
        for _, entry in ipairs(entries) do
            if entry.status == "canceled" then canceledCount = canceledCount + 1 end
        end
        if canceledCount > 0 then
            log(string.format("Batch cancelled during photos %d-%d: %d restored without export",
                first, last, canceledCount))
        end
        for _, entry in ipairs(entries) do
            if entry.status == "ok" then
                successCount = successCount + 1
                log("Batch " .. entry.index .. "/" .. total .. ": ✅ " .. tostring(entry.name))
            elseif entry.status == "no_detection" then
                skippedCount = skippedCount + 1
                table.insert(skippedNames, entry.name)
                log("Batch " .. entry.index .. "/" .. total .. ": ⏭ " .. tostring(entry.name) .. " — " .. tostring(entry.message))
            elseif entry.status ~= "canceled" then
                failCount = failCount + 1
                log("Batch " .. entry.index .. "/" .. total .. ": ❌ " .. tostring(entry.name) .. " — " .. tostring(entry.message))
            end
        end
    end

    progressScope:setPortionComplete(total, total)
    progressScope:done()
    log(string.format("Batch AI complete: %d/%d success, %d skipped, %d failed in %.1fs",
        successCount, total, skippedCount, failCount, now() - started))
    return successCount, failCount, skippedCount, skippedNames
end

return MaskBridgeMatte
