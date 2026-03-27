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


def _exr_via_openexr(path: Path, size: int) -> bytes:
    """EXR via OpenEXR library (optional, Linux/Mac向け)."""
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
    rgb = rgb / (1.0 + rgb)          # Reinhard tone mapping
    rgb = np.clip(rgb, 0, 1)
    rgb = (rgb ** (1.0 / _TONE_GAMMA) * 255).astype(np.uint8)
    img = Image.fromarray(rgb, mode="RGB")
    return _to_png_bytes(img, size)


def _exr_via_opencv(path: Path, size: int) -> bytes:
    """EXR via opencv-python (Windows推奨: pip install opencv-python でEXRサポート内蔵)."""
    import os
    # OpenCV 4.5.4+ ではセキュリティのためEXR読み込みに環境変数が必要
    os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"
    import cv2
    import numpy as np

    img = cv2.imread(str(path), cv2.IMREAD_ANYCOLOR | cv2.IMREAD_ANYDEPTH)
    if img is None:
        raise ValueError(f"cv2.imread returned None for {path}")

    img = img.astype(np.float32)
    # BGR → RGB
    if img.ndim == 3 and img.shape[2] >= 3:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    elif img.ndim == 2:
        img = np.stack([img, img, img], axis=-1)

    img = img[:, :, :3]
    # Reinhard tone mapping
    img = img / (1.0 + img)
    img = np.clip(img, 0, 1)
    img = (img ** (1.0 / _TONE_GAMMA) * 255).astype(np.uint8)
    return _to_png_bytes(Image.fromarray(img, mode="RGB"), size)


def _exr_via_pil(path: Path, size: int) -> bytes:
    """EXR 最終フォールバック: PIL で試みる（失敗時はグレープレースホルダー）。"""
    import numpy as np

    try:
        with Image.open(path) as img:
            arr = np.array(img, dtype=np.float32)
            if arr.ndim == 2:
                arr = np.stack([arr, arr, arr], axis=-1)
            arr = arr[:, :, :3]
            arr = arr / (1.0 + arr)
            arr = np.clip(arr, 0, 1)
            arr = (arr ** (1.0 / _TONE_GAMMA) * 255).astype(np.uint8)
            return _to_png_bytes(Image.fromarray(arr, mode="RGB"), size)
    except Exception:
        img = Image.new("RGB", (size, size), (60, 60, 70))
        from PIL import ImageDraw, ImageFont
        draw = ImageDraw.Draw(img)
        font = ImageFont.load_default()
        draw.text((size // 4, size // 2 - 8), "EXR", fill=(200, 200, 200), font=font)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()


def generate_exr_thumbnail(path: Path, size: int) -> bytes:
    """EXR thumbnail with Reinhard tone mapping.
    優先順位: OpenEXR → OpenCV (opencv-python) → PIL
    Windows では opencv-python が最も確実に動作します。
    """
    # 1. OpenEXR (Linux/Mac でビルド済みの場合)
    try:
        return _exr_via_openexr(path, size)
    except ImportError:
        pass
    except Exception as e:
        log.debug("OpenEXR failed for %s: %s", path, e)

    # 2. OpenCV (Windows 推奨: pip install opencv-python)
    try:
        return _exr_via_opencv(path, size)
    except ImportError:
        log.debug("opencv-python not installed, trying PIL for %s", path)
    except Exception as e:
        log.debug("OpenCV EXR failed for %s: %s", path, e)

    # 3. PIL フォールバック
    return _exr_via_pil(path, size)


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
