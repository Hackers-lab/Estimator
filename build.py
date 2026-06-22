"""
Build script for ERP Estimate Generator.
Creates a distributable ZIP using PyInstaller (one-folder mode) and prunes
unused Qt payload to keep the install small.

Usage:  python build.py
Output: dist/<APP_NAME>_v<APP_VERSION>/        (onedir, what the installer packages)
        dist/<APP_NAME>_v<APP_VERSION>.zip      (portable fallback)
"""

import subprocess
import shutil
import sys
import os
import zipfile


from app_config import APP_NAME, APP_VERSION

DIST_DIR = "dist"
FOLDER   = f"{APP_NAME}_v{APP_VERSION}"

# Data files to copy next to the exe.
# rules.json kept as emergency JSON backup; DB is now the primary config store.
DATA_FILES = ["data/rules.json", "data/recipes.json", "assets/logo.svg", "assets/HELP.html"]

# Python packages we never want pulled into the bundle. Some (numpy/PIL) only
# appear because they happen to be installed in a dev environment; excluding
# them makes the build deterministic and small regardless of the build machine.
EXCLUDE_MODULES = [
    # Removed AI Rule Creator dependency tree
    "groq", "pydantic", "pydantic_core", "httpx", "httpcore",
    "anyio", "sniffio", "h11", "certifi", "distro", "jiter",
    # Heavy scientific / imaging libs the app never uses
    "numpy", "PIL", "Pillow", "pandas", "scipy", "matplotlib", "IPython",
    # GUI toolkit we don't use (PyQt6 only)
    "tkinter", "_tkinter",
    # Test frameworks
    "test", "unittest", "pytest",
]

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)


def prune_qt_payload(internal_dir: str) -> None:
    """Delete unused Qt files to shrink the install.

    Safe to remove:
      - opengl32sw.dll  : software OpenGL fallback (~20 MB). The app uses the
                          raster QGraphicsView paint engine, not OpenGL.
      - translations/   : Qt's .qm locale files (~6 MB). App is English-only.
      - Qt6Pdf.dll      : the standalone QtPdf *viewer* module (~6 MB). PDF
                          export uses QPrinter/QtPrintSupport, which does not
                          depend on QtPdf.
      - surplus image format plugins: keep only the formats actually used
                          (svg for the logo, ico/jpeg/gif; png is built into
                          Qt6Gui). Removes webp/tiff/tga/icns/pdf/wbmp/etc.
    """
    if not os.path.isdir(internal_dir):
        print(f"  [prune] _internal not found at {internal_dir}; skipping")
        return

    qt6 = os.path.join(internal_dir, "PyQt6", "Qt6")
    removed = 0

    def _rm(path: str) -> None:
        nonlocal removed
        if os.path.isdir(path):
            sz = sum(os.path.getsize(os.path.join(dp, f))
                     for dp, _, fs in os.walk(path) for f in fs)
            shutil.rmtree(path, ignore_errors=True)
            removed += sz
            print(f"  [prune] removed dir  {os.path.relpath(path, internal_dir)}")
        elif os.path.isfile(path):
            removed += os.path.getsize(path)
            os.remove(path)
            print(f"  [prune] removed file {os.path.relpath(path, internal_dir)}")

    # Big single items
    _rm(os.path.join(qt6, "bin", "opengl32sw.dll"))
    _rm(os.path.join(qt6, "translations"))
    _rm(os.path.join(qt6, "bin", "Qt6Pdf.dll"))

    # Trim image-format plugins to a small whitelist
    imgfmt = os.path.join(qt6, "plugins", "imageformats")
    if os.path.isdir(imgfmt):
        keep = {"qsvg", "qico", "qjpeg", "qgif"}
        for fn in os.listdir(imgfmt):
            stem = os.path.splitext(fn)[0].lower()
            if stem not in keep:
                _rm(os.path.join(imgfmt, fn))

    print(f"  [prune] reclaimed {removed / (1024 * 1024):.1f} MB")


