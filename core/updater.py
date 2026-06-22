"""
core/updater.py
===============
In-app auto-update via GitHub Releases.

Pure standard-library (urllib) so it stays import-light and testable. The PyQt
glue (background thread, progress dialog, prompts) lives in app.py.

Flow
----
1. ``check_for_update()`` queries the repo's latest release, compares the tag
   to ``APP_VERSION`` and returns the new version + installer URL if newer.
2. ``download_installer()`` streams the Setup.exe asset to a temp file.
3. ``run_installer_and_exit()`` launches it and quits so the installer can
   replace the running files, then relaunch the app.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import urllib.request

from app_config import APP_VERSION, APP_NAME, GITHUB_REPO

_API_LATEST = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
_UA = {"User-Agent": f"{APP_NAME}-updater"}


def _parse_version(text: str) -> tuple[int, ...]:
    """'v7.9' / '7.9.1' / 'V8' → tuple of ints; non-numeric parts dropped."""
    nums = re.findall(r"\d+", text or "")
    return tuple(int(n) for n in nums) if nums else (0,)


def is_newer(latest: str, current: str = APP_VERSION) -> bool:
    return _parse_version(latest) > _parse_version(current)


def check_for_update(timeout: float = 8.0) -> dict | None:
    """Return {'version', 'url', 'notes'} if a newer release exists, else None.

    Network/parse errors return None (callers treat "no update" as the safe
    default). ``url`` points at the first ``.exe`` asset (the installer).
    """
    try:
        req = urllib.request.Request(_API_LATEST, headers=_UA)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None

    tag = str(data.get("tag_name") or data.get("name") or "")
    if not tag or not is_newer(tag):
        return None

    installer_url = ""
    for asset in data.get("assets", []):
        name = str(asset.get("name", "")).lower()
        if name.endswith(".exe"):
            installer_url = asset.get("browser_download_url", "")
            break
    if not installer_url:
        return None

    return {
        "version": tag.lstrip("vV"),
        "url": installer_url,
        "notes": str(data.get("body") or "").strip(),
    }


def download_installer(url: str, progress_cb=None) -> str:
    """Stream the installer to a temp file. Returns the local path.

    ``progress_cb(downloaded_bytes, total_bytes)`` is called as data arrives;
    ``total_bytes`` is 0 if the server omits Content-Length.
    """
    req = urllib.request.Request(url, headers=_UA)
    fname = os.path.basename(url) or f"{APP_NAME}_Setup.exe"
    dest = os.path.join(tempfile.gettempdir(), fname)

    with urllib.request.urlopen(req, timeout=30) as resp, open(dest, "wb") as out:
        total = int(resp.headers.get("Content-Length", 0) or 0)
        done = 0
        while True:
            chunk = resp.read(64 * 1024)
            if not chunk:
                break
            out.write(chunk)
            done += len(chunk)
            if progress_cb is not None:
                progress_cb(done, total)
    return dest


def run_installer_and_exit(installer_path: str) -> None:
    """Launch the downloaded installer and quit so it can replace files."""
    if sys.platform == "win32":
        os.startfile(installer_path)  # type: ignore[attr-defined]
    else:  # pragma: no cover - dev fallback
        import subprocess
        subprocess.Popen([installer_path])
    sys.exit(0)
