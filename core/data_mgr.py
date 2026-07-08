import os
import shutil
import json
import sqlite3
from app_config import get_user_data_path, get_data_path, get_app_root, APP_NAME

def initialize_user_data():
    """
    Ensure the standard AppData folder exists and is populated with 
    initial database and configuration files if they don't exist.
    """
    user_dir = get_user_data_path()
    if not os.path.exists(user_dir):
        os.makedirs(user_dir, exist_ok=True)

    # Database: NEVER copy a pre-existing root erp_master.db to the user folder.
    # Copying a stale root DB brings in old hardcoded rules before the recipe migration.
    # setup_database() is called by app.py and handles fresh DB creation + seeding via
    # INSERT OR REPLACE, so the user always gets the current rules.json state.

    # Rules JSON (seed source)
    user_rules = get_user_data_path("rules.json")
    if not os.path.exists(user_rules):
        factory_rules = get_data_path("rules.json")
        if os.path.exists(factory_rules):
            shutil.copy2(factory_rules, user_rules)

    # Defaults JSON
    user_defaults = get_user_data_path("defaults.json")
    if not os.path.exists(user_defaults):
        factory_defaults = get_data_path("defaults.json")
        if os.path.exists(factory_defaults):
            shutil.copy2(factory_defaults, user_defaults)

