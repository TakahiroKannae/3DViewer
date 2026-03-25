"""Left-bottom filter panel: category checkboxes + search bar."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox,
    QLineEdit, QGroupBox,
)

from ..formats import (
    CATEGORY_3D, CATEGORY_POINTCLOUD, CATEGORY_IMAGE,
    CATEGORY_VIDEO, CATEGORY_DOCUMENT, CATEGORY_GAMEENGINE, CATEGORY_UNKNOWN,
)

_CATEGORIES = [
    (CATEGORY_IMAGE,       "Images"),
    (CATEGORY_3D,          "3D"),
    (CATEGORY_POINTCLOUD,  "Point Clouds"),
    (CATEGORY_VIDEO,       "Video"),
    (CATEGORY_DOCUMENT,    "Documents"),
    (CATEGORY_GAMEENGINE,  "Game Engine"),
    (CATEGORY_UNKNOWN,     "Other"),
]


class FilterPanel(QWidget):
    """Emits filter_changed(active_categories, search_text) when state changes."""

    filter_changed = Signal(set, str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # Search
        search_box = QGroupBox("Search")
        sb_layout = QVBoxLayout(search_box)
        self._search = QLineEdit()
        self._search.setPlaceholderText("Filter by name…")
        self._search.textChanged.connect(self._on_change)
        sb_layout.addWidget(self._search)
        layout.addWidget(search_box)

        # Category checkboxes
        cat_box = QGroupBox("Format Filter")
        cat_layout = QVBoxLayout(cat_box)
        self._checks: dict[str, QCheckBox] = {}
        for cat, label in _CATEGORIES:
            cb = QCheckBox(label)
            cb.setChecked(True)
            cb.stateChanged.connect(self._on_change)
            self._checks[cat] = cb
            cat_layout.addWidget(cb)
        layout.addWidget(cat_box)
        layout.addStretch()

    def _on_change(self) -> None:
        active = {cat for cat, cb in self._checks.items() if cb.isChecked()}
        self.filter_changed.emit(active, self._search.text())

    def active_categories(self) -> set[str]:
        return {cat for cat, cb in self._checks.items() if cb.isChecked()}

    def search_text(self) -> str:
        return self._search.text()
