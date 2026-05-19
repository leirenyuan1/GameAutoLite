"""
模块四: 主界面与引擎调度 (main_ui.py)
================================
功能: 程序唯一入口. 提供任务配置界面, 引擎调度线程, F8 热键启停,
     配置持久化(config.json).

技术要点:
  - 引擎运行在 QThread, 不阻塞 UI
  - 停止机制使用 threading.Event, 可安全退出循环
  - F8 热键双向切换启停, 热键回调通过 invokeMethod 转发主线程
  - 退出时保存 config.json, 启动时自动恢复
"""

import json
import os
import random
import sys
import threading
import time
import logging

import cv2
import numpy as np
import mss

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QCheckBox, QScrollArea,
    QSlider, QFrame, QSizePolicy, QFileDialog, QSpacerItem
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, pyqtSlot, QMetaObject, Q_ARG
from PyQt6.QtGui import QFont, QPixmap, QIntValidator
import keyboard

import image_engine
import mouse_controller
import overlay_selector

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

if getattr(sys, "frozen", False):
    _app_dir = os.path.dirname(os.path.abspath(sys.executable))
else:
    _app_dir = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(_app_dir, "config.json")


# ============================================================
# 任务卡片组件
# ============================================================

class TaskCard(QFrame):
    """单个任务配置卡片."""

    removed = pyqtSignal(object)
    moved_up = pyqtSignal(object)
    moved_down = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._image_path: str | None = None
        self._region: tuple[int, int, int, int] | None = None
        self._cooldown_min = 0
        self._cooldown_max = 0
        self._setup_ui()

    def _setup_ui(self) -> None:
        """构建卡片内部布局."""
        self.setObjectName("TaskCard")
        self.setStyleSheet("""
            #TaskCard {
                background: #ffffff;
                border-radius: 8px;
                border: 1px solid #d0d0d0;
                padding: 10px;
            }
        """)

        root = QVBoxLayout(self)
        root.setSpacing(6)

        # ---- 行1: 任务名称 + 操作按钮 ----
        row1 = QHBoxLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("任务名称")
        self.name_edit.setStyleSheet("font-size: 13px; padding: 4px;")

        self.btn_up = QPushButton("↑")
        self.btn_up.setFixedSize(28, 28)
        self.btn_up.setToolTip("上移")
        self.btn_up.clicked.connect(lambda: self.moved_up.emit(self))

        self.btn_down = QPushButton("↓")
        self.btn_down.setFixedSize(28, 28)
        self.btn_down.setToolTip("下移")
        self.btn_down.clicked.connect(lambda: self.moved_down.emit(self))

        self.btn_delete = QPushButton("🗑")
        self.btn_delete.setFixedSize(28, 28)
        self.btn_delete.setToolTip("删除")
        self.btn_delete.clicked.connect(lambda: self.removed.emit(self))

        row1.addWidget(self.name_edit, 1)
        row1.addWidget(self.btn_up)
        row1.addWidget(self.btn_down)
        row1.addWidget(self.btn_delete)
        root.addLayout(row1)

        # ---- 行2: 上传识别图 + 缩略图预览 ----
        row2 = QHBoxLayout()
        self.btn_upload = QPushButton("🖼 上传识别图")
        self.btn_upload.clicked.connect(self._on_upload_image)

        self.img_preview = QLabel()
        self.img_preview.setFixedSize(60, 60)
        self.img_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.img_preview.setStyleSheet(
            "border: 2px dashed #bbb; color: #999; font-size: 11px;"
        )
        self.img_preview.setText("无图片")

        self.btn_capture = QPushButton("📷 截图上传")
        self.btn_capture.clicked.connect(self._on_screenshot_capture)

        row2.addWidget(self.btn_upload)
        row2.addWidget(self.btn_capture)
        row2.addWidget(self.img_preview)
        row2.addStretch(1)
        root.addLayout(row2)

        # ---- 行3: 匹配精确度滑块 ----
        row3 = QHBoxLayout()
        row3.addWidget(QLabel("匹配精确度:"))

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(50, 99)
        self.slider.setValue(80)
        self.slider.wheelEvent = lambda event: event.ignore()
        self.slider.valueChanged.connect(self._on_slider_changed)

        self.label_threshold = QLabel("80%")

        row3.addWidget(self.slider, 1)
        row3.addWidget(self.label_threshold)
        root.addLayout(row3)

        # ---- 行4: 设定点击区域 ----
        row4 = QHBoxLayout()
        self.btn_region = QPushButton("⊕ 设定点击区域")
        self.btn_region.clicked.connect(self._on_set_region)

        self.label_region = QLabel("未设定")
        self.label_region.setStyleSheet("color: #999;")

        row4.addWidget(self.btn_region)
        row4.addWidget(self.label_region)
        row4.addStretch(1)
        root.addLayout(row4)

        # ---- 行5: 识别后随机延迟 ----
        row5 = QHBoxLayout()
        row5.addWidget(QLabel("识别后随机延迟: 最小"))

        self.edit_delay_min = QLineEdit("200")
        self.edit_delay_min.setFixedWidth(60)
        self.edit_delay_min.setValidator(QIntValidator(0, 9999))
        self.edit_delay_min.editingFinished.connect(self._validate_delay)

        row5.addWidget(self.edit_delay_min)
        row5.addWidget(QLabel("ms ~ 最大"))

        self.edit_delay_max = QLineEdit("500")
        self.edit_delay_max.setFixedWidth(60)
        self.edit_delay_max.setValidator(QIntValidator(0, 9999))
        self.edit_delay_max.editingFinished.connect(self._validate_delay)

        row5.addWidget(self.edit_delay_max)
        row5.addWidget(QLabel("ms"))
        row5.addStretch(1)
        root.addLayout(row5)

        # ---- 行6: 点击后冷却时间 ----
        row6 = QHBoxLayout()
        row6.addWidget(QLabel("点击后冷却:      最小"))

        self.edit_cooldown_min = QLineEdit("0")
        self.edit_cooldown_min.setFixedWidth(60)
        self.edit_cooldown_min.setValidator(QIntValidator(0, 99999))
        self.edit_cooldown_min.editingFinished.connect(self._validate_cooldown)

        row6.addWidget(self.edit_cooldown_min)
        row6.addWidget(QLabel("ms ~ 最大"))

        self.edit_cooldown_max = QLineEdit("0")
        self.edit_cooldown_max.setFixedWidth(60)
        self.edit_cooldown_max.setValidator(QIntValidator(0, 99999))
        self.edit_cooldown_max.editingFinished.connect(self._validate_cooldown)

        row6.addWidget(self.edit_cooldown_max)
        row6.addWidget(QLabel("ms"))
        row6.addStretch(1)
        root.addLayout(row6)

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
                "border: 2px dashed #f00; color: #f00; font-size: 11px;"
            )
            self._image_path = None
            return
        self.img_preview.setPixmap(pixmap.scaled(
            60, 60, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
        ))
        self.img_preview.setStyleSheet("border: 1px solid #ccc;")
        self._update_image_warning()

    def _on_screenshot_capture(self) -> None:
        """通过 overlay 框选屏幕区域, 截图并保存为模板图片."""
        main_win = self.window()
        if main_win and main_win.isVisible():
            main_win.hide()
        try:
            result = overlay_selector.get_region()
        finally:
            if main_win:
                main_win.show()
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
        app_dir = _app_dir
        save_dir = os.path.join(app_dir, "screenshots")
        os.makedirs(save_dir, exist_ok=True)
        timestamp = int(time.time() * 1000)
        save_path = os.path.join(save_dir, f"capture_{timestamp}.png")
        cv2.imwrite(save_path, img)

        self._image_path = save_path
        pixmap = QPixmap(save_path)
        self.img_preview.setPixmap(pixmap.scaled(
            60, 60, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
        ))
        self.img_preview.setStyleSheet("border: 1px solid #ccc;")
        self._update_image_warning()

    def _on_slider_changed(self, value: int) -> None:
        self.label_threshold.setText(f"{value}%")

    def _on_set_region(self) -> None:
        # 隐藏主窗口避免遮挡
        main_win = self.window()
        if main_win and main_win.isVisible():
            main_win.hide()
        try:
            result = overlay_selector.get_region()
        finally:
            if main_win:
                main_win.show()
        if result is not None:
            x, y, w, h = result
            self._region = (x, y, w, h)
            self.label_region.setText(f"{x},{y}  {w}×{h}")
            self.label_region.setStyleSheet("color: #333; font-weight: bold;")
        else:
            self.label_region.setText("未设定")
            self.label_region.setStyleSheet("color: #999;")
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
                "border: 2px dashed #f00; color: #f00; font-size: 10px;"
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

    # ---- 配置完备性 ----

    def is_configured(self) -> bool:
        """任务是否配置完整: 有图片 + 有区域."""
        has_image = bool(self._image_path and os.path.exists(self._image_path))
        has_region = self._region is not None
        return has_image and has_region

    # ---- 序列化 ----

    def to_dict(self) -> dict:
        return {
            "name": self.name_edit.text(),
            "image_path": self._image_path or "",
            "threshold": self.slider.value(),
            "region": list(self._region) if self._region else None,
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
                    "border: 2px dashed #f00; color: #f00; font-size: 10px;"
                )
                self._image_path = None
            else:
                self.img_preview.setPixmap(pixmap.scaled(
                    60, 60, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                ))
                self.img_preview.setStyleSheet("border: 1px solid #ccc;")
                self._update_image_warning()
        self.slider.setValue(data.get("threshold", 80))
        region = data.get("region")
        if region and len(region) == 4:
            x, y, w, h = region
            self._region = (int(x), int(y), int(w), int(h))
            self.label_region.setText(f"{int(x)},{int(y)}  {int(w)}×{int(h)}")
            self.label_region.setStyleSheet("color: #333; font-weight: bold;")
        self.edit_delay_min.setText(str(data.get("delay_min", 200)))
        self.edit_delay_max.setText(str(data.get("delay_max", 500)))
        self.edit_cooldown_min.setText(str(data.get("cooldown_min", 0)))
        self.edit_cooldown_max.setText(str(data.get("cooldown_max", 0)))


