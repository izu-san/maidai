import sys
import uuid
from pathlib import Path

import pytest

from rino_launcher import autostart

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows レジストリが必要")


def test_build_command_is_windowless_and_cwd_independent(tmp_path):
    python = tmp_path / "python.exe"
    pythonw = tmp_path / "pythonw.exe"
    python.write_text("")
    pythonw.write_text("")
    command = autostart.build_command(str(python), Path(r"D:\AI\MaidAI"))
    assert command.startswith(f'"{pythonw}"')
    assert "os.chdir(r'D:\\AI\\MaidAI')" in command
    assert "run_module('rino_launcher'" in command


def test_enable_disable_roundtrip_uses_isolated_key():
    key = rf"Software\MaidAI-Test\{uuid.uuid4().hex}\Run"
    try:
        assert not autostart.is_enabled(key)
        autostart.set_enabled(True, key, command="dummy")
        assert autostart.is_enabled(key)
        autostart.set_enabled(False, key)
        assert not autostart.is_enabled(key)
        autostart.set_enabled(False, key)  # 未登録でも例外にならない
    finally:
        import winreg

        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key.rsplit("\\", 1)[0])
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, r"Software\MaidAI-Test")
        except OSError:
            pass