def sync_factory_updates():
    """
    Merge new items from factory files into the user's persistent data.
    - New rules from rules.json -> user DB
    - New materials/labor from seed_data.json -> user DB
    """
    user_db_path = get_user_data_path("erp_master.db")
    if not os.path.exists(user_db_path):
        return

    conn = sqlite3.connect(user_db_path, timeout=10.0)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
    except:
        pass
    cursor = conn.cursor()

    # --- 1. Sync Rules ---
    factory_rules_path = get_data_path("rules.json")
    if os.path.exists(factory_rules_path):
        try:
            with open(factory_rules_path, "r", encoding="utf-8") as f:
                factory_rules = json.load(f)
            
            # Fetch existing rules to check for clashing IDs
            cursor.execute("SELECT id, object_type, condition FROM rules")
            existing_db_rules = {row[0]: {"object": row[1], "cond": row[2]} for row in cursor.fetchall()}

            for r in factory_rules:
                fid = r.get("id")
                if fid is None: continue

                if fid in existing_db_rules:
                    # ID exists. Is it the same rule or a user-created clash?
                    db_rule = existing_db_rules[fid]
                    if db_rule["object"] == r.get("object") and db_rule["cond"] == r.get("condition"):
                        # Condition and object match — update items_json to pick up
                        # recipe-key migrations without disturbing user-edited conditions.
                        cursor.execute(
                            "UPDATE rules SET items_json = ?, enabled = ? WHERE id = ?",
                            (json.dumps(r.get("items", [])), r.get("enabled", 1), fid)
                        )
                        continue
                    else:
                        # CLASH! User created a rule with ID fid. 
                        # We must move the user's rule to make room for the system rule.
                        cursor.execute("SELECT MAX(id) FROM rules")
                        max_id = cursor.fetchone()[0] or 7000
                        new_id = max(max_id + 1, 7101)
                        
                        print(f"[DataMgr] Resolving clash: Moving user rule ID {fid} to {new_id} to make room for system rule.")
                        cursor.execute("UPDATE rules SET id = ? WHERE id = ?", (new_id, fid))
                        # Now the ID is free, we can insert the system rule below.
                
                # Insert system rule
                cursor.execute(
                    "INSERT INTO rules (id, object_type, condition, items_json, enabled, sort_order) "
                    "VALUES (?,?,?,?,?,?)",
                    (
                        fid,
                        r.get("object", ""),
                        r.get("condition", "True"),
                        json.dumps(r.get("items", [])),
                        r.get("enabled", 1),
                        fid # Use ID as default sort order for system rules
                    )
                )
                print(f"[DataMgr] Synced system rule ID {fid}: {r.get('condition')}")

        except Exception as e:
            import traceback
            print(f"[DataMgr] Rule sync failed: {e}")
            traceback.print_exc()

    # --- 2. Sync Seed Data (Materials & Labor) ---
    seed_path = get_data_path("seed_data.json")
    if os.path.exists(seed_path):
        try:
            with open(seed_path, "r", encoding="utf-8") as f:
                seed_data = json.load(f)
            
            # Materials (Sync by item_code)
            try:
                cursor.execute("SELECT item_code, item_name FROM materials")
                existing_m = {row[0]: row[1] for row in cursor.fetchall() if row[0]}
            except sqlite3.OperationalError as e:
                err = str(e).lower()
                if "no such column: item_code" in err:
                    cursor.execute("ALTER TABLE materials ADD COLUMN item_code TEXT")
                    existing_m = {}
                else:
                    raise
            
            for m in seed_data.get("materials", []):
                m_code, m_name, m_rate, m_unit = m[0], m[1], m[2], m[3]
                
                # Check for existing items with this code to handle potential duplicates
                cursor.execute("SELECT item_name FROM materials WHERE item_code = ?", (m_code,))
                db_names = [row[0] for row in cursor.fetchall() if row[0]]
                
                if db_names:
                    if m_name in db_names:
                        # Canonical name matches. Update its rate and unit
                        cursor.execute(
                            "UPDATE materials SET rate = ?, unit = ? WHERE item_code = ? AND item_name = ?",
                            (m_rate, m_unit, m_code, m_name)
                        )
                    else:
                        # Name differs. Update the first matched name to the canonical name, rate, and unit
                        cursor.execute(
                            "UPDATE materials SET item_name = ?, rate = ?, unit = ? WHERE item_code = ? AND item_name = ?",
                            (m_name, m_rate, m_unit, m_code, db_names[0])
                        )
                    # Delete any other duplicate rows under this code that don't match the canonical name
                    cursor.execute(
                        "DELETE FROM materials WHERE item_code = ? AND item_name != ?",
                        (m_code, m_name)
                    )
                else:
                    # Insert new factory version
                    cursor.execute("INSERT OR IGNORE INTO materials VALUES (?,?,?,?)", m)
                    print(f"[DataMgr] Synced material: {m_name}")

            # Labor (Sync by labor_code)
            cursor.execute("SELECT labor_code, task_name FROM labor")
            existing_l = {row[0]: row[1] for row in cursor.fetchall() if row[0]}
            
            for l in seed_data.get("labor", []):
                l_code, l_name, l_rate, l_unit = l[0], l[1], l[2], l[3]
                
                cursor.execute("SELECT task_name FROM labor WHERE labor_code = ?", (l_code,))
                db_names = [row[0] for row in cursor.fetchall() if row[0]]
                
                if db_names:
                    if l_name in db_names:
                        cursor.execute(
                            "UPDATE labor SET rate = ?, unit = ? WHERE labor_code = ? AND task_name = ?",
                            (l_rate, l_unit, l_code, l_name)
                        )
                    else:
                        cursor.execute(
                            "UPDATE labor SET task_name = ?, rate = ?, unit = ? WHERE labor_code = ? AND task_name = ?",
                            (l_name, l_rate, l_unit, l_code, db_names[0])
                        )
                    cursor.execute(
                        "DELETE FROM labor WHERE labor_code = ? AND task_name != ?",
                        (l_code, l_name)
                    )
                else:
                    cursor.execute("INSERT OR IGNORE INTO labor VALUES (?,?,?,?)", l)
                    print(f"[DataMgr] Synced labor: {l_name}")

        except Exception as e:
            print(f"[DataMgr] Seed data sync failed: {e}")

    # --- 3. Sync Settings (rate_chart_base_year: 2024 -> 2026) ---
    try:
        cursor.execute("SELECT value FROM settings WHERE key='rate_chart_base_year'")
        row = cursor.fetchone()
        if row:
            if row[0] == "2024":
                print("[DataMgr] Synced rate_chart_base_year from 2024 to 2026")
                cursor.execute("UPDATE settings SET value='2026' WHERE key='rate_chart_base_year'")
        else:
            cursor.execute(
                "INSERT INTO settings (key, value, category) VALUES (?, ?, ?)",
                ("rate_chart_base_year", "2026", "general")
            )
    except Exception as e:
        print(f"[DataMgr] Settings sync failed: {e}")

    conn.commit()
    conn.close()

def check_and_sync():
    """
    Check if the current app version is newer than the one that last 
    performed a sync. If so, run the sync.
    """
    from app_config import APP_VERSION
    user_ver_path = get_user_data_path("version.json")
    
    current_ver = str(APP_VERSION)
    stored_ver = ""
    
    if os.path.exists(user_ver_path):
        try:
            with open(user_ver_path, "r") as f:
                stored_ver = json.load(f).get("version", "")
        except:
            pass

    # If version differs, or it's the first time, run sync
    if current_ver != stored_ver:
        print(f"[DataMgr] New version detected ({current_ver} vs {stored_ver}). Syncing factory data...")
        sync_factory_updates()
        
        # Save new version to prevent re-syncing every launch
        try:
            with open(user_ver_path, "w") as f:
                json.dump({"version": current_ver}, f)
        except:
            pass
    else:
        # Same version, skip heavy sync
        pass
