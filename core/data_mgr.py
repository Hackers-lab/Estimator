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

    # 1. Database
    user_db = get_user_data_path("erp_master.db")
    if not os.path.exists(user_db):
        # Prefer the root erp_master.db for seeding if it exists (dev/source mode)
        root_db = os.path.join(get_app_root(), "erp_master.db")
        if os.path.exists(root_db):
            shutil.copy2(root_db, user_db)
        else:
            # Fallback to empty creation or data/ folder if any
            factory_db = get_data_path("erp_master.db")
            if os.path.exists(factory_db):
                shutil.copy2(factory_db, user_db)

    # 2. Rules JSON (Used as a seed/update source)
    user_rules = get_user_data_path("rules.json")
    if not os.path.exists(user_rules):
        factory_rules = get_data_path("rules.json")
        if os.path.exists(factory_rules):
            shutil.copy2(factory_rules, user_rules)

    # 3. Defaults JSON
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

    conn = sqlite3.connect(user_db_path)
    cursor = conn.cursor()

    # --- 1. Sync Rules ---
    factory_rules_path = get_data_path("rules.json")
    if os.path.exists(factory_rules_path):
        try:
            with open(factory_rules_path, "r", encoding="utf-8") as f:
                factory_rules = json.load(f)
            
            # Fetch existing rules to check for clashing IDs
            cursor.execute("SELECT id, item_name, condition FROM rules")
            existing_db_rules = {row[0]: {"name": row[1], "cond": row[2]} for row in cursor.fetchall()}

            for r in factory_rules:
                fid = r.get("id")
                if fid is None: continue

                if fid in existing_db_rules:
                    # ID exists. Is it the same rule or a user-created clash?
                    db_rule = existing_db_rules[fid]
                    if db_rule["name"] == r.get("item_name") and db_rule["cond"] == r.get("condition"):
                        # Already in DB and matches. Skip.
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
                    "INSERT INTO rules (id, object_type, condition, formula, type, item_code, item_name, enabled, sort_order) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        fid,
                        r.get("object", ""),
                        r.get("condition", "True"),
                        r.get("formula", "1"),
                        r.get("type", "Material"),
                        r.get("item_code", ""),
                        r.get("item_name", ""),
                        r.get("enabled", 1),
                        fid # Use ID as default sort order for system rules
                    )
                )
                print(f"[DataMgr] Synced system rule ID {fid}: {r.get('item_name')}")

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
            cursor.execute("SELECT item_code, item_name FROM materials")
            existing_m = {row[0]: row[1] for row in cursor.fetchall() if row[0]}
            
            for m in seed_data.get("materials", []):
                m_code, m_name = m[0], m[1]
                if m_code in existing_m:
                    if existing_m[m_code] != m_name:
                        # CLASH: Code matches but name differs. 
                        # Rename user's version to free the code.
                        print(f"[DataMgr] Material clash on {m_code}: Renaming user version to {m_code}-USER")
                        cursor.execute("UPDATE materials SET item_code = ? WHERE item_code = ?", (f"{m_code}-USER", m_code))
                        # Update user rules that were referencing this code
                        cursor.execute("UPDATE rules SET item_code = ? WHERE item_code = ? AND id > 7000", (f"{m_code}-USER", m_code))
                    else:
                        # Matches name. Skip to preserve user's price/rate.
                        continue
                
                # Insert factory version
                cursor.execute("INSERT OR IGNORE INTO materials VALUES (?,?,?,?)", m)
                print(f"[DataMgr] Synced material: {m_name}")

            # Labor (Sync by labor_code)
            cursor.execute("SELECT labor_code, task_name FROM labor")
            existing_l = {row[0]: row[1] for row in cursor.fetchall() if row[0]}
            
            for l in seed_data.get("labor", []):
                l_code, l_name = l[0], l[1]
                if l_code in existing_l:
                    if existing_l[l_code] != l_name:
                        # CLASH
                        print(f"[DataMgr] Labor clash on {l_code}: Renaming user version to {l_code}-USER")
                        cursor.execute("UPDATE labor SET labor_code = ? WHERE labor_code = ?", (f"{l_code}-USER", l_code))
                        # Update user rules
                        cursor.execute("UPDATE rules SET item_code = ? WHERE item_code = ? AND id > 7000", (f"{l_code}-USER", l_code))
                    else:
                        continue
                
                cursor.execute("INSERT OR IGNORE INTO labor VALUES (?,?,?,?)", l)
                print(f"[DataMgr] Synced labor: {l_name}")

        except Exception as e:
            print(f"[DataMgr] Seed data sync failed: {e}")

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