# ============================================================
# 引擎工作线程
# ============================================================

class EngineThread(QThread):
    """引擎调度线程: 循环截图-匹配-点击."""

    status_update = pyqtSignal(str)

    def __init__(self, task_configs: list[dict], parent=None):
        super().__init__(parent)
        self._task_configs = task_configs
        self._stop_event = threading.Event()

    def run(self) -> None:
        self.status_update.emit("● 运行中...")
        while not self._stop_event.is_set():
            # 1. 截全屏
            try:
                screenshot = image_engine.take_screenshot()
            except Exception as e:
                logger.error(f"截图失败: {e}")
                self.status_update.emit("● 截图失败, 1秒后重试...")
                time.sleep(1)
                continue

            # 2. 按列表从上到下顺序扫描
            matched = False
            for cfg in self._task_configs:
                if self._stop_event.is_set():
                    break

                template = image_engine.load_template(cfg["image_path"])
                if template is None:
                    continue

                result = image_engine.find_template(
                    screenshot, template, cfg["threshold"] / 100.0
                )
                if result is not None:
                    # 3. 匹配成功 → 随机延迟
                    _dmin, _dmax = cfg["delay_min"], cfg["delay_max"]
                    delay_ms = random.randint(_dmin, max(_dmin, _dmax))
                    self.status_update.emit(
                        f"● 匹配到「{cfg['name']}」, 延迟 {delay_ms}ms 后点击"
                    )
                    self._sleep_interruptible(delay_ms / 1000.0)
                    if self._stop_event.is_set():
                        break

                    # 4. 执行点击
                    rx, ry, rw, rh = cfg["region"]
                    try:
                        mouse_controller.click_in_region(rx, ry, rw, rh)
                    except Exception as e:
                        logger.error(f"点击失败: {e}")

                    # 5. 点击后冷却
                    _cmin = cfg.get("cooldown_min", 0)
                    _cmax = cfg.get("cooldown_max", 0)
                    cooldown_ms = random.randint(_cmin, max(_cmin, _cmax))
                    if cooldown_ms > 0 and not self._stop_event.is_set():
                        self.status_update.emit(
                            f"● 点击完成, 冷却 {cooldown_ms}ms"
                        )
                        self._sleep_interruptible(cooldown_ms / 1000.0)

                    matched = True
                    # 6. 本轮结束, 回到步骤1
                    break

            if not matched and not self._stop_event.is_set():
                self.status_update.emit("● 运行中...")

        self.status_update.emit("● 已停止")

    def _sleep_interruptible(self, seconds: float) -> None:
        """可被打断的 sleep, 每 50ms 检查一次停止标志."""
        end = time.time() + seconds
        while time.time() < end and not self._stop_event.is_set():
            time.sleep(0.05)

    def stop(self) -> None:
        self._stop_event.set()


