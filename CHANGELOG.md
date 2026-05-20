# ERP Estimate Generator — Release Notes

---

## v7.8 — May 20, 2026

### What's New

#### 💾 Auto-Save Drawings to Documents
Your drawings are now automatically saved to the `Documents/ERP_Estimates/` folder as `unsaved1.json`, `unsaved2.json`, etc. whenever you:
- **Create a new drawing** (the previous work is preserved before clearing)
- **Close the application**

Only drawings with actual changes are saved — opening a file and closing without editing will not generate duplicate files. The **Open Project** dialog now defaults to this folder for easy access.

#### 🔒 Single-Instance Protection
The application now prevents multiple instances from running simultaneously. If you try to launch the app while it is already open, you will see a friendly prompt:
> *"ERP Estimate Generator is already running. Please switch to the existing window."*

This prevents accidental data conflicts and database locking issues.

#### 🧩 Fixed Iron Recipe on Fresh Installation
Resolved an issue where iron recipes (DP, TP, DTR, Pole Iron, etc.) appeared blank on a fresh install. The root cause was that `data/recipes.json` was not included in the PyInstaller packaging configuration, preventing the database from seeding default recipes on first launch.

---

## v7.7 — May 20, 2026

### What's New & Fixes

#### 🤖 AI Rule Creator Option Restored
The **"✨ Describe in plain English"** button has been fully restored under a polished new layout in the Rule Editor's condition panel. In addition, an outdated internal layout chunk that was causing application crashes when looking up items in the database has been completely removed.

#### 🛠️ Fixed HT Pole Iron & Defaults Calculation
- **HT Pole Iron**: Corrected the structural iron calculations so that the top adaptor and V-bracket (composed of Channel 75x40 1.8m and Flat 65x6 1.0m) are correctly and reliably evaluated for HT poles.
- **Default Fallback Iron Recipes**: Restored stable structural iron fallback recipes for both LT and HT poles, preventing errors where unassigned iron recipes would omit basic pole iron.

#### 💾 Permanent Recipe Deletion
Resolved an issue where deleting a factory recipe from the database (such as the default LT iron recipe) would cause it to be recreated and reappear when restarting the application. The system now permanently respects your deletion decisions across relaunches.

#### 🔧 Stability & Automated Build Fixes
Corrected internal dependency compilation and packaging steps to ensure that standalone builds generated on GitHub Releases load instantly and run reliably out-of-the-box.

---

## v7.6 — May 19, 2026

### What's New

#### 🛠️ Iron Recipes
Added new Iron Recipes to give you more granular control over iron calculations.

#### 📊 Live Iron Breakup
A live iron breakup is now visible alongside the live estimate for immediate feedback on calculations.

#### 🔧 General Enhancements
Minor adjustments and rule updates to improve the estimation engine and overall stability.

---

## v7.5 — May 17, 2026

### What's New

#### 🤖 AI Rule Creator
You can now create and manage estimation rules using plain English! Simply describe the rule to the AI Assistant, and it will handle the complex logic for you.

#### ⚡ SIN on Existing Poles
Support has been added for configuring SIN (Service Identification Number) directly on existing poles.

#### 💾 Rule Preservation
Your existing, custom-made rules are now safely preserved and will not be overwritten by application updates.

#### 📅 Extended Validity
The application's validity period has been extended until **30.06.2026**.

---

## v7.2 — April 12, 2026

### Fixes & Improvements

#### ✅ Excel / App Total Match Fix
The app now rounds every material and labour quantity to **3 decimal places before calculating the amount**, exactly matching Excel's quantity precision. This resolves the issue where the app and exported Excel workbook showed different grand totals due to hidden extra decimal precision in internal Python calculations.

#### 🔍 User Impact
- Estimates in the app now align with Excel exports for all itemized totals.
- Iron and cable quantities are handled consistently between the table display and the amount calculation.
- The final `GRAND TOTAL` no longer diverges from the worksheet total because of floating-point carryover.

