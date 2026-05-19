# Future Feature Backlog

Last updated: 2026-05-19

---

## Completed

- Reuse last export path.
- Save project bundle (PDF + Excel + drawing JSON).
- Initial custom property system: Property Editor, slot count, per-object Custom 1..N selectors, rule-context exposure, and project save/load persistence.
- AI Rule Creator (plain English rule generation via Groq API).
- Configurable Rate Chart Base Year for escalations (Settings → Rate Chart Year dialog + database persistence).
- Rule Grouping (Phase 1.1): One condition maps to multiple items; SQLite auto-migration; and interactive items table editor in Ruleset Manager UI.
- Phase 2 — Iron Recipe System: Built dynamic database-backed iron recipes template system (`data/recipes.json` + `recipes`/`sections` database tables), complete CRUD API integration, canvas property serialization, Property Editor dropdown integration, dynamic Rule Engine `"formula": "recipe"` expansion, and premium `RecipeManagerDialog` UI for full template and steel profile management.
- Iron Breakup Sheet (2.5): Section-centric Excel layout with nested object groups, IRON SUMMARY block per section type, 3-decimal formatting, wastage + final total rows. No combined grand total mixing section types.
- Externalize Iron Variables (2.6): All kg/m values for MS iron sections stored in `sections` DB table; recipe engine and rule engine both read from this single source. No hardcoded values in rules or formulas.
- Iron-estimate sync fix: Recipe expansion in rule engine now accumulates by exact materials-table name (hardcoded section→DB-name map). DB rule seeding changed to `INSERT OR REPLACE` so `rules.json` changes always propagate. App data reset no longer copies stale root DB.
- SAG wastage guard: Wastage multiplier (×1.03) now checks the item's DB unit before applying — counted items (SET, NOS) containing "ACSR" in their name no longer receive spurious wastage.
- Ruleset Manager recipe labels: Iron rule cards now display the actual recipe name (e.g., "HT Pole Extension Iron") and a green "recipe" badge instead of the generic "Structural Iron (from Recipe)" placeholder.

---

## Phase 1 — Fix & Clean (Next Up)

### 1.1 Rule Grouping [COMPLETED]
- Restructure `rules.json` — one condition maps to an array of items underneath it.
- Update rule engine — one extra inner loop over items, ~2 lines of code change.
- Update Ruleset Manager UI — rule cards become expandable, showing item table inside each card.
- Write one-time migration script to convert existing 230 rules to new format automatically.

### 1.2 Known Rule Issues to Fix
- Rules 48–50 (SmartStructure): `condition: True` fires for every structure type. Replace with explicit `structure_type in (...)` condition.
- Rules 93–97 (DTR iron): Iron calculation ignores `dtr_size`. Temporary fix — add `dtr_size` condition until recipe system is ready in Phase 2.
- Rules 95 + 97: Both add `ANG_65X65X6` for DTR with no description explaining why. Document or split into named recipe items.
- DTR augmentation rules 202–219 sit on SmartPole with `existing_subtype == 'DTR'` — architectural mismatch. Flag for cleanup when augmentation is revisited.

### 1.3 Duplicate & Overlap Detection in Ruleset Manager
- On Save, compare new condition against all existing rules for the same object type.
- Detect: exact match, new is broader, new is narrower, partial overlap.
- Show plain English warning with options — warn but never block the user.
- Suggest "add items to existing rule" when exact match is found.

### 1.4 Rate Chart Base Year (Escalation) [COMPLETED]
- Currently the base year for escalation calculation is hardcoded.
- Move to a configurable setting: Settings → Rate Chart Year.
- Store in local DB or config file so user can update it without code changes.
- Escalation calculation reads this year dynamically.

---

## Phase 2 — Iron Recipe System [COMPLETED]

### 2.1 Recipe Data
- Create `data/recipes.json` — named templates per object variant.
- Each recipe contains: description per item, section type, length (m), quantity, kg/m.
- Add `sections` table to `erp_master.db` — section code, label, kg per metre.

### 2.2 Canvas Changes
- Add capacity/variant dropdown to SmartStructure (DTR size, structure type).
- Add iron recipe picker dropdown on poles and structures in property panel.
- Selected recipe key saved in project JSON alongside other object properties.

### 2.3 Rule Engine Changes
- Iron rules simplified to `"formula": "recipe"` — one line per iron rule.
- Rule engine detects `recipe` formula and delegates to recipe engine.
- Recipe engine reads selected recipe, calculates weights, returns descriptive line items.

### 2.4 Recipe Manager UI
- Settings → Iron Recipes.
- Expandable list — click a recipe to open inline editable grid.
- Each row: description, section, length, qty, kg/m, auto-calculated weight.
- Live total (kg and MT) updates as user types.
- Clone, Add New, Delete buttons.
- Changes are local per installation — does not affect other users.

