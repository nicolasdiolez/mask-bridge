"""Windows acceptance run of 15 October 2026: what the user is told after a batch.

- A photo with no object of the checked classes still gets its (empty) mask,
  but it is counted apart: "N masks generated" only counts masks with a subject.
- Engine warnings are stable codes, worded by the plugin in the Lightroom
  language instead of English text from the engine.
"""
import os
import re
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import inference_engine
from inference_engine import MaskBridgeEngine

PLUGIN = Path(__file__).resolve().parents[2]
SOURCE = (PLUGIN / "MaskBridgeDashboard.lua").read_text(encoding="utf-8")
LANGUAGES = ("ar", "de", "en", "es", "fr", "it", "ja", "pt", "zh_Hans")
CODES = {"no_detection", "unknown_classes", "fine_detail_unavailable"}
ENGINE_RESULT = SOURCE[SOURCE.index("local EngineResult = {}"):SOURCE.index("local function saveSettings(")]


def lua_runtime():
    """Lua 5.1 with the SDK pieces the Dashboard's result handling touches."""
    lua = pytest.importorskip("lupa.lua51").LuaRuntime(unpack_returned_tuples=True)
    lua.globals().plugin_path = PLUGIN.as_posix()
    lua.execute('''
        json = dofile(plugin_path .. "/dkjson.lua")
        function LOC(s, a) local text = s:gsub("^%$%$%$/[^=]*=", "")
            return (text:gsub("%^1", tostring(a))) end
        function logMsg() end
        posts = {}; replies = {}
        MaskBridgeUtils = {
            isServerRunning = function() return true end,
            httpPost = function(endpoint, body)
                posts[#posts + 1] = {endpoint = endpoint, body = json.decode(body)}
                local reply = replies[endpoint]
                if type(reply) == "function" then reply = reply(json.decode(body)) end
                return reply and json.encode(reply)
            end,
        }
    ''')
    return lua, lua.execute(ENGINE_RESULT + "\nreturn EngineResult")


# --- Engine -------------------------------------------------------------------

class _Port:
    def __init__(self, name):
        self.name = name


class FakeRfDetr:
    """RF-DETR Medium output contract: dets (200, 4), labels (200, 91) logits,
    masks (200, 108, 108) logits. One query can carry a confident person."""

    def __init__(self, person=False):
        self.labels = np.full((1, 200, 91), -20.0, dtype=np.float32)
        self.masks = np.full((1, 200, 108, 108), -20.0, dtype=np.float32)
        if person:
            self.labels[0, 0, 1] = 10.0           # 91-class index 1 = person
            self.masks[0, 0, 30:80, 40:70] = 20.0

    def get_inputs(self):
        return [_Port("input")]

    def get_outputs(self):
        return [_Port("dets"), _Port("labels"), _Port("masks")]

    def run(self, _names, _feeds):
        return [np.zeros((1, 200, 4), dtype=np.float32), self.labels, self.masks]


def engine_with(session):
    engine = MaskBridgeEngine("/nonexistent")
    engine.session = session
    engine._models_loaded = True
    return engine


@pytest.fixture
def photo(tmp_path):
    path = tmp_path / "photo.jpg"
    cv2.imwrite(str(path), np.full((120, 160, 3), 128, dtype=np.uint8))
    return path


def test_no_detection_writes_the_empty_mask_and_reports_a_code(photo, tmp_path):
    output = tmp_path / "photo_mask.png"
    result = engine_with(FakeRfDetr()).process_image(str(photo), str(output), ["person"])
    assert result["detections"] == 0
    assert result["warnings"] == [inference_engine.WARNING_NO_DETECTION] == ["no_detection"]
    # Still written: File > Export keeps its rendition, the CLI still exits 0.
    mask = cv2.imread(str(output), cv2.IMREAD_GRAYSCALE)
    assert mask is not None and mask.shape == (120, 160) and mask.max() == 0


def test_detection_reports_no_warning(photo, tmp_path):
    output = tmp_path / "photo_mask.png"
    result = engine_with(FakeRfDetr(person=True)).process_image(str(photo), str(output), ["person"])
    assert result["detections"] == 1 and result["warnings"] == []
    assert cv2.imread(str(output), cv2.IMREAD_GRAYSCALE).max() == 255


def test_unknown_classes_are_a_code_with_the_names_apart(photo, tmp_path):
    result = engine_with(FakeRfDetr(person=True)).process_image(
        str(photo), str(tmp_path / "m.png"), ["person", "unicornzz"])
    assert result["warnings"] == ["unknown_classes"]
    assert result["ignored_classes"] == ["unicornzz"]


def test_unavailable_fine_detail_is_a_code(photo, tmp_path, monkeypatch):
    engine = engine_with(FakeRfDetr(person=True))
    monkeypatch.setattr(engine, "_load_birefnet_locked", lambda: False)
    result = engine.process_image(str(photo), str(tmp_path / "m.png"), ["person"], birefnet_refine=True)
    assert result["warnings"] == ["fine_detail_unavailable"]
    assert result["mode_applied"] == "standard"


def test_every_engine_warning_is_a_code_the_plugin_words():
    codes = {value for name, value in vars(inference_engine).items() if name.startswith("WARNING_")}
    assert codes == CODES
    lua, engine_result = lua_runtime()
    words = engine_result.warningText
    for code in codes:
        assert words(code, lua.table_from({"ignored_classes": lua.table_from(["x"])})) != code


