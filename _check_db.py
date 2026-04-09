import sqlite3
from core.database import DB_PATH
conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()
cur.execute("SELECT labor_code, task_name, rate, unit FROM labor WHERE task_name LIKE '%PVC%' OR task_name LIKE '%String%'")
print("PVC/Stringing:", cur.fetchall())
cur.execute("SELECT labor_code, task_name FROM labor ORDER BY labor_code DESC LIMIT 8")
print("Top codes:", cur.fetchall())
conn.close()