---

## v7.1 — April 11, 2026

### What's New

#### ✅ Rule Enable / Disable Toggle
Every rule card in the Ruleset Manager now shows a checkbox.  Un-checking a rule disables it — it is excluded from all estimates and Excel exports — but stays in the database so you can re-enable it at any time.  Disabled rules appear dimmed with strikethrough text.

#### ⚠️ Live Rule Validation
The rule editor now checks the syntax of the **condition** and **formula** fields in real time.  A red warning banner appears beneath the formula field if the expression has a syntax error.  On save, if an error is detected you are asked to confirm before proceeding.

#### 🗂 Heights & Sizes Manager
A new **"Heights & Sizes"** tab in the Property Editor lets you manage pole heights and conductor sizes directly:
- **Pole Heights** — add or remove height values per pole type (PCC / STP / H-BEAM).  Built-in values are protected; user-added values (shown in blue) can be removed.
- **Conductor Sizes** — add or remove size options per conductor type and voltage class (LT / HT).

#### 🗄 Fully Database-Driven Heights & Conductors
`_height_options()` and `_conductor_sizes()` in the canvas editor now read directly from the database instead of hardcoded constants, so any value you add in the new manager is instantly available when placing or editing canvas objects.

#### 📦 Build Now Ships Pre-Seeded Database
`build.py` packages a pre-seeded `erp_master.db` alongside the EXE so distributed users get all rules, settings, heights, and conductor sizes on first launch without any JSON-seeding delay.

---

## v7.0 — April 11, 2026

### What's New

#### 🗄 Full Database-Driven Architecture
All configuration (rules, settings, property options, heights, conductor sizes, custom properties) is now stored in `erp_master.db`.  A new `core/db_gateway.py` module provides a unified read/write API.  JSON files are kept only as emergency backups.

---

## v6.9 — April 10, 2026

### Bug Fixes

#### 🔧 Excel Export: `openpyxl` NameError
Exporting an estimate to Excel raised a `NameError: name 'openpyxl' is not defined` because
the `generate()` method in `ExcelExporter` called `openpyxl.Workbook()` directly — but
`openpyxl` is lazily loaded (only available after calling `_xl()`).
Fixed by pulling the reference from `_xl()` before constructing the workbook.

#### ✅ All Module Imports Verified
Every project module (`canvas`, `core`, `exporters`, `ui.dialogs.*`) imports cleanly with
no stale, circular, or missing imports.

---

## v6.7 — April 10, 2026

### What's New

#### 🏷 Custom Canvas Labels
Every pole, structure, and consumer on the drawing canvas now carries a **configurable prefix with a sequential number** assigned automatically as you place objects.

| Object | Default Label | Example |
|---|---|---|
| Existing Pole | EP | EP1, EP2, EP3 … |
| New LT Pole | PP | PP1, PP2, PP3 … |
| New HT Pole | HP | HP1, HP2, HP3 … |
| DP Structure | DP | DP1, DP2 … |
| TP Structure | TP | TP1, TP2 … |
| 4P Structure | 4P | 4P1, 4P2 … |
| DTR Sub-station | DTR | DTR1, DTR2 … |
| Consumer / Service Point | SC | SC1, SC2, SC3 … |

**How to change a label prefix:**
1. Open **Settings → Placement Defaults**.
2. Go to the **🏷 Labels** tab.
3. Edit the prefix for any object type (e.g. change `PP` to `NP` for "New Pole").
4. Click **Save** — all future objects you place will use the new prefix. Existing objects keep their current number.

**Automatic renumbering on delete:**
If you delete an object, the remaining objects of the same type immediately renumber (EP1, EP2, EP4 becomes EP1, EP2, EP3 — no gaps). This is done automatically, no manual action needed.

