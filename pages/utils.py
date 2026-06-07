"""
pages 共享辅助函数 (pages/utils.py)
"""

from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QFrame, QVBoxLayout, QLabel, QGraphicsDropShadowEffect

from styles.colors import CLR_CARD_BG, CLR_CARD_BORDER, CLR_TEXT_MAIN


# 模块级计数器，保证所有卡片 objectName 全局唯一
_settings_card_counter = 0


def make_settings_card(title_text: str) -> tuple[QFrame, QVBoxLayout]:
    """创建带阴影的设置分组卡片。供 StopConditionsPage 和 SettingsPage 共用。"""
    global _settings_card_counter
    _settings_card_counter += 1
    card_id = f"settings_card_{_settings_card_counter}"

    card = QFrame()
    card.setObjectName(card_id)
    card.setStyleSheet(f"""
        #{card_id} {{
            background: {CLR_CARD_BG};
            border: 1px solid {CLR_CARD_BORDER};
            border-radius: 10px;
        }}
    """)
    shadow = QGraphicsDropShadowEffect()
    shadow.setBlurRadius(12)
    shadow.setOffset(0, 2)
    shadow.setColor(QColor(33, 150, 243, 30))
    card.setGraphicsEffect(shadow)

    card_layout = QVBoxLayout(card)
    card_layout.setContentsMargins(12, 8, 12, 10)
    card_layout.setSpacing(6)

    header = QLabel(title_text)
    header.setStyleSheet(
        f"font-size: 13px; font-weight: bold; color: {CLR_TEXT_MAIN};"
    )
    card_layout.addWidget(header)

    return card, card_layout
