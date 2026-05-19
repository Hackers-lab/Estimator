import sqlite3
import json
import os
import sys

workspace_dir = r"c:\Users\Pramod\Documents\GitHub\Estimator"
sys.path.insert(0, workspace_dir)

import app_config

db_path = app_config.get_user_data_path("erp_master.db")
seed_path = os.path.join(workspace_dir, "data", "seed_data.json")
rules_path = os.path.join(workspace_dir, "data", "rules.json")

print(f"Reading from SQLite database: {db_path}")
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Export Materials
cursor.execute("SELECT item_code, item_name, rate, unit FROM materials")
materials = cursor.fetchall()

# Export Labor
cursor.execute("SELECT labor_code, task_name, rate, unit FROM labor")
labor = cursor.fetchall()

seed_data = {
    "materials": materials,
    "labor": labor
}

print(f"Writing {len(materials)} materials and {len(labor)} labor tasks to {seed_path}...")
with open(seed_path, "w", encoding="utf-8") as f:
    json.dump(seed_data, f, indent=2, ensure_ascii=False)

# Export Rules
cursor.execute("SELECT id, object_type, condition, items_json FROM rules")
rules_rows = cursor.fetchall()
rules_list = []
for r in rules_rows:
    rules_list.append({
        "id": r[0],
        "object": r[1],
        "condition": r[2],
        "items": json.loads(r[3]) if r[3] else []
    })

print(f"Writing {len(rules_list)} rules to {rules_path}...")
with open(rules_path, "w", encoding="utf-8") as f:
    json.dump(rules_list, f, indent=2, ensure_ascii=False)

conn.close()
print("Export complete successfully!")
