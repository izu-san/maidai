"""MaidAI 起動ハブのデスクトップウィジェット（PySide6）。"""
from __future__ import annotations

import math
import sys

from PySide6.QtCore import QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QFont, QFontMetrics, QIcon, QPainter, QPixmap, QRadialGradient
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLayout,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from .runner import ScriptRunner
from .status_model import (
    PROFILES,
    ServiceStatus,
    build_action_args,
    build_profile_args,
    build_status_args,
    build_stop_all_args,
    parse_status,
)

POLL_MS = 5000
STATE_COLORS = {
    "running": "#3ddc97",
    "loading": "#ffc857",
    "stopped": "#5b6675",
    "missing": "#3a424d",
    "unavailable": "#ff6b6b",
}
STATE_LABELS = {
    "running": "起動中",
    "loading": "読込中",
    "stopped": "停止",
    "missing": "未作成",
    "unavailable": "利用不可",
}
ACTIONS = (("start", "▶", "起動"), ("stop", "■", "停止"), ("restart", "↻", "再起動"))
SECTIONS = (("process", "サービス"), ("container", "Docker"), ("project", "Docker"))

STYLE = """
* { font-family: "Segoe UI", "Yu Gothic UI", "Meiryo UI"; font-size: 12px; color: #e8edf3; }
QWidget { background: transparent; }
QFrame#card {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #1b212b, stop:1 #12161d);
    border: 1px solid rgba(255,255,255,26); border-radius: 14px;
}
QLabel#title { font-size: 15px; font-weight: 700; letter-spacing: 1px; }
QLabel#chip { background: rgba(255,255,255,14); border-radius: 9px; padding: 2px 10px; color: #b7c2d0; }
QLabel#section { color: #6f7d8f; font-size: 10px; font-weight: 700; }
QLabel#muted { color: #7d8a9b; }
QLabel#port { color: #7d8a9b; font-family: Consolas, "Cascadia Mono"; font-size: 11px; }
QFrame#row { border-radius: 8px; }
QFrame#row:hover { background: rgba(255,255,255,12); }
QFrame#sep { background: rgba(255,255,255,18); max-height: 1px; min-height: 1px; border: none; }
QPushButton { border: none; }
QPushButton#win, QPushButton#winclose { color: #8b98a9; border-radius: 6px; font-size: 14px; padding: 0; }
QPushButton#win:hover { background: rgba(255,255,255,20); color: #fff; }
QPushButton#winclose:hover { background: #e5484d; color: #fff; }
QPushButton#pill {
    background: rgba(110,168,254,26); color: #a9caff; border-radius: 13px; padding: 0 8px; font-weight: 600;
}
QPushButton#pill:hover { background: rgba(110,168,254,60); color: #fff; }
QPushButton#pill:pressed { background: rgba(110,168,254,90); }
QPushButton#danger {
    background: rgba(255,107,107,26); color: #ff9a9a; border-radius: 13px; padding: 0 12px; font-weight: 600;
}
QPushButton#danger:hover { background: rgba(255,107,107,70); color: #fff; }
QPushButton#act { background: rgba(255,255,255,10); color: #aab6c5; border-radius: 6px; font-size: 11px; }
QPushButton#act:disabled { background: transparent; color: #3b4450; }
QPushButton#act[role="start"]:hover { background: rgba(61,220,151,50); color: #3ddc97; }
QPushButton#act[role="stop"]:hover { background: rgba(255,107,107,50); color: #ff8f8f; }
QPushButton#act[role="restart"]:hover { background: rgba(255,200,87,50); color: #ffc857; }
QPushButton#link { color: #8b98a9; padding: 2px 6px; border-radius: 6px; }
QPushButton#link:hover, QPushButton#link:checked { background: rgba(255,255,255,18); color: #fff; }
QPlainTextEdit {
    background: rgba(0,0,0,70); border: 1px solid rgba(255,255,255,18); border-radius: 8px;
    color: #b7c2d0; font-family: Consolas, "Cascadia Mono"; font-size: 11px; padding: 4px;
}
QToolTip { background: #232a35; color: #e8edf3; border: 1px solid #3a4453; padding: 4px; }
"""


def _dot_icon(color: str) -> QIcon:
    pixmap = QPixmap(32, 32)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor(color))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(3, 3, 26, 26)
    painter.end()
    return QIcon(pixmap)


