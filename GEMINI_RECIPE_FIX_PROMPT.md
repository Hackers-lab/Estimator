# Gemini Flash — Recipe System Fix Prompt

Paste this entire prompt to Gemini Flash. Do not paraphrase it.

---

## Context

I have a PyQt6 desktop application called ERP Estimate Generator.
It draws electrical network diagrams and generates Bill of Materials estimates.

The codebase has the following relevant files:
- `data/rules.json` — estimation rules
- `data/recipes.json` — iron recipe templates (already exists)
- `canvas/nodes.py` — SmartStructure and SmartPole canvas objects
- `ui/editors/editor_mixin.py` — property panel editor (EditorMixin class)
- `core/rule_engine.py` — evaluates rules against canvas objects
- `exporters/excel.py` — generates Excel estimate with Iron Breakup sheet
- `core/db_gateway.py` — database access functions

The recipe system infrastructure is already built and working:
- `db_gateway.get_recipes()` fetches recipes from SQLite
- `db_gateway.get_sections()` fetches steel sections with kg/m
- `db_gateway.save_recipe()` saves recipes
- `RecipeManagerDialog` UI exists and works correctly
- Rule engine and excel exporter both have recipe expansion logic that activates when `formula == "recipe"`
- `iron_recipe` property exists on SmartStructure and SmartPole (defaults to `"None"`)
- `_add_iron_recipe_picker()` method exists in EditorMixin and shows a dropdown in the property panel

## The Three Problems to Fix

---

### FIX 1 — Remove iron items from rules and replace with a single recipe trigger

In `data/rules.json`, the following rules still have iron MS items hardcoded.
You must remove ONLY the iron items from each rule and replace them all with ONE single iron trigger item.
Do NOT touch any other items in these rules (insulators, hardware, labour stay exactly as they are).

**Rule ID 64** (`condition: structure_type == 'DP'`):
Remove these 2 iron items:
- `item_code: "0102010611"` (M.S Channel 75X40 mm), `formula: "5.0 * CH_75X40 / 1000"`
- `item_code: "0103011511"` (M.S Flat 65X6 mm), `formula: "2.0 * FLAT_65X6 / 1000"`

Replace them with this single item appended to the items array:
```json
{
  "type": "Iron",
  "item_code": "RECIPE_IRON",
  "item_name": "Structural Iron (from Recipe)",
  "formula": "recipe"
}
```

**Rule ID 79** (`condition: structure_type == 'TP'`):
Remove these 3 iron items:
- `item_code: "0102010611"` (M.S Channel 75X40 mm), `formula: "12.0 * CH_75X40 / 1000"`
- `item_code: "0101011311"` (M.S Angle 65X65X6mm), `formula: "12.72 * ANG_65X65X6 / 1000"`
- `item_code: "0103011511"` (M.S Flat 65X6 mm), `formula: "9.0 * FLAT_65X6 / 1000"`

Replace them with the same single recipe trigger item shown above.

**Rule ID 86** (`condition: structure_type == '4P'`):
Remove these 3 iron items:
- `item_code: "0102010611"` (M.S Channel 75X40 mm), `formula: "16.0 * CH_75X40 / 1000"`
- `item_code: "0101011311"` (M.S Angle 65X65X6mm), `formula: "12.72 * ANG_65X65X6 / 1000"`
- `item_code: "0103011511"` (M.S Flat 65X6 mm), `formula: "12.0 * FLAT_65X6 / 1000"`

Replace them with the same single recipe trigger item.

**Rule ID 93** (`condition: structure_type == 'DTR'`):
Remove these 5 iron items (note: two separate ANG_65X65X6 entries, remove both):
- `item_code: "0102010611"` (M.S Channel 75X40 mm), `formula: "9.5 * CH_75X40 / 1000"`
- `item_code: "0102010911"` (M.S Channel 100X50 mm), `formula: "5.0 * CH_100X50 / 1000"`
- First `item_code: "0101011311"` (M.S Angle 65X65X6mm), `formula: "12.25 * ANG_65X65X6 / 1000"`
- `item_code: "0103011511"` (M.S Flat 65X6 mm), `formula: "14.0 * FLAT_65X6 / 1000"`
- Second `item_code: "0101011311"` (M.S Angle 65X65X6mm), `formula: "5.0 * ANG_65X65X6 / 1000"`

Replace them with the same single recipe trigger item.

Keep all other items in all four rules exactly as they are. Only the iron items listed above are removed.

---

### FIX 2 — Auto-assign default recipe when structure is placed

In `canvas/nodes.py`, find the `SmartStructure.__init__` method.

