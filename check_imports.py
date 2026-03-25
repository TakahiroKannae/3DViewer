#!/usr/bin/env python3
"""Import availability check for 3D CG File Viewer dependencies."""

import sys

results = []

def check(label, fn):
    try:
        fn()
        results.append(("OK", label))
    except ImportError as e:
        results.append(("MISSING", f"{label}: {e}"))
    except Exception as e:
        results.append(("ERROR", f"{label}: {e}"))

check("PySide6",         lambda: __import__("PySide6.QtWidgets"))
check("PySide6.OpenGL",  lambda: __import__("PySide6.QtOpenGL"))
check("trimesh",         lambda: __import__("trimesh"))
check("OpenGL (PyOpenGL)",lambda: __import__("OpenGL.GL"))
check("open3d",          lambda: __import__("open3d"))
check("laspy",           lambda: __import__("laspy"))
check("Pillow (PIL)",    lambda: __import__("PIL.Image"))
check("openexr-python",  lambda: __import__("OpenEXR"))
check("psd-tools",       lambda: __import__("psd_tools"))
check("pymupdf (fitz)",  lambda: __import__("fitz"))
check("numpy",           lambda: __import__("numpy"))
check("PyYAML",          lambda: __import__("yaml"))
check("sqlite3 (stdlib)",lambda: __import__("sqlite3"))
check("subprocess (stdlib)",lambda: __import__("subprocess"))
check("pathlib (stdlib)", lambda: __import__("pathlib"))
check("concurrent.futures",lambda: __import__("concurrent.futures"))

print(f"\n{'='*50}")
print(f"Python {sys.version}")
print(f"{'='*50}")
ok = [l for s, l in results if s == "OK"]
missing = [(s, l) for s, l in results if s != "OK"]

for status, label in results:
    icon = "✓" if status == "OK" else ("✗" if status == "MISSING" else "!")
    print(f"  {icon} {label}")

print(f"\n  {len(ok)}/{len(results)} available")
if missing:
    print(f"\n  Missing/Error:")
    for s, l in missing:
        print(f"    [{s}] {l}")
    sys.exit(1)
else:
    print("\n  All dependencies available!")