**Labels are saved with the project:**
When you save a `.json` project file and reload it, every object comes back with its original prefix and number exactly as you left it.

#### 📝 Project Subject Limit & Smart Filename
- The **Subject** field in Project Settings is now limited to **300 characters** (roughly 4–5 lines of text). A live counter shows how many characters remain; it turns red when below 30.
- When you save or export a file, the filename is **automatically generated from the project subject**, trimmed to the first **6 words** and with characters not allowed in filenames replaced by underscores. For example, a subject of `"ERECTION OF 10 NOS POLES FOR LT OH LINE AT ABC VILLAGE"` becomes `ERECTION_OF_10_NOS_POLES_FOR.json`.
- The Save dialog **opens in the last folder you used for export**, so you no longer have to navigate there every time. If a file with the same name exists, the OS will prompt you to replace it.

---

### What Got Better

#### 📄 PDF Export
- **Dynamic title strip height** — The PDF title strip at the top of each page now automatically expands to fit the full project name, no matter how long it is. Previously, text beyond 2 lines was clipped. The strip height is calculated fresh for every page using the actual rendered text size.
- The title is left-aligned and word-wrapped, always fully visible in the exported PDF.

#### ⚡ Faster App Startup
The application now opens significantly faster. The main improvements:
- **openpyxl** (the Excel library) is no longer loaded at startup. It is loaded the first time you export an Excel file, saving ~500 ms–1 s on every launch.
- The PDF exporter (`PDFExporter`) and Excel exporter (`ExcelExporter`) are loaded on-demand instead of at startup.
- The seed database (initial material/labour records) is only parsed from disk when the database is empty; normal launches skip that work entirely.
- Several dialog modules were importing openpyxl as a dead import (never using it). These have been cleaned up.

#### 🔄 Per-Tab Reset in Placement Defaults
The **Reset to Default** button in the Placement Defaults dialog now resets **only the currently visible tab** instead of clearing everything at once. Switch to the Poles tab and reset, and your Spans and Labels settings are untouched.

---

### Bug Fixes

#### 🔧 DTR / New Structure Spans Incorrectly Flagged as Existing
When a brand-new DTR sub-station or DP/TP/4P structure was placed between two existing poles and connected with spans, the app was automatically promoting those new spans to "existing" status — meaning they would be dropped from the estimate as if they were already built. Only plain relay poles threaded between existing networks should trigger that promotion; new structures never should. Fixed.

#### 🔧 Dead End Clamp Rule: Existing Poles with Old ABC Spans
The Dead End Clamp and its erection labour were being added to the estimate for **existing poles that had only existing AB cable spans** — infrastructure already in place that should never generate a material or labour item. The rule condition was `ab_needs_dead_end` alone (no check for new vs existing spans). Fixed: the Dead End Clamp fires only when the pole has **at least one new AB cable span** attached, whether the pole itself is new or existing. Specifically:
- **New pole + new ABC span** → Dead End Clamp ✅
- **Existing pole + new ABC augmentation** → Dead End Clamp ✅ (correct — you are adding new cable)
- **Existing pole + only existing ABC spans** → No Dead End Clamp ✅ (correct — nothing new to clamp)

#### 🔧 PDF Generator Warnings ("QPainter not active")
The PDF export was printing `QPainter not active` warnings to the console on every export due to mixed PyQt6 enum types in the font metrics calculation. The height calculation for the title strip now uses `QTextDocument` (which works off-painter) instead of `QFontMetricsF`, fixing the warnings without changing the visual output.

---

### Full App Feature Reference

This section is a complete guide to everything the ERP Estimate Generator can do.

---

#### 🗺 Drawing Canvas

The canvas is the main work area. You build a network diagram here by placing poles and connecting them with spans. The estimate in the right panel updates live as you draw.

