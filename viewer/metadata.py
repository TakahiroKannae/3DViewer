"""File metadata extraction."""

from __future__ import annotations

import json
import logging
import os
import struct
from pathlib import Path

from .formats import get_format_info, CATEGORY_3D, CATEGORY_IMAGE, CATEGORY_VIDEO
from .formats import CATEGORY_POINTCLOUD, CATEGORY_DOCUMENT
from .sequence import SequenceGroup

log = logging.getLogger(__name__)


def _size_human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def get_metadata(item: Path | SequenceGroup) -> dict:
    """Return a dict of displayable metadata for the given file/group."""
    if isinstance(item, SequenceGroup):
        return _sequence_meta(item)

    path = item
    try:
        st = path.stat()
    except OSError as e:
        return {"error": str(e)}

    category, label = get_format_info(path)
    base = {
        "name": path.name,
        "path": str(path),
        "size": _size_human(st.st_size),
        "size_bytes": st.st_size,
        "modified": _fmt_time(st.st_mtime),
        "format": label,
        "category": category,
    }

    try:
        extra = _format_extra(path, category)
        base.update(extra)
    except Exception as exc:
        log.debug("Extra metadata failed for %s: %s", path, exc)

    return base


def _sequence_meta(grp: SequenceGroup) -> dict:
    total = sum(p.stat().st_size for p in grp.members if p.exists())
    st = grp.first_frame.stat()
    category, label = get_format_info(grp.first_frame)
    return {
        "name": grp.pattern,
        "path": str(grp.directory / grp.pattern),
        "size": _size_human(total),
        "size_bytes": total,
        "modified": _fmt_time(st.st_mtime),
        "format": label,
        "category": category,
        "frame_count": grp.frame_count,
        "first_frame": str(grp.first_frame),
        "last_frame": str(grp.members[-1]),
    }


def _fmt_time(ts: float) -> str:
    import datetime
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def _format_extra(path: Path, category: str) -> dict:
    if category == CATEGORY_IMAGE:
        return _image_meta(path)
    if category == CATEGORY_VIDEO:
        return _video_meta(path)
    if category == CATEGORY_3D:
        return _mesh_meta(path)
    if category == CATEGORY_POINTCLOUD:
        return _pointcloud_meta(path)
    return {}


def _image_meta(path: Path) -> dict:
    ext = path.suffix.lstrip(".").lower()
    if ext == "exr":
        try:
            import OpenEXR
            f = OpenEXR.InputFile(str(path))
            h = f.header()
            dw = h["dataWindow"]
            w = dw.max.x - dw.min.x + 1
            ht = dw.max.y - dw.min.y + 1
            channels = list(h.get("channels", {}).keys())
            return {"width": w, "height": ht, "channels": ", ".join(channels)}
        except Exception:
            pass
    try:
        from PIL import Image
        with Image.open(path) as img:
            w, h = img.size
            return {"width": w, "height": h, "mode": img.mode}
    except Exception:
        return {}


def _video_meta(path: Path) -> dict:
    import subprocess, sys
    try:
        from .thumbnails.video_gen import _find_ffmpeg
        ffprobe = _find_ffmpeg().replace("ffmpeg", "ffprobe")
        result = subprocess.run(
            [ffprobe, "-v", "quiet", "-print_format", "json",
             "-show_streams", "-show_format", str(path)],
            capture_output=True, text=True, timeout=10,
            creationflags=0x08000000 if sys.platform == "win32" else 0
        )
        data = json.loads(result.stdout)
        fmt = data.get("format", {})
        streams = data.get("streams", [])
        vstream = next((s for s in streams if s.get("codec_type") == "video"), {})
        return {
            "duration": fmt.get("duration", "?"),
            "width": vstream.get("width"),
            "height": vstream.get("height"),
            "codec": vstream.get("codec_name"),
            "fps": vstream.get("r_frame_rate"),
        }
    except Exception:
        return {}


def _mesh_meta(path: Path) -> dict:
    ext = path.suffix.lstrip(".").lower()
    from .formats import TRIMESH_LOADABLE
    if ext not in TRIMESH_LOADABLE:
        return {}
    try:
        import trimesh
        scene = trimesh.load(str(path), force="scene")
        verts = sum(getattr(m, "vertices", []) is not None and len(m.vertices)
                    for m in (scene.geometry.values() if hasattr(scene, "geometry") else [scene]))
        faces = sum(getattr(m, "faces", []) is not None and len(m.faces)
                    for m in (scene.geometry.values() if hasattr(scene, "geometry") else [scene]))
        return {"vertices": verts, "faces": faces}
    except Exception:
        return {}


def _pointcloud_meta(path: Path) -> dict:
    ext = path.suffix.lstrip(".").lower()
    if ext in ("las", "laz"):
        try:
            import laspy
            las = laspy.read(str(path))
            return {"point_count": len(las.x), "crs": str(getattr(las.header, "parse_crs", lambda: None)())}
        except Exception:
            return {}
    try:
        import open3d as o3d
        pcd = o3d.io.read_point_cloud(str(path))
        return {"point_count": len(pcd.points)}
    except Exception:
        return {}
