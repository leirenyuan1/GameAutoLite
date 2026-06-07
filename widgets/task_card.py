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

from PyQt6.QtCore import Qt, pyqtSignal, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QPixmap, QIntValidator, QColor
from PyQt6.QtWidgets import (
    QFrame, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QCheckBox, QSlider,
    QComboBox, QFileDialog, QGraphicsDropShadowEffect, QSizePolicy,
)

import overlay_selector
from config_manager import SCREENSHOTS_DIR
from styles.colors import (
    CLR_ACCENT_LINE, CLR_CARD_BORDER, CLR_CARD_HEADER,
    CLR_TEXT_MAIN, CLR_TEXT_SUB, CLR_BTN_PRIMARY,
    CLR_BTN_DANGER, CLR_CARD_BG, CLR_CONTENT_BG,
)

if TYPE_CHECKING:
    from main_window import MainWindow

logger = logging.getLogger(__name__)


class CollapsibleTaskCard(QFrame):
    """可折叠的任务配置卡片."""

    removed = pyqtSignal(object)
    moved_up = pyqtSignal(object)
    moved_down = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._image_path: str | None = None
        self._region: tuple[int, int, int, int] | None = None
        self._click_on_match = False
        self._multi_region = False
        self._regions: list[tuple[int, int, int, int]] = []
        self._click_count = 1
        self._expanded = True
        self._is_deleting = False
        self._name_has_error = False  # 标记当前卡片名称是否有校验错误
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
        self._update_header_style()

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

        # 折叠/展开箭头
        self.btn_arrow = QPushButton("▼")
        self.btn_arrow.setFixedSize(32, 32)
        self.btn_arrow.setStyleSheet(
            "QPushButton { border: none; font-size: 16px; color: #7A9AB8; }"
            "QPushButton:hover { color: #2196F3; }"
        )
        self.btn_arrow.clicked.connect(self._toggle_expand)
        header_layout.addWidget(self.btn_arrow)

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

        # 操作按钮
        self.btn_up = self._make_header_btn("↑")
        self.btn_up.clicked.connect(lambda: self.moved_up.emit(self))
        self.btn_down = self._make_header_btn("↓")
        self.btn_down.clicked.connect(lambda: self.moved_down.emit(self))
        self.btn_delete = QPushButton("✕")
        self.btn_delete.setFixedSize(30, 30)
        self.btn_delete.setStyleSheet(f"""
            QPushButton {{
                background: transparent; border: none; border-radius: 6px;
                font-size: 14px; font-weight: bold; color: {CLR_BTN_DANGER};
            }}
            QPushButton:hover {{
                background: {CLR_BTN_DANGER}; color: #fff;
            }}
        """)
        self.btn_delete.clicked.connect(lambda: self.removed.emit(self))

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

        # ---- 行: 上传识别图 + 缩略图预览 ----
        row2 = QHBoxLayout()
        self.btn_upload = QPushButton("🖼 上传识别图")
        self.btn_upload.setStyleSheet(f"""
            QPushButton {{
                background: {CLR_CONTENT_BG}; border: 1px solid {CLR_CARD_BORDER};
                border-radius: 6px; padding: 6px 12px; font-size: 12px;
                color: {CLR_TEXT_MAIN};
            }}
            QPushButton:hover {{ border-color: {CLR_BTN_PRIMARY}; color: {CLR_BTN_PRIMARY}; }}
        """)
        self.btn_upload.clicked.connect(self._on_upload_image)

        self.img_preview = QLabel()
        self.img_preview.setFixedSize(60, 60)
        self.img_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.img_preview.setStyleSheet(
            f"border: 2px dashed {CLR_CARD_BORDER}; color: {CLR_TEXT_SUB}; font-size: 11px;"
            "border-radius: 6px;"
        )
        self.img_preview.setText("无图片")

        self.btn_capture = QPushButton("📷 截图上传")
        self.btn_capture.setStyleSheet(f"""
            QPushButton {{
                background: {CLR_CONTENT_BG}; border: 1px solid {CLR_CARD_BORDER};
                border-radius: 6px; padding: 6px 12px; font-size: 12px;
                color: {CLR_TEXT_MAIN};
            }}
            QPushButton:hover {{ border-color: {CLR_BTN_PRIMARY}; color: {CLR_BTN_PRIMARY}; }}
        """)
        self.btn_capture.clicked.connect(self._on_screenshot_capture)

        row2.addWidget(self.btn_upload)
        row2.addWidget(self.btn_capture)
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
        self.slider.wheelEvent = lambda event: event.ignore()
        self.slider.valueChanged.connect(self._on_slider_changed)
        row3.addWidget(self.slider, 1)

        self.label_threshold = QLabel("90%")
        self.label_threshold.setMinimumWidth(36)
        self.label_threshold.setStyleSheet(_LABEL_STYLE)
        row3.addWidget(self.label_threshold)
        content_layout.addWidget(row3_container)

        # ---- 行: 设定点击区域 ----
        row4 = QHBoxLayout()
        row4.addWidget(_row_label("点击区域:"))

        self.btn_region = QPushButton("⊕ 设定")
        self.btn_region.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self.btn_region.setStyleSheet(f"""
            QPushButton {{
                background: {CLR_CONTENT_BG}; border: 1px solid {CLR_CARD_BORDER};
                border-radius: 6px; padding: 6px 12px; font-size: 12px;
                color: {CLR_TEXT_MAIN};
            }}
            QPushButton:hover {{ border-color: {CLR_BTN_PRIMARY}; color: {CLR_BTN_PRIMARY}; }}
        """)
        self.btn_region.clicked.connect(self._on_set_region)

        self.label_region = QLabel("未设定")
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
        row4c.addWidget(self.combo_click_mode)

        lbl_suffix = QLabel("击（可填入1~9999的阿拉伯数字）")
        lbl_suffix.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        lbl_suffix.setStyleSheet(_SUB_STYLE)
        row4c.addWidget(lbl_suffix)
        content_layout.addLayout(row4c)

        # ---- 分隔线 ----
        content_layout.addWidget(self._make_hline())

        # ---- 随机延迟 + 点击后冷却 (QGridLayout) ----
        grid = QGridLayout()
        grid.setVerticalSpacing(6)
        grid.setHorizontalSpacing(6)

        # 行0: 随机延迟
        grid.addWidget(_row_label("随机延迟:"), 0, 0)
        grid.addWidget(_small_label("最小", 30), 0, 1)

        self.edit_delay_min = QLineEdit("200")
        self.edit_delay_min.setMinimumWidth(50)
        self.edit_delay_min.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.edit_delay_min.setValidator(QIntValidator(0, 9999))
        self.edit_delay_min.editingFinished.connect(self._validate_delay)
        grid.addWidget(self.edit_delay_min, 0, 2)

        grid.addWidget(_small_label("ms", 24), 0, 3)
        grid.addWidget(_small_label("~", 16), 0, 4)
        grid.addWidget(_small_label("最大", 30), 0, 5)

        self.edit_delay_max = QLineEdit("500")
        self.edit_delay_max.setMinimumWidth(50)
        self.edit_delay_max.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.edit_delay_max.setValidator(QIntValidator(0, 9999))
        self.edit_delay_max.editingFinished.connect(self._validate_delay)
        grid.addWidget(self.edit_delay_max, 0, 6)

        grid.addWidget(_small_label("ms", 24), 0, 7)

        # 行1: 点击后冷却
        grid.addWidget(_row_label("点击后冷却:"), 1, 0)
        grid.addWidget(_small_label("最小", 30), 1, 1)

        self.edit_cooldown_min = QLineEdit("0")
        self.edit_cooldown_min.setMinimumWidth(50)
        self.edit_cooldown_min.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.edit_cooldown_min.setValidator(QIntValidator(0, 999999))
        self.edit_cooldown_min.editingFinished.connect(self._validate_cooldown)
        grid.addWidget(self.edit_cooldown_min, 1, 2)

        grid.addWidget(_small_label("ms", 24), 1, 3)
        grid.addWidget(_small_label("~", 16), 1, 4)
        grid.addWidget(_small_label("最大", 30), 1, 5)

        self.edit_cooldown_max = QLineEdit("0")
        self.edit_cooldown_max.setMinimumWidth(50)
        self.edit_cooldown_max.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.edit_cooldown_max.setValidator(QIntValidator(0, 999999))
        self.edit_cooldown_max.editingFinished.connect(self._validate_cooldown)
        grid.addWidget(self.edit_cooldown_max, 1, 6)

        grid.addWidget(_small_label("ms", 24), 1, 7)

        # 列拉伸：输入框列可伸缩
        grid.setColumnStretch(2, 1)
        grid.setColumnStretch(6, 1)

        content_layout.addLayout(grid)

        root.addWidget(self.content_widget)

        # 默认展开
        self._expanded = True
        self.content_widget.setVisible(True)
        self.btn_arrow.setText("▼")

        # 初始阴影
        self.setGraphicsEffect(shadow)

    def _make_hline(self) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFixedHeight(1)
        line.setStyleSheet(f"background: {CLR_CARD_BORDER}; border: none;")
        return line

    def _make_header_btn(self, text: str) -> QPushButton:
        btn = QPushButton(text)
        btn.setFixedSize(28, 28)
        btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; border: none; border-radius: 6px;
                font-size: 13px; color: {CLR_TEXT_SUB};
            }}
            QPushButton:hover {{
                background: {CLR_CONTENT_BG}; color: {CLR_BTN_PRIMARY};
            }}
        """)
        return btn

    def _update_header_style(self) -> None:
        if self._expanded:
            self._header.setStyleSheet(f"""
                #card_header {{
                    background: {CLR_CARD_HEADER};
                    border: 1px solid {CLR_CARD_BORDER};
                    border-bottom: none;
                    border-top-left-radius: 10px;
                    border-top-right-radius: 10px;
                }}
            """)
        else:
            self._header.setStyleSheet(f"""
                #card_header {{
                    background: {CLR_CARD_HEADER};
                    border: 1px solid {CLR_CARD_BORDER};
                    border-radius: 10px;
                }}
            """)

    def _toggle_expand(self) -> None:
        if self._is_deleting:
            return
        if self._expanded:
            self._collapse()
        else:
            self._expand()

    def _expand(self) -> None:
        self._expanded = True
        self.btn_arrow.setText("▼")
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

    def _collapse(self) -> None:
        self._expanded = False
        self.btn_arrow.setText("▶")
        self._update_header_style()

        cur_h = self.content_widget.height()
        anim = QPropertyAnimation(self.content_widget, b"maximumHeight", self)
        anim.setDuration(180)
        anim.setStartValue(cur_h)
        anim.setEndValue(0)
        anim.setEasingCurve(QEasingCurve.Type.InCubic)
        anim.finished.connect(lambda: self.content_widget.setVisible(False))
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

    def set_collapsed(self, collapsed: bool) -> None:
        """外部设置初始折叠状态（无动画）."""
        if collapsed:
            self._expanded = False
            self.btn_arrow.setText("▶")
            self.content_widget.setVisible(False)
            self.content_widget.setMaximumHeight(0)
            self._update_header_style()
        else:
            self._expanded = True
            self.btn_arrow.setText("▼")
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
            self.img_preview.setText("⚠ 无效图片")
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
        """通过 overlay 框选屏幕区域, 截图并保存为模板图片."""
        main_win = self.window()
        geom = main_win.geometry() if main_win else None
        if main_win and main_win.isVisible():
            main_win._suppress_floating = True  # 抑制悬浮窗显示
            main_win.showMinimized()  # 最小化到任务栏，避免标题栏残留
        try:
            result = overlay_selector.get_region()
        finally:
            if main_win:
                main_win._suppress_floating = False  # 恢复悬浮窗控制
                if geom:
                    main_win.setGeometry(geom)
                main_win.showNormal()  # 从任务栏恢复
        if result is None:
            return
        x, y, w, h = result

        # 截取选定区域
        try:
            with mss.mss() as sct:
                monitor = {"top": y, "left": x, "width": w, "height": h}
                sct_img = sct.grab(monitor)
                img = np.array(sct_img)
                img = np.ascontiguousarray(img[:, :, :3])
        except Exception as e:
            logger.error(f"截图捕获失败: {e}")
            return

        # 保存到 exe/脚本所在目录的 screenshots 子目录
        save_dir = SCREENSHOTS_DIR
        os.makedirs(save_dir, exist_ok=True)
        timestamp = int(time.time() * 1000)
        save_path = os.path.join(save_dir, f"capture_{timestamp}.png")
        cv2.imwrite(save_path, img)

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
        if not checked:
            return  # 只处理勾选事件, 避免信号循环
        self._click_on_match = True
        self._multi_region = False
        self.chk_multi_region.blockSignals(True)
        self.chk_multi_region.setChecked(False)
        self.chk_multi_region.blockSignals(False)
        # 更新 UI
        self.btn_region.setText("⊕ 设定")
        self.btn_region.setDisabled(True)
        self.label_region.setText("跟随识别图")
        self.label_region.setStyleSheet(
            f"color: {CLR_BTN_PRIMARY}; font-weight: bold; font-size: 12px;"
        )

    def _on_multi_region_changed(self, checked: bool) -> None:
        if checked:
            self._multi_region = True
            self._click_on_match = False
            self.chk_click_on_match.blockSignals(True)
            self.chk_click_on_match.setChecked(False)
            self.chk_click_on_match.blockSignals(False)
            # 更新 UI
            self.btn_region.setText("⊕ 框选")
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
            self.btn_region.setText("⊕ 设定")
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

    def _on_slider_changed(self, value: int) -> None:
        self.label_threshold.setText(f"{value}%")

    def _on_set_region(self) -> None:
        # 隐藏主窗口避免遮挡
        main_win = self.window()
        geom = main_win.geometry() if main_win else None
        if main_win and main_win.isVisible():
            main_win._suppress_floating = True  # 抑制悬浮窗显示
            main_win.showMinimized()  # 最小化到任务栏，避免标题栏残留
        try:
            if self._multi_region:
                result = overlay_selector.get_regions()
            else:
                result = overlay_selector.get_region()
        finally:
            if main_win:
                main_win._suppress_floating = False  # 恢复悬浮窗控制
                if geom:
                    main_win.setGeometry(geom)
                main_win.showNormal()  # 从任务栏恢复
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
            else:
                self.label_region.setText("未设定")
                self.label_region.setStyleSheet(f"color: {CLR_TEXT_SUB}; font-size: 12px;")
                self._region = None

    def _validate_delay(self) -> None:
        try:
            mn = int(self.edit_delay_min.text())
            mx = int(self.edit_delay_max.text())
            if mn > mx:
                self.edit_delay_max.setText(str(mn + 100))
        except ValueError:
            pass

    def _validate_cooldown(self) -> None:
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
            self.img_preview.setText("⚠ 图片文件已丢失")
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

    # ---- 名称校验 ----

    def _validate_name(self) -> None:
        """校验名称：不能为空，不能与其他卡片重名."""
        text = self.name_edit.text().strip()
        main_win = self._find_main_window()

        if not text:
            # 空名称 → 自动生成唯一名称
            if main_win:
                self.name_edit.setText(main_win._next_task_name())
            self._name_has_error = False
            self._set_name_normal_style()
            self._clear_sibling_errors(main_win)
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

            # 校验通过 → 恢复自己和同名兄弟的正常样式
            self._name_has_error = False
            self._clear_sibling_errors(main_win)

        self._set_name_normal_style()

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
        self.name_edit.setStyleSheet(
            f"background: #F0F7FF; border: 1px solid {CLR_CARD_BORDER};"
            f"border-radius: 6px; padding: 4px 8px; font-size: 13px;"
            f"color: {CLR_TEXT_MAIN};"
        )

    # ---- 配置完备性 ----

    def is_configured(self) -> bool:
        """任务是否配置完整: 有图片 + 有区域(或勾选了跟随识别图)."""
        has_image = bool(self._image_path and os.path.exists(self._image_path))
        if self._click_on_match:
            return has_image
        if self._multi_region:
            return has_image and len(self._regions) > 0
        return has_image and self._region is not None

    # ---- 序列化 ----

    def to_dict(self) -> dict:
        return {
            "name": self.name_edit.text(),
            "image_path": self._image_path or "",
            "threshold": self.slider.value(),
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
        self.name_edit.setText(data.get("name", ""))
        self._image_path = data.get("image_path") or None
        if self._image_path:
            pixmap = QPixmap(self._image_path)
            if pixmap.isNull():
                self.img_preview.setText("⚠ 无效图片")
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
        self.slider.setValue(data.get("threshold", 90))
        region = data.get("region")
        if region and len(region) == 4:
            x, y, w, h = region
            self._region = (int(x), int(y), int(w), int(h))
            self.label_region.setText(f"{int(x)},{int(y)}  {int(w)}×{int(h)}")
            self.label_region.setStyleSheet(
                f"color: {CLR_TEXT_MAIN}; font-weight: bold; font-size: 12px;"
            )
        self.edit_delay_min.setText(str(data.get("delay_min", 200)))
        self.edit_delay_max.setText(str(data.get("delay_max", 500)))
        self.edit_cooldown_min.setText(str(data.get("cooldown_min", 0)))
        self.edit_cooldown_max.setText(str(data.get("cooldown_max", 0)))
        if data.get("click_on_match", False):
            self.chk_click_on_match.setChecked(True)
        # 多区域模式
        if data.get("multi_region", False):
            self._multi_region = True
            self.chk_multi_region.setChecked(True)
            self.btn_region.setText("⊕ 框选")
        raw_regions = data.get("regions", [])
        if raw_regions:
            self._regions = [tuple(int(v) for v in r) for r in raw_regions if len(r) == 4]
            if self._multi_region:
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
        self._click_count = click_count



# ============================================================
# 主窗口
# ============================================================