class StatusDot(QWidget):
    """状態ランプ。起動中は淡く発光し、読込中・処理中は脈動する。"""

    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(16, 16)
        self._state = "stopped"
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._tick)

    def set_state(self, state: str) -> None:
        if state == self._state:
            return
        self._state = state
        if state == "loading":
            self._timer.start()
        else:
            self._timer.stop()
            self._phase = 0.0
        self.update()

    def _tick(self) -> None:
        self._phase += 0.25
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(STATE_COLORS[self._state])
        center = QPointF(self.width() / 2, self.height() / 2)
        pulse = 0.5 + 0.5 * math.sin(self._phase) if self._state == "loading" else 1.0
        if self._state in ("running", "loading"):
            glow = QRadialGradient(center, 8)
            edge = QColor(color)
            edge.setAlpha(0)
            inner = QColor(color)
            inner.setAlpha(int(110 * pulse))
            glow.setColorAt(0.35, inner)
            glow.setColorAt(1.0, edge)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(glow)
            painter.drawEllipse(center, 8, 8)
        painter.setBrush(color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(center, 4.5, 4.5)


class ServiceRow(QFrame):
    def __init__(self, status: ServiceStatus, on_action) -> None:
        super().__init__()
        self.setObjectName("row")
        self.name = status.name
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 6, 4)
        layout.setSpacing(8)
        self.dot = StatusDot()
        self.title = QLabel(status.name)
        self.detail = QLabel()
        self.detail.setObjectName("port")
        layout.addWidget(self.dot)
        layout.addWidget(self.title, 1)
        layout.addWidget(self.detail)
        self.buttons: dict[str, QPushButton] = {}
        for action, glyph, tip in ACTIONS:
            button = QPushButton(glyph)
            button.setObjectName("act")
            button.setProperty("role", action)
            button.setToolTip(tip)
            button.setFixedSize(26, 24)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _=False, a=action: on_action(self.name, a))
            layout.addWidget(button)
            self.buttons[action] = button
        self.update_status(status, busy=False)

    def update_status(self, status: ServiceStatus, busy: bool) -> None:
        self.dot.set_state("loading" if busy else status.state)
        port = f":{status.port}" if status.port else ""
        label = "処理中…" if busy else STATE_LABELS[status.state]
        self.detail.setText(f"{label}  {port}".strip())
        self.setToolTip(f"{status.name} — {label}")
        usable = status.state not in ("unavailable", "missing") and not busy
        self.buttons["start"].setEnabled(usable and status.state != "running")
        self.buttons["stop"].setEnabled(usable and status.state not in ("stopped",))
        self.buttons["restart"].setEnabled(usable)


