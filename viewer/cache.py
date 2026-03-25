"""SQLite-backed thumbnail cache manager."""

from __future__ import annotations

import sqlite3
import threading
import time
import logging
from pathlib import Path

log = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS thumbnails (
    path        TEXT NOT NULL,
    mtime       REAL NOT NULL,
    fsize       INTEGER NOT NULL,
    width       INTEGER NOT NULL,
    height      INTEGER NOT NULL,
    png_data    BLOB NOT NULL,
    created_at  REAL NOT NULL,
    PRIMARY KEY (path, width, height)
);
CREATE INDEX IF NOT EXISTS idx_thumbnails_path ON thumbnails(path);

CREATE TABLE IF NOT EXISTS metadata (
    path        TEXT PRIMARY KEY,
    mtime       REAL NOT NULL,
    fsize       INTEGER NOT NULL,
    info_json   TEXT NOT NULL,
    created_at  REAL NOT NULL
);
"""


class ThumbnailCache:
    """Thread-safe SQLite thumbnail cache.

    Each unique (path, mtime, fsize, width, height) combination is cached
    as a PNG blob.  Stale entries (mtime or fsize changed) are evicted on
    lookup.
    """

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        self._local = threading.local()
        self._lock = threading.Lock()
        self._init_db()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _conn(self) -> sqlite3.Connection:
        """Return a per-thread connection."""
        if not hasattr(self._local, "conn"):
            conn = sqlite3.connect(self._db_path, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA cache_size=-8192")  # 8 MB
            self._local.conn = conn
        return self._local.conn

    def _init_db(self) -> None:
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.executescript(_SCHEMA)
        conn.commit()
        conn.close()

    # ------------------------------------------------------------------
    # Thumbnail API
    # ------------------------------------------------------------------

    def get(self, path: str | Path, mtime: float, fsize: int,
            width: int, height: int) -> bytes | None:
        """Return cached PNG bytes, or None on miss / stale."""
        path = str(path)
        conn = self._conn()
        row = conn.execute(
            "SELECT png_data FROM thumbnails "
            "WHERE path=? AND mtime=? AND fsize=? AND width=? AND height=?",
            (path, mtime, fsize, width, height)
        ).fetchone()
        return row[0] if row else None

    def put(self, path: str | Path, mtime: float, fsize: int,
            width: int, height: int, png_data: bytes) -> None:
        """Insert or replace a thumbnail entry."""
        path = str(path)
        conn = self._conn()
        with self._lock:
            conn.execute(
                "INSERT OR REPLACE INTO thumbnails "
                "(path, mtime, fsize, width, height, png_data, created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (path, mtime, fsize, width, height, png_data, time.time())
            )
            conn.commit()

    def invalidate(self, path: str | Path) -> None:
        """Remove all cached entries for a path."""
        path = str(path)
        conn = self._conn()
        with self._lock:
            conn.execute("DELETE FROM thumbnails WHERE path=?", (path,))
            conn.commit()

    # ------------------------------------------------------------------
    # Metadata API
    # ------------------------------------------------------------------

    def get_meta(self, path: str | Path, mtime: float, fsize: int) -> str | None:
        """Return cached metadata JSON string, or None on miss / stale."""
        path = str(path)
        conn = self._conn()
        row = conn.execute(
            "SELECT info_json FROM metadata WHERE path=? AND mtime=? AND fsize=?",
            (path, mtime, fsize)
        ).fetchone()
        return row[0] if row else None

    def put_meta(self, path: str | Path, mtime: float, fsize: int,
                 info_json: str) -> None:
        """Insert or replace metadata."""
        path = str(path)
        conn = self._conn()
        with self._lock:
            conn.execute(
                "INSERT OR REPLACE INTO metadata "
                "(path, mtime, fsize, info_json, created_at) VALUES (?,?,?,?,?)",
                (path, mtime, fsize, info_json, time.time())
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def prune_missing(self) -> int:
        """Remove entries for files that no longer exist. Returns count removed."""
        conn = self._conn()
        rows = conn.execute("SELECT DISTINCT path FROM thumbnails").fetchall()
        removed = 0
        dead = [r[0] for r in rows if not Path(r[0]).exists()]
        if dead:
            with self._lock:
                conn.executemany(
                    "DELETE FROM thumbnails WHERE path=?",
                    [(p,) for p in dead]
                )
                conn.executemany(
                    "DELETE FROM metadata WHERE path=?",
                    [(p,) for p in dead]
                )
                conn.commit()
            removed = len(dead)
        log.info("Cache prune: removed %d stale entries", removed)
        return removed

    def stats(self) -> dict:
        """Return cache statistics."""
        conn = self._conn()
        thumb_count = conn.execute("SELECT COUNT(*) FROM thumbnails").fetchone()[0]
        thumb_size = conn.execute(
            "SELECT COALESCE(SUM(LENGTH(png_data)),0) FROM thumbnails"
        ).fetchone()[0]
        meta_count = conn.execute("SELECT COUNT(*) FROM metadata").fetchone()[0]
        return {
            "thumbnail_count": thumb_count,
            "thumbnail_bytes": thumb_size,
            "metadata_count": meta_count,
            "db_path": self._db_path,
        }

    def close(self) -> None:
        if hasattr(self._local, "conn"):
            self._local.conn.close()
            del self._local.conn
