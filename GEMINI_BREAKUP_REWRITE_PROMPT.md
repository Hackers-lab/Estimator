# Gemini Flash — Iron Breakup Sheet Complete Rewrite

Paste this entire prompt to Gemini Flash. Do not paraphrase it.

---

## Context

I have a PyQt6 desktop application (ERP Estimate Generator) that generates electrical
network estimates. The relevant file is `exporters/excel.py` which contains the
`ExcelExporter` class.

The app has SmartPole, SmartStructure, SmartSpan, SmartConsumer canvas objects.
The app has a recipe system in `data/recipes.json` and a `core/db_gateway.py`
with these functions already working:
- `db_gateway.get_recipes(object_type=None)` — returns list of recipe dicts
- `db_gateway.get_sections()` — returns dict of {section_code: {label, kg_per_metre}}

---

## What Each Recipe Item Looks Like (New Schema)

Each recipe item in `recipes.json` now has these fields:

```json
{
  "description": "Sub-Stn Top",
  "section": "CH_75X40",
  "length_per_piece": 2.25,
  "qty_per_object": 2,
  "length_formula": "=2*2.25",
  "qty_source": "dtr_count"
}
```

- `description` — human-readable label shown in breakup row
- `section` — section code key (matches `get_sections()` dict)
- `length_per_piece` — metres per single piece
- `qty_per_object` — how many pieces per ONE canvas object of this type
- `length_formula` — Excel formula string for the length column (display only)
- `qty_source` — which canvas count to use for quantity column (see counts below)

---

## Section Code → Item Code Mapping

```python
SECTION_TO_ITEM_CODE = {
    "CH_75X40":   "0102010611",
    "CH_100X50":  "0102010911",
    "ANG_65X65X6":"0101011311",
    "ANG_50X50X6":"0101011011",
    "FLAT_65X6":  "0103011511",
    "FLAT_50X6":  "0103011211",
}
```

Section kg/m weights (also available from `db_gateway.get_sections()`):
```python
KG_PER_METRE = {
    "CH_75X40":    6.8,
    "CH_100X50":   9.8,
    "ANG_65X65X6": 5.8,
    "ANG_50X50X6": 4.5,
    "FLAT_65X6":   3.1,
    "FLAT_50X6":   2.5,
}
```

---

## Canvas Counts — How to Calculate Each qty_source

These counts are computed by scanning `self._app.scene.items()`:

```python
def _compute_canvas_counts(self) -> dict:
    from canvas import SmartPole, SmartStructure, SmartSpan

    scene_items = self._app.scene.items()
    poles    = [i for i in scene_items if isinstance(i, SmartPole)]
    structs  = [i for i in scene_items if isinstance(i, SmartStructure)]
    spans    = [i for i in scene_items if isinstance(i, SmartSpan)]

    new_lt_poles = [p for p in poles if not p.is_existing and p.pole_type == "LT"]
    new_ht_poles = [p for p in poles if not p.is_existing and p.pole_type == "HT"]

    return {
        "lt_pole_count":    len(new_lt_poles),
        "ht_pole_count":    len(new_ht_poles),
        "dp_count":         len([s for s in structs if s.structure_type == "DP"]),
        "tp_count":         len([s for s in structs if s.structure_type == "TP"]),
        "4p_count":         len([s for s in structs if s.structure_type == "4P"]),
        "dtr_count":        len([s for s in structs if s.structure_type == "DTR"]),
        "cg_pole_count":    len([p for p in new_lt_poles if any(
                                getattr(s, "has_cg", False)
                                for s in getattr(p, "connected_spans", []))]),
        "pole_ext_count":   len([p for p in poles if getattr(p, "has_extension", False)]),
        "ht_ext_count":     len([p for p in new_ht_poles if getattr(p, "has_extension", False)]),
        "lt_acsr_count":    len([p for p in new_lt_poles if any(
                                getattr(s, "conductor", "") == "ACSR"
                                for s in getattr(p, "connected_spans", []))]),
        "ab_cable_count":   len([sp for sp in spans
                                if getattr(sp, "conductor", "") == "AB Cable"
                                and not getattr(sp, "is_existing_span", False)]),
    }
```

