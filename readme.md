# ERP Estimate Generator v7.3

![Version](https://img.shields.io/badge/version-7.3-blue.svg)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg)
![Framework](https://img.shields.io/badge/framework-PyQt6-brightgreen.svg)

**ERP Estimate Generator** is a powerful, interactive PyQt6 desktop application designed to automate and streamline electrical network estimation. Tailored for drafting professional project schematics, it pairs a fast, 2D CAD-like drawing canvas with a dynamic, highly configurable rule-based estimation engine.

---

## 🚀 What's New in Version 7.3

We’ve completely upgraded the drafting and exporting experience to give you maximum control over your estimates:

* **📊 Live Excel Formulas:** The exported Excel sheets now contain active formulas. You can edit the exported spreadsheets externally, and the totals will automatically recalculate.
* **🛠️ Custom Canvas Properties:** You can now add and define your own custom properties directly on canvas objects for greater flexibility.
* **🎨 Custom Object Colors:** Fully personalize your network diagrams by managing and customizing the colors of your canvas components.
* **🏷️ Advanced Label Management:** Take complete control over your schematic numbering. Easily manage labels (e.g., set "PP1" for new poles and "EP1" for existing poles).
* **⚙️ Simplified Rule Manager:** The Rule Manager has been heavily streamlined and updated with more conditions, making it easier than ever to configure custom estimation logic.
* **🔠 Extra Text & Symbols:** Enhance your network drawings with newly added text features and additional schematic symbol options.

---

## ⚡ Core Features

### 1. Interactive Drawing Canvas
* **Smart Objects:** Drag and drop specialized elements like `SmartPole` (LT/HT), `SmartStructure` (DP, TP, 4P, DTR), and `SmartConsumer`.
* **Smart Connections:** Wire objects together using `SmartSpan`, which automatically calculates line lengths, voltage drops, and required hardware based on connected nodes.
* **CAD Controls:** Smooth zooming, middle-mouse panning, and spacebar-drag navigation for a professional drafting experience.

### 2. Dynamic Rule Engine
* **Automated BOM & Labor:** Automatically evaluates the drawn canvas against a dynamic `rules.json` configuration file.
* **Granular Calculations:** Computes exact material (BOM) and labor quantities, including complex structural iron weights and stay/earth requirements.

### 3. Professional Exports
* **Excel Estimates (`openpyxl`):** Generates detailed, multi-sheet workbooks complete with full standard estimates and granular "Iron Breakup" sheets.
* **PDF Schematics:** Exports massive network drawings into multi-page PDFs with automatic page orientation and continuation markers.

### 4. Built-in Database
* Powered by a robust SQLite backend containing official master material and labor codes/rates.

---

## 💻 Tech Stack
* **Python 3.x**
* **UI & Canvas:** PyQt6 (`QGraphicsScene` / `QGraphicsView`)
* **Data Export:** `openpyxl`, `QPrinter`
* **Database:** SQLite3

---

## 📝 Release Notes & Installation
Please check the releases tab to download the standalone executable for **v7.3**. 
*(Note: Ensure any custom `rules.json` files from older versions are updated using the new Simplified Rule Manager to take advantage of the new conditions).*
