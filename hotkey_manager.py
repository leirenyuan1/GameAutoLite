"""
热键管理器 (hotkey_manager.py)

支持多个全局热键的注册与注销。
"""

import logging

import keyboard
from PyQt6.QtCore import QMetaObject, Qt, QObject

logger = logging.getLogger(__name__)


class HotkeyManager(QObject):
    """管理多个全局热键的注册与注销。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._target: QObject | None = None
        self._slot_name: str = ""
        self._registered_keys: dict[str, int] = {}  # key -> hotkey_id 映射

    def register_all(self, target: QObject, slot_name: str, hotkeys: list[dict]) -> list[str]:
        """
        批量注册热键。
        :param target:    invokeMethod 目标对象
        :param slot_name: 槽函数名
        :param hotkeys:   [{"key": "f8", "enabled": True}, ...]
        :return: 成功注册的 key 列表
        """
        self._target = target
        self._slot_name = slot_name
        registered = []
        for item in hotkeys:
            if not item.get("enabled", True):
                continue
            key = item["key"].lower().strip()
            if key in self._registered_keys:
                continue  # 已注册，跳过
            try:
                hotkey_id = keyboard.add_hotkey(key, lambda k=key: self._on_hotkey_pressed(k))
                self._registered_keys[key] = hotkey_id
                registered.append(key)
            except Exception as e:
                logger.warning(f"热键注册失败 [{key}]: {e}")
        return registered

    def unregister_all(self) -> None:
        """注销所有已注册的热键。"""
        for key, hotkey_id in list(self._registered_keys.items()):
            try:
                keyboard.remove_hotkey(hotkey_id)
            except Exception:
                pass
        self._registered_keys.clear()

    def add_hotkey(self, key: str) -> bool:
        """动态添加单个热键，返回是否成功。
        预留 API：当前 _on_hotkeys_changed 使用 unregister_all + register_all 全量替换，
        不调用此方法。保留供未来按需增删场景使用。
        """
        key = key.lower().strip()
        if key in self._registered_keys:
            return True  # 已存在
        try:
            hotkey_id = keyboard.add_hotkey(key, lambda k=key: self._on_hotkey_pressed(k))
            self._registered_keys[key] = hotkey_id
            return True
        except Exception as e:
            logger.warning(f"热键注册失败 [{key}]: {e}")
            return False

    def remove_hotkey(self, key: str) -> bool:
        """动态移除单个热键，返回是否成功。
        预留 API：当前 _on_hotkeys_changed 使用 unregister_all + register_all 全量替换，
        不调用此方法。保留供未来按需增删场景使用。
        """
        key = key.lower().strip()
        hotkey_id = self._registered_keys.pop(key, None)
        if hotkey_id is None:
            return False
        try:
            keyboard.remove_hotkey(hotkey_id)
            return True
        except Exception:
            return False

    def is_registered(self, key: str) -> bool:
        """检查指定热键是否已注册。"""
        return key.lower().strip() in self._registered_keys

    @property
    def registered_keys(self) -> list[str]:
        """返回所有已注册的热键列表。"""
        return list(self._registered_keys.keys())

    def _on_hotkey_pressed(self, key: str) -> None:
        """热键回调在 keyboard 的钩子线程中执行，必须转发到主线程。"""
        if self._target and self._slot_name:
            QMetaObject.invokeMethod(
                self._target,
                self._slot_name,
                Qt.ConnectionType.QueuedConnection,
            )
