"""Regressions for destructive, authorization and data-fidelity audit findings."""
import json
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
import pytest
from PIL import Image, ImageCms

from atomic_io import atomic_write, distinct_output
from inference_engine import MaskBridgeEngine
from validation import normalize_manifest, validate_request


@pytest.mark.parametrize("params", [[], None, {"image": []}, {"output": None}, {"invert": "false"}, {"prompts": [1]}])
def test_request_schema_rejects_bad_types(params):
    with pytest.raises(ValueError):
        validate_request(params)


def test_batch_cannot_overwrite_another_input(tmp_path):
    a, b = str(tmp_path / "a.png"), str(tmp_path / "b.png")
    with pytest.raises(ValueError, match="input"):
        normalize_manifest({"images": [{"input": a, "output": b}, {"input": b, "output": str(tmp_path / 'c.png')}]})


def test_atomic_failure_preserves_destination(tmp_path):
    target = tmp_path / "original.png"
    target.write_bytes(b"original")
    with patch("atomic_io.os.replace", side_effect=OSError("disk failure")):
        with pytest.raises(OSError):
            atomic_write(target, b"replacement")
    assert target.read_bytes() == b"original"
    assert list(tmp_path.iterdir()) == [target]


def test_source_alias_rejected(tmp_path):
    source, alias = tmp_path / "original.png", tmp_path / "alias.png"
    source.write_bytes(b"original")
    try:
        alias.symlink_to(source)
    except OSError:
        # Windows can require Developer Mode/admin rights for symbolic links.
        # A hard link exercises the same-file guard without those privileges.
        alias.hardlink_to(source)
    with pytest.raises(ValueError):
        distinct_output(alias, source)


def test_alpha_keeps_one_pixel_strands_and_profile(tmp_path):
    source, mask, output = [tmp_path / p for p in ("rgb.png", "mask.png", "out.png")]
    profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    Image.new("RGB", (20, 20), "red").save(source, icc_profile=profile)
    alpha = np.zeros((20, 20), np.uint8); alpha[:, 10] = 255
    Image.fromarray(alpha).save(mask)
    MaskBridgeEngine.merge_rgb_mask_to_rgba(str(source), str(mask), str(output))
    with Image.open(output) as result:
        assert result.info['icc_profile'] == profile
        np.testing.assert_array_equal(np.asarray(result)[:, :, 3], alpha)


def test_matte_keeps_small_regions_and_holes(tmp_path):
    source, output = tmp_path / "matte.png", tmp_path / "out.png"
    pixels = np.zeros((400, 400), np.uint8)
    pixels[30:230, 30:230] = 255
    pixels[90:120, 90:120] = 0
    pixels[300:330, 300:330] = 255
    Image.fromarray(pixels).save(source)
    MaskBridgeEngine.process_matte_to_alpha(str(source), str(output))
    np.testing.assert_array_equal(np.asarray(Image.open(output)), pixels)


def test_preprocessing_matches_exporter_contract():
    engine = MaskBridgeEngine.__new__(MaskBridgeEngine)
    image = np.random.default_rng(42).integers(0, 256, (63, 117, 3), dtype=np.uint8)
    reference = Image.fromarray(image[:, :, ::-1]).resize((engine.INPUT_SIZE, engine.INPUT_SIZE))
    values = np.asarray(reference).astype(np.float32) / 255
    values = ((values - [0.485, 0.456, 0.406]) / [0.229, 0.224, 0.225]).astype(np.float32)
    np.testing.assert_allclose(engine._preprocess_rfdetr(image), values.transpose(2, 0, 1)[None], atol=5e-7)


@pytest.fixture
def lua():
    runtime = pytest.importorskip("lupa.lua51").LuaRuntime(unpack_returned_tuples=True)
    runtime.globals().plugin_path = str(Path(__file__).resolve().parents[2])
    runtime.execute(Path(__file__).with_name("sdk_double.lua").read_text())
    return runtime


