"""Interactive 3D mesh / point cloud viewer dialog.

Double-clicking a 3D or point cloud file opens this dialog.
Controls:
  Left drag   : orbit (rotate)
  Right drag  : zoom
  Middle drag : pan
  Scroll      : zoom
  R key       : reset view
"""

from __future__ import annotations

import logging
import math
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QSurfaceFormat
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QSizePolicy, QPushButton,
)

log = logging.getLogger(__name__)

_MAX_DISPLAY_POINTS = 500_000   # subsample threshold for interactive display

try:
    from OpenGL.GL import (
        glClear, glClearColor, glEnable, glDisable,
        glMatrixMode, glLoadIdentity, glTranslatef, glRotatef,
        glViewport, glDepthFunc, glShadeModel,
        glLightfv, glMaterialfv, glMaterialf,
        glColorMaterial, glColor3f, glPointSize,
        glEnableClientState, glDisableClientState,
        glVertexPointerf, glNormalPointerf, glColorPointerf,
        glDrawArrays, glDrawElements,
        GL_COLOR_BUFFER_BIT, GL_DEPTH_BUFFER_BIT,
        GL_DEPTH_TEST, GL_LEQUAL, GL_LIGHTING,
        GL_LIGHT0, GL_NORMALIZE, GL_SMOOTH,
        GL_AMBIENT, GL_DIFFUSE, GL_SPECULAR, GL_POSITION,
        GL_FRONT_AND_BACK, GL_AMBIENT_AND_DIFFUSE, GL_SHININESS,
        GL_COLOR_MATERIAL, GL_TRIANGLES, GL_POINTS,
        GL_MODELVIEW, GL_PROJECTION,
        GL_VERTEX_ARRAY, GL_NORMAL_ARRAY, GL_COLOR_ARRAY,
        GL_FLOAT, GL_UNSIGNED_INT,
    )
    from OpenGL.GLU import gluPerspective
    _GL_OK = True
except ImportError:
    _GL_OK = False


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _normalize_geometry(verts: np.ndarray) -> np.ndarray:
    """Center at origin, scale to unit sphere. Returns float32 array."""
    center = (verts.max(axis=0) + verts.min(axis=0)) / 2.0
    v = (verts - center).astype(np.float32)
    scale = float(np.abs(v).max()) or 1.0
    return v / scale


def _compute_vertex_normals(verts: np.ndarray, faces: np.ndarray) -> np.ndarray:
    """Smooth per-vertex normals by accumulating face normals."""
    normals = np.zeros_like(verts, dtype=np.float32)
    v0, v1, v2 = verts[faces[:, 0]], verts[faces[:, 1]], verts[faces[:, 2]]
    fn = np.cross(v1 - v0, v2 - v0).astype(np.float32)
    for i in range(3):
        np.add.at(normals, faces[:, i], fn)
    lens = np.linalg.norm(normals, axis=1, keepdims=True)
    lens[lens < 1e-10] = 1.0
    return (normals / lens).astype(np.float32)


def _height_colors(verts: np.ndarray) -> np.ndarray:
    """Generate height-based blue→cyan→green gradient colors (Nx3 float32)."""
    z = verts[:, 2]
    z_min, z_max = float(z.min()), float(z.max())
    z_range = max(z_max - z_min, 1e-6)
    t = ((z - z_min) / z_range).astype(np.float32)   # 0..1

    r = np.zeros(len(verts), dtype=np.float32)
    g = (0.4 + 0.6 * t).astype(np.float32)
    b = (0.6 + 0.4 * (1.0 - t)).astype(np.float32)
    return np.stack([r, g, b], axis=-1)


def _subsample(pts: np.ndarray, colors: np.ndarray | None,
               max_pts: int) -> tuple[np.ndarray, np.ndarray | None]:
    """Random subsample if point count exceeds max_pts."""
    n = len(pts)
    if n <= max_pts:
        return pts, colors
    idx = np.random.default_rng(42).choice(n, max_pts, replace=False)
    idx.sort()
    return pts[idx], (colors[idx] if colors is not None else None)


# ---------------------------------------------------------------------------
# GL widget
# ---------------------------------------------------------------------------

