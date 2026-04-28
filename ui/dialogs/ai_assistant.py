"""
ui/dialogs/ai_assistant.py
==========================
AI Rule Assistant dialog — v2.

What's new vs v1
----------------
* Uses the 3-stage ai_rule_parser pipeline (intent → search → propose).
* "Similar rules" panel appears BEFORE calling AI — powered by pure Python
  search so the user can check whether a rule already exists without burning
  an API call.
* Proposals table has Confidence and Reason columns.
* Unverified item names (not found in DB) are highlighted in orange so the
  user knows to fix them before saving.
* SKIP proposals are shown greyed-out with a pre-unchecked checkbox.
"""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTextEdit, QMessageBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QWidget, QCheckBox, QSplitter, QGroupBox, QProgressBar,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor

from core.ai_rule_parser import parse_natural_language_rules, find_similar_rules
from core.property_registry import get_registry


# ─────────────────────────────────────────────────────────────────────────────
# Background worker so the UI doesn't freeze during API calls
# ─────────────────────────────────────────────────────────────────────────────

class _AIWorker(QThread):
    finished = pyqtSignal(list)
    error    = pyqtSignal(str)

    def __init__(self, sentence, obj_type, rules, catalog, history):
        super().__init__()
        self.sentence  = sentence
        self.obj_type  = obj_type
        self.rules     = rules
        self.catalog   = catalog
        self.history   = history

    def run(self):
        try:
            from core.database import get_all_catalog_items
            cat = self.catalog or get_all_catalog_items()
            results = parse_natural_language_rules(
                sentence=self.sentence,
                active_obj_type=self.obj_type,
                registry=get_registry(),
                current_rules=self.rules,
                catalog=cat,
                history=self.history,
            )
            self.finished.emit(results)
        except Exception as exc:
            import traceback; traceback.print_exc()
            self.error.emit(str(exc))


# ─────────────────────────────────────────────────────────────────────────────
# Main dialog
# ─────────────────────────────────────────────────────────────────────────────

