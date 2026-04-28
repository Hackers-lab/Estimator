import sqlite3
import os

DB_PATH = "erp_master.db"

def cleanup_and_renumber():
    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH}")
        return

    con = sqlite3.connect(DB_PATH)
    try:
        cur = con.cursor()
        
        # 1. Delete junk rules
        print("Deleting 'New Rule' placeholders...")
        cur.execute("DELETE FROM rules WHERE item_name LIKE 'New Rule%'")
        deleted_count = cur.rowcount
        print(f"Deleted {deleted_count} junk rules.")

        # 2. Fetch all remaining rules ordered by their current sort_order
        cur.execute("SELECT object_type, condition, formula, type, item_code, item_name, enabled, sort_order FROM rules ORDER BY sort_order, id")
        rules = cur.fetchall()
        print(f"Found {len(rules)} active rules to preserve.")

        # 3. Truncate and reset
        print("Truncating rules table and resetting sequence...")
        cur.execute("DELETE FROM rules")
        cur.execute("DELETE FROM sqlite_sequence WHERE name='rules'")
        
        # 4. Re-insert with fresh IDs (starting from 1 automatically)
        print("Re-inserting rules with new IDs...")
        for i, r in enumerate(rules):
            cur.execute(
                "INSERT INTO rules (object_type, condition, formula, type, item_code, item_name, enabled, sort_order) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (r[0], r[1], r[2], r[3], r[4], r[5], r[6], i) # Using loop index as new sort_order too
            )
        
        con.commit()
        print(f"Successfully renumbered {len(rules)} rules starting from ID 1.")
        
    except Exception as e:
        con.rollback()
        print(f"Error during maintenance: {e}")
    finally:
        con.close()

if __name__ == "__main__":
    cleanup_and_renumber()
