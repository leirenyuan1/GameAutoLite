"""
程序入口 (main.py)
"""

import ctypes
import logging
import os
import sys

from PyQt6.QtGui import QFont, QIcon
from PyQt6.QtWidgets import QApplication


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
