"""
可折叠任务卡片 (widgets/task_card.py)
"""
from __future__ import annotations
from typing import TYPE_CHECKING

import logging
import os
import time

import cv2
import mss
import numpy as np

from PyQt6.QtCore import Qt, pyqtSignal, QPropertyAnimation, QEasingCurve, QTimer, QRectF, QSize
from PyQt6.QtGui import QPixmap, QColor, QPainter, QPen, QFont
from PyQt6.QtWidgets import (
    QApplication, QFrame, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QCheckBox, QSlider,
    QComboBox, QFileDialog, QGraphicsDropShadowEffect, QSizePolicy,
)

import image_engine
import overlay_selector
from config_manager import SCREENSHOTS_DIR
from pages.utils import DefaultIntValidator
from styles.icons import IconButton, button_icon, ICON_BTN, ICON_CARD
from styles.colors import (
    CLR_ACCENT_LINE, CLR_CARD_BORDER, CLR_CARD_HEADER,
    CLR_TEXT_MAIN, CLR_TEXT_SUB, CLR_BTN_PRIMARY,
    CLR_BTN_DANGER, CLR_CARD_BG, CLR_CONTENT_BG,
)

if TYPE_CHECKING:
    from main_window import MainWindow

logger = logging.getLogger(__name__)


class _MatchHighlightOverlay(QWidget):
    """测试识别匹配结果全屏透明高亮框 (FEAT-02)"""

    def __init__(
        self,
        task_name: str,
        score_pct: float,
        passed: bool,
        rx: int,
        ry: int,
        rw: int,
        rh: int,
        parent=None,
    ):
        super().__init__(parent)
        self._task_name = task_name
        self._score_pct = score_pct
        self._passed = passed
        self._tag_bg_color = QColor("#43A047") if passed else QColor("#FF9800")
        self._rx, self._ry, self._rw, self._rh = rx, ry, rw, rh
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)

        ratio = self.devicePixelRatioF()
        lx, ly = int(self._rx / ratio), int(self._ry / ratio)
        lw, lh = max(1, int(self._rw / ratio)), max(1, int(self._rh / ratio))
        self._lx, self._ly, self._lw, self._lh = lx, ly, lw, lh

        pad_x = 4
        pad_top = 28
        win_w = max(lw + pad_x * 2, 160)
        win_h = lh + pad_top + 4

        screen = QApplication.primaryScreen().geometry()
        tag_below = (ly < pad_top)
        self._tag_below = tag_below
        win_y = ly if tag_below else (ly - pad_top)
        win_x = max(0, min(lx - pad_x, screen.width() - win_w))
        win_y = max(0, min(win_y, screen.height() - win_h))
        self.setGeometry(win_x, win_y, win_w, win_h)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        win_x = self.x()
        win_y = self.y()
        target_x = self._lx - win_x
        target_y = self._ly - win_y
        lw, lh = self._lw, self._lh

        # 1. 目标框体 (消除边缘 Clamp 平移错位)
        painter.setPen(QPen(self._tag_bg_color, 2, Qt.PenStyle.SolidLine if self._passed else Qt.PenStyle.DashLine))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QRectF(target_x, target_y, lw, lh), 2.5, 2.5)

        # 2. 胶囊标签 (固定字体，长任务名自适应省略与截断保护)
        painter.setFont(QFont("Microsoft YaHei", 9))
        fm = painter.fontMetrics()
        win_w = self.width()
        win_h = self.height()
        max_tag_w = max(60, win_w - 8)
        elided_name = fm.elidedText(self._task_name, Qt.TextElideMode.ElideRight, max(30, max_tag_w - 55))
        raw_tag = f"{elided_name} · {self._score_pct:.1f}%" if self._passed else f"未达标 · 最高 {self._score_pct:.1f}%"
        tag_text = fm.elidedText(raw_tag, Qt.TextElideMode.ElideRight, max_tag_w - 12)
        tag_w = min(max_tag_w, fm.horizontalAdvance(tag_text) + 14)
        tag_h = 22

        # 3. 标签坐标安全 clamp
        tag_x = max(2, min(target_x, win_w - tag_w - 2))
        if self._tag_below:
            tag_y = min(win_h - tag_h - 2, target_y + lh + 4)
        else:
            tag_y = max(2, target_y - tag_h - 4)

        # 4. 绘制圆角胶囊背景与文字
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._tag_bg_color)
        painter.drawRoundedRect(QRectF(tag_x, tag_y, tag_w, tag_h), 4.0, 4.0)
        painter.setPen(QColor("#FFFFFF"))
        painter.drawText(QRectF(tag_x, tag_y, tag_w, tag_h), Qt.AlignmentFlag.AlignCenter, tag_text)


