"""
自定义勾选框样式 (styles/checkbox_style.py)
"""

from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QProxyStyle, QStyle

from styles.colors import CLR_BTN_PRIMARY


class CheckboxStyle(QProxyStyle):
    """蓝色圆角方块 + 白色 ✓ 的勾选框."""

    def drawPrimitive(self, element, option, painter, widget=None):
        if element != QStyle.PrimitiveElement.PE_IndicatorCheckBox:
            return super().drawPrimitive(element, option, painter, widget)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        size = 16
        x = option.rect.x() + (option.rect.width() - size) // 2
        y = option.rect.y() + (option.rect.height() - size) // 2
        rect = QRectF(x, y, size, size).adjusted(1, 1, -1, -1)

        is_on = bool(option.state & QStyle.StateFlag.State_On)
        is_enabled = bool(option.state & QStyle.StateFlag.State_Enabled)

        if is_on:
            fill_color = QColor(CLR_BTN_PRIMARY) if is_enabled else QColor("#B0C8E0")
            painter.setBrush(fill_color)
            painter.setPen(QPen(fill_color, 1.5))
        else:
            fill_color = QColor("white") if is_enabled else QColor("#F0F4F8")
            border_color = QColor("#B0CDE8") if is_enabled else QColor("#CCDDEC")
            painter.setBrush(fill_color)
            painter.setPen(QPen(border_color, 1.5))

        painter.drawRoundedRect(rect, 4, 4)

        if is_on:
            painter.setPen(QPen(QColor("white") if is_enabled else QColor("#7A9AB8"), 2.0,
                                Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                                Qt.PenJoinStyle.RoundJoin))
            path = QPainterPath()
            path.moveTo(x + 3.6, y + 8.8)
            path.lineTo(x + 6.8, y + 11.6)
            path.lineTo(x + 12.4, y + 4.8)
            painter.drawPath(path)

        painter.restore()
