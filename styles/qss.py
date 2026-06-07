"""
全局 QSS 样式生成函数
"""

from styles.colors import (
    CLR_CONTENT_BG, CLR_CARD_BORDER, CLR_BTN_PRIMARY,
    CLR_TEXT_MAIN, CLR_TEXT_SUB,
)


def get_global_qss() -> str:
    """返回应用于 QMainWindow 的全局 QSS 字符串。"""
    return f"""
        QMainWindow {{ background-color: {CLR_CONTENT_BG}; }}
        QLineEdit {{
            background: white;
            border: 1px solid {CLR_CARD_BORDER};
            border-radius: 6px;
            padding: 4px 8px;
            font-size: 13px;
            color: {CLR_TEXT_MAIN};
        }}
        QLineEdit:focus {{
            border-color: {CLR_BTN_PRIMARY};
        }}
        QPushButton {{
            border-radius: 6px;
            font-size: 12px;
            padding: 5px 12px;
        }}
        QComboBox {{
            background: white;
            border: 1px solid {CLR_CARD_BORDER};
            border-radius: 6px;
            padding: 4px 8px;
            font-size: 12px;
        }}
        QComboBox QAbstractItemView {{
            background: white;
            selection-background-color: {CLR_BTN_PRIMARY};
            selection-color: white;
        }}
        QCheckBox {{
            font-size: 13px;
            color: {CLR_TEXT_MAIN};
            spacing: 8px;
        }}
        QSlider::groove:horizontal {{
            height: 4px;
            background: {CLR_CARD_BORDER};
            border-radius: 2px;
        }}
        QSlider::handle:horizontal {{
            width: 14px;
            height: 14px;
            margin: -5px 0;
            border-radius: 7px;
            background: {CLR_BTN_PRIMARY};
        }}
        QSlider::sub-page:horizontal {{
            background: {CLR_BTN_PRIMARY};
            border-radius: 2px;
        }}
        QScrollBar:vertical {{
            width: 6px;
            background: transparent;
        }}
        QScrollBar::handle:vertical {{
            background: #B0CDE8;
            border-radius: 3px;
            min-height: 20px;
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0;
        }}
        QScrollBar:horizontal {{
            height: 6px;
            background: transparent;
        }}
        QScrollBar::handle:horizontal {{
            background: #B0CDE8;
            border-radius: 3px;
            min-width: 20px;
        }}
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
            width: 0;
        }}
    """