def main() -> None:
    # ── 1. Clean previous build ─────────────────────────────────────────────
    for d in ("build", "dist", f"{APP_NAME}.spec"):
        p = os.path.join(ROOT, d)
        if os.path.isdir(p):
            shutil.rmtree(p)
        elif os.path.isfile(p):
            os.remove(p)

    print("=== Building with PyInstaller ===")

    # ── 2. Run PyInstaller ──────────────────────────────────────────────────
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onedir",
        "--windowed",
        "--name", APP_NAME,
        "--icon", "assets/logo.ico",
        # Bundle data files into _internal/ so resource_path() and __file__-relative
        # lookups work correctly at runtime.
        "--add-data", "data/seed_data.json;data",
        "--add-data", "data/rules.json;data",
        "--add-data", "data/recipes.json;data",
        "--add-data", "data/property_catalog.json;data",
        "--add-data", "assets/logo.svg;assets",
        "--add-data", "assets/logo.ico;assets",
        "--add-data", "assets/HELP.html;assets",
        "--add-data", "assets/icons;assets/icons",
        # Hidden imports that PyInstaller might miss
        "--hidden-import", "openpyxl",
        "--hidden-import", "sqlite3",
        "--hidden-import", "simpleeval",
    ]
    for mod in EXCLUDE_MODULES:
        cmd += ["--exclude-module", mod]
    cmd.append("app.py")

    result = subprocess.run(cmd)
    if result.returncode != 0:
        print("PyInstaller build failed!")
        sys.exit(1)

    print("=== PyInstaller done ===")

    exe_dir = os.path.join(ROOT, DIST_DIR, APP_NAME)

    # ── 2b. Prune unused Qt payload ──────────────────────────────────────────
    print("=== Pruning unused Qt payload ===")
    prune_qt_payload(os.path.join(exe_dir, "_internal"))

    # ── 3. Copy data files to dist folder ────────────────────────────────────
    for fname in DATA_FILES:
        src = os.path.join(ROOT, fname)
        dst = os.path.join(exe_dir, fname)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if os.path.exists(src):
            shutil.copy2(src, dst)
            print(f"  Copied {fname}")
        else:
            print(f"  WARNING: {fname} not found, skipping")

    # ── 3b. Generate and copy erp_master.db (pre-seeded) ─────────────────────
    print("=== Packaging pre-seeded database ===")
    db_src = os.path.join(ROOT, "erp_master.db")
    if not os.path.exists(db_src):
        print("  erp_master.db not found — generating a fresh seeded copy...")
        sys.path.insert(0, ROOT)
        from core.database import setup_database as _setup_db  # noqa: PLC0415
        _setup_db(db_src)
    db_dst = os.path.join(exe_dir, "erp_master.db")
    shutil.copy2(db_src, db_dst)
    print("  Copied erp_master.db")

    # ── 4. Rename dist folder to versioned name ──────────────────────────────
    final_dir = os.path.join(ROOT, DIST_DIR, FOLDER)
    if os.path.exists(final_dir):
        shutil.rmtree(final_dir)
    # shutil.move is more robust than os.rename on Windows (avoids AV lock errors)
    shutil.move(exe_dir, final_dir)

    # ── 5. Create ZIP ─────────────────────────────────────────────────────────
    zip_path = os.path.join(ROOT, DIST_DIR, f"{FOLDER}.zip")
    print(f"=== Creating {zip_path} ===")

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for dirpath, dirnames, filenames in os.walk(final_dir):
            for fn in filenames:
                abs_file = os.path.join(dirpath, fn)
                arc_name = os.path.join(FOLDER, os.path.relpath(abs_file, final_dir))
                zf.write(abs_file, arc_name)

    print("=== Build complete ===\n")
    print(f"  Folder      : {final_dir}")
    print(f"  Deliverable : {zip_path}")
    print(f"  Size        : {os.path.getsize(zip_path) / (1024 * 1024):.1f} MB")


if __name__ == "__main__":
    main()
