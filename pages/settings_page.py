"""全局设置页 (pages/settings_page.py)"""
from __future__ import annotations
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIntValidator
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QCheckBox, QSlider, QComboBox, QLineEdit, QFrame, QScrollArea,
    QSizePolicy,
)

from styles.colors import (
    CLR_TEXT_MAIN, CLR_TEXT_SUB, CLR_CARD_BG, CLR_CARD_BORDER,
    CLR_BTN_PRIMARY,
)
from pages.utils import make_settings_card

if TYPE_CHECKING:
    from main_window import MainWindow


class SettingsPage(QWidget):
    def __init__(self, main_win: 'MainWindow', parent=None):
        super().__init__(parent)
        self._main_win = main_win
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

        self.chk_f8 = QCheckBox("启用 F8 快捷键启停")
        self.chk_f8.setChecked(True)
        self.chk_f8.toggled.connect(self._main_win._on_f8_toggled)
        hotkey_layout.addWidget(self.chk_f8)

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

