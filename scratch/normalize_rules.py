from core import db_gateway
import json

def normalize_rules():
    rules = db_gateway.get_rules(enabled_only=False)
    count = 0
    for r in rules:
        cond = r.get("condition", "")
        if not cond: continue
        
        # Replace double quotes with single quotes
        new_cond = cond.replace('"', "'")
        # Normalize spaces around operators if needed, but quotes are the main issue here
        
        if new_cond != cond:
            print(f"Normalizing Rule {r.get('id')}: {cond} -> {new_cond}")
            r["condition"] = new_cond
            count += 1
            
    if count > 0:
        db_gateway.save_rules(rules)
        print(f"Successfully normalized {count} rules.")
    else:
        print("No rules needed normalization.")

if __name__ == "__main__":
    normalize_rules()
