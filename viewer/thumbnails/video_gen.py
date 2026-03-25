"""Video thumbnail generation via ffmpeg subprocess."""

from __future__ import annotations

import io
import logging
import subprocess
import sys
from pathlib import Path

from PIL import Image

log = logging.getLogger(__name__)


def _find_ffmpeg() -> str:
    """Return path to ffmpeg binary: bundled first, then PATH."""
    # Check for bundled binary next to the package
    candidates = [
        Path(__file__).parent.parent.parent / "bin" / "ffmpeg",
        Path(__file__).parent.parent.parent / "bin" / "ffmpeg.exe",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return "ffmpeg"  # fallback to PATH


def generate_video_thumbnail(path: Path, size: int) -> bytes:
    """Extract middle frame from video using ffmpeg."""
    ffmpeg = _find_ffmpeg()

    # First, get duration
    probe_cmd = [
        ffmpeg, "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path)
    ]
    # Use ffprobe if available
    ffprobe = ffmpeg.replace("ffmpeg", "ffprobe")
    try:
        result = subprocess.run(
            [ffprobe, "-v", "error",
             "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1",
             str(path)],
            capture_output=True, text=True, timeout=15
        )
        duration = float(result.stdout.strip() or "0")
    except Exception:
        duration = 0.0

    seek = max(0.0, duration / 2) if duration > 0 else 0.0

    cmd = [
        ffmpeg,
        "-ss", str(seek),
        "-i", str(path),
        "-frames:v", "1",
        "-vf", f"scale={size}:{size}:force_original_aspect_ratio=decrease",
        "-f", "image2",
        "-vcodec", "png",
        "pipe:1",
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, timeout=30,
            creationflags=0x08000000 if sys.platform == "win32" else 0
        )
        if result.returncode != 0 or not result.stdout:
            raise RuntimeError(f"ffmpeg failed: {result.stderr.decode(errors='replace')[:200]}")
        img = Image.open(io.BytesIO(result.stdout)).convert("RGB")
        buf = io.BytesIO()
        img.thumbnail((size, size), Image.LANCZOS)
        img.save(buf, format="PNG")
        return buf.getvalue()
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"ffmpeg timed out for {path}")