class LauncherWidget(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("MaidAI")
        self.setWindowFlags(
            Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(STYLE)
        self._drag: QPoint | None = None
        self._rows: dict[str, ServiceRow] = {}
        self._statuses: dict[str, ServiceStatus] = {}
        self._busy: set[str] = set()
        self.runner = ScriptRunner(self)
        self.runner.finished.connect(self._on_finished)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 10, 14, 18)  # ドロップシャドウ用の余白
        outer.setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)
        self.card = QFrame()
        self.card.setObjectName("card")
        self.card.setMinimumWidth(380)
        shadow = QGraphicsDropShadowEffect(self.card)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(0, 0, 0, 170))
        self.card.setGraphicsEffect(shadow)
        outer.addWidget(self.card)

        root = QVBoxLayout(self.card)
        root.setContentsMargins(14, 12, 14, 10)
        root.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel("MaidAI")
        title.setObjectName("title")
        self.chip = QLabel("取得中…")
        self.chip.setObjectName("chip")
        header.addWidget(title)
        header.addWidget(self.chip)
        header.addStretch(1)
        for text, name, tip, slot in (
            ("－", "win", "トレイへ格納", self.hide),
            ("×", "winclose", "ウィジェットを終了（サービスは停止しません）", QApplication.quit),
        ):
            button = QPushButton(text)
            button.setObjectName(name)
            button.setFixedSize(26, 24)
            button.setToolTip(tip)
            button.clicked.connect(slot)
            header.addWidget(button)
        root.addLayout(header)

        profiles = QHBoxLayout()
        profiles.setSpacing(6)
        for profile in PROFILES:
            button = QPushButton(profile)
            button.setObjectName("pill")
            button.setFixedHeight(26)
            button.setToolTip(f"プロファイル {profile} を起動")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _=False, p=profile: self.start_profile(p))
            profiles.addWidget(button, 1)
        stop_all = QPushButton("全停止")
        stop_all.setObjectName("danger")
        stop_all.setFixedHeight(26)
        stop_all.setCursor(Qt.CursorShape.PointingHandCursor)
        stop_all.clicked.connect(self.stop_all)
        profiles.addWidget(stop_all)
        root.addLayout(profiles)

        self.rows_layout = QVBoxLayout()
        self.rows_layout.setSpacing(1)
        root.addLayout(self.rows_layout)

        sep = QFrame()
        sep.setObjectName("sep")
        root.addWidget(sep)

        footer = QHBoxLayout()
        self.msg = QLabel("状態を取得中…")
        self.msg.setObjectName("muted")
        footer.addWidget(self.msg, 1)
        self.log_toggle = QPushButton("ログ")
        self.log_toggle.setObjectName("link")
        self.log_toggle.setCheckable(True)
        self.log_toggle.toggled.connect(self._toggle_log)
        copy = QPushButton("コピー")
        copy.setObjectName("link")
        copy.clicked.connect(self._copy_log)
        footer.addWidget(self.log_toggle)
        footer.addWidget(copy)
        root.addLayout(footer)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)  # 選択・コピー可能（Ctrl+C / 右クリック）
        self.log.setFixedHeight(120)
        self.log.setVisible(False)
        root.addWidget(self.log)

        self._build_tray()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(POLL_MS)
        self.refresh()

    # --- ログ ---
    def _set_log(self, text: str, error: bool = False) -> None:
        self.log.setPlainText(text)
        lines = text.strip().splitlines()
        first = lines[0] if lines else ""
        metrics = QFontMetrics(self.msg.font())
        self.msg.setText(metrics.elidedText(first, Qt.TextElideMode.ElideRight, 250))
        self.msg.setToolTip(text)
        self.msg.setStyleSheet("color:#ff8f8f;" if error else "")
        if error:
            self.log_toggle.setChecked(True)

    def _toggle_log(self, shown: bool) -> None:
        self.log.setVisible(shown)

    def _copy_log(self) -> None:
        QApplication.clipboard().setText(self.log.toPlainText() or self.msg.toolTip())

    # --- 操作 ---
    def refresh(self) -> None:
        self.runner.run("status", build_status_args())

    def do_action(self, name: str, action: str) -> None:
        try:
            args = build_action_args(name, action, set(self._statuses))
        except ValueError as exc:
            self._set_log(str(exc), error=True)
            return
        if self.runner.run(f"action:{name}", args):
            self._busy.add(name)
            self._set_log(f"{name}: {action} 実行中…")
            self._apply_statuses()

    def start_profile(self, profile: str) -> None:
        if self.runner.run(f"profile:{profile}", build_profile_args(profile)):
            self._set_log(f"プロファイル {profile} を起動中…")

    def stop_all(self) -> None:
        answer = QMessageBox.question(self, "MaidAI", "すべてのサービスを停止しますか？")
        if answer == QMessageBox.StandardButton.Yes and self.runner.run("stop-all", build_stop_all_args()):
            self._set_log("全停止中…")

    # --- 結果処理 ---
    def _on_finished(self, tag: str, code: int, out: str, err: str) -> None:
        if tag == "status":
            try:
                statuses = parse_status(out)
            except ValueError as exc:
                self._set_log(f"状態取得に失敗: {exc}\n{err.strip()}", error=True)
                return
            self._statuses = {s.name: s for s in statuses}
            self._apply_statuses()
            return
        if tag.startswith("action:"):
            self._busy.discard(tag.split(":", 1)[1])
        if code == 0:
            self._set_log(f"{tag}: 完了")
        else:
            self._set_log(f"{tag}: 失敗 (exit {code})\n{(err or out).strip()}", error=True)
        self.refresh()

    def _clear_rows(self) -> None:
        while self.rows_layout.count():
            item = self.rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._rows = {}

    def _apply_statuses(self) -> None:
        if set(self._rows) != set(self._statuses):
            self._clear_rows()
            shown: set[str] = set()
            for kind, caption in SECTIONS:
                members = [s for s in self._statuses.values() if s.kind == kind]
                if not members:
                    continue
                if caption not in shown:
                    label = QLabel(caption)
                    label.setObjectName("section")
                    font = label.font()
                    font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.5)
                    label.setFont(font)
                    label.setContentsMargins(8, 6, 0, 2)
                    self.rows_layout.addWidget(label)
                    shown.add(caption)
                for status in members:
                    row = ServiceRow(status, self.do_action)
                    self.rows_layout.addWidget(row)
                    self._rows[status.name] = row
        for name, status in self._statuses.items():
            self._rows[name].update_status(status, busy=name in self._busy)
        running = sum(1 for s in self._statuses.values() if s.state == "running")
        total = len(self._statuses)
        self.chip.setText(f"{running} / {total} 起動中")
        self.tray.setIcon(_dot_icon(STATE_COLORS["running" if running else "stopped"]))
        self.tray.setToolTip(f"MaidAI: {running}/{total} 起動中")
        if self.msg.toolTip() == "" or self.msg.text() == "状態を取得中…":
            self.msg.setText("")

    # --- トレイ ---
    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(_dot_icon(STATE_COLORS["stopped"]), self)
        menu = QMenu()
        menu.addAction(QAction("表示", self, triggered=self.show))
        for profile in PROFILES:
            menu.addAction(QAction(f"起動: {profile}", self, triggered=lambda _=False, p=profile: self.start_profile(p)))
        menu.addAction(QAction("全停止", self, triggered=self.stop_all))
        menu.addSeparator()
        menu.addAction(QAction("終了", self, triggered=QApplication.quit))
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: self.setVisible(not self.isVisible())
            if reason == QSystemTrayIcon.ActivationReason.Trigger
            else None
        )
        self.tray.show()

    # --- ドラッグ移動 ---
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self.windowHandle()
            if handle is not None and handle.startSystemMove():
                event.accept()
                return
            self._drag = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._drag is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, event) -> None:
        self._drag = None


def main() -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    widget = LauncherWidget()
    widget.show()
    return app.exec()
