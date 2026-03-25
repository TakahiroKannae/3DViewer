"""Game engine asset thumbnails (Unreal, Unity)."""

from __future__ import annotations

import io
import logging
from pathlib import Path

from PIL import Image

log = logging.getLogger(__name__)

_THUMB_NAMES = ["Thumb.png", "thumbnail.png", ".thumb.png"]


def generate_unreal_thumbnail(path: Path, size: int) -> bytes | None:
    """Try to find Unreal-generated thumbnail PNG near the .uasset/.umap file."""
    parent = path.parent
    stem = path.stem

    candidates = [
        parent / f"{stem}_Thumb.png",
        parent / "Thumbnails" / f"{stem}.png",
        parent.parent / "Thumbnails" / f"{stem}.png",
    ]
    for c in candidates:
        if c.exists():
            try:
                with Image.open(c) as img:
                    img.thumbnail((size, size), Image.LANCZOS)
                    buf = io.BytesIO()
                    img.save(buf, format="PNG")
                    return buf.getvalue()
            except Exception:
                log.debug("Failed to open Unreal thumb: %s", c)
    return None


def generate_unity_thumbnail(path: Path, size: int) -> bytes | None:
    """Parse Unity .meta / .prefab YAML for embedded preview."""
    try:
        import yaml  # PyYAML
    except ImportError:
        return None

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        # Strip Unity-specific YAML tags that confuse the parser
        import re
        text = re.sub(r"!u![0-9]+ &[0-9]+", "---", text)
        text = re.sub(r"%YAML.*\n", "", text)
        text = re.sub(r"%TAG.*\n", "", text)
        data = yaml.safe_load(text)
    except Exception:
        return None

    if not isinstance(data, dict):
        return None

    # Look for embedded base64 thumbnail
    import base64
    thumb_b64 = (
        data.get("TextureImporter", {}).get("thumbnailCustom")
        or data.get("preview")
    )
    if thumb_b64 and isinstance(thumb_b64, str):
        try:
            img_bytes = base64.b64decode(thumb_b64)
            img = Image.open(io.BytesIO(img_bytes))
            img.thumbnail((size, size), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue()
        except Exception:
            pass
    return None


def generate_gameengine_placeholder(path: Path, size: int, label: str) -> bytes:
    """Placeholder icon for game engine assets."""
    from PIL import ImageDraw, ImageFont

    colors = {
        "uasset": (30, 30, 60),
        "umap":   (20, 40, 60),
        "prefab": (30, 50, 30),
        "mat":    (50, 30, 30),
        "meta":   (40, 40, 40),
    }
    ext = path.suffix.lstrip(".").lower()
    bg = colors.get(ext, (40, 40, 40))

    img = Image.new("RGB", (size, size), bg)
    draw = ImageDraw.Draw(img)

    # Simple geometric icon
    m = size // 4
    draw.rectangle([(m, m), (size - m, size - m)], outline=(120, 180, 240), width=2)
    draw.line([(m, m), (size - m, size - m)], fill=(120, 180, 240), width=1)
    draw.line([(size - m, m), (m, size - m)], fill=(120, 180, 240), width=1)

    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", max(9, size // 11))
    except Exception:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), label, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((size - tw) // 2, size - th - 6), label, fill=(200, 220, 255), font=font)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
