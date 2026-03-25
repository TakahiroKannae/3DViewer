"""Right-side detail panel showing selected file metadata."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QScrollArea, QFrame, QSizePolicy,
)

from ..models import FileItem
from ..metadata import get_metadata
from ..sequence import SequenceGroup


class DetailPanel(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(200)
        self.setMaximumWidth(320)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        title = QLabel("Details")
        title.setStyleSheet("font-weight: bold; font-size: 13px; color: #ccc;")
        layout.addWidget(title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        layout.addWidget(scroll)

        self._container = QWidget()
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(4)
        self._layout.addStretch()
        scroll.setWidget(self._container)

        self._labels: list[QLabel] = []

    def show_item(self, item: FileItem) -> None:
        meta = get_metadata(item.path_or_group)
        self._update(meta)

    def clear(self) -> None:
        self._update({})

    def _update(self, meta: dict) -> None:
        # Remove old labels
        for lbl in self._labels:
            self._layout.removeWidget(lbl)
            lbl.deleteLater()
        self._labels.clear()

        if not meta:
            return

        # Ordered display keys
        display_order = [
            ("name", "Name"), ("format", "Format"), ("category", "Category"),
            ("size", "Size"), ("modified", "Modified"),
            ("width", "Width"), ("height", "Height"), ("mode", "Color Mode"),
            ("channels", "Channels"),
            ("vertices", "Vertices"), ("faces", "Faces"),
            ("point_count", "Points"),
            ("duration", "Duration"), ("codec", "Codec"), ("fps", "FPS"),
            ("frame_count", "Frames"), ("first_frame", "First Frame"),
            ("last_frame", "Last Frame"),
            ("crs", "CRS"),
            ("path", "Path"),
        ]

        for key, display in display_order:
            val = meta.get(key)
            if val is None or val == "" or val == "None":
                continue
            row = self._make_row(display, str(val))
            self._layout.insertWidget(self._layout.count() - 1, row)
            self._labels.append(row)

        # Remaining unknown keys
        shown = {k for k, _ in display_order}
        for key, val in meta.items():
            if key in shown or val is None:
                continue
            row = self._make_row(key.replace("_", " ").title(), str(val))
            self._layout.insertWidget(self._layout.count() - 1, row)
            self._labels.append(row)

    def _make_row(self, label: str, value: str) -> QLabel:
        text = f"<b style='color:#aaa'>{label}</b><br><span style='color:#ddd'>{value}</span>"
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lbl.setStyleSheet("padding: 2px 0;")
        return lbl
