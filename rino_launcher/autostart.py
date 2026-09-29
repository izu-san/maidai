"""Windows ログイン時の自動起動（HKCU の Run キー）。Qt 非依存。

登録するのはこのウィジェットの起動コマンドだけ。管理者権限は不要で、レジストリの
現在のユーザー領域以外には書き込まない。
"""
from __future__ import annotations

import sys
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "MaidAIWidget"
ROOT = Path(__file__).resolve().parent.parent


def build_command(python: str | None = None, root: Path = ROOT) -> str:
    """コンソールを出さず、作業ディレクトリに依存せずに `python -m rino_launcher` を起動するコマンド。"""
    exe = Path(python or sys.executable)
    if exe.name.lower() == "python.exe":
        candidate = exe.with_name("pythonw.exe")
        if candidate.exists():
            exe = candidate
    bootstrap = (
        f"import os,sys,runpy;os.chdir(r'{root}');sys.path.insert(0,r'{root}');"
        "runpy.run_module('rino_launcher',run_name='__main__',alter_sys=True)"
    )
    return f'"{exe}" -c "{bootstrap}"'


def is_enabled(key_path: str = RUN_KEY) -> bool:
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            value, _ = winreg.QueryValueEx(key, VALUE_NAME)
        return bool(value)
    except (ImportError, OSError):
        return False


def set_enabled(enabled: bool, key_path: str = RUN_KEY, command: str | None = None) -> None:
    import winreg

    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, command or build_command())
        else:
            try:
                winreg.DeleteValue(key, VALUE_NAME)
            except FileNotFoundError:
                pass
