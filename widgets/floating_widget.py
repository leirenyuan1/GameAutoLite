"""
悬浮状态卡片 (widgets/floating_widget.py)
"""
from __future__ import annotations
from typing import TYPE_CHECKING

import ctypes

from PyQt6.QtCore import Qt, QRect, QPoint, QPropertyAnimation, QEasingCurve
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QPushButton, QSizePolicy, QMenu,
)

from styles.colors import (
    CLR_CARD_BG, CLR_CARD_BORDER, CLR_TEXT_SUB,
    CLR_BTN_SUCCESS, CLR_BTN_DANGER,
)

if TYPE_CHECKING:
    from main_window import MainWindow


class FloatingWidget(QWidget):
    """悬浮状态卡片，支持最小化时显示和始终显示两种模式。"""

    def __init__(self, main_window: 'MainWindow'):
        super().__init__()
        self._main_win = main_window
        self._drag_pos = None
        self._last_pos = None
        self._fade_anim = None
        self._interactive = True  # 是否可交互
        self._setup_ui()

    def _setup_ui(self):
        """构建 UI：3行状态 + 分隔线 + 启停按钮"""
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(200)

        container = QWidget(self)
        container.setObjectName("floatingContainer")
        container.setStyleSheet(f"""
            #floatingContainer {{
                background: {CLR_CARD_BG};
                border: 1px solid {CLR_CARD_BORDER};
                border-radius: 12px;
            }}
        """)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(container)

        layout = QVBoxLayout(container)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        self.status_icon1, self.status_line1 = self._make_row(layout, "⚡", "就绪")
        self.status_icon2, self.status_line2 = self._make_row(layout, "🖱", "—")
        self.status_icon3, self.status_line3 = self._make_row(layout, "⏱", "—")

        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background: {CLR_CARD_BORDER};")
        layout.addWidget(line)

        self.btn_toggle = QPushButton("▶ 开始")
        self.btn_toggle.setFixedHeight(36)
        self.btn_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_toggle.setStyleSheet(f"""
            QPushButton {{
                background: {CLR_BTN_SUCCESS}; color: #fff; border: none;
                border-radius: 8px; font-size: 13px; font-weight: bold;
            }}
            QPushButton:hover {{ background: #66BB6A; }}
        """)
        self.btn_toggle.clicked.connect(self._on_toggle_clicked)
        layout.addWidget(self.btn_toggle)

    def _make_row(self, parent_layout, icon_text, line_text):
        """创建一行状态显示"""
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)

        icon_lbl = QLabel(icon_text)
        icon_lbl.setFixedWidth(18)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setStyleSheet(f"font-size: 13px; color: {CLR_TEXT_SUB};")

        text_lbl = QLabel(line_text)
        text_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        text_lbl.setStyleSheet(f"font-size: 13px; color: {CLR_TEXT_SUB};")

        row.addWidget(icon_lbl)
        row.addWidget(text_lbl)
        parent_layout.addLayout(row)
        return icon_lbl, text_lbl

    def sync_from_sidebar(self, sb):
        """从 SideBar 同步所有状态（文本 + 颜色）"""
        self.status_icon1.setText(sb.status_icon1.text())
        self.status_icon1.setStyleSheet(sb.status_icon1.styleSheet())
        self.status_line1.setText(sb.status_line1.text())
        self.status_line1.setStyleSheet(sb.status_line1.styleSheet())

        self.status_icon2.setText(sb.status_icon2.text())
        self.status_icon2.setStyleSheet(sb.status_icon2.styleSheet())
        self.status_line2.setText(sb.status_line2.text())
        self.status_line2.setStyleSheet(sb.status_line2.styleSheet())

        self.status_icon3.setText(sb.status_icon3.text())
        self.status_icon3.setStyleSheet(sb.status_icon3.styleSheet())
        self.status_line3.setText(sb.status_line3.text())
        self.status_line3.setStyleSheet(sb.status_line3.styleSheet())

        self.btn_toggle.setText(sb.btn_toggle.text())
        self._sync_button_style()

    def _sync_button_style(self):
        """根据按钮文字更新样式"""
        if "停止" in self.btn_toggle.text():
            self.btn_toggle.setStyleSheet(f"""
                QPushButton {{
                    background: {CLR_BTN_DANGER}; color: #fff; border: none;
                    border-radius: 8px; font-size: 13px; font-weight: bold;
                }}
                QPushButton:hover {{ background: #E53935; }}
            """)
        else:
            self.btn_toggle.setStyleSheet(f"""
                QPushButton {{
                    background: {CLR_BTN_SUCCESS}; color: #fff; border: none;
                    border-radius: 8px; font-size: 13px; font-weight: bold;
                }}
                QPushButton:hover {{ background: #66BB6A; }}
            """)

    def set_interactive(self, enabled: bool) -> None:
        """设置是否可交互（使用 WS_EX_TRANSPARENT 实现真正的鼠标穿透）"""
        import ctypes
        hwnd = int(self.winId())
        GWL_EXSTYLE = -20
        WS_EX_TRANSPARENT = 0x00000020
        WS_EX_LAYERED = 0x00080000
        SWP_FRAMECHANGED = 0x0020
        SWP_NOACTIVATE = 0x0010
        SWP_NOMOVE = 0x0002
        SWP_NOSIZE = 0x0001
        SWP_NOZORDER = 0x0004
        HWND_TOPMOST = -1

        style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        if enabled:
            # 恢复正常模式：接收输入事件
            style &= ~WS_EX_TRANSPARENT
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self.btn_toggle.setEnabled(True)
        else:
            # 穿透模式：鼠标事件穿透到下层窗口（包括游戏窗口）
            style |= WS_EX_TRANSPARENT | WS_EX_LAYERED
            self.btn_toggle.setEnabled(False)

        ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
        # 刷新窗口使样式生效
        ctypes.windll.user32.SetWindowPos(
            hwnd, HWND_TOPMOST, 0, 0, 0, 0,
            SWP_FRAMECHANGED | SWP_NOACTIVATE | SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER
        )
        self._interactive = enabled

    def _stop_running_anim(self):
        """停止正在运行的淡入/淡出动画，避免冲突"""
        try:
            if self._fade_anim and self._fade_anim.state() == QPropertyAnimation.State.Running:
                self._fade_anim.stop()
        except RuntimeError:
            # Qt 动画对象已被删除，清除引用
            self._fade_anim = None

    def fade_show(self, screen_geo, target_opacity=1.0):
        """淡入显示，定位到记忆位置或默认右下角"""
        self._stop_running_anim()

        self.adjustSize()

        if self._last_pos:
            widget_rect = QRect(self._last_pos, self.size())
            if screen_geo.contains(widget_rect):
                self.move(self._last_pos)
            else:
                self._move_to_default(screen_geo)
        else:
            self._move_to_default(screen_geo)

        self.setWindowOpacity(0.0)
        self.show()
        anim = QPropertyAnimation(self, b"windowOpacity")
        anim.setDuration(200)
        anim.setStartValue(0.0)
        anim.setEndValue(target_opacity)
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        self._fade_anim = anim

    def fade_hide(self):
        """淡出隐藏"""
        if not self.isVisible():
            return
        self._stop_running_anim()

        anim = QPropertyAnimation(self, b"windowOpacity")
        anim.setDuration(200)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.finished.connect(self.hide)
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        self._fade_anim = anim

    def _move_to_default(self, screen_geo):
        """移动到屏幕右下角，确保不超出边界"""
        x = screen_geo.right() - self.width() - 20
        y = screen_geo.bottom() - self.height() - 20
        x = max(screen_geo.left(), x)
        y = max(screen_geo.top(), y)
        self.move(x, y)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.pos()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_pos and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        if self._drag_pos:
            self._drag_pos = None
            self._last_pos = self.pos()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._main_win.showNormal()

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        action_restore = menu.addAction("恢复窗口")
        action_stop = menu.addAction("停止引擎")
        action_stop.setEnabled(
            bool(self._main_win._engine and self._main_win._engine.isRunning())
        )
        action = menu.exec(event.globalPos())
        if action == action_restore:
            self._main_win.showNormal()
        elif action == action_stop:
            self._main_win._stop_engine()

    def _on_toggle_clicked(self):
        """控制引擎启停（状态同步由 _on_engine_finished 统一处理）"""
        self._main_win._on_toggle_clicked()


# ============================================================
# 可折叠任务卡片组件
# ============================================================

