"""
core/property_registry.py
=========================
Single source of truth for property metadata, loaded from the database.
Replaces the hardcoded PROPERTY_DATA and SIM_DEFAULTS from constants.py.
"""

from core import db_gateway
from core.constants import (
    PROPERTY_DATA as FALLBACK_PD, 
    SIM_DEFAULTS as FALLBACK_SD
)

class PropertyRegistry:
    _instance = None

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._property_data: dict[str, dict] = {}
        self._sim_defaults: dict[str, dict] = {}
        self._tree_def: list = []
        self._filter_chips: dict[str, list] = {}
        self._formula_vars: dict[str, list] = {}
        self.reload()

    def reload(self):
        """Load all property definitions from database."""
        obj_types = ["SmartPole", "SmartStructure", "SmartSpan", "SmartConsumer"]
        for ot in obj_types:
            props = db_gateway.get_properties_for_simulator(ot)
            if not props:
                # Fallback to constants if DB is empty or unavailable
                self._property_data[ot] = dict(FALLBACK_PD.get(ot, {}))
                self._sim_defaults[ot] = dict(FALLBACK_SD.get(ot, {}))
                continue

            pd = {}
            sd = {}
            for p in props:
                name = p["prop_name"]
                wtype = p["widget_type"]
                options = p.get("options", [])
                sim_def = p.get("sim_default", "")

                # 1. Reconstruct PROPERTY_DATA style format for rule builder condition dropdowns
                if wtype == "combo":
                    typed_options = []
                    for opt in options:
                        s_opt = str(opt).strip()
                        if s_opt.lower() == "true":
                            typed_options.append(True)
                        elif s_opt.lower() == "false":
                            typed_options.append(False)
                        else:
                            try:
                                typed_options.append(int(s_opt))
                            except ValueError:
                                typed_options.append(s_opt)
                    pd[name] = typed_options
                elif wtype in ("spin", "dspin"):
                    pd[name] = "int"
                else:
                    pd[name] = "text"

                # 2. Reconstruct SIM_DEFAULTS style format for simulator side panel
                if wtype == "combo":
                    # Simulator needs strict strings for combo options
                    str_options = [str(o) for o in options]
                    sd[name] = (wtype, str_options, sim_def)
                elif wtype in ("spin", "dspin"):
                    try:
                        sim_def_val = float(sim_def) if wtype == "dspin" else int(float(sim_def))
                    except ValueError:
                        sim_def_val = 0
                    min_v = p.get("sim_min")
                    max_v = p.get("sim_max")
                    
                    min_v = float(min_v) if min_v is not None else 0.0
                    max_v = float(max_v) if max_v is not None else 100.0
                    
                    if wtype == "spin":
                        min_v, max_v = int(min_v), int(max_v)
                        
                    sd[name] = (wtype, (min_v, max_v), sim_def_val)
                else:
                    sd[name] = (wtype, None, sim_def)


            # 3. Add Custom Properties
            custom_entries = db_gateway.get_custom_entries(ot)
            for entry in custom_entries:
                label = entry['label']
                options = entry.get('options', [])
                if options:
                    pd[label] = ['None'] + options
                    sd[label] = ('combo', ['None'] + options, 'None')
                else:
                    pd[label] = [True, False]
                    sd[label] = ('combo', ['False', 'True'], 'False')

            self._property_data[ot] = pd
            self._sim_defaults[ot] = sd

        # 4. Reload Structural Hierarchies (Tree, Filters, Formula Vars)
        try:
            td = db_gateway.get_tree_def()
            self._tree_def = td if td else []
        except Exception:
            self._tree_def = []

        try:
            fc = db_gateway.get_filter_chips()
            self._filter_chips = fc if fc else {}
        except Exception:
            self._filter_chips = {}

        try:
            fv = db_gateway.get_formula_vars()
            self._formula_vars = fv if fv else {}
        except Exception:
            self._formula_vars = {}

    def get_property_data(self, obj_type: str) -> dict:
        """Get PROPERTY_DATA dict for an object type."""
        return self._property_data.get(obj_type, {})

    def get_sim_defaults(self, obj_type: str) -> dict:
        """Get SIM_DEFAULTS dict for an object type."""
        return self._sim_defaults.get(obj_type, {})

    def get_all_property_data(self) -> dict:
        """Get the full dictionary of all PROPERTY_DATA."""
        return self._property_data

    def get_all_sim_defaults(self) -> dict:
        """Get the full dictionary of all SIM_DEFAULTS."""
        return self._sim_defaults

    def get_tree_def(self) -> list:
        return self._tree_def

    def get_filter_chips(self, obj_type: str = None) -> dict | list:
        if obj_type:
            return self._filter_chips.get(obj_type, [])
        return self._filter_chips

    def get_formula_vars(self, obj_type: str = None) -> dict | list:
        if obj_type:
            return self._formula_vars.get(obj_type, [])
        return self._formula_vars

# Global registry instance retriever
def get_registry() -> PropertyRegistry:
    return PropertyRegistry.instance()
