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


def get_user_data_path(filename: str = "") -> str:
    """Return the path for a file in the user's standard AppData directory.

    - Windows: ``%APPDATA%/ERP_Estimate/``
    - Linux: ``~/.local/share/ERP_Estimate/``
    """
    import os
    appdata = os.environ.get("APPDATA")
    if not appdata:
        appdata = os.path.expanduser("~/.local/share")
    
    base = os.path.join(appdata, APP_NAME)
    if not os.path.exists(base):
        try:
            os.makedirs(base, exist_ok=True)
        except OSError:
            # Fallback to local data folder if AppData is not writable
            return get_data_path(filename)
            
    return os.path.join(base, filename) if filename else base


def get_data_path(filename: str = "") -> str:
    """Return the path for a 'factory' file in the application's internal ``data/`` directory.
    """
    if getattr(_sys, "frozen", False):
        base = _os.path.join(_os.path.dirname(_sys.executable), "data")
    else:
        base = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "data")
    return _os.path.join(base, filename) if filename else base


APP_DISPLAY_NAME = "ERP Estimate Generator"
APP_NAME = "ERP_Estimate"
APP_VERSION = "7.5"
APP_AUTHOR = "Pramod Verma"

# Expiry date in ISO format "YYYY-MM-DD", or None to disable.
APP_EXPIRY = "2026-06-30"
