"""Quick verification of the new config tables after v7.0 migration."""
from core.database import setup_database, DB_PATH
import sqlite3

print("Running setup_database() ...")
setup_database()

con = sqlite3.connect(DB_PATH)

tables = [r[0] for r in con.execute(
    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
).fetchall()]
print("\nAll tables:", tables)

for tbl in ("rules", "settings", "height_options", "conductor_options",
            "properties", "property_options", "extended_options",
            "custom_properties", "custom_property_options", "conductor_meta"):
    cnt = con.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
    print(f"  {tbl}: {cnt} rows")

print("\nSample rules (first 3):")
for r in con.execute("SELECT object_type, condition, item_name FROM rules LIMIT 3").fetchall():
    print(" ", r)

print("\nSample settings (canvas_lt_pole, lt_height, lt_earth_count):")
for k in ("canvas_lt_pole", "lt_height", "lt_earth_count"):
    row = con.execute("SELECT value, category FROM settings WHERE key=?", (k,)).fetchone()
    print(f"  {k} = {row}")

print("\nHeight options:")
for r in con.execute("SELECT pole_type2, height_val FROM height_options ORDER BY pole_type2, height_val").fetchall():
    print(" ", r)

print("\nConductor options sample (ACSR, LT):")
for r in con.execute(
    "SELECT size_value FROM conductor_options WHERE conductor_type='ACSR' AND voltage_class='LT'"
).fetchall():
    print(" ", r)

con.close()
print("\nDone.")
