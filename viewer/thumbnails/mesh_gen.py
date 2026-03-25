"""3D mesh thumbnail generation via trimesh + offscreen OpenGL rendering."""

from __future__ import annotations

import io
import logging
import math
from pathlib import Path

import numpy as np
from PIL import Image

log = logging.getLogger(__name__)

# Camera parameters: 45° elevation, 30° azimuth
_ELEV_DEG = 45.0
_AZIM_DEG = 30.0


def _camera_transform(bounds: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    """Compute camera position, lookat, and distance from mesh bounds."""
    center = (bounds[0] + bounds[1]) / 2
    extent = np.linalg.norm(bounds[1] - bounds[0])
    dist = extent * 1.5

    elev = math.radians(_ELEV_DEG)
    azim = math.radians(_AZIM_DEG)

    eye = center + dist * np.array([
        math.cos(elev) * math.cos(azim),
        math.cos(elev) * math.sin(azim),
        math.sin(elev),
    ])
    return eye, center, dist


def _render_with_pyrender(mesh_scene, size: int) -> bytes | None:
    """Try rendering with pyrender (optional dependency)."""
    try:
        import pyrender
        import trimesh

        scene = pyrender.Scene.from_trimesh_scene(mesh_scene)
        bounds = mesh_scene.bounds
        eye, center, _ = _camera_transform(bounds)

        camera = pyrender.PerspectiveCamera(yfov=math.radians(45.0))
        up = np.array([0, 0, 1], dtype=float)
        forward = center - eye
        forward /= np.linalg.norm(forward)
        right = np.cross(forward, up)
        if np.linalg.norm(right) < 1e-6:
            up = np.array([0, 1, 0], dtype=float)
            right = np.cross(forward, up)
        right /= np.linalg.norm(right)
        up = np.cross(right, forward)

        cam_pose = np.eye(4)
        cam_pose[:3, 0] = right
        cam_pose[:3, 1] = up
        cam_pose[:3, 2] = -forward
        cam_pose[:3, 3] = eye

        scene.add(camera, pose=cam_pose)
        light = pyrender.DirectionalLight(color=[1, 1, 1], intensity=3.0)
        scene.add(light, pose=cam_pose)

        r = pyrender.OffscreenRenderer(size, size)
        color, _ = r.render(scene)
        r.delete()

        img = Image.fromarray(color, "RGB")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return None


def _render_with_trimesh(mesh_scene, size: int) -> bytes:
    """Fallback: use trimesh's built-in PNG export (software renderer)."""
    import trimesh

    if hasattr(mesh_scene, "geometry") and mesh_scene.geometry:
        meshes = list(mesh_scene.geometry.values())
        combined = trimesh.util.concatenate(meshes)
    else:
        combined = mesh_scene

    bounds = combined.bounds
    eye, center, dist = _camera_transform(bounds)

    # Use trimesh scene export
    scene = trimesh.Scene([combined])
    scene.camera.resolution = (size, size)
    scene.camera.fov = (60, 60)
    scene.camera_transform = scene.camera.look_at(
        combined.vertices, rotation=trimesh.transformations.euler_matrix(
            math.radians(-_ELEV_DEG), 0, math.radians(_AZIM_DEG)
        )
    )
    try:
        png_bytes = scene.save_image(resolution=(size, size))
        if png_bytes:
            return png_bytes
    except Exception:
        pass

    # Last resort: solid color placeholder
    img = Image.new("RGB", (size, size), (80, 80, 80))
    draw_wireframe_placeholder(img, combined, size)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def draw_wireframe_placeholder(img: Image.Image, mesh, size: int) -> None:
    """Draw a rough 2D projection as wireframe placeholder."""
    from PIL import ImageDraw

    verts = mesh.vertices
    # Project onto XY plane with simple ortho
    mn = verts.min(axis=0)
    mx = verts.max(axis=0)
    scale_x = (size - 20) / max(mx[0] - mn[0], 1e-6)
    scale_y = (size - 20) / max(mx[1] - mn[1], 1e-6)
    scale = min(scale_x, scale_y)

    draw = ImageDraw.Draw(img)
    faces = mesh.faces[:500]  # limit for speed
    for face in faces:
        pts = []
        for vi in face:
            x = int((verts[vi][0] - mn[0]) * scale) + 10
            y = int((verts[vi][1] - mn[1]) * scale) + 10
            pts.append((x, size - y))
        if len(pts) >= 2:
            draw.line(pts + [pts[0]], fill=(180, 180, 180), width=1)


def generate_mesh_thumbnail(path: Path, size: int) -> bytes:
    """Load 3D mesh and render thumbnail."""
    import trimesh

    log.debug("Loading mesh: %s", path)
    scene_or_mesh = trimesh.load(str(path), force="scene")

    result = _render_with_pyrender(scene_or_mesh, size)
    if result:
        return result
    return _render_with_trimesh(scene_or_mesh, size)


def generate_metadata_only_thumbnail(path: Path, size: int, label: str) -> bytes:
    """For formats we can't render (Maya, Blender, etc.) — show a labeled icon."""
    from PIL import ImageDraw, ImageFont

    bg = (50, 50, 60)
    img = Image.new("RGB", (size, size), bg)
    draw = ImageDraw.Draw(img)

    # Draw a simple 3D-cube wireframe icon
    cx, cy = size // 2, size // 2
    hs = size // 4
    offset = size // 8
    # Front face
    front = [(cx - hs, cy + hs), (cx + hs, cy + hs),
             (cx + hs, cy - hs), (cx - hs, cy - hs)]
    # Back face (offset)
    back = [(x + offset, y - offset) for x, y in front]
    color = (100, 180, 220)
    for a, b in zip(front, front[1:] + front[:1]):
        draw.line([a, b], fill=color, width=2)
    for a, b in zip(back, back[1:] + back[:1]):
        draw.line([a, b], fill=color, width=1)
    for a, b in zip(front, back):
        draw.line([a, b], fill=color, width=1)

    # Label
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", max(10, size // 10))
    except Exception:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), label, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((size - tw) // 2, size - th - 6), label, fill=(220, 220, 220), font=font)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
