import os
import re
import logging

def get_latest_save():
    local_app_data = os.environ.get('LOCALAPPDATA')
    if not local_app_data:
        return None
    save_path = os.path.join(local_app_data, 'kenshi', 'save')
    if not os.path.exists(save_path):
        return None
    
    saves = [os.path.join(save_path, d) for d in os.listdir(save_path) if os.path.isdir(os.path.join(save_path, d))]
    if not saves:
        return None
        
    saves.sort(key=lambda x: os.path.getmtime(x), reverse=True)
    return saves[0]

def scan_platoon_for_characters(platoon_path):
    """Heuristic scan, not a parse of the .platoon layout: any capitalised ASCII run in the binary is a candidate name, so results include junk."""
    try:
        with open(platoon_path, 'rb') as f:
            data = f.read()
            
        matches = re.findall(b'([A-Z][a-z]{2,15})', data)
        names = []
        for m in matches:
            name = m.decode('utf-8')
            if name in ['The', 'And', 'But', 'For', 'With', 'From', 'This']: continue
            names.append(name)
        return list(set(names))
    except Exception as e:
        logging.error(f"Error scanning {platoon_path}: {e}")
        return []

def build_world_index():
    latest = get_latest_save()
    if not latest:
        logging.warning("No Kenshi saves found.")
        return {}
        
    logging.info(f"Scanning save: {latest}")
    platoon_dir = os.path.join(latest, 'platoon')
    if not os.path.exists(platoon_dir):
        return {}
        
    script_dir = os.path.dirname(os.path.abspath(__file__))
    mod_dir = os.path.dirname(os.path.dirname(script_dir))
    
    registry_dir = os.path.join(mod_dir, "sentient_sands_registry")
    
    if not os.path.exists(registry_dir):
        dev_reg = os.path.join(mod_dir, "mod", "sentient_sands_registry")
        if os.path.exists(dev_reg):
            registry_dir = dev_reg
    
    if not os.path.exists(registry_dir):
        os.makedirs(registry_dir)

    index = {}
    for f in os.listdir(platoon_dir):
        if f.endswith('.platoon'):
            chars = scan_platoon_for_characters(os.path.join(platoon_dir, f))
            for name in chars:
                if name not in index:
                    index[name] = []
                index[name].append(f)
                
                clean_name = re.sub(r'[^\w\s-]', '', name).strip()
                if not clean_name: continue
                reg_file = os.path.join(registry_dir, f"{clean_name.replace(' ', '_')}_init.txt")
                if not os.path.exists(reg_file):
                    with open(reg_file, "w") as rf:
                        rf.write(f"Registry: {name} initialized from save persistence ({f}).\n")

    return index

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    idx = build_world_index()
    for name, files in list(idx.items())[:10]:
        print(f"{name}: {files}")
