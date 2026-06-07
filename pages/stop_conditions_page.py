"""停止条件页 (pages/stop_conditions_page.py)"""
from __future__ import annotations
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap, QIntValidator
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QCheckBox, QLineEdit, QSlider, QScrollArea, QFrame, QComboBox,
    QSizePolicy,
)

from styles.colors import (
    CLR_TEXT_MAIN, CLR_TEXT_SUB, CLR_CARD_BG, CLR_CARD_BORDER,
    CLR_BTN_PRIMARY, CLR_BTN_DANGER, CLR_CONTENT_BG,
)
from pages.utils import make_settings_card

if TYPE_CHECKING:
    from main_window import MainWindow


class StopConditionsPage(QWidget):
    def __init__(self, main_win: 'MainWindow', parent=None):
        super().__init__(parent)
        self._main_win = main_win
        self._setup_ui()

    def _setup_ui(self) -> None:
        """构建停止条件页."""

        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(0)

        # 顶部工具栏
        toolbar = QWidget()
        toolbar.setMinimumHeight(32)
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(12, 8, 12, 8)
        toolbar_layout.setSpacing(8)

        title = QLabel("停止条件")
        title.setStyleSheet(
            f"font-size: 16px; font-weight: bold; color: {CLR_TEXT_MAIN};"
        )
        toolbar_layout.addWidget(title)
        toolbar_layout.addStretch(1)
        page_layout.addWidget(toolbar)

        # 可滚动设置区
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; }")

        container = QWidget()
        container.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(10)

        # ---- 总开关 ----
        master_card, master_layout = make_settings_card("停止条件")
        self.chk_stop_enabled = QCheckBox("启用停止条件")
        self.chk_stop_enabled.setChecked(False)
        self.chk_stop_enabled.setStyleSheet(f"""
            QCheckBox {{ color: {CLR_TEXT_MAIN}; font-size: 13px; }}
            QCheckBox:disabled {{ color: {CLR_TEXT_SUB}; }}
        """)
        self.chk_stop_enabled.toggled.connect(self._main_win._on_stop_enabled_toggled)
        master_layout.addWidget(self.chk_stop_enabled)
        desc = QLabel("启用或不启用停止条件，仍然可以手动停止")
        desc.setStyleSheet(f"color: {CLR_TEXT_SUB}; font-size: 11px;")
        desc.setWordWrap(True)
        master_layout.addWidget(desc)
        layout.addWidget(master_card)

        # ---- 条件一：任务执行次数 ----
        c1_card, c1_layout = make_settings_card("任务执行次数")
        c1_row = QHBoxLayout()
        c1_row.setContentsMargins(0, 0, 0, 0)
        c1_row.setSpacing(8)

        self.chk_stop_cond1 = QCheckBox("识别到")
        self.chk_stop_cond1.setStyleSheet(f"""
            QCheckBox {{ color: {CLR_TEXT_MAIN}; font-size: 13px; }}
            QCheckBox:disabled {{ color: {CLR_TEXT_SUB}; }}
        """)
        self.chk_stop_cond1.toggled.connect(self._main_win._on_stop_cond1_toggled)
        c1_row.addWidget(self.chk_stop_cond1)

        self.combo_stop_task = QComboBox()
        self.combo_stop_task.setMinimumWidth(100)
        self.combo_stop_task.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.combo_stop_task.setStyleSheet(f"""
            QComboBox {{ background: white; border: 1px solid {CLR_CARD_BORDER};
                border-radius: 6px; padding: 4px 8px; font-size: 12px; color: {CLR_TEXT_MAIN}; }}
            QComboBox QAbstractItemView {{ background: white; color: {CLR_TEXT_MAIN};
                selection-background-color: {CLR_BTN_PRIMARY}; selection-color: white; }}
        """)
        self.combo_stop_task.wheelEvent = lambda event: event.ignore()
        c1_row.addWidget(self.combo_stop_task)

        c1_row.addWidget(QLabel("任务执行"))

        self.edit_stop_exec_count = QLineEdit("5")
        self.edit_stop_exec_count.setFixedWidth(64)
        self.edit_stop_exec_count.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.edit_stop_exec_count.setValidator(QIntValidator(1, 99999))
        self.edit_stop_exec_count.setStyleSheet(f"""
            QLineEdit {{ background: white; border: 1px solid {CLR_CARD_BORDER};
                border-radius: 6px; padding: 4px 6px; font-size: 12px; color: {CLR_TEXT_MAIN}; }}
            QLineEdit:disabled {{ background: #F0F4F8; color: {CLR_TEXT_SUB}; }}
        """)
        c1_row.addWidget(self.edit_stop_exec_count)

        c1_row.addWidget(QLabel("次后停止"))
        c1_row.addStretch(1)
        c1_layout.addLayout(c1_row)
        layout.addWidget(c1_card)

        # ---- 条件二：运行时间限制 ----
        c2_card, c2_layout = make_settings_card("运行时间限制")
        c2_row = QHBoxLayout()
        c2_row.setContentsMargins(0, 0, 0, 0)
        c2_row.setSpacing(8)

        self.chk_stop_cond2 = QCheckBox("执行")
        self.chk_stop_cond2.setStyleSheet(f"""
            QCheckBox {{ color: {CLR_TEXT_MAIN}; font-size: 13px; }}
            QCheckBox:disabled {{ color: {CLR_TEXT_SUB}; }}
        """)
        self.chk_stop_cond2.toggled.connect(self._main_win._on_stop_cond2_toggled)
        c2_row.addWidget(self.chk_stop_cond2)

        self.edit_stop_run_minutes = QLineEdit("10")
        self.edit_stop_run_minutes.setFixedWidth(64)
        self.edit_stop_run_minutes.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.edit_stop_run_minutes.setValidator(QIntValidator(1, 99999))
        self.edit_stop_run_minutes.setStyleSheet(f"""
            QLineEdit {{ background: white; border: 1px solid {CLR_CARD_BORDER};
                border-radius: 6px; padding: 4px 6px; font-size: 12px; color: {CLR_TEXT_MAIN}; }}
            QLineEdit:disabled {{ background: #F0F4F8; color: {CLR_TEXT_SUB}; }}
        """)
        c2_row.addWidget(self.edit_stop_run_minutes)

        c2_row.addWidget(QLabel("分钟后停止"))
        c2_row.addStretch(1)
        c2_layout.addLayout(c2_row)
        layout.addWidget(c2_card)

        # ---- 条件三：识别指定图片 ----
        c3_card, c3_layout = make_settings_card("识别指定图片")
        self.chk_stop_cond3 = QCheckBox("识别到以下图片后停止")
        self.chk_stop_cond3.setStyleSheet(f"""
            QCheckBox {{ color: {CLR_TEXT_MAIN}; font-size: 13px; }}
            QCheckBox:disabled {{ color: {CLR_TEXT_SUB}; }}
        """)
        self.chk_stop_cond3.toggled.connect(self._main_win._on_stop_cond3_toggled)
        c3_layout.addWidget(self.chk_stop_cond3)

        c3_img_row = QHBoxLayout()
        c3_img_row.setContentsMargins(0, 0, 0, 0)
        c3_img_row.setSpacing(8)

        self.btn_stop_img_upload = QPushButton("🖼 上传识别图")
        self.btn_stop_img_upload.setStyleSheet(f"""
            QPushButton {{
                background: {CLR_CONTENT_BG}; border: 1px solid {CLR_CARD_BORDER};
                border-radius: 6px; padding: 6px 12px; font-size: 12px; color: {CLR_TEXT_MAIN};
            }}
            QPushButton:hover {{ border-color: {CLR_BTN_PRIMARY}; color: {CLR_BTN_PRIMARY}; }}
            QPushButton:disabled {{ background: #F0F4F8; color: {CLR_TEXT_SUB}; border-color: {CLR_CARD_BORDER}; }}
        """)
        self.btn_stop_img_upload.clicked.connect(self._main_win._on_stop_img_upload)
        c3_img_row.addWidget(self.btn_stop_img_upload)

        self.btn_stop_img_capture = QPushButton("📷 截图上传")
        self.btn_stop_img_capture.setStyleSheet(f"""
            QPushButton {{
                background: {CLR_CONTENT_BG}; border: 1px solid {CLR_CARD_BORDER};
                border-radius: 6px; padding: 6px 12px; font-size: 12px; color: {CLR_TEXT_MAIN};
            }}
            QPushButton:hover {{ border-color: {CLR_BTN_PRIMARY}; color: {CLR_BTN_PRIMARY}; }}
            QPushButton:disabled {{ background: #F0F4F8; color: {CLR_TEXT_SUB}; border-color: {CLR_CARD_BORDER}; }}
        """)
        self.btn_stop_img_capture.clicked.connect(self._main_win._on_stop_img_capture)
        c3_img_row.addWidget(self.btn_stop_img_capture)

        self.stop_img_preview = QLabel()
        self.stop_img_preview.setFixedSize(60, 60)
        self.stop_img_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stop_img_preview.setStyleSheet(
            f"border: 2px dashed {CLR_CARD_BORDER}; color: {CLR_TEXT_SUB}; font-size: 11px;"
            "border-radius: 6px;"
        )
        self.stop_img_preview.setText("无图片")
        c3_img_row.addWidget(self.stop_img_preview)
        c3_img_row.addStretch(1)
        c3_layout.addLayout(c3_img_row)

        # 精确度滑块
        c3_slider_row = QWidget()
        c3_slider_row.setFixedHeight(32)
        c3_slider_layout = QHBoxLayout(c3_slider_row)
        c3_slider_layout.setContentsMargins(0, 0, 0, 0)
        c3_slider_layout.setSpacing(8)

        lbl_threshold = QLabel("匹配精确度:")
        lbl_threshold.setMinimumWidth(90)
        lbl_threshold.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lbl_threshold.setStyleSheet(f"color: {CLR_TEXT_MAIN}; font-size: 12px;")
        c3_slider_layout.addWidget(lbl_threshold)

        self.slider_stop_threshold = QSlider(Qt.Orientation.Horizontal)
        self.slider_stop_threshold.setRange(50, 99)
        self.slider_stop_threshold.setValue(90)
        self.slider_stop_threshold.wheelEvent = lambda event: event.ignore()
        self.slider_stop_threshold.valueChanged.connect(
            lambda v: self.label_stop_threshold.setText(f"{v}%")
        )
        c3_slider_layout.addWidget(self.slider_stop_threshold, 1)

        self.label_stop_threshold = QLabel("90%")
        self.label_stop_threshold.setMinimumWidth(36)
        self.label_stop_threshold.setStyleSheet(f"color: {CLR_TEXT_MAIN}; font-size: 12px;")
        c3_slider_layout.addWidget(self.label_stop_threshold)
        c3_layout.addWidget(c3_slider_row)

        layout.addWidget(c3_card)

        # ---- 条件四：无匹配超时 ----
        c4_card, c4_layout = make_settings_card("无匹配超时")
        c4_row = QHBoxLayout()
        c4_row.setContentsMargins(0, 0, 0, 0)
        c4_row.setSpacing(8)

        self.chk_stop_cond4 = QCheckBox()
        self.chk_stop_cond4.setStyleSheet(f"""
            QCheckBox {{ color: {CLR_TEXT_MAIN}; font-size: 13px; }}
            QCheckBox:disabled {{ color: {CLR_TEXT_SUB}; }}
        """)
        self.chk_stop_cond4.toggled.connect(self._main_win._on_stop_cond4_toggled)
        c4_row.addWidget(self.chk_stop_cond4)

        self.edit_stop_idle_minutes = QLineEdit("5")
        self.edit_stop_idle_minutes.setFixedWidth(64)
        self.edit_stop_idle_minutes.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.edit_stop_idle_minutes.setValidator(QIntValidator(1, 99999))
        self.edit_stop_idle_minutes.setStyleSheet(f"""
            QLineEdit {{ background: white; border: 1px solid {CLR_CARD_BORDER};
                border-radius: 6px; padding: 4px 6px; font-size: 12px; color: {CLR_TEXT_MAIN}; }}
            QLineEdit:disabled {{ background: #F0F4F8; color: {CLR_TEXT_SUB}; }}
        """)
        c4_row.addWidget(self.edit_stop_idle_minutes)

        c4_row.addWidget(QLabel("分钟无匹配则停止"))
        c4_row.addStretch(1)
        c4_layout.addLayout(c4_row)

        c4_warn = QLabel("⚠ 为保证体验，请确保时间大于游戏单局最长等待时间")
        c4_warn.setStyleSheet(f"color: {CLR_TEXT_SUB}; font-size: 11px;")
        c4_warn.setWordWrap(True)
        c4_layout.addWidget(c4_warn)

        layout.addWidget(c4_card)

        layout.addStretch(1)

        # 初始禁用状态由 MainWindow._setup_ui 在快捷引用建立后统一调用
        # self._main_win._set_stop_controls_enabled(False)

        scroll.setWidget(container)
        page_layout.addWidget(scroll, 1)

        # self._stack.addWidget(page)  # 由 MainWindow._setup_ui 负责 addWidget