class CollapsibleTaskCard(QFrame):
    """可折叠的任务配置卡片."""

    removed = pyqtSignal(object)
    moved_up = pyqtSignal(object)
    moved_down = pyqtSignal(object)
    copy_requested = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._image_path: str | None = None
        self._region: tuple[int, int, int, int] | None = None
        self._search_region: tuple[int, int, int, int] | None = None
        self._click_on_match = False
        self._multi_region = False
        self._regions: list[tuple[int, int, int, int]] = []
        self._click_count = 1
        self._expanded = True
        self._is_deleting = False
        self._is_enabled: bool = True
        self._name_has_error = False  # 标记当前卡片名称是否有校验错误
        self._last_valid_name: str = ""  # 任务改名基线记录 (DASH-04)
        self._fold_anim: QPropertyAnimation | None = None
        self._active_overlay: _MatchHighlightOverlay | None = None
        self._highlight_timer = QTimer(self)
        self._highlight_timer.setSingleShot(True)
        self._highlight_timer.timeout.connect(self.close_highlight_overlay)
        self._setup_ui()

    def _setup_ui(self) -> None:
        """构建卡片内部布局."""
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(12)
        shadow.setOffset(0, 2)
        shadow.setColor(QColor(33, 150, 243, 30))

        self.setObjectName("CollapsibleTaskCard")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- 头部 ----
        self._header = QFrame()
        self._header.setObjectName("card_header")
        self._header.setFixedHeight(48)

        header_layout = QHBoxLayout(self._header)
        header_layout.setContentsMargins(0, 0, 8, 0)
        header_layout.setSpacing(6)

        # 左侧蓝色竖线
        accent_line = QFrame()
        accent_line.setFixedWidth(3)
        accent_line.setStyleSheet(
            f"background: {CLR_ACCENT_LINE}; border-top-left-radius: 10px;"
        )
        header_layout.addWidget(accent_line)

        # 折叠/展开箭头 (位于勾选框左侧)
        self.btn_arrow = IconButton("chevron-down", "#7A9AB8", CLR_BTN_PRIMARY, ICON_CARD)
        self.btn_arrow.setFixedSize(32, 32)
        self.btn_arrow.setStyleSheet("QPushButton { border: none; }")
        self.btn_arrow.clicked.connect(self._toggle_expand)
        header_layout.addWidget(self.btn_arrow)

        # 独立启用复选框 (FEAT-03, 位于折叠箭头右侧)
        self.chk_enabled = QCheckBox()
        self.chk_enabled.setChecked(True)
        self.chk_enabled.setStyleSheet("QCheckBox { margin-left: 2px; }")
        self.chk_enabled.toggled.connect(self._on_enabled_toggled)
        header_layout.addWidget(self.chk_enabled)

        # 任务名称输入框
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("任务名称")
        self.name_edit.setStyleSheet(
            f"background: #F0F7FF; border: 1px solid {CLR_CARD_BORDER};"
            "border-radius: 6px; padding: 4px 8px; font-size: 13px;"
            f"color: {CLR_TEXT_MAIN};"
        )
        header_layout.addWidget(self.name_edit, 1)
        self.name_edit.editingFinished.connect(self._validate_name)

        # name_edit 创建完毕后再应用 Header 初始样式 (防 P0-2 AttributeError)
        self._update_header_style()

        # 操作按钮
        self.btn_copy = self._make_header_btn("copy")
        self.btn_copy.setToolTip("复制任务")
        self.btn_copy.clicked.connect(lambda: self.copy_requested.emit(self))
        self.btn_up = self._make_header_btn("arrow-up")
        self.btn_up.clicked.connect(lambda: self.moved_up.emit(self))
        self.btn_down = self._make_header_btn("arrow-down")
        self.btn_down.clicked.connect(lambda: self.moved_down.emit(self))
        self.btn_delete = IconButton("x", CLR_BTN_DANGER, "#FFFFFF", 14)
        self.btn_delete.setFixedSize(30, 30)
        self.btn_delete.setStyleSheet(f"""
            QPushButton {{
                background: transparent; border: none; border-radius: 6px;
            }}
            QPushButton:hover {{
                background: {CLR_BTN_DANGER};
            }}
        """)
        self.btn_delete.clicked.connect(lambda: self.removed.emit(self))

        header_layout.addWidget(self.btn_copy)
        header_layout.addWidget(self.btn_up)
        header_layout.addWidget(self.btn_down)
        header_layout.addWidget(self.btn_delete)

        root.addWidget(self._header)

        # ---- 内容区 ----
        self.content_widget = QWidget()
        self.content_widget.setObjectName("card_content")
        self.content_widget.setStyleSheet(
            "#card_content {"
            f"background: {CLR_CARD_BG}; border: 1px solid {CLR_CARD_BORDER};"
            "border-top: none; border-bottom-left-radius: 10px;"
            "border-bottom-right-radius: 10px;"
            "}"
        )

        content_layout = QVBoxLayout(self.content_widget)
        content_layout.setContentsMargins(12, 10, 12, 12)
        content_layout.setSpacing(6)

        _LABEL_STYLE = f"color: {CLR_TEXT_MAIN}; font-size: 12px;"
        _SUB_STYLE = f"color: {CLR_TEXT_SUB}; font-size: 11px;"

        def _row_label(text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setMinimumWidth(90)
            lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            lbl.setStyleSheet(_LABEL_STYLE)
            return lbl

        def _small_label(text: str, min_w: int = 0) -> QLabel:
            lbl = QLabel(text)
            if min_w:
                lbl.setMinimumWidth(min_w)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet(_SUB_STYLE)
            return lbl

        # ---- 行: 上传识别图 + 缩略图预览 (FEAT-02 测试识别按钮) ----
        row2 = QHBoxLayout()
        self.btn_upload = IconButton("image", CLR_TEXT_MAIN, CLR_BTN_PRIMARY, ICON_BTN)
        self.btn_upload.setText("上传识别图")
        self.btn_upload.setStyleSheet(f"""
            QPushButton {{
                background: {CLR_CONTENT_BG}; border: 1px solid {CLR_CARD_BORDER};
                border-radius: 6px; padding: 6px 12px; font-size: 12px;
                color: {CLR_TEXT_MAIN};
            }}
            QPushButton:hover {{ border-color: {CLR_BTN_PRIMARY}; color: {CLR_BTN_PRIMARY}; }}
        """)
        self.btn_upload.clicked.connect(self._on_upload_image)

        self.btn_capture = IconButton("camera", CLR_TEXT_MAIN, CLR_BTN_PRIMARY, ICON_BTN)
        self.btn_capture.setText("截图上传")
        self.btn_capture.setStyleSheet(f"""
            QPushButton {{
                background: {CLR_CONTENT_BG}; border: 1px solid {CLR_CARD_BORDER};
                border-radius: 6px; padding: 6px 12px; font-size: 12px;
                color: {CLR_TEXT_MAIN};
            }}
            QPushButton:hover {{ border-color: {CLR_BTN_PRIMARY}; color: {CLR_BTN_PRIMARY}; }}
        """)
        self.btn_capture.clicked.connect(self._on_screenshot_capture)

        self.btn_test = IconButton("target", CLR_TEXT_MAIN, CLR_BTN_PRIMARY, ICON_BTN)
        self.btn_test.setText("测试识别")
        self.btn_test.setFixedWidth(92)
        self.btn_test.setStyleSheet(f"""
            QPushButton {{
                background: {CLR_CONTENT_BG}; border: 1px solid {CLR_CARD_BORDER};
                border-radius: 6px; padding: 6px 8px; font-size: 12px;
                color: {CLR_TEXT_MAIN};
            }}
            QPushButton:hover {{ border-color: {CLR_BTN_PRIMARY}; color: {CLR_BTN_PRIMARY}; }}
            QPushButton:disabled {{ background: #F0F4F8; color: {CLR_TEXT_SUB}; border-color: {CLR_CARD_BORDER}; }}
        """)
        self.btn_test.clicked.connect(self._on_test_match)
        self._test_btn_timer = QTimer(self)
        self._test_btn_timer.setSingleShot(True)
        self._test_btn_timer.timeout.connect(self._reset_test_button)

        self.img_preview = QLabel()
        self.img_preview.setFixedSize(60, 60)
        self.img_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.img_preview.setStyleSheet(
            f"border: 2px dashed {CLR_CARD_BORDER}; color: {CLR_TEXT_SUB}; font-size: 11px;"
            "border-radius: 6px;"
        )
        self.img_preview.setText("无图片")

        row2.addWidget(self.btn_upload)
        row2.addWidget(self.btn_capture)
        row2.addWidget(self.btn_test)
        row2.addWidget(self.img_preview)
        row2.addStretch(1)
        content_layout.addLayout(row2)

        # ---- 分隔线 ----
        content_layout.addWidget(self._make_hline())

        # ---- 行: 匹配精确度滑块 ----
        row3_container = QWidget()
        row3_container.setFixedHeight(32)
        row3 = QHBoxLayout(row3_container)
        row3.setContentsMargins(0, 0, 0, 0)
        row3.addWidget(_row_label("匹配精确度:"))

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(50, 99)
        self.slider.setValue(90)
        # 宽度区间：宽窗口下不拉满卡片，窄窗口下也保持可拖长度
        self.slider.setMinimumWidth(200)
        self.slider.setMaximumWidth(240)
        self.slider.wheelEvent = lambda event: event.ignore()
        self.slider.valueChanged.connect(self._on_slider_changed)
        row3.addWidget(self.slider, 1)

        self.label_threshold = QLabel("90%")
        self.label_threshold.setMinimumWidth(36)
        self.label_threshold.setStyleSheet(_LABEL_STYLE)
        row3.addWidget(self.label_threshold)
        row3.addStretch(1)  # 吸收多余宽度，保持整行左对齐
        content_layout.addWidget(row3_container)

        # ---- 行: 识别范围 (FEAT-04) ----
        row_roi = QHBoxLayout()
        row_roi.addWidget(_row_label("识别范围:"))

        self.btn_roi = IconButton("target", CLR_TEXT_MAIN, CLR_BTN_PRIMARY, ICON_BTN)
        self.btn_roi.setText("范围")
        self.btn_roi.setFixedHeight(28)
        self.btn_roi.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self.btn_roi.setStyleSheet(f"""
            QPushButton {{
                background: {CLR_CONTENT_BG}; border: 1px solid {CLR_CARD_BORDER};
                border-radius: 6px; padding: 0 8px; font-size: 12px;
                color: {CLR_TEXT_MAIN};
            }}
            QPushButton:hover {{ border-color: {CLR_BTN_PRIMARY}; color: {CLR_BTN_PRIMARY}; }}
            QPushButton:disabled {{ background: #F0F4F8; color: {CLR_TEXT_SUB}; border-color: {CLR_CARD_BORDER}; }}
        """)
        self.btn_roi.clicked.connect(self._on_set_roi)
        row_roi.addWidget(self.btn_roi)

        self.btn_roi_reset = QPushButton("重置")
        self.btn_roi_reset.setFixedHeight(28)
        self.btn_roi_reset.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self.btn_roi_reset.setStyleSheet(f"""
            QPushButton {{
                background: {CLR_CONTENT_BG}; border: 1px solid {CLR_CARD_BORDER};
                border-radius: 6px; padding: 0 8px; font-size: 12px;
                color: {CLR_TEXT_MAIN};
            }}
            QPushButton:hover {{ border-color: {CLR_BTN_PRIMARY}; color: {CLR_BTN_PRIMARY}; }}
            QPushButton:disabled {{ background: #F0F4F8; color: {CLR_TEXT_SUB}; border-color: {CLR_CARD_BORDER}; }}
        """)
        self.btn_roi_reset.clicked.connect(self._on_reset_roi)
        self.btn_roi_reset.setVisible(False)
        row_roi.addWidget(self.btn_roi_reset)

        self.label_roi = QLabel("全屏识别")
        self.label_roi.setMinimumWidth(0)
        self.label_roi.minimumSizeHint = lambda: QSize(0, 16)
        self.label_roi.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.label_roi.setStyleSheet(f"color: {CLR_TEXT_SUB}; font-size: 12px;")
        row_roi.addWidget(self.label_roi)

        content_layout.addLayout(row_roi)

        # ---- 行: 设定点击区域 ----
        row4 = QHBoxLayout()
        row4.addWidget(_row_label("点击区域:"))

        self.btn_region = IconButton("circle-plus", CLR_TEXT_MAIN, CLR_BTN_PRIMARY, ICON_BTN)
        self.btn_region.setText("设定")
        self.btn_region.setFixedHeight(28)
        self.btn_region.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self.btn_region.setStyleSheet(f"""
            QPushButton {{
                background: {CLR_CONTENT_BG}; border: 1px solid {CLR_CARD_BORDER};
                border-radius: 6px; padding: 0 8px; font-size: 12px;
                color: {CLR_TEXT_MAIN};
            }}
            QPushButton:hover {{ border-color: {CLR_BTN_PRIMARY}; color: {CLR_BTN_PRIMARY}; }}
        """)
        self.btn_region.clicked.connect(self._on_set_region)

        self.label_region = QLabel("未设定")
        self.label_region.setMinimumWidth(0)
        self.label_region.minimumSizeHint = lambda: QSize(0, 16)
        self.label_region.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.label_region.setStyleSheet(f"color: {CLR_TEXT_SUB}; font-size: 12px;")

        row4.addWidget(self.btn_region)
        row4.addWidget(self.label_region)
        content_layout.addLayout(row4)

        # ---- 点击区域选项 (同一行) ----
        row_chk = QHBoxLayout()
        self.chk_click_on_match = QCheckBox("点击区域为识别图")
        self.chk_click_on_match.toggled.connect(self._on_click_on_match_changed)
        row_chk.addWidget(self.chk_click_on_match)
        self.chk_multi_region = QCheckBox("点击区域可多选")
        self.chk_multi_region.toggled.connect(self._on_multi_region_changed)
        row_chk.addWidget(self.chk_multi_region)
        row_chk.addStretch()
        content_layout.addLayout(row_chk)

        # ---- 分隔线 ----
        content_layout.addWidget(self._make_hline())

        # ---- 鼠标点击行为 ----
        row4c = QHBoxLayout()
        row4c.addWidget(_row_label("鼠标点击行为:"))

        self.combo_click_mode = QComboBox()
        self.combo_click_mode.setEditable(True)
        self.combo_click_mode.addItems(["单击", "双击"])
        self.combo_click_mode.setMinimumWidth(80)
        self.combo_click_mode.setMaximumWidth(120)
        self.combo_click_mode.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.combo_click_mode.setStyleSheet(f"""
            QComboBox {{
                background: white; border: 1px solid {CLR_CARD_BORDER};
                border-radius: 6px; padding: 4px 8px; font-size: 12px;
                color: {CLR_TEXT_MAIN};
            }}
            QComboBox QAbstractItemView {{
                background: white; color: {CLR_TEXT_MAIN};
                selection-background-color: {CLR_BTN_PRIMARY}; selection-color: white;
            }}
        """)
        self.combo_click_mode.wheelEvent = lambda event: event.ignore()
        self.combo_click_mode.currentTextChanged.connect(self._on_click_mode_changed)
        if self.combo_click_mode.lineEdit():
            self.combo_click_mode.lineEdit().editingFinished.connect(
                self._on_click_mode_editing_finished
            )
        row4c.addWidget(self.combo_click_mode)

        lbl_suffix = QLabel("（可填入 1~9999 自定义次数）")
        lbl_suffix.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        lbl_suffix.setStyleSheet(_SUB_STYLE)
        row4c.addWidget(lbl_suffix)
        row4c.addStretch(1)  # 剩余宽度留在末尾，保持与本页其他行左对齐
        content_layout.addLayout(row4c)

        # ---- 分隔线 ----
        content_layout.addWidget(self._make_hline())

        # ---- 随机延迟 + 点击后冷却 (QGridLayout) (FEAT-06 DefaultIntValidator) ----
        grid = QGridLayout()
        grid.setVerticalSpacing(6)
        grid.setHorizontalSpacing(6)

        # 行0: 随机延迟
        grid.addWidget(_row_label("随机延迟:"), 0, 0)
        grid.addWidget(_small_label("最小", 30), 0, 1)

        self.edit_delay_min = QLineEdit("200")
        self.edit_delay_min.setMinimumWidth(50)
        self.edit_delay_min.setMaximumWidth(96)
        self.edit_delay_min.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.edit_delay_min.setValidator(DefaultIntValidator(0, 9999, 200, self))
        self.edit_delay_min.editingFinished.connect(self._validate_delay)
        grid.addWidget(self.edit_delay_min, 0, 2)

        grid.addWidget(_small_label("ms", 24), 0, 3)
        grid.addWidget(_small_label("~", 16), 0, 4)
        grid.addWidget(_small_label("最大", 30), 0, 5)

        self.edit_delay_max = QLineEdit("500")
        self.edit_delay_max.setMinimumWidth(50)
        self.edit_delay_max.setMaximumWidth(96)
        self.edit_delay_max.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.edit_delay_max.setValidator(DefaultIntValidator(0, 9999, 500, self))
        self.edit_delay_max.editingFinished.connect(self._validate_delay)
        grid.addWidget(self.edit_delay_max, 0, 6)

        grid.addWidget(_small_label("ms", 24), 0, 7)

        # 行1: 点击后冷却
        grid.addWidget(_row_label("点击后冷却:"), 1, 0)
        grid.addWidget(_small_label("最小", 30), 1, 1)

        self.edit_cooldown_min = QLineEdit("0")
        self.edit_cooldown_min.setMinimumWidth(50)
        self.edit_cooldown_min.setMaximumWidth(96)
        self.edit_cooldown_min.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.edit_cooldown_min.setValidator(DefaultIntValidator(0, 999999, 0, self))
        self.edit_cooldown_min.editingFinished.connect(self._validate_cooldown)
        grid.addWidget(self.edit_cooldown_min, 1, 2)

        grid.addWidget(_small_label("ms", 24), 1, 3)
        grid.addWidget(_small_label("~", 16), 1, 4)
        grid.addWidget(_small_label("最大", 30), 1, 5)

        self.edit_cooldown_max = QLineEdit("0")
        self.edit_cooldown_max.setMinimumWidth(50)
        self.edit_cooldown_max.setMaximumWidth(96)
        self.edit_cooldown_max.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.edit_cooldown_max.setValidator(DefaultIntValidator(0, 999999, 0, self))
        self.edit_cooldown_max.editingFinished.connect(self._validate_cooldown)
        grid.addWidget(self.edit_cooldown_max, 1, 6)

        grid.addWidget(_small_label("ms", 24), 1, 7)

        # 列拉伸：末尾补一个空列吸收剩余宽度，输入框保持固定宽度不被拉伸
        grid.setColumnStretch(8, 1)

        content_layout.addLayout(grid)

        root.addWidget(self.content_widget)

        # 默认展开
        self._expanded = True
        self.content_widget.setVisible(True)
        self.btn_arrow.set_icon("chevron-down")

        # 初始阴影
        self.setGraphicsEffect(shadow)

    def _make_hline(self) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFixedHeight(1)
        line.setStyleSheet(f"background: {CLR_CARD_BORDER}; border: none;")
        return line

    def _make_header_btn(self, icon_key: str) -> IconButton:
        btn = IconButton(icon_key, CLR_TEXT_SUB, CLR_BTN_PRIMARY, 14)
        btn.setFixedSize(28, 28)
        btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; border: none; border-radius: 6px;
            }}
            QPushButton:hover {{
                background: {CLR_CONTENT_BG};
            }}
        """)
        return btn

    def _on_enabled_toggled(self, checked: bool) -> None:
        self._is_enabled = checked
        self._update_header_style()

    def _update_header_style(self) -> None:
        bg = "#F2F6FA" if not self._is_enabled else CLR_CARD_HEADER
        if self._expanded:
            self._header.setStyleSheet(f"""
                #card_header {{
                    background: {bg};
                    border: 1px solid {CLR_CARD_BORDER};
                    border-bottom: none;
                    border-top-left-radius: 10px;
                    border-top-right-radius: 10px;
                }}
            """)
        else:
            self._header.setStyleSheet(f"""
                #card_header {{
                    background: {bg};
                    border: 1px solid {CLR_CARD_BORDER};
                    border-radius: 10px;
                }}
            """)
        if hasattr(self, "name_edit") and not self._name_has_error:
            self._set_name_normal_style()

    def _toggle_expand(self) -> None:
        if self._is_deleting:
            return
        if self._expanded:
            self._collapse()
        else:
            self._expand()

    def _expand(self) -> None:
        try:
            if self._fold_anim is not None and self._fold_anim.state() == QPropertyAnimation.State.Running:
                self._fold_anim.stop()
        except RuntimeError:
            self._fold_anim = None
        self._expanded = True
        self.btn_arrow.set_icon("chevron-down")
        self._update_header_style()
        self.content_widget.setVisible(True)
        self.content_widget.setMaximumHeight(16777215)

        # 计算内容实际高度
        target_h = self.content_widget.sizeHint().height()
        if target_h <= 0:
            target_h = 200

        anim = QPropertyAnimation(self.content_widget, b"maximumHeight", self)
        anim.setDuration(200)
        anim.setStartValue(0)
        anim.setEndValue(target_h)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.finished.connect(lambda: self.content_widget.setMaximumHeight(16777215))
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        self._fold_anim = anim

    def _collapse(self) -> None:
        try:
            if self._fold_anim is not None and self._fold_anim.state() == QPropertyAnimation.State.Running:
                self._fold_anim.stop()
        except RuntimeError:
            self._fold_anim = None
        self._expanded = False
        self.btn_arrow.set_icon("chevron-right")
        self._update_header_style()

        cur_h = self.content_widget.height()
        anim = QPropertyAnimation(self.content_widget, b"maximumHeight", self)
        anim.setDuration(180)
        anim.setStartValue(cur_h)
        anim.setEndValue(0)
        anim.setEasingCurve(QEasingCurve.Type.InCubic)
        anim.finished.connect(lambda: self.content_widget.setVisible(False))
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        self._fold_anim = anim

    def set_collapsed(self, collapsed: bool) -> None:
        """外部设置初始折叠状态（无动画）."""
        if collapsed:
            self._expanded = False
            self.btn_arrow.set_icon("chevron-right")
            self.content_widget.setVisible(False)
            self.content_widget.setMaximumHeight(0)
            self._update_header_style()
        else:
            self._expanded = True
            self.btn_arrow.set_icon("chevron-down")
            self.content_widget.setVisible(True)
            self.content_widget.setMaximumHeight(16777215)
            self._update_header_style()

    # ---- 交互回调 ----

    def _on_upload_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择识别模板图片", "",
            "Images (*.png *.jpg *.jpeg *.bmp);;All Files (*)"
        )
        if not path:
            return
        self._image_path = path
        pixmap = QPixmap(path)
        if pixmap.isNull():
            self.img_preview.setText("无效图片")
            self.img_preview.setStyleSheet(
                "border: 2px dashed #EF5350; color: #EF5350; font-size: 11px;"
                "border-radius: 6px;"
            )
            self._image_path = None
            return
        self.img_preview.setPixmap(pixmap.scaled(
            60, 60, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
        ))
        self.img_preview.setStyleSheet(
            f"border: 1px solid {CLR_CARD_BORDER}; border-radius: 6px;"
        )
        self._update_image_warning()

    def _on_screenshot_capture(self) -> None:
        """通过 overlay 框选屏幕区域, 截图并保存为模板图片 (BUG-01, BUG-02, BUG-03)."""
        main_win = self.window()
        state = main_win.prepare_selection_mode() if main_win else None
        img = None
        try:
            result, cropped = overlay_selector.get_region_with_image(prompt="拖拽鼠标划定模板图片区域, 按 Esc 取消")
            if result is not None:
                if cropped is not None:
                    img = cropped
                else:
                    QApplication.processEvents()
                    time.sleep(0.05)
                    x, y, w, h = result
                    try:
                        with mss.mss() as sct:
                            monitor = {"top": y, "left": x, "width": w, "height": h}
                            sct_img = sct.grab(monitor)
                            img = np.ascontiguousarray(np.array(sct_img)[:, :, :3])
                    except Exception as e:
                        logger.error(f"截图捕获失败: {e}")
        finally:
            if main_win and state:
                main_win.restore_after_selection(state)

        if img is None:
            return

        # 保存到 exe/脚本所在目录的 screenshots 子目录
        save_dir = SCREENSHOTS_DIR
        os.makedirs(save_dir, exist_ok=True)
        timestamp = int(time.time() * 1000)
        save_path = os.path.join(save_dir, f"capture_{timestamp}.png")
        # imwrite 不支持中文路径，改用 imencode + tofile（numpy 原生写入支持中文）
        success, encoded = cv2.imencode(".png", img)
        if not success:
            logger.error("截图编码失败")
            return
        encoded.tofile(save_path)

        self._image_path = save_path
        pixmap = QPixmap(save_path)
        self.img_preview.setPixmap(pixmap.scaled(
            60, 60, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
        ))
        self.img_preview.setStyleSheet(
            f"border: 1px solid {CLR_CARD_BORDER}; border-radius: 6px;"
        )
        self._update_image_warning()

    def _on_click_on_match_changed(self, checked: bool) -> None:
        if checked:
            self._click_on_match = True
            self._multi_region = False
            self.chk_multi_region.blockSignals(True)
            self.chk_multi_region.setChecked(False)
            self.chk_multi_region.blockSignals(False)
            # 更新 UI
            self.btn_region.setText("设定")
            self.btn_region.setDisabled(True)
            self.label_region.setText("跟随识别图")
            self.label_region.setStyleSheet(
                f"color: {CLR_BTN_PRIMARY}; font-weight: bold; font-size: 12px;"
            )
        else:
            # 取消勾选：恢复手动设定区域模式（与 _on_multi_region_changed 的 False 分支对齐）
            self._click_on_match = False
            self.btn_region.setDisabled(False)
            self.btn_region.setText("设定")
            if self._region:
                x, y, w, h = self._region
                self.label_region.setText(f"{x},{y}  {w}×{h}")
                self.label_region.setStyleSheet(
                    f"color: {CLR_TEXT_MAIN}; font-weight: bold; font-size: 12px;"
                )
            else:
                self.label_region.setText("未设定")
                self.label_region.setStyleSheet(f"color: {CLR_TEXT_SUB}; font-size: 12px;")

    def _on_multi_region_changed(self, checked: bool) -> None:
        if checked:
            self._multi_region = True
            self._click_on_match = False
            self.chk_click_on_match.blockSignals(True)
            self.chk_click_on_match.setChecked(False)
            self.chk_click_on_match.blockSignals(False)
            # 更新 UI
            self.btn_region.setText("框选")
            self.btn_region.setDisabled(False)
            if self._regions:
                self.label_region.setText(f"{len(self._regions)} 个区域")
                self.label_region.setStyleSheet(
                    f"color: {CLR_TEXT_MAIN}; font-weight: bold; font-size: 12px;"
                )
            else:
                self.label_region.setText("未设定")
                self.label_region.setStyleSheet(f"color: {CLR_TEXT_SUB}; font-size: 12px;")
        else:
            self._multi_region = False
            # 恢复单区域模式 UI
            self.btn_region.setText("设定")
            self.btn_region.setDisabled(False)
            if self._region:
                x, y, w, h = self._region
                self.label_region.setText(f"{x},{y}  {w}×{h}")
                self.label_region.setStyleSheet(
                    f"color: {CLR_TEXT_MAIN}; font-weight: bold; font-size: 12px;"
                )
            else:
                self.label_region.setText("未设定")
                self.label_region.setStyleSheet(f"color: {CLR_TEXT_SUB}; font-size: 12px;")

    def _on_click_mode_changed(self, text: str) -> None:
        if text == "单击":
            self._click_count = 1
        elif text == "双击":
            self._click_count = 2
        else:
            try:
                val = int(text)
                self._click_count = max(1, min(9999, val))
            except ValueError:
                self._click_count = 1

    def _on_click_mode_editing_finished(self) -> None:
        """输入框失焦或回车时的格式化与合法性修正 (BUG-16)."""
        text = self.combo_click_mode.currentText().strip()
        if text == "单击":
            self._click_count = 1
            return
        if text == "双击":
            self._click_count = 2
            return
        try:
            val = int(text)
            clamped = max(1, min(9999, val))
            self._click_count = clamped
            if clamped == 1:
                self.combo_click_mode.setCurrentText("单击")
            elif clamped == 2:
                self.combo_click_mode.setCurrentText("双击")
            else:
                self.combo_click_mode.setCurrentText(str(clamped))
        except (ValueError, TypeError):
            self._click_count = 1
            self.combo_click_mode.setCurrentText("单击")

    def _on_slider_changed(self, value: int) -> None:
        self.label_threshold.setText(f"{value}%")

    def _on_set_region(self) -> None:
        """设定点击区域 (BUG-01, BUG-02, BUG-03)."""
        main_win = self.window()
        state = main_win.prepare_selection_mode() if main_win else None
        try:
            if self._multi_region:
                result = overlay_selector.get_regions()
            else:
                result = overlay_selector.get_region()
        finally:
            if main_win and state:
                main_win.restore_after_selection(state)
        if self._multi_region:
            if result:  # 非空列表
                self._regions = result
                self.label_region.setText(f"{len(result)} 个区域")
                self.label_region.setStyleSheet(
                    f"color: {CLR_TEXT_MAIN}; font-weight: bold; font-size: 12px;"
                )
            # result 为 None 时不清空已有 _regions (用户按了 Esc 取消本次)
        else:
            if result is not None:
                x, y, w, h = result
                self._region = (x, y, w, h)
                self.label_region.setText(f"{x},{y}  {w}×{h}")
                self.label_region.setStyleSheet(
                    f"color: {CLR_TEXT_MAIN}; font-weight: bold; font-size: 12px;"
                )
            # Esc 取消时保留已有区域，与多选模式行为对齐（task_card.py 多选分支注释）

    def _validate_delay(self) -> None:
        for edit in (self.edit_delay_min, self.edit_delay_max):
            if edit.validator():
                edit.setText(edit.validator().fixup(edit.text()))
        if not self.edit_delay_min.text().strip():
            self.edit_delay_min.setText("200")
        if not self.edit_delay_max.text().strip():
            self.edit_delay_max.setText("500")
        try:
            mn = int(self.edit_delay_min.text())
            mx = int(self.edit_delay_max.text())
            if mn > mx:
                self.edit_delay_max.setText(str(min(9999, mn + 100)))
        except ValueError:
            pass

    def _validate_cooldown(self) -> None:
        for edit in (self.edit_cooldown_min, self.edit_cooldown_max):
            if edit.validator():
                edit.setText(edit.validator().fixup(edit.text()))
        if not self.edit_cooldown_min.text().strip():
            self.edit_cooldown_min.setText("0")
        if not self.edit_cooldown_max.text().strip():
            self.edit_cooldown_max.setText("0")
        try:
            mn = int(self.edit_cooldown_min.text())
            mx = int(self.edit_cooldown_max.text())
            if mn > mx:
                self.edit_cooldown_max.setText(str(mn))
        except ValueError:
            pass

    # ---- 图片路径有效性检查 ----

    def _update_image_warning(self) -> None:
        if self._image_path and not os.path.exists(self._image_path):
            self.img_preview.setText("图片文件已丢失")
            self.img_preview.setStyleSheet(
                "border: 2px dashed #EF5350; color: #EF5350; font-size: 10px;"
                "border-radius: 6px;"
            )

    def check_image_exists(self) -> bool:
        """检查图片文件是否存在, 若不存在则更新预览提示."""
        if self._image_path and not os.path.exists(self._image_path):
            self._update_image_warning()
            return False
        return True

    # ---- 边界按钮控制 ----

    def update_move_buttons(self, is_first: bool, is_last: bool) -> None:
        self.btn_up.setDisabled(is_first)
        self.btn_down.setDisabled(is_last)

    def set_running_locked(self, locked: bool) -> None:
        """运行期控件锁定与解锁 (BUG-09, R3, P2-5, PRE-02)."""
        self.btn_capture.setEnabled(not locked)
        self.btn_upload.setEnabled(not locked)
        # 模式守卫 P2-5：解锁时仅在未勾选“跟随识别图”时才启用 btn_region，杜绝状态冲突
        self.btn_region.setEnabled(not locked and not self._click_on_match)
        self.btn_delete.setEnabled(not locked)
        self.name_edit.setEnabled(not locked)
        self.combo_click_mode.setEnabled(not locked)
        # 锁定区域模式复选框（R3）：防运行期勾选反向触发 btn_region 启用引发遮罩与引擎点击冲突
        self.chk_click_on_match.setEnabled(not locked)
        self.chk_multi_region.setEnabled(not locked)
        # 运行期一并锁定上移/下移，防止运行中挪动卡片引发删除锁泄漏与布局竞态
        self.btn_up.setEnabled(not locked)
        self.btn_down.setEnabled(not locked)
        # 补全锁定数值滑块与延迟冷却输入项 (PRE-02)
        self.slider.setEnabled(not locked)
        self.edit_delay_min.setEnabled(not locked)
        self.edit_delay_max.setEnabled(not locked)
        self.edit_cooldown_min.setEnabled(not locked)
        self.edit_cooldown_max.setEnabled(not locked)
        # 新增控件安全锁定（兼容未来属性挂载）
        if hasattr(self, "chk_enabled"):
            self.chk_enabled.setEnabled(not locked)
        if hasattr(self, "btn_copy"):
            self.btn_copy.setEnabled(not locked)
        if hasattr(self, "btn_test"):
            self.btn_test.setEnabled(not locked)
        if hasattr(self, "btn_roi"):
            self.btn_roi.setEnabled(not locked)
        if hasattr(self, "btn_roi_reset"):
            self.btn_roi_reset.setEnabled(not locked)

    # ---- 名称校验 ----

    def _validate_name(self) -> None:
        """校验名称：不能为空，不能与其他卡片重名."""
        text = self.name_edit.text().strip()
        main_win = self._find_main_window()

        if not text:
            # 空名称 → 自动生成唯一名称
            if main_win:
                new_name = main_win._next_task_name()
                if self._last_valid_name and self._last_valid_name != new_name:
                    if hasattr(main_win, "on_task_renamed"):
                        main_win.on_task_renamed(self._last_valid_name, new_name)
                self.name_edit.setText(new_name)
                self._last_valid_name = new_name
            self._name_has_error = False
            self._set_name_normal_style()
            self._clear_sibling_errors(main_win)
            if main_win:
                main_win._refresh_stop_task_combo()  # 名称变更后同步条件一下拉框
            return

        if main_win:
            my_name = text
            duplicates = [
                c for c in main_win._task_cards
                if c is not self and c.name_edit.text().strip() == my_name
            ]
            if duplicates:
                self._name_has_error = True
                self._set_name_error_style()
                # 同时标红所有同名的兄弟卡片
                for c in duplicates:
                    c._name_has_error = True
                    c._set_name_error_style()
                return

            # 校验通过 → 先迁移自身旧名数据腾出键位，再恢复同名兄弟卡片并迁移其数据 (BUG-04 细节闭环)
            self._name_has_error = False
            if self._last_valid_name and self._last_valid_name != my_name:
                if hasattr(main_win, "on_task_renamed"):
                    main_win.on_task_renamed(self._last_valid_name, my_name)
            self._last_valid_name = my_name
            self._clear_sibling_errors(main_win)

        self._set_name_normal_style()
        if main_win:
            main_win._refresh_stop_task_combo()  # 名称变更后同步条件一下拉框

    def _clear_sibling_errors(self, main_win) -> None:
        """恢复所有与自己不同名且确实不再重复的兄弟卡片样式."""
        if not main_win:
            return
        my_name = self.name_edit.text().strip()
        for c in main_win._task_cards:
            if c is self:
                continue
            other_name = c.name_edit.text().strip()
            # 只恢复确实不再重复的兄弟
            if other_name and other_name != my_name:
                has_other_dup = any(
                    x is not c and x.name_edit.text().strip() == other_name
                    for x in main_win._task_cards
                )
                if not has_other_dup:
                    c._name_has_error = False
                    c._set_name_normal_style()
                    # 补齐失步保护：当兄弟卡片解除重名错误恢复合法时，同步更新其有效名并迁移数据 (BUG-04)
                    if c._last_valid_name and c._last_valid_name != other_name:
                        if hasattr(main_win, "on_task_renamed"):
                            main_win.on_task_renamed(c._last_valid_name, other_name)
                        c._last_valid_name = other_name

    def _find_main_window(self):
        """向上遍历 parent 链找到 MainWindow."""
        p = self.parent()
        while p and not getattr(p, '_is_main_window', False):
            p = p.parent()
        if p is None:
            logger.warning("CollapsibleTaskCard: 未找到 MainWindow parent，名称校验静默跳过")
        return p

    def _set_name_error_style(self) -> None:
        self.name_edit.setStyleSheet(
            f"background: #FFF0F0; border: 1px solid #EF5350;"
            f"border-radius: 6px; padding: 4px 8px; font-size: 13px;"
            f"color: {CLR_TEXT_MAIN};"
        )

    def _set_name_normal_style(self) -> None:
        color = CLR_TEXT_SUB if not self._is_enabled else CLR_TEXT_MAIN
        self.name_edit.setStyleSheet(
            f"background: #F0F7FF; border: 1px solid {CLR_CARD_BORDER};"
            f"border-radius: 6px; padding: 4px 8px; font-size: 13px;"
            f"color: {color};"
        )

    # ---- 测试识别与高亮反馈 (FEAT-02) ----

    def _reset_test_button(self) -> None:
        self.btn_test.set_icon("target", CLR_TEXT_MAIN, CLR_BTN_PRIMARY)
        self.btn_test.setText("测试识别")
        self.btn_test.setStyleSheet(f"""
            QPushButton {{
                background: {CLR_CONTENT_BG}; border: 1px solid {CLR_CARD_BORDER};
                border-radius: 6px; padding: 6px 8px; font-size: 12px;
                color: {CLR_TEXT_MAIN};
            }}
            QPushButton:hover {{ border-color: #B0CDE8; color: {CLR_BTN_PRIMARY}; }}
            QPushButton:disabled {{ background: #F0F4F8; color: {CLR_TEXT_SUB}; border-color: {CLR_CARD_BORDER}; }}
        """)

    def _set_test_btn_warning(self, text: str) -> None:
        self.btn_test.set_icon("alert-triangle", "#F57C00", "#E65100")
        self.btn_test.setText(text)
        self.btn_test.setStyleSheet(f"""
            QPushButton {{
                background: #FFF8E1; border: 1px solid #FFB74D;
                border-radius: 6px; padding: 6px 8px; font-size: 12px;
                color: #E65100; font-weight: bold;
            }}
            QPushButton:hover {{ border-color: #FFA726; color: #E65100; }}
            QPushButton:disabled {{ background: #F0F4F8; color: {CLR_TEXT_SUB}; border-color: {CLR_CARD_BORDER}; }}
        """)
        self._test_btn_timer.start(2000)

    def close_highlight_overlay(self) -> None:
        """安全关闭并清理测试识别高亮浮窗，同时复位测试按钮状态."""
        if hasattr(self, "_highlight_timer") and self._highlight_timer.isActive():
            self._highlight_timer.stop()
        if hasattr(self, "_test_btn_timer") and self._test_btn_timer.isActive():
            self._test_btn_timer.stop()
            self._reset_test_button()
        if getattr(self, "_active_overlay", None) is not None:
            try:
                self._active_overlay.close()
            except (RuntimeError, Exception):
                pass
            self._active_overlay = None

    def _on_test_match(self) -> None:
        """单任务「测试识别」执行与全屏高亮反馈 (FEAT-02)."""
        if getattr(self, "_is_testing", False):
            return
        self._is_testing = True

        # 预先安全关闭旧高亮浮窗
        self.close_highlight_overlay()

        try:
            if not self._image_path or not os.path.exists(self._image_path):
                self._set_test_btn_warning("未设图片")
                return

            template = image_engine.load_template(self._image_path)
            if template is None:
                self._set_test_btn_warning("未设图片")
                return

            # 尺寸预检 (P2-B)
            if self._search_region is not None:
                rx, ry, rw, rh = self._search_region
                th, tw = template.shape[:2]
                if tw > rw or th > rh:
                    self._set_test_btn_warning("范围过小")
                    return

            main_win = self.window()
            state = main_win.prepare_selection_mode() if main_win else None
            match_res = None
            try:
                screenshot = image_engine.take_screenshot()
                match_res = image_engine.find_best_match(
                    screenshot, template, search_region=self._search_region
                )
            except Exception as e:
                logger.error(f"测试识别异常: {e}")
                self._set_test_btn_warning("识别失败")
                return
            finally:
                if main_win and state:
                    main_win.restore_after_selection(state)

            threshold = self.slider.value() / 100.0
            if match_res is None:
                self._set_test_btn_warning("未匹配")
                return

            mx, my, mw, mh, score = match_res
            score_pct = score * 100.0
            passed = score >= threshold

            if passed:
                self.btn_test.set_icon("check", "#43A047", "#2E7D32")
                txt_clr = "#2E7D32"
            else:
                self.btn_test.set_icon("info", "#F57C00", "#E65100")
                txt_clr = "#E65100"
            self.btn_test.setText(f"{score_pct:.1f}%")
            self.btn_test.setStyleSheet(f"""
                QPushButton {{
                    background: {CLR_CONTENT_BG}; border: 1px solid {CLR_CARD_BORDER};
                    border-radius: 6px; padding: 6px 8px; font-size: 12px;
                    color: {txt_clr}; font-weight: bold;
                }}
                QPushButton:hover {{ border-color: #B0CDE8; color: {CLR_BTN_PRIMARY}; }}
                QPushButton:disabled {{ background: #F0F4F8; color: {CLR_TEXT_SUB}; border-color: {CLR_CARD_BORDER}; }}
            """)
            self._test_btn_timer.start(2000)

            # 弹出透明高亮浮窗并安全管理生命周期
            overlay = _MatchHighlightOverlay(
                task_name=self.name_edit.text().strip() or "未命名任务",
                score_pct=score_pct,
                passed=passed,
                rx=mx,
                ry=my,
                rw=mw,
                rh=mh,
            )
            self._active_overlay = overlay
            overlay.destroyed.connect(
                lambda *_: setattr(self, "_active_overlay", None) if getattr(self, "_active_overlay", None) is overlay else None
            )
            overlay.show()
            self._highlight_timer.start(1200)
        finally:
            self._is_testing = False

    # ---- 识别范围 (ROI) 设定与重置 (FEAT-04) ----

    def _on_set_roi(self) -> None:
        """限定图像识别范围 ROI."""
        main_win = self.window()
        state = main_win.prepare_selection_mode() if main_win else None
        try:
            result = overlay_selector.get_region(prompt="拖拽鼠标划定【图像识别范围】, 按 Esc 取消")
        finally:
            if main_win and state:
                main_win.restore_after_selection(state)
        if result is not None:
            x, y, w, h = result
            self._search_region = (x, y, w, h)
            self.label_roi.setText(f"({x}, {y}) {w}×{h}")
            self.label_roi.setStyleSheet(
                f"color: {CLR_BTN_PRIMARY}; font-weight: bold; font-size: 12px;"
            )
            self.btn_roi_reset.setVisible(True)

    def _on_reset_roi(self) -> None:
        """重置识别范围为全屏识别."""
        self._search_region = None
        self.label_roi.setText("全屏识别")
        self.label_roi.setStyleSheet(f"color: {CLR_TEXT_SUB}; font-size: 12px;")
        self.btn_roi_reset.setVisible(False)

    # ---- 数值校验回填 (FEAT-06) ----

    def validate_inputs(self) -> None:
        """任务卡片延迟与冷却输入框回填与归一化 (FEAT-06)."""
        for edit in (self.edit_delay_min, self.edit_delay_max, self.edit_cooldown_min, self.edit_cooldown_max):
            if edit.validator():
                edit.setText(edit.validator().fixup(edit.text()))
        self._validate_delay()
        self._validate_cooldown()
        self._on_click_mode_editing_finished()

    # ---- 配置完备性 ----

    def is_configured(self) -> bool:
        """任务是否配置完整: 已勾选启用 + 有图片 + 有区域(或勾选了跟随识别图)."""
        if not self.chk_enabled.isChecked():
            return False
        has_image = bool(self._image_path and os.path.exists(self._image_path))
        if self._click_on_match:
            return has_image
        if self._multi_region:
            return has_image and len(self._regions) > 0
        return has_image and self._region is not None

    # ---- 序列化 ----

    def to_dict(self) -> dict:
        self.validate_inputs()
        return {
            "name": self.name_edit.text().strip(),
            "enabled": self.chk_enabled.isChecked(),
            "image_path": self._image_path or "",
            "threshold": self.slider.value(),
            "search_region": list(self._search_region) if self._search_region else None,
            "region": list(self._region) if self._region else None,
            "click_on_match": self._click_on_match,
            "multi_region": self._multi_region,
            "regions": [list(r) for r in self._regions],
            "click_count": self._click_count,
            "delay_min": int(self.edit_delay_min.text() or "200"),
            "delay_max": int(self.edit_delay_max.text() or "500"),
            "cooldown_min": int(self.edit_cooldown_min.text() or "0"),
            "cooldown_max": int(self.edit_cooldown_max.text() or "0"),
        }

    def from_dict(self, data: dict) -> None:
        self.name_edit.setText((data.get("name") or "").strip())  # or "" 防 None
        self._last_valid_name = self.name_edit.text().strip()
        enabled = data.get("enabled", True)
        self.chk_enabled.setChecked(enabled)
        self._is_enabled = enabled
        self._update_header_style()
        self._image_path = data.get("image_path") or None
        if self._image_path:
            pixmap = QPixmap(self._image_path)
            if pixmap.isNull():
                self.img_preview.setText("无效图片")
                self.img_preview.setStyleSheet(
                    "border: 2px dashed #EF5350; color: #EF5350; font-size: 10px;"
                    "border-radius: 6px;"
                )
                self._image_path = None
            else:
                self.img_preview.setPixmap(pixmap.scaled(
                    60, 60, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                ))
                self.img_preview.setStyleSheet(
                    f"border: 1px solid {CLR_CARD_BORDER}; border-radius: 6px;"
                )
                self._update_image_warning()
        else:
            self.img_preview.setText("无图片")
            self.img_preview.setStyleSheet(
                f"border: 2px dashed {CLR_CARD_BORDER}; color: {CLR_TEXT_SUB}; font-size: 11px;"
                "border-radius: 6px;"
            )
        th = data.get("threshold", 90)
        try:
            th_f = float(th)
            if th_f <= 1.0:
                th_val = int(round(th_f * 100))
            else:
                th_val = int(round(th_f))
        except (ValueError, TypeError):
            th_val = 90
        self.slider.setValue(max(0, min(100, th_val)))

        sr = data.get("search_region")
        if sr and isinstance(sr, (list, tuple)) and len(sr) == 4:
            try:
                x, y, w, h = [int(v) for v in sr]
                if w > 0 and h > 0:
                    self._search_region = (x, y, w, h)
                    self.label_roi.setText(f"({x}, {y}) {w}×{h}")
                    self.label_roi.setStyleSheet(
                        f"color: {CLR_BTN_PRIMARY}; font-weight: bold; font-size: 12px;"
                    )
                    self.btn_roi_reset.setVisible(True)
                else:
                    self._on_reset_roi()
            except Exception:
                self._on_reset_roi()
        else:
            self._on_reset_roi()
        region = data.get("region")
        if region and isinstance(region, (list, tuple)) and len(region) == 4:
            try:
                x, y, w, h = [int(v) for v in region]
                if w > 0 and h > 0:
                    self._region = (x, y, w, h)
                    self.label_region.setText(f"{x},{y}  {w}×{h}")
                    self.label_region.setStyleSheet(
                        f"color: {CLR_TEXT_MAIN}; font-weight: bold; font-size: 12px;"
                    )
            except (ValueError, TypeError):
                self._region = None
                if not data.get("multi_region", False):
                    self.label_region.setText("未设定")
                    self.label_region.setStyleSheet(f"color: {CLR_TEXT_SUB}; font-size: 12px;")
        else:
            self._region = None
            if not data.get("multi_region", False):
                self.label_region.setText("未设定")
                self.label_region.setStyleSheet(f"color: {CLR_TEXT_SUB}; font-size: 12px;")

        d_min = data.get("delay_min")
        if d_min is None:
            d_min = data.get("min_delay", 200)
        d_max = data.get("delay_max")
        if d_max is None:
            d_max = data.get("max_delay", 500)
        c_min = data.get("cooldown_min")
        if c_min is None:
            c_min = data.get("cooldown", 0)
        c_max = data.get("cooldown_max")
        if c_max is None:
            c_max = data.get("cooldown", 0)
        self.edit_delay_min.setText(str(200 if d_min is None else d_min))
        self.edit_delay_max.setText(str(500 if d_max is None else d_max))
        self.edit_cooldown_min.setText(str(0 if c_min is None else c_min))
        self.edit_cooldown_max.setText(str(0 if c_max is None else c_max))

        if data.get("click_on_match", False):
            self.chk_click_on_match.setChecked(True)
        if data.get("multi_region", False):
            self._multi_region = True
            self.chk_multi_region.setChecked(True)
            self.btn_region.setText("框选")
        raw_regions = data.get("regions") or []
        if isinstance(raw_regions, (list, tuple)):
            valid_regs = []
            for r in raw_regions:
                if isinstance(r, (list, tuple)) and len(r) == 4:
                    try:
                        rx, ry, rw, rh = [int(v) for v in r]
                        if rw > 0 and rh > 0:
                            valid_regs.append((rx, ry, rw, rh))
                    except (ValueError, TypeError):
                        pass
            self._regions = valid_regs
            if self._multi_region and self._regions:
                self.label_region.setText(f"{len(self._regions)} 个区域")
                self.label_region.setStyleSheet(
                    f"color: {CLR_TEXT_MAIN}; font-weight: bold; font-size: 12px;"
                )

        # 向后兼容: 旧配置 click_mode → click_count
        click_count = data.get("click_count")
        if click_count is None:
            old_mode = data.get("click_mode", "single")
            click_count = {"single": 1, "double": 2}.get(old_mode, 1)
        if click_count == 1:
            self.combo_click_mode.setCurrentText("单击")
        elif click_count == 2:
            self.combo_click_mode.setCurrentText("双击")
        else:
            self.combo_click_mode.setCurrentText(str(click_count))
        # 统一调用校验与钳制，确保 _click_count 与延迟/冷却数值 100% 合法（移除原末尾未校验的 self._click_count = click_count）
        self.validate_inputs()



# ============================================================
# 主窗口
# ============================================================

