"""
左侧边栏 (widgets/sidebar.py)
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QPushButton, QSizePolicy,
)

from styles.colors import (
    CLR_SIDEBAR_ACT, CLR_CARD_BORDER, CLR_TEXT_SUB,
    CLR_BTN_SUCCESS, CLR_BTN_DANGER,
)
from widgets.nav_item import NavItem


class SideBar(QWidget):
    """左侧导航边栏."""

    navigate = pyqtSignal(int)  # 发射页面索引

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(130)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ---------- 顶部 Logo 区 ----------
        logo_area = QWidget()
        logo_layout = QVBoxLayout(logo_area)
        logo_layout.setContentsMargins(0, 16, 0, 12)
        logo_layout.setSpacing(4)

        logo_icon = QLabel("🎮")
        logo_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_icon.setStyleSheet("font-size: 28px;")
        logo_layout.addWidget(logo_icon)

        logo_text = QLabel("GameAutoLite")
        logo_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_text.setStyleSheet(
            f"font-size: 11px; font-weight: bold; color: {CLR_SIDEBAR_ACT};"
        )
        logo_layout.addWidget(logo_text)

        logo_line = QFrame()
        logo_line.setFixedHeight(1)
        logo_line.setStyleSheet(f"background: {CLR_CARD_BORDER}; margin: 4px 12px;")
        logo_layout.addWidget(logo_line)

        layout.addWidget(logo_area)

        # ---------- 导航菜单区 ----------
        nav_area = QWidget()
        nav_layout = QVBoxLayout(nav_area)
        nav_layout.setContentsMargins(0, 4, 0, 0)
        nav_layout.setSpacing(4)

        self.nav_tasks = NavItem("📋", "任务列表")
        self.nav_stop = NavItem("🛑", "停止条件")
        self.nav_settings = NavItem("⚙", "全局设置")
        self.nav_remote = NavItem("📱", "远程监控")  # 新增
        self.nav_tasks.clicked.connect(lambda: self._on_nav(0))
        self.nav_stop.clicked.connect(lambda: self._on_nav(1))
        self.nav_settings.clicked.connect(lambda: self._on_nav(2))
        self.nav_remote.clicked.connect(lambda: self._on_nav(3))  # 新增
        self.nav_tasks.set_selected(True)

        nav_layout.addWidget(self.nav_tasks)
        nav_layout.addWidget(self.nav_stop)
        nav_layout.addWidget(self.nav_settings)
        nav_layout.addWidget(self.nav_remote)  # 新增
        nav_layout.addStretch(1)

        layout.addWidget(nav_area, 1)

        # ---------- 底部状态区 ----------
        bottom_area = QWidget()
        bottom_layout = QVBoxLayout(bottom_area)
        bottom_layout.setContentsMargins(10, 0, 10, 12)
        bottom_layout.setSpacing(8)

        bottom_line = QFrame()
        bottom_line.setFixedHeight(1)
        bottom_line.setStyleSheet(f"background: {CLR_CARD_BORDER};")
        bottom_layout.addWidget(bottom_line)

        # ---- 三行状态面板 ----
        status_panel = QWidget()
        status_layout = QVBoxLayout(status_panel)
        status_layout.setContentsMargins(0, 6, 0, 6)
        status_layout.setSpacing(2)

        def _make_status_row(icon_text: str, line_text: str):
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
            status_layout.addLayout(row)
            return icon_lbl, text_lbl

        self.status_icon1, self.status_line1 = _make_status_row("⚡", "就绪")
        self.status_icon2, self.status_line2 = _make_status_row("🖱", "—")
        self.status_icon3, self.status_line3 = _make_status_row("⏱", "—")
        bottom_layout.addWidget(status_panel)

        self.btn_toggle = QPushButton("▶ 开始")
        self.btn_toggle.setFixedHeight(36)
        self.btn_toggle.setStyleSheet(f"""
            QPushButton {{
                background: {CLR_BTN_SUCCESS}; color: #fff; border: none;
                border-radius: 8px; font-size: 13px; font-weight: bold;
            }}
            QPushButton:hover {{ background: #66BB6A; }}
        """)
        bottom_layout.addWidget(self.btn_toggle)

        layout.addWidget(bottom_area)

    def _on_nav(self, index: int) -> None:
        self.nav_tasks.set_selected(index == 0)
        self.nav_stop.set_selected(index == 1)
        self.nav_settings.set_selected(index == 2)
        self.nav_remote.set_selected(index == 3)  # 新增
        self.navigate.emit(index)

    def set_engine_running(self, running: bool) -> None:
        """更新启停按钮状态."""
        if running:
            self.btn_toggle.setText("⏹ 停止")
            self.btn_toggle.setStyleSheet(f"""
                QPushButton {{
                    background: {CLR_BTN_DANGER}; color: #fff; border: none;
                    border-radius: 8px; font-size: 13px; font-weight: bold;
                }}
                QPushButton:hover {{ background: #F44336; }}
            """)
        else:
            self.btn_toggle.setText("▶ 开始")
            self.btn_toggle.setStyleSheet(f"""
                QPushButton {{
                    background: {CLR_BTN_SUCCESS}; color: #fff; border: none;
                    border-radius: 8px; font-size: 13px; font-weight: bold;
                }}
                QPushButton:hover {{ background: #66BB6A; }}
            """)


# ============================================================
# 悬浮状态卡片（最小化时显示）
# ============================================================