class MeshGLWidget(QOpenGLWidget):
    """OpenGL viewport — renders shaded mesh OR coloured point cloud."""

    def __init__(
        self,
        verts: np.ndarray,
        faces: np.ndarray | None = None,
        colors: np.ndarray | None = None,   # Nx3 float32, 0-1 range
        parent=None,
    ) -> None:
        fmt = QSurfaceFormat()
        fmt.setDepthBufferSize(24)
        fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CompatibilityProfile)
        fmt.setSamples(4)
        super().__init__(parent)
        self.setFormat(fmt)

        verts_n = _normalize_geometry(verts)

        # For point clouds subsample before storing
        is_cloud = faces is None or len(faces) == 0
        if is_cloud:
            verts_n, colors = _subsample(verts_n, colors, _MAX_DISPLAY_POINTS)

        self._verts   = np.ascontiguousarray(verts_n,   dtype=np.float32)
        self._faces   = (np.ascontiguousarray(faces.flatten(), dtype=np.uint32)
                         if faces is not None and len(faces) > 0 else None)
        self._n_faces = len(faces) if faces is not None else 0

        # Normals for mesh rendering
        self._normals: np.ndarray | None = None
        if faces is not None and len(faces) > 0:
            try:
                n = _compute_vertex_normals(verts_n, faces)
                self._normals = np.ascontiguousarray(n, dtype=np.float32)
            except Exception:
                pass

        # Colours for point cloud rendering
        if colors is not None:
            self._colors = np.ascontiguousarray(colors, dtype=np.float32)
        elif is_cloud:
            self._colors = np.ascontiguousarray(
                _height_colors(verts_n), dtype=np.float32
            )
        else:
            self._colors = None

        self._is_cloud = is_cloud

        # Camera state
        self._rot_x: float = -25.0
        self._rot_y: float = 45.0
        self._zoom:  float = 2.5
        self._pan_x: float = 0.0
        self._pan_y: float = 0.0

        self._last_pos: QPoint | None = None
        self._button:   Qt.MouseButton | None = None

        self.setMinimumSize(400, 400)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    # ------------------------------------------------------------------
    # OpenGL lifecycle
    # ------------------------------------------------------------------

    def initializeGL(self) -> None:
        if not _GL_OK:
            return
        glClearColor(0.12, 0.12, 0.16, 1.0)
        glEnable(GL_DEPTH_TEST)
        glDepthFunc(GL_LEQUAL)
        glEnable(GL_LIGHTING)
        glEnable(GL_LIGHT0)
        glEnable(GL_NORMALIZE)
        glShadeModel(GL_SMOOTH)

        glLightfv(GL_LIGHT0, GL_POSITION, [1.5, 2.5, 3.0, 0.0])
        glLightfv(GL_LIGHT0, GL_AMBIENT,  [0.25, 0.25, 0.28, 1.0])
        glLightfv(GL_LIGHT0, GL_DIFFUSE,  [0.90, 0.88, 0.85, 1.0])
        glLightfv(GL_LIGHT0, GL_SPECULAR, [0.40, 0.40, 0.40, 1.0])

        glEnable(GL_COLOR_MATERIAL)
        glColorMaterial(GL_FRONT_AND_BACK, GL_AMBIENT_AND_DIFFUSE)
        glMaterialfv(GL_FRONT_AND_BACK, GL_SPECULAR, [0.3, 0.3, 0.3, 1.0])
        glMaterialf(GL_FRONT_AND_BACK, GL_SHININESS, 32.0)

    def resizeGL(self, w: int, h: int) -> None:
        if not _GL_OK:
            return
        glViewport(0, 0, w, max(h, 1))
        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        gluPerspective(45.0, w / max(h, 1), 0.001, 1000.0)
        glMatrixMode(GL_MODELVIEW)

    def paintGL(self) -> None:
        if not _GL_OK:
            return
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        glLoadIdentity()
        glTranslatef(self._pan_x, self._pan_y, -self._zoom)
        glRotatef(self._rot_x, 1.0, 0.0, 0.0)
        glRotatef(self._rot_y, 0.0, 1.0, 0.0)

        if self._is_cloud:
            self._draw_points()
        else:
            self._draw_shaded()

    def _draw_shaded(self) -> None:
        """Mesh rendering using vertex / normal arrays + glDrawElements."""
        glColor3f(0.55, 0.70, 0.90)

        glEnableClientState(GL_VERTEX_ARRAY)
        glVertexPointerf(self._verts)

        if self._normals is not None:
            glEnableClientState(GL_NORMAL_ARRAY)
            glNormalPointerf(self._normals)

        glDrawElements(GL_TRIANGLES, len(self._faces),
                       GL_UNSIGNED_INT, self._faces)

        glDisableClientState(GL_VERTEX_ARRAY)
        if self._normals is not None:
            glDisableClientState(GL_NORMAL_ARRAY)

    def _draw_points(self) -> None:
        """Point cloud rendering using vertex + colour arrays."""
        glDisable(GL_LIGHTING)
        glPointSize(2.0)

        glEnableClientState(GL_VERTEX_ARRAY)
        glVertexPointerf(self._verts)

        if self._colors is not None:
            glEnableClientState(GL_COLOR_ARRAY)
            glColorPointerf(self._colors)

        glDrawArrays(GL_POINTS, 0, len(self._verts))

        glDisableClientState(GL_VERTEX_ARRAY)
        if self._colors is not None:
            glDisableClientState(GL_COLOR_ARRAY)

        glEnable(GL_LIGHTING)

    # ------------------------------------------------------------------
    # Mouse / keyboard
    # ------------------------------------------------------------------

    def mousePressEvent(self, event) -> None:
        self._last_pos = event.pos()
        self._button = event.button()

    def mouseMoveEvent(self, event) -> None:
        if self._last_pos is None:
            return
        dx = event.x() - self._last_pos.x()
        dy = event.y() - self._last_pos.y()
        if self._button == Qt.MouseButton.LeftButton:
            self._rot_y += dx * 0.4
            self._rot_x += dy * 0.4
        elif self._button == Qt.MouseButton.RightButton:
            self._zoom *= 1.0 + dy * 0.01
            self._zoom = max(0.05, min(200.0, self._zoom))
        elif self._button == Qt.MouseButton.MiddleButton:
            s = self._zoom * 0.002
            self._pan_x += dx * s
            self._pan_y -= dy * s
        self._last_pos = event.pos()
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        self._last_pos = None
        self._button = None

    def wheelEvent(self, event) -> None:
        self._zoom *= 1.0 - event.angleDelta().y() * 0.001
        self._zoom = max(0.05, min(200.0, self._zoom))
        self.update()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_R:
            self._rot_x, self._rot_y = -25.0, 45.0
            self._zoom, self._pan_x, self._pan_y = 2.5, 0.0, 0.0
            self.update()
        super().keyPressEvent(event)


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def _load_mesh(path: Path) -> tuple[np.ndarray, np.ndarray | None, np.ndarray | None]:
    """Load 3D mesh. Returns (verts, faces_or_None, colors_or_None)."""
    import trimesh

    try:
        scene = trimesh.load(str(path), force="scene")
        meshes = []
        if hasattr(scene, "geometry") and scene.geometry:
            meshes = [m for m in scene.geometry.values()
                      if hasattr(m, "vertices") and len(m.vertices) > 0]
        elif hasattr(scene, "vertices") and len(scene.vertices) > 0:
            meshes = [scene]
        if meshes:
            combined = (trimesh.util.concatenate(meshes)
                        if len(meshes) > 1 else meshes[0])
            verts = np.array(combined.vertices, dtype=np.float32)
            faces = (np.array(combined.faces, dtype=np.int32)
                     if hasattr(combined, "faces") and len(combined.faces) else None)
            return verts, faces, None
    except Exception as e:
        log.debug("trimesh load failed for viewer (%s): %s", path, e)

    # FBX binary fallback
    if path.suffix.lower() == ".fbx":
        from ..thumbnails.mesh_gen import _parse_fbx_binary
        result = _parse_fbx_binary(path)
        if result:
            return result["vertices"], result["faces"], None

    raise ValueError(f"Could not load geometry from {path.name}")