# --- Translations ---------------------------------------------------------------

NEW_KEYS = (
    "$$$/MaskBridge/Warning/NoDetection",
    "$$$/MaskBridge/Warning/UnknownClasses",
    "$$$/MaskBridge/Warning/FineDetailUnavailable",
    "$$$/MaskBridge/Processing/EmptyMasks",
)


def translations(language):
    raw = (PLUGIN / f"TranslatedStrings_{language}.txt").read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf"), f"{language}: UTF-8 BOM missing"
    # A Windows checkout (core.autocrlf) turns LF into CRLF; "$" must still match.
    text = raw.decode("utf-8-sig").replace("\r\n", "\n")
    return dict(re.findall(r'^"(\$\$\$/[^=]+)=(.*)"$', text, re.M))


def test_every_language_has_the_same_keys_and_the_new_ones():
    english = translations("en")
    for key in NEW_KEYS:
        assert key in english
    for language in LANGUAGES:
        strings = translations(language)
        assert set(strings) == set(english), language
        for key in NEW_KEYS:
            # Same placeholders as the English text.
            assert sorted(re.findall(r"\^\d", strings[key])) == sorted(re.findall(r"\^\d", english[key])), (language, key)


def test_lua_defaults_match_the_english_file():
    english = translations("en")
    for key in NEW_KEYS:
        match = re.search(re.escape(key) + r'=([^"]*)"', SOURCE)
        assert match and match.group(1) == english[key], key


# --- Dashboard: counting and wording (Lua 5.1 via lupa) ---------------------------

PROCESS = SOURCE[SOURCE.index("                local function processRendered("):
                 SOURCE.index("                -- Progress is driven by completions, not by submission order:")]


def batch_runtime():
    lua, engine_result = lua_runtime()
    lua.globals().EngineResult = engine_result
    lua.execute('''
        props = {am_export_alpha = false, am_masks_only = false}
        prompts = {"person"}
        processedCount, emptyCount, failedCount, alphaCount = 0, 0, 0, 0
        failedDetails, warnings = {}, {}
        deleted = {}
        LrPathUtils = {
            parent = function(p) return (p:match("^(.*)/[^/]*$")) end,
            leafName = function(p) return (p:match("([^/]*)$")) end,
            removeExtension = function(p) return (p:gsub("%.[^.]*$", "")) end,
        }
        LrFileUtils = {exists = function() return true end, delete = function(p) deleted[#deleted + 1] = p end}
        MaskBridgeUtils.NAMING_STANDARD = "standard"
        MaskBridgeUtils.getMaskPath = function(dir, stem) return dir .. "/" .. stem .. "_mask.png" end
        MaskBridgeUtils.uniqueOutputPath = function(p) return p end
        MaskBridgeUtils.getServerPort = function() return 1 end
        function isServerRunning() return true end
        function buildProcessPayload(_, _, image) return json.encode({image = image}) end
        function httpPost(endpoint, body) return MaskBridgeUtils.httpPost(endpoint, body) end
        progressScope = {setCaption = function() end, cancel = function() end}
    ''')
    run = lua.execute(PROCESS + "\nreturn processRendered")
    return lua, run


def test_photo_without_detection_is_not_counted_as_a_generated_mask():
    lua, run = batch_runtime()
    lua.execute('''replies["/process"] = function(body)
        if body.image:find("empty") then
            return {status = "success", detections = 0, warnings = {"no_detection"}}
        end
        return {status = "success", detections = 2, warnings = {}}
    end''')
    run("/out/full.jpg", 1)
    run("/out/empty.jpg", 2)
    g = lua.globals()
    assert g.processedCount == 1 and g.emptyCount == 1 and g.failedCount == 0
    assert list(g.warnings.values()) == ["empty — No object of the selected classes was detected."]
    assert g.deleted[1] is None                   # the empty photo keeps its render and mask


def test_empty_mask_with_failed_alpha_is_one_failure_not_a_negative_count():
    lua, run = batch_runtime()
    lua.execute('''props.am_export_alpha = true
        replies["/process"] = {status = "success", detections = 0, warnings = {"no_detection"}}
        replies["/merge-alpha"] = {status = "error"}''')
    run("/out/empty.jpg", 1)
    g = lua.globals()
    assert g.processedCount == 0 and g.emptyCount == 0 and g.failedCount == 1


def test_engine_codes_are_worded_by_the_plugin():
    lua, run = batch_runtime()
    lua.execute('''replies["/process"] = {status = "success", detections = 1,
        warnings = {"unknown_classes", "fine_detail_unavailable", "future_code"},
        ignored_classes = {"unicornzz", "dragon"}}''')
    run("/out/a.jpg", 1)
    assert list(lua.globals().warnings.values()) == [
        "a — Unknown classes ignored: unicornzz, dragon",
        "a — HD unavailable for this photo: standard mask kept.",
        "a — future_code",
    ]
    assert lua.globals().processedCount == 1


def test_empty_line_and_empty_result():
    lua, api = lua_runtime()
    assert api.emptyLine(3) == "3 photo(s) with no object detected (mask saved without a subject)."
    assert api.isEmpty(lua.table_from({"detections": 0})) is True
    assert api.isEmpty(lua.table_from({"detections": 4})) is False
    assert api.isEmpty(lua.table_from({})) is False   # CLI-style answer without a count
