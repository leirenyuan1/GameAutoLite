"""
快捷键捕获对话框 (hotkey_capture_dialog.py)

用户在此对话框中按下键盘组合，捕获为快捷键字符串。
"""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

# keyboard 库使用的键名映射（Qt 键码 → keyboard 键名）
# 必须包含 A-Z 字母键，否则 Windows 中文输入法(IME)激活时无法捕获字母键
_KEY_MAP = {
    Qt.Key.Key_Control: "ctrl",
    Qt.Key.Key_Shift: "shift",
    Qt.Key.Key_Alt: "alt",
    Qt.Key.Key_Meta: "win",
    Qt.Key.Key_F1: "f1",
    Qt.Key.Key_F2: "f2",
    Qt.Key.Key_F3: "f3",
    Qt.Key.Key_F4: "f4",
    Qt.Key.Key_F5: "f5",
    Qt.Key.Key_F6: "f6",
    Qt.Key.Key_F7: "f7",
    Qt.Key.Key_F8: "f8",
    Qt.Key.Key_F9: "f9",
    Qt.Key.Key_F10: "f10",
    Qt.Key.Key_F11: "f11",
    Qt.Key.Key_F12: "f12",
    Qt.Key.Key_Space: "space",
    Qt.Key.Key_Tab: "tab",
    Qt.Key.Key_Backspace: "backspace",
    Qt.Key.Key_Delete: "delete",
    Qt.Key.Key_Escape: "escape",
    # 字母键 A-Z（IME 兼容）
    Qt.Key.Key_A: "a",
    Qt.Key.Key_B: "b",
    Qt.Key.Key_C: "c",
    Qt.Key.Key_D: "d",
    Qt.Key.Key_E: "e",
    Qt.Key.Key_F: "f",
    Qt.Key.Key_G: "g",
    Qt.Key.Key_H: "h",
    Qt.Key.Key_I: "i",
    Qt.Key.Key_J: "j",
    Qt.Key.Key_K: "k",
    Qt.Key.Key_L: "l",
    Qt.Key.Key_M: "m",
    Qt.Key.Key_N: "n",
    Qt.Key.Key_O: "o",
    Qt.Key.Key_P: "p",
    Qt.Key.Key_Q: "q",
    Qt.Key.Key_R: "r",
    Qt.Key.Key_S: "s",
    Qt.Key.Key_T: "t",
    Qt.Key.Key_U: "u",
    Qt.Key.Key_V: "v",
    Qt.Key.Key_W: "w",
    Qt.Key.Key_X: "x",
    Qt.Key.Key_Y: "y",
    Qt.Key.Key_Z: "z",
    # 数字键 0-9
    Qt.Key.Key_0: "0",
    Qt.Key.Key_1: "1",
    Qt.Key.Key_2: "2",
    Qt.Key.Key_3: "3",
    Qt.Key.Key_4: "4",
    Qt.Key.Key_5: "5",
    Qt.Key.Key_6: "6",
    Qt.Key.Key_7: "7",
    Qt.Key.Key_8: "8",
    Qt.Key.Key_9: "9",
}
_MODIFIERS = {"ctrl", "shift", "alt", "win"}


