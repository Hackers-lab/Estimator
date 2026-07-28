import sqlite3, json
conn = sqlite3.connect('erp_master.db')
cur = conn.cursor()

for key in ['POLE_LT_IRON', 'AB_CABLE_CLAMP']:
    cur.execute('SELECT recipe_key, name, items_json FROM recipes WHERE recipe_key = ?', (key,))
    row = cur.fetchone()
    if row:
        print(f"\n=== {row[0]}: {row[1]} ===")
        items = json.loads(row[2])
        print(json.dumps(items, indent=2))

conn.close()