def _load_pointcloud(
    path: Path,
) -> tuple[np.ndarray, np.ndarray | None]:
    """Load point cloud. Returns (points Nx3, colors Nx3 float32 0-1 or None)."""
    ext = path.suffix.lstrip(".").lower()

    if ext in ("las", "laz"):
        import laspy
        las = laspy.read(str(path))
        pts = np.stack([
            las.x.scaled_array(),
            las.y.scaled_array(),
            las.z.scaled_array(),
        ], axis=-1).astype(np.float32)
        colors = None
        try:
            r = np.array(las.red,   dtype=np.float32) / 65535.0
            g = np.array(las.green, dtype=np.float32) / 65535.0
            b = np.array(las.blue,  dtype=np.float32) / 65535.0
            colors = np.stack([r, g, b], axis=-1)
        except AttributeError:
            pass
        return pts, colors

    # open3d handles PCD, XYZ, E57, PTX, ...
    import open3d as o3d
    pcd = o3d.io.read_point_cloud(str(path))
    pts = np.asarray(pcd.points, dtype=np.float32)
    colors = (np.asarray(pcd.colors, dtype=np.float32)
              if pcd.has_colors() else None)
    return pts, colors


# ---------------------------------------------------------------------------
# Dialog
# ---------------------------------------------------------------------------