**Canvas objects:**
| Object | What it represents | How to place |
|---|---|---|
| Existing Pole (LT) | A pole already in service on a low-tension (LT) line | Select **Existing LT Pole** tool, click on canvas |
| Existing Pole (HT) | A pole already in service on a high-tension (HT) line | Select **Existing HT Pole** tool, click on canvas |
| New LT Pole | A new pole to be erected on a low-tension line | Select **New LT Pole** tool, click on canvas |
| New HT Pole | A new pole to be erected on a high-tension line | Select **New HT Pole** tool, click on canvas |
| Structure (DP/TP/4P/DTR) | Multi-pole terminal structures, including DTR sub-stations | Select **Structure** tool, click on canvas, then set type in sidebar |
| Span | A conductor run between two nodes | Select **Span** tool, click the start node, then click the end node |
| Consumer | A service connection point | Select **Consumer** tool, click near the pole it connects to |
| Symbol | A free annotation symbol on the drawing | Select **Symbol** tool, click on canvas |
| Text Box | A free text annotation | Select **Text Box** tool, click on canvas |

**Colour coding on canvas:**
- 🔵 Blue node = New LT pole
- 🔴 Red node = New HT pole
- ⬜ Grey node = Existing pole (any voltage)
- 🟢 Green node = DP/TP/4P structure
- 🟠 Orange node = DTR sub-station
- — Solid line = New span
- ― Dashed line = Existing span (not counted in estimate)

**Canvas controls:**
- **Scroll wheel** — zoom in/out
- **Middle-click drag** / **Ctrl + drag** — pan the canvas
- **Esc** — switch to Select tool
- **Delete** — remove selected object
- **Ctrl+Z / Ctrl+Y** — undo / redo
- **Right-click** on any object — edit its properties directly (without using the sidebar)

---

#### 📐 Property Editing

Select any object on the canvas to see its properties in the right-hand **Properties** panel. You can edit properties there or right-click the object directly on the canvas for a context menu.

**Pole properties:**
- Pole Type (LT / HT)
- Material (PCC / STP / H-Beam)
- Height (8MTR, 9MTR, 11MTR, etc.)
- Extension Height (0.5M, 1.0M, etc.)
- Earthing Sets
- Stay Sets
- Distribution Box Required (for AB Cable poles)
- Is Existing (marks the pole as in-service infrastructure)

**Span properties:**
- Conductor type (LT ACSR / AB Cable / HT ACSR / PVC Cable)
- Conductor size
- Wire count (for ACSR spans)
- Length (in metres)
- Is Existing Span (marks the conductor as already in service)
- Is Service Drop (marks as a consumer service connection, not a distribution span)
- Voltage level (auto-detected from connected nodes but can be overridden)

**Structure (DP/TP/4P/DTR) properties:**
- Structure Type
- Pole Material and Height
- Earthing Sets
- Stay Sets
- DTR Size (for DTR sub-station objects)