class AIAssistantDialog(QDialog):
    """
    AI Assistant that first shows Python-found similar rules,
    then proposes AI operations for the user to review and apply.
    """

    def __init__(
        self,
        parent=None,
        obj_type: str = "SmartPole",
        current_rules: list = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("✨ AI Rule Assistant")
        self.resize(1000, 720)

        self.obj_type          = obj_type
        self.current_rules     = current_rules or []
        self.proposed_ops      = []
        self.instruction_history: list[str] = []
        self._worker: _AIWorker | None = None

        self._build_ui()

    # ─────────────────────────────────────────────────────────────────────────
    # UI construction
    # ─────────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        # Header
        hdr = QLabel(f"AI Rule Assistant  —  {self.obj_type}")
        hdr.setStyleSheet("font-size: 15px; font-weight: bold; color: #185FA5;")
        root.addWidget(hdr)

        desc = QLabel(
            "Describe what a rule should do in plain English.\n"
            "The assistant first searches existing rules, then proposes changes."
        )
        desc.setStyleSheet("font-size: 12px; color: #555;")
        root.addWidget(desc)

        # Input row
        self.prompt_edit = QTextEdit()
        self.prompt_edit.setPlaceholderText(
            "E.g.  'new 25KVA DTR structure will add one 25KVA kiosk'\n"
            "      'update all 8mtr LT pole erection labour formula to 1.2'\n"
            "      'add CG bracket material for HT poles'"
        )
        self.prompt_edit.setFixedHeight(80)
        self.prompt_edit.setStyleSheet(
            "font-size: 13px; padding: 6px; border: 1px solid #ccc; border-radius: 4px;"
        )
        root.addWidget(self.prompt_edit)

        # Button row
        btn_row = QHBoxLayout()
        self.search_btn = QPushButton("🔍  Check similar rules first")
        self.search_btn.setStyleSheet(
            "padding: 7px 14px; border: 1px solid #185FA5; color: #185FA5;"
            "border-radius: 4px; background: white; font-size: 12px;"
        )
        self.search_btn.clicked.connect(self._run_search_only)

        self.run_btn = QPushButton("✨  Generate / Refine with AI")
        self.run_btn.setStyleSheet(
            "background: #5DCAA5; color: white; font-weight: bold;"
            "padding: 7px 16px; border-radius: 4px; font-size: 12px; border: none;"
        )
        self.run_btn.clicked.connect(self._run_ai)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)   # indeterminate
        self.progress.setFixedHeight(6)
        self.progress.setTextVisible(False)
        self.progress.setVisible(False)
        self.progress.setStyleSheet("QProgressBar::chunk { background: #5DCAA5; }")

        btn_row.addWidget(self.search_btn)
        btn_row.addWidget(self.run_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)
        root.addWidget(self.progress)

        # Splitter: similar-rules panel (top) / proposals table (bottom)
        splitter = QSplitter(Qt.Orientation.Vertical)

        # ── Similar rules panel ───────────────────────────────────────────────
        sim_group = QGroupBox("Similar existing rules  (Python search — no AI required)")
        sim_group.setStyleSheet("QGroupBox { font-size: 12px; font-weight: bold; }")
        sim_lay = QVBoxLayout(sim_group)

        self.sim_table = QTableWidget(0, 5)
        self.sim_table.setHorizontalHeaderLabels(
            ["Score", "Type", "Object", "Condition", "Item"]
        )
        hdr = self.sim_table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)
        self.sim_table.setColumnWidth(4, 200)
        self.sim_table.setStyleSheet("font-size: 11px;")
        self.sim_table.setMaximumHeight(180)
        sim_lay.addWidget(self.sim_table)

        self.sim_status = QLabel("Enter your instruction above, then click 'Check similar rules first'.")
        self.sim_status.setStyleSheet("font-size: 11px; color: #888;")
        sim_lay.addWidget(self.sim_status)
        splitter.addWidget(sim_group)

        # ── Proposals table ───────────────────────────────────────────────────
        prop_group = QGroupBox("AI proposed operations  (review, edit checkboxes, then save)")
        prop_group.setStyleSheet("QGroupBox { font-size: 12px; font-weight: bold; }")
        prop_lay = QVBoxLayout(prop_group)

        self.table = QTableWidget(0, 10)
        self.table.setHorizontalHeaderLabels([
            "Apply", "Action", "Conf", "Object",
            "Item name (new)", "Current item", "Condition", "Formula", "Type", "Reason"
        ])
        ph = self.table.horizontalHeader()
        for col, mode in [
            (0, QHeaderView.ResizeMode.ResizeToContents),
            (1, QHeaderView.ResizeMode.ResizeToContents),
            (2, QHeaderView.ResizeMode.ResizeToContents),
            (3, QHeaderView.ResizeMode.ResizeToContents),
            (4, QHeaderView.ResizeMode.Interactive),
            (5, QHeaderView.ResizeMode.Interactive),
            (6, QHeaderView.ResizeMode.Stretch),
            (7, QHeaderView.ResizeMode.ResizeToContents),
            (8, QHeaderView.ResizeMode.ResizeToContents),
            (9, QHeaderView.ResizeMode.Interactive),
        ]:
            ph.setSectionResizeMode(col, mode)
        self.table.setColumnWidth(4, 170)
        self.table.setColumnWidth(5, 140)
        self.table.setColumnWidth(9, 200)
        self.table.setStyleSheet("font-size: 11px;")
        prop_lay.addWidget(self.table)
        splitter.addWidget(prop_group)

        splitter.setSizes([220, 440])
        root.addWidget(splitter, 1)

        # Footer
        footer = QHBoxLayout()
        self.apply_btn = QPushButton("💾  Save selected operations")
        self.apply_btn.setEnabled(False)
        self.apply_btn.setStyleSheet(
            "background: #27ae60; color: white; font-weight: bold;"
            "padding: 8px 16px; border-radius: 4px; font-size: 12px;"
        )
        self.apply_btn.clicked.connect(self.accept)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet(
            "padding: 8px 16px; border: 1px solid #ccc; border-radius: 4px;"
        )
        cancel_btn.clicked.connect(self.reject)

        note = QLabel("⚠  Orange item names are not verified in the database — fix before saving.")
        note.setStyleSheet("font-size: 10px; color: #c87920;")

        footer.addWidget(note)
        footer.addStretch()
        footer.addWidget(cancel_btn)
        footer.addWidget(self.apply_btn)
        root.addLayout(footer)

    # ─────────────────────────────────────────────────────────────────────────
    # Similar-rules search (no AI)
    # ─────────────────────────────────────────────────────────────────────────

    def _run_search_only(self):
        sentence = self.prompt_edit.toPlainText().strip()
        if not sentence:
            QMessageBox.warning(self, "Empty", "Please enter an instruction.")
            return

        from core.ai_rule_parser import find_similar_rules, infer_properties_from_text
        
        # Very basic keyword extraction
        hint_words = [w for w in sentence.lower().split() if len(w) > 3]
        hint = " ".join(hint_words[:6])

        # Use shared inference logic
        props = infer_properties_from_text(sentence)

        matches = find_similar_rules(
            obj_type=self.obj_type,
            properties=props,
            item_name_hint=hint,
            current_rules=self.current_rules,
            top_n=8,
        )

        self.sim_table.setRowCount(0)
        if not matches:
            self.sim_status.setText("No closely matching rules found. You may want to CREATE a new rule.")
        else:
            self.sim_status.setText(
                f"Found {len(matches)} similar rule(s). "
                "If one already covers your intent, consider editing it instead."
            )
            for orig_idx, rule, score in matches:
                row = self.sim_table.rowCount()
                self.sim_table.insertRow(row)

                score_item = QTableWidgetItem(f"{score:.0%}")
                score_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if score >= 0.7:
                    score_item.setForeground(QColor("#1a7a40"))
                elif score >= 0.4:
                    score_item.setForeground(QColor("#c87920"))
                self.sim_table.setItem(row, 0, score_item)
                self.sim_table.setItem(row, 1, QTableWidgetItem(rule.get("type", "")))
                self.sim_table.setItem(row, 2, QTableWidgetItem(rule.get("object", "")))
                self.sim_table.setItem(row, 3, QTableWidgetItem(rule.get("condition", "")))
                self.sim_table.setItem(row, 4, QTableWidgetItem(rule.get("item_name", "")))

    # ─────────────────────────────────────────────────────────────────────────
    # AI generation
    # ─────────────────────────────────────────────────────────────────────────

    def _run_ai(self):
        sentence = self.prompt_edit.toPlainText().strip()
        if not sentence:
            QMessageBox.warning(self, "Empty", "Please enter an instruction.")
            return

        self._set_busy(True)
        self.table.setRowCount(0)
        self.proposed_ops = []

        from core.database import get_all_catalog_items
        cat = get_all_catalog_items()

        self._worker = _AIWorker(
            sentence=sentence,
            obj_type=self.obj_type,
            rules=self.current_rules,
            catalog=cat,
            history=self.instruction_history,
        )
        self._worker.finished.connect(self._on_ai_done)
        self._worker.error.connect(self._on_ai_error)
        self._worker.start()

    def _on_ai_done(self, results: list):
        self._set_busy(False)
        sentence = self.prompt_edit.toPlainText().strip()
        if sentence:
            self.instruction_history.append(sentence)

        if not results:
            QMessageBox.information(self, "No results", "The AI proposed no changes.")
            return

        self.proposed_ops = results
        self._populate_proposals_table()

        # Also refresh the similar-rules panel with the AI-identified intent
        self._run_search_only()

    def _on_ai_error(self, msg: str):
        self._set_busy(False)
        QMessageBox.critical(self, "AI Error", f"An error occurred:\n\n{msg}")

    def _set_busy(self, busy: bool):
        self.run_btn.setEnabled(not busy)
        self.search_btn.setEnabled(not busy)
        self.progress.setVisible(busy)
        self.run_btn.setText("⏳ Working…" if busy else "✨  Generate / Refine with AI")

    # ─────────────────────────────────────────────────────────────────────────
    # Proposals table population
    # ─────────────────────────────────────────────────────────────────────────

    def _populate_proposals_table(self):
        self.table.setRowCount(len(self.proposed_ops))

        for r, op in enumerate(self.proposed_ops):
            action     = str(op.get("action", "CREATE")).upper()
            confidence = op.get("confidence", 0.0)
            obj        = op.get("object", self.obj_type)
            new_item   = op.get("item_name", "")
            condition  = op.get("condition", "True")
            formula    = str(op.get("formula", "1"))
            r_type     = op.get("type", "Material")
            reason     = op.get("reason", "")
            unverified = op.get("item_name_unverified", False)

            # Old item (for UPDATE)
            old_item = ""
            rule_id_raw = op.get("rule_id", "")
            try:
                rule_idx = int(rule_id_raw)
                if 0 <= rule_idx < len(self.current_rules):
                    old_item = self.current_rules[rule_idx].get("item_name", "")
            except (TypeError, ValueError):
                pass

            # ── Checkbox ──────────────────────────────────────────────────────
            cb_w = QWidget()
            cb_l = QHBoxLayout(cb_w)
            cb_l.setContentsMargins(0, 0, 0, 0)
            cb_l.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cb = QCheckBox()
            # Pre-uncheck SKIP operations
            cb.setChecked(action != "SKIP")
            cb_l.addWidget(cb)
            self.table.setCellWidget(r, 0, cb_w)

            # ── Action cell ───────────────────────────────────────────────────
            act_item = QTableWidgetItem(action)
            act_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if action == "CREATE":
                act_item.setForeground(QColor("#1a7a40"))
            elif action == "UPDATE":
                act_item.setForeground(QColor("#185FA5"))
            else:   # SKIP
                act_item.setForeground(QColor("#aaa"))
            self.table.setItem(r, 1, act_item)

            # ── Confidence cell ───────────────────────────────────────────────
            conf_item = QTableWidgetItem(f"{confidence:.0%}")
            conf_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if confidence >= 0.75:
                conf_item.setForeground(QColor("#1a7a40"))
            elif confidence >= 0.45:
                conf_item.setForeground(QColor("#c87920"))
            else:
                conf_item.setForeground(QColor("#c0392b"))
            self.table.setItem(r, 2, conf_item)

            self.table.setItem(r, 3, QTableWidgetItem(obj))

            # ── Item name — orange if not in DB ───────────────────────────────
            name_item = QTableWidgetItem(new_item)
            if unverified:
                name_item.setForeground(QColor("#c87920"))
                name_item.setToolTip("⚠ This item name was not found in the database.")
            self.table.setItem(r, 4, name_item)

            # ── Old item (greyed) ─────────────────────────────────────────────
            old_item_cell = QTableWidgetItem(old_item)
            old_item_cell.setForeground(QColor("#aaa"))
            self.table.setItem(r, 5, old_item_cell)

            self.table.setItem(r, 6, QTableWidgetItem(condition))
            self.table.setItem(r, 7, QTableWidgetItem(formula))
            self.table.setItem(r, 8, QTableWidgetItem(r_type))
            self.table.setItem(r, 9, QTableWidgetItem(reason))

            # Grey out entire row for SKIP
            if action == "SKIP":
                for col in range(1, 10):
                    it = self.table.item(r, col)
                    if it:
                        it.setForeground(QColor("#ccc"))

        if self.proposed_ops:
            self.apply_btn.setEnabled(True)

    # ─────────────────────────────────────────────────────────────────────────
    # Result accessor
    # ─────────────────────────────────────────────────────────────────────────

    def get_selected_operations(self) -> list[dict]:
        """Returns only the operations the user left checked."""
        selected = []
        for r in range(self.table.rowCount()):
            w = self.table.cellWidget(r, 0)
            if w:
                cb = w.findChild(QCheckBox)
                if cb and cb.isChecked() and r < len(self.proposed_ops):
                    selected.append(self.proposed_ops[r])
        return selected
