import os
import sys
import unittest
import json

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core import db_gateway as dbg
from core.rule_engine import DynamicRuleEngine
from PyQt6.QtWidgets import QApplication

# Headless application instance for QGraphicsItem-derived objects
_app = QApplication.instance()
if _app is None:
    _app = QApplication(sys.argv)

class TestProjectSerialization(unittest.TestCase):
    """Verify that autosave_erp.json loads properly and preserves key properties."""

    def test_autosave_load_and_structure(self):
        autosave_path = os.path.join(PROJECT_ROOT, "autosave_erp.json")
        self.assertTrue(os.path.exists(autosave_path), "autosave_erp.json must exist")
        
        with open(autosave_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.assertIn("version", data)
        self.assertIn("project_meta", data)
        self.assertIn("nodes", data)
        self.assertIn("spans", data)
        self.assertEqual(len(data["nodes"]), 6)
        self.assertEqual(len(data["spans"]), 4)

class TestDatabaseGateway(unittest.TestCase):
    """Verify basic database connectivity and essential read operations."""

    def test_fetch_settings(self):
        settings = dbg.get_all_settings()
        self.assertIsInstance(settings, dict)

    def test_fetch_pole_type2(self):
        pole_types = dbg.get_all_pole_type2()
        self.assertIsInstance(pole_types, list)
        self.assertGreater(len(pole_types), 0, "Pole types list should not be empty")

from canvas import SmartPole

class TestRuleEngineBasics(unittest.TestCase):
    """Verify DynamicRuleEngine instantiates and evaluates without crashing."""

    def test_rule_engine_init(self):
        engine = DynamicRuleEngine()
        self.assertIsNotNone(engine)

    def test_rule_engine_process_pole(self):
        engine = DynamicRuleEngine()
        rules = dbg.get_rules()
        self.assertGreater(len(rules), 0)

        # Create a single new 8MTR LT PCC pole using real SmartPole class
        pole = SmartPole(0, 0, refresh_signal=None, pole_type="LT", is_existing=False)
        pole.height = "8MTR"
        pole.pole_type2 = "PCC"
        
        bom, lab = engine.process([pole], rules, use_uh=False, project_type="NSC")
        
        self.assertIsInstance(bom, dict)
        self.assertIsInstance(lab, dict)
        # Verify 8MTR PCC pole material is triggered
        self.assertIn("P C C POLE:8 Mtrs.Long", bom)
        self.assertEqual(bom["P C C POLE:8 Mtrs.Long"], 1.0)
        # Verify erection labor is triggered
        self.assertIn("Erection of 8MTR PCC Pole (LT) Without Painted", lab)
        self.assertEqual(lab["Erection of 8MTR PCC Pole (LT) Without Painted"], 1.0)

class TestEditorHelpers(unittest.TestCase):
    """Verify extracted editor helpers return expected configurations."""

    def test_height_options(self):
        from ui.editors import editor_helpers as eh
        opts_pcc = eh.get_height_options("PCC")
        self.assertIn("8MTR", opts_pcc)
        opts_stp = eh.get_height_options("STP")
        self.assertIn("9MTR", opts_stp)

    def test_conductor_sizes(self):
        from ui.editors import editor_helpers as eh
        lt_acsr = eh.get_conductor_sizes("ACSR", is_lt=True)
        self.assertIn("30SQMM", lt_acsr)
        ht_acsr = eh.get_conductor_sizes("ACSR", is_lt=False)
        self.assertIn("50SQMM", ht_acsr)

class TestBillingService(unittest.TestCase):
    """Verify headless billing and tax calculations."""

    def test_calculate_taxes(self):
        from core.billing_service import calculate_taxes
        res = calculate_taxes(10000.0)
        self.assertEqual(res["labor_base"], 10000.0)
        self.assertEqual(res["cgst_amount"], 900.0)
        self.assertEqual(res["sgst_amount"], 900.0)
        self.assertEqual(res["gst_total"], 1800.0)
        self.assertEqual(res["grand_total"], 11800.0)

    def test_amount_to_words(self):
        from core.billing_service import amount_to_indian_rupees_words
        words = amount_to_indian_rupees_words(12345.50)
        self.assertIn("Twelve Thousand Three Hundred Forty Five", words)
        self.assertIn("Fifty Paise", words)

class TestProjectIO(unittest.TestCase):
    """Verify project state serialization and path sanitization."""

    def test_sanitize_subject_stem(self):
        from core.project_io import sanitize_subject_stem
        stem = sanitize_subject_stem("NSC / EXTENSION: LINE 1?")
        self.assertEqual(stem, "NSC___EXTENSION__LINE_1_")
        self.assertEqual(sanitize_subject_stem("", "default"), "default")

    def test_compile_project_state(self):
        from core.project_io import compile_project_state
        state = compile_project_state([], {"subject": "Test"}, {"item1": 5})
        self.assertEqual(state["version"], 5)
        self.assertEqual(state["project_meta"]["subject"], "Test")
        self.assertEqual(state["overrides"]["item1"], 5)

class TestHistoryManager(unittest.TestCase):
    """Verify CanvasHistoryManager undo and redo state progression."""

    def test_undo_redo_flow(self):
        from canvas.history_manager import CanvasHistoryManager
        current = {"v": 1}
        applied = []

        def get_state():
            return dict(current)

        def apply_state(state, fit):
            applied.append(dict(state))

        mgr = CanvasHistoryManager(get_state, apply_state)
        self.assertFalse(mgr.can_undo)
        self.assertFalse(mgr.can_redo)

        # Push state 1
        mgr.push()
        self.assertEqual(len(mgr.history), 1)

        # Change and push state 2
        current["v"] = 2
        mgr.push()
        self.assertTrue(mgr.can_undo)
        self.assertFalse(mgr.can_redo)

        # Undo back to state 1
        self.assertTrue(mgr.undo())
        self.assertEqual(applied[-1]["v"], 1)
        self.assertTrue(mgr.can_redo)

        # Redo back to state 2
        self.assertTrue(mgr.redo())
        self.assertEqual(applied[-1]["v"], 2)

class TestEstimatePanel(unittest.TestCase):
    """Verify estimate calculation, formatting, and humanization helpers."""

    def test_format_quantity(self):
        from ui.estimate_panel import format_quantity
        self.assertEqual(format_quantity(5.0, "Nos"), "5")
        self.assertEqual(format_quantity(12.7, "Nos."), "13")
        self.assertEqual(format_quantity(5.1234, "Mtr"), "5.123")

    def test_humanize_condition_and_formula(self):
        from ui.estimate_panel import humanize_condition, humanize_formula
        self.assertEqual(humanize_condition(""), "Applied automatically to all instances")
        self.assertEqual(humanize_condition("is_new == True"), "New")
        self.assertIn("New line", humanize_condition("is_new_span == True and is_lt_span == True"))
        self.assertEqual(humanize_formula("1"), "1 per object")
        self.assertEqual(humanize_formula("3"), "3 per object")
        self.assertIn("Recipe", humanize_formula("recipe:POLE_TOP_IRON → Top Bracket"))

    def test_calculate_estimate_totals(self):
        from ui.estimate_panel import calculate_estimate_totals
        from datetime import datetime
        bom = [
            {"name": "Pole", "type": "Material", "amt": 1000.0},
            {"name": "Erection", "type": "Labor", "amt": 200.0}
        ]
        # Fixed date within FY 2026-2027 (no escalations if base is 2026)
        totals = calculate_estimate_totals(bom, sup_rate=0.10, base_year=2026, now=datetime(2026, 6, 1))
        self.assertEqual(totals["mat_base"], 1000.0)
        self.assertEqual(totals["lab_sub"], 200.0)
        self.assertEqual(len(totals["escalations"]), 0)
        self.assertEqual(totals["sundries"], 50.0)
        self.assertEqual(totals["mat_sub"], 1050.0)
        self.assertEqual(totals["supervision"], (1050.0 + 200.0) * 0.10)
        self.assertAlmostEqual(totals["gst"], 200.0 * 0.18)

class TestEstimateService(unittest.TestCase):
    """Verify estimate service DB lookup and normalization."""

    def test_normalize_db_name(self):
        from core.estimate_service import normalize_db_name
        self.assertEqual(normalize_db_name("Distribution Transformer 25 KVA"), "dtr25kva")
        self.assertEqual(normalize_db_name("Aug. DTR S/Stn"), "augdtrsstn")

    def test_db_lookup_with_prefetched(self):
        from core.estimate_service import db_lookup
        import sqlite3
        from core.database import DB_PATH
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        prefetched = {
            "Material": [("MAT-01", 150.0, "Nos", "Stay Set Complete HT")],
            "Labor": [("LAB-01", 80.0, "Nos", "Erection of Stay Set")]
        }
        # Exact
        res = db_lookup(cursor, "Material", "Stay Set Complete HT", _prefetched=prefetched)
        self.assertIsNotNone(res)
        self.assertEqual(res[0], "MAT-01")
        # Case insensitive
        res_ci = db_lookup(cursor, "Material", "stay set complete ht", _prefetched=prefetched)
        self.assertIsNotNone(res_ci)
        self.assertEqual(res_ci[0], "MAT-01")
        conn.close()

class TestCanvasOps(unittest.TestCase):
    """Verify graph algorithms and span validation in canvas_ops."""

    def test_find_nearby_node(self):
        from canvas.canvas_ops import find_nearby_node
        class DummyNode:
            def __init__(self, x, y):
                self._x, self._y = x, y
            def x(self): return self._x
            def y(self): return self._y

        n1 = DummyNode(100.0, 100.0)
        nodes = [n1]
        self.assertIsNotNone(find_nearby_node(nodes, 105.0, 100.0, min_gap=20.0))
        self.assertIsNone(find_nearby_node(nodes, 150.0, 100.0, min_gap=20.0))

    def test_validate_span_creation_endpoints(self):
        from canvas.canvas_ops import validate_span_creation
        class DummyNode:
            connected_spans = []

        n1 = DummyNode()
        ok, reason = validate_span_creation(n1, n1)
        self.assertFalse(ok)
        self.assertIn("different", reason)

    def test_auto_update_stays_single_span(self):
        from canvas.canvas_ops import auto_update_stays
        from canvas._base import SmartPole

        p1 = SmartPole(0, 0, None, "LT")
        p2 = SmartPole(50, 0, None, "LT")
        class DummySpan:
            is_service_drop = False
            is_existing_span = False
            def __init__(self, node1, node2):
                self.p1 = node1
                self.p2 = node2
        p1.connected_spans = [DummySpan(p1, p2)]
        auto_update_stays([p1])
        # Dead-end pole with 1 active span requires 1 stay
    def test_estimate_app_launch_and_live_estimate(self):
        from app import EstimateApp
        from canvas import SmartPole

        win = EstimateApp()
        self.assertIsNotNone(win._is_undoing)
        self.assertEqual(win.live_table.rowCount(), 0)

        # Place a pole and verify live estimate updates and renders in table
        p = SmartPole(0, 0, win.refresh_signal, "LT")
        win.scene.addItem(p)
        win._flush_refresh()
        self.assertGreater(len(win.live_bom_data), 0)
        self.assertEqual(win.live_table.rowCount(), len(win.live_bom_data))
        self.assertIn("Estimated Cost", win.grand_total_label.text())

if __name__ == "__main__":
    unittest.main()





