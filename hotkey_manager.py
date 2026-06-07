"""
热键管理器 (hotkey_manager.py)
"""

import logging

import keyboard
from PyQt6.QtCore import QMetaObject, Qt, QObject

logger = logging.getLogger(__name__)


class HotkeyManager(QObject):
    """管理 F8 全局热键的注册与注销。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._target: QObject | None = None
        self._slot_name: str = ""
        self._registered = False

    def register(self, target: QObject, slot_name: str) -> bool:
        """
        注册 F8 热键。
        :param target:    热键触发后 invokeMethod 的目标对象（MainWindow）
        :param slot_name: 目标对象上的槽函数名（字符串），必须以 @pyqtSlot() 装饰
        :return: 注册成功返回 True，失败返回 False
        """
        self._target = target
        self._slot_name = slot_name
        try:
            keyboard.add_hotkey("f8", self._on_f8)
            self._registered = True
            return True
        except Exception as e:
            logger.warning(f"F8 热键注册失败: {e}")
            self._registered = False
            return False

    def unregister(self) -> None:
        """注销 F8 热键。"""
        try:
            keyboard.remove_hotkey("f8")
        except Exception:
            pass
        self._registered = False

    @property
    def is_registered(self) -> bool:
        return self._registered

    def _on_f8(self) -> None:
        """热键回调在 keyboard 的钩子线程中执行，必须转发到主线程。"""
        if self._target and self._slot_name:
            QMetaObject.invokeMethod(
                self._target,
                self._slot_name,
                Qt.ConnectionType.QueuedConnection,
            )
