"""Tests for path safety and for surviving a read-only plugin install.

Two P1 findings of the 10 August 2026 audit:

  - validate_path() compared an already-realpath()'d candidate against literal
    '/etc' and '/var'. macOS puts both behind /private symlinks, so the
    blocklist protected nothing on the product's main platform.
  - the port and token files were written with no guard at all, so a read-only
    plugin directory killed the server at startup.

The second class of test here matters as much as the first: the temp directory
lives *inside* the newly-blocked /var branch on macOS, and Preview and the
matte pipeline both stage their renders there. Closing the /etc hole must not
close those.
"""
import os
import stat
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import server
from validation import validate_path


class TestSensitiveDirsAreActuallyBlocked:
    @pytest.mark.parametrize('path', [
        '/etc/passwd', '/etc/hosts',
        '/System/Library/x.png',
        '/usr/bin/x', '/usr/local/lib/x',
        '/bin/sh', '/sbin/x',
        '/Library/LaunchDaemons/x.plist', '/Library/Keychains/System.keychain',
        os.path.join(os.path.expanduser('~'), '.ssh', 'id_rsa'),
        os.path.join(os.path.expanduser('~'), '.zshrc'),
    ])
    def test_rejected(self, path):
        with pytest.raises(ValueError, match='protected system directory'):
            validate_path(path, 'p')

    @pytest.mark.skipif(sys.platform != 'darwin', reason='/private is macOS-specific')
    @pytest.mark.parametrize('path', ['/private/etc/passwd', '/private/var/db/x'])
    def test_private_forms_rejected_too(self, path):
        """The symlink target must be blocked as directly as the symlink."""
        with pytest.raises(ValueError, match='protected system directory'):
            validate_path(path, 'p')

    @pytest.mark.skipif(sys.platform != 'darwin', reason='/etc symlink is macOS-specific')
    def test_the_exact_regression(self):
        """/etc/passwd resolves to /private/etc/passwd and used to sail through."""
        assert os.path.realpath('/etc') == '/private/etc'
        with pytest.raises(ValueError):
            validate_path('/etc/passwd', 'output')


class TestLegitimatePathsStillWork:
    """The half that would silently break the product if the fix overreached."""

    def test_system_temp_is_accepted(self):
        staged = os.path.join(tempfile.gettempdir(), 'maskbridge_preview_1', 'photo.jpg')
        assert validate_path(staged, 'image')

    def test_preview_and_matte_staging_dirs(self):
        """Exactly what the Dashboard and the matte pipeline pass in."""
        base = tempfile.gettempdir()
        for name in ('maskbridge_preview_123', 'maskbridge_matte_123',
                     'maskbridge_matte_ref_123'):
            assert validate_path(os.path.join(base, name, 'render.jpg'), 'input')

    @pytest.mark.skipif(sys.platform != 'darwin', reason='macOS temp layout')
    def test_var_folders_accepted_even_if_tmpdir_differs(self):
        """The allowance must not depend on this process inheriting Lightroom's TMPDIR."""
        assert validate_path('/var/folders/ab/T/maskbridge_preview_9/x.jpg', 'image')

    def test_system_wide_lightroom_modules_are_accepted(self):
        modules = '/Library/Application Support/Adobe/Lightroom/Modules/MaskBridge.lrplugin/backend/models'
        assert validate_path(modules) == os.path.realpath(modules)

    def test_user_directories(self):
        home = os.path.expanduser('~')
        for sub in ('Desktop/photo.jpg', 'Pictures/export/mask.png', 'Documents/x.tif'):
            assert validate_path(os.path.join(home, sub), 'output')


class TestPathValidationBasics:
    def test_null_byte(self):
        with pytest.raises(ValueError, match='Null byte'):
            validate_path('/tmp/evil\x00.png', 'p')

    @pytest.mark.parametrize('value', ['', None, 123, []])
    def test_empty_or_wrong_type(self, value):
        with pytest.raises(ValueError, match='Empty or invalid'):
            validate_path(value, 'p')


class TestReadOnlyInstallSurvives:
    @pytest.fixture
    def isolated_home(self, tmp_path, monkeypatch):
        """Never touch the real ~/Library/Application Support/MaskBridge."""
        monkeypatch.setenv('HOME', str(tmp_path / 'home'))
        monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'appdata'))
        monkeypatch.setenv('MASKBRIDGE_STATE_DIR', str(tmp_path / 'runtime'))
        return tmp_path

    def test_writable_dir_is_left_alone(self, tmp_path, isolated_home):
        if sys.platform == 'win32':
            assert server._runtime_state_dir(str(tmp_path)) == str(tmp_path / 'runtime')
        else:
            assert server._runtime_state_dir(str(tmp_path)) == str(tmp_path)

    def test_read_only_dir_falls_back(self, tmp_path, isolated_home, monkeypatch):
        ro = tmp_path / 'plugin'
        ro.mkdir()
        if sys.platform == 'win32':
            orig_access = os.access
            monkeypatch.setattr(os, 'access', lambda path, mode, *args, **kwargs: False if os.path.abspath(str(path)) == os.path.abspath(str(ro)) and mode == os.W_OK else orig_access(path, mode, *args, **kwargs))
        else:
            ro.chmod(0o500)
        try:
            state = server._runtime_state_dir(str(ro))
            assert state != str(ro)
            assert os.access(state, os.W_OK)
        finally:
            if sys.platform != 'win32':
                ro.chmod(0o700)

    def test_server_can_publish_from_the_fallback(self, tmp_path, isolated_home, monkeypatch):
        """The whole point: a read-only install must still announce itself."""
        ro = tmp_path / 'plugin'
        ro.mkdir()
        if sys.platform == 'win32':
            orig_access = os.access
            monkeypatch.setattr(os, 'access', lambda path, mode, *args, **kwargs: False if os.path.abspath(str(path)) == os.path.abspath(str(ro)) and mode == os.W_OK else orig_access(path, mode, *args, **kwargs))
        else:
            ro.chmod(0o500)
        try:
            state = server._runtime_state_dir(str(ro))
            token_file = server._write_auth_token(state)
            port_file = server._write_port_file(state, 9876)
            assert open(token_file).read()
            assert open(port_file).read() == '9876'
        finally:
            if sys.platform != 'win32':
                ro.chmod(0o700)

    @pytest.mark.skipif(sys.platform == 'win32', reason='Windows lacks POSIX file mode bits (0o600)')
    def test_token_is_owner_only_from_creation(self, tmp_path):
        """open()+chmod left the secret world-readable in between."""
        token_file = server._write_auth_token(str(tmp_path))
        assert stat.S_IMODE(os.stat(token_file).st_mode) == 0o600

    def test_token_is_fresh_each_run(self, tmp_path):
        first = open(server._write_auth_token(str(tmp_path))).read()
        second = open(server._write_auth_token(str(tmp_path))).read()
        assert first != second and len(first) >= 32