Currently `iron_recipe` is always set to `"None"`:
```python
self.iron_recipe = "None"
```

Change it so the default recipe is set automatically based on `structure_type`:
```python
_default_recipes = {
    "DP":  "DP_IRON",
    "TP":  "TP_IRON",
    "4P":  "4P_IRON",
    "DTR": "DTR_IRON",
}
self.iron_recipe = _default_recipes.get(self.structure_type, "None")
```

IMPORTANT: Also find the `restore_state` method (or wherever `structure_type` is set from saved JSON).
After `self.structure_type` is loaded from state, if `iron_recipe` is `"None"` or missing from state,
apply the same default mapping so old saved projects also get a sensible default:
```python
self.iron_recipe = state.get("iron_recipe", "None")
if self.iron_recipe == "None":
    _default_recipes = {"DP": "DP_IRON", "TP": "TP_IRON", "4P": "4P_IRON", "DTR": "DTR_IRON"}
    self.iron_recipe = _default_recipes.get(self.structure_type, "None")
```

Also find `_update_structure_type` in `ui/editors/editor_mixin.py`
(the function called when user changes structure type from the dropdown).
After updating `structure_type`, also update `iron_recipe` to match the new type's default:
```python
_default_recipes = {"DP": "DP_IRON", "TP": "TP_IRON", "4P": "4P_IRON", "DTR": "DTR_IRON"}
item.iron_recipe = _default_recipes.get(new_type, item.iron_recipe)
```
Then refresh the property panel so the Iron Recipe dropdown updates visually.

---

### FIX 3 — Filter recipe dropdown by structure type in property panel

In `ui/editors/editor_mixin.py`, find `_add_iron_recipe_picker(self, item)`.

Currently it calls `_dbg.get_recipes(item.__class__.__name__)` which returns all SmartStructure recipes regardless of structure type.

Change it so recipes are filtered to only show relevant ones for the current structure type.
Relevant mapping:
- `structure_type == "DP"` → show only recipes where `recipe_key` starts with `"DP_"` plus "None"
- `structure_type == "TP"` → show only recipes where `recipe_key` starts with `"TP_"` plus "None"
- `structure_type == "4P"` → show only recipes where `recipe_key` starts with `"4P_"` plus "None"
- `structure_type == "DTR"` → show only recipes where `recipe_key` starts with `"DTR_"` plus "None"
- SmartPole → show only recipes where `recipe_key` starts with `"POLE_"` plus "None"
- If no matching recipes exist, fall back to showing all recipes for that object type

Implementation:
```python
def _add_iron_recipe_picker(self, item):
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
```

---

## Verification Checklist

After making all three fixes, verify:

1. `rules.json` — Rules 64, 79, 86, 93 no longer contain any item with `item_code` in
   `["0102010611", "0102010911", "0101011311", "0103011511"]`.
   Each of those four rules now has exactly one item with `"formula": "recipe"`.

2. `canvas/nodes.py` — A newly placed DP structure has `iron_recipe == "DP_IRON"` by default,
   not `"None"`.

3. `ui/editors/editor_mixin.py` — When a DTR is selected on canvas, the Iron Recipe dropdown
   shows only DTR recipes (DTR_IRON, any custom DTR_* recipes), not DP or TP recipes.

4. When user changes a structure from DP to DTR using the Type dropdown in the property panel,
   the Iron Recipe dropdown automatically updates to show DTR_IRON as selected.

5. No other files need to be changed. The rule engine, excel exporter, RecipeManagerDialog,
   and db_gateway already handle recipe expansion correctly once the above three fixes are in place.

---

## What NOT to change

- Do not touch `core/rule_engine.py` — recipe expansion already works correctly there.
- Do not touch `exporters/excel.py` — iron breakup sheet already handles recipes correctly.
- Do not touch `ui/dialogs/recipe_manager.py` — RecipeManagerDialog is already complete.
- Do not touch `core/db_gateway.py` — all recipe DB functions are already correct.
- Do not touch `data/recipes.json` — factory recipes are already defined correctly.
- Do not modify any rules other than IDs 64, 79, 86, and 93 in `rules.json`.
- Do not remove any non-iron items from any rule.

---

## Output Required

Provide the complete updated content for exactly these files:
1. `data/rules.json` — full file, all 120 rules, only the 4 rules above changed
2. `canvas/nodes.py` — full file with the `__init__` and `restore_state` changes
3. `ui/editors/editor_mixin.py` — full file with `_add_iron_recipe_picker` and `_update_structure_type` changes

Do not provide partial diffs or snippets. Provide each complete file in full.
