"""Batch AI matte path (Lightroom Classic 15.3+) against an SDK double.

The double reproduces what Lightroom 15.6 did on 2026-10-01: a plug-in preset
replaces the mask list, catalog:updateAISettings computes each photo's own
mask (or ErrorReason=1 when nothing is found), and exporting a photo whose AI
settings are outdated would open a blocking window (here: an assertion).
"""
from pathlib import Path

import pytest


BATCH_DOUBLE = r'''
local function deep(v)
    if type(v) ~= "table" then return v end
    local c = {}
    for k, x in pairs(v) do c[k] = deep(x) end
    return c
end
version = {major=15, minor=6}
presets, renders, posted = {}, {}, {}
apply_calls, update_calls, restore_calls, clock = 0, 0, 0, 0
ignore_mask_restore, fail_render_dir, cancel_after_published = false, nil, nil
photo_number = 0

function make_photo(name, opts)
    photo_number = photo_number + 1
    -- Lightroom returns every global setting, not only the changed ones
    local p = {localIdentifier=photo_number, name=name, opts=opts or {}, needs=false, settings={Exposure2012=0.5, Contrast2012=10,
        Highlights2012=0, Shadows2012=0, Whites2012=0, Blacks2012=3, Clarity2012=0,
        Vibrance=0, Saturation=0, Dehaze=0, Texture=0}}
    if p.opts.masks then p.settings.MaskGroupBasedCorrections = deep(p.opts.masks) end
    function p:getFormattedMetadata(k) return self.name end
    function p:getDevelopSettings() return deep(self.settings) end
    function p:applyDevelopSettings(s, label)
        if label == "MaskBridge Matte Restore" then restore_calls = restore_calls + 1 end
        for k, v in pairs(s) do
            if not (k == "MaskGroupBasedCorrections" and ignore_mask_restore) then
                self.settings[k] = deep(v)
            end
        end
    end
    p.snapshots = p.opts.snapshots or {}
    function p:createDevelopSnapshot(name, update)
        if self.opts.snapshot_fails or (self.snapshots[name] and not update) then return false end
        self.snapshots[name] = deep(self.settings)
        return true
    end
    function p:needsUpdateAISettings() return self.needs end
    return p
end

function catalog:applyDevelopPreset(list, preset, plugin, amount, update)
    apply_calls = apply_calls + 1
    module_at_apply = current_module or "develop"
    for _, p in ipairs(list) do
        p.settings.MaskGroupBasedCorrections = deep(preset.values.MaskGroupBasedCorrections)
        p.needs = true
    end
end
function catalog:updateAISettings(list)
    update_calls = update_calls + 1
    for _, p in ipairs(list) do
        if not p.opts.stuck then
            p.needs = false
            local masks = p.settings.MaskGroupBasedCorrections
            local m = masks[#masks].CorrectionMasks[1]
            if p.opts.nodetect then m.ErrorReason = 1 else m.MaskDigest = "D-" .. p.name; m.ErrorReason = nil end
        end
    end
end

local function batchCorrection(p)
    for _, c in ipairs(p.settings.MaskGroupBasedCorrections or {}) do
        if c.CorrectionName == "Mask Bridge" then return c end
    end
end

local function batchExport(opts)
    local list = opts.photosToExport
    local dir = opts.exportSettings.LR_export_destinationPathPrefix
    for _, p in ipairs(list) do
        assert(not p.needs, "AI Updates Recommended window would block the export")
        renders[#renders + 1] = {photo=p.name, kind=dir:match("([^/]+)$"),
            batch=batchCorrection(p) ~= nil, exposure=p.settings.Exposure2012}
    end
    if fail_render_dir and dir:match(fail_render_dir) then error("injected render failure") end
    return {renditions=function()
        local i = 0
        return function()
            i = i + 1
            local p = list[i]
            if not p then return nil end
            render_number = render_number + 1
            local path = dir .. "/" .. p.name .. "_" .. render_number .. ".tif"
            files[path] = true
            return i, {photo=p, waitForRender=function() return true, path end}
        end
    end}
end

local application = {
    activeCatalog=function() return catalog end,
    versionTable=function() return version end,
    getDevelopPresetsForPlugin=function() return presets end,
    addDevelopPresetForPlugin=function(plugin, name, values)
        local preset = {name=name, values=deep(values)}
        function preset:getName() return self.name end
        presets[#presets + 1] = preset
        return preset
    end,
}
local previousImport = import
function import(n)
    if n == "LrApplication" then return application end
    if n == "LrExportSession" then return batchExport end
    if n == "LrDate" then return {currentTime=function() clock = clock + 0.5; return clock end} end
    return previousImport(n)
end
local previousPost = utils.httpPost
utils.httpPost = function(endpoint, data)
    posted[#posted + 1] = endpoint
    return previousPost(endpoint, data)
end
progress = {isCanceled=function()
        if not cancel_after_published then return false end
        local n = 0
        for _, e in ipairs(posted) do if e == "/matte" then n = n + 1 end end
        return n >= cancel_after_published
    end,
    setCaption=function() end, setPortionComplete=function() end, done=function() end}
matte = dofile(plugin_path .. "/MaskBridgeMatte.lua")

function run_batch(list, subtype, options)
    options = options or {}
    options.progressScope = progress
    options.isCanceled = progress.isCanceled
    return matte.exportMattesBatchAI(list, subtype or "subject", "/out", options)
end
function count_renders(kind, field)
    local n = 0
    for _, r in ipairs(renders) do
        if r.kind == kind and (field == nil or r[field]) then n = n + 1 end
    end
    return n
end
function count_files(pattern)
    local n = 0
    for p in pairs(files) do if p:match(pattern) then n = n + 1 end end
    return n
end
'''


