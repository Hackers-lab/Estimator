"""
rule_engine.py
==============
Dynamic rule engine for ERP Estimate Generator v5.0.

How it works
------------
1.  For each canvas item, build an ``item_context`` dict of all its
    properties (including global project properties like ``use_uh`` and
    ``project_type``).
2.  Each rule in rules.json specifies:
        object    — which object type it applies to
        condition — a Python expression evaluated against item_context
        formula   — a Python expression that returns the quantity
        type      — "Material" or "Labor"
        item_name — matches the database item_name / task_name column
3.  Safe eval is used: no builtins except ``math`` and ``int``.

Context keys available per object type
---------------------------------------

SmartPole
    object_type, pole_type, pole_type2, is_existing, height (int metres),
    has_extension, extension_height (float), earth_count, stay_count,
    has_cg, ht_spans_count, lt_acsr_count, lt_wire_count,
    has_new_lt_acsr, has_existing_lt_acsr, existing_lt_wire_count,
    use_uh, project_type

SmartStructure
    object_type, structure_type, pole_type2, height (int metres),
    has_extension, extension_height (float), earth_count, stay_count,
    dtr_size, has_cg, use_uh, project_type

SmartSpan
    object_type, conductor, conductor_size, is_service_drop,
    is_existing_span, is_lt_span, wire_count (int), length (int/float),
    aug_type, has_cg, phase, consider_cable, use_uh, project_type

SmartConsumer
    object_type, phase, cable_size, agency_supply, use_uh, project_type

Backward-compatibility notes
-----------------------------
•   Rules written for the old SmartPole / SmartHome / SmartSpan contexts
    will continue to work because the old key names are preserved where
    possible (``wire_count``, ``conductor``, etc.).
•   ``wire_size`` and ``cable_size`` from old rules still resolve because
    we provide them as aliases of ``conductor_size`` for SmartSpan.
•   ``SmartHome`` rules are silently skipped (no SmartHome objects exist
    in v5 drawings). They will not error; they simply produce zero output.
•   ``dtr_size`` is now a SmartStructure property — old rules that checked
    ``object == 'SmartPole' and dtr_size != 'None'`` will no longer fire
    because there are no SmartPole items with dtr_size. Those rules should
    be migrated to ``object == 'SmartStructure'`` in the Ruleset Manager.
"""

from __future__ import annotations
import math
import re
from core.expression_engine import evaluate_condition, evaluate_formula

# Uppercase-only identifiers (A-Z, 0-9, _) with 2+ chars are treated as recipe keys.
# Matches: DP_IRON, POLE_HT_EXT, CG_BRACKET, AB_CABLE_CLAMP, etc.
# Does NOT match Python expressions (lowercase/mixed) or single-char values like "1".
_RECIPE_KEY_RE = re.compile(r'^[A-Z][A-Z0-9_]{1,}$')

# Maps section code → exact item_name in the materials table.
# The sections table label field uses lowercase (75x40) but the materials table
# uses uppercase (75X40).  Using a hardcoded mapping avoids the case mismatch.
_SECTION_TO_DB_NAME: dict[str, str] = {
    "CH_75X40":    "M.S Channel 75X40 mm",
    "CH_100X50":   "M.S Channel 100X50 mm",
    "ANG_65X65X6": "M.S Angle 65X65X6mm",
    "ANG_50X50X6": "M.S Angle 50X50X6mm",
    "FLAT_65X6":   "M.S Flat 65X6 mm",
    "FLAT_50X6":   "M.S Flat 50X6 mm",
}


def _object_label(item) -> str:
    """Human-readable label for an object, for estimate transparency.

    Uses the canvas label (e.g. "PP1"/"DTR1") for nodes; for spans the on-canvas
    label shows length, so we build one from the endpoint labels instead.
    """
    if type(item).__name__ == "SmartSpan":
        def _node(n):
            lbl = getattr(n, "label", None)
            try:
                t = lbl.toPlainText().strip() if lbl is not None else ""
            except Exception:
                t = ""
            return t or "?"
        return (
            f"{getattr(item, 'conductor', '')} span "
            f"{_node(getattr(item, 'p1', None))}–{_node(getattr(item, 'p2', None))}"
        ).strip()
    lbl = getattr(item, "label", None)
    try:
        text = lbl.toPlainText().strip() if lbl is not None else ""
    except Exception:
        text = ""
    return text or type(item).__name__


