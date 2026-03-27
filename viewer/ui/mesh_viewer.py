"""Interactive 3D mesh viewer dialog.

Double-clicking a 3D file in the grid opens this dialog.
Controls:
  Left drag   : orbit (rotate)
  Right drag  : zoom
  Middle drag : pan
  Scroll      : zoom
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
    QSizePolicy, QPushButton, QMessageBox,
)

log = logging.getLogger(__name__)

try:
    from OpenGL.GL import (
        glClear, glClearColor, glEnable, glDisable,
        glMatrixMode, glLoadIdentity, glTranslatef, glRotatef, glScalef,
        glBegin, glEnd, glVertex3fv, glNormal3fv, glColor3f,
        glViewport, glDepthFunc, glShadeModel,
        glLightfv, glLightf, glMaterialfv, glMaterialf,
        glColorMaterial, glFogf, glFogfv, glFogi,
        GL_COLOR_BUFFER_BIT, GL_DEPTH_BUFFER_BIT,
        GL_DEPTH_TEST, GL_LEQUAL, GL_LIGHTING,
        GL_LIGHT0, GL_NORMALIZE, GL_SMOOTH,
        GL_AMBIENT, GL_DIFFUSE, GL_SPECULAR, GL_POSITION,
        GL_FRONT_AND_BACK, GL_AMBIENT_AND_DIFFUSE, GL_SHININESS,
        GL_COLOR_MATERIAL, GL_TRIANGLES, GL_MODELVIEW, GL_PROJECTION,
    )
    from OpenGL.GLU import gluPerspective
    _GL_OK = True
except ImportError:
    _GL_OK = False


def _normalize_geometry(verts: np.ndarray) -> tuple[np.ndarray, float]:
    """Center mesh at origin and scale to unit sphere. Returns (verts, scale)."""
    center = (verts.max(axis=0) + verts.min(axis=0)) / 2
    v = verts - center
    scale = float(np.abs(v).max()) or 1.0
    return (v / scale).astype(np.float32), scale


def _compute_vertex_normals(verts: np.ndarray, faces: np.ndarray) -> np.ndarray:
    """Compute smooth per-vertex normals by averaging face normals."""
    normals = np.zeros_like(verts, dtype=np.float32)
    v0 = verts[faces[:, 0]]
    v1 = verts[faces[:, 1]]
    v2 = verts[faces[:, 2]]
    fn = np.cross(v1 - v0, v2 - v0).astype(np.float32)  # face normals (unnorm)
    for i in range(3):
        np.add.at(normals, faces[:, i], fn)
    lens = np.linalg.norm(normals, axis=1, keepdims=True)
    lens[lens < 1e-10] = 1.0
    return normals / lens


class MeshGLWidget(QOpenGLWidget):
    """OpenGL viewport for interactive 3D mesh viewing."""

    def __init__(
        self,
        verts: np.ndarray,
        faces: np.ndarray | None,
        parent=None,
    ) -> None:
        fmt = QSurfaceFormat()
        fmt.setDepthBufferSize(24)
        fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CompatibilityProfile)
        fmt.setSamples(4)

        super().__init__(parent)
        self.setFormat(fmt)

        verts_n, _ = _normalize_geometry(verts)
        self._verts = verts_n
        self._faces = faces
        self._normals: np.ndarray | None = None
        if faces is not None and len(faces) > 0:
            try:
                self._normals = _compute_vertex_normals(verts_n, faces)
            except Exception:
                pass

        # Camera state
        self._rot_x: float = -25.0   # elevation
        self._rot_y: float = 45.0    # azimuth
        self._zoom: float = 2.5
        self._pan_x: float = 0.0
        self._pan_y: float = 0.0

        self._last_pos: QPoint | None = None
        self._button: Qt.MouseButton | None = None

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

        # Main light: warm-white, slightly from above-right
        glLightfv(GL_LIGHT0, GL_POSITION, [1.5, 2.5, 3.0, 0.0])
        glLightfv(GL_LIGHT0, GL_AMBIENT,  [0.25, 0.25, 0.28, 1.0])
        glLightfv(GL_LIGHT0, GL_DIFFUSE,  [0.90, 0.88, 0.85, 1.0])
        glLightfv(GL_LIGHT0, GL_SPECULAR, [0.40, 0.40, 0.40, 1.0])

        # Material
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

        # Camera: translate back by zoom, then rotate
        glTranslatef(self._pan_x, self._pan_y, -self._zoom)
        glRotatef(self._rot_x, 1.0, 0.0, 0.0)
        glRotatef(self._rot_y, 0.0, 1.0, 0.0)

        if self._faces is not None and len(self._faces) > 0:
            self._draw_shaded()
        else:
            self._draw_points()

    def _draw_shaded(self) -> None:
        verts = self._verts
        faces = self._faces
        norms = self._normals

        glColor3f(0.55, 0.70, 0.90)   # steel-blue mesh color
        glBegin(GL_TRIANGLES)
        for fi in range(len(faces)):
            face = faces[fi]
            for vi in face:
                if norms is not None:
                    glNormal3fv(norms[vi])
                glVertex3fv(verts[vi])
        glEnd()

    def _draw_points(self) -> None:
        from OpenGL.GL import glPointSize, GL_POINTS
        verts = self._verts
        mn = verts.min(axis=0)
        mx = verts.max(axis=0)
        rng = mx - mn
        rng[rng < 1e-6] = 1.0

        glDisable(GL_LIGHTING)
        glPointSize(2.0)
        glBegin(GL_POINTS)
        for v in verts[::max(1, len(verts) // 50000)]:
            z_norm = float((v[2] - mn[2]) / rng[2])
            glColor3f(0.0, 0.4 + 0.6 * z_norm, 0.6 + 0.4 * (1 - z_norm))
            glVertex3fv(v)
        glEnd()
        glEnable(GL_LIGHTING)

    # ------------------------------------------------------------------
    # Mouse / wheel input
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
        delta = event.angleDelta().y()
        self._zoom *= 1.0 - delta * 0.001
        self._zoom = max(0.05, min(200.0, self._zoom))
        self.update()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_R:
            self._rot_x, self._rot_y = -25.0, 45.0
            self._zoom, self._pan_x, self._pan_y = 2.5, 0.0, 0.0
            self.update()
        super().keyPressEvent(event)


# ---------------------------------------------------------------------------
# Mesh loading helper
# ---------------------------------------------------------------------------

def _load_mesh(path: Path) -> tuple[np.ndarray, np.ndarray | None]:
    """Load mesh from file. Returns (vertices, faces_or_None)."""
    import trimesh

    # Try trimesh first
    try:
        scene = trimesh.load(str(path), force="scene")
        meshes = []
        if hasattr(scene, "geometry") and scene.geometry:
            meshes = [m for m in scene.geometry.values()
                      if hasattr(m, "vertices") and len(m.vertices) > 0]
        elif hasattr(scene, "vertices") and len(scene.vertices) > 0:
            meshes = [scene]
        if meshes:
            combined = trimesh.util.concatenate(meshes) if len(meshes) > 1 else meshes[0]
            verts = np.array(combined.vertices, dtype=np.float32)
            faces = np.array(combined.faces, dtype=np.int32) if hasattr(combined, "faces") else None
            return verts, faces
    except Exception as e:
        log.debug("trimesh load failed for viewer (%s): %s", path, e)

    # FBX binary fallback
    ext = path.suffix.lstrip(".").lower()
    if ext == "fbx":
        from ..thumbnails.mesh_gen import _parse_fbx_binary
        result = _parse_fbx_binary(path)
        if result:
            return result["vertices"], result["faces"]

    raise ValueError(f"Could not load geometry from {path.name}")


# ---------------------------------------------------------------------------
# Dialog
# ---------------------------------------------------------------------------

class MeshViewerDialog(QDialog):
    """Full-screen interactive 3D viewer dialog."""

    def __init__(self, path: Path, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"3D Viewer — {path.name}")
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
                "Run:  python -m pip install pyopengl\n"
                "then restart the viewer."
            ))
            return

        # Load mesh
        try:
            verts, faces = _load_mesh(path)
        except Exception as e:
            layout.addWidget(QLabel(f"Failed to load mesh:\n{e}"))
            return

        gl_widget = MeshGLWidget(verts, faces, parent=self)
        layout.addWidget(gl_widget, 1)

        # Info bar
        info_layout = QHBoxLayout()
        n_verts = f"{len(verts):,}"
        n_faces = f"{len(faces):,}" if faces is not None else "—"
        info_layout.addWidget(QLabel(
            f"  Vertices: {n_verts}   Faces: {n_faces}"
            f"   |  Left drag: rotate   Right drag / scroll: zoom   Middle drag: pan"
            f"   |  R: reset view"
        ))
        info_layout.addStretch()
        close_btn = QPushButton("Close")
        close_btn.setFixedWidth(80)
        close_btn.clicked.connect(self.close)
        info_layout.addWidget(close_btn)
        layout.addLayout(info_layout)


def open_mesh_viewer(path: Path, parent=None) -> None:
    """Open the interactive 3D viewer for the given file (non-blocking)."""
    dlg = MeshViewerDialog(path, parent)
    dlg.show()   # non-blocking: lets Qt event loop run normally
