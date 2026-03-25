"""Thumbnail generation for document formats (PDF, text)."""

from __future__ import annotations

import io
import logging
from pathlib import Path

from PIL import Image

log = logging.getLogger(__name__)

_TEXT_EXTENSIONS = {"json", "yaml", "yml", "xml", "csv", "txt"}


def generate_pdf_thumbnail(path: Path, size: int) -> bytes:
    """Render first page of PDF via pymupdf."""
    import fitz  # type: ignore

    doc = fitz.open(str(path))
    page = doc[0]
    # Scale so the longest side ≈ size
    scale = size / max(page.rect.width, page.rect.height)
    mat = fitz.Matrix(scale, scale)
    pix = page.get_pixmap(matrix=mat)
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def generate_text_thumbnail(path: Path, size: int) -> bytes:
    """Render the first 100 lines of a text file as a simple image."""
    from PIL import ImageDraw, ImageFont

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        text = path.read_text(encoding="latin-1", errors="replace")

    lines = text.splitlines()[:100]
    preview = "\n".join(lines)

    bg_color = (30, 30, 30)
    fg_color = (200, 200, 200)
    img = Image.new("RGB", (size, size), bg_color)
    draw = ImageDraw.Draw(img)

    # Try to use a monospace font; fall back to default
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 9)
    except Exception:
        font = ImageFont.load_default()

    draw.text((4, 4), preview, fill=fg_color, font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