@pytest.mark.parametrize('cancel_at, expected_batches, expected_renders', [
    (0, 3, 10), (-1, 0, 0), (2, 1, 4),
])
def test_lua_export_batches_allow_sdk_yields_and_drain_cancelled_batch(
        lua, cancel_at, expected_batches, expected_renders):
    # A real Lua 5.1 coroutine catches the generic-for yield boundary that
    # Lightroom's canYield()/export-session constructor rejects. A synchronous
    # SDK double would miss the regression even if every file count matched.
    lua.globals().cancel_at = cancel_at
    lua.execute('''
        local originalImport = import
        batches, rendered, discarded, outstanding = 0, 0, 0, 0
        canceled = cancel_at == -1
        function import(name)
            if name ~= "LrExportSession" then return originalImport(name) end
            return function(options)
                assert(outstanding == 0, "Previous render batch was abandoned")
                assert(#options.photosToExport <= 4, "Unbounded rendering")
                coroutine.yield("create session")
                batches = batches + 1
                outstanding = #options.photosToExport
                return {renditions=function()
                    coroutine.yield("prepare renditions")
                    local index = 0
                    return function()
                        index = index + 1
                        local photoId = options.photosToExport[index]
                        if not photoId then return nil end
                        return index, {waitForRender=function()
                            coroutine.yield("wait for render")
                            outstanding = outstanding - 1
                            rendered = rendered + 1
                            if photoId == cancel_at then canceled = true end
                            return true, photoId
                        end}
                    end
                end}
            end
        end
        local photos = {}; for i = 1, 10 do photos[i] = i end
        local progress = {isCanceled=function() return canceled end}
        local task = coroutine.create(function()
            utils.forEachExportRendition(photos, {}, 4, progress, function(rendition)
                local ok, id = rendition:waitForRender()
                assert(ok)
                if canceled then discarded = discarded + 1 end
            end)
        end)
        while coroutine.status(task) ~= "dead" do
            local ok, err = coroutine.resume(task)
            assert(ok, err)
        end
        assert(outstanding == 0)
    ''')
    assert lua.globals().batches == expected_batches
    assert lua.globals().rendered == expected_renders
    assert lua.globals().discarded == (3 if cancel_at == 2 else 0)


def test_lua_exception_restores_catalogue(lua):
    lua.execute('fail_boost=true; ok,err=matte.exportMatteExisting(photo,"id","Mask","/out",{masksOnly=true})')
    assert lua.globals().ok is False
    assert lua.globals().photo.settings.Exposure2012 == 1
    assert lua.globals().restore_calls == 1


@pytest.mark.parametrize('delete_fails', [False, True])
def test_new_matte_removes_temporary_adjustments_before_color_render(lua, delete_fails):
    # Lightroom applyDevelopSettings restores globals but does not remove a
    # newly created AI mask absent from the saved settings (observed on Windows).
    lua.globals().delete_fails = delete_fails
    lua.execute('''
        local dc=import 'LrDevelopController'
        local masks={}
        dc.getAllMasks=function() return masks end
        dc.createNewMask=function()
            masks={{ID="temporary"}}; selected_id="temporary"
        end
        delete_calls=0; color_renders=0; contaminated_renders=0
        dc.deleteMask=function(id)
            delete_calls=delete_calls+1
            if delete_fails then error("injected delete failure") end
            masks={}
        end
        on_render=function(opts)
            if photo.settings.Exposure2012 == 1 then
                color_renders=color_renders+1
                if #masks > 0 then contaminated_renders=contaminated_renders+1 end
            end
        end
        ok,err=matte.exportMatte(photo,"subject","/out",{
            masksOnly=false,exportAlpha=true,enhancedDetection=true})
    ''')
    assert lua.globals().contaminated_renders == 0
    assert lua.globals().delete_calls == 1
    assert lua.globals().restore_calls == 1
    assert lua.globals().ok is not delete_fails, lua.globals().err
    assert lua.globals().color_renders == (0 if delete_fails else 2)


def test_lua_restore_lock_failure_is_reported(lua):
    lua.execute('abort_restore=true; ok,err,status=matte.exportMatteExisting(photo,"id","Mask","/out",{masksOnly=true})')
    assert lua.globals().ok is False
    assert lua.globals().status == "restore_failed"


