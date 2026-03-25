"""Left-sidebar folder tree view."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal, QDir, Qt
from PySide6.QtWidgets import QTreeView, QFileSystemModel, QAbstractItemView


class FolderTree(QTreeView):
    """File-system tree; emits folder_selected(Path) on click."""

    folder_selected = Signal(Path)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._fs_model = QFileSystemModel()
        self._fs_model.setRootPath("")
        self._fs_model.setFilter(QDir.Filter.AllDirs | QDir.Filter.NoDotAndDotDot)
        self.setModel(self._fs_model)

        # Hide all columns except Name
        for col in range(1, self._fs_model.columnCount()):
            self.hideColumn(col)

        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setHeaderHidden(True)
        self.setAnimated(False)
        self.setStyleSheet(
            "QTreeView { background: #1e1e28; color: #ccc; border: none; }"
            "QTreeView::item:selected { background: #3a5080; }"
        )

        self.clicked.connect(self._on_clicked)

        # Expand to home by default
        home = Path.home()
        self.expand_to(home)

    def expand_to(self, path: Path) -> None:
        idx = self._fs_model.index(str(path))
        if idx.isValid():
            self.setCurrentIndex(idx)
            self.expand(idx)
            self.scrollTo(idx)

    def _on_clicked(self, index) -> None:
        path = Path(self._fs_model.filePath(index))
        self.folder_selected.emit(path)
