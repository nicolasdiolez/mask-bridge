"""Mask Bridge is free and open source: no licence code, no call home.

The engine and the plugin must work without a key and without network access.
These guards keep the removed licensing system from creeping back in.
"""
import ast
import re
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
PLUGIN = BACKEND.parent
ROOT = PLUGIN.parent

LICENCE_MODULES = {"lemonsqueezy", "license_manager", "license_policy"}
# Hosts the old licensing and checkout code talked to.
LICENCE_HOSTS = ("lemonsqueezy", "api.lemonsqueezy.com")
# Client-side network modules. The local HTTP *server* and port probing use
# http.server and socket; neither opens an outbound connection.
NETWORK_CLIENTS = {"urllib.request", "http.client", "ssl", "requests", "certifi", "urllib3", "httpx"}


def backend_sources():
    return sorted(path for path in BACKEND.glob("*.py") if path.name != "build_info.py")


def imported_modules(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


def test_licence_modules_are_gone():
    for name in LICENCE_MODULES:
        assert not (BACKEND / f"{name}.py").exists(), name


def test_no_backend_module_imports_licence_code():
    for path in backend_sources():
        imports = imported_modules(path)
        assert not imports & LICENCE_MODULES, (path.name, imports & LICENCE_MODULES)
        assert not any(name.split(".")[0].startswith("license") for name in imports), path.name


def test_no_source_mentions_a_licence_host():
    sources = backend_sources() + sorted(PLUGIN.glob("*.lua")) + [ROOT / "maskbridge_engine.spec"]
    for path in sources:
        text = path.read_text(encoding="utf-8").lower()
        for host in LICENCE_HOSTS:
            assert host not in text, (path.name, host)


def test_server_runtime_has_no_network_client():
    # Everything the running engine imports for /process, /batch, /matte and
    # /merge-alpha. cli.py is excluded: its --download-models setup tool is the
    # one deliberate outbound connection, and the server never calls it.
    for name in ("server", "inference_engine", "validation", "atomic_io",
                 "runtime_paths", "dashboard_window"):
        imports = imported_modules(BACKEND / f"{name}.py")
        assert not imports & NETWORK_CLIENTS, (name, imports & NETWORK_CLIENTS)


def test_only_outbound_url_is_the_model_download():
    hosts = set()
    for path in backend_sources():
        hosts.update(re.findall(r"https?://([^/:\"'\s{}]+)", path.read_text(encoding="utf-8")))
    assert hosts <= {"127.0.0.1", "huggingface.co"}, hosts


def test_cli_has_no_licence_option():
    text = (BACKEND / "cli.py").read_text(encoding="utf-8")
    for option in ("--license", "--validate-license", "MASKBRIDGE_LICENSE"):
        assert option not in text, option


def test_spec_bundles_no_licence_module():
    spec = (ROOT / "maskbridge_engine.spec").read_text(encoding="utf-8")
    for name in LICENCE_MODULES:
        assert f"'{name}'" not in spec, name


def test_plugin_sends_no_key_and_calls_no_licence_endpoint():
    for path in sorted(PLUGIN.glob("*.lua")):
        text = path.read_text(encoding="utf-8")
        for needle in ("license_key", "licenseKey", "-license\"", "isStrictlyValid", "MASKBRIDGE_LICENSE"):
            assert needle not in text, (path.name, needle)


# --- "Support Mask Bridge" and the open-source notice (Lua 5.1 via lupa) -------

CONFIG = (PLUGIN / "MaskBridgeConfig.lua").read_text(encoding="utf-8")
DASHBOARD = (PLUGIN / "MaskBridgeDashboard.lua").read_text(encoding="utf-8")


def config_urls():
    return dict(re.findall(r'^MaskBridgeConfig\.(\w+_URL) = "([^"]*)"', CONFIG, re.M))


def test_config_points_to_support_source_and_contact():
    assert config_urls() == {
        "SUPPORT_URL": "https://nicolasdiolez.com/maskbridge",
        "SOURCE_URL": "https://github.com/nicolasdiolez/mask-bridge",
        "CONTACT_URL": "mailto:maskbridge@nicolasdiolez.com",
    }


def lua_with_sdk_stubs():
    lua = pytest.importorskip("lupa.lua51").LuaRuntime(unpack_returned_tuples=True)
    lua.globals().plugin_path = PLUGIN.as_posix()
    lua.execute('''
        opened = {}
        function LOC(s) return (s:gsub("^%$%$%$/[^=]*=", "")) end
        LrHttp = {openUrlInBrowser = function(url) opened[#opened + 1] = url end}
        MaskBridgeConfig = dofile(plugin_path .. "/MaskBridgeConfig.lua")
        f = setmetatable({}, {__index = function(_, kind)
            return function(_, spec) spec = spec or {}; spec.kind = kind; return spec end
        end})
    ''')
    return lua


def buttons(view, found=None):
    found = [] if found is None else found
    if hasattr(view, "values"):
        if view["kind"] == "push_button":
            found.append(view)
        for value in list(view.values()):
            if hasattr(value, "values"):
                buttons(value, found)
    return found


def test_dashboard_support_button_opens_the_support_page():
    lua = lua_with_sdk_stubs()
    start = DASHBOARD.index("                    -- Mask Bridge is free: one discreet way to support it.")
    end = DASHBOARD.index("                    -- Server Maintenance Controls (Discreet section)")
    column = lua.execute("return f:column {\n" + DASHBOARD[start:end] + "\n}")
    (button,) = buttons(column)
    assert button.title == "Support Mask Bridge"
    button.action()
    assert list(lua.globals().opened.values()) == ["https://nicolasdiolez.com/maskbridge"]


def test_plugin_manager_states_the_licence_and_links_source_and_support():
    lua = lua_with_sdk_stubs()
    lua.execute('''
        local stubs = {
            LrView = {bind = function(v) return v end},
            LrHttp = LrHttp,
            LrTasks = {startAsyncTask = function() end, pcall = pcall},
        }
        function import(name) return stubs[name] or {} end
        package.loaded["MaskBridgeUtils"] = {}
        package.loaded["MaskBridgeConfig"] = MaskBridgeConfig
        info = dofile(plugin_path .. "/MaskBridgeInfoProvider.lua")
    ''')
    sections = lua.globals().info.sectionsForTopOfDialog(lua.globals().f, lua.table())
    section = sections[1]
    texts = []

    def collect(view):
        if hasattr(view, "values"):
            if view["kind"] == "static_text" and isinstance(view["title"], str):
                texts.append(view["title"])
            for value in list(view.values()):
                collect(value)

    collect(section)
    assert "Free and open source (MIT licence)" in texts
    for button in buttons(section):
        if button.title in ("Source code", "Support Mask Bridge", "Contact support"):
            button.action()
    assert sorted(lua.globals().opened.values()) == sorted(config_urls().values())


# --- Translations ----------------------------------------------------------------

LANGUAGES = ("ar", "de", "en", "es", "fr", "it", "ja", "pt", "zh_Hans")
OPEN_SOURCE_KEYS = (
    "$$$/MaskBridge/Dashboard/SupportProject",
    "$$$/MaskBridge/Dashboard/Footer/Contact",
    "$$$/MaskBridge/Info/OpenSource",
    "$$$/MaskBridge/Info/SourceCode",
)


def translations(language):
    raw = (PLUGIN / f"TranslatedStrings_{language}.txt").read_bytes()
    # A Windows checkout (core.autocrlf) turns LF into CRLF; "$" must still match.
    text = raw.decode("utf-8-sig").replace("\r\n", "\n")
    return dict(re.findall(r'^"(\$\$\$/[^=]+)=(.*)"$', text, re.M))


def lua_keys():
    """(key, default) for every LOC string in the plugin, comments excluded."""
    found = {}
    for path in sorted(PLUGIN.glob("*.lua")):
        code = "\n".join(line for line in path.read_text(encoding="utf-8").splitlines()
                         if not line.lstrip().startswith("--"))
        for key, default in re.findall(r'"(\$\$\$/[^="]+)=([^"]*)"', code):
            found.setdefault(key, (path.name, default))
    return found


def test_every_key_the_lua_uses_exists_in_every_language():
    used = lua_keys()
    assert len(used) > 150  # the scan really sees the plugin's strings
    for language in LANGUAGES:
        missing = sorted(set(used) - set(translations(language)))
        assert not missing, (language, missing)


def test_no_language_keeps_licence_or_trial_strings():
    for language in LANGUAGES:
        stale = [key for key in translations(language)
                 if "/Licensing/" in key or "/Trial/" in key or key in (
                     "$$$/MaskBridge/Error/License", "$$$/MaskBridge/Error/LicenseRequired",
                     "$$$/MaskBridge/Error/InvalidKey", "$$$/MaskBridge/Error/ActivationLimit",
                     "$$$/MaskBridge/Info/LicenseActivated", "$$$/MaskBridge/Info/LicenseNone")]
        assert not stale, (language, stale)


def test_open_source_strings_are_translated_and_match_the_lua_defaults():
    english = translations("en")
    used = lua_keys()
    for key in OPEN_SOURCE_KEYS:
        assert used[key][1] == english[key], key
        for language in LANGUAGES:
            value = translations(language).get(key)
            assert value, (language, key)
            if language != "en" and key != "$$$/MaskBridge/Dashboard/Footer/Contact":
                assert value != english[key], (language, key)  # really translated
            if key == "$$$/MaskBridge/Info/OpenSource":
                assert "MIT" in value, language


# --- The package ships readable Lua ------------------------------------------------

def release_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location("release_open_source", ROOT / "tools/release/release.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def staged_plugin(release, directory):
    import json
    import shutil
    for path in PLUGIN.glob("*.lua"):
        shutil.copy2(path, directory / path.name)
    shutil.copy2(ROOT / "LICENSE", directory / "LICENSE.txt")
    manifest = {"lua": {path.name: release.sha(path) for path in PLUGIN.glob("*.lua")}}
    (directory / "release-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return directory


def test_package_verification_accepts_sources_and_refuses_bytecode(tmp_path, monkeypatch):
    release = release_module()
    monkeypatch.setattr(release, "MODEL_SHA256", {})  # models are checked elsewhere
    stage = staged_plugin(release, tmp_path)
    release.verify_package(stage)
    (stage / "._Info.lua").write_bytes(b"\x00\x05\x16\x07")  # AppleDouble record from ditto
    release.verify_package(stage)
    (stage / "MaskBridgeDashboard.luc").write_bytes(b"\x1bLuaQ")
    with pytest.raises(RuntimeError, match="Development artifact"):
        release.verify_package(stage)


def test_package_verification_refuses_lua_that_differs_from_the_manifest(tmp_path, monkeypatch):
    release = release_module()
    monkeypatch.setattr(release, "MODEL_SHA256", {})
    stage = staged_plugin(release, tmp_path)
    with (stage / "MaskBridgeDashboard.lua").open("a", encoding="utf-8") as stream:
        stream.write("\n-- edited after the manifest\n")
    with pytest.raises(RuntimeError, match="differ from the release manifest"):
        release.verify_package(stage)


def test_package_verification_requires_the_mit_notice(tmp_path, monkeypatch):
    release = release_module()
    monkeypatch.setattr(release, "MODEL_SHA256", {})
    stage = staged_plugin(release, tmp_path)
    (stage / "LICENSE.txt").unlink()
    with pytest.raises(RuntimeError, match="LICENSE.txt"):
        release.verify_package(stage)


def test_licence_text_is_mit_with_the_author():
    text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert text.startswith("MIT License\n\nCopyright (c) 2026 Nicolas Diolez\n")
    assert "THE SOFTWARE IS PROVIDED \"AS IS\"" in text


def test_packaging_only_syntax_checks_lua():
    source = (ROOT / "tools/release/release.py").read_text(encoding="utf-8")
    assert "check_lua51_syntax(path)" in source
    assert "luac" not in source
    assert "'-o'" not in source and "with_suffix('.luc')" not in source
    assert "MaskBridgeMatte.luc" not in source


def test_packaging_syntax_check_rejects_invalid_lua(tmp_path):
    pytest.importorskip("lupa.lua51")
    release = release_module()
    good = tmp_path / "Good.lua"
    good.write_text("local x = 1\nreturn x\n", encoding="utf-8")
    release.check_lua51_syntax(good)
    bad = tmp_path / "Bad.lua"
    bad.write_text("local x = = 1\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="Bad.lua"):
        release.check_lua51_syntax(bad)
    # Lua 5.2+ syntax that Lightroom's Lua 5.1 cannot load.
    goto = tmp_path / "Goto.lua"
    goto.write_text("goto done\n::done::\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="Goto.lua"):
        release.check_lua51_syntax(goto)


def test_repository_ships_no_prebuilt_compiler():
    assert not (ROOT / "tools" / "luac").exists()


def test_every_plugin_file_parses_as_lua51():
    lua = pytest.importorskip("lupa.lua51").LuaRuntime(unpack_returned_tuples=True)
    check = lua.eval("function(code, name) local chunk, err = loadstring(code, name); return err end")
    for path in sorted(PLUGIN.glob("*.lua")):
        assert check(path.read_text(encoding="utf-8"), path.name) is None, path.name
