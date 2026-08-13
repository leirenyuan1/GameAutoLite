"""
主窗口 (main_window.py)
"""

import logging
import os
import re
import sys
import time
import threading

from PyQt6.QtCore import (
    Qt, pyqtSignal, pyqtSlot, QMetaObject, Q_ARG,
    QPropertyAnimation, QEasingCurve, QRect, QPoint, QTimer,
)
from PyQt6.QtGui import QPixmap, QColor
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QCheckBox, QScrollArea, QSlider, QFrame,
    QSizePolicy, QFileDialog, QMessageBox, QStackedWidget, QComboBox,
    QGraphicsOpacityEffect, QSizeGrip, QMenu,
)

# ↓ _on_stop_img_capture 仍需要这四个库，不要删除
import cv2
import mss
import numpy as np
import overlay_selector

from styles.colors import *           # noqa: F403
from styles.qss import get_global_qss
from engine import EngineThread
from config_manager import (
    save_config, load_config, export_scheme, write_scheme_file,
    parse_scheme_file, restore_task_image, restore_stop_image,
    CONFIG_FILE, SCREENSHOTS_DIR,
)
from hotkey_manager import HotkeyManager
from widgets.sidebar import SideBar
from widgets.floating_widget import FloatingWidget
from widgets.task_card import CollapsibleTaskCard
from pages.task_list_page import TaskListPage
from pages.stop_conditions_page import StopConditionsPage
from pages.settings_page import SettingsPage

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self._is_main_window = True  # 供 CollapsibleTaskCard._find_main_window 标记识别
        self.setWindowTitle("GameAutoLite")
        self.setMinimumSize(480, 500)

        self._task_cards: list[CollapsibleTaskCard] = []
        self._engine: EngineThread | None = None
        self._hotkey_mgr = HotkeyManager(parent=self)
        # L60 已完全删除 — 不注册热键，等 _load_config 后注册
        self._auto_minimized = False
        self._stop_by_condition = False  # 条件停止标志
        self._manual_stop = False  # 手动停止标志
        self._engine_dying = False  # 旧引擎线程退出中标志（wait 超时兜底防御）
        self._moveAnimating = False
        self._suppress_floating = False  # 抑制悬浮窗（截图/选取区域时）
        self._floating_widget: FloatingWidget | None = None  # 悬浮窗实例（延迟初始化）
        self._global_settings: dict = {"scan_interval": 200, "auto_minimize": False, "move_speed": 1.0, "click_speed": 1.0, "show_floating_widget": False, "always_show_floating": False}

        # 远程监控相关属性
        self._remote_server = None
        self._remote_thread = None
        self._remote_status_lock = threading.Lock()
        self._remote_status_cache = {
            "icon1": "⚡", "line1": "就绪",
            "icon2": "🖱", "line2": "—",
            "icon3": "⏱", "line3": "—",
            "is_running": False
        }

        # 预览定时器（复用同一个实例，避免内存泄漏）
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.timeout.connect(self._preview_hide)

        self._setup_ui()
        self._load_config()

    # ---- UI 构建 ----

    def _setup_ui(self) -> None:
        # ---- 全局 QSS ----
        self.setStyleSheet(get_global_qss())

        # ---- 根布局: 左右双栏 ----
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # 左侧边栏
        self.sidebar = SideBar()
        self.sidebar.navigate.connect(self._on_sidebar_navigate)
        self.sidebar.btn_toggle.clicked.connect(self._on_toggle_clicked)
        root_layout.addWidget(self.sidebar)

        # 右侧内容区: QStackedWidget
        self._stack = QStackedWidget()
        self._stack.setStyleSheet(f"background: {CLR_CONTENT_BG};")
        root_layout.addWidget(self._stack, 1)

        # 窗口右下角缩放手柄（直接子控件，手动定位）
        self._resize_grip = QSizeGrip(self)
        self._resize_grip.setFixedSize(16, 16)

        # _stop_image_path 归属 MainWindow（见附录二），在此显式初始化
        self._stop_image_path = None

        # ========== 页面 0: 任务列表 ==========
        self._task_list_page = TaskListPage(self)

        # ========== 页面 1: 停止条件 ==========
        self._stop_conditions_page = StopConditionsPage(self)

        # ========== 页面 2: 全局设置 ==========
        self._settings_page = SettingsPage(self)

        # ========== 页面 3: 远程监控 ==========
        from pages.remote_monitor_page import RemoteMonitorPage
        self._remote_monitor_page = RemoteMonitorPage(self)

        self._stack.addWidget(self._task_list_page)          # index 0
        self._stack.addWidget(self._stop_conditions_page)    # index 1
        self._stack.addWidget(self._settings_page)           # index 2
        self._stack.addWidget(self._remote_monitor_page)     # index 3

        # ======== 快捷引用（过渡期） ========
        # 任务列表页
        self._scroll = self._task_list_page._scroll
        self._card_container = self._task_list_page._card_container
        self._card_layout = self._task_list_page._card_layout
        self.btn_add = self._task_list_page.btn_add
        self.btn_import = self._task_list_page.btn_import
        self.btn_export = self._task_list_page.btn_export

        # 停止条件页
        self.chk_stop_enabled = self._stop_conditions_page.chk_stop_enabled
        self.chk_stop_cond1 = self._stop_conditions_page.chk_stop_cond1
        self.combo_stop_task = self._stop_conditions_page.combo_stop_task
        self.edit_stop_exec_count = self._stop_conditions_page.edit_stop_exec_count
        self.chk_stop_cond2 = self._stop_conditions_page.chk_stop_cond2
        self.edit_stop_run_minutes = self._stop_conditions_page.edit_stop_run_minutes
        self.chk_stop_cond3 = self._stop_conditions_page.chk_stop_cond3
        self.btn_stop_img_upload = self._stop_conditions_page.btn_stop_img_upload
        self.btn_stop_img_capture = self._stop_conditions_page.btn_stop_img_capture
        self.stop_img_preview = self._stop_conditions_page.stop_img_preview
        self.slider_stop_threshold = self._stop_conditions_page.slider_stop_threshold
        self.label_stop_threshold = self._stop_conditions_page.label_stop_threshold
        self.chk_stop_cond4 = self._stop_conditions_page.chk_stop_cond4
        self.edit_stop_idle_minutes = self._stop_conditions_page.edit_stop_idle_minutes

        # 全局设置页
        self._settings_page.hotkeys_changed.connect(self._on_hotkeys_changed)
        self.chk_top = self._settings_page.chk_top
        self.chk_auto_minimize = self._settings_page.chk_auto_minimize
        self.edit_scan_interval = self._settings_page.edit_scan_interval
        self.combo_move_speed = self._settings_page.combo_move_speed
        self.combo_click_speed = self._settings_page.combo_click_speed
        self.chk_floating = self._settings_page.chk_floating
        self.chk_always_floating = self._settings_page.chk_always_floating
        self.slider_opacity = self._settings_page.slider_opacity
        self.label_opacity = self._settings_page.label_opacity
        self.chk_floating_disabled = self._settings_page.chk_floating_disabled

        # 快捷引用建立后，统一设置停止条件控件的初始禁用状态
        self._set_stop_controls_enabled(False)

    def _set_stop_controls_enabled(self, master_on: bool) -> None:
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

    # ---- 停止条件联动回调 ----

    def _on_stop_enabled_toggled(self, checked: bool) -> None:
        self._set_stop_controls_enabled(checked)

    def _on_stop_cond1_toggled(self, checked: bool) -> None:
        master_on = self.chk_stop_enabled.isChecked()
        self.combo_stop_task.setEnabled(master_on and checked)
        self.edit_stop_exec_count.setEnabled(master_on and checked)

    def _on_stop_cond2_toggled(self, checked: bool) -> None:
        master_on = self.chk_stop_enabled.isChecked()
        self.edit_stop_run_minutes.setEnabled(master_on and checked)

    def _on_stop_cond3_toggled(self, checked: bool) -> None:
        master_on = self.chk_stop_enabled.isChecked()
        self.btn_stop_img_upload.setEnabled(master_on and checked)
        self.btn_stop_img_capture.setEnabled(master_on and checked)
        self.slider_stop_threshold.setEnabled(master_on and checked)
        self.label_stop_threshold.setEnabled(master_on and checked)

    def _on_stop_cond4_toggled(self, checked: bool) -> None:
        master_on = self.chk_stop_enabled.isChecked()
        self.edit_stop_idle_minutes.setEnabled(master_on and checked)

    # ---- 停止条件图片上传/截图 ----

    def _on_stop_img_upload(self) -> None:
        """条件三：上传识别图."""
        path, _ = QFileDialog.getOpenFileName(
            self, "选择识别模板图片", "",
            "Images (*.png *.jpg *.jpeg *.bmp);;All Files (*)"
        )
        if not path:
            return
        self._stop_image_path = path
        pixmap = QPixmap(path)
        if pixmap.isNull():
            self.stop_img_preview.setText("⚠ 无效图片")
            self.stop_img_preview.setStyleSheet(
                "border: 2px dashed #EF5350; color: #EF5350; font-size: 11px;"
                "border-radius: 6px;"
            )
            self._stop_image_path = None
            return
        self.stop_img_preview.setPixmap(pixmap.scaled(
            60, 60, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        ))
        self.stop_img_preview.setStyleSheet(
            f"border: 1px solid {CLR_CARD_BORDER}; border-radius: 6px;"
        )

    def _on_stop_img_capture(self) -> None:
        """条件三：截图选取."""
        main_win = self.window()
        geom = main_win.geometry() if main_win else None
        if main_win and main_win.isVisible():
            main_win._suppress_floating = True
            main_win.showMinimized()
        try:
            result = overlay_selector.get_region()
        finally:
            if main_win:
                main_win._suppress_floating = False
                if geom:
                    main_win.setGeometry(geom)
                main_win.showNormal()
        if result is None:
            return
        x, y, w, h = result
        try:
            with mss.mss() as sct:
                monitor = {"top": y, "left": x, "width": w, "height": h}
                sct_img = sct.grab(monitor)
                img = np.array(sct_img)
                img = np.ascontiguousarray(img[:, :, :3])
        except Exception as e:
            logger.error(f"截图捕获失败: {e}")
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
        self._stop_image_path = save_path
        pixmap = QPixmap(save_path)
        self.stop_img_preview.setPixmap(pixmap.scaled(
            60, 60, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        ))
        self.stop_img_preview.setStyleSheet(
            f"border: 1px solid {CLR_CARD_BORDER}; border-radius: 6px;"
        )

    # ---- 停止条件辅助方法 ----

    def _refresh_stop_task_combo(self) -> None:
        """任务卡片增删/重命名时刷新停止条件的任务名称下拉框."""
        current = self.combo_stop_task.currentText()
        self.combo_stop_task.clear()
        names = [c.name_edit.text().strip() for c in self._task_cards if c.name_edit.text().strip()]
        if names:
            self.combo_stop_task.addItems(names)
            self.combo_stop_task.setPlaceholderText("")
            idx = self.combo_stop_task.findText(current)
            if idx >= 0:
                self.combo_stop_task.setCurrentIndex(idx)
            elif current and self.chk_stop_cond1.isChecked():
                self.chk_stop_cond1.setChecked(False)
                logger.warning(f"停止条件引用的任务「{current}」已不存在，已自动取消勾选")
        else:
            self.combo_stop_task.setPlaceholderText("暂无任务")

    def _collect_stop_conditions(self) -> dict:
        """收集停止条件配置."""
        result: dict = {"enabled": self.chk_stop_enabled.isChecked()}

        task_name = self.combo_stop_task.currentText().strip()
        try:
            exec_count = int(self.edit_stop_exec_count.text())
        except ValueError:
            exec_count = 0
        result["task_exec_count"] = {
            "enabled": self.chk_stop_cond1.isChecked() and bool(task_name and exec_count > 0),
            "task_name": task_name,
            "count": exec_count,
        }

        try:
            run_min = int(self.edit_stop_run_minutes.text())
        except ValueError:
            run_min = 0
        result["run_time_limit"] = {
            "enabled": self.chk_stop_cond2.isChecked() and run_min > 0,
            "minutes": run_min,
        }

        result["image_match_stop"] = {
            "enabled": self.chk_stop_cond3.isChecked() and bool(
                self._stop_image_path and os.path.exists(self._stop_image_path)
            ),
            "image_path": self._stop_image_path or "",
            "threshold": self.slider_stop_threshold.value(),
        }

        try:
            idle_min = int(self.edit_stop_idle_minutes.text())
        except ValueError:
            idle_min = 0
        result["no_match_timeout"] = {
            "enabled": self.chk_stop_cond4.isChecked() and idle_min > 0,
            "minutes": idle_min,
        }

        return result

    # ---- 停止条件触发处理 ----

    def _restore_window_if_auto_minimized(self) -> None:
        """如果启用了自动最小化，引擎停止后恢复窗口."""
        if self._auto_minimized:
            self._auto_minimized = False
            self.showNormal()

    def _on_stop_condition_met(self, reason: str) -> None:
        """停止条件触发."""
        self._stop_by_condition = True

        if not self._engine or not self._engine.isRunning():
            # 守卫触发：引擎已快速结束或已被手动停止。
            # 如果是手动停止（_manual_stop=True），不干涉（UI 已由 _on_engine_finished 更新）。
            # 如果是条件触发导致引擎快速结束（_manual_stop=False），仍需更新 UI + 弹窗。
            if not self._manual_stop:
                self._apply_condition_stop_ui()
                msg = self._styled_msgbox()
                msg.setWindowTitle("停止条件触发")
                msg.setText(reason)
                self._exec_msgbox_centered(msg)
            return

        try:
            self._engine.status_update.disconnect(self._on_status_update)
            self._engine.finished.disconnect(self._on_engine_finished)
            self._engine.stop_condition_met.disconnect(self._on_stop_condition_met)
        except Exception:
            pass
        self._engine.stop()
        if not self._engine.wait(3000):
            # 兜底：线程未在 3 秒内退出（仅当未来新增更长的不可打断操作才会走到这里）
            logger.error("引擎线程未在 3 秒内退出，进入等待退出状态")
            self._engine_dying = True
            self._engine.finished.connect(self._on_dying_engine_finished)  # 线程真正退出后再清理

        self._apply_condition_stop_ui()

        msg = self._styled_msgbox()
        msg.setWindowTitle("停止条件触发")
        msg.setText(reason)
        self._exec_msgbox_centered(msg)

    def _apply_condition_stop_ui(self) -> None:
        """更新状态栏为条件停止 + 同步悬浮窗 + 恢复窗口."""
        self.sidebar.set_engine_running(False)
        self.sidebar.status_line1.setText("条件停止")
        self.sidebar.status_icon1.setText("🛑")
        self.sidebar.status_icon1.setStyleSheet(f"color: #FF9800;")
        self.sidebar.status_line2.setText("自动停止")
        self.sidebar.status_icon2.setText("ℹ")
        self.sidebar.status_line3.setText("—")
        self.sidebar.status_icon3.setText("⏱")

        if self._floating_widget and self._floating_widget.isVisible():
            self._floating_widget.sync_from_sidebar(self.sidebar)

        self._restore_window_if_auto_minimized()
        self._update_remote_status_cache()  # 插入点D

    def _update_remote_status_cache(self) -> None:
        """更新远程监控状态缓存（线程安全）"""
        with self._remote_status_lock:
            sb = self.sidebar
            self._remote_status_cache = {
                "icon1": sb.status_icon1.text(),
                "line1": sb.status_line1.text(),
                "icon2": sb.status_icon2.text(),
                "line2": sb.status_line2.text(),
                "icon3": sb.status_icon3.text(),
                "line3": sb.status_line3.text(),
                "is_running": sb.btn_toggle.text().startswith("⏹")
            }

    # 设置卡片计数器，用于生成唯一的 objectName
    _settings_card_counter = 0

    def changeEvent(self, event):
        """监听窗口状态变化，控制悬浮窗显示/隐藏"""
        if event.type() == event.Type.WindowStateChange:
            if self.isMinimized():
                # 停止预览定时器
                self._preview_timer.stop()
                # 最小化时显示悬浮窗（仅当勾选了"最小化时显示悬浮窗"）
                if (self.chk_floating.isChecked()
                        and not self._suppress_floating):
                    self._sync_and_show_floating()
            else:
                # 从最小化恢复、最大化、或正常状态变化时
                if self.chk_always_floating.isChecked():
                    # 如果勾选了"始终显示悬浮窗"，保持/恢复显示
                    if not self._suppress_floating:
                        self._sync_and_show_floating()
                else:
                    # 未勾选"始终显示悬浮窗"，隐藏悬浮窗
                    if self._floating_widget and not self._suppress_floating:
                        self._floating_widget.fade_hide()
        super().changeEvent(event)

    def _on_floating_toggled(self, checked: bool) -> None:
        """悬浮窗开关切换时，联动子项可用性和互斥逻辑"""
        # 获取触发信号的控件（仅在信号触发时有效，直接调用时为 None）
        sender = self.sender()

        # 获取两个开关的状态
        minimize_on = self.chk_floating.isChecked()
        always_on = self.chk_always_floating.isChecked()
        any_on = minimize_on or always_on

        # 互斥逻辑：勾选一个时禁用另一个，取消勾选时启用另一个
        if sender == self.chk_floating:
            if checked:
                self.chk_always_floating.setEnabled(False)
            else:
                self.chk_always_floating.setEnabled(True)
        elif sender == self.chk_always_floating:
            if checked:
                self.chk_floating.setEnabled(False)
            else:
                self.chk_floating.setEnabled(True)

        # 联动子项可用性
        self.slider_opacity.setEnabled(any_on)
        self.label_opacity.setEnabled(any_on)
        self.chk_floating_disabled.setEnabled(any_on)

        # 始终显示悬浮窗的逻辑
        if always_on:
            self._preview_timer.stop()
            self._sync_and_show_floating()
        elif minimize_on:
            pass  # 最小化时才显示，这里不需要操作
        else:
            # 两个都关闭时，停止定时器并隐藏悬浮窗
            self._preview_timer.stop()
            if self._floating_widget and self._floating_widget.isVisible():
                self._floating_widget.fade_hide()

    def _on_opacity_changed(self, value: int) -> None:
        """透明度滑块值改变，自动预览悬浮窗"""
        self.label_opacity.setText(f"{value}%")
        # 两个开关都没勾选时才跳过
        if not self.chk_floating.isChecked() and not self.chk_always_floating.isChecked():
            return
        # 自动显示预览悬浮窗
        self._auto_preview_floating()

    def _auto_preview_floating(self) -> None:
        """滑块拖动时自动显示预览，停止拖动后 2 秒自动隐藏"""
        # 复用 __init__ 中创建的定时器，避免内存泄漏
        self._preview_timer.stop()

        if not self._floating_widget:
            self._floating_widget = FloatingWidget(self)

        # 应用当前透明度和交互状态
        opacity = self.slider_opacity.value() / 100.0
        self._floating_widget.setWindowOpacity(opacity)
        self._floating_widget.set_interactive(not self.chk_floating_disabled.isChecked())

        # 同步状态
        self._floating_widget.sync_from_sidebar(self.sidebar)

        # 显示在屏幕中央（仅首次）
        if not self._floating_widget.isVisible():
            self._floating_widget.adjustSize()  # 先计算尺寸再定位
            screen = QApplication.screenAt(self.geometry().center())
            if not screen:
                screen = QApplication.primaryScreen()
            geo = screen.availableGeometry()
            self._floating_widget.move(
                geo.center().x() - self._floating_widget.width() // 2,
                geo.center().y() - self._floating_widget.height() // 2
            )
            self._floating_widget.show()

        # 2 秒后自动隐藏（始终显示模式下不需要定时器）
        if not self.chk_always_floating.isChecked():
            self._preview_timer.start(2000)

    def _preview_hide(self) -> None:
        """预览结束后隐藏（仅在非最小化状态下，且未勾选始终显示）"""
        if self._floating_widget and not self.isMinimized():
            # 如果勾选了"始终显示悬浮窗"，不隐藏
            if self.chk_always_floating.isChecked():
                return
            self._floating_widget.fade_hide()

    def _on_floating_disabled_toggled(self, checked: bool) -> None:
        """禁用交互切换时，更新悬浮窗状态（悬浮窗未创建时会在下次显示时应用）"""
        if self._floating_widget:
            self._floating_widget.set_interactive(not checked)

    def _sync_and_show_floating(self):
        """同步当前状态到悬浮窗并显示"""
        if not self._floating_widget:
            self._floating_widget = FloatingWidget(self)
            # 从配置恢复位置记忆
            pos_data = self._global_settings.get("floating_widget_pos")
            if pos_data and len(pos_data) == 2:
                self._floating_widget._last_pos = QPoint(pos_data[0], pos_data[1])

        # 应用透明度设置（从 UI 控件读取当前值，而不是 _global_settings）
        opacity = self.slider_opacity.value() / 100.0
        self._floating_widget.setWindowOpacity(opacity)

        # 应用交互状态（从 UI 控件读取当前值，状态没变时跳过避免重复调用 Windows API）
        disabled = self.chk_floating_disabled.isChecked()
        if self._floating_widget._interactive != (not disabled):
            self._floating_widget.set_interactive(not disabled)

        # 同步状态
        self._floating_widget.sync_from_sidebar(self.sidebar)

        # 已可见时只刷新状态，不重新淡入（避免闪烁）
        if self._floating_widget.isVisible():
            return

        # 获取主窗口所在的屏幕（多显示器支持）
        screen = QApplication.screenAt(self.geometry().center())
        if not screen:
            screen = QApplication.primaryScreen()
        geo = screen.availableGeometry()

        # 淡入显示（传入目标透明度，避免动画重置为1.0）
        self._floating_widget.fade_show(geo, target_opacity=opacity)

    # ---- 侧边栏导航 ----

    def _on_sidebar_navigate(self, index: int) -> None:
        self._stack.setCurrentIndex(index)

    # ---- 快捷键管理 ----

    @pyqtSlot(list)
    def _on_hotkeys_changed(self, hotkeys: list[dict]) -> None:
        """设置页快捷键变更时调用。"""
        self._hotkey_mgr.unregister_all()
        enabled_hotkeys = [h for h in hotkeys if h.get("enabled", True)]
        if enabled_hotkeys and self._global_settings.get("hotkeys_enabled", True):
            self._hotkey_mgr.register_all(self, "_toggle_engine", enabled_hotkeys)
        self._global_settings["hotkeys"] = hotkeys

    def _on_top_toggled(self, checked: bool) -> None:
        """切换窗口置顶状态."""
        geom = self.geometry()
        flags = self.windowFlags()
        if checked:
            self.setWindowFlags(flags | Qt.WindowType.WindowStaysOnTopHint)
        else:
            self.setWindowFlags(flags & ~Qt.WindowType.WindowStaysOnTopHint)
        self.setGeometry(geom)
        self.show()

    # ---- 引擎启停 ----

    def _on_toggle_clicked(self) -> None:
        self._toggle_engine()

    @pyqtSlot()
    def _toggle_engine(self) -> None:
        """双向切换: 运行中则停止, 未运行则启动."""
        if self._engine and self._engine.isRunning():
            self._stop_engine()
        else:
            self._start_engine()

    def _start_engine(self) -> None:
        if self._engine_dying:
            # 旧引擎线程尚未退出（wait 超时兜底场景），拒绝启动新引擎
            self.sidebar.status_line1.setText("引擎正在退出")
            logger.warning("旧引擎线程尚未退出，拒绝启动新引擎")
            return
        # 启动前同步所有设置到 _global_settings
        self._sync_settings_to_global()

        # 校验名称：检查是否有重复或空名称
        name_count: dict[str, list] = {}
        for card in self._task_cards:
            name = card.name_edit.text().strip()
            name_count.setdefault(name, []).append(card)

        has_error = False
        for name, cards in name_count.items():
            if not name or len(cards) > 1:
                for card in cards:
                    card._name_has_error = True
                    card._set_name_error_style()
                has_error = True

        if has_error:
            self.sidebar.status_line1.setText("名称有误")
            self.sidebar.status_icon1.setText("⚠")
            self.sidebar.status_icon1.setStyleSheet("color: #E65100;")
            self.sidebar.status_line2.setText("请检查重复/空名称")
            self.sidebar.status_icon2.setText("✏")
            self.sidebar.status_line3.setText("")
            self.sidebar.status_icon3.setText("⏱")
            if self._floating_widget and self._floating_widget.isVisible():
                self._floating_widget.sync_from_sidebar(self.sidebar)
            self._update_remote_status_cache()  # 插入点E1
            return

        # 收集所有配置完整的任务
        configs = self._collect_task_configs()
        if not configs:
            self.sidebar.status_line1.setText("无可用任务")
            self.sidebar.status_icon1.setText("⚠")
            self.sidebar.status_icon1.setStyleSheet("color: #E65100;")
            self.sidebar.status_line2.setText("需设置图片")
            self.sidebar.status_icon2.setText("🖱")
            self.sidebar.status_line3.setText("和点击区域")
            self.sidebar.status_icon3.setText("⏱")
            # 同步到悬浮窗
            if self._floating_widget and self._floating_widget.isVisible():
                self._floating_widget.sync_from_sidebar(self.sidebar)
            self._update_remote_status_cache()  # 插入点E2
            return

        # ---- 停止条件处理 ----
        self._stop_by_condition = False
        self._manual_stop = False
        self._refresh_stop_task_combo()
        self._sync_settings_to_global()
        stop_conditions = self._global_settings.get("stop_conditions", {"enabled": False})

        if stop_conditions.get("enabled"):
            warnings: list[str] = []
            cond1 = stop_conditions.get("task_exec_count", {})
            if cond1.get("enabled"):
                task_name = cond1.get("task_name", "")
                config_names = [c["name"] for c in configs]
                if task_name not in config_names:
                    warnings.append(f"条件一引用的任务「{task_name}」不存在或未配置完整，该条件将不会生效")
                    stop_conditions["task_exec_count"]["enabled"] = False
            cond3 = stop_conditions.get("image_match_stop", {})
            if cond3.get("enabled"):
                img_path = cond3.get("image_path", "")
                if not img_path or not os.path.exists(img_path):
                    warnings.append("条件三的图片文件不存在或已被移动，该条件将不会生效")
                    stop_conditions["image_match_stop"]["enabled"] = False
            if warnings:
                msg = self._styled_msgbox()
                msg.setWindowTitle("停止条件校验")
                msg.setText("以下停止条件存在问题：\n\n" + "\n".join(f"• {w}" for w in warnings))
                self._exec_msgbox_centered(msg)

        self._engine = EngineThread(
            configs,
            scan_interval=self._global_settings.get("scan_interval", 200),
            move_speed=self._global_settings.get("move_speed", 1.0),
            click_speed=self._global_settings.get("click_speed", 1.0),
            stop_conditions=stop_conditions,
        )
        self._engine.status_update.connect(self._on_status_update)
        self._engine.finished.connect(self._on_engine_finished)
        self._engine.stop_condition_met.connect(self._on_stop_condition_met)
        self._engine.start()

        self.sidebar.set_engine_running(True)

        if self.chk_auto_minimize.isChecked():
            self._auto_minimized = True
            self.showMinimized()

    def _stop_engine(self) -> None:
        self._manual_stop = True
        if self._engine:
            try:
                self._engine.status_update.disconnect(self._on_status_update)
                self._engine.finished.disconnect(self._on_engine_finished)
                self._engine.stop_condition_met.disconnect(self._on_stop_condition_met)
            except Exception:
                pass
            self._engine.stop()
            if not self._engine.wait(3000):
                # 兜底：线程未在 3 秒内退出（仅当未来新增更长的不可打断操作才会走到这里）
                logger.error("引擎线程未在 3 秒内退出，进入等待退出状态")
                self._engine_dying = True
                self._engine.finished.connect(self._on_dying_engine_finished)  # 线程真正退出后再清理
        self._on_engine_finished()  # 幂等，超时/正常都执行，保证 UI 不卡在"运行中"

    def _on_status_update(self, text: str) -> None:
        sb = self.sidebar

        if "运行中" in text:
            sb.status_line1.setText("运行中")
            sb.status_icon1.setText("⚡")
            sb.status_icon1.setStyleSheet(f"color: {CLR_BTN_SUCCESS};")
            sb.status_line2.setText("监测中...")
            sb.status_icon2.setText("🔍")
            sb.status_line3.setText("—")
            sb.status_icon3.setText("⏱")

        elif "匹配到" in text:
            m = re.search(r'匹配到「(.*?)」.*?(\d+)ms', text)
            name = m.group(1) if m else "目标"
            delay = m.group(2) if m else "?"
            sb.status_line1.setText("运行中")
            sb.status_icon1.setText("⚡")
            sb.status_icon1.setStyleSheet(f"color: {CLR_BTN_SUCCESS};")
            sb.status_line2.setText(f"识别: {name}")
            sb.status_icon2.setText("🎯")
            sb.status_icon2.setStyleSheet(f"color: {CLR_BTN_SUCCESS};")
            sb.status_line3.setText(f"延迟 {delay}ms")
            sb.status_icon3.setText("⏱")
            sb.status_icon3.setStyleSheet(f"color: {CLR_TEXT_SUB};")

        elif "点击完成" in text:
            m = re.search(r'冷却 (\d+)ms', text)
            cd = m.group(1) if m else "?"
            sb.status_line1.setText("运行中")
            sb.status_icon1.setText("⚡")
            sb.status_icon1.setStyleSheet(f"color: {CLR_BTN_SUCCESS};")
            sb.status_line2.setText("点击完成")
            sb.status_icon2.setText("🖱")
            sb.status_icon2.setStyleSheet(f"color: {CLR_BTN_SUCCESS};")
            sb.status_line3.setText(f"冷却 {cd}ms")
            sb.status_icon3.setText("⏱")
            sb.status_icon3.setStyleSheet("color: #FF9800;")

        elif "截图失败" in text:
            sb.status_line1.setText("异常")
            sb.status_icon1.setText("⚠")
            sb.status_icon1.setStyleSheet(f"color: {CLR_BTN_DANGER};")
            sb.status_line2.setText("截图失败")
            sb.status_icon2.setText("📷")
            sb.status_icon2.setStyleSheet(f"color: {CLR_BTN_DANGER};")
            sb.status_line3.setText("1s 后重试")
            sb.status_icon3.setText("⏱")
            sb.status_icon3.setStyleSheet(f"color: {CLR_TEXT_SUB};")

        elif "已停止" in text or "无可用任务" in text:
            if self._stop_by_condition:
                self._update_remote_status_cache()  # 插入点A
                return
            sb.status_line1.setText("就绪")
            sb.status_icon1.setText("⚡")
            sb.status_icon1.setStyleSheet(f"color: {CLR_TEXT_SUB};")
            sb.status_line2.setText("—")
            sb.status_icon2.setText("🖱")
            sb.status_icon2.setStyleSheet(f"color: {CLR_TEXT_SUB};")
            sb.status_line3.setText("—")
            sb.status_icon3.setText("⏱")
            sb.status_icon3.setStyleSheet(f"color: {CLR_TEXT_SUB};")

        # 同步到悬浮窗（如果可见）
        if self._floating_widget and self._floating_widget.isVisible():
            self._floating_widget.sync_from_sidebar(sb)
        self._update_remote_status_cache()  # 插入点B

    def _on_engine_finished(self) -> None:
        if self._stop_by_condition:
            return

        self.sidebar.set_engine_running(False)
        sb = self.sidebar
        sb.status_line1.setText("就绪")
        sb.status_icon1.setText("⚡")
        sb.status_icon1.setStyleSheet(f"color: {CLR_TEXT_SUB};")
        sb.status_line2.setText("—")
        sb.status_icon2.setText("🖱")
        sb.status_icon2.setStyleSheet(f"color: {CLR_TEXT_SUB};")
        sb.status_line3.setText("—")
        sb.status_icon3.setText("⏱")
        sb.status_icon3.setStyleSheet(f"color: {CLR_TEXT_SUB};")

        # 统一同步悬浮窗状态（引擎停止完成后）
        if self._floating_widget and self._floating_widget.isVisible():
            self._floating_widget.sync_from_sidebar(sb)

        self._restore_window_if_auto_minimized()
        self._update_remote_status_cache()  # 插入点C

    def _on_dying_engine_finished(self) -> None:
        """wait 超时后旧引擎线程真正退出时的清理（此时线程已结束，可安全置 None）。"""
        self._engine = None
        self._engine_dying = False

    def _collect_task_configs(self) -> list[dict]:
        configs = []
        for card in self._task_cards:
            if card.is_configured():
                configs.append(card.to_dict())
        return configs

    # ---- 任务卡片管理 ----

    def _next_task_name(self) -> str:
        """生成 '任务N' 格式的唯一名称."""
        existing = {c.name_edit.text().strip() for c in self._task_cards}
        n = len(self._task_cards) + 1
        while f"任务{n}" in existing:
            n += 1
        return f"任务{n}"

    def _add_task(self, data: dict | None = None, refresh_combo: bool = True) -> None:
        card = CollapsibleTaskCard()
        if data:
            card.from_dict(data)
            card.set_collapsed(True)  # 有内容的卡片默认折叠
        else:
            card.set_collapsed(False)  # 新建空卡片默认展开
            card.name_edit.setText(self._next_task_name())  # 自动命名
        card.removed.connect(self._remove_task)
        card.moved_up.connect(self._move_task_up)
        card.moved_down.connect(self._move_task_down)
        self._task_cards.append(card)
        # 插入到 btn_add 之前(或 stretch 之前, 如果 btn_add 还未添加)
        insert_pos = self._card_layout.indexOf(self.btn_add)
        if insert_pos < 0:
            insert_pos = self._card_layout.count() - 1
        self._card_layout.insertWidget(insert_pos, card)
        self._refresh_move_buttons()
        if refresh_combo:
            self._refresh_stop_task_combo()
        # 启动后检查图片是否存在
        if card._image_path:
            card.check_image_exists()

    def _remove_task(self, card: CollapsibleTaskCard) -> None:
        """带动画删除卡片."""
        if card not in self._task_cards:
            return
        self._task_cards.remove(card)
        card._is_deleting = True

        # 阶段1: 透明度动画 1.0 → 0.0
        # 动态创建 opacity effect 替换 shadow（QGraphicsEffect 互斥）
        opacity_effect = QGraphicsOpacityEffect(card)
        opacity_effect.setOpacity(1.0)
        card.setGraphicsEffect(opacity_effect)

        opacity_anim = QPropertyAnimation(opacity_effect, b"opacity", card)
        opacity_anim.setDuration(150)
        opacity_anim.setStartValue(1.0)
        opacity_anim.setEndValue(0.0)
        opacity_anim.setEasingCurve(QEasingCurve.Type.InCubic)

        def on_opacity_done():
            # 阶段2: 高度收缩
            cur_h = card.height()
            height_anim = QPropertyAnimation(card, b"maximumHeight", card)
            height_anim.setDuration(120)
            height_anim.setStartValue(cur_h)
            height_anim.setEndValue(0)
            height_anim.setEasingCurve(QEasingCurve.Type.InCubic)

            def on_height_done():
                self._card_layout.removeWidget(card)
                card.deleteLater()
                self._refresh_move_buttons()
                self._refresh_stop_task_combo()

            height_anim.finished.connect(on_height_done)
            height_anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
            card._height_anim = height_anim

        opacity_anim.finished.connect(on_opacity_done)
        opacity_anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        card._opacity_anim = opacity_anim

    def _clear_tasks_no_anim(self) -> None:
        """清空所有任务卡片（无动画，用于导入替换）."""
        for card in self._task_cards:
            self._card_layout.removeWidget(card)
            card.deleteLater()
        self._task_cards.clear()
        self._refresh_move_buttons()

    def _move_task_up(self, card: CollapsibleTaskCard) -> None:
        idx = self._task_cards.index(card)
        if idx <= 0:
            return
        self._do_move_card(card, idx, idx - 1)

    def _move_task_down(self, card: CollapsibleTaskCard) -> None:
        idx = self._task_cards.index(card)
        if idx >= len(self._task_cards) - 1:
            return
        self._do_move_card(card, idx, idx + 1)

    def _do_move_card(self, card: CollapsibleTaskCard, from_idx: int, to_idx: int) -> None:
        """通用卡片移动：先重排布局，再动画滑动."""
        if self._moveAnimating:
            return
        self._moveAnimating = True
        # 1. 禁用所有移动按钮 + 删除按钮
        for c in self._task_cards:
            c.btn_up.setEnabled(False)
            c.btn_down.setEnabled(False)
            c.btn_delete.setEnabled(False)
        # 2. 记录旧位置
        old_pos = card.pos()
        # 3. 交换列表
        self._task_cards[from_idx], self._task_cards[to_idx] = (
            self._task_cards[to_idx], self._task_cards[from_idx]
        )
        # 4. 重排布局
        self._reorder_all_cards()
        self._refresh_move_buttons()
        # 5. 强制布局计算，拿到新位置
        # 注意: processEvents() 会处理排队中的其他事件（删除、折叠等），
        # 200ms 动画期间这些操作可能被触发。_moveAnimating 锁只防止重入移动，
        # 不防止其他操作。实际使用中 200ms 窗口极小，风险可接受。
        self._card_container.updateGeometry()
        QApplication.processEvents()
        new_pos = card.pos()
        # 6. 如果位置有变化，播放滑动动画
        if old_pos != new_pos:
            try:
                if hasattr(card, '_move_anim') and card._move_anim.state() == QPropertyAnimation.State.Running:
                    card._move_anim.stop()
            except RuntimeError:
                pass
            anim = QPropertyAnimation(card, b"pos", card)
            anim.setDuration(200)
            anim.setStartValue(old_pos)
            anim.setEndValue(new_pos)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)

            def on_done():
                self._moveAnimating = False
                self._refresh_move_buttons()
                for c in self._task_cards:
                    c.btn_delete.setEnabled(True)
                self._scroll.ensureWidgetVisible(card)

            anim.finished.connect(on_done)
            anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
            card._move_anim = anim
        else:
            self._moveAnimating = False
            self._refresh_move_buttons()
            for c in self._task_cards:
                c.btn_delete.setEnabled(True)
            self._scroll.ensureWidgetVisible(card)

    def _reorder_all_cards(self) -> None:
        """按 self._task_cards 顺序重建布局."""
        for card in self._task_cards:
            self._card_layout.removeWidget(card)
        insert_pos = self._card_layout.indexOf(self.btn_add)
        if insert_pos < 0:
            insert_pos = self._card_layout.count() - 1
        for i, card in enumerate(self._task_cards):
            self._card_layout.insertWidget(insert_pos + i, card)

    def _refresh_move_buttons(self) -> None:
        n = len(self._task_cards)
        for i, card in enumerate(self._task_cards):
            card.update_move_buttons(is_first=(i == 0), is_last=(i == n - 1))

    def _sync_settings_to_global(self) -> None:
        """同步所有 UI 控件的当前值到 _global_settings."""
        try:
            self._global_settings["scan_interval"] = int(self.edit_scan_interval.text() or "200")
        except ValueError:
            self._global_settings["scan_interval"] = 200
        speed_options = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0]
        self._global_settings["move_speed"] = speed_options[self.combo_move_speed.currentIndex()]
        self._global_settings["click_speed"] = speed_options[self.combo_click_speed.currentIndex()]
        self._global_settings["always_on_top"] = self.chk_top.isChecked()
        self._global_settings["auto_minimize"] = self.chk_auto_minimize.isChecked()
        self._global_settings["show_floating_widget"] = self.chk_floating.isChecked()
        self._global_settings["always_show_floating"] = self.chk_always_floating.isChecked()
        self._global_settings["floating_opacity"] = self.slider_opacity.value()
        self._global_settings["floating_disabled"] = self.chk_floating_disabled.isChecked()
        self._global_settings["stop_conditions"] = self._collect_stop_conditions()

    # ---- 方案导入导出 ----

    def _styled_msgbox(self) -> QMessageBox:
        """创建蓝天白云风格的 QMessageBox，置顶且居中于屏幕."""
        msg = QMessageBox(self)
        msg.setWindowFlags(msg.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        msg.setStyleSheet(f"""
            QMessageBox {{ background: {CLR_CARD_BG}; }}
            QMessageBox QLabel {{ color: {CLR_TEXT_MAIN}; font-size: 13px; }}
            QPushButton {{
                background: {CLR_CARD_BG}; border: 1px solid {CLR_CARD_BORDER};
                border-radius: 6px; padding: 6px 16px; font-size: 12px;
                color: {CLR_TEXT_MAIN}; min-width: 60px;
            }}
            QPushButton:hover {{ border-color: {CLR_BTN_PRIMARY}; color: {CLR_BTN_PRIMARY}; }}
        """)
        return msg

    def _exec_msgbox_centered(self, msg: QMessageBox) -> None:
        """显示 QMessageBox 并居中于屏幕."""
        msg.adjustSize()
        screen = QApplication.screenAt(self.geometry().center())
        if not screen:
            screen = QApplication.primaryScreen()
        geo = screen.availableGeometry()
        msg.move(
            geo.center().x() - msg.width() // 2,
            geo.center().y() - msg.height() // 2,
        )
        msg.exec()

    def _on_export(self) -> None:
        """导出当前所有任务配置为 .galt 文件."""
        if not self._task_cards:
            msg = self._styled_msgbox()
            msg.setWindowTitle("提示")
            msg.setText("当前没有任务可导出。")
            self._exec_msgbox_centered(msg)
            return

        # 生成默认文件名
        if len(self._task_cards) == 1:
            name = self._task_cards[0].name_edit.text().strip() or "方案"
            default_name = f"{name}.galt"
        else:
            default_name = f"方案_{int(time.time())}.galt"

        path, _ = QFileDialog.getSaveFileName(
            self, "导出方案", default_name, "方案文件 (*.galt);;所有文件 (*)"
        )
        if not path:
            return

        task_data = [card.to_dict() for card in self._task_cards]
        sc = self._collect_stop_conditions()
        export_obj = export_scheme(task_data, sc, self._stop_image_path)

        try:
            write_scheme_file(path, export_obj)
            msg = self._styled_msgbox()
            msg.setWindowTitle("导出成功")
            msg.setText(f"方案已保存到:\n{path}")
            self._exec_msgbox_centered(msg)
        except Exception as e:
            msg = self._styled_msgbox()
            msg.setWindowTitle("导出失败")
            msg.setText(f"保存文件时出错:\n{e}")
            self._exec_msgbox_centered(msg)

    def _on_import(self) -> None:
        """从 .galt 文件导入方案, 替换当前所有任务."""
        path, _ = QFileDialog.getOpenFileName(
            self, "导入方案", "", "方案文件 (*.galt);;所有文件 (*)"
        )
        if not path:
            return

        try:
            tasks_data, imported_stop_conditions, stop_image_filename, stop_image_data = \
                parse_scheme_file(path)
        except Exception as e:
            msg = self._styled_msgbox()
            msg.setWindowTitle("导入失败")
            msg.setText(f"无法读取文件:\n{e}")
            self._exec_msgbox_centered(msg)
            return

        msg = self._styled_msgbox()
        msg.setWindowTitle("导入方案")
        msg.setText("请选择导入方式：")
        msg.setInformativeText("替换：清空当前任务后导入\n新增：追加到当前任务末尾")
        btn_replace = msg.addButton("替换", QMessageBox.ButtonRole.AcceptRole)
        btn_append = msg.addButton("新增", QMessageBox.ButtonRole.ActionRole)
        btn_cancel = msg.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        self._exec_msgbox_centered(msg)

        if msg.clickedButton() != btn_replace and msg.clickedButton() != btn_append:
            return

        if msg.clickedButton() == btn_replace:
            self._clear_tasks_no_anim()

        # 新增模式 + 方案的停止条件总开关启用 → 询问是否覆盖当前停止条件
        # （export_scheme 会无条件写入 stop_conditions 字段，必须按 enabled 判断，
        #   否则未设置停止条件的方案导入时也会 100% 弹窗）
        apply_stop_conditions = True
        if (msg.clickedButton() == btn_append
                and isinstance(imported_stop_conditions, dict)
                and imported_stop_conditions.get("enabled", False)):
            msg_sc = self._styled_msgbox()
            msg_sc.setWindowTitle("导入停止条件")
            msg_sc.setText("新增方案包含停止条件，是否覆盖当前的停止条件？")
            msg_sc.setInformativeText(
                "是：将当前的停止条件替换为新增方案的停止条件\n"
                "否：保留当前的停止条件，不做改动"
            )
            btn_sc_yes = msg_sc.addButton("是", QMessageBox.ButtonRole.AcceptRole)
            btn_sc_no = msg_sc.addButton("否", QMessageBox.ButtonRole.RejectRole)
            btn_sc_cancel = msg_sc.addButton("取消", QMessageBox.ButtonRole.RejectRole)
            self._exec_msgbox_centered(msg_sc)
            if msg_sc.clickedButton() == btn_sc_cancel:
                return  # 中止整个导入（任务也不导入）
            apply_stop_conditions = (msg_sc.clickedButton() == btn_sc_yes)

        # 导入新任务（智能检测图片）
        for item in tasks_data:
            restore_task_image(item)
            # 名称去重
            name = item.get("name", "").strip()
            if not name:
                item["name"] = self._next_task_name()
            else:
                existing = {c.name_edit.text().strip() for c in self._task_cards}
                if name in existing:
                    n = 2
                    while f"{name}({n})" in existing:
                        n += 1
                    item["name"] = f"{name}({n})"
            self._add_task(item, refresh_combo=False)

        # 刷新停止条件 combo
        self._refresh_stop_task_combo()

        if apply_stop_conditions:
            # 还原停止条件图片
            restored = restore_stop_image(stop_image_filename, stop_image_data, self._stop_image_path)
            if restored:
                self._stop_image_path = restored

            if self._stop_image_path and os.path.exists(self._stop_image_path):
                pixmap = QPixmap(self._stop_image_path)
                if not pixmap.isNull():
                    self.stop_img_preview.setPixmap(pixmap.scaled(
                        60, 60, Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation
                    ))

            # 恢复停止条件配置（开关状态、参数值）
            if imported_stop_conditions and isinstance(imported_stop_conditions, dict):
                # 把还原的图片路径写入条件三
                if self._stop_image_path and "image_match_stop" in imported_stop_conditions:
                    imported_stop_conditions["image_match_stop"]["image_path"] = self._stop_image_path
                self._global_settings["stop_conditions"] = imported_stop_conditions
                # 恢复 UI
                sc = imported_stop_conditions
                self.chk_stop_enabled.blockSignals(True)
                self.chk_stop_enabled.setChecked(sc.get("enabled", False))
                self.chk_stop_enabled.blockSignals(False)

                tc = sc.get("task_exec_count", {})
                self.chk_stop_cond1.blockSignals(True)
                self.chk_stop_cond1.setChecked(tc.get("enabled", False))
                self.chk_stop_cond1.blockSignals(False)
                self.edit_stop_exec_count.setText(str(tc.get("count", 5)))

                # 恢复目标任务下拉框（导入时任务已加入 _task_cards，无需 pending 机制）
                task_name = tc.get("task_name", "")
                if task_name:
                    idx = self.combo_stop_task.findText(task_name)
                    if idx >= 0:
                        self.combo_stop_task.setCurrentIndex(idx)
                    elif self.chk_stop_cond1.isChecked():
                        self.chk_stop_cond1.setChecked(False)
                        logger.warning(f"导入方案的停止条件引用了不存在的任务「{task_name}」，已取消条件一勾选")

                rl = sc.get("run_time_limit", {})
                self.chk_stop_cond2.blockSignals(True)
                self.chk_stop_cond2.setChecked(rl.get("enabled", False))
                self.chk_stop_cond2.blockSignals(False)
                self.edit_stop_run_minutes.setText(str(rl.get("minutes", 10)))

                ims = sc.get("image_match_stop", {})
                self.chk_stop_cond3.blockSignals(True)
                self.chk_stop_cond3.setChecked(ims.get("enabled", False))
                self.chk_stop_cond3.blockSignals(False)
                self.slider_stop_threshold.setValue(ims.get("threshold", 90))

                nmt = sc.get("no_match_timeout", {})
                self.chk_stop_cond4.blockSignals(True)
                self.chk_stop_cond4.setChecked(nmt.get("enabled", False))
                self.chk_stop_cond4.blockSignals(False)
                self.edit_stop_idle_minutes.setText(str(nmt.get("minutes", 5)))

                self._on_stop_enabled_toggled(self.chk_stop_enabled.isChecked())

        self._save_config()

    # ---- 配置持久化 ----

    def _save_config(self) -> None:
        save_config(
            self._global_settings,
            [card.to_dict() for card in self._task_cards],
        )

    def _load_config(self) -> None:
        data = load_config()
        if data is None:
            # 首次使用：设置默认快捷键
            # 安全：populate_hotkeys 内部 _create_hotkey_row 对 chk 使用 blockSignals
            # 不会触发 hotkeys_changed 信号链
            self._global_settings["hotkeys"] = [{"key": "f8", "enabled": True}]
            self._global_settings["hotkeys_enabled"] = True
            self._settings_page.chk_hotkeys_enabled.blockSignals(True)
            self._settings_page.chk_hotkeys_enabled.setChecked(True)
            self._settings_page.chk_hotkeys_enabled.blockSignals(False)
            self._settings_page.populate_hotkeys(self._global_settings["hotkeys"])
            self._hotkey_mgr.register_all(self, "_toggle_engine", self._global_settings["hotkeys"])
            self._add_task()
            return
        if isinstance(data, dict):
                saved = data.get("settings", {})
                self._global_settings.update(saved)

                # 兼容旧配置：f8_enabled → hotkeys 迁移
                if "hotkeys" not in self._global_settings:
                    if self._global_settings.get("f8_enabled", True):
                        self._global_settings["hotkeys"] = [{"key": "f8", "enabled": True}]
                    else:
                        self._global_settings["hotkeys"] = []
                # 设置 hotkeys_enabled 默认值
                if "hotkeys_enabled" not in self._global_settings:
                    self._global_settings["hotkeys_enabled"] = True

                # 填充设置页快捷键列表 UI
                self._settings_page.chk_hotkeys_enabled.blockSignals(True)
                self._settings_page.chk_hotkeys_enabled.setChecked(
                    self._global_settings.get("hotkeys_enabled", True)
                )
                self._settings_page.chk_hotkeys_enabled.blockSignals(False)
                self._settings_page.populate_hotkeys(self._global_settings["hotkeys"])

                # 注册热键
                if self._global_settings.get("hotkeys_enabled", True):
                    enabled = [h for h in self._global_settings["hotkeys"] if h.get("enabled", True)]
                    if enabled:
                        self._hotkey_mgr.register_all(self, "_toggle_engine", enabled)

                # 同步 UI 控件 - 复选框
                self.chk_top.setChecked(
                    self._global_settings.get("always_on_top", False)
                )
                self.chk_auto_minimize.setChecked(
                    self._global_settings.get("auto_minimize", False)
                )
                # 用 blockSignals 防止加载配置时误触发预览
                self.chk_floating.blockSignals(True)
                self.chk_floating.setChecked(
                    self._global_settings.get("show_floating_widget", False)
                )
                self.chk_floating.blockSignals(False)

                self.slider_opacity.blockSignals(True)
                opacity_value = self._global_settings.get("floating_opacity", 100)
                self.slider_opacity.setValue(opacity_value)
                self.label_opacity.setText(f"{opacity_value}%")  # 手动更新标签
                self.slider_opacity.blockSignals(False)

                self.chk_floating_disabled.blockSignals(True)
                self.chk_floating_disabled.setChecked(
                    self._global_settings.get("floating_disabled", False)
                )
                self.chk_floating_disabled.blockSignals(False)

                # 新增：读取 always_show_floating
                self.chk_always_floating.blockSignals(True)
                self.chk_always_floating.setChecked(
                    self._global_settings.get("always_show_floating", False)
                )
                self.chk_always_floating.blockSignals(False)

                # 初始状态设置（不能直接调用 _on_floating_toggled，因为没有 sender）
                minimize_on = self.chk_floating.isChecked()
                always_on = self.chk_always_floating.isChecked()

                # 防御：如果配置异常导致两个都为 True，优先保留"始终显示"，重置"最小化"
                if minimize_on and always_on:
                    self.chk_floating.blockSignals(True)
                    self.chk_floating.setChecked(False)
                    self.chk_floating.blockSignals(False)
                    minimize_on = False

                any_on = minimize_on or always_on

                # 互斥：如果一个已勾选，禁用另一个
                if minimize_on:
                    self.chk_always_floating.setEnabled(False)
                if always_on:
                    self.chk_floating.setEnabled(False)

                # 联动子项
                self.slider_opacity.setEnabled(any_on)
                self.label_opacity.setEnabled(any_on)
                self.chk_floating_disabled.setEnabled(any_on)

                # 启动时如果勾选了"始终显示悬浮窗"，立即显示悬浮窗
                if always_on:
                    self._sync_and_show_floating()

                # 同步 UI 控件 - 图像扫描间隔
                self.edit_scan_interval.setText(
                    str(self._global_settings.get("scan_interval", 200))
                )

                # 同步 UI 控件 - 鼠标速度
                speed_options = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0]
                move_speed = self._global_settings.get("move_speed", 1.0)
                click_speed = self._global_settings.get("click_speed", 1.0)
                if move_speed in speed_options:
                    self.combo_move_speed.setCurrentIndex(speed_options.index(move_speed))
                if click_speed in speed_options:
                    self.combo_click_speed.setCurrentIndex(speed_options.index(click_speed))

                # 恢复停止条件配置
                sc = self._global_settings.get("stop_conditions", {})
                self.chk_stop_enabled.blockSignals(True)
                self.chk_stop_enabled.setChecked(sc.get("enabled", False))
                self.chk_stop_enabled.blockSignals(False)

                tc = sc.get("task_exec_count", {})
                self._pending_stop_cond1_enabled = tc.get("enabled", False)
                self.edit_stop_exec_count.setText(str(tc.get("count", 5)))
                self._pending_stop_task_name = tc.get("task_name", "")

                rl = sc.get("run_time_limit", {})
                self.chk_stop_cond2.blockSignals(True)
                self.chk_stop_cond2.setChecked(rl.get("enabled", False))
                self.chk_stop_cond2.blockSignals(False)
                self.edit_stop_run_minutes.setText(str(rl.get("minutes", 10)))

                ims = sc.get("image_match_stop", {})
                self.chk_stop_cond3.blockSignals(True)
                self.chk_stop_cond3.setChecked(ims.get("enabled", False))
                self.chk_stop_cond3.blockSignals(False)
                self._stop_image_path = ims.get("image_path") or None
                if self._stop_image_path and os.path.exists(self._stop_image_path):
                    pixmap = QPixmap(self._stop_image_path)
                    if not pixmap.isNull():
                        self.stop_img_preview.setPixmap(pixmap.scaled(
                            60, 60, Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation
                        ))
                    else:
                        self._stop_image_path = None
                        self.stop_img_preview.setText("⚠ 无效图片")
                elif self._stop_image_path:
                    self._stop_image_path = None
                    self.stop_img_preview.setText("⚠ 图片已丢失")
                    self.chk_stop_cond3.setChecked(False)
                self.slider_stop_threshold.setValue(ims.get("threshold", 90))

                nmt = sc.get("no_match_timeout", {})
                self.chk_stop_cond4.blockSignals(True)
                self.chk_stop_cond4.setChecked(nmt.get("enabled", False))
                self.chk_stop_cond4.blockSignals(False)
                self.edit_stop_idle_minutes.setText(str(nmt.get("minutes", 5)))

                self._on_stop_enabled_toggled(self.chk_stop_enabled.isChecked())

                tasks_raw = data.get("tasks", [])
                if not isinstance(tasks_raw, list):
                    logger.error("config.json 中 tasks 字段格式不正确，已忽略任务列表")
                    tasks_raw = []
                for item in tasks_raw:
                    # 补全空名称
                    if not item.get("name", "").strip():
                        item["name"] = self._next_task_name()
                    # 去重：与已加载的卡片名称冲突时自动加后缀
                    else:
                        existing = {c.name_edit.text().strip() for c in self._task_cards}
                        name = item["name"].strip()
                        if name in existing:
                            n = 2
                            while f"{name}({n})" in existing:
                                n += 1
                            item["name"] = f"{name}({n})"
                    self._add_task(item, refresh_combo=False)

                # 末尾统一刷新停止条件 combo
                self._refresh_stop_task_combo()
                if hasattr(self, '_pending_stop_task_name') and self._pending_stop_task_name:
                    idx = self.combo_stop_task.findText(self._pending_stop_task_name)
                    if idx >= 0:
                        self.combo_stop_task.setCurrentIndex(idx)
                    del self._pending_stop_task_name
                if hasattr(self, '_pending_stop_cond1_enabled'):
                    self.chk_stop_cond1.setChecked(self._pending_stop_cond1_enabled)
                    del self._pending_stop_cond1_enabled

        else:
            self._add_task()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        size = self.size()
        self._resize_grip.move(size.width() - 16, size.height() - 16)

    def closeEvent(self, event) -> None:
        self._hotkey_mgr.unregister_all()
        # 提前设置，防止 changeEvent 触发 fade_hide
        self._suppress_floating = True
        # 同步所有设置到 _global_settings
        self._sync_settings_to_global()
        if self._engine and self._engine.isRunning():
            try:
                self._engine.stop_condition_met.disconnect(self._on_stop_condition_met)
            except Exception:
                pass
            self._engine.stop()
            if not self._engine.wait(3000):
                logger.error("引擎线程未在 3 秒内退出，进程即将结束")
        # ===== 新增：停止远程监控服务器（异步，不阻塞UI）=====
        if self._remote_server:
            from remote_server import stop_server_async
            stop_server_async(self._remote_server, self._remote_thread)
            self._remote_server = None
            self._remote_thread = None
        # ===== 新增结束 =====
        # 保存悬浮窗位置并清理
        if self._floating_widget:
            if self._floating_widget.isVisible() or self._floating_widget._last_pos:
                pos = self._floating_widget._last_pos or self._floating_widget.pos()
                self._global_settings["floating_widget_pos"] = [pos.x(), pos.y()]
            self._floating_widget.close()
            self._floating_widget = None
        self._save_config()
        super().closeEvent(event)


# ============================================================
# 程序入口
# ============================================================

