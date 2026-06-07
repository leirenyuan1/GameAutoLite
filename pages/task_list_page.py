"""任务列表页 (pages/task_list_page.py)"""
from __future__ import annotations
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame,
)

from styles.colors import (
    CLR_TEXT_MAIN, CLR_CARD_BG, CLR_CARD_BORDER,
    CLR_BTN_PRIMARY, CLR_TEXT_SUB,
)

if TYPE_CHECKING:
    from main_window import MainWindow


class TaskListPage(QWidget):
    """任务列表页：顶部工具栏 + 可滚动卡片区 + 底部添加按钮。"""

    def __init__(self, main_win: 'MainWindow', parent=None):
        super().__init__(parent)
        self._main_win = main_win
        self._setup_ui()

    def _setup_ui(self) -> None:
        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(8, 6, 8, 6)
        page_layout.setSpacing(8)

        # -- 顶部工具栏 --
        toolbar = QWidget()
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(0, 0, 0, 0)
        toolbar_layout.setSpacing(8)

        title = QLabel("任务列表")
        title.setStyleSheet(
            f"font-size: 16px; font-weight: bold; color: {CLR_TEXT_MAIN};"
        )
        toolbar_layout.addWidget(title)
        toolbar_layout.addStretch(1)

        self.btn_import = QPushButton("\U0001F4C2 导入方案")
        self.btn_import.setStyleSheet(f"""
            QPushButton {{
                background: {CLR_CARD_BG}; border: 1px solid {CLR_CARD_BORDER};
                border-radius: 6px; padding: 4px 10px; font-size: 12px;
                color: {CLR_TEXT_MAIN};
            }}
            QPushButton:hover {{ border-color: {CLR_BTN_PRIMARY}; color: {CLR_BTN_PRIMARY}; }}
        """)
        self.btn_import.clicked.connect(self._main_win._on_import)

        self.btn_export = QPushButton("\U0001F4BE 导出方案")
        self.btn_export.setStyleSheet(f"""
            QPushButton {{
                background: {CLR_CARD_BG}; border: 1px solid {CLR_CARD_BORDER};
                border-radius: 6px; padding: 4px 10px; font-size: 12px;
                color: {CLR_TEXT_MAIN};
            }}
            QPushButton:hover {{ border-color: {CLR_BTN_PRIMARY}; color: {CLR_BTN_PRIMARY}; }}
        """)
        self.btn_export.clicked.connect(self._main_win._on_export)

        toolbar_layout.addWidget(self.btn_import)
        toolbar_layout.addWidget(self.btn_export)
        page_layout.addWidget(toolbar)

        # -- 可滚动任务卡片区 --
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setStyleSheet("QScrollArea { background: transparent; }")

        self._card_container = QWidget()
        self._card_container.setStyleSheet("background: transparent;")
        self._card_layout = QVBoxLayout(self._card_container)
        self._card_layout.setSpacing(8)
        self._card_layout.setContentsMargins(0, 0, 0, 0)

        self._scroll.setWidget(self._card_container)
        page_layout.addWidget(self._scroll, 1)

        # -- 底部添加按钮 --
        self.btn_add = QPushButton("＋ 添加任务")
        self.btn_add.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: 2px dashed {CLR_CARD_BORDER};
                border-radius: 8px;
                padding: 8px;
                font-size: 13px;
                color: {CLR_TEXT_SUB};
            }}
            QPushButton:hover {{
                border-color: {CLR_BTN_PRIMARY};
                color: {CLR_BTN_PRIMARY};
            }}
        """)
        self.btn_add.clicked.connect(lambda: self._main_win._add_task())
        # 先加按钮再加 stretch：btn_add 位于 stretch 上方，卡片在 btn_add 上方
        self._card_layout.addWidget(self.btn_add)
        self._card_layout.addStretch(1)