---

## The Task

**Completely replace** the two methods `_write_iron_breakup_sheet` and
`_collect_iron_detail` in `exporters/excel.py` with the new implementation below.

Do NOT change any other method in the file. Keep all imports as they are.

---

### New `_write_iron_breakup_sheet` Implementation

The new sheet layout is **object-group centric**. Each group of canvas objects
gets its own labelled block. After all blocks, a grand summary by section type
is shown, followed by wastage and total.

**Column layout** (columns A–G):
- A: Row number (integer, per block)
- B: Description label
- C: Quantity (canvas count for that row's qty_source)
- D: Length per piece (Excel formula string from `length_formula`, e.g. `=2*2.25`)
- E: Total length `=C*D` as Excel formula (e.g. `=C4*D4`)
- F: Weight kg (total_m × kg_per_metre, computed in Python, written as value)
- G: (empty, reserved)

**Block structure per object group:**

```
[Section header row — merged A:G, bold, blue fill]
  Col A: Group letter (B, C, D...)
  Col B: Group title  e.g. "DTR Substation Iron (2 nos on canvas)"
  Col C: "No"
  Col D: "Length (m)"
  Col E: "Total (m)"
  Col F: "Wt (kg)"

[Data rows — one per recipe item that belongs to this group]
  Col A: row index (1, 2, 3...)
  Col B: item description
  Col C: canvas count (qty_source value from counts dict)
  Col D: length_formula string (written as Excel formula)
  Col E: Excel formula =Cx*Dx  (references actual row)
  Col F: computed weight = (length_per_piece × qty_per_object × canvas_count) × kg_per_metre

[Subtotal row per section type within this group — only if group has >1 section type]
  e.g. "Channel subtotal: 14.0m = 95.2 kg"

[Blank row between groups]
```

**Groups to generate (in this order), skip group if canvas count is 0:**
1. DTR Substation Iron — uses `DTR_IRON` recipe, canvas count = `dtr_count`
2. DP Structure Iron — uses `DP_IRON` recipe, canvas count = `dp_count`
3. TP Structure Iron — uses `TP_IRON` recipe, canvas count = `tp_count`
4. 4-Pole Structure Iron — uses `4P_IRON` recipe, canvas count = `4p_count`
5. LT Pole Iron — use the `iron_recipe` set on each pole object.
   Group all LT poles together. For each recipe item, qty = count of LT poles
   whose `iron_recipe` matches that recipe key.
   If LT poles use different recipes (some use POLE_LT_IRON, some use POLE_LT_TOP_ADAPTOR),
   show each recipe as a sub-group within the LT Pole block.
6. HT Pole Iron — uses `POLE_HT_IRON` recipe, canvas count = `ht_pole_count`
7. Pole Extensions — read directly from rules (not recipe):
   - HT pole extension: CH_75X40, `=extension_height*2` per pole, flat 3m per pole
   - LT pole extension: ANG_65X65X6, `=extension_height` per pole
   Count poles with `has_extension == True` separately for HT and LT.
8. CG Bracket Iron — read directly from rules:
   - ANG_65X65X6: 1.9m per CG pole (count = `cg_pole_count`)
   - FLAT_65X6: 0.5m per CG pole
9. LT ACSR Bracket — read directly from rules:
   - ANG_65X65X6: 1.0m per pole with LT ACSR (count = `lt_acsr_count`)
   - FLAT_65X6: 1.0m per pole with LT ACSR
10. AB Cable Clamp Flat — read directly from rules:
    - FLAT_65X6: 0.5m per AB Cable span (count = `ab_cable_count`)

**After all groups — Grand Summary block:**

```
[Bold header row: "SECTION SUMMARY"]
For each section type that has any total > 0:
  Row: section label | total metres | kg/m | total kg
e.g.:
  M.S. Channel 75x40mm  |  68.5m  |  6.8 kg/m  |  465.8 kg
  M.S. Angle 65x65x6mm  |  42.0m  |  5.8 kg/m  |  243.6 kg
  M.S. Flat 65x6mm      |  28.0m  |  3.1 kg/m   |   86.8 kg

[Blank row]
Sub-total (all iron):    896.2 kg
Add: Wastage + Sag @ 3%:  26.9 kg
GRAND TOTAL:             923.1 kg  =  0.923 MT
```

---

### New `_compute_canvas_counts` Method

Add this as a private method on `ExcelExporter` (paste the implementation from
the Canvas Counts section above exactly).

---

### Remove `_collect_iron_detail` and `_iron_source_label`

These two methods are no longer needed. Remove them entirely.

---

## Key Implementation Notes

1. **Do not hardcode recipe keys** in the breakup logic for groups 1–6.
   Load all recipes from `db_gateway.get_recipes()` and find by key.
   If a recipe key is not found in DB, skip that group silently.

2. **Excel formula strings** in column D must be written using `ws.cell(row, 4).value = "=2*2.25"`.
   openpyxl writes formula strings directly. Do NOT evaluate them in Python.

3. **Column E formula** must reference the actual Excel row.
   e.g. if data row is Excel row 7: `ws.cell(7, 5).value = "=C7*D7"`

4. **Weight column F** is always computed in Python (not a formula):
   `wt_kg = length_per_piece * qty_per_object * canvas_count * kg_per_metre`
   Write as a float value rounded to 2 decimal places.

5. **Accumulate section totals** in a dict as you write each row:
   ```python
   section_totals = {}  # {section_code: {"metres": 0.0, "kg": 0.0}}
   ```
   Add to it for every data row written. Use this for the grand summary.

6. **Wastage**: apply 3% to grand total kg. Write as:
   `wastage_kg = round(total_all_kg * 0.03, 2)`
   `grand_total_kg = total_all_kg + wastage_kg`
   `grand_total_mt = round(grand_total_kg / 1000, 4)`

7. **Styling**:
   - Group header rows: `PatternFill solid fgColor="4472C4"` (dark blue), white bold font
   - Data rows: alternating white / `fgColor="F2F7FF"` (very light blue)
   - Subtotal/summary rows: `fgColor="E2EFDA"` (light green), bold
   - Grand total row: `fgColor="FFF2CC"` (light yellow), bold, font size 12
   - All cells: thin border

8. **Column widths**:
   - A: 5, B: 44, C: 8, D: 14, E: 12, F: 12

9. **Groups 7–10** (extensions, CG, ACSR bracket, AB cable) do NOT use recipes.
   They read counts from `_compute_canvas_counts()` and use hardcoded section
   codes and lengths matching the rule engine values:
   - HT extension: CH_75X40 at `extension_height * 2` m (average 3m if unknown), FLAT_65X6 at 3.0m
   - LT extension: ANG_65X65X6 at `extension_height` m per pole
   - CG bracket: ANG_65X65X6 at 1.9m, FLAT_65X6 at 0.5m
   - LT ACSR bracket: ANG_65X65X6 at 1.0m, FLAT_65X6 at 1.0m
   - AB cable clamp: FLAT_65X6 at 0.5m per span
   For extension groups, also compute average extension_height from actual pole objects:
   ```python
   ext_poles_ht = [p for p in poles if not p.is_existing
                   and p.pole_type == "HT" and p.has_extension]
   avg_ext_ht = (sum(p.extension_height for p in ext_poles_ht) / len(ext_poles_ht)
                 if ext_poles_ht else 3.0)
   ```

---

## Output Required

Provide the complete updated `exporters/excel.py` file in full.
Replace only `_write_iron_breakup_sheet` and `_collect_iron_detail` and
`_iron_source_label`. Add new methods `_write_iron_breakup_sheet`,
`_compute_canvas_counts`. Keep every other method exactly as-is.
