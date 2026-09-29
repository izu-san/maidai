"""MaidAI 起動ハブのデスクトップウィジェット（PySide6）。"""
from __future__ import annotations

import math
import sys
import time

from PySide6.QtCore import QPoint, QPointF, QSettings, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QColor, QDesktopServices, QFont, QFontMetrics, QIcon, QPainter, QPixmap, QRadialGradient
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
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from . import autostart
from .runner import ScriptRunner
from .status_model import (
    GPU_ARGS,
    PROFILES,
    ServiceStatus,
    build_action_args,
    build_profile_args,
    build_status_args,
    build_stop_all_args,
    detect_problems,
    format_elapsed,
    parse_gpu,
    parse_log_path,
    parse_status,
    profile_states,
)

POLL_MS = 5000
NOTIFY_QUIET_SECONDS = 10  # 操作の完了直後は、意図した停止を異常として通知しない
# "unhealthy" は状態 running のまま応答確認に失敗している、ウィジェット上の表示専用の状態
STATE_COLORS = {
    "running": "#3ddc97",
    "loading": "#ffc857",
    "stopped": "#5b6675",
    "missing": "#3a424d",
    "unavailable": "#ff6b6b",
    "unhealthy": "#ff9f43",
}
STATE_LABELS = {
    "running": "起動中",
    "loading": "読込中",
    "stopped": "停止",
    "missing": "未作成",
    "unavailable": "利用不可",
    "unhealthy": "応答異常",
}
PROFILE_LABELS = {"ready": "全て起動中", "partial": "一部のみ起動中", "off": "未起動"}
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
QPushButton#pill[fill="ready"] { background: rgba(61,220,151,46); color: #3ddc97; }
QPushButton#pill[fill="ready"]:hover { background: rgba(61,220,151,90); color: #fff; }
QPushButton#pill[fill="partial"] { background: rgba(255,200,87,40); color: #ffc857; }
QPushButton#pill[fill="partial"]:hover { background: rgba(255,200,87,80); color: #fff; }
QPushButton#tool { background: rgba(255,255,255,10); color: #8b98a9; border-radius: 6px; font-size: 12px; }
QPushButton#tool:hover { background: rgba(110,168,254,60); color: #fff; }
QPushButton#tool:disabled { background: transparent; color: #3b4450; }
QProgressBar { background: rgba(255,255,255,16); border: none; border-radius: 3px; max-height: 6px; min-height: 6px; }
QProgressBar::chunk { background: #3ddc97; border-radius: 3px; }
QProgressBar[level="warn"]::chunk { background: #ffc857; }
QProgressBar[level="high"]::chunk { background: #ff6b6b; }
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
        if self._state in ("running", "loading", "unhealthy"):
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
        # 状態・経過時間・ポートは固定幅の別ラベルにして、行が違っても縦の列を揃える
        self.state_label = self._column(52, Qt.AlignmentFlag.AlignRight)
        self.elapsed_label = self._column(66, Qt.AlignmentFlag.AlignRight)
        self.port_label = self._column(50, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.dot)
        layout.addWidget(self.title, 1)
        layout.addWidget(self.state_label)
        layout.addWidget(self.elapsed_label)
        layout.addWidget(self.port_label)
        self.buttons: dict[str, QPushButton] = {}
        # 補助ボタン（ブラウザで開く / ログを開く）。URL のない行も幅は確保して、ボタン列を揃える
        for action, glyph, tip in (("open", "↗", "ブラウザで開く"), ("log", "☰", "ログを開く")):
            button = QPushButton(glyph)
            button.setObjectName("tool")
            button.setToolTip(tip)
            button.setFixedSize(24, 24)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _=False, a=action: on_action(self.name, a))
            policy = button.sizePolicy()
            policy.setRetainSizeWhenHidden(True)
            button.setSizePolicy(policy)
            layout.addWidget(button)
            self.buttons[action] = button
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

    @staticmethod
    def _column(width: int, align: Qt.AlignmentFlag) -> QLabel:
        label = QLabel()
        label.setObjectName("port")
        label.setFixedWidth(width)
        label.setAlignment(align | Qt.AlignmentFlag.AlignVCenter)
        return label

    def update_status(self, status: ServiceStatus, busy: bool) -> None:
        unhealthy = status.state == "running" and status.health == "fail"
        shown = "loading" if busy else ("unhealthy" if unhealthy else status.state)
        self.dot.set_state(shown)
        port = f":{status.port}" if status.port else ""
        label = "処理中…" if busy else STATE_LABELS[shown]
        started = status.started_at
        # 稼働中は経過時間、停止中の container は「最終起動」の相対時刻を併記する
        elapsed = format_elapsed(started) if started and status.state in ("running", "loading") else ""
        self.state_label.setText(label)
        self.elapsed_label.setText(elapsed)
        self.port_label.setText(port)
        tip = f"{status.name} — {label}"
        if started:
            local = started.astimezone().strftime("%Y-%m-%d %H:%M:%S")
            tip += f"\n最終起動: {local}（{format_elapsed(started)}前）"
        if unhealthy:
            tip += "\nポートは開いていますが、応答確認に失敗しています"
        self.setToolTip(tip)
        usable = status.state not in ("unavailable", "missing") and not busy
        self.buttons["open"].setVisible(status.open_url is not None)
        self.buttons["open"].setEnabled(status.state == "running")
        self.buttons["log"].setEnabled(status.state not in ("unavailable", "missing"))
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
        self._previous: dict[str, ServiceStatus] | None = None  # 異常通知の比較基準（初回は None）
        self._quiet_until = 0.0
        self._gpu_available = True
        self._pills: dict[str, QPushButton] = {}
        self._settings = QSettings("MaidAI", "Launcher")
        self._restoring = True
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(500)
        self._save_timer.timeout.connect(self._save_position)
        self.runner = ScriptRunner(self)
        self.runner.finished.connect(self._on_finished)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 10, 14, 18)  # ドロップシャドウ用の余白
        outer.setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)
        self.card = QFrame()
        self.card.setObjectName("card")
        self.card.setMinimumWidth(470)
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
            self._pills[profile] = button
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

        # GPU（VRAM）使用状況。nvidia-smi が使えない環境では非表示のまま
        self.gpu_box = QWidget()
        gpu_layout = QHBoxLayout(self.gpu_box)
        gpu_layout.setContentsMargins(8, 0, 6, 0)
        gpu_layout.setSpacing(8)
        gpu_caption = QLabel("VRAM")
        gpu_caption.setObjectName("section")
        self.gpu_bar = QProgressBar()
        self.gpu_bar.setTextVisible(False)
        self.gpu_bar.setRange(0, 1000)
        self.gpu_bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.gpu_text = QLabel()
        self.gpu_text.setObjectName("port")
        gpu_layout.addWidget(gpu_caption)
        gpu_layout.addWidget(self.gpu_bar, 1)
        gpu_layout.addWidget(self.gpu_text)
        self.gpu_box.setVisible(False)
        root.addWidget(self.gpu_box)

        footer = QHBoxLayout()
        self.msg = QLabel("状態を取得中…")
        self.msg.setObjectName("muted")
        footer.addWidget(self.msg, 1)
        self.autostart_toggle = QPushButton("自動起動")
        self.autostart_toggle.setObjectName("link")
        self.autostart_toggle.setCheckable(True)
        self.autostart_toggle.setToolTip("Windows へのログイン時にこのウィジェットを自動で起動する")
        self.autostart_toggle.setChecked(autostart.is_enabled())
        self.autostart_toggle.toggled.connect(self._toggle_autostart)
        self.log_toggle = QPushButton("ログ")
        self.log_toggle.setObjectName("link")
        self.log_toggle.setCheckable(True)
        self.log_toggle.toggled.connect(self._toggle_log)
        copy = QPushButton("コピー")
        copy.setObjectName("link")
        copy.clicked.connect(self._copy_log)
        footer.addWidget(self.autostart_toggle)
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
        self._restore_position()
        self._restoring = False
        QApplication.instance().aboutToQuit.connect(self._save_position)

    # --- 位置の保存・復元 ---
    def _restore_position(self) -> None:
        pos = self._settings.value("position")
        if not isinstance(pos, QPoint):
            return
        self.adjustSize()
        rect = self.frameGeometry()
        rect.moveTopLeft(pos)
        # 保存位置がどのモニターにも十分入らない場合（モニター構成の変更）は既定位置のままにする
        for screen in QApplication.screens():
            visible = screen.availableGeometry().intersected(rect)
            if visible.width() >= 80 and visible.height() >= 40:
                self.move(pos)
                return

    def _save_position(self) -> None:
        self._settings.setValue("position", self.pos())
        self._settings.sync()

    def moveEvent(self, event) -> None:
        # startSystemMove ではマウス解放イベントが届かないため、移動後に間引いて保存する
        super().moveEvent(event)
        if not self._restoring:
            self._save_timer.start()

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

    def _toggle_autostart(self, enabled: bool) -> None:
        try:
            autostart.set_enabled(enabled)
        except OSError as exc:
            self.autostart_toggle.blockSignals(True)
            self.autostart_toggle.setChecked(not enabled)
            self.autostart_toggle.blockSignals(False)
            self._set_log(f"自動起動の設定に失敗: {exc}", error=True)
            return
        self._set_log("自動起動を有効にしました" if enabled else "自動起動を無効にしました")

    # --- 操作 ---
    def refresh(self) -> None:
        self.runner.run("status", build_status_args())
        if self._gpu_available:
            self.runner.run("gpu", GPU_ARGS, program="nvidia-smi")

    def do_action(self, name: str, action: str) -> None:
        if action == "open":
            status = self._statuses.get(name)
            if status is not None and status.open_url:
                QDesktopServices.openUrl(QUrl(status.open_url))
            return
        if action == "log":
            try:
                args = build_action_args(name, action, set(self._statuses))
            except ValueError as exc:
                self._set_log(str(exc), error=True)
                return
            self.runner.run(f"log:{name}", args)  # busy 表示は付けない（ログを開くだけ）
            return
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
            self._notify_problems()
            self._apply_statuses()
            return
        if tag == "gpu":
            self._apply_gpu(code, out)
            return
        if tag.startswith("log:"):
            self._open_log(tag.split(":", 1)[1], code, out, err)
            return
        # 起動・停止の完了直後は、意図した停止を異常として通知しない
        self._quiet_until = time.monotonic() + NOTIFY_QUIET_SECONDS
        if tag.startswith("action:"):
            self._busy.discard(tag.split(":", 1)[1])
        if code == 0:
            self._set_log(f"{tag}: 完了")
        else:
            self._set_log(f"{tag}: 失敗 (exit {code})\n{(err or out).strip()}", error=True)
        self.refresh()

    def _notify_problems(self) -> None:
        """前回から新たに停止・応答異常になったサービスをトレイ通知する（操作中・直後は除く）。"""
        current = self._statuses
        operating = any(
            tag not in ("status", "gpu") and not tag.startswith("log:") for tag in self.runner.active_tags()
        )
        if operating or time.monotonic() < self._quiet_until:
            self._previous = current  # 意図した変化は基準だけ更新して通知しない
            return
        messages = detect_problems(self._previous, current)
        self._previous = current
        if messages:
            text = "\n".join(messages)
            self.tray.showMessage("MaidAI", text, QSystemTrayIcon.MessageIcon.Warning, 8000)
            self._set_log(text, error=True)

    def _apply_gpu(self, code: int, out: str) -> None:
        if code == -1:  # nvidia-smi が見つからない・起動できない環境では以後取得しない
            self._gpu_available = False
            self.gpu_box.setVisible(False)
            return
        info = parse_gpu(out) if code == 0 else None
        self.gpu_box.setVisible(info is not None)
        if info is None or info.total_mb <= 0:
            return
        ratio = info.used_mb / info.total_mb
        self.gpu_bar.setValue(int(ratio * 1000))
        self.gpu_bar.setProperty("level", "high" if ratio >= 0.9 else "warn" if ratio >= 0.75 else "ok")
        self.gpu_bar.style().unpolish(self.gpu_bar)
        self.gpu_bar.style().polish(self.gpu_bar)
        self.gpu_text.setText(f"{info.used_mb / 1024:.1f} / {info.total_mb / 1024:.1f} GB · {info.util_percent}%")
        self.gpu_box.setToolTip(f"{info.name}\nVRAM 使用 {info.used_mb} / {info.total_mb} MiB、GPU 使用率 {info.util_percent}%")

    def _open_log(self, name: str, code: int, out: str, err: str) -> None:
        if code != 0:
            self._set_log(f"{name}: ログを取得できません\n{(err or out).strip()}", error=True)
            return
        path = parse_log_path(out)
        if path is None:
            self._set_log(f"{name}: ログの場所を確認できませんでした", error=True)
            return
        # 関連付けがなく開けない場合は、ログの置き場所のフォルダを開く
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))
        self._set_log(f"{name}: ログを開きました\n{path}")

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
        for profile, fill in profile_states(list(self._statuses.values())).items():
            pill = self._pills[profile]
            if pill.property("fill") != fill:
                pill.setProperty("fill", fill)
                pill.style().unpolish(pill)
                pill.style().polish(pill)
            pill.setToolTip(f"プロファイル {profile} を起動（現在: {PROFILE_LABELS[fill]}）")
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