class HotkeyCaptureDialog(QDialog):
    """快捷键捕获对话框。"""

    def __init__(self, existing_keys: list[str], parent=None):
        """
        :param existing_keys: 已存在的快捷键列表（用于重复检测）
        :param parent: 父窗口
        """
        super().__init__(parent)
        self.setWindowTitle("捕获快捷键")
        self.setFixedSize(320, 160)
        self._existing_keys = [k.lower() for k in existing_keys]
        self._captured_keys: set[str] = set()
        self._hotkey_string: str = ""

        layout = QVBoxLayout(self)

        self._label_title = QLabel("请按下快捷键...")
        self._label_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._label_title)

        self._label_display = QLabel("等待输入中...")
        self._label_display.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label_display.setStyleSheet(
            "border: 2px dashed #999; padding: 15px; font-size: 14px;"
        )
        layout.addWidget(self._label_display)

        self._label_error = QLabel("")
        self._label_error.setStyleSheet("color: red; font-size: 12px;")
        self._label_error.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._label_error)

        btn_layout = QHBoxLayout()
        self._btn_confirm = QPushButton("确定")
        self._btn_confirm.setEnabled(False)
        self._btn_confirm.clicked.connect(self._on_confirm)
        btn_layout.addWidget(self._btn_confirm)
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)
        layout.addLayout(btn_layout)

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = self._translate_key(event)
        if not key:
            return
        if key == "escape":
            self.reject()
            return
        self._captured_keys.add(key)
        self._label_error.setText("")
        self._update_display()

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        key = self._translate_key(event)
        if not key:
            return
        # 必须在 discard 之前锁定：松开非修饰键时，用松键前的完整组合作为快捷键
        # 例如按 Ctrl+Shift+P 后松开 P，此时 _captured_keys = {ctrl, shift, p}
        # 应锁定为 ctrl+shift+p，而不是 discard p 后锁定 ctrl+shift
        if not self._is_modifier(key):
            self._lock_hotkey()
        self._captured_keys.discard(key)

    def _translate_key(self, event: QKeyEvent) -> str | None:
        """将 Qt 键码转换为 keyboard 库格式的键名。"""
        key = event.key()
        if key in _KEY_MAP:
            return _KEY_MAP[key]
        # 不使用 event.text() 回退：Windows 中文输入法激活时
        # event.text() 可能返回中文候选字，导致意外捕获
        # 所有需要支持的键都已在 _KEY_MAP 中映射
        # 如需支持符号键（-、=、[、]等），可在 _KEY_MAP 里补充对应的 Qt.Key.Key_* 映射
        return None

    def _is_modifier(self, key: str) -> bool:
        """检查是否为修饰键。"""
        return key.lower() in _MODIFIERS

    def _update_display(self) -> None:
        """更新显示标签，格式化当前按下的键组合。"""
        if self._captured_keys:
            parts = sorted(self._captured_keys, key=lambda k: (k not in _MODIFIERS, k))
            display = "+".join(parts).upper()
            self._label_display.setText(display)
            # 只有当包含非修饰键时才启用确定按钮
            has_non_modifier = any(not self._is_modifier(k) for k in self._captured_keys)
            self._btn_confirm.setEnabled(has_non_modifier)
        else:
            self._label_display.setText("等待输入中...")
            self._btn_confirm.setEnabled(False)

    def _lock_hotkey(self) -> None:
        """锁定当前键组合为最终快捷键。"""
        if self._captured_keys:
            # 使用与 _update_display 一致的排序：修饰键优先，其余按字母序
            parts = sorted(self._captured_keys, key=lambda k: (k not in _MODIFIERS, k))
            # 显式转小写：虽然 _KEY_MAP 值全是小写，但防御性编程避免扩展时引入大小写 bug
            self._hotkey_string = "+".join(p.lower() for p in parts)

    def _on_confirm(self) -> None:
        """点击确定时校验。"""
        # 防御性检查：正常情况下按钮已被禁用，但用户可能按住修饰键不松手
        # 此时 _captured_keys 非空导致按钮启用，但 _hotkey_string 仍为空
        if not self._hotkey_string:
            self._show_error("请输入有效的按键组合")
            return
        if self._is_only_modifiers(self._hotkey_string):
            self._show_error("请输入有效的按键组合")
            return
        if self._hotkey_string.lower() in self._existing_keys:
            self._show_error("该快捷键已存在")
            return
        self.accept()

    def _show_error(self, msg: str) -> None:
        """显示错误提示。"""
        self._label_error.setText(msg)

    def get_hotkey_string(self) -> str:
        """返回捕获的快捷键字符串。"""
        return self._hotkey_string

    def _is_only_modifiers(self, key_str: str) -> bool:
        """检查是否仅包含修饰键。"""
        parts = {p.strip().lower() for p in key_str.split("+")}
        return parts.issubset(_MODIFIERS)
