import os
import sys
import base64 as _b64
import struct as _struct
import urllib.request
from datetime import date as _date
from email.utils import parsedate_to_datetime
from PyQt6.QtWidgets import QApplication, QMessageBox

# This will be imported from app_config at runtime to avoid circular imports
# but we can pass them in or import them here.
try:
    from app_config import APP_DISPLAY_NAME, APP_NAME, APP_EXPIRY
except ImportError:
    APP_DISPLAY_NAME = "Estimator"
    APP_NAME = "Estimator"
    APP_EXPIRY = None

_WM_DIR  = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), APP_NAME)
_WM_FILE = os.path.join(_WM_DIR, "prefs.dat")
_WM_KEY  = 0x5A

def _wm_encode(d: _date) -> bytes:
    raw = _struct.pack(">I", d.toordinal())
    return _b64.b64encode(bytes(b ^ _WM_KEY for b in raw))

def _wm_decode(data: bytes) -> "_date | None":
    try:
        raw = bytes(b ^ _WM_KEY for b in _b64.b64decode(data.strip()))
        return _date.fromordinal(_struct.unpack(">I", raw)[0])
    except Exception:
        return None

def _load_watermark() -> "_date | None":
    try:
        with open(_WM_FILE, "rb") as f:
            return _wm_decode(f.read())
    except Exception:
        return None

def _save_watermark(d: _date) -> None:
    try:
        os.makedirs(_WM_DIR, exist_ok=True)
        with open(_WM_FILE, "wb") as f:
            f.write(_wm_encode(d))
    except Exception:
        pass

def _internet_date() -> "_date | None":
    """Fetch the real date from public HTTP server Date headers."""
    for url in ("https://www.google.com", "https://www.microsoft.com", "https://www.cloudflare.com"):
        try:
            with urllib.request.urlopen(url, timeout=3) as resp:
                hdr = resp.headers.get("Date", "")
                if hdr:
                    return parsedate_to_datetime(hdr).date()
        except Exception:
            continue
    return None

def check_expiry() -> bool:
    """Return False if the app has expired, using system, internet, and watermark dates."""
    if not APP_EXPIRY:
        return True
    try:
        expiry = _date.fromisoformat(APP_EXPIRY)
    except ValueError:
        return True

    system_date   = _date.today()
    internet_date = _internet_date()
    watermark_date = _load_watermark()

    candidates = [d for d in (system_date, internet_date, watermark_date) if d is not None]
    effective_date = max(candidates)
    _save_watermark(effective_date)

    if effective_date > expiry:
        # Ensure a QApplication exists to show the message box
        _app = QApplication.instance() or QApplication(sys.argv)
        QMessageBox.critical(
            None,
            "Application Expired",
            f"<b>{APP_DISPLAY_NAME}</b> expired on <b>{expiry.strftime('%d %b %Y')}</b>.<br>"
            "Please contact the administrator for an updated version.",
        )
        return False
    return True
