"""停止条件页 (pages/stop_conditions_page.py)"""
from __future__ import annotations
from typing import TYPE_CHECKING

import logging
import math
import os
import re
import time

import cv2
import mss
import numpy as np
import overlay_selector
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap, QIntValidator
from PyQt6.QtWidgets import (
    QApplication, QFileDialog, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QCheckBox, QLineEdit, QSlider, QScrollArea,
    QFrame, QComboBox, QSizePolicy,
)
from config_manager import SCREENSHOTS_DIR
from styles.colors import (
    CLR_TEXT_MAIN, CLR_TEXT_SUB, CLR_CARD_BG, CLR_CARD_BORDER,
    CLR_BTN_PRIMARY, CLR_BTN_DANGER, CLR_CONTENT_BG,
    CLR_STATUS_WARN, CLR_BTN_SUCCESS,
)
from styles.icons import IconButton, ICON_BTN
from pages.utils import make_settings_card, DefaultIntValidator

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from main_window import MainWindow


class StopConditionsPage(QWidget):
    def __init__(self, main_win: 'MainWindow', parent=None):
        super().__init__(parent)
        self._main_win = main_win
        self.stop_image_path: str | None = None
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

        self.container = QWidget()
        self.container.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(self.container)
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
        self.chk_stop_enabled.toggled.connect(self.on_stop_enabled_toggled)
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
        self.chk_stop_cond1.toggled.connect(self.on_stop_cond1_toggled)
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

        c1_row.addWidget(QLabel("执行"))

        self.edit_stop_exec_count = QLineEdit("5")
        self.edit_stop_exec_count.setFixedWidth(64)
        self.edit_stop_exec_count.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.edit_stop_exec_count.setValidator(DefaultIntValidator(1, 99999, 5, self))
        self.edit_stop_exec_count.editingFinished.connect(self.validate_inputs)
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
        self.chk_stop_cond2.toggled.connect(self.on_stop_cond2_toggled)
        c2_row.addWidget(self.chk_stop_cond2)

        self.edit_stop_run_minutes = QLineEdit("10")
        self.edit_stop_run_minutes.setFixedWidth(64)
        self.edit_stop_run_minutes.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.edit_stop_run_minutes.setValidator(DefaultIntValidator(1, 99999, 10, self))
        self.edit_stop_run_minutes.editingFinished.connect(self.validate_inputs)
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
        self.chk_stop_cond3.toggled.connect(self.on_stop_cond3_toggled)
        c3_layout.addWidget(self.chk_stop_cond3)

        c3_img_row = QHBoxLayout()
        c3_img_row.setContentsMargins(0, 0, 0, 0)
        c3_img_row.setSpacing(8)

        self.btn_stop_img_upload = IconButton("image", CLR_TEXT_MAIN, CLR_BTN_PRIMARY, ICON_BTN)
        self.btn_stop_img_upload.setText("上传识别图")
        self.btn_stop_img_upload.setStyleSheet(f"""
            QPushButton {{
                background: {CLR_CONTENT_BG}; border: 1px solid {CLR_CARD_BORDER};
                border-radius: 6px; padding: 6px 12px; font-size: 12px; color: {CLR_TEXT_MAIN};
            }}
            QPushButton:hover {{ border-color: {CLR_BTN_PRIMARY}; color: {CLR_BTN_PRIMARY}; }}
            QPushButton:disabled {{ background: #F0F4F8; color: {CLR_TEXT_SUB}; border-color: {CLR_CARD_BORDER}; }}
        """)
        self.btn_stop_img_upload.clicked.connect(self.on_stop_img_upload)
        c3_img_row.addWidget(self.btn_stop_img_upload)

        self.btn_stop_img_capture = IconButton("camera", CLR_TEXT_MAIN, CLR_BTN_PRIMARY, ICON_BTN)
        self.btn_stop_img_capture.setText("截图上传")
        self.btn_stop_img_capture.setStyleSheet(f"""
            QPushButton {{
                background: {CLR_CONTENT_BG}; border: 1px solid {CLR_CARD_BORDER};
                border-radius: 6px; padding: 6px 12px; font-size: 12px; color: {CLR_TEXT_MAIN};
            }}
            QPushButton:hover {{ border-color: {CLR_BTN_PRIMARY}; color: {CLR_BTN_PRIMARY}; }}
            QPushButton:disabled {{ background: #F0F4F8; color: {CLR_TEXT_SUB}; border-color: {CLR_CARD_BORDER}; }}
        """)
        self.btn_stop_img_capture.clicked.connect(self.on_stop_img_capture)
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
        # 宽度区间：宽窗口下不拉满卡片，窄窗口下也保持可拖长度
        self.slider_stop_threshold.setMinimumWidth(200)
        self.slider_stop_threshold.setMaximumWidth(240)
        self.slider_stop_threshold.wheelEvent = lambda event: event.ignore()
        self.slider_stop_threshold.valueChanged.connect(
            lambda v: self.label_stop_threshold.setText(f"{v}%")
        )
        c3_slider_layout.addWidget(self.slider_stop_threshold, 1)

        self.label_stop_threshold = QLabel("90%")
        self.label_stop_threshold.setMinimumWidth(36)
        self.label_stop_threshold.setStyleSheet(f"color: {CLR_TEXT_MAIN}; font-size: 12px;")
        c3_slider_layout.addWidget(self.label_stop_threshold)
        c3_slider_layout.addStretch(1)  # 吸收多余宽度，保持整行左对齐
        c3_layout.addWidget(c3_slider_row)

        layout.addWidget(c3_card)

        # ---- 条件四：无匹配超时 ----
        c4_card, c4_layout = make_settings_card("无匹配超时")
        c4_row = QHBoxLayout()
        c4_row.setContentsMargins(0, 0, 0, 0)
        c4_row.setSpacing(8)

        self.chk_stop_cond4 = QCheckBox("连续")
        self.chk_stop_cond4.setStyleSheet(f"""
            QCheckBox {{ color: {CLR_TEXT_MAIN}; font-size: 13px; }}
            QCheckBox:disabled {{ color: {CLR_TEXT_SUB}; }}
        """)
        self.chk_stop_cond4.toggled.connect(self.on_stop_cond4_toggled)
        c4_row.addWidget(self.chk_stop_cond4)

        self.edit_stop_idle_minutes = QLineEdit("5")
        self.edit_stop_idle_minutes.setFixedWidth(64)
        self.edit_stop_idle_minutes.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.edit_stop_idle_minutes.setValidator(DefaultIntValidator(1, 99999, 5, self))
        self.edit_stop_idle_minutes.editingFinished.connect(self.validate_inputs)
        self.edit_stop_idle_minutes.setStyleSheet(f"""
            QLineEdit {{ background: white; border: 1px solid {CLR_CARD_BORDER};
                border-radius: 6px; padding: 4px 6px; font-size: 12px; color: {CLR_TEXT_MAIN}; }}
            QLineEdit:disabled {{ background: #F0F4F8; color: {CLR_TEXT_SUB}; }}
        """)
        c4_row.addWidget(self.edit_stop_idle_minutes)

        c4_row.addWidget(QLabel("分钟匹配不到目标图片则停止"))
        c4_row.addStretch(1)
        c4_layout.addLayout(c4_row)

        c4_warn = QLabel("建议时长大于游戏最长加载等待时间，避免中途误停")
        c4_warn.setStyleSheet(f"color: {CLR_TEXT_SUB}; font-size: 11px;")
        c4_warn.setWordWrap(True)
        c4_layout.addWidget(c4_warn)

        layout.addWidget(c4_card)

        layout.addStretch(1)

        # 初始禁用状态由 MainWindow._setup_ui 在快捷引用建立后统一调用
        # self._main_win._set_stop_controls_enabled(False)

        scroll.setWidget(self.container)
        page_layout.addWidget(scroll, 1)

    def set_stop_controls_enabled(self, master_on: bool) -> None:
        """根据总开关状态设置所有停止条件控件的可用性."""
        self.chk_stop_cond1.setEnabled(master_on)
        self.combo_stop_task.setEnabled(master_on and self.chk_stop_cond1.isChecked())
        self.edit_stop_exec_count.setEnabled(master_on and self.chk_stop_cond1.isChecked())

        self.chk_stop_cond2.setEnabled(master_on)
        self.edit_stop_run_minutes.setEnabled(master_on and self.chk_stop_cond2.isChecked())

        self.chk_stop_cond3.setEnabled(master_on)
        self.btn_stop_img_upload.setEnabled(master_on and self.chk_stop_cond3.isChecked())
        self.btn_stop_img_capture.setEnabled(master_on and self.chk_stop_cond3.isChecked())
        self.slider_stop_threshold.setEnabled(master_on and self.chk_stop_cond3.isChecked())
        self.label_stop_threshold.setEnabled(master_on and self.chk_stop_cond3.isChecked())

        self.chk_stop_cond4.setEnabled(master_on)
        self.edit_stop_idle_minutes.setEnabled(master_on and self.chk_stop_cond4.isChecked())


    def on_stop_enabled_toggled(self, checked: bool) -> None:
        self.set_stop_controls_enabled(checked)


    def on_stop_cond1_toggled(self, checked: bool) -> None:
        master_on = self.chk_stop_enabled.isChecked()
        self.combo_stop_task.setEnabled(master_on and checked)
        self.edit_stop_exec_count.setEnabled(master_on and checked)


    def on_stop_cond2_toggled(self, checked: bool) -> None:
        master_on = self.chk_stop_enabled.isChecked()
        self.edit_stop_run_minutes.setEnabled(master_on and checked)


    def on_stop_cond3_toggled(self, checked: bool) -> None:
        master_on = self.chk_stop_enabled.isChecked()
        self.btn_stop_img_upload.setEnabled(master_on and checked)
        self.btn_stop_img_capture.setEnabled(master_on and checked)
        self.slider_stop_threshold.setEnabled(master_on and checked)
        self.label_stop_threshold.setEnabled(master_on and checked)


    def on_stop_cond4_toggled(self, checked: bool) -> None:
        master_on = self.chk_stop_enabled.isChecked()
        self.edit_stop_idle_minutes.setEnabled(master_on and checked)


    def on_stop_img_upload(self) -> None:
        """条件三：上传识别图."""
        path, _ = QFileDialog.getOpenFileName(
            self, "选择识别模板图片", "",
            "Images (*.png *.jpg *.jpeg *.bmp);;All Files (*)"
        )
        if not path:
            return
        self.stop_image_path = path
        pixmap = QPixmap(path)
        if pixmap.isNull():
            self.stop_img_preview.setText("无效图片")
            self.stop_img_preview.setStyleSheet(
                "border: 2px dashed #EF5350; color: #EF5350; font-size: 11px;"
                "border-radius: 6px;"
            )
            self.stop_image_path = None
            return
        self.stop_img_preview.setPixmap(pixmap.scaled(
            60, 60, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        ))
        self.stop_img_preview.setStyleSheet(
            f"border: 1px solid {CLR_CARD_BORDER}; border-radius: 6px;"
        )


    def on_stop_img_capture(self) -> None:
        """条件三：截图选取 (BUG-01, BUG-02, BUG-03)."""
        main_win = getattr(self, "_main_win", None) or self.window()
        state = main_win.prepare_selection_mode() if main_win and hasattr(main_win, "prepare_selection_mode") else None
        if state is None:
            return
        img = None
        try:
            result, cropped = overlay_selector.get_region_with_image(prompt="拖拽鼠标划定停止条件识别图, 按 Esc 取消")
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
            if main_win and state and hasattr(main_win, "restore_after_selection"):
                main_win.restore_after_selection(state)

        if img is None:
            return

        save_dir = SCREENSHOTS_DIR
        os.makedirs(save_dir, exist_ok=True)
        timestamp = int(time.time() * 1000)
        save_path = os.path.join(save_dir, f"stop_capture_{timestamp}.png")
        # imwrite 不支持中文路径，改用 imencode + tofile（numpy 原生写入支持中文）
        success, encoded = cv2.imencode(".png", img)
        if not success:
            logger.error("停止图片截图编码失败")
            return
        encoded.tofile(save_path)
        self.stop_image_path = save_path
        pixmap = QPixmap(save_path)
        self.stop_img_preview.setPixmap(pixmap.scaled(
            60, 60, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        ))
        self.stop_img_preview.setStyleSheet(
            f"border: 1px solid {CLR_CARD_BORDER}; border-radius: 6px;"
        )


    def refresh_task_combo(self, task_names: list[str]) -> None:
        """按主窗口传入的任务名称刷新条件一目标列表。"""
        current = self.combo_stop_task.currentText()
        names = [name.strip() for name in task_names if isinstance(name, str) and name.strip()]
        self.combo_stop_task.clear()
        if names:
            self.combo_stop_task.addItems(names)
            self.combo_stop_task.setPlaceholderText("")
            index = self.combo_stop_task.findText(current)
            if index >= 0:
                self.combo_stop_task.setCurrentIndex(index)
            elif current and self.chk_stop_cond1.isChecked():
                self.chk_stop_cond1.blockSignals(True)
                self.chk_stop_cond1.setChecked(False)
                self.chk_stop_cond1.blockSignals(False)
                logger.warning(f"停止条件引用的任务「{current}」已不存在，已自动取消条件一勾选")
        else:
            self.combo_stop_task.setPlaceholderText("暂无任务")


    def collect_stop_conditions(self) -> dict:
        """收集停止条件配置。"""
        self.validate_inputs()
        result: dict = {"enabled": self.chk_stop_enabled.isChecked()}

        task_name = self.combo_stop_task.currentText().strip()
        try:
            exec_count = int(self.edit_stop_exec_count.text())
        except (ValueError, TypeError, OverflowError):
            exec_count = 0
        result["task_exec_count"] = {
            "enabled": self.chk_stop_cond1.isChecked() and bool(task_name and exec_count > 0),
            "task_name": task_name,
            "count": exec_count,
        }

        try:
            run_min = int(self.edit_stop_run_minutes.text())
        except (ValueError, TypeError, OverflowError):
            run_min = 0
        result["run_time_limit"] = {
            "enabled": self.chk_stop_cond2.isChecked() and run_min > 0,
            "minutes": run_min,
        }

        result["image_match_stop"] = {
            "enabled": self.chk_stop_cond3.isChecked() and bool(
                self.stop_image_path and os.path.exists(self.stop_image_path)
            ),
            "image_path": self.stop_image_path or "",
            "threshold": self.slider_stop_threshold.value(),
        }

        try:
            idle_min = int(self.edit_stop_idle_minutes.text())
        except (ValueError, TypeError, OverflowError):
            idle_min = 0
        result["no_match_timeout"] = {
            "enabled": self.chk_stop_cond4.isChecked() and idle_min > 0,
            "minutes": idle_min,
        }
        return result

    @staticmethod
    def parse_stop_reason_lines(reason: str) -> tuple[str, str, str, str, str, str]:
        """
        解析停止原因并拆分为条件主体与结果文案。
        返回: (line2_text, icon2_key, icon2_color, line3_text, icon3_key, icon3_color)
        """
        m1 = re.search(r"「(.*?)」已执行\s*(\d+)\s*次", reason)
        if m1:
            task_name, count = m1.group(1), m1.group(2)
            display_name = task_name if len(task_name) <= 5 else task_name[:4] + "…"
            return f"任务：「{display_name}」", "info", CLR_STATUS_WARN, f"累计已执行 {count} 次", "check", CLR_BTN_SUCCESS

        m2 = re.search(r"(?:已运行|最大运行时间)\s*(\d+)\s*分钟", reason)
        if m2:
            minutes = m2.group(1)
            return "挂机时长达标", "info", CLR_STATUS_WARN, f"已达到 {minutes} 分钟", "timer", CLR_STATUS_WARN

        m3 = re.search(r"匹配度\s*(\d+)%", reason)
        if m3:
            score = m3.group(1)
            return "目标图片命中", "info", CLR_STATUS_WARN, f"匹配度 {score}%", "check", CLR_BTN_SUCCESS
        if "停止图片" in reason:
            return "目标图片命中", "info", CLR_STATUS_WARN, "检测到停止图", "check", CLR_BTN_SUCCESS

        m4 = re.search(r"(?:连续\s*)?(\d+)\s*分钟(?:无匹配|未匹配)", reason)
        if m4:
            minutes = m4.group(1)
            return "画面无任何匹配", "info", CLR_STATUS_WARN, f"已空转 {minutes} 分钟", "hourglass", CLR_STATUS_WARN

        clean = reason.replace("，自动停止", "").replace("自动停止", "").strip()
        if not clean:
            return "条件停止", "info", CLR_STATUS_WARN, "—", "timer", CLR_TEXT_SUB
        if len(clean) <= 8:
            return clean, "info", CLR_STATUS_WARN, "—", "timer", CLR_TEXT_SUB
        return clean[:8], "info", CLR_STATUS_WARN, clean[8:16], "check", CLR_BTN_SUCCESS

    def apply_stop_conditions(
        self,
        sc: dict | None,
        stop_image_path: str | None = None,
        is_replace_mode: bool = False,
    ) -> None:
        """将字典配置完整恢复到停止条件页 UI 控件（含类型校验、图片状态与开关复位）。"""
        if not isinstance(sc, dict):
            if not is_replace_mode:
                return
            sc = {}

        def _safe_int(val, default: int) -> int:
            if isinstance(val, bool) or val is None:
                return default
            try:
                return int(val)
            except (ValueError, TypeError, OverflowError):
                return default

        def _safe_threshold(val, default: int = 90) -> int:
            if isinstance(val, bool) or val is None:
                return default
            try:
                number = float(val)
                if not math.isfinite(number):
                    return default
                value = int(round(number * 100)) if 0.0 < number <= 1.0 else int(round(number))
                return max(50, min(99, value))
            except (ValueError, TypeError, OverflowError):
                return default

        try:
            self.chk_stop_enabled.blockSignals(True)
            self.chk_stop_enabled.setChecked(bool(sc.get("enabled", False)))
            self.chk_stop_enabled.blockSignals(False)

            raw_tc = sc.get("task_exec_count")
            tc = raw_tc if isinstance(raw_tc, dict) else {}
            self.chk_stop_cond1.blockSignals(True)
            self.chk_stop_cond1.setChecked(bool(tc.get("enabled", False)))
            self.chk_stop_cond1.blockSignals(False)
            count = _safe_int(tc.get("count"), 5)
            self.edit_stop_exec_count.setText(str(count if count > 0 else 5))
            raw_name = tc.get("task_name")
            task_name = raw_name.strip() if isinstance(raw_name, str) else ""
            if task_name:
                index = self.combo_stop_task.findText(task_name)
                if index >= 0:
                    self.combo_stop_task.setCurrentIndex(index)
                elif self.chk_stop_cond1.isChecked():
                    self.chk_stop_cond1.blockSignals(True)
                    self.chk_stop_cond1.setChecked(False)
                    self.chk_stop_cond1.blockSignals(False)
                    logger.warning(f"停止条件引用的任务「{task_name}」不存在，已取消条件一勾选")
            elif self.chk_stop_cond1.isChecked():
                self.chk_stop_cond1.blockSignals(True)
                self.chk_stop_cond1.setChecked(False)
                self.chk_stop_cond1.blockSignals(False)

            raw_rl = sc.get("run_time_limit")
            rl = raw_rl if isinstance(raw_rl, dict) else {}
            self.chk_stop_cond2.blockSignals(True)
            self.chk_stop_cond2.setChecked(bool(rl.get("enabled", False)))
            self.chk_stop_cond2.blockSignals(False)
            run_minutes = _safe_int(rl.get("minutes"), 10)
            self.edit_stop_run_minutes.setText(str(run_minutes if run_minutes > 0 else 10))

            raw_ims = sc.get("image_match_stop")
            ims = raw_ims if isinstance(raw_ims, dict) else {}
            self.chk_stop_cond3.blockSignals(True)
            self.chk_stop_cond3.setChecked(bool(ims.get("enabled", False)))
            self.chk_stop_cond3.blockSignals(False)
            self.slider_stop_threshold.setValue(_safe_threshold(ims.get("threshold"), 90))

            raw_img = stop_image_path if stop_image_path is not None else ims.get("image_path")
            image_path = raw_img if isinstance(raw_img, str) and raw_img.strip() else None
            self.stop_image_path = image_path
            if image_path and os.path.exists(image_path):
                pixmap = QPixmap(image_path)
                if not pixmap.isNull():
                    self.stop_img_preview.setPixmap(pixmap.scaled(
                        60, 60, Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    ))
                    self.stop_img_preview.setStyleSheet(
                        f"border: 1px solid {CLR_CARD_BORDER}; border-radius: 6px;"
                    )
                else:
                    self.stop_image_path = None
                    self.stop_img_preview.setPixmap(QPixmap())
                    self.stop_img_preview.setText("无效图片")
                    self.stop_img_preview.setStyleSheet(
                        "border: 2px dashed #EF5350; color: #EF5350; font-size: 11px; border-radius: 6px;"
                    )
                    self.chk_stop_cond3.blockSignals(True)
                    self.chk_stop_cond3.setChecked(False)
                    self.chk_stop_cond3.blockSignals(False)
            elif image_path:
                self.stop_image_path = None
                self.stop_img_preview.setPixmap(QPixmap())
                self.stop_img_preview.setText("图片已丢失")
                self.stop_img_preview.setStyleSheet(
                    "border: 2px dashed #EF5350; color: #EF5350; font-size: 11px; border-radius: 6px;"
                )
                self.chk_stop_cond3.blockSignals(True)
                self.chk_stop_cond3.setChecked(False)
                self.chk_stop_cond3.blockSignals(False)
            else:
                self.stop_image_path = None
                self.stop_img_preview.setPixmap(QPixmap())
                self.stop_img_preview.setText("无图片")
                self.stop_img_preview.setStyleSheet(
                    f"border: 2px dashed {CLR_CARD_BORDER}; color: {CLR_TEXT_SUB}; font-size: 11px; border-radius: 6px;"
                )
                if self.chk_stop_cond3.isChecked():
                    self.chk_stop_cond3.blockSignals(True)
                    self.chk_stop_cond3.setChecked(False)
                    self.chk_stop_cond3.blockSignals(False)

            raw_nmt = sc.get("no_match_timeout")
            nmt = raw_nmt if isinstance(raw_nmt, dict) else {}
            self.chk_stop_cond4.blockSignals(True)
            self.chk_stop_cond4.setChecked(bool(nmt.get("enabled", False)))
            self.chk_stop_cond4.blockSignals(False)
            idle_minutes = _safe_int(nmt.get("minutes"), 5)
            self.edit_stop_idle_minutes.setText(str(idle_minutes if idle_minutes > 0 else 5))

            self.validate_inputs()
            self.set_stop_controls_enabled(self.chk_stop_enabled.isChecked())
        except Exception as e:
            logger.error(f"恢复停止条件配置异常: {e}")

    def set_controls_enabled(self, enabled: bool) -> None:
        """运行期控件锁定与解锁 (BUG-09). 仅禁用容器内输入项，外部 QScrollArea 保持 enabled，滚动条/滚轮依然可用."""
        self.container.setEnabled(enabled)

    def validate_inputs(self) -> None:
        """停止条件页 3 个数值输入框强制校验回填 (FEAT-06)."""
        for edit in (self.edit_stop_exec_count, self.edit_stop_run_minutes, self.edit_stop_idle_minutes):
            if edit is not None and edit.validator():
                edit.setText(edit.validator().fixup(edit.text()))


