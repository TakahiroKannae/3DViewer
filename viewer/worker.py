"""Background thumbnail worker using QThreadPool."""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from .cache import ThumbnailCache
from .thumbnails import generate_thumbnail
from .sequence import SequenceGroup

log = logging.getLogger(__name__)


class _Signals(QObject):
    done = Signal(object, bytes)   # (path_or_group, png_bytes)
    error = Signal(object, str)    # (path_or_group, error_msg)


class ThumbnailTask(QRunnable):
    """Single thumbnail generation task."""

    def __init__(
        self,
        item: Path | SequenceGroup,
        size: int,
        cache: ThumbnailCache,
    ) -> None:
        super().__init__()
        self.item = item
        self.size = size
        self.cache = cache
        self.signals = _Signals()
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        item = self.item
        size = self.size

        if isinstance(item, SequenceGroup):
            path = item.first_frame
            cache_key_path = str(item.first_frame)
        else:
            path = item
            cache_key_path = str(path)

        try:
            st = path.stat()
            mtime = st.st_mtime
            fsize = st.st_size

            # Cache lookup
            cached = self.cache.get(cache_key_path, mtime, fsize, size, size)
            if cached:
                self.signals.done.emit(item, cached)
                return

            png = generate_thumbnail(path, size)
            self.cache.put(cache_key_path, mtime, fsize, size, size, png)
            self.signals.done.emit(item, png)

        except Exception as exc:
            log.warning("Thumbnail task failed for %s: %s", path, exc)
            self.signals.error.emit(item, str(exc))
