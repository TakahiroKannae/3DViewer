"""Central thumbnail generation dispatcher."""

from __future__ import annotations

import io
import logging
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from ..formats import (
    CATEGORY_3D, CATEGORY_POINTCLOUD, CATEGORY_IMAGE,
    CATEGORY_VIDEO, CATEGORY_DOCUMENT, CATEGORY_GAMEENGINE,
    TRIMESH_LOADABLE, METADATA_ONLY_3D,
    get_format_info, get_label,
)

log = logging.getLogger(__name__)

_OPEN3D_PC_EXTS = {"pcd", "xyz", "pts", "ptx", "e57"}


def _fallback_icon(path: Path, size: int, label: str, error: str = "") -> bytes:
    """Generic error / unknown format icon."""
    bg = (45, 45, 55)
    img = Image.new("RGB", (size, size), bg)
    draw = ImageDraw.Draw(img)

    # Question mark
    try:
        font_big = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            max(20, size // 3)
        )
        font_sm = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            max(9, size // 10)
        )
    except Exception:
        font_big = ImageFont.load_default()
        font_sm = font_big

    sym = "?"
    bb = draw.textbbox((0, 0), sym, font=font_big)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    draw.text(((size - tw) // 2, (size - th) // 2 - size // 10), sym,
              fill=(160, 160, 180), font=font_big)

    bb2 = draw.textbbox((0, 0), label, font=font_sm)
    tw2 = bb2[2] - bb2[0]
    draw.text(((size - tw2) // 2, size - (bb2[3] - bb2[1]) - 4),
              label, fill=(180, 180, 200), font=font_sm)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def generate_thumbnail(path: str | Path, size: int = 128) -> bytes:
    """Generate a PNG thumbnail for any supported file.

    Returns PNG bytes.  Never raises — on failure returns a fallback icon.
    """
    path = Path(path)
    ext = path.suffix.lstrip(".").lower()
    category, label = get_format_info(path)

    try:
        # ----------------------------------------------------------------
        # Images
        # ----------------------------------------------------------------
        if category == CATEGORY_IMAGE:
            if ext == "exr":
                from .image_gen import generate_exr_thumbnail
                return generate_exr_thumbnail(path, size)
            elif ext in ("hdr",):
                from .image_gen import generate_hdr_thumbnail
                return generate_hdr_thumbnail(path, size)
            elif ext in ("psd", "psb"):
                from .image_gen import generate_psd_thumbnail
                return generate_psd_thumbnail(path, size)
            elif ext == "gif":
                from .image_gen import generate_gif_thumbnail
                return generate_gif_thumbnail(path, size)
            elif ext == "dpx":
                # PIL can open DPX via rawmode
                from .image_gen import generate_image_thumbnail
                return generate_image_thumbnail(path, size)
            else:
                from .image_gen import generate_image_thumbnail
                return generate_image_thumbnail(path, size)

        # ----------------------------------------------------------------
        # Video
        # ----------------------------------------------------------------
        elif category == CATEGORY_VIDEO:
            from .video_gen import generate_video_thumbnail
            return generate_video_thumbnail(path, size)

        # ----------------------------------------------------------------
        # Documents
        # ----------------------------------------------------------------
        elif category == CATEGORY_DOCUMENT:
            if ext == "pdf":
                from .document_gen import generate_pdf_thumbnail
                return generate_pdf_thumbnail(path, size)
            else:
                from .document_gen import generate_text_thumbnail
                return generate_text_thumbnail(path, size)

        # ----------------------------------------------------------------
        # 3D Meshes
        # ----------------------------------------------------------------
        elif category == CATEGORY_3D:
            if ext in METADATA_ONLY_3D:
                from .mesh_gen import generate_metadata_only_thumbnail
                return generate_metadata_only_thumbnail(path, size, label)
            elif ext in TRIMESH_LOADABLE:
                from .mesh_gen import generate_mesh_thumbnail
                return generate_mesh_thumbnail(path, size)
            else:
                # Try trimesh anyway (it supports more than TRIMESH_LOADABLE)
                try:
                    from .mesh_gen import generate_mesh_thumbnail
                    return generate_mesh_thumbnail(path, size)
                except Exception:
                    from .mesh_gen import generate_metadata_only_thumbnail
                    return generate_metadata_only_thumbnail(path, size, label)

        # ----------------------------------------------------------------
        # Point clouds
        # ----------------------------------------------------------------
        elif category == CATEGORY_POINTCLOUD:
            if ext in ("las", "laz"):
                from .pointcloud_gen import generate_las_thumbnail
                return generate_las_thumbnail(path, size)
            elif ext in _OPEN3D_PC_EXTS:
                from .pointcloud_gen import generate_open3d_pointcloud_thumbnail
                return generate_open3d_pointcloud_thumbnail(path, size)
            else:
                from .pointcloud_gen import generate_pointcloud_metadata_thumbnail
                return generate_pointcloud_metadata_thumbnail(path, size, label)

        # ----------------------------------------------------------------
        # Game engine assets
        # ----------------------------------------------------------------
        elif category == CATEGORY_GAMEENGINE:
            if ext in ("uasset", "umap"):
                from .gameengine_gen import generate_unreal_thumbnail
                result = generate_unreal_thumbnail(path, size)
                if result:
                    return result
            elif ext in ("prefab", "mat", "meta"):
                from .gameengine_gen import generate_unity_thumbnail
                result = generate_unity_thumbnail(path, size)
                if result:
                    return result
            from .gameengine_gen import generate_gameengine_placeholder
            return generate_gameengine_placeholder(path, size, label)

        # ----------------------------------------------------------------
        # Unknown
        # ----------------------------------------------------------------
        else:
            return _fallback_icon(path, size, label)

    except Exception as exc:
        log.warning("Thumbnail generation failed for %s: %s", path, exc, exc_info=True)
        return _fallback_icon(path, size, label, str(exc))
