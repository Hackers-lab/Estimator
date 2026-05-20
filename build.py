"""
Build script for ERP Estimate Generator.
Creates a distributable ZIP using PyInstaller (one-folder mode).

Usage:  python build.py
Output: dist/<APP_NAME>_v<APP_VERSION>.zip
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

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)

# ── 1. Clean previous build ─────────────────────────────────────────────────
for d in ("build", "dist", f"{APP_NAME}.spec"):
    p = os.path.join(ROOT, d)
    if os.path.isdir(p):
        shutil.rmtree(p)
    elif os.path.isfile(p):
        os.remove(p)

print("=== Building with PyInstaller ===")

# ── 2. Run PyInstaller ──────────────────────────────────────────────────────
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
    "--hidden-import", "api_secrets",
    "app.py",
]

result = subprocess.run(cmd)
if result.returncode != 0:
    print("PyInstaller build failed!")
    sys.exit(1)

print("=== PyInstaller done ===")

# ── 3. Copy data files to dist folder ───────────────────────────────────────
exe_dir = os.path.join(ROOT, DIST_DIR, APP_NAME)
for fname in DATA_FILES:
    src = os.path.join(ROOT, fname)
    dst = os.path.join(exe_dir, fname)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.exists(src):
        shutil.copy2(src, dst)
        print(f"  Copied {fname}")
    else:
        print(f"  WARNING: {fname} not found, skipping")

# ── 3b. Generate and copy erp_master.db (pre-seeded) ────────────────────────
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

# ── 4. Rename dist folder to versioned name ─────────────────────────────────
final_dir = os.path.join(ROOT, DIST_DIR, FOLDER)
if os.path.exists(final_dir):
    shutil.rmtree(final_dir)
# shutil.move is more robust than os.rename on Windows (avoids AV lock errors)
shutil.move(exe_dir, final_dir)

# ── 5. Create ZIP ───────────────────────────────────────────────────────────
zip_path = os.path.join(ROOT, DIST_DIR, f"{FOLDER}.zip")
print(f"=== Creating {zip_path} ===")

with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
    for dirpath, dirnames, filenames in os.walk(final_dir):
        for fn in filenames:
            abs_file = os.path.join(dirpath, fn)
            arc_name = os.path.join(FOLDER, os.path.relpath(abs_file, final_dir))
            zf.write(abs_file, arc_name)

print("=== Build complete ===\n")
print(f"  Deliverable : {zip_path}")
print(f"  Size        : {os.path.getsize(zip_path) / (1024 * 1024):.1f} MB")
