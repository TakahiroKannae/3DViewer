"""Main application window."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from PySide6.QtCore import Qt, QThreadPool, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QSplitter, QVBoxLayout, QHBoxLayout,
    QSlider, QLabel, QStatusBar, QToolBar, QApplication, QProgressBar,
)

from ..cache import ThumbnailCache
from ..models import FileItem, ThumbnailModel
from ..sequence import group_sequences, SequenceGroup
from ..formats import get_category
from ..worker import ThumbnailTask
from .folder_tree import FolderTree
from .grid_view import GridView
from .detail_panel import DetailPanel
from .filter_panel import FilterPanel

log = logging.getLogger(__name__)

_DB_PATH = Path.home() / ".cache" / "qooop_3dviewer" / "thumbnails.db"
_DEFAULT_THUMB_SIZE = 128
_MAX_THREADS = max(2, os.cpu_count() or 4)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("qooop 3D File Viewer")
        self.resize(1400, 900)

        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._cache = ThumbnailCache(_DB_PATH)
        self._pool = QThreadPool.globalInstance()
        self._pool.setMaxThreadCount(_MAX_THREADS)

        self._current_folder: Path | None = None
        self._all_items: list[FileItem] = []
        self._thumb_size = _DEFAULT_THUMB_SIZE

        self._build_ui()
        self._connect_signals()

        # Debounce timer for filter changes
        self._filter_timer = QTimer()
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(150)
        self._filter_timer.timeout.connect(self._apply_filter)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # Toolbar
        toolbar = QToolBar("Main")
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        toolbar.setStyleSheet("QToolBar { background: #1a1a22; border: none; padding: 2px; }")
        self.addToolBar(toolbar)

        self._thumb_slider = QSlider(Qt.Orientation.Horizontal)
        self._thumb_slider.setRange(64, 512)
        self._thumb_slider.setValue(_DEFAULT_THUMB_SIZE)
        self._thumb_slider.setFixedWidth(140)
        self._thumb_slider.setToolTip("Thumbnail size")

        self._size_label = QLabel(f"{_DEFAULT_THUMB_SIZE}px")
        self._size_label.setStyleSheet("color: #aaa; padding: 0 4px;")

        toolbar.addWidget(QLabel("  Size: "))
        toolbar.addWidget(self._thumb_slider)
        toolbar.addWidget(self._size_label)
        toolbar.addSeparator()

        act_prune = QAction("Prune Cache", self)
        act_prune.triggered.connect(self._prune_cache)
        toolbar.addAction(act_prune)

        act_refresh = QAction("Refresh", self)
        act_refresh.setShortcut(QKeySequence("F5"))
        act_refresh.triggered.connect(self._refresh_folder)
        toolbar.addAction(act_refresh)

        # Main splitter: tree | grid | detail
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setStyleSheet("QSplitter::handle { background: #333; width: 2px; }")
        root_layout.addWidget(splitter)

        # Left panel: tree + filter
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)

        self._folder_tree = FolderTree()
        self._filter_panel = FilterPanel()

        left_layout.addWidget(self._folder_tree, 3)
        left_layout.addWidget(self._filter_panel, 2)
        splitter.addWidget(left_panel)

        # Centre: grid view
        self._grid = GridView()
        splitter.addWidget(self._grid)

        # Right: detail panel
        self._detail = DetailPanel()
        splitter.addWidget(self._detail)

        splitter.setSizes([220, 900, 260])

        # Status bar
        status = QStatusBar()
        self.setStatusBar(status)
        self._status_label = QLabel("Ready")
        self._progress = QProgressBar()
        self._progress.setMaximumWidth(200)
        self._progress.setVisible(False)
        status.addWidget(self._status_label)
        status.addPermanentWidget(self._progress)

        # Apply dark theme
        self.setStyleSheet(_DARK_STYLESHEET)

    def _connect_signals(self) -> None:
        self._folder_tree.folder_selected.connect(self._load_folder)
        self._grid.item_selected.connect(self._on_item_selected)
        self._grid.item_activated.connect(self._on_item_activated)
        self._thumb_slider.valueChanged.connect(self._on_size_changed)
        self._filter_panel.filter_changed.connect(self._on_filter_changed)

    # ------------------------------------------------------------------
    # Folder loading
    # ------------------------------------------------------------------

    def _load_folder(self, folder: Path) -> None:
        self._current_folder = folder
        self._status_label.setText(f"Loading {folder} …")

        # Collect all files
        try:
            raw_files = sorted(
                p for p in folder.iterdir()
                if p.is_file() and not p.name.startswith(".")
            )
        except PermissionError as e:
            self._status_label.setText(f"Error: {e}")
            return

        # Group sequences
        grouped = group_sequences(raw_files)

        # Wrap in FileItem
        self._all_items = [
            FileItem(item, self._thumb_size)
            for item in grouped
        ]

        self._apply_filter()
        self._status_label.setText(
            f"{folder.name}  —  {len(self._all_items)} items"
        )

    def _refresh_folder(self) -> None:
        if self._current_folder:
            self._load_folder(self._current_folder)

    # ------------------------------------------------------------------
    # Filtering
    # ------------------------------------------------------------------

    def _on_filter_changed(self, active_cats, search_text) -> None:
        self._filter_timer.start()

    def _apply_filter(self) -> None:
        active = self._filter_panel.active_categories()
        text = self._filter_panel.search_text().lower()

        visible = [
            item for item in self._all_items
            if item.category in active
            and (not text or text in item.display_name.lower())
        ]

        self._grid.set_items(visible)
        self._status_label.setText(
            f"{self._current_folder.name if self._current_folder else ''}  "
            f"— {len(visible)} / {len(self._all_items)} items"
        )
        # Kick off thumbnail generation for visible items
        self._queue_thumbnails(visible)

    # ------------------------------------------------------------------
    # Thumbnail generation queue
    # ------------------------------------------------------------------

    def _queue_thumbnails(self, items: list[FileItem]) -> None:
        pending = 0
        for item in items:
            # Skip if already loaded
            if item.pixmap is not None:
                continue
            task = ThumbnailTask(item.path_or_group, self._thumb_size, self._cache)
            task.signals.done.connect(self._on_thumbnail_done)
            task.signals.error.connect(self._on_thumbnail_error)
            self._pool.start(task)
            pending += 1

        if pending:
            self._progress.setVisible(True)
            self._progress.setRange(0, 0)
        else:
            self._progress.setVisible(False)

    def _on_thumbnail_done(self, path_or_group, png_bytes: bytes) -> None:
        self._grid.apply_pixmap(path_or_group, png_bytes)
        # Hide spinner when queue drains
        if self._pool.activeThreadCount() == 0:
            self._progress.setVisible(False)

    def _on_thumbnail_error(self, path_or_group, error: str) -> None:
        log.warning("Thumbnail error for %s: %s", path_or_group, error)

    # ------------------------------------------------------------------
    # Selection / activation
    # ------------------------------------------------------------------

    def _on_item_selected(self, item: FileItem) -> None:
        self._detail.show_item(item)

    def _on_item_activated(self, path_or_group) -> None:
        if isinstance(path_or_group, SequenceGroup):
            # Expand: reload folder showing individual files from this sequence
            # For now show a message; full expand is a future enhancement
            from PySide6.QtWidgets import QMessageBox
            names = "\n".join(str(p) for p in path_or_group.members[:20])
            if path_or_group.frame_count > 20:
                names += f"\n… and {path_or_group.frame_count - 20} more"
            QMessageBox.information(self, "Sequence Members", names)

    # ------------------------------------------------------------------
    # Thumbnail size
    # ------------------------------------------------------------------

    def _on_size_changed(self, value: int) -> None:
        self._thumb_size = value
        self._size_label.setText(f"{value}px")
        self._grid.set_thumb_size(value)
        # Regenerate thumbnails at new size
        if self._current_folder:
            self._queue_thumbnails(self._grid.thumbnail_model().all_items())

    # ------------------------------------------------------------------
    # Cache maintenance
    # ------------------------------------------------------------------

    def _prune_cache(self) -> None:
        n = self._cache.prune_missing()
        stats = self._cache.stats()
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(
            self, "Cache",
            f"Removed {n} stale entries.\n"
            f"Thumbnails: {stats['thumbnail_count']} "
            f"({stats['thumbnail_bytes'] // 1024} KB)\n"
            f"DB: {stats['db_path']}"
        )

    def closeEvent(self, event) -> None:
        self._pool.waitForDone(2000)
        self._cache.close()
        super().closeEvent(event)


# ---------------------------------------------------------------------------
# Dark stylesheet
# ---------------------------------------------------------------------------

_DARK_STYLESHEET = """
QMainWindow, QWidget {
    background: #1e1e28;
    color: #cccccc;
    font-family: "Segoe UI", "SF Pro Text", "Helvetica Neue", Arial, sans-serif;
    font-size: 11px;
}
QSplitter::handle { background: #2a2a36; }
QGroupBox {
    border: 1px solid #333;
    border-radius: 4px;
    margin-top: 8px;
    padding-top: 8px;
    color: #aaa;
}
QGroupBox::title { subcontrol-origin: margin; left: 8px; color: #999; }
QCheckBox { color: #bbb; }
QCheckBox::indicator { width: 14px; height: 14px; }
QLineEdit {
    background: #2a2a36;
    border: 1px solid #444;
    border-radius: 3px;
    padding: 3px 6px;
    color: #ddd;
}
QSlider::groove:horizontal { height: 4px; background: #444; border-radius: 2px; }
QSlider::handle:horizontal {
    background: #5588cc;
    border-radius: 6px;
    width: 12px;
    margin: -4px 0;
}
QScrollBar:vertical { background: #1e1e28; width: 10px; }
QScrollBar::handle:vertical { background: #3a3a4a; border-radius: 4px; min-height: 20px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QToolBar QLabel { color: #aaa; }
QStatusBar { background: #151520; color: #888; }
QProgressBar { background: #2a2a36; border-radius: 3px; }
QProgressBar::chunk { background: #4477cc; }
QToolButton { color: #bbb; background: transparent; border: none; padding: 4px 8px; }
QToolButton:hover { background: #2e2e40; border-radius: 3px; }
QMenu { background: #252535; border: 1px solid #444; color: #ccc; }
QMenu::item:selected { background: #3a5080; }
QMessageBox { background: #1e1e28; }
"""