@pytest.fixture
def lua():
    runtime = pytest.importorskip("lupa.lua51").LuaRuntime(unpack_returned_tuples=True)
    runtime.globals().plugin_path = str(Path(__file__).resolve().parents[2])
    runtime.execute(Path(__file__).with_name("sdk_double.lua").read_text())
    runtime.execute(BATCH_DOUBLE)
    return runtime


def results(lua, code):
    lua.execute(code)
    g = lua.globals()
    return g.ok_count, g.fail_count, g.skip_count


def test_master_and_virtual_copies_keep_independent_recovery_settings(lua):
    lua.execute('''
        family = { ["Mask Bridge - Before export"] = {Exposure2012=9} }
        master = make_photo("same.tif", {snapshots=family})
        copy = make_photo("same.tif", {snapshots=family})
        master.settings.CropLeft = 0
        copy.settings.CropLeft = 0.28
        copy.settings.Exposure2012 = 2
        ok_count, fail_count = run_batch({master, copy}, "subject", {masksOnly=true})
    ''')
    g = lua.globals()
    assert (g.ok_count, g.fail_count) == (2, 0)
    assert len(list(g.family.items())) == 3  # Legacy recovery remains untouched.
    settings = [v for k, v in g.family.items() if k != "Mask Bridge - Before export"]
    assert sorted((s.CropLeft, s.Exposure2012) for s in settings) == [(0, .5), (.28, 2)]
    # Re-exporting a renamed copy updates only that view, even if rendering fails.
    lua.execute('''
        copy.name = "renamed.tif"
        copy.settings.CropLeft = 0.4
        fail_render_dir = "/matte$"
        run_batch({copy}, "subject", {masksOnly=true})
    ''')
    assert len(list(g.family.items())) == 3
    settings = [v for k, v in g.family.items() if k != "Mask Bridge - Before export"]
    assert sorted((s.CropLeft, s.Exposure2012) for s in settings) == [(0, .5), (.4, 2)]
    assert g.master.settings.CropLeft == 0
    assert g.copy.settings.CropLeft == .4


def test_missing_photo_identity_stops_before_batch_mutation(lua):
    lua.execute('''
        unsafe = make_photo("unsafe.tif")
        unsafe.localIdentifier = nil
        ok_count, fail_count = run_batch({unsafe}, "subject", {masksOnly=true})
    ''')
    g = lua.globals()
    assert (g.ok_count, g.fail_count, g.apply_calls) == (0, 1, 0)
    assert g.unsafe.settings.Exposure2012 == .5
    assert len(list(g.unsafe.snapshots.items())) == 0


