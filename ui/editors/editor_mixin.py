"""
ui/editors/editor_mixin.py
===========================
Mixin class providing property-editor panel building for the main application.

This was extracted from app.py to reduce its size. The EditorMixin class is
inherited by EstimateApp, so all methods retain access to ``self`` as before.
"""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QComboBox, QSpinBox, QDoubleSpinBox, QLabel, QCheckBox,
    QLineEdit, QPushButton, QHBoxLayout, QWidget, QFrame, QMenu,
    QInputDialog, QMessageBox, QSizePolicy, QFormLayout
)
from PyQt6.QtCore import Qt, QTimer

from core import defaults
from core import property_catalog
from canvas import SmartPole, SmartStructure, SmartSpan, SmartConsumer

class EditorMixin:
    """Mixin providing all property-editor building and update callbacks.
    
    Expects the host class to provide:
    - self.editor_layout (QFormLayout)
    - self.editor_group (QGroupBox)
    - self.refresh_live_estimate()
    - self.on_selection_changed()
    - self.scene (QGraphicsScene)
    - self.detail_view (bool)
    - self.refresh_signal
    - self._show_advanced_pole_props (bool)
    """

    _LABEL_W = 58  # fixed label width for 4-col grid alignment

    def _add_field_pair(self, label1, widget1, label2=None, widget2=None):
        """Add a row: [label1][input1] or [label1][input1][label2][input2]."""
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        lbl1 = QLabel(label1)
        lbl1.setFixedWidth(self._LABEL_W)
        lbl1.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(lbl1)
        row.addWidget(widget1, 1)
        if label2 is not None and widget2 is not None:
            lbl2 = QLabel(label2)
            lbl2.setFixedWidth(self._LABEL_W)
            lbl2.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            row.addWidget(lbl2)
            row.addWidget(widget2, 1)
        w = QWidget()
        w.setLayout(row)
        self.editor_layout.addRow(w)

    def _build_empty_editor_hint(self):
        hint = QLabel(
            "<b>Mouse</b><br>"
            "• Left drag on blank space: Pan canvas<br>"
            "• Shift + Left drag: Rubber-band multi-select<br>"
            "• Hover on object: Select cursor<br>"
            "• Middle drag / Ctrl + Left drag: Pan canvas<br>"
            "• Wheel: Zoom, Ctrl + Wheel: Fine zoom<br><br>"
            "<b>Keyboard</b><br>"
            "• Esc: Select tool<br>"
            "• F or Ctrl+0: Fit drawing to view<br>"
            "• Ctrl+A: Select all objects"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(
            "QLabel {"
            "  background:#f7fbff;"
            "  border:1px solid #d7e8f6;"
            "  border-radius:6px;"
            "  padding:10px;"
            "  color:#2b3d4f;"
            "  line-height:1.35;"
            "}"
        )
        self.editor_layout.addRow(hint)

    def _add_iron_recipe_picker(self, item):
        """Add a dropdown for selecting a dynamic iron recipe from the database. [ignoring loop detection]"""
        from core import db_gateway as _dbg
        all_recipes = _dbg.get_recipes(item.__class__.__name__)
        
        # Determine prefix filter
        st = getattr(item, "structure_type", None)
        prefix_map = {"DP": "DP_", "TP": "TP_", "4P": "4P_", "DTR": "DTR_"}
        prefix = prefix_map.get(st, "POLE_") if st else "POLE_"
        
        filtered = [r for r in all_recipes if r["recipe_key"].startswith(prefix)]
        recipes = filtered if filtered else all_recipes  # fallback to all if none match
        
        recipe_cb = QComboBox()
        recipe_cb.addItem("None", "None")
        for r in recipes:
            recipe_cb.addItem(r["name"], r["recipe_key"])
        
        current_key = getattr(item, "iron_recipe", "None")
        idx = 0
        for i in range(recipe_cb.count()):
            if recipe_cb.itemData(i) == current_key:
                idx = i
                break
        recipe_cb.setCurrentIndex(idx)
        
        def _on_recipe_changed(index, i=item, cb=recipe_cb):
            val = cb.itemData(index) or "None"
            i.iron_recipe = val
            if hasattr(i, "update_visuals"):
                i.update_visuals()
            self.refresh_live_estimate()
        
        recipe_cb.currentIndexChanged.connect(_on_recipe_changed)
        self._add_field_pair("Iron Recipe:", recipe_cb)

    # ── Pole editor ───────────────────────────────────────────────────────────

    def _build_pole_editor(self, item):
        subtype = getattr(item, "existing_subtype", item.pole_type)
        if item.is_existing:
            self.editor_group.setTitle(f"Existing — {subtype}")
        else:
            self.editor_group.setTitle(f"{item.pole_type} Pole")

        # Existing subtype picker
        if item.is_existing:
            type_cb = QComboBox()
            type_cb.addItems(["LT", "HT", "DP", "TP", "4P", "DTR"])
            type_cb.setCurrentText(subtype)
            type_cb.currentTextChanged.connect(
                lambda t, i=item: self._update_existing_subtype(i, t)
            )
            if subtype == "DTR":
                dtr_cb = QComboBox()
                _xdtr = self._dtr_size_options("SmartPole", "existing_dtr_size")
                dtr_cb.addItems(_xdtr)
                _xval = getattr(item, "existing_dtr_size", "None")
                if _xval not in _xdtr:
                    dtr_cb.addItem(_xval)
                dtr_cb.setCurrentText(_xval)
                dtr_cb.currentTextChanged.connect(
                    lambda t, i=item: self._update_pole(i, "existing_dtr_size", t)
                )
                self._add_field_pair("Ex Type:", type_cb, "DTR Size:", dtr_cb)
            else:
                self._add_field_pair("Ex Type:", type_cb)

            sin_input = QLineEdit(str(getattr(item, "dynamic_props", {}).get("sin", "")))
            sin_input.setPlaceholderText("Optional System ID")
            sin_input.editingFinished.connect(
                lambda i=item, w=sin_input: self._set_dynamic_prop(i, "sin", w.text().strip())
            )
            self._add_field_pair("SIN:", sin_input)

        # Material + Height paired
        pt2_cb = QComboBox()
        pt2_cb.addItems(self._pole_type2_options())
        if item.pole_type2 not in self._pole_type2_options():
            pt2_cb.addItem(item.pole_type2)
        pt2_cb.setCurrentText(item.pole_type2)
        pt2_cb.currentTextChanged.connect(
            lambda t, i=item: self._update_pole_type2(i, t)
        )
        ht_cb = QComboBox()
        ht_cb.addItems(self._height_options(item.pole_type2))
        ht_cb.setCurrentText(item.height)
        self._bind_property_widget(item, "height", ht_cb)
        self._add_field_pair("Material:", pt2_cb, "Height:", ht_cb)

        # Earth + Stay paired
        earth_sp = QSpinBox()
        earth_sp.setRange(0, 10)
        earth_sp.setValue(item.earth_count)
        self._bind_property_widget(item, "earth_count", earth_sp)
        stay_w = QWidget()
        stay_row = QHBoxLayout(stay_w)
        stay_row.setContentsMargins(0, 0, 0, 0)
        stay_row.setSpacing(3)
        stay_sp = QSpinBox()
        stay_sp.setRange(0, 10)
        stay_sp.setValue(item.stay_count)
        stay_sp.valueChanged.connect(
            lambda v, i=item: self._manual_stay(i, v)
        )
        stay_row.addWidget(stay_sp)
        if item.override_auto_stay:
            lock_lbl = QLabel("🔒")
            lock_lbl.setStyleSheet("color:#e67e22; font-size:10px;")
            stay_row.addWidget(lock_lbl)
            reset_btn = QPushButton("Reset")
            reset_btn.setFixedWidth(40)
            reset_btn.setStyleSheet("font-size:10px; padding:2px;")
            reset_btn.clicked.connect(
                lambda _, i=item: self._reset_auto_stay(i)
            )
            stay_row.addWidget(reset_btn)
        self._add_field_pair("Earth:", earth_sp, "Stay:", stay_w)

        self._add_custom_slots_editor(item)

        # Note
        note = QLineEdit(getattr(item, "custom_note", ""))
        note.setPlaceholderText("Custom note...")
        note.textChanged.connect(
            lambda t, i=item: self._update_note(i, t)
        )
        self._add_field_pair("Note:", note)

        self._add_iron_recipe_picker(item)

        # Checkboxes grouped at bottom
        ext_chk = QCheckBox("Extension required")
        ext_chk.setChecked(item.has_extension)
        ext_chk.stateChanged.connect(
            lambda v, i=item: self._toggle_pole_extension(i, v == 2)
        )
        self.editor_layout.addRow(ext_chk)

        if item.has_extension:
            ext_ht = QDoubleSpinBox()
            ext_ht.setRange(1.0, 10.0)
            ext_ht.setSingleStep(0.5)
            ext_ht.setSuffix(" m")
            ext_ht.setValue(item.extension_height)
            self._bind_property_widget(item, "extension_height", ext_ht)
            self._add_field_pair("Ext. Ht:", ext_ht)

        if not item.is_existing and item.pole_type == "LT":
            has_ab = any(
                s.conductor == "AB Cable" and not s.is_service_drop
                for s in item.connected_spans
                if s.scene() is not None
            )
            if has_ab:
                db_chk = QCheckBox("Distribution Box required")
                db_chk.setChecked(getattr(item, "dist_box_required", True))
                db_chk.stateChanged.connect(
                    lambda v, i=item: self._update_pole(i, "dist_box_required", v == 2)
                )
                self.editor_layout.addRow(db_chk)

        adv_chk = QCheckBox("Show advanced controls")
        adv_chk.setChecked(self._show_advanced_pole_props)
        adv_chk.stateChanged.connect(
            lambda v: self._set_pole_advanced_props(v == 2)
        )
        self.editor_layout.addRow(adv_chk)

        if self._show_advanced_pole_props:
            def _make_angle_row(label_text, angle_val, rotate_fn, reset_fn):
                row_w   = QWidget()
                row_lay = QHBoxLayout(row_w)
                row_lay.setContentsMargins(0, 0, 0, 0)
                row_lay.setSpacing(3)
                angle_lbl = QLabel(f"{int(angle_val) if angle_val is not None else 'Auto'}°")
                angle_lbl.setFixedWidth(40)
                angle_lbl.setStyleSheet("color:#555; font-size:10px;")
                ccw_btn = QPushButton("↺ −15°")
                ccw_btn.setFixedWidth(52)
                ccw_btn.setStyleSheet("font-size:10px; padding:2px;")
                ccw_btn.clicked.connect(lambda _, fn=rotate_fn: fn(-15))
                cw_btn  = QPushButton("↻ +15°")
                cw_btn.setFixedWidth(52)
                cw_btn.setStyleSheet("font-size:10px; padding:2px;")
                cw_btn.clicked.connect(lambda _, fn=rotate_fn: fn(+15))
                rst_btn = QPushButton("Auto")
                rst_btn.setFixedWidth(40)
                rst_btn.setStyleSheet("font-size:10px; padding:2px;")
                rst_btn.clicked.connect(reset_fn)
                row_lay.addWidget(angle_lbl)
                row_lay.addWidget(ccw_btn)
                row_lay.addWidget(cw_btn)
                row_lay.addWidget(rst_btn)
                return row_w

            self._add_field_pair("Stay dir:", _make_angle_row(
                "Stay", item.stay_angle_override,
                lambda delta, i=item: self._rotate_stay(i, delta),
                lambda _, i=item: self._reset_stay_angle(i),
            ))
            self._add_field_pair("Earth dir:", _make_angle_row(
                "Earth", item.earth_angle_override,
                lambda delta, i=item: self._rotate_earth(i, delta),
                lambda _, i=item: self._reset_earth_angle(i),
            ))

        if item.is_existing and subtype == "DTR":
            self._build_dtr_augmentation_editor(item)

        self._add_delete_btn(item)

    def _set_pole_advanced_props(self, enabled: bool) -> None:
        self._show_advanced_pole_props = enabled
        self.on_selection_changed()

    # ── Structure editor ──────────────────────────────────────────────────────

    def _build_structure_editor(self, item):
        self.editor_group.setTitle(f"Structure — {item.structure_type}")

        # Structure type + Orientation paired
        st_cb = QComboBox()
        st_cb.addItems(["DP", "TP", "4P", "DTR"])
        st_cb.setCurrentText(item.structure_type)
        st_cb.currentTextChanged.connect(
            lambda t, i=item: self._update_structure_type(i, t)
        )
        orient_cb = QComboBox()
        orient_cb.addItems(["Horizontal", "Vertical"])
        orient_cb.setCurrentText(getattr(item, "orientation", "Horizontal"))
        self._bind_property_widget(item, "orientation", orient_cb)
        self._add_field_pair("Type:", st_cb, "Orient:", orient_cb)

        # DTR size (only when DTR)
        if item.structure_type == "DTR":
            dtr_cb = QComboBox()
            _sdtr = self._dtr_size_options("SmartStructure", "dtr_size")
            dtr_cb.addItems(_sdtr)
            if item.dtr_size not in _sdtr:
                dtr_cb.addItem(item.dtr_size)
            dtr_cb.setCurrentText(item.dtr_size)
            dtr_cb.currentTextChanged.connect(
                lambda t, i=item: self._update_structure(i, "dtr_size", t)
            )
            self._add_field_pair("DTR Size:", dtr_cb)

        # Material + Height paired
        pt2_cb = QComboBox()
        _spt2 = self._pole_type2_options("SmartStructure")
        pt2_cb.addItems(_spt2)
        if item.pole_type2 not in _spt2:
            pt2_cb.addItem(item.pole_type2)
        pt2_cb.setCurrentText(item.pole_type2)
        pt2_cb.currentTextChanged.connect(
            lambda t, i=item: self._update_struct_type2(i, t)
        )
        ht_cb = QComboBox()
        ht_cb.addItems(self._height_options(item.pole_type2, "SmartStructure"))
        ht_cb.setCurrentText(item.height)
        self._bind_property_widget(item, "height", ht_cb)
        self._add_field_pair("Material:", pt2_cb, "Height:", ht_cb)

        # Earth + Stay paired
        earth_sp = QSpinBox()
        earth_sp.setRange(0, 20)
        earth_sp.setValue(item.earth_count)
        self._bind_property_widget(item, "earth_count", earth_sp)
        stay_sp = QSpinBox()
        stay_sp.setRange(0, 20)
        stay_sp.setValue(item.stay_count)
        self._bind_property_widget(item, "stay_count", stay_sp)
        self._add_field_pair("Earth:", earth_sp, "Stay:", stay_sp)

        self._add_custom_slots_editor(item)

        # Note
        note = QLineEdit(getattr(item, "custom_note", ""))
        note.setPlaceholderText("Custom note...")
        note.textChanged.connect(
            lambda t, i=item: self._update_note(i, t)
        )
        self._add_field_pair("Note:", note)

        self._add_iron_recipe_picker(item)

        # Checkboxes at bottom
        ext_chk = QCheckBox("Extension required")
        ext_chk.setChecked(item.has_extension)
        ext_chk.stateChanged.connect(
            lambda v, i=item: self._toggle_struct_extension(i, v == 2)
        )
        self.editor_layout.addRow(ext_chk)

        if item.has_extension:
            ext_ht = QDoubleSpinBox()
            ext_ht.setRange(1.0, 10.0)
            ext_ht.setSingleStep(0.5)
            ext_ht.setSuffix(" m")
            ext_ht.setValue(item.extension_height)
            self._bind_property_widget(item, "extension_height", ext_ht)
            self._add_field_pair("Ext. Ht:", ext_ht)

        if item.structure_type == "DTR":
            kiosk_chk = QCheckBox("Kiosk required")
            kiosk_chk.setChecked(bool(getattr(item, "kiosk_required", True)))
            kiosk_chk.stateChanged.connect(
                lambda v, i=item: self._update_structure(i, "kiosk_required", v == 2)
            )
            self.editor_layout.addRow(kiosk_chk)

        self._add_delete_btn(item)

    # ── Span editor ───────────────────────────────────────────────────────────

    def _build_span_editor(self, item):
        if item.is_service_drop:
            self.editor_group.setTitle("Service Connection")
            self._build_service_drop_editor(item)
        else:
            self.editor_group.setTitle("Span")
            self._build_line_span_editor(item)

        self._add_custom_slots_editor(item)

        note = QLineEdit(getattr(item, "custom_note", ""))
        note.setPlaceholderText("Custom note...")
        note.textChanged.connect(
            lambda t, i=item: self._update_note(i, t)
        )
        self._add_field_pair("Note:", note)
        self._add_delete_btn(item)

    def _build_service_drop_editor(self, item):
        # Phase + Cable size — the service drop carries the actual cable.
        # Both stay in sync with the connected consumer.
        phase_cb = QComboBox()
        phase_cb.addItems(["1 Phase", "3 Phase"])
        phase_cb.setCurrentText(item.phase)
        phase_cb.currentTextChanged.connect(
            lambda t, i=item: self._update_service_drop(i, "phase", t)
        )
        sz_cb = QComboBox()
        _sizes = self._service_cable_sizes(item.phase)
        sz_cb.addItems(_sizes)
        if item.conductor_size not in _sizes:
            sz_cb.addItem(item.conductor_size)
        sz_cb.setCurrentText(item.conductor_size)
        sz_cb.currentTextChanged.connect(
            lambda t, i=item: self._update_service_drop(i, "cable_size", t)
        )
        self._add_field_pair("Phase:", phase_cb, "Cable:", sz_cb)

        len_sp = QSpinBox()
        len_sp.setRange(1, 150)
        len_sp.setValue(int(item.length))
        len_sp.valueChanged.connect(
            lambda v, i=item: self._update_span(i, "length", v)
        )
        self._add_field_pair("Length:", len_sp)

    def _build_line_span_editor(self, item):
        # Status override
        status_cb = QComboBox()
        status_cb.addItems(["Auto", "New", "Existing"])
        curr_override = getattr(item, "override_is_existing", "Auto")
        status_cb.setCurrentText(curr_override)
        status_cb.currentTextChanged.connect(
            lambda v, i=item: self._update_span_override_status(i, v)
        )

        len_sp = QSpinBox()
        len_sp.setRange(1, 500)
        len_sp.setValue(int(item.length))
        len_sp.valueChanged.connect(
            lambda v, i=item: self._update_span(i, "length", v)
        )
        self._add_field_pair("Status:", status_cb, "Length:", len_sp)

        # Voltage
        vl_lbl = QLabel(
            f"{'LT' if item.is_lt_span else 'HT'} (auto)"
        )
        vl_lbl.setStyleSheet("color:#555; font-style:italic;")
        self._add_field_pair("Voltage:", vl_lbl)

        # Conductor + Size paired
        _user = property_catalog.get_user_conductors()
        _user_lt = [c["name"] for c in _user if c["voltage"] in ("LT", "Both")]
        _user_ht = [c["name"] for c in _user if c["voltage"] in ("HT", "Both")]
        _LT_CONDUCTORS = ["AB Cable", "ACSR", "PVC Cable"] + _user_lt
        _HT_CONDUCTORS = ["ACSR", "AB Cable", "PVC Cable"] + _user_ht
        cond_list = _LT_CONDUCTORS if item.is_lt_span else _HT_CONDUCTORS
        cond_cb = QComboBox()
        cond_cb.addItems(cond_list)
        if item.conductor not in cond_list:
            cond_cb.addItem(item.conductor)
        cond_cb.setCurrentText(item.conductor)
        cond_cb.currentTextChanged.connect(
            lambda t, i=item: self._update_conductor(i, t)
        )
        sz_cb = QComboBox()
        sz_cb.addItems(self._conductor_sizes(item.conductor, item.is_lt_span))
        sz_cb.setCurrentText(item.conductor_size)
        sz_cb.currentTextChanged.connect(
            lambda t, i=item: self._update_span(i, "conductor_size", t)
        )
        self._add_field_pair("Cond:", cond_cb, "Size:", sz_cb)

        # Wire count (ACSR)
        if item.conductor == "ACSR":
            wc_cb = QComboBox()
            wc_cb.addItems(["2", "3", "4"])
            wc_cb.setCurrentText(str(item.wire_count))
            wc_cb.currentTextChanged.connect(
                lambda t, i=item: self._update_span(i, "wire_count", t)
            )
            self._add_field_pair("Wires:", wc_cb)

        if item.conductor == "ACSR" and item.is_existing_span and not item.is_service_drop:
            self._build_conductor_augmentation_editor(item)

        # Checkbox at bottom
        cg_chk = QCheckBox("Cattle Guard required")
        cg_chk.setChecked(item.has_cg)
        cg_chk.stateChanged.connect(
            lambda v, i=item: self._update_span_refresh(i, "has_cg", v == 2)
        )
        self.editor_layout.addRow(cg_chk)

    # ── Consumer editor ───────────────────────────────────────────────────────

    def _build_consumer_editor(self, item):
        self.editor_group.setTitle("Consumer")

        # Phase + Cable Size paired
        phase_cb = QComboBox()
        phase_cb.addItems(["1 Phase", "3 Phase"])
        phase_cb.setCurrentText(item.phase)
        phase_cb.currentTextChanged.connect(
            lambda t, i=item: self._update_consumer(i, "phase", t)
        )
        sz_cb = QComboBox()
        sz_cb.addItems(self._service_cable_sizes(item.phase))
        sz_cb.setCurrentText(item.cable_size)
        sz_cb.currentTextChanged.connect(
            lambda t, i=item: self._update_consumer(i, "cable_size", t)
        )
        self._add_field_pair("Phase:", phase_cb, "Cable:", sz_cb)

        self._add_custom_slots_editor(item)

        note = QLineEdit(getattr(item, "custom_note", ""))
        note.setPlaceholderText("Custom note...")
        note.textChanged.connect(
            lambda t, i=item: self._update_note(i, t)
        )
        self._add_field_pair("Note:", note)

        # Checkboxes at bottom
        agency_chk = QCheckBox("Agency Supplied (not WBSEDCL)")
        agency_chk.setChecked(item.agency_supply)
        agency_chk.stateChanged.connect(
            lambda v, i=item: self._update_consumer(i, "agency_supply", v == 2)
        )
        self.editor_layout.addRow(agency_chk)

        cons_chk = QCheckBox("Include cable in estimate (FDS only)")
        cons_chk.setChecked(getattr(item, "consider_cable", False))
        cons_chk.stateChanged.connect(
            lambda v, i=item: self._update_consumer(i, "consider_cable", v == 2)
        )
        self.editor_layout.addRow(cons_chk)

        self._add_delete_btn(item)

    # ── Editor helpers ────────────────────────────────────────────────────────

    def _height_options(self, pole_type2: str, obj_type: str = "SmartPole") -> list[str]:
        """Return height option strings for the given pole_type2 from DB.
        Falls back to hardcoded + extended_options if DB not available.
        """
        try:
            from core import db_gateway as _dbg  # noqa: PLC0415
            opts = _dbg.get_height_options(pole_type2)
            if opts:
                return opts
        except Exception:
            pass
        # Fallback: hardcoded base + extended_options
        base: list[str] = {
            "PCC":    ["8MTR", "9MTR"],
            "STP":    ["9MTR", "9.5MTR", "11MTR"],
            "H-BEAM": ["13MTR"],
        }.get(pole_type2, ["8MTR", "9MTR"])
        from core import property_catalog as _pc
        ext = _pc.get_extended_options(obj_type, f"height__{pole_type2}")
        base_fold = {v.casefold() for v in base}
        return base + [o for o in ext if o.casefold() not in base_fold]

    def _conductor_sizes(self, conductor: str, is_lt: bool) -> list[str]:
        """Return conductor-size option strings from DB.
        Falls back to hardcoded + extended_options if DB not available.
        """
        try:
            from core import db_gateway as _dbg  # noqa: PLC0415
            vc   = "LT" if is_lt else "HT"
            opts = _dbg.get_conductor_options(conductor, vc)
            if opts:
                return opts
        except Exception:
            pass
        # Fallback: hardcoded base + extended_options
        if conductor == "ACSR":
            base = ["30SQMM", "50SQMM"]
        elif conductor == "AB Cable":
            base = (
                ["3CX50+1CX35", "3CX50+1CX16+1CX35", "3CX70+1CX16+1CX50"]
                if is_lt else ["3CX50+1CX150", "3CX95+1CX70"]
            )
        elif conductor == "PVC Cable":
            base = ["10 SQMM", "16 SQMM", "25 SQMM", "50 SQMM", "95 SQMM", "120 SQMM"]
        else:
            base = ["10 SQMM"]
        from core import property_catalog as _pc
        vlt = "lt" if is_lt else "ht"
        ext = _pc.get_extended_options("SmartSpan", f"conductor_size__{vlt}_{conductor}")
        base_fold = {v.casefold() for v in base}
        return base + [o for o in ext if o.casefold() not in base_fold]

    def _service_cable_sizes(self, phase: str) -> list[str]:
        """Cable sizes for consumer / service drop, merged with user-added values."""
        if phase == "1 Phase":
            base = ["4 SQMM", "6 SQMM", "10 SQMM", "16 SQMM", "25 SQMM"]
        else:
            base = ["4 SQMM", "6 SQMM", "10 SQMM", "16 SQMM", "25 SQMM", "50 SQMM"]
        ext = property_catalog.get_extended_options("SmartConsumer", "cable_size")
        base_fold = {v.casefold() for v in base}
        return base + [o for o in ext if o.casefold() not in base_fold]

    @staticmethod
    def _consumer_service_drop(consumer):
        """Return the active service-drop span connected to a consumer, or None."""
        for s in getattr(consumer, "connected_spans", []):
            if getattr(s, "is_service_drop", False) and s.scene() is not None:
                return s
        return None

    @staticmethod
    def _service_drop_consumer(span):
        """Return the SmartConsumer endpoint of a service-drop span, or None."""
        if isinstance(span.p1, SmartConsumer):
            return span.p1
        if isinstance(span.p2, SmartConsumer):
            return span.p2
        return None

    def _pole_type2_options(self, obj_type: str = "SmartPole") -> list[str]:
        """Pole material options (PCC/STP/H-BEAM) merged with user-added values."""
        base = ["PCC", "STP", "H-BEAM"]
        ext  = property_catalog.get_extended_options(obj_type, "pole_type2")
        base_fold = {v.casefold() for v in base}
        return base + [o for o in ext if o.casefold() not in base_fold]

    def _dtr_size_options(
        self, obj_type: str = "SmartStructure", prop: str = "dtr_size"
    ) -> list[str]:
        """DTR kVA size options merged with user-added values."""
        base = ["None", "10KVA", "16KVA", "25KVA", "63KVA", "100KVA", "160KVA"]
        ext  = property_catalog.get_extended_options(obj_type, prop)
        base_fold = {v.casefold() for v in base}
        return base + [o for o in ext if o.casefold() not in base_fold]

    def _add_section_separator(self, title: str) -> None:
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color:#cfcfcf;")
        self.editor_layout.addRow(sep)
        lbl = QLabel(title)
        lbl.setStyleSheet("color:#444; font-weight:bold;")
        self.editor_layout.addRow(lbl)

    def _add_separator_line(self) -> None:
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color:#cfcfcf;")
        self.editor_layout.addRow(sep)

    @staticmethod
    def _parse_kva(size_text: str) -> int:
        txt = str(size_text or "").upper().replace("KVA", "").strip()
        try:
            return int(txt)
        except ValueError:
            return 0

    def _set_dynamic_prop(self, item, key: str, value, refresh_selection: bool = False) -> None:
        props = dict(getattr(item, "dynamic_props", {}) or {})
        if value in (None, "", False):
            props.pop(key, None)
        else:
            props[key] = value
        item.dynamic_props = props
        if hasattr(item, "update_visuals"):
            item.update_visuals()
        self.refresh_live_estimate()
        if refresh_selection:
            QTimer.singleShot(10, self.on_selection_changed)

    def _build_dtr_augmentation_editor(self, item) -> None:
        props = dict(getattr(item, "dynamic_props", {}) or {})

        self._add_section_separator("Augmentation")

        aug_chk = QCheckBox("DTR Augmentation required")
        aug_chk.setChecked(bool(props.get("dtr_aug_required", False)))
        aug_chk.stateChanged.connect(
            lambda s, i=item: self._set_dynamic_prop(i, "dtr_aug_required", s == 2, True)
        )
        self.editor_layout.addRow(aug_chk)

        if not aug_chk.isChecked():
            return

        self._set_dynamic_prop(item, "dtr_return_old_dtr", True)

        existing_size = str(getattr(item, "existing_dtr_size", "None"))
        existing_pt2 = str(getattr(item, "pole_type2", "PCC"))
        existing_h = str(getattr(item, "height", "9MTR"))

        ex_txt = (
            f"Ex {existing_size} S/STN ({existing_pt2} {existing_h}) "
            f"to be augmentated"
        )
        ex_lbl = QLabel(ex_txt)
        ex_lbl.setStyleSheet("color:#6b4e00; font-style:italic;")
        self.editor_layout.addRow("Existing:", ex_lbl)

        new_dtr = QComboBox()
        dtr_sizes = [s for s in self._dtr_size_options("SmartStructure", "dtr_size") if s != "None"]
        new_dtr.addItems(dtr_sizes)
        new_dtr_val = str(props.get("dtr_new_size", existing_size))
        if new_dtr_val not in dtr_sizes:
            new_dtr.addItem(new_dtr_val)
        new_dtr.setCurrentText(new_dtr_val)

        def _on_new_dtr_size_change(text: str, i=item):
            old_kva = self._parse_kva(getattr(i, "existing_dtr_size", "None"))
            new_kva = self._parse_kva(text)
            self._set_dynamic_prop(i, "dtr_new_size", text)
            if old_kva and new_kva and new_kva <= old_kva:
                QMessageBox.warning(
                    self,
                    "DTR size warning",
                    "New DTR size should be greater than existing DTR size for augmentation.",
                )

        new_dtr.currentTextChanged.connect(_on_new_dtr_size_change)
        self.editor_layout.addRow("New DTR Size:", new_dtr)

        struct_change_chk = QCheckBox("S/STN structure change required")
        struct_change_chk.setChecked(bool(props.get("dtr_structure_change_required", False)))
        struct_change_chk.stateChanged.connect(
            lambda s, i=item: self._set_dynamic_prop(i, "dtr_structure_change_required", s == 2, True)
        )
        self.editor_layout.addRow(struct_change_chk)

        if struct_change_chk.isChecked():
            self._set_dynamic_prop(item, "dtr_return_old_pole", True)

            new_pt2 = QComboBox()
            _npt2 = self._pole_type2_options("SmartStructure")
            new_pt2.addItems(_npt2)
            new_pt2_val = str(props.get("dtr_new_pole_type2", existing_pt2))
            if new_pt2_val not in _npt2:
                new_pt2.addItem(new_pt2_val)
            new_pt2.setCurrentText(new_pt2_val)
            new_pt2.currentTextChanged.connect(
                lambda t, i=item: self._set_dynamic_prop(i, "dtr_new_pole_type2", t, True)
            )
            self.editor_layout.addRow("New Pole Type:", new_pt2)

            new_ht = QComboBox()
            new_ht_opts = self._height_options(new_pt2.currentText(), "SmartStructure")
            new_ht.addItems(new_ht_opts)
            new_ht_val = str(props.get("dtr_new_height", existing_h))
            if new_ht_val not in new_ht_opts:
                new_ht.addItem(new_ht_val)
            new_ht.setCurrentText(new_ht_val)
            new_ht.currentTextChanged.connect(
                lambda t, i=item: self._set_dynamic_prop(i, "dtr_new_height", t)
            )
            self.editor_layout.addRow("New Pole Height:", new_ht)

            def _refresh_new_height_options(pt2: str):
                old = new_ht.currentText()
                new_ht.blockSignals(True)
                new_ht.clear()
                opts = self._height_options(pt2, "SmartStructure")
                new_ht.addItems(opts)
                if old in opts:
                    new_ht.setCurrentText(old)
                elif opts:
                    new_ht.setCurrentText(opts[0])
                    self._set_dynamic_prop(item, "dtr_new_height", opts[0])
                new_ht.blockSignals(False)

            new_pt2.currentTextChanged.connect(_refresh_new_height_options)

            ret_iron = QCheckBox("Return old iron to store")
            ret_iron.setChecked(bool(props.get("dtr_return_old_iron", False)))
            ret_iron.stateChanged.connect(
                lambda s, i=item: self._set_dynamic_prop(i, "dtr_return_old_iron", s == 2)
            )
            self.editor_layout.addRow(ret_iron)
        else:
            self._set_dynamic_prop(item, "dtr_return_old_pole", False)

        labour_txt = "Includes labour: dismantling existing DTR and fixing new DTR"
        labour_lbl = QLabel(labour_txt)
        labour_lbl.setStyleSheet("color:#555; font-style:italic;")
        self.editor_layout.addRow("Labour:", labour_lbl)

        self._add_separator_line()

    def _build_conductor_augmentation_editor(self, item) -> None:
        props = dict(getattr(item, "dynamic_props", {}) or {})

        self._add_section_separator("Augmentation")

        aug_chk = QCheckBox("Conductor augmentation required")
        aug_chk.setChecked(bool(props.get("conductor_aug_required", False)))
        aug_chk.stateChanged.connect(
            lambda s, i=item: self._set_dynamic_prop(i, "conductor_aug_required", s == 2, True)
        )
        self.editor_layout.addRow(aug_chk)

        if not aug_chk.isChecked():
            return

        try:
            current_wc = int(str(getattr(item, "wire_count", "3") or "3"))
        except ValueError:
            current_wc = 3
        if current_wc <= 2:
            aug_targets = ["3", "4", "5", "ABC"]
        elif current_wc == 3:
            aug_targets = ["4", "5", "ABC"]
        elif current_wc == 4:
            aug_targets = ["5", "ABC"]
        else:
            aug_targets = ["ABC"]

        to_cb = QComboBox()
        to_cb.addItems(aug_targets)
        to_val = str(props.get("aug_to_config", aug_targets[0]))
        if to_val not in aug_targets:
            to_cb.addItem(to_val)
        to_cb.setCurrentText(to_val)

        def _on_aug_to_change(text: str, i=item):
            self._set_dynamic_prop(i, "aug_to_config", text)
            self._set_dynamic_prop(i, "aug_to_conductor", "AB Cable" if text == "ABC" else "ACSR")

        to_cb.currentTextChanged.connect(_on_aug_to_change)
        self.editor_layout.addRow("Augment To:", to_cb)

        self._add_separator_line()

    def _bind_property_widget(self, item, prop_name: str, widget) -> None:
        """
        DRY helper: connect a QComboBox or QSpinBox/QDoubleSpinBox to an item
        property via setattr, then trigger update_visuals + refresh.
        Use for simple one-to-one property bindings only.
        For properties with cascade side-effects use the dedicated handlers.
        """
        def _apply(val, i=item, p=prop_name):
            setattr(i, p, val)
            if hasattr(i, "update_visuals"):
                i.update_visuals()
            self.refresh_live_estimate()
            QTimer.singleShot(10, self.on_selection_changed)

        if isinstance(widget, QComboBox):
            widget.currentTextChanged.connect(_apply)
        elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
            widget.valueChanged.connect(_apply)

    # ── Right-click context menu ──────────────────────────────────────────────

    def _show_item_context_menu(self, item, global_pos):
        """Show a context menu with inline property editing for a canvas item."""
        menu = QMenu(self)

        def _choice_submenu(title, choices, current, callback):
            """Add a submenu where each choice is a checkable action."""
            sub = menu.addMenu(title)
            for choice in choices:
                act = sub.addAction(str(choice))
                if act is not None:
                    act.setCheckable(True)
                    act.setChecked(str(choice) == str(current))
                    act.triggered.connect(
                        lambda _checked, c=choice: callback(c)
                    )
            return sub

        def _input_action(title, current, callback, min_val=0, max_val=999):
            """Add a single action that opens an input dialog for a numeric value."""
            act = menu.addAction(f"{title}: {current}  ✏")
            act.triggered.connect(
                lambda _checked, t=title, c=current, cb=callback:
                    self._prompt_int(t, c, cb, min_val, max_val)
            )
            return act

        if isinstance(item, SmartPole):
            _choice_submenu(
                "Material", ["PCC", "STP", "H-BEAM"], item.pole_type2,
                lambda v, i=item: self._update_pole_type2(i, v)
            )
            _choice_submenu(
                "Height", self._height_options(item.pole_type2), item.height,
                lambda v, i=item: self._update_pole(i, "height", v)
            )
            _input_action(
                "Earthing Sets", item.earth_count,
                lambda v, i=item: self._update_pole(i, "earth_count", v),
                0, 20
            )
            _input_action(
                "Stay Sets", item.stay_count,
                lambda v, i=item: self._manual_stay(i, v),
                0, 20
            )
            ext_act = menu.addAction("Extension Required")
            if ext_act is not None:
                ext_act.setCheckable(True)
                ext_act.setChecked(item.has_extension)
                ext_act.triggered.connect(
                    lambda checked, i=item: self._toggle_pole_extension(i, checked)
                )
            menu.addSeparator()

        elif isinstance(item, SmartStructure):
            _choice_submenu(
                "Structure Type", ["DP", "TP", "4P", "DTR"], item.structure_type,
                lambda v, i=item: self._update_structure_type(i, v)
            )
            _choice_submenu(
                "Pole Material", ["PCC", "STP", "H-BEAM"], item.pole_type2,
                lambda v, i=item: self._update_struct_type2(i, v)
            )
            _choice_submenu(
                "Height", self._height_options(item.pole_type2, "SmartStructure"), item.height,
                lambda v, i=item: self._update_structure(i, "height", v)
            )
            _input_action(
                "Earthing Sets", item.earth_count,
                lambda v, i=item: self._update_structure(i, "earth_count", v),
                0, 20
            )
            _input_action(
                "Stay Sets", item.stay_count,
                lambda v, i=item: self._update_structure(i, "stay_count", v),
                0, 20
            )
            menu.addSeparator()

        elif isinstance(item, SmartSpan):
            if item.is_service_drop:
                _input_action(
                    "Length (m)", int(item.length),
                    lambda v, i=item: self._update_span(i, "length", v),
                    1, 150
                )
            else:
                _input_action(
                    "Length (m)", int(item.length),
                    lambda v, i=item: self._update_span(i, "length", v),
                    1, 500
                )
                cond_list = (["AB Cable", "ACSR", "PVC Cable"]
                             if item.is_lt_span else ["ACSR", "AB Cable"])
                _choice_submenu(
                    "Conductor", cond_list, item.conductor,
                    lambda v, i=item: self._update_conductor(i, v)
                )
                _choice_submenu(
                    "Size", self._conductor_sizes(item.conductor, item.is_lt_span),
                    item.conductor_size,
                    lambda v, i=item: self._update_span(i, "conductor_size", v)
                )
                if item.conductor == "ACSR":
                    _choice_submenu(
                        "Wire Count", ["2", "3", "4"], str(item.wire_count),
                        lambda v, i=item: self._update_span(i, "wire_count", v)
                    )
                cg_act = menu.addAction("Cattle Guard Required")
                if cg_act is not None:
                    cg_act.setCheckable(True)
                    cg_act.setChecked(item.has_cg)
                    cg_act.triggered.connect(
                        lambda checked, i=item: self._update_span_refresh(i, "has_cg", checked)
                    )
            menu.addSeparator()

        elif isinstance(item, SmartConsumer):
            _choice_submenu(
                "Phase", ["1 Phase", "3 Phase"], item.phase,
                lambda v, i=item: self._update_consumer(i, "phase", v)
            )
            _choice_submenu(
                "Cable Size", self._service_cable_sizes(item.phase), item.cable_size,
                lambda v, i=item: self._update_consumer(i, "cable_size", v)
            )
            agency_act = menu.addAction("Agency Supplied")
            if agency_act is not None:
                agency_act.setCheckable(True)
                agency_act.setChecked(item.agency_supply)
                agency_act.triggered.connect(
                    lambda checked, i=item: self._update_consumer(i, "agency_supply", checked)
                )
            menu.addSeparator()

        del_act = menu.addAction("🗑  Delete")
        if del_act is not None:
            del_act.triggered.connect(lambda: self.delete_item(item))

        menu.exec(global_pos)

    def _prompt_int(self, title, current, callback, min_val=0, max_val=999):
        """Open a simple integer input dialog and call callback if accepted."""
        val, ok = QInputDialog.getInt(
            self, title, f"Enter value for {title}:",
            value=int(current), min=min_val, max=max_val
        )
        if ok:
            callback(val)

    def _add_delete_btn(self, item):
        del_btn = QPushButton("🗑 Delete Selected")
        del_btn.setStyleSheet(
            "background:#ff4c4c; color:white; padding:5px; font-weight:bold;"
        )
        del_btn.clicked.connect(lambda: self.delete_item(item))
        self.editor_layout.addRow(del_btn)

    # =========================================================================
    #  UPDATE CALLBACKS
    # =========================================================================

    def _convert_node(self, item, target: str):
        """Convert a SmartPole to a different type or to a SmartStructure."""
        if target.startswith("—"):
            return

        x, y = item.x(), item.y()
        spans = list(item.connected_spans)

        structure_targets = {"DP Structure": "DP", "TP Structure": "TP",
                             "4P Structure": "4P", "DTR": "DTR"}
        pole_targets      = {"LT Pole": "LT", "HT Pole": "HT"}

        if target in structure_targets:
            # ── Pole → Structure ──────────────────────────────────────────
            st = structure_targets[target]
            new_item = SmartStructure(x, y, self.refresh_signal,
                                     detail_view=self.detail_view)
            new_item.structure_type = st
            new_item.earth_count    = SmartStructure._EARTH_DEFAULTS.get(st, 2)
            new_item.stay_count     = getattr(item, "stay_count", 4)
            new_item.update_visuals()

        elif target in pole_targets:
            # ── Pole type change (LT↔HT or toggle existing) ───────────────
            new_item = SmartPole(x, y, self.refresh_signal,
                                 pole_type=pole_targets[target],
                                 is_existing=item.is_existing,
                                 detail_view=self.detail_view)
            new_item.pole_type2       = item.pole_type2
            new_item.height           = item.height
            new_item.has_extension    = item.has_extension
            new_item.extension_height = item.extension_height
            new_item.earth_count      = item.earth_count
            new_item.stay_count       = item.stay_count
            new_item.override_auto_stay    = item.override_auto_stay
            new_item.stay_angle_override   = item.stay_angle_override
            new_item.earth_angle_override  = item.earth_angle_override
            new_item.custom_note      = item.custom_note
            new_item.update_visuals()
        else:
            return

        # ── Re-wire spans ─────────────────────────────────────────────────
        self.scene.addItem(new_item)
        self.scene.addItem(new_item.label)
        new_item.label.setPos(
            -(new_item.label.boundingRect().width() / 2), 14
        )

        for span in spans:
            if span.p1 is item:
                span.p1 = new_item
            if span.p2 is item:
                span.p2 = new_item
            new_item.connected_spans.append(span)
            span.update_position()

        # ── Remove old item ───────────────────────────────────────────────
        self.scene.removeItem(item.label)
        self.scene.removeItem(item)

        # ── Select new item and refresh ───────────────────────────────────
        self.scene.clearSelection()
        new_item.setSelected(True)
        self._renumber_labels()
        self.refresh_live_estimate()
        QTimer.singleShot(10, self.on_selection_changed)

    def _update_pole(self, item, prop, value):
        setattr(item, prop, value)
        item.update_visuals()
        self.refresh_live_estimate()
        QTimer.singleShot(10, self.on_selection_changed)

    def _update_pole_type2(self, item, value):
        item.pole_type2 = value
        # Reset height to first valid option
        options = self._height_options(value)
        if item.height not in options:
            item.height = options[0]
        item.update_visuals()
        self.refresh_live_estimate()
        QTimer.singleShot(10, self.on_selection_changed)

    def _toggle_pole_extension(self, item, value):
        item.has_extension = value
        item.update_visuals()
        self.refresh_live_estimate()
        QTimer.singleShot(10, self.on_selection_changed)

    def _manual_stay(self, item, value):
        item.override_auto_stay = True
        item.stay_count = value
        item.update_visuals()
        self.refresh_live_estimate()

    def _reset_auto_stay(self, item):
        item.override_auto_stay = False
        self.refresh_live_estimate()
        QTimer.singleShot(10, self.on_selection_changed)

    def _rotate_stay(self, item, delta: float):
        """Rotate stay symbol ±delta degrees; initialise from auto if not overridden."""
        if item.stay_angle_override is None:
            item.stay_angle_override = item._calc_stay_angle()
        item.stay_angle_override = (item.stay_angle_override + delta) % 360
        item.update_visuals()
        self.refresh_live_estimate()
        QTimer.singleShot(10, self.on_selection_changed)

    def _reset_stay_angle(self, item):
        """Clear stay angle override — revert to auto-calculated direction."""
        item.stay_angle_override = None
        item.update_visuals()
        self.refresh_live_estimate()
        QTimer.singleShot(10, self.on_selection_changed)

    def _rotate_earth(self, item, delta: float):
        """Rotate earth symbol ±delta degrees; initialise from auto if not overridden."""
        if item.earth_angle_override is None:
            auto_stay = (item.stay_angle_override
                         if item.stay_angle_override is not None
                         else item._calc_stay_angle())
            item.earth_angle_override = (auto_stay + 180) % 360
        item.earth_angle_override = (item.earth_angle_override + delta) % 360
        item.update_visuals()
        self.refresh_live_estimate()
        QTimer.singleShot(10, self.on_selection_changed)

    def _reset_earth_angle(self, item):
        """Clear earth angle override — revert to auto (opposite of stay)."""
        item.earth_angle_override = None
        item.update_visuals()
        self.refresh_live_estimate()
        QTimer.singleShot(10, self.on_selection_changed)

    def _update_structure(self, item, prop, value):
        setattr(item, prop, value)
        item.update_visuals()
        self.refresh_live_estimate()
        QTimer.singleShot(10, self.on_selection_changed)

    def _update_existing_subtype(self, item, value):
        item.existing_subtype = value
        
        # Sync pole_type with the selected subtype's implied voltage
        if value in ("HT", "DP", "TP", "4P", "DTR"):
            item.pole_type = "HT"
        elif value == "LT":
            item.pole_type = "LT"
            
        item.update_visuals()
        self._renumber_labels()
        # Re-evaluate voltage level & conductor defaults on all connected spans
        for span in getattr(item, "connected_spans", []):
            was_lt = span.is_lt_span
            span.is_lt_span = span._detect_lt()
            if span.is_lt_span != was_lt:
                # Voltage side changed — reset conductor to the new side's default
                _d = defaults.current
                _pfx = "lt_" if span.is_lt_span else "ht_"
                span.conductor      = _d[_pfx + "conductor"]
                span.conductor_size = _d[_pfx + "conductor_size"]
                span.wire_count     = _d[_pfx + "wire_count"]
                span.has_cg = bool(_d.get("ht_cg_required", True)) if not span.is_lt_span else False
            span.update_visuals()
        self.refresh_live_estimate()
        QTimer.singleShot(10, self.on_selection_changed)

    def _update_structure_type(self, item, value):
        item.structure_type = value
        # Reset earth defaults
        d = defaults.current
        earth_defaults = {"DP": d.get("earth_default_dp", 2), "TP": d.get("earth_default_tp", 3), "4P": d.get("earth_default_4p", 4), "DTR": d.get("earth_default_dtr", 5)}
        item.earth_count = earth_defaults.get(value, 2)
        if value != "DTR":
            item.dtr_size = "None"
            item.kiosk_required = False
        else:
            # Default a freshly-converted DTR to 25KVA instead of "None".
            if item.dtr_size in ("None", "", None):
                item.dtr_size = defaults.current.get("struct_dtr_size", "25KVA")
            item.kiosk_required = bool(defaults.current.get("dtr_kiosk_required", True))
            
        _default_recipes = {"DP": "DP_IRON", "TP": "TP_IRON", "4P": "4P_IRON", "DTR": "DTR_IRON"}
        item.iron_recipe = _default_recipes.get(value, item.iron_recipe)
        
        item.update_visuals()
        self.refresh_live_estimate()
        QTimer.singleShot(10, self.on_selection_changed)

    def _update_struct_type2(self, item, value):
        item.pole_type2 = value
        options = self._height_options(value, "SmartStructure")
        if item.height not in options:
            item.height = options[0]
        item.update_visuals()
        self.refresh_live_estimate()
        QTimer.singleShot(10, self.on_selection_changed)

    def _toggle_struct_extension(self, item, value):
        item.has_extension = value
        item.update_visuals()
        self.refresh_live_estimate()
        QTimer.singleShot(10, self.on_selection_changed)

    def _update_span(self, item, prop, value):
        setattr(item, prop, value)
        item.update_visuals()
        self.refresh_live_estimate()

    def _update_span_refresh(self, item, prop, value):
        setattr(item, prop, value)
        item.update_visuals()
        self.refresh_live_estimate()
        QTimer.singleShot(10, self.on_selection_changed)

    def _update_span_override_status(self, item, value):
        item.override_is_existing = value
        self.recalculate_all_span_types()
        item.update_visuals()
        self.refresh_live_estimate()
        QTimer.singleShot(10, self.on_selection_changed)

    def _update_conductor(self, item, conductor):
        item.conductor = conductor
        # Reset size to first valid option
        sizes = self._conductor_sizes(conductor, item.is_lt_span)
        item.conductor_size = sizes[0]
        item.update_visuals()
        self.refresh_live_estimate()
        QTimer.singleShot(50, self.on_selection_changed)

    def _update_consumer(self, item, prop, value):
        setattr(item, prop, value)
        sd = self._consumer_service_drop(item)

        if prop == "phase":
            # Keep cable valid for the new phase, then mirror to the service drop.
            sizes = self._service_cable_sizes(value)
            if item.cable_size not in sizes:
                item.cable_size = sizes[0]
            if sd is not None:
                sd.phase = value
                sd.conductor_size = item.cable_size
                sd.update_visuals()
        elif prop == "cable_size":
            if sd is not None:
                sd.conductor_size = value
                sd.update_visuals()

        item.update_visuals()
        self.refresh_live_estimate()
        QTimer.singleShot(10, self.on_selection_changed)

    def _update_service_drop(self, span, prop, value):
        """Edit a service-drop span and mirror phase/cable back to its consumer."""
        consumer = self._service_drop_consumer(span)
        if prop == "phase":
            span.phase = value
            sizes = self._service_cable_sizes(value)
            if span.conductor_size not in sizes:
                span.conductor_size = sizes[0]
            if consumer is not None:
                consumer.phase = value
                consumer.cable_size = span.conductor_size
                consumer.update_visuals()
        elif prop == "cable_size":
            span.conductor_size = value
            if consumer is not None:
                consumer.cable_size = value
                consumer.update_visuals()
        span.update_visuals()
        self.refresh_live_estimate()
        QTimer.singleShot(10, self.on_selection_changed)

    def _update_note(self, item, text):
        item.custom_note = text
        item.update_visuals()

    def _add_custom_slots_editor(self, item) -> None:
        """
        Render per-object-type custom property fields into the editor panel.

        Values are stored directly by label in ``item.dynamic_props``
        (e.g. ``{"OLD_IRON": "Yes"}``), which the rule engine automatically
        exposes as context variables (e.g. ``OLD_IRON == "Yes"``).
        """
        obj_type = item.__class__.__name__
        entries  = property_catalog.get_custom_entries(obj_type)
        if not entries:
            return

        for entry in entries:
            label   = entry["label"]

            # Simple convention for limiting custom properties to specific pole/structure types:
            if obj_type == "SmartPole":
                if (label.upper().startswith("HT_") or label.upper().startswith("HT ")) and item.pole_type != "HT":
                    continue
                if (label.upper().startswith("LT_") or label.upper().startswith("LT ")) and item.pole_type != "LT":
                    continue
            elif obj_type == "SmartStructure":
                req_st = None
                for st in ("DP", "TP", "4P", "DTR"):
                    if label.upper().startswith(f"{st}_") or label.upper().startswith(f"{st} "):
                        req_st = st
                        break
                if req_st and getattr(item, "structure_type", "") != req_st:
                    continue

            options = entry.get("options", [])
            props   = getattr(item, "dynamic_props", {})

            if options:
                # Choice-type: show combo box
                current_val = str(props.get(label, "None") or "None")
                all_opts    = ["None"] + options
                combo = QComboBox()
                combo.addItems(all_opts)
                if current_val not in all_opts:
                    combo.addItem(current_val)
                combo.setCurrentText(current_val)

                def _on_combo_change(value, i=item, lbl=label):
                    p = getattr(i, "dynamic_props", {})
                    if value == "None":
                        p.pop(lbl, None)
                    else:
                        p[lbl] = value
                    i.dynamic_props = p
                    self.refresh_live_estimate()

                combo.currentTextChanged.connect(_on_combo_change)
                self.editor_layout.addRow(f"{label}:", combo)

            else:
                # Marker-type: show checkbox
                current_val = bool(props.get(label, False))
                chk = QCheckBox(f"Mark as {label}")
                chk.setChecked(current_val)

                def _on_check_change(state, i=item, lbl=label):
                    p = getattr(i, "dynamic_props", {})
                    if state == 2:
                        p[lbl] = True
                    else:
                        p.pop(lbl, None)
                    i.dynamic_props = p
                    self.refresh_live_estimate()

                chk.stateChanged.connect(_on_check_change)
                self.editor_layout.addRow(chk)

    # =========================================================================
    #  DELETION
    # =========================================================================