class DynamicRuleEngine:
    """
    Evaluates a JSON ruleset against all canvas items and accumulates
    material quantities and labour task counts.
    """

    # ── Safe evaluation helpers ───────────────────────────────────────────────

    def evaluate_rule(self, item_context: dict, condition_str: str) -> bool:
        """
        Safely evaluate a condition string.
        Returns False on any exception (rule silently skipped).
        """
        try:
            return evaluate_condition(condition_str, item_context)
        except Exception as exc:
            print(f"[RuleEngine] Condition error '{condition_str}': {exc}")
            return False

    def calculate_qty(self, item_context: dict, formula_str: str) -> float:
        """
        Safely evaluate a quantity formula.
        Returns 0 on any exception.
        """
        try:
            return evaluate_formula(formula_str, item_context)
        except Exception as exc:
            print(f"[RuleEngine] Formula error '{formula_str}': {exc}")
            return 0

    # ── Context builders ──────────────────────────────────────────────────────

    def _height_int(self, height_p) -> int:
        """
        Convert height value to integer metres.
        Handles: "8MTR" -> 8,  8.0 -> 8, "9.5" -> 9, None -> 8
        """
        if height_p is None:
            return 8
        try:
            s = str(height_p).upper().replace("MTR", "").strip()
            return int(float(s))
        except (ValueError, TypeError):
            return 8

    def _build_pole_context(
        self, item: SmartPole,
        use_uh: bool, project_type: str
    ) -> dict:
        # For existing poles use existing_subtype (e.g. "HT") as the
        # effective pole_type so stay/insulator rules fire correctly.
        eff_pole_type = item.pole_type
        dyn = dict(getattr(item, "dynamic_props", {}) or {})
        dtr_aug_required_pole = bool(dyn.get("dtr_aug_required", False))
        ctx: dict = {
            "object_type":      "SmartPole",
            "pole_type":        eff_pole_type,
            "pole_type2":       item.pole_type2,
            "is_existing":      item.is_existing,
            "is_new":           not item.is_existing,   # positive alias
            "existing_subtype": getattr(item, "existing_subtype", item.pole_type),
            "existing_dtr_size": getattr(item, "existing_dtr_size", "None"),
            "height":           self._height_int(item.height),
            "has_extension":    item.has_extension,
            "extension_height": item.extension_height,
            "earth_count":      item.earth_count,
            "stay_count":       item.stay_count,
            "use_uh":           use_uh,
            "project_type":     project_type,
            "work_mode":        getattr(item, "work_mode", "new"),
            "reuse_material":   getattr(item, "reuse_material", False),
            # DTR augmentation fields (used when existing_subtype == 'DTR')
            "dtr_aug_required":             dtr_aug_required_pole,
            "dtr_structure_change_required": bool(dyn.get("dtr_structure_change_required", False)),
            "dtr_new_pole_type2":           str(dyn.get("dtr_new_pole_type2", item.pole_type2)),
            "dtr_new_height":               str(dyn.get("dtr_new_height", item.height)),
            "dtr_size":                     getattr(item, "existing_dtr_size", "None"),
            "dtr_from_size":                getattr(item, "existing_dtr_size", "None"),
            "dtr_to_size":                  str(dyn.get("dtr_new_size", "None")),
            "dtr_return_old_dtr":           bool(dyn.get("dtr_return_old_dtr", dtr_aug_required_pole)),
            "dtr_return_old_pole":          bool(dyn.get("dtr_return_old_pole", bool(dyn.get("dtr_structure_change_required", False)))),
            "dtr_return_old_iron":          bool(dyn.get("dtr_return_old_iron", False)),
            "iron_recipe":                  getattr(item, "iron_recipe", "None"),
        }

        # has_cg — True if any connected span has cattle guard
        ctx["has_cg"] = any(
            getattr(s, "has_cg", False)
            for s in item.connected_spans
        )

        # ht_spans_count — number of NEW (non-existing) ACSR spans connected.
        # Used to classify end pole (==1 → disc) vs through pole (>=2 → pin).
        # Includes spans to/from existing poles so a DTR or new pole adjacent
        # to an existing HT pole is still treated as an end point.
        ctx["ht_spans_count"] = sum(
            1 for s in item.connected_spans
            if s.conductor == "ACSR"
            and not getattr(s, "is_existing_span", False)
        )

        # lt_acsr_count — number of LT ACSR spans connected to this pole
        # (used by LT bracket iron rules on SmartPole)
        lt_acsr_spans = [
            s for s in item.connected_spans
            if s.conductor == "ACSR" and getattr(s, "is_lt_span", False)
        ]
        ctx["lt_acsr_count"] = len(lt_acsr_spans)

        # lt_wire_count — max wire count across LT ACSR spans (for UH D-Iron rule)
        ctx["lt_wire_count"] = max(
            (int(getattr(s, "wire_count", 0)) for s in lt_acsr_spans),
            default=0
        )

        # lt_pvc_count — number of new LT PVC cable distribution spans connected
        # (used for shackle insulator / D-iron / pole clamp rules on PVC cable poles)
        lt_pvc_spans = [
            s for s in item.connected_spans
            if s.conductor == "PVC Cable"
            and getattr(s, "is_lt_span", False)
            and not getattr(s, "is_existing_span", False)
            and not getattr(s, "is_service_drop", False)
        ]
        ctx["lt_pvc_count"] = len(lt_pvc_spans)

        # ── Shackle insulator context for new poles jointing existing lines ─
        # has_existing_lt_acsr — True when connected to at least one existing LT ACSR span
        # has_new_lt_acsr      — True when connected to at least one new LT ACSR span
        # existing_lt_wire_count — wire count of the existing LT ACSR span (max, if multiple)
        new_lt_acsr_spans      = [s for s in lt_acsr_spans if not getattr(s, "is_existing_span", False)]
        existing_lt_acsr_spans = [s for s in lt_acsr_spans if getattr(s, "is_existing_span", False)]
        ctx["has_new_lt_acsr"]          = len(new_lt_acsr_spans) > 0
        ctx["has_existing_lt_acsr"]     = len(existing_lt_acsr_spans) > 0
        ctx["existing_lt_wire_count"]   = max(
            (int(getattr(s, "wire_count", 0)) for s in existing_lt_acsr_spans),
            default=0
        )

        # AB cable context — distribution box / clamp / IPC rules
        ab_spans = [
            s for s in item.connected_spans
            if s.conductor == "AB Cable"
            and not getattr(s, "is_service_drop", False)
        ]
        ab_new_spans = [
            s for s in ab_spans
            if not getattr(s, "is_existing_span", False)
        ]
        ab_cable_count = len(ab_spans)
        if ab_cable_count == 0:
            ab_needs_dead_end   = False
            ab_needs_suspension = False
        elif ab_cable_count == 1:
            ab_needs_dead_end   = True
            ab_needs_suspension = False
        else:
            my_x, my_y = item.x(), item.y()
            span_angles = []
            for s in ab_spans:
                other = s.p1 if s.p2 is item else s.p2
                dx = other.x() - my_x
                dy = other.y() - my_y
                mag = math.hypot(dx, dy)
                if mag > 0:
                    span_angles.append(math.atan2(dy, dx))
            max_dev = 0.0
            for i in range(len(span_angles)):
                for j in range(i + 1, len(span_angles)):
                    diff = abs(span_angles[i] - span_angles[j])
                    if diff > math.pi:
                        diff = 2 * math.pi - diff
                    deviation = abs(math.pi - diff)
                    max_dev = max(max_dev, math.degrees(deviation))
            ab_needs_dead_end   = max_dev > 65
            ab_needs_suspension = not ab_needs_dead_end
        ctx["ab_cable_count"]      = ab_cable_count
        ctx["ab_new_cable_count"]  = len(ab_new_spans)
        ctx["ab_needs_dead_end"]   = ab_needs_dead_end
        ctx["ab_needs_suspension"] = ab_needs_suspension
        ctx["dist_box_required"]   = getattr(item, "dist_box_required", True)

        ctx.update(getattr(item, "dynamic_props", {}))
        return ctx

    def _build_structure_context(
        self, item: SmartStructure,
        use_uh: bool, project_type: str
    ) -> dict:
        dyn = dict(getattr(item, "dynamic_props", {}) or {})
        dtr_aug_required = bool(dyn.get("dtr_aug_required", False))
        ht_spans_count = sum(
            1 for s in getattr(item, "connected_spans", [])
            if s.conductor == "ACSR"
            and not getattr(s, "is_existing_span", False)
        )
        ctx: dict = {
            "object_type":      "SmartStructure",
            "structure_type":   item.structure_type,
            "pole_type2":       item.pole_type2,
            "height":           self._height_int(item.height),
            "orientation":      getattr(item, "orientation", "Horizontal"),
            "has_extension":    item.has_extension,
            "extension_height": item.extension_height,
            "earth_count":      item.earth_count,
            "stay_count":       item.stay_count,
            "dtr_size":         item.dtr_size,
            "kiosk_required":   getattr(item, "kiosk_required", True),
            "ht_spans_count":   ht_spans_count,
            "dtr_aug_required": dtr_aug_required,
            "dtr_from_size":    item.dtr_size,
            "dtr_to_size":      str(dyn.get("dtr_new_size", "None")),
            "dtr_structure_change_required": bool(dyn.get("dtr_structure_change_required", False)),
            "dtr_new_pole_type2": str(dyn.get("dtr_new_pole_type2", item.pole_type2)),
            "dtr_new_height":   str(dyn.get("dtr_new_height", item.height)),
            "dtr_return_old_dtr": bool(dyn.get("dtr_return_old_dtr", dtr_aug_required)),
            "dtr_return_old_pole": bool(
                dyn.get("dtr_return_old_pole", bool(dyn.get("dtr_structure_change_required", False)))
            ),
            "dtr_return_old_iron": bool(dyn.get("dtr_return_old_iron", False)),
            "use_uh":           use_uh,
            "project_type":     project_type,
            "iron_recipe":      getattr(item, "iron_recipe", "None"),
        }

        # has_cg — True if any connected span has cattle guard
        ctx["has_cg"] = any(
            getattr(s, "has_cg", False)
            for s in getattr(item, "connected_spans", [])
        )

        ctx.update(dyn)
        return ctx

    def _build_span_context(
        self, item: SmartSpan,
        use_uh: bool, project_type: str
    ) -> dict:
        dyn = dict(getattr(item, "dynamic_props", {}) or {})
        cond_aug_required = bool(dyn.get("conductor_aug_required", False))
        # wire_count as int — old rules used int(wire_count)
        try:
            wire_count_int = int(item.wire_count)
        except (ValueError, TypeError):
            wire_count_int = 3

        ctx: dict = {
            "object_type":      "SmartSpan",
            "conductor":        item.conductor,
            "conductor_size":   item.conductor_size,
            # Backward-compat aliases so old rules still work
            "wire_size":        item.conductor_size,
            "cable_size":       item.conductor_size,
            "is_service_drop":  item.is_service_drop,
            "is_distribution_span": not item.is_service_drop,   # positive alias
            "is_existing_span": item.is_existing_span,
            "is_new_span":      not item.is_existing_span,       # positive alias
            "is_lt_span":       item.is_lt_span,
            "is_ht_span":       not item.is_lt_span,             # positive alias
            "wire_count":       wire_count_int,
            "length":           item.length,
            "aug_type":         item.aug_type,
            "has_cg":           item.has_cg,
            "phase":            item.phase,
            "consider_cable":   item.consider_cable,
            "conductor_aug_required": cond_aug_required,
            "aug_from_config":  str(
                dyn.get("aug_from_config", {
                    "2": "1P2W",
                    "3": "2P3W",
                    "4": "3P4W",
                }.get(str(getattr(item, "wire_count", "3")), "2P3W"))
            ),
            "aug_to_config":    str(dyn.get("aug_to_config", "")),
            "aug_to_conductor": str(dyn.get("aug_to_conductor", "")),
            "use_uh":           use_uh,
            "project_type":     project_type,
        }
        ctx.update(dyn)
        return ctx

    def _build_consumer_context(
        self, item: SmartConsumer,
        use_uh: bool, project_type: str
    ) -> dict:
        service_span = next(
            (s for s in getattr(item, "connected_spans", [])
             if getattr(s, "is_service_drop", False)),
            None,
        )
        service_length = service_span.length if service_span else 20
        ctx: dict = {
            "object_type":       "SmartConsumer",
            # Keep SmartHome alias so any legacy rules survive
            "object_type_alias": "SmartHome",
            "phase":             item.phase,
            "cable_size":        item.cable_size,
            "agency_supply":     item.agency_supply,
            "consider_cable":    getattr(item, "consider_cable", False),
            "service_length":    service_length,
            "use_uh":            use_uh,
            "project_type":      project_type,
        }
        ctx.update(getattr(item, "dynamic_props", {}))
        return ctx

    # ── Main processing entry point ───────────────────────────────────────────

    def process(
        self,
        canvas_items: list,
        rules: list,
        use_uh: bool = False,
        project_type: str = "NSC",
        provenance_out: dict | None = None,
    ) -> tuple[dict, dict]:
        """
        Walk all canvas items, build their context, evaluate every rule,
        and accumulate quantities.

        Parameters
        ----------
        canvas_items  : list of SmartPole / SmartStructure / SmartSpan /
                        SmartConsumer instances from the scene
        rules         : parsed contents of rules.json
        use_uh        : project-level UH material toggle
        project_type  : project type string e.g. "NSC", "SHIFTING" etc.

        provenance_out : optional dict. When supplied, it is populated with
                        ``(item_type, name) → list[contribution]`` records so the
                        UI can show where each estimate line came from (object
                        label, rule id, condition, formula/recipe, qty).

        Returns
        -------
        (raw_bom, raw_lab)
            raw_bom  : dict  item_name → total_quantity  (Materials)
            raw_lab  : dict  task_name → total_quantity  (Labor)
        """
        from canvas import SmartPole, SmartStructure, SmartSpan, SmartConsumer
        raw_bom: dict[str, float] = {}
        raw_lab: dict[str, float] = {}

        # Load recipes and sections once before the item/rule loop.
        # Previously these were fetched inside the inner loop — one DB open+close
        # per (item × rule) match, which could mean dozens of round-trips per refresh.
        from core import db_gateway as _dbg
        try:
            _recipes_list   = _dbg.get_recipes()
            _sections       = _dbg.get_sections()
            _recipes_by_key = {r["recipe_key"]: r for r in _recipes_list}
        except Exception:
            _recipes_list   = []
            _sections       = {}
            _recipes_by_key = {}

        for item in canvas_items:

            # ── Build context ─────────────────────────────────────────────
            if isinstance(item, SmartPole):
                ctx = self._build_pole_context(item, use_uh, project_type)

            elif isinstance(item, SmartStructure):
                ctx = self._build_structure_context(item, use_uh, project_type)

            elif isinstance(item, SmartSpan):
                ctx = self._build_span_context(item, use_uh, project_type)

            elif isinstance(item, SmartConsumer):
                ctx = self._build_consumer_context(item, use_uh, project_type)

            else:
                # Unknown item type — skip silently
                continue

            obj_label = _object_label(item) if provenance_out is not None else ""

            # ── Evaluate rules ────────────────────────────────────────────
            for rule in rules:
                target = rule.get("object", "")

                # Match object type
                # Also allow "SmartHome" rules to match SmartConsumer
                # so legacy rulesets keep working without any edits.
                obj_type = ctx.get("object_type", "")
                if target == "SmartHome" and obj_type == "SmartConsumer":
                    pass   # allow legacy match
                elif target != obj_type:
                    continue

                condition = rule.get("condition", "")
                if not self.evaluate_rule(ctx, condition):
                    continue

                rule_items = rule.get("items")
                if rule_items is None:
                    rule_items = [{
                        "type":      rule.get("type", "Material"),
                        "item_name": rule.get("item_name", ""),
                        "formula":   rule.get("formula", "1")
                    }]

                for item_dict in rule_items:
                    formula = item_dict.get("formula", "1")
                    
                    is_recipe = False
                    recipe_key = str(formula).strip()
                    if recipe_key.lower() == "recipe":
                        recipe_key = ctx.get("iron_recipe", "None")
                        is_recipe = True
                        # Apply defaults when no recipe is assigned to this pole
                        if not recipe_key or recipe_key == "None":
                            if ctx.get("object_type") == "SmartPole":
                                recipe_key = "POLE_HT_IRON" if ctx.get("pole_type") == "HT" else "POLE_LT_IRON"
                            else:
                                recipe_key = "None"
                    elif _RECIPE_KEY_RE.match(recipe_key):
                        is_recipe = True

                    if is_recipe:
                        if not recipe_key or recipe_key == "None":
                            continue
                        try:
                            recipe = _recipes_by_key.get(recipe_key)
                            if not recipe:
                                continue
                            for rec_item in recipe.get("items", []):
                                sec_code = rec_item["section"]
                                sec = _sections.get(sec_code)
                                if not sec:
                                    continue

                                # dynamic_length: evaluate formula against this item's context
                                if "dynamic_length" in rec_item:
                                    try:
                                        lpp = float(evaluate_formula(rec_item["dynamic_length"], ctx))
                                    except Exception:
                                        lpp = 0.0
                                else:
                                    lpp = float(rec_item.get("length_per_piece", rec_item.get("length", 0.0)))

                                qpo = int(rec_item.get("qty_per_object", rec_item.get("qty", 1)))
                                qty_mt = round((lpp * qpo * sec.get("kg_per_metre", 0.0)) / 1000.0, 6)
                                if qty_mt <= 0:
                                    continue

                                # Use the exact materials table item_name as the accumulation key.
                                # Sections table labels use lowercase (75x40) while the materials
                                # table uses uppercase (75X40) — the hardcoded map bridges that gap.
                                agg_key = _SECTION_TO_DB_NAME.get(sec_code, sec.get("label", sec_code))
                                item_type = item_dict.get("type", "Material")
                                prov_type = "Labor" if item_type == "Labor" else "Material"
                                if item_type in ("Material", "Iron"):
                                    raw_bom[agg_key] = raw_bom.get(agg_key, 0) + qty_mt
                                elif item_type == "Labor":
                                    raw_lab[agg_key] = raw_lab.get(agg_key, 0) + qty_mt
                                if provenance_out is not None:
                                    provenance_out.setdefault((prov_type, agg_key), []).append({
                                        "object_label": obj_label,
                                        "object_type":  ctx.get("object_type", ""),
                                        "rule_id":      rule.get("id"),
                                        "condition":    condition,
                                        "formula":      f"recipe:{recipe_key} → {sec_code}",
                                        "qty":          qty_mt,
                                        "item_type":    prov_type,
                                    })
                        except Exception as e:
                            print(f"[RuleEngine] Error expanding recipe '{recipe_key}': {e}")
                        continue

                    qty     = self.calculate_qty(ctx, formula)

                    if qty <= 0:
                        continue

                    item_name = item_dict.get("item_name", "")
                    item_type = item_dict.get("type", "Material")

                    if not item_name:
                        continue

                    if item_type == "Material":
                        raw_bom[item_name] = raw_bom.get(item_name, 0) + qty
                    elif item_type == "Labor":
                        raw_lab[item_name] = raw_lab.get(item_name, 0) + qty

                    if provenance_out is not None:
                        provenance_out.setdefault((item_type, item_name), []).append({
                            "object_label": obj_label,
                            "object_type":  ctx.get("object_type", ""),
                            "rule_id":      rule.get("id"),
                            "condition":    condition,
                            "formula":      formula,
                            "qty":          qty,
                            "item_type":    item_type,
                        })

        return raw_bom, raw_lab
