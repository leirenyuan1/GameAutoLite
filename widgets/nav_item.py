"""
侧边栏导航项 (widgets/nav_item.py)
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel, QFrame

from styles.colors import CLR_SIDEBAR_ACT, CLR_SIDEBAR_SEL, CLR_SIDEBAR_TEXT


class NavItem(QWidget):
    """侧边栏导航菜单项."""

    clicked = pyqtSignal()

    def __init__(self, icon: str, label: str, parent=None):
        super().__init__(parent)
        self._selected = False
        self.setFixedHeight(44)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 0, 8, 0)
        layout.setSpacing(8)

        self.icon_label = QLabel(icon)
        self.icon_label.setFixedWidth(20)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.text_label = QLabel(label)

        # 左侧选中指示条
        self.indicator = QFrame()
        self.indicator.setFixedWidth(3)
        self.indicator.hide()

        layout.addWidget(self.indicator)
        layout.addWidget(self.icon_label)
        layout.addWidget(self.text_label, 1)
        self._update_style()

    def _update_style(self) -> None:
        if self._selected:
            self.indicator.show()
            self.indicator.setStyleSheet(
                f"background: {CLR_SIDEBAR_ACT}; border-radius: 1px;"
            )
            self.text_label.setStyleSheet(
                f"color: {CLR_SIDEBAR_ACT}; font-size: 13px; font-weight: bold;"
            )
            self.icon_label.setStyleSheet(
                f"color: {CLR_SIDEBAR_ACT}; font-size: 14px;"
            )
            self.setStyleSheet(f"background: {CLR_SIDEBAR_SEL}; border-radius: 8px;")
        else:
            self.indicator.hide()
            self.text_label.setStyleSheet(
                f"color: {CLR_SIDEBAR_TEXT}; font-size: 13px;"
            )
            self.icon_label.setStyleSheet(
                f"color: {CLR_SIDEBAR_TEXT}; font-size: 14px;"
            )
            self.setStyleSheet("background: transparent;")

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self._update_style()

    def enterEvent(self, event) -> None:
        if not self._selected:
            self.setStyleSheet("background: rgba(33,150,243,0.08); border-radius: 8px;")
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._update_style()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