def test_lua_original_kept_on_same_folder_export(lua):
    lua.execute('files["/photos/original.jpg"]=true; ok,err=matte.exportMatteExisting(photo,"id","Mask","/out",{masksOnly=false,imageOutputDir="/photos"})')
    assert lua.globals().ok is True, lua.globals().err
    assert lua.globals().files['/photos/original.jpg'] is True
    assert '/photos/original.jpg' not in lua.globals().deleted.values()
    assert lua.globals().files['/photos/original_2.jpg'] is True


def test_lua_individual_label_collision_keeps_every_mask(lua):
    lua.execute('count,failed=matte.exportMatteAllIndividual(photo,{{value="1",name="A"},{value="2",name="A"},{value="3",name="A_2"}},"/out",{masksOnly=true})')
    assert (lua.globals().count, lua.globals().failed) == (3, 0)
    outputs = [p for p in lua.globals().files.keys() if p.startswith('/out/') and p.endswith('.png')]
    assert len(outputs) == 3


def test_lua_unicode_and_exclusive_operations(lua):
    decoded = lua.globals().j.decode(json.dumps({'path': '/tmp/café_📷.png'}))[0]
    assert decoded['path'] == '/tmp/café_📷.png'
    lua.execute('first=utils.beginOperation("a"); second=utils.beginOperation("b"); utils.endOperation({}); busy=utils.isBusy(); utils.endOperation(first)')
    assert lua.globals().second is None
    assert lua.globals().busy is True
    assert lua.globals().utils.isBusy() is False


def test_lua_missing_alpha_is_not_success(lua):
    lua.execute('''
        local originalPost=utils.httpPost
        utils.httpPost=function(endpoint,data)
            if endpoint=="/merge-alpha" then return '{"status":"error","message":"not a success"}' end
            return originalPost(endpoint,data)
        end
        ok,err=matte.exportMatteExisting(photo,"id","Mask","/out",{masksOnly=true,exportAlpha=true})
    ''')
    assert lua.globals().ok is False
    assert 'alpha' in lua.globals().err.lower()
    assert lua.globals().photo.settings.Exposure2012 == 1


def test_lua_requires_recovery_snapshot_before_mutation(lua):
    lua.execute('''
        fail_snapshot=true; black_calls=0
        local originalApply=photo.applyDevelopSettings
        photo.applyDevelopSettings=function(self,settings,label)
            if label=="MaskBridge Matte Black" then black_calls=black_calls+1 end
            originalApply(self,settings,label)
        end
        ok=matte.exportMatteExisting(photo,"id","Mask","/out",{masksOnly=true})
    ''')
    assert lua.globals().ok is False
    assert lua.globals().black_calls == 0


def test_legacy_matte_keeps_master_and_copy_recovery_separate(lua):
    lua.execute('''
        family = {}
        function photo:createDevelopSnapshot(name, update)
            assert(update)
            family[name] = self.settings.Exposure2012
            return true
        end
        photo.localIdentifier = 41
        master_ok = matte.exportMatteExisting(photo,"id","Mask","/out",{masksOnly=true})
        photo.localIdentifier = 42
        photo.settings.Exposure2012 = 2
        copy_ok = matte.exportMatteExisting(photo,"id","Mask","/out",{masksOnly=true})
        abort_restore = true
        ok,err = matte.exportMatteExisting(photo,"id","Mask","/out",{masksOnly=true})
    ''')
    g = lua.globals()
    assert g.master_ok and g.copy_ok
    assert sorted(g.family.values()) == [1, 2]
    assert g.ok is False
    assert "[42]" in g.err  # Recovery message identifies the affected view.


def test_lua_individual_cancellation_stops_between_masks(lua):
    lua.execute('''
        local function canceled()
            for name in pairs(files) do
                if name:match("^/out/.*%.png$") then return true end
            end
            return false
        end
        count,failed=matte.exportMatteAllIndividual(photo,
            {{value="1",name="A"},{value="2",name="B"}},"/out",{masksOnly=true,isCanceled=canceled})
    ''')
    assert lua.globals().count == 1
    assert lua.globals().failed == 0
