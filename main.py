"""
程序入口 (main.py)
"""

import ctypes
import logging
import os
import sys

from PyQt6.QtGui import QFont, QIcon
from PyQt6.QtWidgets import QApplication

logger = logging.getLogger(__name__)

# 单实例互斥体句柄（模块级保持引用防 GC, 关闭句柄即失去锁）
_instance_mutex_handle = None


def _acquire_single_instance():
    """
    创建命名互斥体实现单实例限制.
    互斥体已存在 -> 返回 False（应拒绝启动）; 创建失败（极端情况）-> 返回 True 放行.
    注意: 必须在提权块之后调用（先提权, 提权重启的新进程再上加锁, 防止自撞锁）.
    """
    global _instance_mutex_handle
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    handle = kernel32.CreateMutexW(
        None, False, "Local\\GameAutoLite_SingleInstance")
    err = kernel32.GetLastError()  # 必须在 CreateMutexW 后立即读取
    if not handle:
        logger.warning("创建单实例互斥体失败, 放行本次启动")
        return True
    _instance_mutex_handle = handle
    if err == 183:  # ERROR_ALREADY_EXISTS
        logger.warning("检测到已运行实例, 拒绝本次启动")
        return False
    return True


def main():
    # 日志配置必须在所有模块 import 之前设置，否则 basicConfig 可能被忽略
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    # 尝试以管理员权限运行（keyboard 库全局热键需要）
    if "--admin" not in sys.argv and sys.platform == "win32":
        try:
            script = '"' + sys.argv[0] + '"'
            params = script + " --admin"
            h = ctypes.windll.shell32.ShellExecuteW(
                None, "runas", sys.executable, params, None, 1
            )
            if h > 32:
                sys.exit(0)
        except Exception:
            pass

    # ---- 单实例锁（必须放在提权块之后, 防提权重启自撞锁）----
    if sys.platform == "win32" and _acquire_single_instance() is False:
        ctypes.windll.user32.MessageBoxW(
            None,
            "GameAutoLite 已在运行中\n请勿重复启动（如需使用，请切换到已打开的窗口）",
            "GameAutoLite", 0x30  # MB_ICONWARNING
        )
        sys.exit(0)

    # 强制 Qt 使用 1:1 缩放因子，确保 overlay_selector / mss / win32api
    # 三者使用同一物理像素坐标系，消除 125%/150%/200% 缩放下的坐标漂移。
    os.environ["QT_SCALE_FACTOR"] = "1"

    app = QApplication(sys.argv)
    app.setFont(QFont("Microsoft YaHei", 10))

    # CheckboxStyle 和 MainWindow 在此处 import，确保 QApplication 已存在
    from styles.checkbox_style import CheckboxStyle
    from main_window import MainWindow

    app.setStyle(CheckboxStyle())

    # 设置窗口图标（支持 exe 和脚本两种模式）
    if getattr(sys, "frozen", False):
        _app_dir = os.path.dirname(os.path.abspath(sys.executable))
        _icon_dir = getattr(sys, "_MEIPASS", _app_dir)
    else:
        _app_dir = os.path.dirname(os.path.abspath(__file__))
        _icon_dir = _app_dir

    _icon_path = os.path.join(_icon_dir, "icon.ico")
    if os.path.exists(_icon_path):
        app.setWindowIcon(QIcon(_icon_path))

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
