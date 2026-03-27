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


def _load_fbx_vertices(path: Path) -> np.ndarray | None:
    """Extract vertex positions from FBX binary format (pure Python, no assimp).

    FBX Binary structure:
      Magic: b"Kaydara FBX Binary  \\x00\\x1a\\x00"  (23 bytes)
      Version: uint32
      Nodes: recursive records
    Each node record:
      EndOffset     : uint32 (FBX < 7500) or uint64 (FBX >= 7500)
      NumProperties : uint32 / uint64
      PropertyLen   : uint32 / uint64
      NameLen       : uint8
      Name          : bytes[NameLen]
      Properties    : ...
      Children      : recursive
    """
    import struct

    FBX_MAGIC = b"Kaydara FBX Binary  \x00\x1a\x00"
    try:
        data = path.read_bytes()
    except Exception:
        return None

    if not data.startswith(FBX_MAGIC):
        return None  # ASCII FBX or not FBX

    version = struct.unpack_from("<I", data, 23)[0]
    is_v7500 = version >= 7500

    def read_node(offset: int):
        """Parse one node, return (end_offset, name, properties, children_start)."""
        try:
            if is_v7500:
                end_off, n_props, prop_len = struct.unpack_from("<QQQ", data, offset)
                name_len = struct.unpack_from("B", data, offset + 24)[0]
                header_size = 25
            else:
                end_off, n_props, prop_len = struct.unpack_from("<III", data, offset)
                name_len = struct.unpack_from("B", data, offset + 12)[0]
                header_size = 13
        except struct.error:
            return None

        if end_off == 0:
            return None  # null record

        name_start = offset + header_size
        name = data[name_start: name_start + name_len].decode("utf-8", errors="replace")
        props_start = name_start + name_len
        children_start = props_start + prop_len
        return (int(end_off), name, props_start, int(n_props), children_start)

    def read_property(offset: int):
        """Read a single property value, return (value_or_None, next_offset)."""
        try:
            type_code = chr(data[offset])
            offset += 1
        except IndexError:
            return None, offset

        try:
            if type_code == "d":   # float64 array
                count, encoding, comp_len = struct.unpack_from("<III", data, offset)
                offset += 12
                raw = data[offset: offset + comp_len]
                offset += comp_len
                if encoding == 1:
                    import zlib
                    raw = zlib.decompress(raw)
                arr = np.frombuffer(raw, dtype=np.float64)
                return arr, offset
            elif type_code == "f":  # float32 array
                count, encoding, comp_len = struct.unpack_from("<III", data, offset)
                offset += 12
                raw = data[offset: offset + comp_len]
                offset += comp_len
                if encoding == 1:
                    import zlib
                    raw = zlib.decompress(raw)
                arr = np.frombuffer(raw, dtype=np.float32).astype(np.float64)
                return arr, offset
            elif type_code == "D":  # double scalar
                v = struct.unpack_from("<d", data, offset)[0]
                return v, offset + 8
            elif type_code == "F":  # float scalar
                v = struct.unpack_from("<f", data, offset)[0]
                return v, offset + 4
            elif type_code == "I":  # int32 scalar
                v = struct.unpack_from("<i", data, offset)[0]
                return v, offset + 4
            elif type_code == "L":  # int64 scalar
                v = struct.unpack_from("<q", data, offset)[0]
                return v, offset + 8
            elif type_code == "S":  # string
                slen = struct.unpack_from("<I", data, offset)[0]
                s = data[offset + 4: offset + 4 + slen]
                return s, offset + 4 + slen
            elif type_code == "R":  # raw bytes
                rlen = struct.unpack_from("<I", data, offset)[0]
                return None, offset + 4 + rlen
            elif type_code in ("C", "Y", "i", "l", "b"):
                sizes = {"C": 1, "Y": 2, "i": 4, "l": 8, "b": 1}
                return None, offset + sizes.get(type_code, 1)
            else:
                return None, offset
        except Exception:
            return None, offset

    all_vertices = []

    def walk_nodes(offset: int, end: int, depth: int = 0):
        """Recursively walk nodes, collect Vertices arrays."""
        while offset < end:
            node = read_node(offset)
            if node is None:
                break
            end_off, name, props_start, n_props, children_start = node

            # Collect Vertices property (array of float64/float32)
            if name == "Vertices" and n_props >= 1:
                prop_val, _ = read_property(props_start)
                if isinstance(prop_val, np.ndarray) and len(prop_val) >= 3:
                    pts = prop_val.reshape(-1, 3)
                    all_vertices.append(pts)

            # Recurse into children (limit depth to avoid infinite loops)
            if depth < 8 and children_start < end_off:
                walk_nodes(children_start, end_off, depth + 1)

            offset = end_off

    walk_nodes(27, len(data) - 1)

    if not all_vertices:
        return None

    pts = np.concatenate(all_vertices, axis=0)
    return pts.astype(np.float32)


def _render_pointcloud_as_mesh(pts: np.ndarray, size: int) -> bytes:
    """Render extracted vertices as a point cloud projection."""
    from .pointcloud_gen import _project_points_to_image
    return _project_points_to_image(pts, size)


def generate_mesh_thumbnail(path: Path, size: int) -> bytes:
    """Load 3D mesh and render thumbnail.

    For FBX: tries trimesh first (needs assimp), falls back to pure Python
    FBX binary vertex extraction + point cloud projection.
    """
    import trimesh

    ext = path.suffix.lstrip(".").lower()
    log.debug("Loading mesh: %s", path)

    try:
        scene_or_mesh = trimesh.load(str(path), force="scene")
        # Verify we actually got geometry
        if hasattr(scene_or_mesh, "geometry") and not scene_or_mesh.geometry:
            raise ValueError("trimesh returned empty scene")
        result = _render_with_pyrender(scene_or_mesh, size)
        if result:
            return result
        return _render_with_trimesh(scene_or_mesh, size)

    except Exception as e:
        log.debug("trimesh load failed for %s (%s), trying fallback", path, e)

    # FBX fallback: pure Python vertex extraction
    if ext == "fbx":
        pts = _load_fbx_vertices(path)
        if pts is not None and len(pts) >= 3:
            log.debug("FBX fallback: rendering %d vertices from %s", len(pts), path)
            return _render_pointcloud_as_mesh(pts, size)

    # Final fallback: metadata icon
    return generate_metadata_only_thumbnail(path, size, path.suffix.lstrip(".").upper())


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