### 2.5 Iron Breakup Sheet (Excel) — Full Redesign [COMPLETED]
- Section-centric outer layout with nested object groups per section block.
- Per-object sub-headers, individual recipe item rows (No × Length), object iron totals.
- Bottom IRON SUMMARY: one row per section type (MT > 0), then TOTAL IRON, wastage @ 3%, TOTAL (incl. wastage).
- All values 3 decimal places. No combined grand total mixing different section types.

### 2.6 Externalize Iron Variables for Rule Engine [COMPLETED]
- Iron section kg/m values stored in `sections` DB table; editable via Iron Recipes Manager.
- Rule engine and recipe engine both read kg/m from DB — no hardcoded values in rules or code.

### 2.7 Externalize Conversion Rate
- Move escalation/conversion rate logic to external config source.
- Editable from Settings without code changes.
- Ties in with Rate Chart Base Year (1.4 above).

---

## Phase 3 — User Control & Customisation

### 3.1 Per-Object Estimate Override
- Any line in live estimate table can be overridden for a specific object.
- Click line → small override panel: substitute item, change quantity, zero out.
- Override travels with project JSON — not global, not affecting other projects.

### 3.2 Estimate Transparency
- Click any line in live estimate → popup shows:
  - Which canvas object generated it.
  - Which rule matched.
  - Which recipe was used (if iron).
  - Formula and calculated value.
- User understands exactly where every number came from.

### 3.3 External Property Containers
- Move hardcoded object property options to external definitions.
- Example: Pole type values (PCC/STP/RAIL) and heights (8m/9m/11m) editable without code changes.
- User can add custom options (e.g. new pole type or height) from Settings.
- Apply across all object types: SmartPole, SmartStructure, SmartSpan, SmartConsumer.

### 3.4 Conductor and DTR Augmentation Controls
- Add augmentation controls for conductor calculations.
- Add augmentation controls for DTR size change calculations.
- Clarify where augmentation applies: estimate view, exports, rule context.

### 3.5 Improved Rule Adding UI
- Pick object type from dropdown.
- Build condition visually — dropdowns for property, operator, value. No Python typing.
- Add items below condition — searchable item code from database.
- Formula helper shows all available context variables.
- Overlap detection runs on Save (see 1.3).
- AI assistant stays for plain English rule creation.

### 3.6 Custom Objects
- Settings → Custom Objects.
- User defines: name, icon shape, properties list.
- Appears in toolbar like any built-in object.
- Rules added for it via Ruleset Manager as normal.
- Advanced feature — not for everyday users.

---

## Phase 4 — User Profiles & Billing

### 4.1 Local User Profiles
- Simple login/select screen on app startup.
- Each profile stores: name, firm name, address, GST number, signature image.
- Stored in local `erp_master.db` — no server required.
- Multiple profiles per installation supported.

### 4.2 Export Personalisation
- PDF and Excel headers auto-filled from logged-in user profile.
- Date auto-filled.
- Signature embedded in PDF if provided.

### 4.3 Billing Module
- One-click bill generation from any saved project.
- Bill document includes: firm details, GST number, Bill To fields, itemised estimate table, grand total.
- User can select multiple projects and generate a combined bill.
- Output as PDF, ready to submit.

### 4.4 Project Management Screen
- File → My Projects.
- List of all saved projects: name, date, location, status.
- Open, rename, delete, duplicate from list.
- Compare two projects side by side (totals and key quantities).

---

## Phase 5 — Cloud & Mobile (Design Before Building)

### 5.1 Backend Architecture (Plan First)
- Design API and data model before writing any server code.
- Recommended stack: FastAPI, PostgreSQL, REST API.
- Desktop app syncs via API. Mobile app is a separate lighter codebase.
- Decision needed: which data is global (rules, recipes) vs per-user (projects, overrides).

### 5.2 Cloud Backend
- User accounts with proper authentication.
- Projects stored server-side, synced to desktop on open/save.
- Recipes and rules optionally synced per user or pushed by admin.
- Billing history stored in cloud.

### 5.3 Mobile App
- Simplified canvas — place poles, connect spans, set basic properties.
- Estimate generates on device.
- Share PDF directly from phone.
- Syncs to desktop automatically when online.

### 5.4 Multi-User & Admin Features
- Each user has own projects and recipe customisations.
- Admin can push default rules and recipes to all users.
- Audit trail — who changed which rule and when.
- Per-user billing details and export history.

---

## Implementation Order (Recommended)

1. Rate chart base year setting (1.4) — small, high value, do immediately.
2. Rule overlap detection (1.3) — before any new rules are added.
3. Rule grouping migration (1.1) — foundation for everything else.
4. Known rule fixes (1.2).
5. Iron recipe system (Phase 2) — biggest structural improvement.
6. External property containers (3.3).
7. Improved rule adding UI (3.5).
8. Per-object overrides and transparency (3.1, 3.2).
9. User profiles and billing (Phase 4).
10. Cloud and mobile (Phase 5) — separate product decision, 6–12 months.
