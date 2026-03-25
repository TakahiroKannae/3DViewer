"""Qt data models and shared data structures."""

from __future__ import annotations

from enum import IntEnum
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QAbstractListModel, QModelIndex, QSize
from PySide6.QtGui import QPixmap

from .formats import get_format_info, CATEGORY_IMAGE, CATEGORY_VIDEO, CATEGORY_3D
from .formats import CATEGORY_POINTCLOUD, CATEGORY_DOCUMENT, CATEGORY_GAMEENGINE
from .sequence import SequenceGroup


class Role(IntEnum):
    ITEM   = Qt.ItemDataRole.UserRole + 1
    PIXMAP = Qt.ItemDataRole.UserRole + 2
    PATH   = Qt.ItemDataRole.UserRole + 3


class FileItem:
    """Lightweight descriptor for one file or sequence group."""

    __slots__ = (
        "path_or_group", "display_name", "format_label", "category",
        "is_sequence", "frame_count", "thumb_size", "_pixmap",
    )

    def __init__(self, path_or_group: Path | SequenceGroup, thumb_size: int = 128) -> None:
        self.path_or_group = path_or_group
        self.thumb_size = thumb_size
        self._pixmap: QPixmap | None = None

        if isinstance(path_or_group, SequenceGroup):
            self.is_sequence = True
            self.frame_count = path_or_group.frame_count
            self.display_name = path_or_group.pattern
            cat, lbl = get_format_info(path_or_group.first_frame)
            self.category = cat
            self.format_label = lbl
        else:
            self.is_sequence = False
            self.frame_count = 1
            self.display_name = path_or_group.name
            cat, lbl = get_format_info(path_or_group)
            self.category = cat
            self.format_label = lbl

    @property
    def pixmap(self) -> QPixmap | None:
        return self._pixmap

    @pixmap.setter
    def pixmap(self, px: QPixmap | None) -> None:
        self._pixmap = px

    def real_path(self) -> Path:
        if isinstance(self.path_or_group, SequenceGroup):
            return self.path_or_group.first_frame
        return self.path_or_group


class ThumbnailModel(QAbstractListModel):
    """Model for the thumbnail grid view."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._items: list[FileItem] = []

    def set_items(self, items: list[FileItem]) -> None:
        self.beginResetModel()
        self._items = items
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._items)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or index.row() >= len(self._items):
            return None
        item = self._items[index.row()]
        if role == Role.ITEM:
            return item
        if role == Role.PIXMAP:
            return item.pixmap
        if role == Role.PATH:
            return item.path_or_group
        if role == Qt.ItemDataRole.DisplayRole:
            return item.display_name
        if role == Qt.ItemDataRole.SizeHintRole:
            sz = item.thumb_size + 44
            return QSize(sz, sz)
        return None

    def set_pixmap(self, path_or_group, pixmap: QPixmap) -> None:
        """Update pixmap for a given item and emit dataChanged."""
        for i, item in enumerate(self._items):
            if item.path_or_group == path_or_group:
                item.pixmap = pixmap
                idx = self.index(i)
                self.dataChanged.emit(idx, idx, [Role.PIXMAP])
                return

    def update_thumb_size(self, size: int) -> None:
        for item in self._items:
            item.thumb_size = size
        if self._items:
            self.dataChanged.emit(
                self.index(0),
                self.index(len(self._items) - 1),
                [Qt.ItemDataRole.SizeHintRole, Role.ITEM]
            )

    def all_items(self) -> list[FileItem]:
        return list(self._items)
