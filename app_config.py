"""
Central project configuration.

Fields
------
APP_VERSION   : Bump this to propagate version branding everywhere.
APP_EXPIRY    : Set to "YYYY-MM-DD" to hard-expire the app on that date,
                or None / empty string to disable expiry entirely.
"""

import sys as _sys
import os as _os


def get_app_root() -> str:
    """Return the writable application root directory.

    - Frozen EXE: the folder that contains the ``.exe`` file.
    - Dev / source: the project root (same folder as ``app_config.py``).
    """
    if getattr(_sys, "frozen", False):
        return _os.path.dirname(_sys.executable)
    return _os.path.dirname(_os.path.abspath(__file__))


def get_data_path(filename: str = "") -> str:
    """Return the path for a file in the writable ``data/`` directory.

    Works in both development (source tree) and PyInstaller ``--onedir``
    builds:
    - **Frozen EXE**: ``data/`` lives next to the ``.exe`` (placed there by
      ``build.py``'s post-copy step).
    - **Dev / source**: ``data/`` lives at the project root (same folder as
      ``app_config.py``).
    """
    if getattr(_sys, "frozen", False):
        base = _os.path.join(_os.path.dirname(_sys.executable), "data")
    else:
        base = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "data")
    return _os.path.join(base, filename) if filename else base


APP_DISPLAY_NAME = "ERP Estimate Generator"
APP_NAME = "ERP_Estimate"
APP_VERSION = "7.3"
APP_AUTHOR = "Pramod Verma"

# Expiry date in ISO format "YYYY-MM-DD", or None to disable.
APP_EXPIRY = "2026-04-30"
