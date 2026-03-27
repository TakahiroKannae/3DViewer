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


def _parse_fbx_binary(path: Path) -> dict | None:
    """Extract vertices + triangulated faces from FBX binary (pure Python).

    Returns dict with 'vertices' (Nx3 float32) and 'faces' (Mx3 int32),
    or None if parse fails / not binary FBX.
    """
    import struct, zlib

    FBX_MAGIC = b"Kaydara FBX Binary  \x00\x1a\x00"
    try:
        data = path.read_bytes()
    except Exception:
        return None
    if not data.startswith(FBX_MAGIC):
        return None

    version = struct.unpack_from("<I", data, 23)[0]
    is_v7500 = version >= 7500

    def read_node(off):
        try:
            if is_v7500:
                eo, np_, pl = struct.unpack_from("<QQQ", data, off)
                nl = struct.unpack_from("B", data, off + 24)[0]
                hs = 25
            else:
                eo, np_, pl = struct.unpack_from("<III", data, off)
                nl = struct.unpack_from("B", data, off + 12)[0]
                hs = 13
        except struct.error:
            return None
        if eo == 0:
            return None
        ns = off + hs
        name = data[ns: ns + nl].decode("utf-8", errors="replace")
        ps = ns + nl
        cs = ps + pl
        return int(eo), name, ps, int(np_), cs

    def read_arr(off):
        """Read a typed array property (d/f/i/l). Returns (array, next_off)."""
        try:
            tc = chr(data[off]); off += 1
        except IndexError:
            return None, off
        try:
            if tc in ("d", "f", "i", "l"):
                count, enc, clen = struct.unpack_from("<III", data, off); off += 12
                raw = data[off: off + clen]; off += clen
                if enc == 1:
                    raw = zlib.decompress(raw)
                dtype = {"d": np.float64, "f": np.float32,
                         "i": np.int32,   "l": np.int64}[tc]
                return np.frombuffer(raw, dtype=dtype), off
            elif tc == "D":
                return struct.unpack_from("<d", data, off)[0], off + 8
            elif tc == "F":
                return struct.unpack_from("<f", data, off)[0], off + 4
            elif tc == "I":
                return struct.unpack_from("<i", data, off)[0], off + 4
            elif tc == "L":
                return struct.unpack_from("<q", data, off)[0], off + 8
            elif tc == "S":
                sl = struct.unpack_from("<I", data, off)[0]
                return None, off + 4 + sl
            elif tc == "R":
                rl = struct.unpack_from("<I", data, off)[0]
                return None, off + 4 + rl
            elif tc in ("C", "Y", "b"):
                return None, off + 1
            else:
                return None, off
        except Exception:
            return None, off

    # Walk geometry nodes and collect per-geometry (vertices, poly_indices)
    geometries: list[dict] = []

    def walk_geo_children(off, end, geo):
        while off < end:
            node = read_node(off)
            if node is None:
                break
            eo, name, ps, np_, cs = node
            if name == "Vertices" and np_ >= 1:
                arr, _ = read_arr(ps)
                if isinstance(arr, np.ndarray) and arr.size >= 3:
                    geo["v"] = arr.astype(np.float32).reshape(-1, 3)
            elif name == "PolygonVertexIndex" and np_ >= 1:
                arr, _ = read_arr(ps)
                if isinstance(arr, np.ndarray):
                    geo["pi"] = arr.astype(np.int32)
            off = eo

    def walk_top(off, end, depth=0):
        while off < end:
            node = read_node(off)
            if node is None:
                break
            eo, name, ps, np_, cs = node
            if name == "Geometry" and depth <= 4:
                geo: dict = {}
                walk_geo_children(cs, eo, geo)
                if "v" in geo:
                    geometries.append(geo)
            elif depth < 6:
                walk_top(cs, eo, depth + 1)
            off = eo

    walk_top(27, len(data) - 1)

    if not geometries:
        return None

    # Merge all geometries
    all_verts, all_faces = [], []
    v_offset = 0
    for geo in geometries:
        verts = geo["v"]
        pi = geo.get("pi")
        all_verts.append(verts)
        if pi is not None:
            # Decode FBX polygon vertex indices: negative = end-of-polygon marker
            tris = []
            poly: list[int] = []
            for idx in pi:
                if idx < 0:
                    poly.append(int(-(idx + 1)))
                    if len(poly) >= 3:
                        v0 = poly[0]
                        for i in range(1, len(poly) - 1):
                            tris.append([v0 + v_offset,
                                         poly[i] + v_offset,
                                         poly[i + 1] + v_offset])
                    poly = []
                else:
                    poly.append(int(idx))
            if tris:
                all_faces.append(np.array(tris, dtype=np.int32))
        v_offset += len(verts)

    verts_all = np.concatenate(all_verts, axis=0)
    faces_all = np.concatenate(all_faces, axis=0) if all_faces else None
    return {"vertices": verts_all, "faces": faces_all}