# ============================================================
# 主窗口
# ============================================================

class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("GameAutoLite")
        self.setFixedWidth(480)
        self.setMinimumHeight(500)

        self._task_cards: list[TaskCard] = []
        self._engine: EngineThread | None = None
        self._f8_registered = True

        self._setup_ui()
        self._register_f8_hotkey()
        self._load_config()

    # ---- UI 构建 ----

    def _setup_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        self.setStyleSheet("QMainWindow { background-color: #f2f2f2; }")

        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(12, 12, 12, 8)
        main_layout.setSpacing(8)

        # -- 顶部标题区 --
        title = QLabel("🎮 GameAutoLite")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setFont(QFont("Microsoft YaHei", 20, QFont.Weight.Bold))
        title.setStyleSheet("color: #2c3e50; margin-top: 4px;")

        subtitle = QLabel("极简游戏自动化助手")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setFont(QFont("Microsoft YaHei", 10))
        subtitle.setStyleSheet("color: #888; margin-bottom: 4px;")

        main_layout.addWidget(title)
        main_layout.addWidget(subtitle)

        # -- 可滚动任务列表区 --
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setStyleSheet("QScrollArea { background: transparent; }")

        self._card_container = QWidget()
        self._card_container.setStyleSheet("background: transparent;")
        self._card_layout = QVBoxLayout(self._card_container)
        self._card_layout.setSpacing(8)
        self._card_layout.setContentsMargins(0, 0, 0, 0)
        self._card_layout.addStretch(1)  # 底部弹簧, 卡片从顶部堆叠

        self._scroll.setWidget(self._card_container)
        main_layout.addWidget(self._scroll, 1)

        # -- 添加任务按钮 --
        self.btn_add = QPushButton("＋ 添加任务")
        self.btn_add.setStyleSheet("""
            QPushButton {
                background: #fff; border: 2px dashed #aaa; border-radius: 6px;
                padding: 8px; font-size: 13px; color: #666;
            }
            QPushButton:hover { border-color: #4a90d9; color: #4a90d9; }
        """)
        self.btn_add.clicked.connect(lambda: self._add_task())
        self._card_layout.insertWidget(
            self._card_layout.count() - 1, self.btn_add
        )

        # -- 启停控制区 --
        ctrl_frame = QFrame()
        ctrl_frame.setStyleSheet("""
            QFrame { background: #fff; border-radius: 8px; border: 1px solid #d0d0d0; padding: 10px; }
        """)
        ctrl_layout = QVBoxLayout(ctrl_frame)
        ctrl_layout.setSpacing(8)

        # F8 勾选框
        self.chk_f8 = QCheckBox("启用 F8 快捷键启停")
        self.chk_f8.setChecked(True)
        self.chk_f8.toggled.connect(self._on_f8_toggled)
        ctrl_layout.addWidget(self.chk_f8)

        # 窗口置顶勾选框
        self.chk_top = QCheckBox("📌 窗口置顶")
        self.chk_top.setChecked(False)
        self.chk_top.toggled.connect(self._on_top_toggled)
        ctrl_layout.addWidget(self.chk_top)

        # 开始/停止按钮
        self.btn_toggle = QPushButton("▶  开  始")
        self.btn_toggle.setStyleSheet(self._start_btn_style())
        self.btn_toggle.clicked.connect(self._on_toggle_clicked)
        ctrl_layout.addWidget(self.btn_toggle)

        # 状态标签
        self.label_status = QLabel("● 就绪")
        self.label_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label_status.setFont(QFont("Microsoft YaHei", 10))
        self.label_status.setStyleSheet("color: #888;")
        ctrl_layout.addWidget(self.label_status)

        main_layout.addWidget(ctrl_frame)

        # -- 底部提示栏(固定) --
        hint = QLabel("💡 提示: 如点击无效, 请右键本软件选择\"以管理员身份运行\"")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setFont(QFont("Microsoft YaHei", 9))
        hint.setStyleSheet("color: #aaa; padding: 4px;")
        main_layout.addWidget(hint)

    # ---- F8 热键 ----

    def _register_f8_hotkey(self) -> None:
        try:
            keyboard.add_hotkey("f8", self._on_f8_hotkey)
            self._f8_registered = True
        except Exception as e:
            logger.warning(f"F8 热键注册失败: {e}")
            self._f8_registered = False

    def _unregister_f8_hotkey(self) -> None:
        try:
            keyboard.remove_hotkey("f8")
        except Exception:
            pass
        self._f8_registered = False

    def _on_f8_toggled(self, checked: bool) -> None:
        if checked:
            self._register_f8_hotkey()
        else:
            self._unregister_f8_hotkey()

    def _on_top_toggled(self, checked: bool) -> None:
        """切换窗口置顶状态."""
        flags = self.windowFlags()
        if checked:
            self.setWindowFlags(flags | Qt.WindowType.WindowStaysOnTopHint)
        else:
            self.setWindowFlags(flags & ~Qt.WindowType.WindowStaysOnTopHint)
        # 修改 windowFlags 后需要重新 show 才能生效
        self.show()

    def _on_f8_hotkey(self) -> None:
        """热键回调在 keyboard 的钩子线程中执行, 必须转发到主线程."""
        QMetaObject.invokeMethod(
            self, "_toggle_engine", Qt.ConnectionType.QueuedConnection
        )

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
        # 收集所有配置完整的任务
        configs = self._collect_task_configs()
        if not configs:
            self.label_status.setText("● 无可用任务(需设置图片和点击区域)")
            self.label_status.setStyleSheet("color: #e67e22;")
            return

        self._engine = EngineThread(configs)
        self._engine.status_update.connect(self._on_status_update)
        self._engine.finished.connect(self._on_engine_finished)
        self._engine.start()

        self.btn_toggle.setText("⏹  停  止")
        self.btn_toggle.setStyleSheet(self._stop_btn_style())

    def _stop_engine(self) -> None:
        if self._engine:
            self._engine.stop()
            self._engine.wait(3000)
        self._on_engine_finished()

    def _on_status_update(self, text: str) -> None:
        if "运行中" in text:
            self.label_status.setStyleSheet("color: #27ae60;")
        elif "已停止" in text or "失败" in text:
            self.label_status.setStyleSheet("color: #e74c3c;")
        else:
            self.label_status.setStyleSheet("color: #f39c12;")
        self.label_status.setText(text)

    def _on_engine_finished(self) -> None:
        self.btn_toggle.setText("▶  开  始")
        self.btn_toggle.setStyleSheet(self._start_btn_style())
        self.label_status.setText("● 已停止")
        self.label_status.setStyleSheet("color: #e74c3c;")

    def _collect_task_configs(self) -> list[dict]:
        configs = []
        for card in self._task_cards:
            if card.is_configured():
                configs.append(card.to_dict())
        return configs

    # ---- 任务卡片管理 ----

    def _add_task(self, data: dict | None = None) -> None:
        card = TaskCard()
        if data:
            card.from_dict(data)
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
        # 启动后检查图片是否存在
        if card._image_path:
            card.check_image_exists()

    def _remove_task(self, card: TaskCard) -> None:
        self._task_cards.remove(card)
        self._card_layout.removeWidget(card)
        card.deleteLater()
        self._refresh_move_buttons()

    def _move_task_up(self, card: TaskCard) -> None:
        idx = self._task_cards.index(card)
        if idx <= 0:
            return
        self._task_cards[idx], self._task_cards[idx - 1] = (
            self._task_cards[idx - 1], self._task_cards[idx]
        )
        self._reorder_cards()
        self._refresh_move_buttons()

    def _move_task_down(self, card: TaskCard) -> None:
        idx = self._task_cards.index(card)
        if idx >= len(self._task_cards) - 1:
            return
        self._task_cards[idx], self._task_cards[idx + 1] = (
            self._task_cards[idx + 1], self._task_cards[idx]
        )
        self._reorder_cards()
        self._refresh_move_buttons()

    def _reorder_cards(self) -> None:
        """按 self._task_cards 顺序重建布局中的卡片位置."""
        for card in self._task_cards:
            self._card_layout.removeWidget(card)
        # 获取 btn_add 当前位置作为插入基准
        insert_pos = self._card_layout.indexOf(self.btn_add)
        if insert_pos < 0:
            insert_pos = self._card_layout.count() - 1
        for i, card in enumerate(self._task_cards):
            self._card_layout.insertWidget(insert_pos + i, card)

    def _refresh_move_buttons(self) -> None:
        n = len(self._task_cards)
        for i, card in enumerate(self._task_cards):
            card.update_move_buttons(is_first=(i == 0), is_last=(i == n - 1))

    # ---- 按钮样式 ----

    @staticmethod
    def _start_btn_style() -> str:
        return """
            QPushButton {
                background: #27ae60; color: #fff; border: none; border-radius: 6px;
                padding: 10px; font-size: 15px; font-weight: bold;
            }
            QPushButton:hover { background: #2ecc71; }
            QPushButton:pressed { background: #1e8449; }
        """

    @staticmethod
    def _stop_btn_style() -> str:
        return """
            QPushButton {
                background: #e74c3c; color: #fff; border: none; border-radius: 6px;
                padding: 10px; font-size: 15px; font-weight: bold;
            }
            QPushButton:hover { background: #ec7063; }
            QPushButton:pressed { background: #c0392b; }
        """

    # ---- 配置持久化 ----

    def _save_config(self) -> None:
        data = [card.to_dict() for card in self._task_cards]
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存配置失败: {e}")

    def _load_config(self) -> None:
        if not os.path.exists(CONFIG_FILE):
            # 首次启动, 自动添加一个空白任务卡片
            self._add_task()
            return
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            for item in data:
                self._add_task(item)
        except Exception as e:
            logger.error(f"加载配置失败: {e}")
            self._add_task()

    def closeEvent(self, event) -> None:
        self._unregister_f8_hotkey()
        if self._engine and self._engine.isRunning():
            self._engine.stop()
            self._engine.wait(3000)
        self._save_config()
        super().closeEvent(event)


# ============================================================
# 程序入口
# ============================================================

if __name__ == "__main__":
    # 强制 Qt 使用 1:1 缩放因子, 确保 overlay_selector / mss / win32api
    # 三者使用同一物理像素坐标系, 消除 125%/150%/200% 缩放下的坐标漂移.
    # Qt6 默认已设置 PerMonitorAwareV2, 无需再手动调用 SetProcessDpiAwareness.
    os.environ["QT_SCALE_FACTOR"] = "1"
    app = QApplication(sys.argv)
    app.setFont(QFont("Microsoft YaHei", 10))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
