import sqlite3

conn = sqlite3.connect('erp_master.db')
cur = conn.cursor()

# 1. Add DTR augmentation labour items
labor_items = [
    ('LAB-80', 'DTR Aug. Dismantling & Installation (upto 25KVA)', 2205.0, 'NOS'),
    ('LAB-81', 'DTR Aug. Dismantling & Installation (63KVA)', 2665.0, 'NOS'),
    ('LAB-82', 'DTR Aug. Dismantling & Installation (100KVA)', 2998.0, 'NOS'),
    ('LAB-83', 'DTR Aug. Dismantling & Installation (160/250/315KVA)', 5087.0, 'NOS'),
]

for code, name, rate, unit in labor_items:
    cur.execute(
        "INSERT OR REPLACE INTO labor (labor_code, task_name, rate, unit) VALUES (?, ?, ?, ?)",
        (code, name, rate, unit),
    )
    print(f"  Labour: {code} - {name} @ Rs.{rate}")

# 2. Add return DTR material items (rate=0 — must NOT affect estimate)
material_items = [
    ('391020541', 'Return of Defective DTR 10KVA (DAM1)', 0, 'NOS'),
    ('391021041', 'Return of Defective DTR 16KVA (DAM1)', 0, 'NOS'),
    ('391021541', 'Return of Defective DTR 25KVA (DAM1)', 0, 'NOS'),
    ('391022541', 'Return of Defective DTR 63KVA (DAM1)', 0, 'NOS'),
    ('391023441', 'Return of Defective DTR 100KVA (DAM1)', 0, 'NOS'),
    ('391030541', 'Return of Use & Healthy DTR 10KVA (UH01)', 0, 'NOS'),
    ('391031041', 'Return of Use & Healthy DTR 16KVA (UH01)', 0, 'NOS'),
    ('391031541', 'Return of Use & Healthy DTR 25KVA (UH01)', 0, 'NOS'),
    ('391032541', 'Return of Use & Healthy DTR 63KVA (UH01)', 0, 'NOS'),
    ('391033441', 'Return of Use & Healthy DTR 100KVA (UH01)', 0, 'NOS'),
]

for code, name, rate, unit in material_items:
    cur.execute(
        "INSERT OR REPLACE INTO materials (item_code, item_name, rate, unit) VALUES (?, ?, ?, ?)",
        (code, name, rate, unit),
    )
    print(f"  Material: {code} - {name}")

conn.commit()
conn.close()
print("\nDone - 4 labour + 10 material items inserted.")
