"""Thumbnail grid view widget."""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QItemSelection
from PySide6.QtGui import QAction, QPixmap
from PySide6.QtWidgets import (
    QListView, QAbstractItemView, QMenu, QApplication,
    QMessageBox,
)

from ..models import ThumbnailModel, Role, FileItem
from .grid_delegate import ThumbnailDelegate
from ..sequence import SequenceGroup


class GridView(QListView):
    """Icon-mode list view with custom delegate for thumbnails."""

    item_selected = Signal(FileItem)
    item_activated = Signal(object)  # Path or SequenceGroup

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._model = ThumbnailModel()
        self.setModel(self._model)
        self._delegate = ThumbnailDelegate()
        self.setItemDelegate(self._delegate)

        self.setViewMode(QListView.ViewMode.IconMode)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setSpacing(4)
        self.setUniformItemSizes(False)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._context_menu)
        self.doubleClicked.connect(self._on_double_click)
        self.selectionModel().selectionChanged.connect(self._on_selection)

        # Dark background
        self.setStyleSheet("QListView { background: #282830; border: none; }")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_items(self, items: list[FileItem]) -> None:
        self._model.set_items(items)

    def set_thumb_size(self, size: int) -> None:
        self._model.update_thumb_size(size)
        # Force layout refresh
        self.scheduleDelayedItemsLayout()

    def apply_pixmap(self, path_or_group, png_bytes: bytes) -> None:
        px = QPixmap()
        px.loadFromData(png_bytes)
        self._model.set_pixmap(path_or_group, px)

    def thumbnail_model(self) -> ThumbnailModel:
        return self._model

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_selection(self, selected: QItemSelection, _deselected) -> None:
        idxs = self.selectionModel().selectedIndexes()
        if idxs:
            item: FileItem = idxs[0].data(Role.ITEM)
            if item:
                self.item_selected.emit(item)

    def _on_double_click(self, index) -> None:
        item: FileItem = index.data(Role.ITEM)
        if not item:
            return
        from ..formats import CATEGORY_3D, CATEGORY_POINTCLOUD
        if item.is_sequence:
            self.item_activated.emit(item.path_or_group)
        elif item.category == CATEGORY_3D:
            from .mesh_viewer import open_mesh_viewer
            open_mesh_viewer(item.real_path(), self, is_pointcloud=False)
        elif item.category == CATEGORY_POINTCLOUD:
            from .mesh_viewer import open_mesh_viewer
            open_mesh_viewer(item.real_path(), self, is_pointcloud=True)
        else:
            self.item_activated.emit(item.path_or_group)

    def _context_menu(self, pos) -> None:
        index = self.indexAt(pos)
        if not index.isValid():
            return
        item: FileItem = index.data(Role.ITEM)
        if not item:
            return

        menu = QMenu(self)

        from ..formats import CATEGORY_3D, CATEGORY_POINTCLOUD
        if not item.is_sequence and item.category in (CATEGORY_3D, CATEGORY_POINTCLOUD):
            is_pc = item.category == CATEGORY_POINTCLOUD
            act_3d = QAction("Open in Point Cloud Viewer" if is_pc
                             else "Open in 3D Viewer", self)
            act_3d.triggered.connect(lambda checked=False, i=item:
                                     self._open_3d_viewer(i))
            menu.addAction(act_3d)
            menu.addSeparator()

        act_open = QAction("Open in File Manager", self)
        act_open.triggered.connect(lambda: self._open_in_manager(item))
        menu.addAction(act_open)

        act_copy = QAction("Copy Path", self)
        act_copy.triggered.connect(lambda: self._copy_path(item))
        menu.addAction(act_copy)

        menu.addSeparator()
        act_meta = QAction("Show Metadata", self)
        act_meta.triggered.connect(lambda: self._show_meta(item))
        menu.addAction(act_meta)

        menu.exec(self.viewport().mapToGlobal(pos))

    # ------------------------------------------------------------------
    # Context menu handlers
    # ------------------------------------------------------------------

    def _open_3d_viewer(self, item: FileItem) -> None:
        from .mesh_viewer import open_mesh_viewer
        from ..formats import CATEGORY_POINTCLOUD
        open_mesh_viewer(item.real_path(), self,
                         is_pointcloud=(item.category == CATEGORY_POINTCLOUD))

    def _open_in_manager(self, item: FileItem) -> None:
        path = item.real_path()
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", "-R", str(path)])
            elif sys.platform == "win32":
                subprocess.Popen(["explorer", "/select,", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path.parent)])
        except Exception as e:
            QMessageBox.warning(self, "Error", str(e))

    def _copy_path(self, item: FileItem) -> None:
        if isinstance(item.path_or_group, SequenceGroup):
            text = str(item.path_or_group.directory / item.path_or_group.pattern)
        else:
            text = str(item.path_or_group)
        QApplication.clipboard().setText(text)

    def _show_meta(self, item: FileItem) -> None:
        from ..metadata import get_metadata
        meta = get_metadata(item.path_or_group)
        lines = [f"{k}: {v}" for k, v in meta.items() if v is not None]
        QMessageBox.information(self, "Metadata — " + item.display_name,
                                "\n".join(lines))
