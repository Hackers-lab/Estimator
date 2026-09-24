"""
ui/auto_updater.py
==================
Background update checker and installer downloader threads with Qt progress dialogs.
"""
from __future__ import annotations
import os
import sys
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import QMessageBox, QProgressDialog, QApplication, QWidget
from app_config import APP_VERSION

class UpdateCheckThread(QThread):
    """Query GitHub Releases off the UI thread. Emits the result dict or None."""
    done = pyqtSignal(object)

    def run(self):
        try:
            from core.updater import check_for_update
            self.done.emit(check_for_update())
        except Exception:
            self.done.emit(None)

class UpdateDownloadThread(QThread):
    """Download the installer off the UI thread, reporting progress."""
    progress = pyqtSignal(int, int)   # downloaded, total
    finished_path = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, url: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._url = url

    def run(self):
        try:
            from core.updater import download_installer
            path = download_installer(
                self._url, lambda d, t: self.progress.emit(d, t)
            )
            self.finished_path.emit(path)
        except Exception as exc:
            self.failed.emit(str(exc))

class AutoUpdaterController:
    """Manages update check triggers and installer launch."""

    def __init__(self, parent_widget: QWidget):
        self.parent = parent_widget
        self._update_check_thread: UpdateCheckThread | None = None
        self._update_dl_thread: UpdateDownloadThread | None = None

    def maybe_check_for_updates_on_startup(self) -> None:
        """Silent background update check run shortly after launch in frozen builds."""
        if not getattr(sys, "frozen", False):
            return
        self.launch_update_check(silent=True)

    def check_for_updates(self) -> None:
        """Manual 'Check for Updates' action."""
        self.launch_update_check(silent=False)

    def launch_update_check(self, silent: bool) -> None:
        self._update_check_thread = UpdateCheckThread(self.parent)
        self._update_check_thread.done.connect(
            lambda info: self._on_update_check_result(info, silent)
        )
        self._update_check_thread.start()

    def _on_update_check_result(self, info: dict | None, silent: bool) -> None:
        if not info:
            if not silent:
                QMessageBox.information(
                    self.parent, "No Updates",
                    f"You are running the latest version (v{APP_VERSION}).",
                )
            return

        notes = info.get("notes", "")
        if len(notes) > 600:
            notes = notes[:600] + "…"
        ans = QMessageBox.question(
            self.parent, "Update Available",
            f"Version {info['version']} is available "
            f"(you have v{APP_VERSION}).\n\n"
            f"{notes}\n\nDownload and install now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ans == QMessageBox.StandardButton.Yes:
            self._download_and_install_update(info)

    def _download_and_install_update(self, info: dict) -> None:
        dlg = QProgressDialog("Downloading update…", "Cancel", 0, 100, self.parent)
        dlg.setWindowTitle("Updating")
        dlg.setMinimumDuration(0)
        dlg.setAutoClose(False)
        dlg.setValue(0)

        self._update_dl_thread = UpdateDownloadThread(info["url"], self.parent)

        def _on_progress(done: int, total: int):
            if total > 0:
                dlg.setMaximum(total)
                dlg.setValue(done)
            else:
                dlg.setMaximum(0)

        def _on_finished(path: str):
            dlg.close()
            try:
                os.startfile(path)  # type: ignore[attr-defined]
            except Exception as exc:
                QMessageBox.critical(self.parent, "Update Failed", f"Could not launch installer:\n{exc}")
                return
            app_inst = QApplication.instance()
            if app_inst is not None:
                app_inst.quit()

        def _on_failed(msg: str):
            dlg.close()
            QMessageBox.critical(self.parent, "Update Failed", f"Download failed:\n{msg}")

        self._update_dl_thread.progress.connect(_on_progress)
        self._update_dl_thread.finished_path.connect(_on_finished)
        self._update_dl_thread.failed.connect(_on_failed)
        dlg.canceled.connect(self._update_dl_thread.terminate)
        self._update_dl_thread.start()
