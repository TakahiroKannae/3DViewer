"""Format detection: extension → category and display label."""

from __future__ import annotations
from pathlib import Path

# ---------------------------------------------------------------------------
# Format categories
# ---------------------------------------------------------------------------

CATEGORY_3D         = "3D"
CATEGORY_POINTCLOUD = "PointCloud"
CATEGORY_IMAGE      = "Image"
CATEGORY_VIDEO      = "Video"
CATEGORY_DOCUMENT   = "Document"
CATEGORY_GAMEENGINE = "GameEngine"
CATEGORY_UNKNOWN    = "Unknown"

# ext (lower, no dot) → (category, label)
_EXT_MAP: dict[str, tuple[str, str]] = {
    # --- 3D ---
    "fbx":   (CATEGORY_3D, "FBX"),
    "obj":   (CATEGORY_3D, "OBJ"),
    "gltf":  (CATEGORY_3D, "glTF"),
    "glb":   (CATEGORY_3D, "GLB"),
    "abc":   (CATEGORY_3D, "Alembic"),
    "usd":   (CATEGORY_3D, "USD"),
    "usda":  (CATEGORY_3D, "USDA"),
    "usdc":  (CATEGORY_3D, "USDC"),
    "ma":    (CATEGORY_3D, "Maya ASCII"),
    "mb":    (CATEGORY_3D, "Maya Binary"),
    "blend": (CATEGORY_3D, "Blender"),
    "3ds":   (CATEGORY_3D, "3DS"),
    "stl":   (CATEGORY_3D, "STL"),
    "ply":   (CATEGORY_3D, "PLY"),
    "dxf":   (CATEGORY_3D, "DXF"),
    # --- Point cloud ---
    "las":   (CATEGORY_POINTCLOUD, "LAS"),
    "laz":   (CATEGORY_POINTCLOUD, "LAZ"),
    "e57":   (CATEGORY_POINTCLOUD, "E57"),
    "pcd":   (CATEGORY_POINTCLOUD, "PCD"),
    "xyz":   (CATEGORY_POINTCLOUD, "XYZ"),
    "ptx":   (CATEGORY_POINTCLOUD, "PTX"),
    "rcs":   (CATEGORY_POINTCLOUD, "RCS"),
    "rcp":   (CATEGORY_POINTCLOUD, "RCP"),
    # --- Image ---
    "png":   (CATEGORY_IMAGE, "PNG"),
    "jpg":   (CATEGORY_IMAGE, "JPEG"),
    "jpeg":  (CATEGORY_IMAGE, "JPEG"),
    "tiff":  (CATEGORY_IMAGE, "TIFF"),
    "tif":   (CATEGORY_IMAGE, "TIFF"),
    "tga":   (CATEGORY_IMAGE, "TGA"),
    "bmp":   (CATEGORY_IMAGE, "BMP"),
    "gif":   (CATEGORY_IMAGE, "GIF"),
    "webp":  (CATEGORY_IMAGE, "WebP"),
    "avif":  (CATEGORY_IMAGE, "AVIF"),
    "exr":   (CATEGORY_IMAGE, "EXR"),
    "hdr":   (CATEGORY_IMAGE, "HDR"),
    "dpx":   (CATEGORY_IMAGE, "DPX"),
    "psd":   (CATEGORY_IMAGE, "PSD"),
    "psb":   (CATEGORY_IMAGE, "PSB"),
    # --- Video ---
    "mp4":   (CATEGORY_VIDEO, "MP4"),
    "mov":   (CATEGORY_VIDEO, "MOV"),
    "avi":   (CATEGORY_VIDEO, "AVI"),
    "mxf":   (CATEGORY_VIDEO, "MXF"),
    "mkv":   (CATEGORY_VIDEO, "MKV"),
    # --- Documents ---
    "pdf":   (CATEGORY_DOCUMENT, "PDF"),
    "json":  (CATEGORY_DOCUMENT, "JSON"),
    "yaml":  (CATEGORY_DOCUMENT, "YAML"),
    "yml":   (CATEGORY_DOCUMENT, "YAML"),
    "xml":   (CATEGORY_DOCUMENT, "XML"),
    "csv":   (CATEGORY_DOCUMENT, "CSV"),
    "txt":   (CATEGORY_DOCUMENT, "TXT"),
    # --- Game engine ---
    "uasset": (CATEGORY_GAMEENGINE, "UAsset"),
    "umap":   (CATEGORY_GAMEENGINE, "UMap"),
    "prefab": (CATEGORY_GAMEENGINE, "Prefab"),
    "mat":    (CATEGORY_GAMEENGINE, "Material"),
    "meta":   (CATEGORY_GAMEENGINE, "Unity Meta"),
}

# Formats that trimesh can load (used by 3D thumbnail generator)
TRIMESH_LOADABLE = {"obj", "glb", "gltf", "stl", "ply", "3ds", "dxf"}
# Formats that need open3d for loading
OPEN3D_LOADABLE  = {"ply", "pcd", "xyz", "pts"}
# Metadata-only 3D formats
METADATA_ONLY_3D = {"ma", "mb", "blend", "fbx", "abc", "usd", "usda", "usdc"}


def get_format_info(path: str | Path) -> tuple[str, str]:
    """Return (category, label) for the given file path."""
    ext = Path(path).suffix.lstrip(".").lower()
    return _EXT_MAP.get(ext, (CATEGORY_UNKNOWN, ext.upper() or "?"))


def get_category(path: str | Path) -> str:
    return get_format_info(path)[0]


def get_label(path: str | Path) -> str:
    return get_format_info(path)[1]