def test_preset_carries_only_the_mask_description(lua):
    lua.execute('''
        subject_values = matte._batchPresetValues("subject")
        background = matte._batchPresetValues("background")
        sky = matte._batchPresetValues("sky")
    ''')
    g = lua.globals()
    correction = g.subject_values.MaskGroupBasedCorrections[1]
    mask = correction.CorrectionMasks[1]
    for photo_bound in ("InputDigest", "InputDigestVersion", "MaskDigest", "MaskID",
                        "FullMaskSize", "Origin", "WholeImageArea", "ModelVersion"):
        assert mask[photo_bound] is None, photo_bound
    assert correction.CorrectionID is None
    assert (mask.What, mask.MaskSubType) == ("Mask/Image", 1)
    assert g.sky.MaskGroupBasedCorrections[1].CorrectionMasks[1].MaskSubType == 2
    background_mask = g.background.MaskGroupBasedCorrections[1].CorrectionMasks[1]
    assert (background_mask.MaskSubType, background_mask.MaskSubCategoryID) == (0, 22)
    for key in ("LocalExposure2012", "LocalContrast2012", "LocalHighlights2012",
                "LocalShadows2012", "LocalWhites2012", "LocalBlacks2012", "LocalClarity2012"):
        assert correction[key] == 1


@pytest.mark.parametrize("major, minor, subtype, expected", [
    (15, 6, "subject", True), (15, 3, "sky", True), (16, 0, "background", True),
    (15, 2, "subject", False), (14, 5, "subject", False),
    (15, 6, "people", False), (15, 6, "objects", False), (15, 6, "landscape", False),
])
def test_batch_path_requires_lightroom_15_3_and_a_panel_free_mask(lua, major, minor, subtype, expected):
    lua.globals().version.major = major
    lua.globals().version.minor = minor
    assert lua.eval(f'matte.canBatchAI("{subtype}")') is expected


def test_group_is_masked_once_rendered_by_phase_and_restored(lua):
    ok, failed, skipped = results(lua, '''
        user_mask = {{What="Correction", CorrectionName="User", CorrectionSyncID="USER",
            LocalExposure2012=0.2, CorrectionMasks={{What="Mask/Image", MaskDigest="U"}}}}
        a, b, c = make_photo("a.cr3"), make_photo("b.cr3", {masks=user_mask}), make_photo("c.cr3")
        ok_count, fail_count, skip_count = run_batch({a, b, c}, "subject",
            {masksOnly=false, exportAlpha=true, enhancedDetection=true})
    ''')
    assert (ok, failed, skipped) == (3, 0, 0)
    g = lua.globals()
    assert (g.apply_calls, g.update_calls, g.restore_calls) == (1, 1, 3)
    # Clean sources come from the untouched photos, the reference from the
    # black globals without the mask, the matte with the computed mask.
    assert lua.eval('count_renders("clean")') == 3 and lua.eval('count_renders("clean", "batch")') == 0
    assert lua.eval('count_renders("alpha")') == 3 and lua.eval('count_renders("alpha", "batch")') == 0
    assert lua.eval('count_renders("ref")') == 3 and lua.eval('count_renders("ref", "batch")') == 0
    assert lua.eval('count_renders("matte", "batch")') == 3
    for r in g.renders.values():
        assert (r.exposure == 0.5) == (r.kind in ("clean", "alpha"))
    # Every photo is back to its own settings, the user's mask included.
    for name in ("a", "b", "c"):
        settings = lua.eval(f"{name}.settings")
        assert (settings.Exposure2012, settings.Contrast2012, settings.Blacks2012) == (0.5, 10, 3)
    assert len(lua.eval("a.settings.MaskGroupBasedCorrections")) == 0
    b_masks = lua.eval("b.settings.MaskGroupBasedCorrections")
    assert len(b_masks) == 1 and b_masks[1].CorrectionSyncID == "USER"
    assert lua.eval('count_files("^/out/.*%.mask%.png$")') == 3
    assert lua.eval('count_files("^/out/.*_alpha%.png$")') == 3


