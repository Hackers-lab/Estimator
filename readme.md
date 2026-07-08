# ERP Estimate Generator v9.0

![Version](https://img.shields.io/badge/version-9.0-blue.svg)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg)
![Framework](https://img.shields.io/badge/framework-PyQt6-brightgreen.svg)

**ERP Estimate Generator** is a powerful, interactive PyQt6 desktop application designed to automate and streamline electrical network estimation. Tailored for drafting professional project schematics, it pairs a fast, 2D CAD-like drawing canvas with a dynamic, highly configurable rule-based estimation engine.

---

## 🚀 What's New in Version 9.0

* **📊 All-Projects Billing Report:** Generate a landscape PDF summary of every invoiced project in the database — showing invoice number, date, project ID, PO, client, description, labor total, GST, grand total, and creation date with grand totals and amount in words.
* **📑 Restructured Estimate (Excel-Match):** The billing packet's estimate page now mirrors the Excel export with **Section A (Materials + escalations + sundries)**, **Section B (Labor)**, and **Section C (Overheads & Taxes — supervision, GST, cess, grand total)**.
* **📏 Separate Measurement Sheets:** New checkboxes to include **Material Measurement Sheet** and/or **Labor Measurement Sheet** — each with full pagination, page numbering, and signature blocks.
* **🏷 Copy Stamp Repositioned:** When printing on letterheads (agency header excluded), the copy designation now appears below "TAX INVOICE" as small centered text.
* **✍️ Simplified Signatures:** Abstract and Certificate pages now show only the agency signature. Measurement sheets retain all three signatures.

## 🔄 Previous Highlights (v8.1)

* **🔎 Estimate Transparency:** Right-click any line in the Live Estimate to trace exactly which objects and rules produced it.
* **⚠️ Rule Overlap Warning:** Save-time alerts for duplicate or overlapping rule conditions.
* **🏗️ Structure Extensions:** DP/TP/4P/DTR extensions now correctly add iron and erection labour.

## 🔄 Previous Highlights (v8.0)

* **📦 Windows Installer with Automatic Updates:** Ships as Setup.exe with Start-menu shortcut, checks GitHub for updates on launch.
* **🪶 Smaller, Faster Install:** Removed AI Rule Creator dependency, pruned unused Qt payload (~50% smaller download).
* **🛟 Startup Crash Log:** Full error written to `last_crash.log` if the app fails to start.

## 🔄 Previous Highlights (v7.9)

* **⚡ Massive Speed Boost:** Live estimate refresh up to ~220× faster on large drawings.
* **🔌 New Service-Drop Cable Sizes:** 4 SQMM, 6 SQMM, and 25 SQMM options added.
* **🎨 PDF Legend Symbols Fixed:** Legend now draws exact canvas symbols.
* **♻️ Factory Reset:** New Settings → Reset App Data option.

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
* **Billing Packets:** Generates comprehensive billing PDF packets with invoice, SMB cover, abstract, completion certificate, consumption report, optional estimate, measurement sheets, and project drawings.
* **Billing Reports:** Landscape PDF summary of all invoiced projects with totals.

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
Please check the releases tab to download the standalone executable for **v9.0**. 
*(Note: Existing users upgrading to v9.0 will automatically receive all fixes and new features directly on launch, with all saved local estimates and custom overrides fully preserved!).*