**Consumer properties:**
- Phase (Single / Three)
- Cable Size
- Agency Supply (if supply is provided by the consumer's agency)

---

#### 📊 Live Estimate Panel

The **Estimate** panel on the right shows a live bill of materials and labour as you draw. It pulls quantities from the Rule Engine and rates from the Master Database.

| Column | Description |
|---|---|
| Sl No. | Serial number |
| Code | WBSEDCL material/labour code |
| Description | Item name |
| Qty | Calculated quantity |
| Unit | Unit of measure |
| Rate | Rate from database (₹) |
| Amount | Qty × Rate (₹) |

The **Supervision** line at the bottom is calculated as a percentage of the total amount (set in Project Settings, default 10%).

**Overriding a quantity:** Double-click any Qty cell to lock it to a manual value. A lock icon appears. Click **Reset** on that row to revert to the auto-calculated quantity.

---

#### 📄 PDF Export

**Export → Export PDF Drawing** (or toolbar button 📑) exports the canvas as a multi-page A4 PDF scaled to match your chosen print scale.

**Controls at the bottom of the canvas:**

| Control | What it does |
|---|---|
| Print Scale | How much real-world area fits on one A4 page. 1:150 = more detail, 1:300 = wider area. |
| Orientation | Landscape, Portrait, Auto (picks the best globally), or Auto + Overrides (per-page manual overrides) |
| Page Overrides | Set specific pages to landscape or portrait (e.g. `2:P, 5:L`) |
| Show Symbols | Toggle detailed drawing symbols on/off |
| Page Grid | Toggle the page boundary grid on canvas |
| Crosshatch | Toggle crosshatch shading in the page margin areas |
| Project Name | Include the project subject in the PDF title strip |
| Legend | Include the legend block on the last page |

**Title strip:** Each PDF page has a title strip at the top showing the project name (word-wrapped, any length) and the page number / total pages / scale on the right.

**Footer:** Each page has a footer showing project type, date, coordinates, and app version.

**Legend (last page):** A key showing all symbol types used in the drawing, placed in the bottom-right corner of the final page. If the corner is occupied by drawing content, the legend is placed in a reserved strip above the bottom.

**Continuation marks:** When a span crosses a page boundary, a small arrow and label on each page shows where the span continues on the next page.

---

#### 📊 Excel Export

**Export → Generate Excel Estimate** (or toolbar button 📊) exports the estimate as an `.xlsx` file with two sheets:

1. **Estimate sheet** — Full bill of materials and labour with quantities, rates, and amounts. Includes project header (subject, type, date, coordinates, UH/Raw Steel selection) and a supervision charge line at the bottom.
2. **Iron Breakup sheet** — Detailed breakdown of structural iron (channels, angles, flats, GI wire) by pole source (B, C, D, E sections) with 3% wastage and sag applied, in metres and kilograms, with unit rates and total value.

---

#### 📦 Project Bundle

**Export → Save PDF + Excel + JSON Bundle** exports all three files (drawing PDF, estimate Excel, project JSON) into a single folder in one click. The folder and all file names are generated from the project subject.

---

#### 💾 Save & Load

- **File → Save** (`Ctrl+S`) — saves the current drawing and project settings as a `.json` file. All poles, spans, structures, consumers, labels, span types, and overrides are saved.
- **File → Open** (`Ctrl+O`) — loads a previously saved `.json` project file.
- **File → New Drawing** (`Ctrl+N`) — clears the canvas and resets all counters. Asks for confirmation if there is unsaved work.
- **Autosave** — the app automatically saves to `autosave_erp.json` every time you make a change. On the next launch, it restores the last session automatically.

---

#### ⚙ Project Settings

Open via **File → Project Settings** or the ⚙ toolbar button. Sets project-level properties that affect the estimate:

| Setting | Description |
|---|---|
| Subject | Project name / description (max 300 chars). Shown in PDF title strip and Excel header. |
| Project Type | NSC / FDS / UG — affects which rule conditions fire |
| UH Materials | Toggle between UH readymade materials and raw steel (affects which items are included) |
| Supervision Rate | Percentage added as supervision charge on the estimate total |
| Latitude / Longitude | Project coordinates — shown in PDF footer and Excel header |

---

#### 🔧 Placement Defaults

Open via **Settings → Placement Defaults** or the 🔧 toolbar button. Sets default values pre-filled whenever you place a new object.

**Poles tab:** default pole type, material, height, earthing and stay counts for LT and HT poles.

**Spans / Service Drops tab:** default conductor, wire count, and span lengths for distribution spans and service drops.

**🏷 Labels tab:** the prefix used for each object type. Edit a prefix and save — new objects will use the new prefix. Each tab has its own **↩ Reset this tab** button to restore factory defaults for that tab only.

---

#### 📋 Rule Engine & Ruleset Manager

The estimate is calculated by a set of **rules** stored in `data/rules.json`. Each rule defines:
- Which object type it applies to (SmartPole, SmartStructure, SmartSpan, SmartConsumer)
- A **condition** (a Python expression evaluated against the object's properties)
- A **formula** (a Python expression that calculates the quantity)
- The **material or labour item** to add to the estimate

**To edit rules:** open **Settings → Ruleset Manager**. You can add, edit, delete, and test rules. The Simulator lets you set object properties and see which rules fire and what quantities they produce before committing a change.

---

#### 🗄 Master Database

**Settings → Master Database** opens the database manager where you can:
- View all materials and labour items with their codes, rates, and units.
- Edit a rate directly in the table.
- Add new materials or labour items.
- Export the full database to Excel for offline review.
- Import a modified Excel file back into the database.

The database is stored in `erp_master.db` (SQLite) in the application folder. It uses WBSEDCL FY 2023-24 rates as the baseline.

---

#### 📖 Help

Press **F1** or open **Help → User Guide** to open the built-in HTML help guide in your default browser.

---

## v6.7 — April 10, 2026

### What's New
- **Automated releases** — Each version is now published automatically to GitHub Releases when tagged. The ZIP package is built on GitHub's servers and attached to the release for direct download.
- Right-click property editing and numeric input dialogs from v6.6 are included in this release.

---

## v6.6 — April 10, 2026

### What's New
- **Right-click property editing on canvas** — Right-click any pole, structure, span, or consumer directly on the drawing canvas to instantly edit its properties without switching to the sidebar. The sidebar and right-click menu stay in perfect sync — a change from either place reflects in both.
- **Smarter input for numbers** — Numeric fields like "Earthing Sets", "Stay Sets", and "Length" now open a clean input dialog where you type the value directly. Previously these were long dropdown lists going from 0–20 which was awkward to scroll through.

### What Got Better
- Right-clicking on empty canvas space still switches to the Select tool, so accidental right-clicks don't break your workflow.
- The context menu shows the current value for each field so you always know what's set before editing.

### How to Use Right-Click Editing
1. Make sure the Select tool is active (press **Esc** or click the arrow icon).
2. Right-click any pole, structure, span, or consumer on the canvas.
3. A menu appears — hover over a property like **Material** or **Conductor** to pick from a sub-list with the current value already ticked.
4. For numbers like **Earthing Sets** or **Length**, click the item to open a number input box, type your value, and press OK.
5. The change saves instantly and the sidebar updates to match.

---

## v6.5 — April 9, 2026

### What's New
- **PVC Cable labour updated** — The labour rate for stringing PVC Cable on new distribution spans has been corrected to *Stringing & Sagging of PVC Cable* at ₹1,592 per KM (was previously using the wrong "Laying & Dressing" item at ₹15,000/KM). All estimates with PVC Cable spans will now calculate correctly.
- **Iron Breakup sheet restored in Excel export** — The detailed iron breakup breakdown was missing from exported Excel files in the previous version. This is now fully working again — you will see the "Iron Breakup" sheet with pole-wise iron quantities when you export to Excel.

### What Got Fixed
- Fixed crashes when opening the **Select Material** or **Select Labour** dialogs inside the Rule Editor. The app would crash with an error immediately on clicking Select — this is resolved.
- Fixed the **Database Manager** dialog crashing on open.
- Fixed **material and labour searches** not finding results because the database path was incorrect in the packaged build.

### How to Verify PVC Cable Rate
1. Draw a new span and set Conductor = **PVC Cable**.
2. Mark it as a distribution span (Is Distribution Span = True in the rule context).
3. Click **Refresh Estimate** — the labour line should now show *Stringing & Sagging of PVC Cable* with quantity in KM.

---

## v6.4 — April 9, 2026

### What Got Fixed
- Fixed a crash when opening the **Rule Editor** and clicking **Select Material** or **Select Labour** — the dialog would immediately crash. Now opens correctly.
- Fixed the **Search** dialog not connecting to the database when opened from the Rule Editor.
- Fixed **Database Manager** not loading material/labour records in the packaged (installed) version.
- General stability improvements for the packaged build — several internal file paths that worked in development but broke in the installed version have been corrected.

---

## v6.3 — March 2026

### What's New
- **Detail View toggle** — Switch between a simplified symbol view and a detailed drawing view for the canvas using the View menu. Useful for printing cleaner drawings.
- **Structure objects on canvas** — DP, TP, 4P, and DTR structures can now be placed as independent objects on the canvas (separate from poles), with their own property editor.
- **Consumer objects** — Consumers (service connections) can be placed on the canvas and connected to poles via service drops.
- **Iron Breakup sheet in Excel** — Excel export now includes a dedicated "Iron Breakup" sheet showing iron weight per pole type.
- **AB Cable distribution box** — LT poles with AB Cable spans automatically add a distribution box to the estimate. Can be toggled per pole.

### How to Place a Structure
1. Select the **Structure** tool from the toolbar.
2. Click on the canvas where the structure (DP/TP/4P/DTR) should go.
3. Right-click or use the sidebar to set Structure Type, Pole Material, Height, Earthing, and Stay sets.
4. Draw spans connecting to/from the structure as usual.

---

## v6.2 — February 2026

### What's New
- **Rule Engine overhaul** — The estimate calculation engine is now fully dynamic. All material and labour items are driven by rules in `rules.json`, which can be edited via the built-in Rule Editor without touching any code.
- **Rule Editor (Ruleset Manager)** — A full-featured dialog to view, add, edit, and delete rules. Rules show colour-coded condition summaries so you can understand at a glance what each rule applies to.
- **Custom property slots** — You can define extra properties per object type (e.g. OLD_IRON, ROAD_CROSSING) via the Property Catalog, and reference them in rule conditions.
- **Auto-stay calculation** — Stay wire sets are calculated automatically based on span angles. A lock icon appears when you manually override it, and a Reset button reverts to auto.

### How to Edit Rules
1. Go to **Edit → Rule Editor** from the menu bar.
2. Browse the list of material and labour rules.
3. Click a rule to see its condition, material/labour item, quantity formula, and unit.
4. Use the **+** button to add a new rule, or select a rule and click **Edit** to modify it.
5. Click **Save** — the estimate recalculates immediately.

---

## v6.1 — January 2026

### What's New
- **Project Setup Wizard** — On first launch (or via File → New Project), a setup wizard asks for project type (NSC/FDS/UG), Unit Head toggle, and supervision rate before you start drawing.
- **HT / LT auto-detection** — Spans are automatically classified as HT or LT based on what they're connected to. You don't need to set this manually.
- **Existing vs New span propagation** — If a new pole is placed between two existing poles and connected with spans, the system automatically recognises those spans as existing (infrastructure already in place) and removes them from the estimate.
- **SmartPole conversion** — LT poles can be converted to HT poles, DP structures, TP structures, 4P structures, or DTR structures in a single click from the property editor. Spans reconnect automatically.

### How to Start a New Project
1. Launch the app — the Project Setup Wizard opens automatically.
2. Choose your project type, set supervision rate, and click **Start**.
3. Begin placing poles using the toolbar: **LT Pole**, **HT Pole**, or **Existing Pole**.
4. Connect poles with spans using the **Span** tool.
5. The live estimate in the right panel updates as you draw.

---

## v6.0 — December 2025

### Initial Release
- First packaged release of ERP Estimate Generator for WBSEDCL project estimation.
- Canvas-based drawing tool for electrical network layouts involving LT/HT poles, structures, spans, and consumers.
- Live bill-of-materials estimate updates as you draw.
- Save and load project files (`.json`).
- Export to **Excel** (itemised BOM with quantities and rates) and **PDF** (drawing + summary).
- Built-in materials and labour database, fully editable.
- App expiry control for distribution management.
