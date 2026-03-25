"""Thumbnail generation for raster/image formats."""

from __future__ import annotations

import io
import logging
from pathlib import Path

from PIL import Image

log = logging.getLogger(__name__)

_TONE_GAMMA = 2.2


def _to_png_bytes(img: Image.Image, size: int) -> bytes:
    img.thumbnail((size, size), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=False)
    return buf.getvalue()


def generate_image_thumbnail(path: Path, size: int) -> bytes:
    """PIL-based thumbnail for common raster formats."""
    with Image.open(path) as img:
        img = img.convert("RGBA") if img.mode in ("RGBA", "LA") else img.convert("RGB")
        return _to_png_bytes(img, size)


def generate_exr_thumbnail(path: Path, size: int) -> bytes:
    """EXR thumbnail with simple reinhard tone mapping."""
    try:
        import OpenEXR
        import Imath
        import numpy as np

        f = OpenEXR.InputFile(str(path))
        header = f.header()
        dw = header["dataWindow"]
        w = dw.max.x - dw.min.x + 1
        h = dw.max.y - dw.min.y + 1
        pt = Imath.PixelType(Imath.PixelType.FLOAT)
        r = np.frombuffer(f.channel("R", pt), dtype=np.float32).reshape(h, w)
        g = np.frombuffer(f.channel("G", pt), dtype=np.float32).reshape(h, w)
        b = np.frombuffer(f.channel("B", pt), dtype=np.float32).reshape(h, w)
        rgb = np.stack([r, g, b], axis=-1)
        # Reinhard tone mapping
        rgb = rgb / (1.0 + rgb)
        rgb = np.clip(rgb, 0, 1)
        rgb = (rgb ** (1.0 / _TONE_GAMMA) * 255).astype(np.uint8)
        img = Image.fromarray(rgb, mode="RGB")
        return _to_png_bytes(img, size)
    except Exception:
        log.exception("EXR thumbnail failed for %s, falling back to PIL", path)
        return generate_image_thumbnail(path, size)


def generate_hdr_thumbnail(path: Path, size: int) -> bytes:
    """HDR/Radiance thumbnail via PIL (supports .hdr)."""
    try:
        with Image.open(path) as img:
            # PIL opens HDR as float; convert for display
            import numpy as np
            arr = np.array(img, dtype=np.float32)
            arr = arr / (1.0 + arr)  # Reinhard
            arr = np.clip(arr, 0, 1)
            arr = (arr ** (1.0 / _TONE_GAMMA) * 255).astype(np.uint8)
            img = Image.fromarray(arr[:, :, :3], mode="RGB")
            return _to_png_bytes(img, size)
    except Exception:
        log.exception("HDR thumbnail failed for %s", path)
        raise


def generate_psd_thumbnail(path: Path, size: int) -> bytes:
    """PSD/PSB composite thumbnail via psd-tools."""
    from psd_tools import PSDImage
    psd = PSDImage.open(str(path))
    img = psd.composite()
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")
    return _to_png_bytes(img, size)


def generate_gif_thumbnail(path: Path, size: int) -> bytes:
    """First frame of GIF."""
    with Image.open(path) as img:
        img.seek(0)
        frame = img.convert("RGB")
        return _to_png_bytes(frame, size)
