"""Start-MaidAI.ps1 を非同期に実行する薄いラッパー。"""
from __future__ import annotations

from PySide6.QtCore import QObject, QProcess, Signal

CREATE_NO_WINDOW = 0x08000000


def _decode(data: bytes) -> str:
    for encoding in ("utf-8", "mbcs"):
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")


class ScriptRunner(QObject):
    """タグ単位で powershell.exe を起動し、完了時に (tag, exit_code, stdout, stderr) を通知する。"""

    finished = Signal(str, int, str, str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._running: dict[str, QProcess] = {}

    def is_running(self, tag: str) -> bool:
        return tag in self._running

    def active_tags(self) -> set[str]:
        return set(self._running)

    def run(self, tag: str, args: list[str], program: str = "powershell.exe") -> bool:
        if tag in self._running:
            return False
        process = QProcess(self)
        try:
            process.setCreateProcessArgumentsModifier(
                lambda modifier: setattr(modifier, "flags", modifier.flags | CREATE_NO_WINDOW)
            )
        except AttributeError:
            pass  # 非 Windows / 古い PySide6
        process.finished.connect(lambda code, _status, t=tag: self._guarded(self._on_finished, t, code))
        process.errorOccurred.connect(lambda _err, t=tag: self._guarded(self._on_error, t))
        self._running[tag] = process
        process.start(program, args)
        return True

    @staticmethod
    def _guarded(handler, *args) -> None:
        try:
            handler(*args)
        except RuntimeError:
            pass  # アプリ終了処理中に QProcess が破棄済み

    def _on_finished(self, tag: str, code: int) -> None:
        process = self._running.pop(tag, None)
        if process is None:
            return
        out = _decode(bytes(process.readAllStandardOutput()))
        err = _decode(bytes(process.readAllStandardError()))
        process.deleteLater()
        self.finished.emit(tag, code, out, err)

    def _on_error(self, tag: str) -> None:
        process = self._running.get(tag)
        if process is not None and process.state() == QProcess.ProcessState.NotRunning:
            # 起動失敗時は finished が来ないためここで通知する
            self._running.pop(tag, None)
            message = process.errorString()
            process.deleteLater()
            self.finished.emit(tag, -1, "", message)
