# ERP Estimate Generator — Release Notes

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
