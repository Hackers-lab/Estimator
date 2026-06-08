# ERP Estimate Generator v7.9

![Version](https://img.shields.io/badge/version-7.9-blue.svg)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg)
![Framework](https://img.shields.io/badge/framework-PyQt6-brightgreen.svg)

**ERP Estimate Generator** is a powerful, interactive PyQt6 desktop application designed to automate and streamline electrical network estimation. Tailored for drafting professional project schematics, it pairs a fast, 2D CAD-like drawing canvas with a dynamic, highly configurable rule-based estimation engine.

---

## 🚀 What's New in Version 7.9

* **⚡ Massive Speed Boost:** The live estimate now recalculates **up to ~220× faster** on large drawings. A 60-pole layout that previously took several seconds per refresh now updates in well under a tenth of a second. This came from caching the rule evaluator and steel-section lookups (no more per-evaluation database hits), a non-blocking debounced refresh pipeline so placing and dragging objects stays smooth, and single-pass material/labour lookups instead of repeated full-table scans. Placing 50–60+ objects no longer makes the app stutter or hang.
* **🔌 New Service-Drop Cable Sizes:** Added **4 SQMM, 6 SQMM and 25 SQMM** to the service cable options (now available for both 1-Phase and 3-Phase connections).
* **🏠 Service Drop & Consumer Sync:** The **cable size is now editable on the service drop itself** (Phase + Cable), and it stays in sync with the connected consumer — change either side and both update. Changing a **consumer's phase now correctly updates its service drop's phase** (and keeps the cable size valid).
* **🟠 DTR Defaults to 25 KVA:** Converting a structure to a DTR now defaults its size to **25 KVA** instead of "None", saving a step on the most common transformer.
* **🎨 PDF Legend Symbols Fixed:** The drawing legend previously used generic emoji/ASCII (e.g. all DP/TP/4P structures showed the same green square). It now **draws the exact same symbols and colours as the canvas** — distinct structure shapes, real pole/consumer colours, and properly **wavy AB-Cable, PVC-Cable and Service-Drop lines** with dashed ACSR — so the legend always matches your drawing.
* **📏 Fixed Height Display Bug:** Structures and poles no longer **show "8 m" while counting "9 m"** in the estimate. The height dropdown now always reflects the value actually used in calculations.
* **♻️ Factory Reset:** A new **Settings → Reset App Data (Factory Reset)** option clears all data — drawing, settings, and the database — and restores a fresh install, after a clear confirmation prompt.
* **📅 Extended Validity:** The application's validity period has been extended until **30.07.2026**.

## 🔄 Previous Highlights (v7.8)

* **💾 Auto-Save Drawings to Documents:** Your drawings are now automatically saved to `Documents/ERP_Estimates/` as `unsaved1.json`, `unsaved2.json`, etc. whenever you create a new drawing or close the app. Only modified drawings are saved — no duplicates from simply opening and closing. The Open Project dialog now defaults to this folder for quick access.
* **🔒 Single-Instance Protection:** The app now prevents multiple instances from running at the same time. If you try to open a second window, you'll see a friendly prompt asking you to switch to the existing one. This prevents database locking and data conflicts.
* **🧩 Fixed Iron Recipe on Fresh Installation:** Iron recipes (DP, TP, DTR, Pole Iron, etc.) no longer appear blank on a fresh install. The `recipes.json` file is now correctly packaged in all distributed builds.

## 🔄 Previous Highlights (v7.7)

* **🤖 AI Rule Creator Option Restored:** The **"✨ Describe in plain English"** button has been fully restored in the Rule Editor's condition panel.
* **🛠️ Fixed HT Pole Iron & Defaults Calculation:** Corrected structural iron calculations for HT poles and restored stable fallback recipes for both LT and HT poles.
* **💾 Permanent Recipe Deletion:** Deleting a factory recipe from the database now permanently respects your deletion decisions across relaunches.
* **🔧 Automated Build Stabilization:** Corrected internal dependency compilation and packaging steps for reliable standalone builds.

## 🔄 Previous Highlights (v7.6)

* **📈 New 2026 Cost Data Rates:** The application is now fully upgraded with the new 2026 financial cost rate chart for all materials and labor tasks, ensuring highly accurate estimates aligned with current market values.
* **🛠️ Iron Recipes:** Added new Iron Recipes to give you more granular control over iron calculations.
* **📊 Live Iron Breakup:** A live iron breakup is now visible alongside the live estimate for immediate feedback on calculations.

## 🔄 Previous Highlights (v7.5)

* **🤖 AI Rule Creator:** You can now create and manage estimation rules using plain English! Simply describe the rule to the AI Assistant, and it will handle the complex logic for you.
* **⚡ SIN on Existing Poles:** Support has been added for configuring SIN (Service Identification Number) directly on existing poles.
* **💾 Rule Preservation:** Your existing, custom-made rules are now safely preserved and will not be overwritten by application updates.
* **📅 Extended Validity:** The application's validity period has been extended until **30.06.2026**.

## 🔄 Previous Highlights (v7.4)

We heavily upgraded the core estimation engine and expanded the canvas capabilities to provide unparalleled accuracy and contextual drafting:

* **📈 Improved Estimation Logic:** A completely overhauled, state-of-the-art estimation core that delivers faster, highly accurate calculations, easily handling complex multi-node network rules and edge cases.
* **🗺️ GPS Map Integration:** You can now add and overlay GPS maps directly into your drawing canvas, allowing for true-to-life, georeferenced schematic drafting and route planning.
* **🛣️ Custom Infrastructure Tools:** Enhance your schematics with our new suite of contextual drawing tools. Easily map out environmental and civil features like roads, railway lines, rivers, and plot boundaries.
* **⚙️ Robust Rule Manager:** The Rule Manager has evolved into a robust, advanced engine. It now supports complex conditional nesting, priority-based execution, and sophisticated custom logic for ultimate estimation control.

*(Looking for older updates? Features like live Excel formulas, custom canvas colors, and advanced label management introduced in v7.3 are still fully supported!)*

---

## ⚡ Core Features

### 1. Interactive Drawing Canvas
* **Smart Objects:** Drag and drop specialized elements like `SmartPole` (LT/HT), `SmartStructure` (DP, TP, 4P, DTR), and `SmartConsumer`.
* **Smart Connections:** Wire objects together using `SmartSpan`, which automatically calculates line lengths, voltage drops, and required hardware based on connected nodes.
* **Contextual Mapping:** Add underlying GPS maps and use custom drawing tools to plot roads, rail lines, and terrain limits alongside your electrical networks.
* **CAD Controls:** Smooth zooming, middle-mouse panning, and spacebar-drag navigation for a professional drafting experience.

### 2. Dynamic Rule Engine
* **Automated BOM & Labor:** Automatically evaluates the drawn canvas against a dynamic `rules.json` configuration file.
* **Advanced Logic Processing:** Granular calculations driven by our improved estimation logic compute exact material (BOM) and labor quantities, including complex structural iron weights and stay/earth requirements.

### 3. Professional Exports
* **Excel Estimates (`openpyxl`):** Generates detailed, multi-sheet workbooks complete with full standard estimates, granular "Iron Breakup" sheets, and live formulas that automatically recalculate when edited externally.
* **PDF Schematics:** Exports massive network drawings into multi-page PDFs with automatic page orientation and continuation markers.

### 4. Built-in Database
* Powered by a robust SQLite backend containing the new official 2026 master material and labor codes/rates.

---

## 💻 Tech Stack
* **Python 3.x**
* **UI & Canvas:** PyQt6 (`QGraphicsScene` / `QGraphicsView`)
* **Data Export:** `openpyxl`, `QPrinter`
* **Database:** SQLite3

---

## 📝 Release Notes & Installation
Please check the releases tab to download the standalone executable for **v7.9**. 
*(Note: Existing users upgrading to v7.9 will automatically receive all fixes and new features directly on launch, with all saved local estimates and custom overrides fully preserved!).*
