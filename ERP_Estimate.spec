# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[('data/seed_data.json', 'data'), ('data/rules.json', 'data'), ('data/recipes.json', 'data'), ('data/property_catalog.json', 'data'), ('assets/logo.svg', 'assets'), ('assets/logo.ico', 'assets'), ('assets/HELP.html', 'assets'), ('assets/icons', 'assets/icons')],
    hiddenimports=['openpyxl', 'sqlite3', 'simpleeval'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['groq', 'pydantic', 'pydantic_core', 'httpx', 'httpcore', 'anyio', 'sniffio', 'h11', 'certifi', 'distro', 'jiter', 'numpy', 'PIL', 'Pillow', 'pandas', 'scipy', 'matplotlib', 'IPython', 'tkinter', '_tkinter', 'test', 'unittest', 'pytest'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ERP_Estimate',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['assets\\logo.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='ERP_Estimate',
)