class MeshViewerDialog(QDialog):
    """Interactive viewer dialog — handles both meshes and point clouds."""

    def __init__(self, path: Path, is_pointcloud: bool = False,
                 parent=None) -> None:
        super().__init__(parent)
        kind = "Point Cloud" if is_pointcloud else "3D"
        self.setWindowTitle(f"{kind} Viewer — {path.name}")
        self.resize(900, 700)
        self.setWindowFlags(
            self.windowFlags() | Qt.WindowType.WindowMaximizeButtonHint
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        if not _GL_OK:
            layout.addWidget(QLabel(
                "PyOpenGL is not installed.\n"
                "Run:  python -m pip install pyopengl\nthen restart."
            ))
            return

        # Load geometry
        try:
            if is_pointcloud:
                pts, colors = _load_pointcloud(path)
                gl_widget = MeshGLWidget(pts, faces=None, colors=colors,
                                         parent=self)
                n_pts = f"{len(pts):,}"
                disp = (f"{min(len(pts), _MAX_DISPLAY_POINTS):,}"
                        if len(pts) > _MAX_DISPLAY_POINTS else n_pts)
                info_text = (
                    f"  Points: {n_pts}"
                    + (f"  (displaying {disp})" if disp != n_pts else "")
                    + ("  • RGB" if colors is not None else "  • height colour")
                    + "   |  Left drag: rotate   Right drag / scroll: zoom"
                      "   Middle drag: pan   |  R: reset"
                )
            else:
                verts, faces, _ = _load_mesh(path)
                gl_widget = MeshGLWidget(verts, faces=faces, parent=self)
                n_verts = f"{len(verts):,}"
                n_faces = f"{len(faces):,}" if faces is not None else "—"
                info_text = (
                    f"  Vertices: {n_verts}   Faces: {n_faces}"
                    "   |  Left drag: rotate   Right drag / scroll: zoom"
                    "   Middle drag: pan   |  R: reset"
                )
        except Exception as e:
            layout.addWidget(QLabel(f"Failed to load:\n{e}"))
            return

        layout.addWidget(gl_widget, 1)

        # Info bar
        info_layout = QHBoxLayout()
        info_layout.addWidget(QLabel(info_text))
        info_layout.addStretch()
        close_btn = QPushButton("Close")
        close_btn.setFixedWidth(80)
        close_btn.clicked.connect(self.close)
        info_layout.addWidget(close_btn)
        layout.addLayout(info_layout)


def open_mesh_viewer(path: Path, parent=None,
                     is_pointcloud: bool = False) -> None:
    """Open the interactive viewer (non-blocking)."""
    dlg = MeshViewerDialog(path, is_pointcloud=is_pointcloud, parent=parent)
    dlg.show()