def test_batch_leaves_develop_before_touching_photos(lua):
    # In Develop, Lightroom runs its own AI on the active photo once the
    # preset lands and opens a modal error: the batch works from Library.
    ok, failed, skipped = results(lua, '''
        current_module = "develop"
        a, b = make_photo("a.cr3"), make_photo("b.cr3")
        ok_count, fail_count, skip_count = run_batch({a, b}, "subject", {masksOnly=true})
    ''')
    assert (ok, failed, skipped) == (2, 0, 0)
    assert lua.globals().module_at_apply == "library"


def test_nothing_detected_is_a_skip_and_never_a_matte(lua):
    ok, failed, skipped = results(lua, '''
        a, empty = make_photo("a.cr3"), make_photo("gray.jpg", {nodetect=true})
        ok_count, fail_count, skip_count, skipped_names = run_batch({a, empty}, "subject", {masksOnly=true})
    ''')
    assert (ok, failed, skipped) == (1, 0, 1)
    assert list(lua.globals().skipped_names.values()) == ["gray.jpg"]
    assert lua.eval('count_renders("matte")') == 1
    assert lua.eval("empty.settings.Exposure2012") == 0.5
    assert len(lua.eval("empty.settings.MaskGroupBasedCorrections")) == 0


def test_outdated_ai_settings_are_never_exported(lua):
    # Exporting it would open the modal "AI Updates Recommended" window.
    ok, failed, skipped = results(lua, '''
        a, stuck, c = make_photo("a.cr3"), make_photo("stuck.cr3", {stuck=true}), make_photo("c.cr3")
        ok_count, fail_count, skip_count = run_batch({a, stuck, c}, "subject", {masksOnly=true})
    ''')
    assert (ok, failed, skipped) == (2, 1, 0)
    assert lua.eval("stuck.settings.Exposure2012") == 0.5
    assert len(lua.eval("stuck.settings.MaskGroupBasedCorrections")) == 0


def test_render_failure_restores_every_photo(lua):
    ok, failed, skipped = results(lua, '''
        fail_render_dir = "/matte$"
        a, b = make_photo("a.cr3"), make_photo("b.cr3")
        ok_count, fail_count, skip_count = run_batch({a, b}, "subject", {masksOnly=true, enhancedDetection=true})
    ''')
    assert (ok, failed, skipped) == (0, 2, 0)
    assert lua.globals().restore_calls == 2
    for name in ("a", "b"):
        assert lua.eval(f"{name}.settings.Exposure2012") == 0.5
        assert len(lua.eval(f"{name}.settings.MaskGroupBasedCorrections")) == 0
    assert lua.eval('count_files("^/out/")') == 0


def test_unconfirmed_restore_is_a_visible_failure(lua):
    ok, failed, skipped = results(lua, '''
        ignore_mask_restore = true
        a, b = make_photo("a.cr3"), make_photo("b.cr3")
        ok_count, fail_count, skip_count = run_batch({a, b}, "subject", {masksOnly=true})
    ''')
    assert (ok, failed, skipped) == (0, 2, 0)
    assert lua.eval('count_files("^/out/")') == 0


def test_photo_without_recovery_snapshot_is_never_modified(lua):
    ok, failed, skipped = results(lua, '''
        a, unsafe = make_photo("a.cr3"), make_photo("unsafe.cr3", {snapshot_fails=true})
        ok_count, fail_count, skip_count = run_batch({a, unsafe}, "subject", {masksOnly=true})
    ''')
    assert (ok, failed, skipped) == (1, 1, 0)
    assert not any(r.photo == "unsafe.cr3" for r in lua.globals().renders.values())
    assert lua.globals().restore_calls == 1


def test_cancel_stops_before_the_next_group(lua):
    ok, failed, skipped = results(lua, '''
        cancel_after_published = 8
        list = {}
        for i = 1, 10 do list[i] = make_photo("p" .. i .. ".cr3") end
        ok_count, fail_count, skip_count = run_batch(list, "subject", {masksOnly=true})
    ''')
    assert (ok, failed, skipped) == (8, 0, 0)
    assert lua.globals().apply_calls == 1
    assert lua.eval("list[9].settings.Exposure2012") == 0.5
    assert lua.eval('count_files("^/out/.*%.mask%.png$")') == 8