def _render_shaded_software(
    verts: np.ndarray,
    faces: np.ndarray | None,
    size: int,
    base_color: tuple = (110, 150, 200),
) -> bytes:
    """Software Phong-shaded thumbnail using PIL polygon drawing.

    Falls back to point cloud projection when faces are unavailable.
    """
    from PIL import ImageDraw

    if faces is None or len(faces) == 0:
        from .pointcloud_gen import _project_points_to_image
        return _project_points_to_image(verts, size)

    # --- Camera transform: 35° elevation, 45° azimuth ---
    elev = math.radians(35)
    azim = math.radians(45)
    Rx = np.array([[1, 0, 0],
                   [0, math.cos(elev), -math.sin(elev)],
                   [0, math.sin(elev),  math.cos(elev)]], dtype=np.float32)
    Rz = np.array([[math.cos(azim), -math.sin(azim), 0],
                   [math.sin(azim),  math.cos(azim), 0],
                   [0, 0, 1]], dtype=np.float32)
    R = Rx @ Rz

    # Center and normalize
    center = (verts.max(axis=0) + verts.min(axis=0)) / 2
    v = (verts - center).astype(np.float32)
    scale = max(np.abs(v).max(), 1e-6)
    v /= scale

    vr = (R @ v.T).T  # rotated vertices

    # Ortho projection to pixel coords
    mn, mx = vr[:, :2].min(axis=0), vr[:, :2].max(axis=0)
    span = max((mx - mn).max(), 1e-6)
    margin = size * 0.08
    px_scale = (size - 2 * margin) / span

    px = (vr[:, 0] - mn[0]) * px_scale + margin
    py = size - ((vr[:, 1] - mn[1]) * px_scale + margin)
    pz = vr[:, 2]

    # Light direction (in rotated space)
    light = np.array([0.5, 0.7, 1.0], dtype=np.float32)
    light /= np.linalg.norm(light)

    ambient = 0.25
    br, bg_, bb = base_color

    # Build face draw list
    v0 = vr[faces[:, 0]]
    v1 = vr[faces[:, 1]]
    v2 = vr[faces[:, 2]]
    normals = np.cross(v1 - v0, v2 - v0)
    lens = np.linalg.norm(normals, axis=1, keepdims=True)
    lens[lens < 1e-10] = 1.0
    normals /= lens

    diff = np.abs(normals @ light)            # double-sided
    intensity = ambient + (1.0 - ambient) * diff
    intensity = np.clip(intensity, 0, 1)

    depths = (pz[faces[:, 0]] + pz[faces[:, 1]] + pz[faces[:, 2]]) / 3

    # Sort back-to-front (painter's algorithm)
    order = np.argsort(depths)

    img = Image.new("RGB", (size, size), (22, 22, 30))
    draw = ImageDraw.Draw(img)

    for fi in order:
        face = faces[fi]
        pts = [(float(px[vi]), float(py[vi])) for vi in face]
        iv = float(intensity[fi])
        color = (int(br * iv), int(bg_ * iv), int(bb * iv))
        draw.polygon(pts, fill=color)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _extract_trimesh_geometry(scene_or_mesh) -> tuple[np.ndarray, np.ndarray] | None:
    """Extract combined (vertices, faces) from a trimesh Scene or Mesh."""
    import trimesh

    try:
        if hasattr(scene_or_mesh, "geometry") and scene_or_mesh.geometry:
            meshes = [m for m in scene_or_mesh.geometry.values()
                      if hasattr(m, "vertices") and len(m.vertices) > 0]
            if not meshes:
                return None
            combined = trimesh.util.concatenate(meshes)
        else:
            combined = scene_or_mesh

        if not hasattr(combined, "vertices") or len(combined.vertices) == 0:
            return None
        return np.array(combined.vertices, dtype=np.float32), np.array(combined.faces, dtype=np.int32)
    except Exception:
        return None


def generate_mesh_thumbnail(path: Path, size: int) -> bytes:
    """Load 3D mesh and render a shaded thumbnail.

    Pipeline:
      1. trimesh.load → software Phong shading
      2. FBX binary parser (pure Python) → software Phong shading
      3. Fallback icon
    """
    import trimesh

    ext = path.suffix.lstrip(".").lower()
    log.debug("Loading mesh for thumbnail: %s", path)

    # --- 1. Try trimesh ---
    try:
        scene_or_mesh = trimesh.load(str(path), force="scene")
        geo = _extract_trimesh_geometry(scene_or_mesh)
        if geo is not None:
            verts, faces = geo
            return _render_shaded_software(verts, faces, size)
    except Exception as e:
        log.debug("trimesh failed for %s: %s", path, e)

    # --- 2. FBX pure Python fallback ---
    if ext == "fbx":
        result = _parse_fbx_binary(path)
        if result is not None:
            log.debug("FBX binary parse: %d verts, %s faces",
                      len(result["vertices"]),
                      len(result["faces"]) if result["faces"] is not None else "none")
            return _render_shaded_software(
                result["vertices"], result["faces"], size
            )

    # --- 3. Final fallback ---
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
