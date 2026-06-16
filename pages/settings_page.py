"""全局设置页 (pages/settings_page.py)"""
from __future__ import annotations
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QIntValidator
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QCheckBox, QSlider, QComboBox, QLineEdit, QFrame, QScrollArea,
    QSizePolicy, QDialog,
)

from styles.colors import (
    CLR_TEXT_MAIN, CLR_TEXT_SUB, CLR_CARD_BG, CLR_CARD_BORDER,
    CLR_BTN_PRIMARY,
)
from pages.utils import make_settings_card

if TYPE_CHECKING:
    from main_window import MainWindow


class SettingsPage(QWidget):
    hotkeys_changed = pyqtSignal(list)  # 类属性

    def __init__(self, main_win: 'MainWindow', parent=None):
        super().__init__(parent)
        self._main_win = main_win
        self._hotkeys: list[dict] = []
        self._setup_ui()

    def _setup_ui(self) -> None:
        """构建全局设置页."""
        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(0)

        # 顶部工具栏（与任务列表页统一结构）
        toolbar = QWidget()
        toolbar.setMinimumHeight(32)
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(12, 8, 12, 8)
        toolbar_layout.setSpacing(8)

        settings_title = QLabel("全局设置")
        settings_title.setStyleSheet(
            f"font-size: 16px; font-weight: bold; color: {CLR_TEXT_MAIN};"
        )
        toolbar_layout.addWidget(settings_title)
        toolbar_layout.addStretch(1)
        page_layout.addWidget(toolbar)

        # -- 可滚动设置区 --
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; }")

        settings_container = QWidget()
        settings_container.setStyleSheet("background: transparent;")
        settings_layout = QVBoxLayout(settings_container)
        settings_layout.setContentsMargins(12, 8, 12, 8)
        settings_layout.setSpacing(10)

        # 分组 1 — 扫描设置
        scan_card, scan_layout = make_settings_card("扫描设置")

        scan_row = QHBoxLayout()
        scan_row.setContentsMargins(0, 0, 0, 0)  # 保持原值，由 card_layout.setSpacing(6) 统一控制间距
        scan_row.setSpacing(8)  # 原为 4

        lbl_scan = QLabel("图像扫描间隔：")
        lbl_scan.setStyleSheet(f"color: {CLR_TEXT_MAIN}; font-size: 12px;")
        scan_row.addWidget(lbl_scan)  # 去掉 stretch=1，让标签不占据剩余空间

        self.edit_scan_interval = QLineEdit("200")
        self.edit_scan_interval.setFixedWidth(64)  # 原为 55
        self.edit_scan_interval.setAlignment(Qt.AlignmentFlag.AlignCenter)  # 以下两行为新增
        self.edit_scan_interval.setValidator(QIntValidator(0, 10000))
        # 以下 QSS 为新增
        self.edit_scan_interval.setStyleSheet(f"""
            QLineEdit {{
                background: white; border: 1px solid {CLR_CARD_BORDER};
                border-radius: 6px; padding: 4px 6px;
                font-size: 12px; color: {CLR_TEXT_MAIN};
            }}
        """)
        scan_row.addWidget(self.edit_scan_interval)

        lbl_ms = QLabel("ms")
        lbl_ms.setFixedWidth(24)  # 以下两行为新增
        lbl_ms.setStyleSheet(f"color: {CLR_TEXT_SUB}; font-size: 11px;")
        scan_row.addWidget(lbl_ms)

        scan_row.addStretch(1)  # 在末尾添加 stretch，让内容左对齐
        scan_layout.addLayout(scan_row)

        scan_desc = QLabel("未匹配图像时每轮扫描的等待时间，设为 0 则全速扫描")
        scan_desc.setStyleSheet(f"color: {CLR_TEXT_SUB}; font-size: 11px;")
        scan_desc.setWordWrap(True)  # 极窄窗口下自动换行，防止文字溢出
        scan_layout.addWidget(scan_desc)

        settings_layout.addWidget(scan_card)

        # 分组 2 — 鼠标速度
        speed_card, speed_layout = make_settings_card("鼠标速度")

        speed_options = ["0.5X", "0.75X", "1.0X", "1.25X", "1.5X", "2.0X"]

        speed_row = QHBoxLayout()
        speed_row.setContentsMargins(0, 0, 0, 0)  # 保持原值，由 card_layout.setSpacing(6) 统一控制间距
        speed_row.setSpacing(8)

        lbl_move = QLabel("移动速度：")
        lbl_move.setMinimumWidth(56)
        lbl_move.setStyleSheet(f"color: {CLR_TEXT_MAIN}; font-size: 12px;")
        speed_row.addWidget(lbl_move)

        self.combo_move_speed = QComboBox()
        self.combo_move_speed.addItems(speed_options)
        self.combo_move_speed.setCurrentIndex(2)
        self.combo_move_speed.setMinimumWidth(80)
        self.combo_move_speed.setMaximumWidth(120)
        self.combo_move_speed.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed
        )
        self.combo_move_speed.wheelEvent = lambda event: event.ignore()
        # ComboBox 样式保持不变，必须保留
        self.combo_move_speed.setStyleSheet(f"""
            QComboBox {{ background: white; border: 1px solid {CLR_CARD_BORDER};
                border-radius: 6px; padding: 4px 8px; font-size: 12px; color: {CLR_TEXT_MAIN}; }}
            QComboBox QAbstractItemView {{ background: white; color: {CLR_TEXT_MAIN};
                selection-background-color: {CLR_BTN_PRIMARY}; selection-color: white; }}
        """)
        speed_row.addWidget(self.combo_move_speed)

        speed_row.addSpacing(12)  # 固定间距 12px，避免极小窗口下两组粘连（原为 addSpacing(4)）

        lbl_click = QLabel("点击速度：")
        lbl_click.setMinimumWidth(56)
        lbl_click.setStyleSheet(f"color: {CLR_TEXT_MAIN}; font-size: 12px;")
        speed_row.addWidget(lbl_click)

        self.combo_click_speed = QComboBox()
        self.combo_click_speed.addItems(speed_options)
        self.combo_click_speed.setCurrentIndex(2)
        self.combo_click_speed.setMinimumWidth(80)
        self.combo_click_speed.setMaximumWidth(120)
        self.combo_click_speed.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed
        )
        self.combo_click_speed.wheelEvent = lambda event: event.ignore()
        # ComboBox 样式保持不变，必须保留
        self.combo_click_speed.setStyleSheet(f"""
            QComboBox {{ background: white; border: 1px solid {CLR_CARD_BORDER};
                border-radius: 6px; padding: 4px 8px; font-size: 12px; color: {CLR_TEXT_MAIN}; }}
            QComboBox QAbstractItemView {{ background: white; color: {CLR_TEXT_MAIN};
                selection-background-color: {CLR_BTN_PRIMARY}; selection-color: white; }}
        """)
        speed_row.addWidget(self.combo_click_speed)

        speed_row.addStretch(1)  # 吸收右侧剩余空间，防止窗口拉宽后标签被拉伸
        speed_layout.addLayout(speed_row)

        settings_layout.addWidget(speed_card)

        # 分组 3 — 快捷键与窗口
        hotkey_card, hotkey_layout = make_settings_card("快捷键与窗口")

        self.chk_hotkeys_enabled = QCheckBox("启用快捷键启停")
        # 正确顺序：先 blockSignals + setChecked，再连接信号
        self.chk_hotkeys_enabled.blockSignals(True)
        self.chk_hotkeys_enabled.setChecked(True)
        self.chk_hotkeys_enabled.blockSignals(False)
        self.chk_hotkeys_enabled.toggled.connect(self._on_hotkeys_enabled_toggled)
        hotkey_layout.addWidget(self.chk_hotkeys_enabled)

        # 快捷键列表 UI
        self._hotkey_list_widget = QWidget()
        self._hotkey_list_layout = QVBoxLayout(self._hotkey_list_widget)
        self._hotkey_list_layout.setContentsMargins(0, 0, 0, 0)
        self._hotkey_list_layout.setSpacing(4)
        hotkey_layout.addWidget(self._hotkey_list_widget)

        self._btn_add_hotkey = QPushButton("+ 添加快捷键")
        self._btn_add_hotkey.setFixedHeight(28)
        self._btn_add_hotkey.setStyleSheet(f"""
            QPushButton {{
                background: transparent; border: 1px solid {CLR_CARD_BORDER};
                border-radius: 4px; color: {CLR_TEXT_SUB}; font-size: 12px;
            }}
            QPushButton:hover {{ border-color: {CLR_BTN_PRIMARY}; color: {CLR_BTN_PRIMARY}; }}
        """)
        self._btn_add_hotkey.clicked.connect(self._on_add_hotkey)
        hotkey_layout.addWidget(self._btn_add_hotkey)

        self.chk_top = QCheckBox("📌 窗口置顶")
        self.chk_top.setChecked(False)
        self.chk_top.toggled.connect(self._main_win._on_top_toggled)
        hotkey_layout.addWidget(self.chk_top)

        self.chk_auto_minimize = QCheckBox("开始后自动最小化")
        self.chk_auto_minimize.setChecked(False)
        hotkey_layout.addWidget(self.chk_auto_minimize)

        settings_layout.addWidget(hotkey_card)

        # 分组 4 — 悬浮窗设置
        floating_card, floating_layout = make_settings_card("悬浮窗设置")

        # 1. 最小化时显示悬浮窗
        self.chk_floating = QCheckBox("最小化时显示悬浮窗")
        self.chk_floating.setChecked(False)
        self.chk_floating.setStyleSheet(f"""
            QCheckBox {{ color: {CLR_TEXT_MAIN}; font-size: 13px; }}
            QCheckBox:disabled {{ color: {CLR_TEXT_SUB}; }}
        """)
        self.chk_floating.toggled.connect(self._main_win._on_floating_toggled)
        floating_layout.addWidget(self.chk_floating)

        # 2. 始终显示悬浮窗
        self.chk_always_floating = QCheckBox("始终显示悬浮窗")
        self.chk_always_floating.setChecked(False)
        self.chk_always_floating.setStyleSheet(f"""
            QCheckBox {{ color: {CLR_TEXT_MAIN}; font-size: 13px; }}
            QCheckBox:disabled {{ color: {CLR_TEXT_SUB}; }}
        """)
        self.chk_always_floating.toggled.connect(self._main_win._on_floating_toggled)
        floating_layout.addWidget(self.chk_always_floating)

        # 3. 透明度滑块
        opacity_container = QWidget()
        # 删除 opacity_container.setFixedHeight(32) 这一行
        opacity_row = QHBoxLayout(opacity_container)
        opacity_row.setContentsMargins(0, 0, 0, 0)  # 保持原值，由 card_layout.setSpacing(6) 统一控制间距
        opacity_row.setSpacing(8)

        # 注意：这是"悬浮窗透明度"标题标签，不是 self.label_opacity
        lbl_opacity = QLabel("悬浮窗透明度：")
        lbl_opacity.setMinimumWidth(80)  # 使用 setMinimumWidth 避免某些字体下文字截断
        lbl_opacity.setStyleSheet(f"color: {CLR_TEXT_MAIN}; font-size: 13px;")
        opacity_row.addWidget(lbl_opacity)

        self.slider_opacity = QSlider(Qt.Orientation.Horizontal)
        self.slider_opacity.setRange(30, 100)
        self.slider_opacity.setValue(100)
        self.slider_opacity.setSingleStep(5)
        self.slider_opacity.setPageStep(5)
        self.slider_opacity.wheelEvent = lambda event: event.ignore()  # 禁用滚轮调整滑块
        self.slider_opacity.valueChanged.connect(self._main_win._on_opacity_changed)
        self.slider_opacity.setStyleSheet(f"""
            QSlider::groove:horizontal {{
                height: 4px; background: {CLR_CARD_BORDER}; border-radius: 2px;
            }}
            QSlider::handle:horizontal {{
                width: 14px; height: 14px; margin: -5px 0;
                background: {CLR_BTN_PRIMARY}; border-radius: 7px;
            }}
            QSlider::sub-page:horizontal {{
                background: {CLR_BTN_PRIMARY}; border-radius: 2px;
            }}
            QSlider::add-page:horizontal {{
                background: {CLR_CARD_BORDER}; border-radius: 2px;
            }}
            QSlider::groove:horizontal:disabled {{
                background: #D0DDE8;
            }}
            QSlider::handle:horizontal:disabled {{
                background: #B0C4D4;
            }}
            QSlider::sub-page:horizontal:disabled {{
                background: #B0C4D4;
            }}
            QSlider::add-page:horizontal:disabled {{
                background: #E6EEF5;
            }}
        """)
        # slider 保持不变，stretch=1
        opacity_row.addWidget(self.slider_opacity, 1)

        # 注意：这是右侧显示百分比的标签，与上面的 lbl_opacity 不同
        self.label_opacity = QLabel("100%")
        self.label_opacity.setFixedWidth(40)
        self.label_opacity.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.label_opacity.setStyleSheet(f"""
            QLabel {{ color: {CLR_TEXT_MAIN}; font-size: 12px; }}
            QLabel:disabled {{ color: {CLR_TEXT_SUB}; }}
        """)
        opacity_row.addWidget(self.label_opacity)

        floating_layout.addWidget(opacity_container)

        # 3. 禁用交互
        self.chk_floating_disabled = QCheckBox("禁用悬浮窗交互（开启后所有鼠标事件穿透到下层窗口）")
        self.chk_floating_disabled.setChecked(False)
        self.chk_floating_disabled.setStyleSheet(f"""
            QCheckBox {{ color: {CLR_TEXT_MAIN}; font-size: 13px; }}
            QCheckBox:disabled {{ color: {CLR_TEXT_SUB}; }}
        """)
        self.chk_floating_disabled.toggled.connect(self._main_win._on_floating_disabled_toggled)
        floating_layout.addWidget(self.chk_floating_disabled)

        settings_layout.addWidget(floating_card)

        settings_layout.addStretch(1)

        # 初始状态：两个复选框初始都是 False，子项禁用
        self.slider_opacity.setEnabled(False)
        self.label_opacity.setEnabled(False)
        self.chk_floating_disabled.setEnabled(False)

        # 将设置容器设置为滚动区域的 widget
        scroll.setWidget(settings_container)
        page_layout.addWidget(scroll, 1)  # stretch=1 让滚动区域占满剩余空间

        # self._stack.addWidget(page)  # 由 MainWindow._setup_ui 负责 addWidget

    # ---- 悬浮窗控制 ----

    # ---- 快捷键管理 ----

    def populate_hotkeys(self, hotkeys: list[dict]) -> None:
        """用配置数据填充快捷键列表 UI。"""
        # 注意：这里是共享引用，不是拷贝
        # _hotkeys 直接引用 _global_settings["hotkeys"]，修改 _hotkeys 里的 dict 会同步到 _global_settings
        # 这是有意设计 — closeEvent 时 _global_settings 被统一保存到 config.json
        self._hotkeys = hotkeys
        self._rebuild_hotkey_list()

    def _rebuild_hotkey_list(self) -> None:
        """重建快捷键列表 UI。"""
        # 清空旧的 widget — 使用 setParent(None) 立即断开，不用 deleteLater()
        while self._hotkey_list_layout.count():
            item = self._hotkey_list_layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
        self._hotkey_rows: list[QWidget] = []
        # 为每条快捷键创建一行
        enabled = self.chk_hotkeys_enabled.isChecked()
        for hotkey in self._hotkeys:
            row = self._create_hotkey_row(hotkey)
            row.setEnabled(enabled)
            self._hotkey_list_layout.addWidget(row)
            self._hotkey_rows.append(row)

    def _set_hotkey_list_enabled(self, enabled: bool) -> None:
        """启用/禁用整个快捷键列表。"""
        if hasattr(self, "_hotkey_rows"):
            for row in self._hotkey_rows:
                row.setEnabled(enabled)

    def _create_hotkey_row(self, hotkey: dict) -> QWidget:
        """创建单条快捷键的 UI 行。"""
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)

        chk = QCheckBox()
        chk.setStyleSheet(f"""
            QCheckBox {{
                color: {CLR_TEXT_MAIN}; font-size: 12px;
                spacing: 6px;
            }}
            QCheckBox::indicator {{
                width: 16px; height: 16px;
            }}
        """)
        # 必须 blockSignals：setChecked 会 emit toggled，否则 populate_hotkeys 会触发信号链
        chk.blockSignals(True)
        chk.setChecked(hotkey.get("enabled", True))
        chk.blockSignals(False)
        chk.toggled.connect(lambda checked, k=hotkey["key"]: self._on_hotkey_toggled(k, checked))
        layout.addWidget(chk)

        # 快捷键名称徽章（淡蓝色底纹）
        badge = QLabel(hotkey["key"])
        badge.setStyleSheet(f"""
            QLabel {{
                background: #E8F4FD; color: #2980B9;
                border-radius: 4px; padding: 2px 8px;
                font-size: 12px; font-weight: bold;
            }}
        """)
        layout.addWidget(badge)

        layout.addStretch(1)

        btn_del = QPushButton("×")
        btn_del.setFixedWidth(30)
        btn_del.setFixedHeight(24)
        btn_del.setStyleSheet(f"""
            QPushButton {{ background: transparent; border: none; color: {CLR_TEXT_SUB}; font-size: 14px; }}
            QPushButton:hover {{ color: #E74C3C; }}
        """)
        btn_del.clicked.connect(lambda _, k=hotkey["key"]: self._on_remove_hotkey(k))
        layout.addWidget(btn_del)

        return row

    def _on_hotkeys_enabled_toggled(self, checked: bool) -> None:
        """全局启用/禁用快捷键。"""
        # 必须先写入 _global_settings，再 emit 信号
        self._main_win._global_settings["hotkeys_enabled"] = checked
        self._set_hotkey_list_enabled(checked)
        self.hotkeys_changed.emit(self._hotkeys)

    def _on_hotkey_toggled(self, key: str, checked: bool) -> None:
        """单个快捷键启用/禁用。"""
        for h in self._hotkeys:
            if h["key"] == key:
                h["enabled"] = checked
                break
        self.hotkeys_changed.emit(self._hotkeys)

    def _on_add_hotkey(self) -> None:
        """添加快捷键。"""
        from widgets.hotkey_capture_dialog import HotkeyCaptureDialog
        existing = [h["key"] for h in self._hotkeys]
        dlg = HotkeyCaptureDialog(existing_keys=existing, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            key = dlg.get_hotkey_string()
            self._hotkeys.append({"key": key, "enabled": True})
            self._rebuild_hotkey_list()
            self.hotkeys_changed.emit(self._hotkeys)

    def _on_remove_hotkey(self, key: str) -> None:
        """删除快捷键。"""
        # 使用[:]原地修改，保持与 _global_settings["hotkeys"] 的共享引用
        self._hotkeys[:] = [h for h in self._hotkeys if h["key"] != key]
        self._rebuild_hotkey_list()
        self.hotkeys_changed.emit(self._hotkeys)

