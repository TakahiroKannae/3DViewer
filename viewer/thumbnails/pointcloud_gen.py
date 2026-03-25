"""Point cloud thumbnail generation via open3d."""

from __future__ import annotations

import io
import logging
import math
from pathlib import Path

import numpy as np
from PIL import Image

log = logging.getLogger(__name__)


def _project_points_to_image(points: np.ndarray, size: int) -> bytes:
    """Software-render a point cloud as coloured dots."""
    if len(points) == 0:
        img = Image.new("RGB", (size, size), (20, 20, 30))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    # Subsample for performance
    if len(points) > 200_000:
        idx = np.random.choice(len(points), 200_000, replace=False)
        points = points[idx]

    # Isometric-ish projection (XY plane, Z as brightness)
    elev = math.radians(35)
    azim = math.radians(45)
    Rx = np.array([
        [1, 0, 0],
        [0, math.cos(elev), -math.sin(elev)],
        [0, math.sin(elev),  math.cos(elev)],
    ])
    Rz = np.array([
        [math.cos(azim), -math.sin(azim), 0],
        [math.sin(azim),  math.cos(azim), 0],
        [0, 0, 1],
    ])
    R = Rx @ Rz
    pts = (R @ points.T).T

    mn = pts.min(axis=0)
    mx = pts.max(axis=0)
    span = (mx - mn)
    span[span == 0] = 1.0
    scale = (size - 4) / span[:2].max()

    px = ((pts[:, 0] - mn[0]) * scale + 2).astype(int)
    py = ((pts[:, 1] - mn[1]) * scale + 2).astype(int)
    pz = (pts[:, 2] - mn[2]) / span[2]  # 0..1

    px = np.clip(px, 0, size - 1)
    py = np.clip(py, 0, size - 1)

    canvas = np.zeros((size, size, 3), dtype=np.uint8)
    # Colour by height: blue→cyan→green
    r = (pz * 0 * 255).astype(np.uint8)
    g = (pz * 200 + 55).astype(np.uint8)
    b = ((1 - pz) * 200 + 55).astype(np.uint8)

    canvas[py, px, 0] = r
    canvas[py, px, 1] = g
    canvas[py, px, 2] = b

    img = Image.fromarray(canvas, "RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def generate_las_thumbnail(path: Path, size: int) -> bytes:
    """LAS/LAZ thumbnail via laspy."""
    import laspy

    las = laspy.read(str(path))
    pts = np.stack([
        las.x.scaled_array(),
        las.y.scaled_array(),
        las.z.scaled_array(),
    ], axis=-1)
    return _project_points_to_image(pts, size)


def generate_open3d_pointcloud_thumbnail(path: Path, size: int) -> bytes:
    """Point cloud thumbnail via open3d for PCD, XYZ, PTX, E57."""
    import open3d as o3d

    pcd = o3d.io.read_point_cloud(str(path))
    pts = np.asarray(pcd.points)
    return _project_points_to_image(pts, size)


def generate_pointcloud_metadata_thumbnail(path: Path, size: int, label: str) -> bytes:
    """Placeholder for unsupported point cloud formats."""
    from PIL import ImageDraw, ImageFont

    img = Image.new("RGB", (size, size), (20, 30, 40))
    draw = ImageDraw.Draw(img)

    # Draw dot-cloud icon
    import random
    rng = random.Random(42)
    for _ in range(300):
        x = rng.randint(10, size - 10)
        y = rng.randint(10, size - 30)
        g = rng.randint(100, 220)
        b = rng.randint(150, 255)
        r = 0
        draw.ellipse([(x - 1, y - 1), (x + 1, y + 1)], fill=(r, g, b))

    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", max(10, size // 10))
    except Exception:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), label, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((size - tw) // 2, size - th - 6), label, fill=(200, 240, 255), font=font)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
