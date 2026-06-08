"""
export_db_to_seed.py
====================
Snapshot the LIVE app-data database (where all your in-app edits land) back
into the project's `data/` seed files, so the next bundled build ships your
current materials, labour, rules and recipes as the new factory baseline.

Live DB   :  %APPDATA%/ERP_Estimate/erp_master.db   (read)
Seed files:  <project>/data/seed_data.json          (materials + labour)
             <project>/data/rules.json              (rules)
             <project>/data/recipes.json            (iron recipes)

Run:  python export_db_to_seed.py
"""
import sqlite3
import json
import os
import sys

# Derive the project folder from THIS file's location (portable across machines).
workspace_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, workspace_dir)

import app_config

db_path     = app_config.get_user_data_path("erp_master.db")
data_dir    = os.path.join(workspace_dir, "data")
seed_path   = os.path.join(data_dir, "seed_data.json")
rules_path  = os.path.join(data_dir, "rules.json")
recipes_path = os.path.join(data_dir, "recipes.json")

if not os.path.exists(db_path):
    print(f"ERROR: live database not found at {db_path}")
    print("Launch the app at least once so the database is created.")
    sys.exit(1)

os.makedirs(data_dir, exist_ok=True)

print(f"Reading from SQLite database: {db_path}")
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# ── Materials + Labour → seed_data.json ───────────────────────────────────────
cursor.execute("SELECT item_code, item_name, rate, unit FROM materials")
materials = cursor.fetchall()
cursor.execute("SELECT labor_code, task_name, rate, unit FROM labor")
labor = cursor.fetchall()

seed_data = {"materials": materials, "labor": labor}
print(f"Writing {len(materials)} materials and {len(labor)} labour tasks to seed_data.json...")
with open(seed_path, "w", encoding="utf-8") as f:
    json.dump(seed_data, f, indent=2, ensure_ascii=False)

# ── Rules → rules.json (list of {id, object, condition, items}) ───────────────
cursor.execute("SELECT id, object_type, condition, items_json FROM rules ORDER BY sort_order, id")
rules_list = []
for r in cursor.fetchall():
    rules_list.append({
        "id": r[0],
        "object": r[1],
        "condition": r[2],
        "items": json.loads(r[3]) if r[3] else [],
    })
print(f"Writing {len(rules_list)} rules to rules.json...")
with open(rules_path, "w", encoding="utf-8") as f:
    json.dump(rules_list, f, indent=2, ensure_ascii=False)

# ── Recipes → recipes.json (dict keyed by recipe_key) ─────────────────────────
cursor.execute("SELECT recipe_key, name, description, object_type, items_json FROM recipes")
recipes_dict = {}
for rkey, name, desc, obj_type, items_json in cursor.fetchall():
    recipes_dict[rkey] = {
        "name": name,
        "description": desc or "",
        "object_type": obj_type or "SmartStructure",
        "items": json.loads(items_json) if items_json else [],
    }
print(f"Writing {len(recipes_dict)} recipes to recipes.json...")
with open(recipes_path, "w", encoding="utf-8") as f:
    json.dump(recipes_dict, f, indent=2, ensure_ascii=False)

conn.close()
print("\nExport complete. The project data/ seed files now match your live database.")
print("NOTE: steel sections, project types and the rule tree are seeded from")
print("      core/database.py + core/constants.py (not these JSON files) — edit")
print("      those in code if you changed them in-app.")
