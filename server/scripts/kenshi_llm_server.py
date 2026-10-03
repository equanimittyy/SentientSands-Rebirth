# Sentient Sands - Kenshi AI Mod
# Copyright (C) 2026 Sentient Sands Team
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import os
import ctypes
import json
import logging
import subprocess
import requests
import re
import time
import threading
import random
import configparser
import mimetypes
from flask import Flask, Response, request, jsonify
from werkzeug.exceptions import HTTPException
import sys

SCRIPT_PATH = os.path.abspath(__file__)
SCRIPT_DIR = os.path.dirname(SCRIPT_PATH)
KENSHI_SERVER_DIR = os.path.dirname(SCRIPT_DIR)
KENSHI_MOD_DIR = os.path.dirname(KENSHI_SERVER_DIR)

# The embedded runtime's ._pth file runs Python isolated, which leaves the script dir off sys.path
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from request_guard import is_request_allowed
from browser_launch import PanelTabs, open_when_ready
import llm_config
import llm_router
import campaign_db
import prompt_store
import world_template
import log_setup
from log_setup import llm_log

def resolve_mod_file(filename):
    """Falls back to the repo's mod/ subdirectory when run from a source checkout."""
    path = os.path.join(KENSHI_MOD_DIR, filename)
    if os.path.exists(path):
        return path
        
    dev_dir = os.path.join(KENSHI_MOD_DIR, "mod")
    if os.path.isdir(dev_dir):
        return os.path.join(dev_dir, filename)

    return path

INI_PATH = resolve_mod_file("SentientSands_Config.ini")
LLM_CONFIG_PATH = os.path.join(KENSHI_SERVER_DIR, "user", "llm_config.json")
DEFAULT_MODELS_PATH = os.path.join(KENSHI_SERVER_DIR, "config", "default_models.json")
DEFAULT_PROVIDERS_PATH = os.path.join(KENSHI_SERVER_DIR, "config", "default_providers.json")
NAMES_PATH = os.path.join(KENSHI_SERVER_DIR, "config", "names.json")
GENERIC_NAMES_PATH = os.path.join(KENSHI_SERVER_DIR, "config", "generic_names.json")
LOCALIZATION_PATH = os.path.join(KENSHI_SERVER_DIR, "config", "localization.json")
WEB_DIR = os.path.join(KENSHI_SERVER_DIR, "web")

NAMES_CONFIG = {}
GENERIC_CONFIG = {}
ACTIVE_CAMPAIGN = "Default"

CAMPAIGNS_DIR = os.path.join(KENSHI_SERVER_DIR, "campaigns")
PROMPTS_DIR = os.path.join(KENSHI_SERVER_DIR, "prompts")
USER_PROMPTS_DIR = os.path.join(KENSHI_SERVER_DIR, "user", "prompts")
WORLD_TEMPLATES_DIR = os.path.join(KENSHI_SERVER_DIR, "world_templates")
USER_TEMPLATES_DIR = os.path.join(KENSHI_SERVER_DIR, "user", "world_templates")
DEFAULT_TEMPLATE = "vanilla_kenshi"
# The defaults of a new campaign's player profile, not prompts, so the Prompts page leaves them out
CAMPAIGN_TEXTS = ("character_bio.txt",)

PROFILES_IN_PROGRESS = set()
PROGRESS_LOCK = threading.Lock()
LIVE_CONTEXTS = {}
PLAYER_CONTEXT = {}
PLAYER2_SESSION_KEY = None
EVENT_THROTTLE = {} 
THROTTLE_LOCK = threading.Lock()
LAST_STATE_LOG = {} # {"<target>|<etype>": last message}
STATE_LOCK = threading.Lock()
SYNTHESIS_STATUS = {"elapsed": 0, "interval": 60}
SEEN_FACTIONS = set()

ANIMAL_RACES = [
    "Bonedog", "Boneyard Wolf", "Garru", "Beak Thing", "Gorillo",
    "Landbat", "Goat", "Bull", "Leviathan", "Blood Spider", "Skin Spider",
    "Cave Crawler", "Crab", "Raptor", "Darkfinger", "Thrasher", "Cleaner",
    "Crimper", "Skimmer", "Beeler", "Bat", "Spider", "Wolf",
    "Dog", "Turtle", "Cleanser", "Gurgler", "Fishman"
]

def describe_faction(name, faction_id=None):
    if not name or name == "Unknown":
        return "Unknown Faction (Remnant or Drifter)"
    faction = campaign_db.find_faction(faction_id, name)
    if not faction or not (faction["description"] or faction["fields"] or faction["major"]):
        return f"{name}: A minor or specialized group in the wasteland."
    details = "; ".join(f"{key}: {', '.join(value) if isinstance(value, list) else value}" for key, value in faction["fields"].items())
    text = f"{faction['name']} ({details})" if details else faction["name"]
    return f"{text}: {faction['description']}" if faction["description"] else text

def note_faction(ctx, is_player=False):
    """Records each faction that the game reports, so the player can describe a modded or minor faction on the Campaigns page."""
    faction_id, name = ctx.get("factionID"), ctx.get("faction")
    # The plugin sends the name as the ID, or "Neutral", when the faction has no string ID
    if not faction_id or not name or faction_id in (name, "Neutral"):
        return
    key = (faction_id, name, is_player)
    if key in SEEN_FACTIONS:
        return
    try:
        campaign_db.note_faction(faction_id, name, is_player)
        SEEN_FACTIONS.add(key)
    except campaign_db.CampaignUnavailable:
        pass  # load_campaign_config already logged why, and the plugin posts a context every 5 s
    except Exception as e:
        logging.warning(f"CAMPAIGN: Cannot record the faction {name}: {e}")

def get_config_radii():
    settings = load_settings()
    r = float(settings.get('radiant_range', 100.0))
    t = float(settings.get('talk_radius', 100.0))
    y = float(settings.get('yell_radius', 200.0))
    return r, t, y
def sanitize_llm_text(text):
    if not text: return ""
    # Kenshi's engine chokes on these non-ASCII characters
    replacements = {
        '\u2018': "'", '\u2019': "'",
        '\u201c': '"', '\u201d': '"',
        '\u2013': '-', '\u2014': '-',
        '\u2026': '...',
        '\u00a0': ' ',
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    
    text = text.replace('\r\n', '\n')
    text = text.replace('\\n', '\n')
    text = text.replace('\\r', '')
    return text

def robust_json_parse(text):
    if not text: return None
    
    text = text.strip()
    
    start = text.find('{')
    end = text.rfind('}')
    if start == -1 or end == -1:
        return None
    
    json_str = text[start:end+1]
    
    json_str = re.sub(r',\s*([}\]])', r'\1', json_str)
    
    json_str = re.sub(r'//.*?\n', '\n', json_str)
    json_str = re.sub(r'/\*.*?\*/', '', json_str, flags=re.DOTALL)
    
    try:
        return json.loads(json_str)
    except Exception as eFirst:
        # Unescaped quotes between word characters are usually dialogue quotes inside a value
        try:
            sanitized = re.sub(r'(?<=[a-zA-Z0-9])"(?=[a-zA-Z0-9\s])', "'", json_str)
            return json.loads(sanitized)
        except:
            logging.warning(f"LLM: Cannot parse the reply as JSON: {json_str[:200]}...")
            raise eFirst

log_setup.setup(os.path.join(KENSHI_SERVER_DIR, "logs"))

def kill_old_servers():
    try:
        result = subprocess.run(
            ['netstat', '-aon'], capture_output=True, text=True, shell=True
        )
        for line in result.stdout.splitlines():
            if ':5000' in line and 'LISTENING' in line:
                parts = line.strip().split()
                pid = int(parts[-1])
                if pid > 0 and pid != os.getpid():
                    logging.info(f"SYSTEM: Stopping the old server process (PID {pid}) on port 5000.")
                    subprocess.run(['taskkill', '/F', '/PID', str(pid)], 
                                 capture_output=True, shell=True)
                    time.sleep(1)
    except Exception as e:
        logging.warning(f"SYSTEM: Cannot check port 5000 for an old server: {e}")

kill_old_servers()

# A Windows registry entry can map .js to text/plain, and browsers refuse to run a module script with that type
mimetypes.add_type("text/javascript", ".js")
app = Flask(__name__, static_folder=WEB_DIR, static_url_path="/web")
# ASCII-only responses: the plugin's UnescapeJSON decodes the \u escapes
app.json.ensure_ascii = True

@app.errorhandler(Exception)
def handle_exception(e):
    if isinstance(e, HTTPException):
        return jsonify({"error": e.description, "status": "error"}), e.code
    if isinstance(e, campaign_db.CampaignUnavailable):
        logging.warning(f"HTTP: {request.path} needs a campaign: {e}")
        return jsonify({"error": str(e), "status": "error"}), 409
    logging.exception(f"HTTP: Unhandled exception in {request.path}: {e}")
    try:
        if request.json:
            logging.debug(f"HTTP: Request body: {json.dumps(request.json)}")
    except:
        pass
    return jsonify({"error": str(e), "status": "error"}), 500

@app.before_request
def reject_foreign_requests():
    host = request.headers.get("Host")
    origin = request.headers.get("Origin")
    if not is_request_allowed(host, origin):
        logging.warning(f"HTTP: Rejected request to {request.path}: Host={host}, Origin={origin}")
        return jsonify({"status": "error", "message": "Forbidden"}), 403

def load_configs():
    global NAMES_CONFIG
    logging.debug("CONFIG: Loading the name, generic name, and localization files.")
    
    config_dir = os.path.join(KENSHI_SERVER_DIR, "config")
    if not os.path.exists(config_dir):
        os.makedirs(config_dir)

    if os.path.exists(NAMES_PATH):
        try:
            with open(NAMES_PATH, "r") as f:
                NAMES_CONFIG = json.load(f)
            logging.debug(f"CONFIG: Loaded {len(NAMES_CONFIG)} gender pools from names.json.")
        except Exception as e:
            logging.error(f"CONFIG: Cannot load names.json: {e}")

    if os.path.exists(GENERIC_NAMES_PATH):
        try:
            global GENERIC_CONFIG
            with open(GENERIC_NAMES_PATH, "r") as f:
                GENERIC_CONFIG = json.load(f)
            logging.debug(f"CONFIG: Loaded {len(GENERIC_CONFIG.get('prefixes', []))} generic prefixes from generic_names.json.")
        except Exception as e:
            logging.error(f"CONFIG: Cannot load generic_names.json: {e}")

    global LOCALIZATION_CONFIG
    LOCALIZATION_CONFIG = {}
    if os.path.exists(LOCALIZATION_PATH):
        try:
            with open(LOCALIZATION_PATH, "r", encoding="utf-8") as f:
                LOCALIZATION_CONFIG = json.load(f)
            logging.debug(f"CONFIG: Loaded {len(LOCALIZATION_CONFIG)} language localizations.")
        except Exception as e:
            logging.error(f"CONFIG: Cannot load localization.json: {e}")

def get_campaign_dir():
    if not os.path.exists(CAMPAIGNS_DIR):
        os.makedirs(CAMPAIGNS_DIR)
        logging.info(f"CAMPAIGN: Created the campaigns folder {CAMPAIGNS_DIR}")
        
    cdir = os.path.join(CAMPAIGNS_DIR, ACTIVE_CAMPAIGN)
    if not os.path.exists(cdir):
        os.makedirs(cdir)
        logging.info(f"CAMPAIGN: Created the campaign folder {cdir}")
        ensure_campaign_seeded(cdir)
    return cdir

def ensure_campaign_seeded(cdir):
    try:
        for component in CAMPAIGN_TEXTS:
            src = os.path.join(PROMPTS_DIR, component)
            dst = os.path.join(cdir, component)
            if os.path.exists(src) and not os.path.exists(dst):
                import shutil
                shutil.copy2(src, dst)
                logging.info(f"CAMPAIGN: Seeded '{os.path.basename(cdir)}' with {component}")
    except Exception as e:
        logging.error(f"CAMPAIGN: Cannot seed the campaign folder {cdir}: {e}")

def load_campaign_config():
    try:
        if ACTIVE_CAMPAIGN:
            campaign_db.open_campaign(get_campaign_dir(), lambda: world_template.campaign_seed(DEFAULT_TEMPLATE, WORLD_TEMPLATES_DIR, USER_TEMPLATES_DIR))
        else:
            campaign_db.close_campaign()
        push_generic_names_to_dll()
    except Exception as e:
        logging.error(f"CAMPAIGN: Cannot load the campaign: {e}")

def send_to_pipe(cmd):
    """The plugin dispatches on these prefixes; anything else is sent as a "CMD: " command."""
    if not (cmd.startswith("CMD:") or cmd.startswith("NPC_") or cmd.startswith("PLAYER_") or cmd.startswith("NOTIFY:")):
        cmd = "CMD: " + cmd

    # The plugin re-creates its only pipe instance after each message, so a send right after another one can find no instance for a moment
    deadline = time.monotonic() + 0.25
    while True:
        try:
            with open(r'\\.\pipe\SentientSands', 'wb') as f:
                f.write(cmd.encode('utf-8'))
            return
        except OSError:
            if time.monotonic() >= deadline:
                return
            time.sleep(0.01)

def push_settings_to_plugin():
    """On a first start the plugin finds no INI and runs on the defaults of LoadPluginConfig, so the server sends each value that the plugin holds."""
    settings = load_settings()
    for var, value in (
        ("g_enableAmbient", "1" if settings["enable_ambient"] else "0"),
        ("g_ambientIntervalSeconds", settings["radiant_delay"]),
        ("g_radiantRange", settings["radiant_range"]),
        ("g_proximityRadius", settings["talk_radius"]),
        ("g_yellRadius", settings["yell_radius"]),
        ("g_chatHotkey", settings["chat_hotkey"]),
        ("g_enableWelcome", "1" if settings["enable_welcome"] else "0"),
        ("g_logLevel", settings["log_level"]),
        ("g_dialogueSpeedSeconds", settings["dialogue_speed_seconds"]),
        ("g_speechBubbleLife", settings["bubble_life"]),
    ):
        send_to_pipe(f"SET_CONFIG: {var}: {value}")
    logging.debug("PIPE: Sent the settings to the plugin.")

def push_generic_names_to_dll():
    try:
        prefixes = GENERIC_CONFIG.get("prefixes", [])
        keywords = GENERIC_CONFIG.get("keywords", [])
        p_str = ",".join(prefixes)
        k_str = ",".join(keywords)
        send_to_pipe(f"POPULATE_GENERIC: {p_str}|{k_str}")
        logging.debug("PIPE: Sent the generic name lists to the plugin.")
    except Exception as e:
        logging.error(f"PIPE: Cannot send the generic name lists to the plugin: {e}")



def is_npc_name_generic(name):
    if not name: return True
    
    # Names may carry a serial suffix: "Name|12345"
    clean_name = str(name).split('|')[0].strip()
    
    if clean_name in GENERIC_NAMES:
        return True
        
    prefixes = GENERIC_CONFIG.get("prefixes", [])
    keywords = GENERIC_CONFIG.get("keywords", [])
    
    lower_clean = clean_name.lower()
    if any(p.lower() in lower_clean for p in prefixes):
        return True
        
    if any(k.lower() in lower_clean for k in keywords):
        return True
        
    # Fallback for when generic_names.json failed to load
    if not keywords:
        default_keywords = [
            "Bandit", "Guard", "Citizen", "Soldier", "Warrior", "Heavy", "Captain", 
            "Sentinel", "Servant", "Wanderer", "Peasant", "Settler", "Thug", "Barman", "Pacifier"
        ]
        if any(k.lower() in lower_clean for k in default_keywords):
            return True
            
    return False

GENERIC_NAMES = [
    "Hungry Bandit", "Dust Bandit", "Starving Vagrant", "Drifter", "Samurai", 
    "Holy Sentinel", "Holy Servant", "Swamper", "Tech Hunter", "Mercenary",
    "Shop Guard", "Caravan Guard", "Slave Hunter", "Slaver", "Manhunter",
    "Escaped Slave", "Rebirth Slave", "United Cities Citizen", "Holy Nation Citizen",
    "Shek Warrior", "Hive Worker", "Hive Soldier", "Hive Prince", "Fogman",
    "Barman", "Pacifier", "Bar Thug",
    "Cannibal", "Outlaw", "Farmer", "Nomad", "Trader", "Gate Guard", 
    "Unknown Entity", "Someone", "Mercenary Heavy", "Mercenary Captain",
    "Holy Nation Outlaw", "Holy Nation Peasant", "United Cities Peasant",
    "Wandering Assassin", "Trader Guard", "Hiver Ronin", "Skeleton Legion",
    "Reaver", "Grass Pirate", "Black Dog", "Crab Raider", "Skeleton Bandit",
    "Bar Thug", "Barman", "Pacifier"
]

KENSHI_NAME_POOL = [
    "Kaelen", "Korg", "Vayn", "Sark", "Mina", "Rook", "Drake", "Silas", "Tane", "Kuna",
    "Zarek", "Jorn", "Lyra", "Kael", "Brena", "Torin", "Sola", "Fen", "Krax", "Vora",
    "Dax", "Nyx", "Garek", "Sora", "Thane", "Kira", "Zane", "Lara", "Marek", "Vina",
    "Rel", "Kaan", "Siv", "Tork", "Meda", "Grox", "Vael", "Syra", "Keld", "Bara",
    "Dorn", "Neld", "Gora", "Sark", "Vane", "Kura", "Zora", "Lena", "Morn", "Vora",
    "Rael", "Kona", "Sima", "Teld", "Mora", "Grak", "Vael", "Sura", "Karn", "Bena",
    "Drak", "Nala", "Gora", "Sina", "Vara", "Kela", "Zana", "Lina", "Mina", "Vorna",
    "Hark", "Skal", "Vorn", "Grek", "Myla", "Rion", "Daka", "Sith", "Tyla", "Korr",
    "Zent", "Lyr", "Brax", "Vort", "Nara", "Grel", "Syk", "Tarn", "Moko", "Vull",
    "Kess", "Tory", "Vann", "Sael", "Miro", "Lorn", "Gryf", "Dael", "Sina", "Kura"
]

def get_used_names():
    return {npc["storage_id"].split("_")[0].lower() for npc in campaign_db.list_npcs()}

def generate_unique_lore_name(gender="Neutral"):
    used = get_used_names()
    
    gender_key = "Neutral"
    if gender.lower() == "male": gender_key = "Male"
    elif gender.lower() == "female": gender_key = "Female"
    
    pool = NAMES_CONFIG.get(gender_key, [])
    if not pool and gender_key != "Neutral":
        pool = NAMES_CONFIG.get("Neutral", [])
    
    if not pool:
        pool = KENSHI_NAME_POOL
    
    available = [n for n in pool if n.lower() not in used]
    if not available:
        base = random.choice(pool if pool else KENSHI_NAME_POOL)
        for i in range(1, 1000):
            candidate = f"{base} {i}"
            if candidate.lower() not in used:
                return candidate
        return f"{base}_{random.randint(1000, 9999)}"
    
    return random.choice(available)

def get_current_time_prefix():
    if PLAYER_CONTEXT:
        day = PLAYER_CONTEXT.get('day', 0)
        hour = int(PLAYER_CONTEXT.get('hour', 0))
        minute = int(PLAYER_CONTEXT.get('minute', 0))
        return f"[Day {day}, {hour:02d}:{minute:02d}] "
    return ""

def generate_relation_bar(rel):
    try:
        rel = int(rel)
    except:
        rel = 0
    
    # rel ranges -100..100, mapped to bar slots 0..20
    pos = int((rel + 100) / 10)
    pos = max(0, min(20, pos))
    
    bar = list("---------------------")
    bar[pos] = "X"
    bar_str = "".join(bar)
    
    label = "NEUTRAL"
    if rel <= -90: label = "ARCH-ENEMY"
    elif rel <= -60: label = "HOSTILE"
    elif rel <= -25: label = "UNFRIENDLY"
    elif rel >= 90: label = "SOUL-MATE"
    elif rel >= 60: label = "ALLIED"
    elif rel >= 25: label = "FRIENDLY"
    
    # Plain text, not MyGUI color tags, so it renders on every UI version
    return f"RELATION: [{label}] [{bar_str}] ({rel:+} pts)"



# Keys are Kenshi's memory-tag enum values
SHORT_TERM_MEM = {
    1: "INTRUDER", 2: "AGGRESSOR", 3: "TEMPORARY_ALLY", 4: "TEMPORARY_ENEMY",
    5: "PRISONER", 6: "HAS_BEEN_LOOTED", 7: "CRIMINAL"
}
LONG_TERM_MEM = {
    1: "MY_INTRUDER", 2: "MY_LIFESAVER", 3: "FREED_ME", 4: "STOLE_FROM_ME",
    5: "MY_CAPTOR", 6: "FRIENDLY_AQUAINTANCE", 7: "DEFEATED_MY_SQUAD_ONCE",
    8: "SQUAD_LOST_TO_ME_ONCE", 14: "KILLED_MY_FRIEND", 15: "I_SCREWED_THIS_GUY"
}

def build_detailed_context_string(npc_name, char_data=None):
    ctx = LIVE_CONTEXTS.get(npc_name)
    
    if not ctx:
        if not char_data:
            return ""
        ctx = char_data
    
    lines = [f"CURRENT CONDITION of {npc_name}:"]

    char_state = ctx.get("character_state", "normal")
    state_labels = {
        "imprisoned":     f"CRITICAL: {npc_name} is currently IMPRISONED. They are locked up and cannot move freely. They should speak with desperation, resignation, or defiance.",
        "enslaved":       f"CRITICAL: {npc_name} is ENSLAVED and wearing shackles. They are bound to a master. They should speak with fear, exhaustion, or suppressed rage.",
        "escaped-slave":  f"CRITICAL: {npc_name} is an ESCAPED SLAVE — no longer chained but hunted. They should be paranoid, guarded, and desperate.",
        "unconscious":    f"CRITICAL: {npc_name} is UNCONSCIOUS and cannot speak.",
        "dead":           f"CRITICAL: {npc_name} is DEAD.",
    }
    if char_state in state_labels:
        lines.append(state_labels[char_state])

    race = ctx.get("race") or ctx.get("Race", "Unknown")
    gender = ctx.get("gender") or ctx.get("Sex", "Unknown")
    faction = ctx.get("faction") or ctx.get("Faction", "Unknown")
    job = ctx.get("job") or ctx.get("Job", "None")
    money = ctx.get("money") or 0
    relation = ctx.get("relation")

    lines.append(f"- RACE: {race}")
    lines.append(f"- SEX: {gender}")
    lines.append(f"- FACTION: {faction}")
    
    is_trader = ctx.get("is_trader", False)
    in_shop = ctx.get("in_shop", False)
    building_name = ctx.get("building_name", "Unknown")
    
    if is_trader or in_shop or "shopkeeper" in job.lower():
        shop_note = f"ROLE: {npc_name} is a SHOPKEEPER/TRADER."
        if in_shop:
            shop_note += f" They are currently IN THEIR SHOP ({building_name})."
        shop_note += " They are authorized to sell items and cats from their inventory in exchange for the player's cats or items."
        lines.append(shop_note)
    
    if ctx.get("is_leader", False):
        lines.append(f"ROLE: {npc_name} is the LEADER of their faction. They speak with authority and make final decisions for their group.")

    lines.append(f"- CURRENT GOAL/JOB: {job}")
    if relation is not None:
        lines.append(f"- FACTION RELATION TO PLAYER: {relation} (Stance: {'ALLIED' if relation >= 50 else 'FRIENDLY' if relation > 0 else 'NEUTRAL' if relation == 0 else 'HOSTILE' if relation <= -30 else 'UNFRIENDLY'})")
    lines.append(f"- MONEY: {money} cats")

    player_faction = PLAYER_CONTEXT.get('faction', 'Nameless')
    player_faction_id = PLAYER_CONTEXT.get("factionID")
    if faction == player_faction or (player_faction_id and ctx.get("factionID") == player_faction_id):
        lines.append(f"CRITICAL CONTEXT: {npc_name} is a member of the PLAYER'S FACTION ({player_faction}).")
        lines.append(f"THE PLAYER IS THE LEADER of this group. {npc_name} understand that they and the player are cooperating, this can take many forms such as direct leadership, partnership, or even just individuals traveling together.")
    elif (campaign_db.find_faction(ctx.get("factionID"), faction) or {}).get("major"):
        lines.append(f"LOYALTY NOTE: {npc_name} belongs to {faction}, a major world power. They are deeply rooted in their society. They will NOT desert their faction to join the player's minor squad without an EXTREMELY compelling narrative reason, high reputation, or having their life saved multiple times. Be highly resistant to recruitment.")
    med = ctx.get("medical", {})
    if med:
        blood = med.get("blood", 100)
        hunger = med.get("hunger", 300)
        limbs = med.get("limbs", {})
        
        status_parts = []
        
        if hunger < 100: status_parts.append("STARVING")
        elif hunger < 250: status_parts.append("HUNGRY")
        else: status_parts.append("WELL FED") 
        
        max_blood = med.get("max_blood", 100)
        blood_pct = blood / max_blood if max_blood > 0 else 1.0
        blood_rate = med.get("blood_rate", 0.0)
        
        if blood_rate > 0.01:
            status_parts.append("BLEEDING")
        elif blood_pct < 0.5:
            status_parts.append("WEAK FROM BLOODLOSS")
        elif blood_pct < 0.85:
            status_parts.append("INJURED")
            
        if med.get("is_unconscious"): status_parts.append("UNCONSCIOUS")
        
        lines.append(f"- CONDITION: {', '.join(status_parts) if status_parts else 'Healthy'}")
        
        injuries = []
        base_limbs = [l for l in limbs.keys() if not l.endswith("_max")]
        for limb in base_limbs:
            hp = limbs.get(limb, 100)
            hp_max = limbs.get(f"{limb}_max", 100)
            hp_pct = hp / hp_max if hp_max > 0 else 1.0
            
            if hp <= -hp_max: 
                injuries.append(f"{limb.upper()} GONE/SEVERED")
            elif hp < 0: 
                injuries.append(f"{limb.upper()} IS CRIPPLED")
            elif hp_pct < 0.5: 
                injuries.append(f"{limb.upper()} IS INJURED")
            
        if injuries: 
            lines.append(f"- INJURIES: {', '.join(injuries)}")
        else:
            lines.append("- INJURIES: None")
    
    env = ctx.get("environment", {})
    if env:
        loc = []
        if env.get("indoors"): loc.append("Indoors")
        if env.get("in_town"): loc.append(f"In town ({env.get('town_name', 'Unknown')})")
        if loc: lines.append(f"- LOCATION: {', '.join(loc)}")

    stats = ctx.get("stats", {})
    if stats:
        lines.append(f"VISIBLE POWER of {npc_name}:")
        core = [f"{k[:3].upper()}: {int(float(stats.get(k, 0)))}" for k in ["strength", "dexterity", "toughness", "perception"]]
        lines.append(f"- ATTRIBUTES: {' | '.join(core)}")
        
        notable = []
        combat_skills = ["melee_attack", "melee_defence", "dodge", "katanas", "sabres", "hackers", "heavy_weapons", "blunt", "polearms", "martial_arts", "crossbows", "turrets", "stealth", "athletics"]
        for s in combat_skills:
            val = int(float(stats.get(s, 0)))
            if val > 15:
                notable.append(f"{s.replace('_', ' ').capitalize()}: {val}")
        if notable:
            lines.append(f"- NOTABLE SKILLS: {', '.join(notable)}")

    mem = ctx.get("memories", {})
    st = [SHORT_TERM_MEM.get(m, str(m)) for m in mem.get("short_term", [])]
    lt = [LONG_TERM_MEM.get(m, str(m)) for m in mem.get("long_term", [])]
    
    if st or lt:
        lines.append(f"PERCEPTION OF PLAYER:")
        if st: lines.append(f"- SHORT TERM: {', '.join(st)}")
        if lt: lines.append(f"- HISTORY TAGS: {', '.join(lt)}")
        
    inv = ctx.get("inventory", [])
    if inv:
        worn = [i for i in inv if i.get("equipped")]
        held = [i for i in inv if not i.get("equipped")]
        
        if worn:
            lines.append(f"EQUIPMENT WORN by {npc_name}:")
            for item in worn:
                lines.append(f"- {item['name']} (x{item.get('count', 1)}) [{item['slot'].upper()}]")
        
        if held:
            lines.append(f"INVENTORY HELD by {npc_name}:")
            for item in held[:12]:
                lines.append(f"- {item['name']} (x{item.get('count', 1)})")
            if len(held) > 12:
                lines.append(f"- ... (and {len(held)-12} other items)")
    else:
        lines.append(f"INVENTORY: Empty")

    nearby = ctx.get("nearby", [])
    if nearby:
        lines.append(f"PEOPLE NEARBY (Visual Awareness):")
        for p in nearby:
            dist = float(p.get("dist", 0))
            dist_str = "Immediate proximity" if dist < 2.5 else f"{int(dist)}m away"
            p_name = p.get("name", "Someone")
            p_race = p.get("race", "Unknown")
            p_gender = p.get("gender", "Unknown")
            p_fact = p.get("faction", "Unknown")
            p_fact_display = p_fact
            if p_fact == "Nameless" or p_fact == PLAYER_CONTEXT.get('faction', 'Nameless'):
                p_fact_display = f"Player's Squad: {p_fact}"
            
            p_health = p.get("health", "Healthy")
            p_equip = p.get("equipment", "")
            
            p_desc = f"- {p_name} ({p_gender} {p_race}, {p_fact_display}) | Health: {p_health} | {dist_str}"
            if p_equip:
                p_desc += f" | Visible Gear: {p_equip}"
            lines.append(p_desc)

    return "\n".join(lines)

# SetHotkeyFromString in the plugin parses only these keys
CHAT_HOTKEYS = ["\\", "[", "P", "T", "J", "U", "K"]

# The plugin reads the same [Settings] keys, so renaming one breaks it
INI_KEY_MAP = {
    "current_campaign": "ActiveCampaign",
    "enable_ambient": "EnableAmbientConversations",
    "radiant_delay": "RadiantDelay",
    "global_events_count": "GlobalEventsCount",
    "synthesis_interval_minutes": "SynthesisIntervalMinutes",
    "radiant_range": "RadiantRange",
    "talk_radius": "TalkRadius",
    "yell_radius": "YellRadius",
    "enable_welcome": "EnableWelcomePopup",
    "dialogue_speed_seconds": "DialogueSpeed",
    "bubble_life": "SpeechBubbleLife",
    "language": "Language",
    "chat_hotkey": "ChatHotkey",
    "open_web_panel_on_start": "OpenWebPanelOnStart",
    "log_level": "LogLevel"
}

def _save_settings_raw(settings):
    try:
        config = configparser.ConfigParser()
        if os.path.exists(INI_PATH):
            config.read(INI_PATH)
        
        if 'Settings' not in config:
            config['Settings'] = {}
            
        for k, v in settings.items():
            ini_key = INI_KEY_MAP.get(k)
            if ini_key:
                if isinstance(v, list):
                    config['Settings'][ini_key] = ",".join(v)
                elif isinstance(v, bool):
                    config['Settings'][ini_key] = "1" if v else "0"
                else:
                    config['Settings'][ini_key] = str(v)
        
        with open(INI_PATH, "w") as f:
            config.write(f)
    except Exception as e:
        logging.error(f"SETTINGS: Cannot save the INI at {INI_PATH}: {e}")

SETTINGS_DEFAULTS = {
    "current_campaign": "Default",
    "enable_ambient": True,
    "radiant_delay": 240,
    "global_events_count": 10,
    "synthesis_interval_minutes": 5,
    "radiant_range": 100,
    "talk_radius": 100,
    "yell_radius": 200,
    "enable_welcome": True,
    "dialogue_speed_seconds": 5,
    "bubble_life": 5.0,
    "language": "English",
    "chat_hotkey": "\\",
    "open_web_panel_on_start": True,
    "log_level": log_setup.DEFAULT_LEVEL
}

def load_settings():
    settings = SETTINGS_DEFAULTS.copy()
    if os.path.exists(INI_PATH):
        try:
            config = configparser.ConfigParser()
            config.read(INI_PATH)
            if 'Settings' in config:
                for k in SETTINGS_DEFAULTS.keys():
                    ini_key = INI_KEY_MAP.get(k)
                    if ini_key and ini_key in config['Settings']:
                        val = config['Settings'][ini_key]
                        if isinstance(SETTINGS_DEFAULTS[k], bool):
                            settings[k] = (val == "1" or val.lower() == "true")
                        elif isinstance(SETTINGS_DEFAULTS[k], int):
                            try: settings[k] = int(val)
                            except: pass
                        elif isinstance(SETTINGS_DEFAULTS[k], float):
                            try: settings[k] = float(val)
                            except: pass
                        elif isinstance(SETTINGS_DEFAULTS[k], list):
                            settings[k] = [x.strip() for x in val.split(",") if x.strip()]
                        else:
                            settings[k] = val
        except Exception as e:
            logging.error(f"SETTINGS: Cannot read the INI: {e}")
            
    return settings

def save_settings(new_settings):
    flat_changes = {}
    for k, v in new_settings.items():
        if k == "radii" and isinstance(v, dict):
            if "radiant" in v: flat_changes["radiant_range"] = v["radiant"]
            if "talk" in v: flat_changes["talk_radius"] = v["talk"]
            if "yell" in v: flat_changes["yell_radius"] = v["yell"]
        else:
            flat_changes[k] = v
            
    settings = load_settings()
    settings.update(flat_changes)
    _save_settings_raw(settings)

load_configs()

def init_server_state():
    global ACTIVE_CAMPAIGN
    try:
        settings = load_settings()
        log_setup.set_level(settings["log_level"])
        ACTIVE_CAMPAIGN = settings.get("current_campaign", "Default")
        logging.info(f"CAMPAIGN: Active campaign: {ACTIVE_CAMPAIGN or 'none'}")
        
        # Backfills missing keys into the INI with defaults
        _save_settings_raw(settings)
        
        load_campaign_config()
    except Exception as e:
        logging.error(f"SYSTEM: Cannot initialize the server state: {e}")

init_server_state()

def load_prompt_component(filename):
    text = prompt_store.load(filename, PROMPTS_DIR, USER_PROMPTS_DIR)
    if not text:
        logging.error(f"PROMPT: {filename} is missing or empty in {PROMPTS_DIR}")
    return text

def fill_prompt(filename, **values):
    template = load_prompt_component(filename)
    unknown = prompt_store.placeholders(template) - values.keys()
    if unknown:
        logging.warning(f"PROMPT: {filename} has placeholders that nothing fills, so they stay as text: {', '.join(sorted(unknown))}")
    return prompt_store.render(template, values)

def load_campaign_text(filename):
    return prompt_store.read(os.path.join(CAMPAIGNS_DIR, ACTIVE_CAMPAIGN, filename)) or prompt_store.read(os.path.join(PROMPTS_DIR, filename))

def format_player_status(player_ctx):
    if not player_ctx: return "No status data."
    res = "PLAYER STATUS:\n"
    res += f"- Race: {player_ctx.get('race', 'Unknown')}\n"
    res += f"- Gender: {player_ctx.get('gender', 'male')}\n"
    med = player_ctx.get("medical", {})
    if med:
        hunger = med.get("hunger", 300)
        blood = med.get("blood", 100)
        max_blood = med.get("max_blood", 100)
        blood_pct = blood / max_blood if max_blood > 0 else 1.0
        blood_rate = med.get("blood_rate", 0.0)
        status = []
        if hunger < 80: status.append("STARVING")
        elif hunger < 200: status.append("VERY HUNGRY")
        elif hunger < 250: status.append("HUNGRY")
        
        if blood_rate > 0.01: 
            status.append("BLEEDING")
        elif blood_pct < 0.5: 
            status.append("CRITICAL BLOODLOSS")
        elif blood_pct < 0.85: 
            status.append("INJURED")
            
        res += f"- Condition: {', '.join(status) if status else 'Healthy/Fed'}\n"
    res += f"- Money: {player_ctx.get('money', 0)} cats\n"
    res += f"- Faction: {player_ctx.get('faction', 'Nameless')}\n"
    return res

def format_player_inventory(player_ctx):
    if not player_ctx: return "No inventory data."
    inv = player_ctx.get("inventory", [])
    if not inv: return "Inventory: Empty or not visible."
    
    visible = []
    bag = []
    for item in inv:
        name = item.get("name", "Unknown Item")
        count = item.get("count", 1)
        equipped = item.get("equipped", False)
        slot = item.get("slot", "none")
        display = f"{name} (x{count})"
        if equipped:
            visible.append(f"{display} [{slot.upper()}]")
        else:
            bag.append(display)
            
    res = "PLAYER EQUIPMENT & INVENTORY:\n"
    res += "VISIBLE (Worn/Held):\n" + ("\n".join([f"- {v}" for v in visible]) if visible else "- Nothing visible.") + "\n"
    res += "CONCEALED (In Bag/Pack):\n" + ("\n".join([f"- {b}" for b in bag[:15]]) if bag else "- Bag appears empty.")
    if len(bag) > 15:
        res += f"\n- ... and {len(bag)-15} more items."
    return res

def build_system_prompt(player_name="Drifter"):
    player_bio = load_campaign_text("character_bio.txt")
    npc_base = load_prompt_component("npc_base.txt")
    world_lore = campaign_db.overview()
    rules = load_prompt_component("response_rules.txt")
    action_tags = load_prompt_component("prompt_action_tags.txt")
    
    settings = load_settings()
    ge_count = settings.get("global_events_count", 10)
    events_list = []

    rumors = [line for _, line in campaign_db.rumors() if line.startswith("- [")]
    events_list.extend(rumors[-max(1, ge_count//2):])

    for e in campaign_db.recent_events(max(1, ge_count - len(events_list))):
        events_list.append(f"- {e}")

    events_block = ""
    if events_list:
        events_block = "WORLD STATUS & RUMORS (Hearsay):\n" 
        events_block += "The following are bits of gossip and recent news circulating in the wasteland. Do NOT prioritize these over your core identity or immediate situation. Mention them only if relevant to the conversation.\n"
        events_block += "\n".join(events_list[-ge_count:])

    player_faction = campaign_db.player_faction()
    faction_block = ""
    if player_faction and player_faction["description"].strip():
        faction_block = f"PLAYER FACTION ({player_faction['name']}):\n{player_faction['description']}\n"

    location_tag = "The Wasteland"
    if PLAYER_CONTEXT:
        env = PLAYER_CONTEXT.get("environment", {})
        if isinstance(env, dict):
            town = env.get("town_name", "")
            biome = env.get("biome", "")
            if town and biome:
                location_tag = f"{town} (within {biome})"
            elif town:
                location_tag = town
            elif biome:
                location_tag = biome

    # Only player2 infers the language from context; other providers need it stated
    language = settings.get("language", "English")
    language_instruction = ""
    if language and language.lower() != "english":
        language_instruction = f"\nLANGUAGE: You MUST respond ONLY in {language}. Do not switch to English under any circumstances.\n"

    player_race = PLAYER_CONTEXT.get("race", "Unknown") if PLAYER_CONTEXT else "Unknown"
    player_gender = PLAYER_CONTEXT.get("gender", "male") if PLAYER_CONTEXT else "male"

    prompt = fill_prompt(
        "prompt_system.txt",
        npc_base=npc_base,
        location=location_tag,
        world_lore=world_lore,
        events=events_block,
        player_name=player_name,
        player_race=player_race,
        player_gender=player_gender,
        player_bio=player_bio,
        player_faction=faction_block,
        player_status=format_player_status(PLAYER_CONTEXT),
        player_inventory=format_player_inventory(PLAYER_CONTEXT),
        rules=rules,
        action_tags=action_tags,
        language_instruction=language_instruction
    )
    return prompt.strip()


def default_llm_config():
    return llm_config.build(llm_config.load(DEFAULT_PROVIDERS_PATH), llm_config.load(DEFAULT_MODELS_PATH), "player2-default")

def load_llm_config():
    if not os.path.exists(LLM_CONFIG_PATH):
        config = default_llm_config()
        llm_config.save(LLM_CONFIG_PATH, config)
        logging.info("LLM: Built llm_config.json from the default providers and models.")
        return config
    try:
        config = llm_config.load(LLM_CONFIG_PATH)
    except Exception as e:
        # Not saved over, so a hand-edited file with a typo keeps its keys until the player fixes it
        logging.error(f"LLM: Cannot read {LLM_CONFIG_PATH}: {e}. Using the default configuration until a save from the web app.")
        return default_llm_config()
    for error in llm_config.validate(config):
        logging.warning(f"LLM: {error['message']}")
    return config

def refresh_player2_session(provider):
    global PLAYER2_SESSION_KEY
    try:
        auth_resp = requests.post(f"http://localhost:4315/v1/login/web/{provider.get('game_key', '')}", timeout=5)
        new_key = auth_resp.json().get("p2Key") if auth_resp.status_code == 200 else None
    except Exception as e:
        # The Player2 app may not be running or logged in
        logging.warning(f"PLAYER2: Cannot refresh the session key: {e}")
        return False
    if new_key:
        PLAYER2_SESSION_KEY = new_key
    return bool(new_key)

def extract_completion(data, model):
    choices = data.get("choices") or []
    if not choices:
        return ""
    msg_obj = choices[0].get("message") or {}
    content = msg_obj.get("content")

    # Some providers put the text in reasoning_content (DeepSeek-style) or completions-style choices[0].text
    if content is None:
        content = msg_obj.get("reasoning_content")
    if content is None:
        content = choices[0].get("text")
    if content is None:
        llm_log.debug(f"{model} reply without text: {data}")
        return ""

    if "</thought>" in content:
        content = content.split("</thought>")[-1]

    content = re.sub(r'<thought>.*?</thought>', '', content, flags=re.DOTALL | re.IGNORECASE)
    content = re.sub(r'<thought>.*', '', content, flags=re.DOTALL | re.IGNORECASE)

    if "\n\n" in content and ("thought" in model.lower() or content.strip().lower().startswith("thought:")):
        parts = content.split("\n\n")
        if "thought" in parts[0].lower() or "reasoning" in parts[0].lower():
            content = "\n\n".join(parts[1:])

    return sanitize_llm_text(content.strip())

def send_completion(provider, profile, body, timeout):
    is_player2 = provider["type"] == "player2"
    target_url = f"{provider['base_url'].rstrip('/')}/chat/completions"

    for attempt in (1, 2):
        api_key = PLAYER2_SESSION_KEY if is_player2 and PLAYER2_SESSION_KEY else provider.get("api_key", "")
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        # OpenRouter uses these headers for app attribution
        if "openrouter.ai" in target_url:
            headers["X-Title"] = "Sentient Sands Rebirth"
            headers["HTTP-Referer"] = "https://github.com/equanimittyy/SentientSands-Rebirth"

        if is_player2:
            headers["player2-game-key"] = provider.get("game_key", "")

        logging.debug(f"LLM: Request to {profile['model']} at {target_url}")
        start_time = time.time()
        response = requests.post(target_url, headers=headers, json=body, timeout=timeout)
        logging.debug(f"LLM: {profile['model']} answered HTTP {response.status_code} in {time.time() - start_time:.1f} s")

        # A Player2 session key expires, so a refreshed key gets one more try on the same profile
        if response.status_code == 401 and is_player2 and attempt == 1 and refresh_player2_session(provider):
            logging.info("PLAYER2: Refreshed the session key.")
            continue
        break

    if response.status_code != 200:
        raise RuntimeError(f"HTTP {response.status_code}: {response.text[:200]}")
    try:
        data = response.json()
    except ValueError:
        raise RuntimeError(f"invalid JSON in the response: {response.text[:200]}")
    return extract_completion(data, profile["model"])

def call_llm(task, messages):
    """Returns the completion text from the first profile of the task's route that answers, or None."""
    llm_log.debug(f"{task} request:\n" + "\n".join(f"[{m['role']}]\n{m['content']}" for m in messages))
    text = llm_router.run_route(LLM_CONFIG, task, messages, send_completion)
    llm_log.debug(f"{task} reply:\n{text}")
    return text

LLM_CONFIG = load_llm_config()

def generate_character_profile(name, context=""):
    lower_name = name.lower()
    if "your squad" in lower_name or "squad" == lower_name:
        player_faction = PLAYER_CONTEXT.get('faction', 'Nameless')
        return {
            "Personality": "A collective of your loyal companions, each with their own views but united in purpose. They are loyal to you and the squad's goals.",
            "Backstory": f"You have traveled together as members of the {player_faction} through the harsh lands of Kenshi, surviving against all odds.",
            "SpeechQuirks": "Speaks as a representative of the group, sometimes mentioning others in the squad.",
            "Race": "Mixed",
            "Faction": player_faction,
            "Sex": "Mixed"
        }

    live_ctx = LIVE_CONTEXTS.get(name) or {}
    
    race = "Unknown"
    gender = "Unknown"
    faction = "Unknown"
    origin_faction = "Unknown"
    job = "None"
    
    ctx_data = {}
    if isinstance(context, dict):
        ctx_data = context
    elif isinstance(context, str) and context.strip().startswith('{'):
        try:
            ctx_data = json.loads(context)
        except: pass
        
    if ctx_data:
        race = ctx_data.get('race', race)
        gender = ctx_data.get('gender', gender)
        faction = ctx_data.get('faction', faction)
        if faction == "Unknown":
            faction = ctx_data.get('factionID', "Unknown")
        origin_faction = ctx_data.get('origin_faction', origin_faction)
        job = ctx_data.get('job', job)
    
    if race == "Unknown": race = live_ctx.get('race', 'Unknown')
    if gender == "Unknown": gender = live_ctx.get('gender', 'Unknown')
    if faction == "Unknown": 
        faction = live_ctx.get('faction', 'Unknown')
        if faction == "Unknown":
            faction = live_ctx.get('factionID', "Unknown")
    
    if origin_faction == "Unknown": origin_faction = live_ctx.get('origin_faction', 'Unknown')
    if job == "None": job = live_ctx.get('job', 'None')
    
    # Unknown race/faction is tolerated: modded factions often don't report names through the hooks
    if name in ("Unknown", "Someone", "Unknown Entity"):
        logging.debug(f"PROFILE: Skipped the profile of {name}.")
        return None


    logging.info(f"PROFILE: Generating the profile of {name} ({gender} {race}, Base Faction: {origin_faction}, Job: {job})...")
    
    f_info = describe_faction(faction, ctx_data.get("factionID") or live_ctx.get("factionID"))
    o_info = describe_faction(origin_faction)

    prompt = fill_prompt("prompt_profile_generation.txt", name=name, gender=gender, race=race, faction=f_info, origin_faction=o_info, job=job, context=context)
    
    settings = load_settings()
    language = settings.get("language", "English")
    if language and language.lower() != "english":
        prompt += f"\nLANGUAGE: The JSON values ('Personality', 'Backstory', 'SpeechQuirks') MUST be written entirely in {language}. Do not use English.\n"
    
    messages = [{"role": "user", "content": prompt}]
    response_text = call_llm("profile", messages)
    
    if response_text:
        try:
            result = robust_json_parse(response_text)
            if result:
                result["Race"] = race
                result["Faction"] = faction
                result["OriginFaction"] = origin_faction
                result["Job"] = job
                result["Sex"] = gender
                return result
        except Exception as e:
            logging.error(f"PROFILE: Cannot parse the generated profile: {e}")
            
    return {
        "Personality": "A weary wanderer.",
        "Backstory": "Trying to survive in the harsh desert.",
        "SpeechQuirks": "None.",
        "Race": race,
        "Faction": faction,
        "OriginFaction": origin_faction,
        "Job": job,
        "Sex": gender
    }

def generate_batch_profiles(npc_list):
    if not npc_list: return
    
    complete = []
    for npc in npc_list:
        name = npc.get('name', 'Unknown')
        race = npc.get('race', 'Unknown')
        gender = npc.get('gender', 'Unknown')
        faction = npc.get('faction', 'Unknown')
        missing = [k for k, v in {"race": race, "gender": gender, "faction": faction}.items() if v in ("Unknown", None, "")]
        if missing:
            logging.debug(f"PROFILE: Batch skips {name} \u2014 missing {', '.join(missing)}, will generate on next full context.")
        else:
            complete.append(npc)

    if not complete:
        logging.debug("PROFILE: Batch has no NPC with complete data, so every profile waits.")
        return
    
    logging.info(f"PROFILE: Batch generating {len(complete)} profiles in one call ({len(npc_list) - len(complete)} deferred)...")
    
    descriptions = []
    for npc in complete:
        name = npc.get('name', 'Unknown')
        race = npc.get('race', 'Unknown')
        gender = npc.get('gender', 'Unknown')
        faction = npc.get('faction', 'Unknown')
        f_info = describe_faction(faction, npc.get("factionID"))
        descriptions.append(f"- Name: {name}, Sex: {gender}, Race: {race}, Faction: {f_info}")
    
    desc_str = "\n".join(descriptions)
    
    prompt = fill_prompt("prompt_batch_profile_generation.txt", desc_str=desc_str)
    
    settings = load_settings()
    language = settings.get("language", "English")
    if language and language.lower() != "english":
        prompt += f"\nLANGUAGE: All generated profile values ('Personality', 'Backstory', 'SpeechQuirks') MUST be written entirely in {language}. Do not use English for the values.\n"
    
    messages = [{"role": "user", "content": prompt}]
    response_text = call_llm("profile_batch", messages)
    
    if response_text:
        try:
            batch_results = robust_json_parse(response_text)
            if batch_results:
                for npc in npc_list:
                    raw_name = npc.get('name', 'Unknown')
                    clean_name = raw_name.split('|')[0] if '|' in raw_name else raw_name
                    gender = npc.get('gender', 'Neutral')
                    
                    profile = batch_results.get(clean_name) or batch_results.get(raw_name)
                    
                    if not profile:
                        # The LLM may change the key's case or echo the "|serial" suffix
                        clean_low = clean_name.lower()
                        raw_low = raw_name.lower()
                        for k, v in batch_results.items():
                            k_low = k.lower()
                            k_clean_low = k_low.split('|')[0].strip() if '|' in k_low else k_low.strip()
                            
                            if k_low == clean_low or k_low == raw_low or k_clean_low == clean_low:
                                profile = v
                                break
                    
                    if profile:
                        storage_id = clean_name
                        
                        if '|' in str(storage_id):
                            storage_id = str(storage_id).split('|')[0]

                        data = {
                            "ID": storage_id,
                            "Name": clean_name,
                            "OriginalName": clean_name,
                            "Race": npc.get('race', 'Unknown'),
                            "Sex": npc.get('gender', 'Unknown'),
                            "Faction": npc.get('faction') or npc.get('Faction') or 'Unknown',
                            "OriginFaction": npc.get('origin_faction', 'Unknown'),
                            "Job": npc.get('job', 'None'),
                            "Personality": profile.get("Personality", "A weary traveler."),
                            "Backstory": profile.get("Backstory", "Trying to survive in the harsh desert."),
                            "SpeechQuirks": profile.get("SpeechQuirks", "None."),
                            "Relation": int(float(npc.get("relation", 0)) / 2)
                        }
                        campaign_db.upsert_profile(storage_id, data)
                        logging.debug(f"PROFILE: Batch saved the profile of {clean_name} (ID: {storage_id})")
        except Exception as e:
            logging.error(f"PROFILE: Cannot parse the batch profiles: {e}")

def get_character_data(name, context="", skip_generate=False):
    # Strip the serial so "Name|ID" doesn't create a separate junk profile per serial
    if '|' in name:
        name_parts = name.split('|')
        name = name_parts[0]

    # Key profiles by name only; serial and faction-suffixed IDs are unstable
    name = str(name).strip()
    storage_id = name
    
    if storage_id and '|' in str(storage_id):
        storage_id = str(storage_id).split('|')[0].strip()

    data = campaign_db.get_npc(storage_id)
    stored = dict(data) if data else {}

    ctx_data = {}
    if isinstance(context, dict):
        ctx_data = context
    elif isinstance(context, str) and context.strip().startswith('{'):
        try:
            ctx_data = json.loads(context)
        except:
            pass

    if ctx_data:
        try:
            if data:
                current_race = ctx_data.get("race", "Unknown")
                current_sex = ctx_data.get("gender", "Unknown")
                current_faction = ctx_data.get("faction", "Unknown")
                needs_save = False
                
                if data.get("Race") == "Unknown" and current_race != "Unknown":
                    logging.debug(f"PROFILE: Updating Race for {name}: {current_race}")
                    data["Race"] = current_race
                    needs_save = True
                    
                if data.get("Sex") in ("Unknown", None) and current_sex not in ("Unknown", None):
                    logging.debug(f"PROFILE: Updating Sex for {name}: {current_sex}")
                    data["Sex"] = current_sex
                    needs_save = True
                    
                if data.get("Faction") == "Unknown" and current_faction != "Unknown":
                    logging.debug(f"PROFILE: Updating Faction for {name}: {current_faction}")
                    data["Faction"] = current_faction
                    needs_save = True

                current_origin = ctx_data.get("origin_faction", "Unknown")
                if data.get("OriginFaction") == "Unknown" and current_origin != "Unknown":
                    logging.debug(f"PROFILE: Updating OriginFaction for {name}: {current_origin}")
                    data["OriginFaction"] = current_origin
                    needs_save = True

                current_job = ctx_data.get("job", "None")
                if data.get("Job") in ("None", "Unknown") and current_job not in ("None", "Unknown"):
                    logging.debug(f"PROFILE: Updating Job for {name}: {current_job}")
                    data["Job"] = current_job
                    needs_save = True

                # Bypasses should_save_profile, which would drop generic-content profiles
                if needs_save:
                    campaign_db.upsert_profile(storage_id, {k: data[k] for k in ("Race", "Sex", "Faction", "OriginFaction", "Job")})
        except Exception as e:
            logging.error(f"PROFILE: Cannot update the profile from the context: {e}")

    if not data:
        if skip_generate:
             logging.debug(f"PROFILE: Stand-in path 1: {name} (skip_generate=True)")
             return {
                "ID": storage_id,
                "Name": name,
                "Race": ctx_data.get("race", "Unknown"),
                "Sex": ctx_data.get("gender", "Unknown"),
                "Faction": ctx_data.get("faction", "Unknown"),
                "OriginFaction": ctx_data.get("origin_faction", "Unknown"),
                "Job": ctx_data.get("job", "None"),
                "Personality": "A quiet traveler.",
                "Backstory": f"A {ctx_data.get('race', 'person')} from {ctx_data.get('faction', 'the borderlands')}.",
                "SpeechQuirks": "None.",
                "ConversationHistory": [],
                "Relation": int(float(ctx_data.get("relation", 0)) / 2),
                "_transient": True
            }

        # Stops concurrent requests from generating the same NPC twice
        with PROGRESS_LOCK:
            if storage_id in PROFILES_IN_PROGRESS:
                logging.debug(f"PROFILE: Stand-in path 2: {name} (Already in progress: {storage_id})")
                return {
                    "ID": storage_id,
                    "Name": name,
                    "Race": "Unknown",
                    "Sex": "Unknown",
                    "Faction": "Unknown",
                    "OriginFaction": "Unknown",
                    "Job": "None",
                    "Personality": "A quiet traveler.",
                    "Backstory": "Unknown.",
                    "SpeechQuirks": "None.",
                    "ConversationHistory": [],
                    "Relation": int(float(ctx_data.get("relation", 0)) / 2),
                    "_transient": True
                }
            PROFILES_IN_PROGRESS.add(storage_id)

        try:
            profile = generate_character_profile(name, context)
            if profile is None:
                logging.debug(f"PROFILE: Stand-in path 3: {name} (Generator returned None)")
                return {
                    "ID": storage_id,
                    "Name": name,
                    "Race": "Unknown",
                    "Sex": "Unknown",
                    "Faction": "Unknown",
                    "OriginFaction": "Unknown",
                    "Job": "None",
                    "Personality": "A quiet traveler who keeps to themselves.",
                    "Backstory": "Their past is unclear.",
                    "SpeechQuirks": "Speaks sparingly.",
                    "ConversationHistory": [],
                    "Relation": int(float(ctx_data.get("relation", 0)) / 2),
                    "_transient": True
                }
            data = {
                "ID": storage_id,
                "Name": name,
                "Race": profile.get("Race", "Unknown"),
                "Sex": profile.get("Sex", "Unknown"),
                "Faction": profile.get("Faction", "Unknown"),
                "OriginFaction": profile.get("OriginFaction", "Unknown"),
                "Job": profile.get("Job", "None"),
                "Personality": profile.get("Personality", "Unknown"),
                "Backstory": profile.get("Backstory", "Unknown"),
                "SpeechQuirks": profile.get("SpeechQuirks", ""),
                "ConversationHistory": [],
                "Relation": int(float(ctx_data.get("relation", 0)) / 2)
            }
        finally:
            with PROGRESS_LOCK:
                if storage_id in PROFILES_IN_PROGRESS:
                    PROFILES_IN_PROGRESS.remove(storage_id)
    
    if should_save_profile(name, storage_id, data):
        # Only the changed keys, so the write cannot undo a change that another request made since the read
        changes = {k: v for k, v in data.items() if stored.get(k) != v}
        if changes:
            campaign_db.upsert_profile(storage_id, changes)
    return data

def should_save_profile(name, storage_id, data):
    if not name or name in ("Unknown", "Someone"):
        return False
        
    personality = data.get("Personality", "").lower()
    is_generic_content = any(x in personality for x in ("unknown", "generic npc", "weary wanderer", "weary traveler"))
    has_history = len(data.get("ConversationHistory", [])) > 0
    
    if is_generic_content and not has_history:
        return False
        
                
    return True

def extract_id_from_context(context_json):
    if not context_json: return None
    try:
        if isinstance(context_json, str) and context_json.strip().startswith('{'):
            context_json = json.loads(context_json)
        if isinstance(context_json, dict):
            # Prefer storage_id: id is a volatile serial
            return context_json.get('storage_id') or context_json.get('id')
    except:
        pass
    return None


@app.route('/get_batch_identities', methods=['POST'])
def get_batch_identities():
    batch = request.json # Plugin sends [{serial, name, gender, race, is_generic}]
    if not batch or not isinstance(batch, list):
        return jsonify({"status": "error", "message": "Invalid batch format"}), 400
    
    results = []
    rename_count = 0
    for item in batch:
        serial = item.get('serial')
        current_name = str(item.get('name', 'Someone')).strip()
        gender = item.get('gender', 'Neutral')
        
        is_generic_client = item.get('is_generic', False)
        is_generic = is_generic_client or is_npc_name_generic(current_name)
        
        if is_generic:
            new_name = generate_unique_lore_name(gender=gender)
            results.append({
                "serial": serial,
                "status": "rename",
                "new_name": new_name
            })
            logging.debug(f"NAME: Assigning the name '{new_name}' to generic NPC '{current_name}' (serial {serial})")
            rename_count += 1
        else:
            results.append({
                "serial": serial,
                "status": "ok"
            })
            
    if results:
        logging.debug(f"NAME: Batch of {len(results)} NPCs, {rename_count} renamed.")
    return jsonify(results)


@app.route('/rename', methods=['POST'])
def rename_character():
    data = request.json
    if not data: return jsonify({"status": "error"}), 400
    
    old_name = data.get('old_name')
    new_name = data.get('new_name')
    context = data.get('context', '')
    
    if not old_name or not new_name:
        return jsonify({"status": "error", "message": "Missing names"}), 400
        
    logging.debug(f"RENAME: Renaming '{old_name}' to '{new_name}'")
    
    char_data = get_character_data(old_name, context, skip_generate=True)
    if char_data.get("_transient"):
        logging.info(f"RENAME: No persistent profile for {old_name}, renaming aborted (will create new on next chat)")
        return jsonify({"status": "ok", "message": "No profile to rename"})

    old_id = char_data.get("ID")
    if not old_id:
        return jsonify({"status": "error", "message": "Profile ID resolution failed"}), 500

    old_safe = "".join([c for c in old_name if c.isalnum() or c in (' ', '_', '-')]).strip()
    if str(old_id).startswith(old_safe) or "_" in str(old_id):
        new_id = new_name
        if campaign_db.rename_npc(old_id, new_id, new_name):
            logging.info(f"RENAME: Moved profile {old_id} -> {new_id}")
            return jsonify({"status": "ok", "new_id": new_id})

    campaign_db.upsert_profile(old_id, {"Name": new_name})
    return jsonify({"status": "ok"})

@app.route('/ambient', methods=['POST'])
def ambient_event():
    logging.debug("HTTP: POST /ambient")
    data = request.json
    if not data: return jsonify({"status": "error"}), 400
    
    npcs_data = data.get('npcs', [])
    player_name = data.get('player', 'Drifter')
    
    logging.info(f"AMBIENT: Banter request ({len(npcs_data)} NPCs nearby)")
    
    if not npcs_data:
        return jsonify({"status": "ignore"})

    char_profiles = ""
    name_to_id = {}
    
    missing_npcs = []
    npc_limit = npcs_data[:12]
    for npc in npc_limit:
        if isinstance(npc, dict):
            name = npc.get('name', 'Unknown')
            if "your squad" in name.lower():
                continue
            
            # skip_generate defers missing profiles to one batch LLM call
            info = get_character_data(name, context=json.dumps(npc), skip_generate=True)
            if info.get("_transient"):
                missing_npcs.append(npc)
                
    if missing_npcs:
        generate_batch_profiles(missing_npcs)

    recent_dialogue = []
    for npc in npc_limit:
        if isinstance(npc, dict):
            name = npc.get('name', 'Unknown')
            nid = npc.get('id', 0)
            name_to_id[name] = nid
            d = get_character_data(name, context=json.dumps(npc))
            
            if d.get("ConversationHistory"):
                recent_dialogue.extend(d["ConversationHistory"][-15:])

            # "Name|ID" lets the plugin map each banter line to the right NPC
            health = npc.get('health', 'Healthy')
            gear = npc.get('equipment', 'nothing notable')
            char_profiles += f"\n- {name}|{nid} ({npc.get('gender')} {npc.get('race')}, {npc.get('faction')}) | Health: {health} | Gear: {gear} | Personality: {d.get('Personality', 'A traveler.')} | Speech quirks: {d.get('SpeechQuirks') or 'None.'}"
        else:
            name_to_id[npc] = 0
            d = get_character_data(npc, "")
            
            if d.get("ConversationHistory"):
                recent_dialogue.extend(d["ConversationHistory"][-15:])
                
            char_profiles += f"\n- {npc} (A traveler): {d.get('Personality', 'A traveler.')} | Speech quirks: {d.get('SpeechQuirks') or 'None.'}"

    all_history = list(recent_dialogue)
    
    location = ""
    if PLAYER_CONTEXT:
        env = PLAYER_CONTEXT.get("environment", {})
        location = env.get("town_name", "") if isinstance(env, dict) else ""

    for evt in reversed(campaign_db.recent_events(campaign_db.MAX_EVENTS)):
        # Entries look like "[Day 3, 14:05] [BANTER] Name (Faction) -> Nearby @ Town: Message"
        if (" [BANTER] " in evt or " [CHAT] " in evt):
            if not location or f"@ {location}" in evt or "@" not in evt:
                if ": " in evt:
                    msg_part = evt.split(": ", 1)[1]
                    match = re.search(r'\]\s*(.*?)\s*(?:\(.*?\))?\s*->', evt)
                    if match:
                        speaker = match.group(1).strip()
                        all_history.append(f"{speaker}: {msg_part}")
                    else:
                        all_history.append(msg_part)
        if len(all_history) > 100: break

    unique_history = []
    seen_history = set()
    for line in reversed(all_history):
        if line not in seen_history:
            unique_history.append(line)
            seen_history.add(line)
    
    unique_history = list(reversed(unique_history))[-40:]
    
    history_block = ""
    if unique_history:
        history_block = "\nRECENT LOCAL DIALOGUE (DO NOT REPEAT TOPICS OR JOKES FROM HERE):\n" + "\n".join(unique_history)

    dynamic_system_prompt = build_system_prompt(player_name)
    
    
    ambient_system_prompt = f"""{dynamic_system_prompt}

[RADIANT DIALOGUE SYSTEM - BANTER MODE]
You are generating a short, atmospheric back-and-forth conversation (banter) between NPCs in Kenshi.
Kenshi is a post-apocalyptic, harsh world. NPCs should sound cynical, weary, or suspicious.

NEARBY CHARACTERS:
{char_profiles}

{history_block}

INSTRUCTIONS:
1. Select 2 or 3 characters from the list to have a short conversation.
2. Each participant MUST speak AT LEAST TWICE (total 4-6 lines).
3. DO NOT include the Player as a speaker and DO NOT let the Player participate.
4. The topic should be grounded in the harsh reality of Kenshi: local rumors, faction politics, the weather, gear maintenance, hunger, or a passing, often cynical comment about the 'drifter' (player) nearby.
5. Format MUST be 'Name|ID: Message' (e.g., 'Lungrot|1234: Wheeze...').
6. Only use characters from the NEARBY list.
7. Use the EXACT Name and ID strings provided in the list for the 'Name|ID' portion.
8. DO NOT use [ACTION] tags or any bracketed text. Radiant mode is for atmospheric dialogue only.
9. CRITICAL: Do NOT repeat topics, lines, or jokes found in the RECENT LOCAL DIALOGUE section. Talk about something new.
10. WORLD-CENTRIC: Remember that in Kenshi, the player is NOT the center of the universe. NPCs have their own lives, problems, and social circles. They should speak to and about each other about what is going on around them more often than they speak about the player.
"""
    
    messages = [
        {"role": "system", "content": ambient_system_prompt},
        {"role": "user", "content": "The world is quiet. Generate a radiant interaction."}
    ]
    
    content = call_llm("ambient", messages)
    if content:
        # The LLM sometimes emits [ACTION] tags despite the prompt forbidding them
        content = re.sub(r'\[\s*[A-Z_]+(?::\s*[^\]]+)?\s*\]', '', content).strip()
        
        content = content.replace('"', '').strip()
        
        lines = []
        for line in content.split('\n'):
            line = line.strip()
            if not line: continue
            
            if ':' in line:
                header, msg = line.split(':', 1)
                name_part = header.split('|')[0].strip()
                
                if name_part.lower() == player_name.lower():
                    continue

                if '|' not in header:
                    if name_part in name_to_id:
                        header = f"{name_part}|{name_to_id[name_part]}"
                
                lines.append(f"{header.strip()}: {msg.strip()}")
            elif '|' in line and len(line) < 100:
                continue
            else:
                if len(line) > 5: lines.append(line)
        
        final_text = "\n".join(lines)
        
        memories = {}
        for npc_obj in npc_limit:
            name = npc_obj.get('name') if isinstance(npc_obj, dict) else npc_obj
            memories[name] = get_character_data(name, context=json.dumps(npc_obj) if isinstance(npc_obj, dict) else "", skip_generate=True)

        banter = []
        for line in lines:
            if ':' in line:
                header, msg = line.split(':', 1)
                speaker_name = header.split('|')[0].strip()
                time_prefix = get_current_time_prefix()
                banter.append(f"{time_prefix}{speaker_name}: {msg.strip()}")
                
                speaker_faction = memories.get(speaker_name, {}).get("Faction", "None")
                record_event_to_history("BANTER", speaker_name, "Nearby", msg.strip(), actor_faction=speaker_faction)

        for name, d in memories.items():
            campaign_db.append_dialogue(d.get("ID", name), banter, d)

        logging.debug(f"AMBIENT: Banter: {final_text}")
        return jsonify({"status": "ok", "text": final_text})
    
    return jsonify({"status": "none"})

@app.route('/')
def web_app():
    return app.send_static_file("index.html")

PANEL_TABS = PanelTabs()

# A GET, because EventSource sends only GET. A hostile page that holds it open can only stop a new tab from opening.
@app.route('/web_panel/presence')
def web_panel_presence():
    return Response(PANEL_TABS.stream(), mimetype="text/event-stream")

@app.route('/chat', methods=['POST'])
def chat():
    data = request.json
    logging.debug("HTTP: POST /chat")
    if not data: return jsonify({"text": "Error: No JSON data provided"}), 400
    
    raw_npc = data.get('npc', 'Someone')
    raw_npcs = data.get('npcs', [])
    
    name_to_id = {}
    
    def register(raw):
        if not raw: return ""
        clean = raw.split('|')[0] if '|' in raw else raw
        name_to_id[clean] = raw
        return clean

    primary_npc = register(raw_npc)
    npcs = [register(n) for n in raw_npcs]
    
    player_name = data.get('player', 'Drifter')
    mode = data.get('mode', 'talk')
    
    nearby = data.get('nearby', [])
    if nearby:
        for n in nearby:
            name = n.get('name')
            sid = n.get('storage_id') or n.get('id')
            if name:
                LIVE_CONTEXTS[name] = {
                    "id": f"{name}|{sid}" if sid else name,
                    "race": n.get('race', 'Unknown'),
                    "faction": n.get('faction', 'Unknown'),
                    "gender": n.get('gender', 'Unknown'),
                    "nearby": [x for x in nearby if x.get('name') != name],
                    "player_dist": n.get('dist', 999.0)
                }
                if name == primary_npc:
                    LIVE_CONTEXTS[primary_npc]["id"] = f"{name}|{sid}" if sid else name
    
    # Keeps the LLM from being asked to voice the player
    npcs = [n for n in npcs if n != player_name]
    if primary_npc == player_name and len(npcs) > 0:
        primary_npc = npcs[0]
        
    player_message = data.get('message', '')
    
    if player_message.startswith('/'):
        cmd_parts = player_message[1:].split(' ', 1)
        cmd = cmd_parts[0].lower()
        args = cmd_parts[1].strip() if len(cmd_parts) > 1 else ""
        
        test_action = None
        if cmd == "help" or cmd == "commands":
            help_text = "[DEBUG] Available test commands:\n" + \
                        "/take, /attack, /follow, /idle, /patrol, /join, /leave, /free, /breakout,\n" + \
                        "/move, /movefast, /home, /shop, /raid [Town], /travel [Town], /medic, /rescue, /repair,\n" + \
                        "/notify [msg], /give_cats [n], /take_cats [n], /drop [item],\n" + \
                        "/take_item [item], /spawn [Templ|Name|Desc], /relations [Fact] [n], /task [TASK]"
            return jsonify({"text": help_text, "actions": []}), 200
            
        if cmd == "attack": test_action = "[ATTACK]"
        elif cmd == "follow": test_action = "[ACTION: FOLLOW_PLAYER]"
        elif cmd == "idle": test_action = "[ACTION: IDLE]"
        elif cmd == "patrol": test_action = "[ACTION: PATROL_TOWN]"
        elif cmd == "join": test_action = "[ACTION: JOIN_PARTY]"
        elif cmd == "leave": test_action = "[ACTION: LEAVE]"
        elif cmd == "free": test_action = "[ACTION: FREE_PLAYER]"
        elif cmd == "breakout": test_action = "[ACTION: BREAKOUT_PLAYER]"
        elif cmd == "move": test_action = "[ACTION: MOVE_ON_FREE_WILL]"
        elif cmd == "movefast": test_action = "[ACTION: MOVE_ON_FREE_WILL_FAST]"
        elif cmd == "home": test_action = "[ACTION: GO_HOMEBUILDING]"
        elif cmd == "shop": test_action = "[ACTION: STAND_AT_SHOPKEEPER_NODE]"
        elif cmd == "raid": test_action = f"[ACTION: RAID_TOWN: {args}]"
        elif cmd == "travel": test_action = f"[ACTION: TRAVEL_TO_TARGET_TOWN: {args}]"
        elif cmd == "medic": test_action = "[ACTION: JOB_MEDIC]"
        elif cmd == "rescue": test_action = "[ACTION: FIND_AND_RESCUE]"
        elif cmd == "repair": test_action = "[ACTION: JOB_REPAIR_ROBOT]"
        elif cmd == "notify": test_action = f"[ACTION: NOTIFY: {args}]"
        elif cmd == "give_cats": test_action = f"[ACTION: GIVE_CATS: {args}]"
        elif cmd == "take_cats": test_action = f"[ACTION: TAKE_CATS: {args}]"
        elif cmd == "take_item": test_action = f"[ACTION: TAKE_ITEM: {args}]"
        elif cmd == "take":
            inv = PLAYER_CONTEXT.get("inventory", [])
            if inv:
                item_name = inv[0].get("name", "Unknown Item")
                test_action = f"[ACTION: TAKE_ITEM: {item_name}]"
            else:
                return jsonify({"text": "[DEBUG] Error: Player inventory is empty or unknown. Call /context to refresh.", "actions": []}), 200
        elif cmd == "drop": test_action = f"[ACTION: DROP_ITEM: {args}]"
        elif cmd == "spawn": test_action = f"[ACTION: SPAWN_ITEM: {args}]"
        elif cmd == "relations":
            rparts = args.rsplit(' ', 1)
            if len(rparts) == 2:
                test_action = f"[ACTION: FACTION_RELATIONS: {rparts[0].strip()}: {rparts[1].strip()}]"
        elif cmd == "task": test_action = f"[TASK: {args.upper()}]"
        
        if test_action:
            logging.info(f"CHAT: Test command {cmd} -> {test_action}")
            return jsonify({
                "text": f"[DEBUG] Executing test command: {test_action}",
                "actions": [test_action]
            }), 200
            
    event = data.get('event')
    
    if event == "selection_clear":
        return jsonify({"status": "ignored"}), 200
        
    if not player_message and event != "ambient_flavor":
        return jsonify({"text": "...", "actions": []}), 200
    
    is_ambient = event == "ambient_flavor"
    if is_ambient:
        player_message = "[AMBIENT CONVERSATION TRIGGERED]"
        
    context = data.get('context', '')
    primary_id = extract_id_from_context(context)

    # Batch profile generation reads race/faction from LIVE_CONTEXTS
    if primary_npc and context:
        try:
            ctx_dict = json.loads(context) if isinstance(context, str) else context
            if ctx_dict:
                # Merge rather than replace, to keep the nearby list and other tracked fields
                if primary_npc not in LIVE_CONTEXTS:
                    LIVE_CONTEXTS[primary_npc] = {}
                
                target = LIVE_CONTEXTS[primary_npc]
                target["id"] = primary_id if primary_id else (ctx_dict.get('id') or target.get('id', primary_npc))
                if ctx_dict.get('storage_id'): target["storage_id"] = ctx_dict.get('storage_id')
                if ctx_dict.get('race'): target["race"] = ctx_dict.get('race')
                if ctx_dict.get('faction'): target["faction"] = ctx_dict.get('faction')
                if ctx_dict.get('factionID'): target["factionID"] = ctx_dict.get('factionID')
                note_faction(ctx_dict)
                if ctx_dict.get('origin_faction'): target["origin_faction"] = ctx_dict.get('origin_faction')
                
                if "nearby" in ctx_dict:
                    target["nearby"] = ctx_dict["nearby"]
                
                if "dist" in ctx_dict:
                    target["player_dist"] = ctx_dict["dist"]
        except Exception as e:
            logging.error(f"CHAT: Cannot register the context of the chat target: {e}")
    
    _, talk_radius, yell_radius = get_config_radii()
    
    npcs_in_radius = []
    nearby_data = data.get('nearby', [])
    for n in nearby_data:
        name = n.get("name")
        if not name or name == player_name or name == primary_npc:
            continue
            
        dist = n.get("dist", 999.0)
        if mode == "whisper":
            # Whisper is one-on-one: nobody overhears
            continue 
        elif mode == "talk":
            if dist <= talk_radius: npcs_in_radius.append(name)
        elif mode == "yell":
            if dist <= yell_radius: npcs_in_radius.append(name)

    
    def get_local_context(target_name):
        clean_target = target_name.split('|')[0] if '|' in target_name else target_name
        
        if clean_target == primary_npc:
            return context
            
        # The request's nearby data is fresher than the LIVE_CONTEXTS cache
        nearby_data = data.get('nearby', [])
        for n in nearby_data:
            n_name = n.get("name", "")
            clean_n = n_name.split('|')[0] if '|' in n_name else n_name
            if clean_n == clean_target:
                return json.dumps(n)
                
        if clean_target in LIVE_CONTEXTS:
            c = LIVE_CONTEXTS[clean_target]
            return json.dumps(c)
            
        return ""

    raw_listeners = list(set([primary_npc] + npcs_in_radius))
    listeners = []
    for l in raw_listeners:
        clean_l = l.split('|')[0] if '|' in l else l
        if clean_l not in listeners: listeners.append(clean_l)

    if mode == 'yell':
        npcs = listeners
    else:
        npcs = [primary_npc]

    # One batch LLM call for every listener missing a profile, instead of one call each
    missing_for_batch = []
    checked_ids = set()
    for name in listeners:
        npc_ctx = get_local_context(name)
        
        storage_id = name
        if '|' in str(storage_id): storage_id = str(storage_id).split('|')[0]
        
        if storage_id in checked_ids: continue
        checked_ids.add(storage_id)
        
        if not campaign_db.npc_exists(storage_id):
            # Another request may already be generating this NPC
            with PROGRESS_LOCK:
                if storage_id in PROFILES_IN_PROGRESS:
                    continue
                PROFILES_IN_PROGRESS.add(storage_id)

            ctx_dict = {}
            if npc_ctx:
                try: ctx_dict = json.loads(npc_ctx) if isinstance(npc_ctx, str) else npc_ctx
                except: pass
            
            if not ctx_dict:
                live = LIVE_CONTEXTS.get(name, {})
                ctx_dict = {
                    "name": name,
                    "race": live.get("race", "Unknown"),
                    "gender": live.get("gender", "Unknown"),
                    "faction": live.get("faction", "Unknown"),
                    "storage_id": storage_id
                }
            else:
                ctx_dict["storage_id"] = storage_id
                
            missing_for_batch.append(ctx_dict)

    if missing_for_batch:
        try:
            generate_batch_profiles(missing_for_batch)
        finally:
            with PROGRESS_LOCK:
                for ctx in missing_for_batch:
                    sid = ctx.get("storage_id")
                    if sid in PROFILES_IN_PROGRESS:
                        PROFILES_IN_PROGRESS.remove(sid)

    char_datas = {}
    threads = []
    def fetch_npc_thread(name, delay):
        if delay > 0:
            time.sleep(delay)
        try:
            char_datas[name] = get_character_data(name, get_local_context(name))
        except Exception as e:
            logging.error(f"PROFILE: Cannot fetch the profile of {name}: {e}")

    delay_counter = 0
    for name in listeners:
        storage_id = name
        if '|' in str(storage_id): storage_id = str(storage_id).split('|')[0]
        
        delay = 0
        if not campaign_db.npc_exists(storage_id):
            delay = delay_counter
            delay_counter += 1
            
        t = threading.Thread(target=fetch_npc_thread, args=(name, delay), daemon=True)
        t.start()
        threads.append(t)
        
    for t in threads:
        t.join()

    for name in npcs:
        if name not in char_datas or not char_datas[name]:
            logging.warning(f"PROFILE: No profile for {name}, so the chat uses a generic one.")
            char_datas[name] = {"Name": name, "Personality": "A generic NPC.", "Backstory": "Unknown", "ConversationHistory": []}
    

    logging.info(f"CHAT: {mode} with {primary_npc} (Total participants: {len(npcs)})...")
    primary_data = char_datas[primary_npc]
    
    history_str = "\n".join(primary_data["ConversationHistory"][-20:])

    npc_profiles = ""
    for name in npcs:
        d = char_datas[name]
        npc_profiles += f"\nCHARACTER: {name}\n"
        npc_profiles += f"RACE: {d.get('Race')}\n"
        npc_profiles += f"ORIGIN FACTION: {describe_faction(d.get('OriginFaction', 'Unknown'))}\n"
        npc_profiles += f"CURRENT FACTION: {describe_faction(d.get('Faction'), LIVE_CONTEXTS.get(name, {}).get('factionID'))}\n"
        npc_profiles += f"JOB: {d.get('Job', 'None')}\n"
        npc_profiles += f"PERSONALITY: {d.get('Personality')}\n"
        npc_profiles += f"BACKSTORY: {d.get('Backstory')}\n"
        npc_profiles += f"SPEECH QUIRKS: {d.get('SpeechQuirks') or 'None.'}\n"
        npc_profiles += f"PERSONAL RELATION TO PLAYER: {d.get('Relation', 0)} (Scale: -100 to 100)\n"
        
        live_context = build_detailed_context_string(name, char_data=d)
        if live_context:
            npc_profiles += f"{live_context}\n"

    primary_race = primary_data.get('Race', 'Unknown')
    is_animal = any(kw.lower() in primary_race.lower() for kw in ANIMAL_RACES)

    if is_animal:
        dynamic_system_prompt = f"CRITICAL: {primary_npc} is an ANIMAL ({primary_race}). Animals in Kenshi CANNOT speak human languages. They do not use words, symbols, or telegram-style speech. They ONLY react with brief physical actions, sounds, or gestures described within asterisks."
        final_instruction = f"Respond as {primary_npc} (the animal). Provide a single, BRIEF action description or sound in asterisks (e.g. *Growls*, *Tilts head*, *Nuzzles hand*). DO NOT USE WORDS OR SPEECH. Keep it under 6 words."
    else:
        dynamic_system_prompt = build_system_prompt(player_name)
        
        if mode == 'yell':
            volume_status = "The player is addressing everyone nearby at a clear, projected volume."
            yell_instruction = f"\nCRITICAL: {volume_status} This can be heard by everyone nearby ({', '.join(npcs)}). This is a public address or talking to a crowd; it is NOT yelling or shouting aggressively. DO NOT tell the player to quiet down or react with annoyance to the volume. You SHOULD respond as multiple characters from the list to create a realistic crowd reaction. Every speaker MUST be on a new line started with 'Name: ' (e.g., 'Beep: Hey!').\nACTION TAGS IN CROWD MODE: If a character decides to take an action (attack, flee, join, etc.), place the [ACTION: TAG] at the END of THAT CHARACTER'S OWN LINE, not at the end of the whole response. Example: 'Hobbs: I'm with you! [ACTION: JOIN_PARTY]'"
            dynamic_system_prompt += yell_instruction
        elif mode == 'whisper':
            volume_status = "The player is WHISPERING to you privately. This is a quiet, intimate, or secretive moment."
            whisper_instruction = f"\nCRITICAL: {volume_status} ONLY {primary_npc} should respond. Keep the tone hushed and private."
            dynamic_system_prompt += whisper_instruction
        else:
            volume_status = "The player is speaking at a normal, conversational volume."

            if "[ACTION: ADDRESSES GROUP]" in history_str:
                 volume_status += " They have STOPPED addressing the group and are now speaking at a calm, normal volume."
                 
            talk_instruction = f"\nINFO: {volume_status} Respond naturally. This is a standard, polite conversation. You are calm and composed. DO NOT tell the player to quiet down, do NOT react with annoyance to their volume, and do NOT mention noise or shouting unless they are actually being aggressive."
            dynamic_system_prompt += talk_instruction
            
        if not is_ambient:
            dynamic_system_prompt += "\nJUDGMENT: At the end of your response, you MUST judge the player's tone and the quality of this interaction on a scale of -5 (extremely aggressive/hostile/insulting) to 5 (extremely friendly/helpful/respectful). 0 is neutral. Format this judgment as a tag like [JUDGMENT: n] at the very end."
        
        if len(npcs) > 1 and mode == 'yell':
            group_instruction = f"\nCONTEXT: You are facilitating a group conversation. YOU SHOULD RESPOND AS SEVERAL DIFFERENT CHARACTERS to create a lively atmosphere. Each speaker MUST use the format: 'Name: Dialogue'."
            dynamic_system_prompt += group_instruction

        final_instruction = f"Respond as {primary_npc} to the player's last message."
        if mode != 'yell':
            final_instruction = f"Respond ONLY as {primary_npc}. Do not speak as anyone else. Keep the response to 1-2 short sentences in a single paragraph."
        else:
            final_instruction = f"Respond as several characters from this list: ({', '.join(npcs)}) to the player's group address. Ensure at least 2-3 unique characters speak on separate lines if they are nearby."

    final_instruction += " Keep it immersive, short, and grounded in the world of Kenshi. Response should be 1-3 sentences maximum."
    
    settings = load_settings()
    user_lang = settings.get("language", "English")

    rich_prompt = fill_prompt(
        "prompt_chat_template.txt",
        system_prompt=dynamic_system_prompt,
        primary_npc=primary_npc,
        npc_profiles=npc_profiles,
        history_str=history_str,
        final_instruction=final_instruction,
        language_str=user_lang
    )
    # Later turns detect these history tags to tell the LLM the volume changed
    mode_action = ""
    if mode == 'whisper':
        mode_action = f" [ACTION: WHISPERS TO {primary_npc}]"
    elif mode == 'yell':
        mode_action = " [ACTION: ADDRESSES GROUP]"
    else:
        if "[ACTION: ADDRESSES GROUP]" in history_str:
            mode_action = " [ACTION: TALKS NORMALLY]"
    time_prefix = get_current_time_prefix()
    full_player_entry = f"{time_prefix}{player_name}{mode_action}: {player_message}"

    messages = [
        {"role": "system", "content": rich_prompt},
        {"role": "user", "content": full_player_entry}
    ]

    content = call_llm("chat", messages)
    if not content:
        logging.error("CHAT: No reply from the LLM.")
    
    if content:
        # Must run before the tag cleanup below strips the tags
        per_speaker_actions = []
        speaker_judgments = {}
        if mode == 'yell':
            raw_lines = content.split('\n')
            for rline in raw_lines:
                rline = rline.strip()
                if not rline: continue
                match = re.match(r'^([^:]+):\s*(.*)$', rline)
                if match:
                    speaker = match.group(1).strip()
                    payload = match.group(2).strip()
                    speaker_tags = re.findall(r'\[\s*[^\]]+\s*\]', payload)
                    for stag in speaker_tags:
                        per_speaker_actions.append(f"{speaker}: {stag}")
                        logging.debug(f"CHAT: Yell attribution: {speaker} took action {stag}")
                        
                        if "JUDGMENT" in stag.upper():
                            j_match = re.search(r'-?\d+', stag)
                            if j_match:
                                try:
                                    val = int(j_match.group(0))
                                    speaker_judgments[speaker] = max(-5, min(5, val))
                                except: pass

        # Allows one level of nested brackets: item names like "Bolts [Toothpicks]" contain them
        all_bracketed = re.findall(r'\[\s*(?:[^\[\]]|\[[^\[\]]*\])+\s*\]', content)
        
        actions = []
        global_judgment = 0
        
        formal_map = {
            "GIVE_CATS": "GIVE_CATS", "TAKE_CATS": "TAKE_CATS", 
            "GIVE_ITEM": "GIVE_ITEM", "TAKE_ITEM": "TAKE_ITEM",
            "DROP_ITEM": "DROP_ITEM", "SPAWN_ITEM": "SPAWN_ITEM",
            "JOIN_PARTY": "JOIN_PARTY", "LEAVE": "LEAVE",
            "IDLE": "IDLE", "PATROL_TOWN": "PATROL_TOWN", 
            "RELEASE_PLAYER": "RELEASE_PLAYER", "FREE_PLAYER": "FREE_PLAYER",
            "NOTIFY": "NOTIFY", "FACTION_RELATIONS": "FACTION_RELATIONS",
            "ATTACK_TOWN": "ATTACK_TOWN", "TRAVEL_TO_TARGET_TOWN": "TRAVEL_TO_TARGET_TOWN",
            "RAID_TOWN": "RAID_TOWN", "ATTACK": "ATTACK",
            "RELEASE_PRISONER": "RELEASE_PRISONER", 
            "BREAKOUT_PRISONER": "BREAKOUT_PRISONER", "BREAKOUT_PLAYER": "BREAKOUT_PLAYER",
            "JOB_MEDIC": "JOB_MEDIC", "JOB_REPAIR_ROBOT": "JOB_REPAIR_ROBOT",
            "FIND_AND_RESCUE": "FIND_AND_RESCUE", "JUDGMENT": "JUDGMENT"
        }

        for raw in all_bracketed:
            inner = raw.strip("[] \t")
            # Loop: the LLM sometimes doubles prefixes, e.g. "ACTION: ACTION: TAKE_CATS"
            clean = inner
            while True:
                prev = clean
                clean = re.sub(r'^(ACTION|TASK|TAG):\s*', '', clean, flags=re.IGNORECASE).strip()
                if clean == prev: break
            
            if ":" in clean:
                parts = clean.split(":", 1)
                kw = parts[0].strip().upper()
                args = parts[1].strip()
                
                # The LLM sometimes repeats the keyword: "[ACTION: TAKE_CATS: TAKE_CATS: 40]"
                if args.upper().startswith(kw):
                     args = re.sub(rf'^{re.escape(kw)}\s*:?\s*', '', args, flags=re.IGNORECASE).strip()
            else:
                kw = clean.upper()
                args = ""

            if kw == "JUDGMENT" or "JUDGMENT" in kw:
                j_val = args or re.search(r'-?\d+', kw)
                if j_val:
                    try:
                        j_str = j_val.group(0) if hasattr(j_val, 'group') else str(j_val)
                        global_judgment = max(-5, min(5, int(j_str)))
                        logging.debug(f"RELATION: Interaction judged as {global_judgment}")
                    except: pass
                # No continue: the JUDGMENT tag is forwarded to the plugin too

            matched_ka = None
            for formal in formal_map:
                if formal == kw or (formal in kw and len(kw) < len(formal) + 3):
                    matched_ka = formal_map[formal]
                    break
            
            if matched_ka:
                if matched_ka in ["WANDERER", "CHASE", "IDLE", "MELEE_ATTACK"]:
                    final_tag = f"[TASK: {matched_ka}{f': {args}' if args else ''}]"
                else:
                    if matched_ka == "LEAVE" and not args:
                        origin_faction = primary_data.get("OriginFaction", "Unknown")
                        if origin_faction == "Unknown":
                            origin_faction = primary_data.get("Faction", "Unknown")
                        final_tag = f"[ACTION: LEAVE: {origin_faction}]" if origin_faction != "Unknown" else "[ACTION: LEAVE]"
                    else:
                        final_tag = f"[ACTION: {matched_ka}{f': {args}' if args else ''}]"
                
                if "TASK:" in final_tag:
                     last_hist = primary_data["ConversationHistory"][-1] if primary_data["ConversationHistory"] else ""
                     if final_tag in last_hist: continue
                
                actions.append(final_tag)

        relation_deltas = {}
        if not is_ambient:
            judges = speaker_judgments if speaker_judgments else {primary_npc: global_judgment}
            
            for judge_name, j_val in judges.items():
                if j_val == 0: continue
                
                j_data = char_datas.get(judge_name)
                if not j_data: 
                    continue

                # Applied as a delta at save time: the profile read before the LLM call can be stale by then
                relation_deltas[judge_name] = j_val

                f_delta = 0
                if j_val >= 5: f_delta = 2
                elif j_val >= 4: f_delta = 1
                elif j_val <= -5: f_delta = -2
                elif j_val <= -4: f_delta = -1
                
                if f_delta != 0:
                    npc_f = j_data.get("Faction", "None")
                    if npc_f and npc_f not in ["None", "Nameless", "No Faction"]:
                        f_tag = f"[ACTION: FACTION_RELATIONS: {npc_f}: {f_delta}]"
                        actions.append(f_tag)
                        logging.info(f"RELATION: Scheduled faction relation change via {judge_name} for {npc_f}: {f_delta}")

        content = re.sub(r'\[\s*(?:[^\[\]]|\[[^\[\]]*\])+\s*\]', '', content).strip()

        # "Name: [ACTION: X]" tells the plugin which NPC takes each action
        if mode == 'yell' and per_speaker_actions:
            logging.debug(f"CHAT: Yell actions: {per_speaker_actions}")
            actions = per_speaker_actions + actions

        content = content.replace('"', '').strip()
        
        lines = content.split('\n')
        filtered_lines = []
        for line in lines:
            line = line.strip()
            if not line: continue
            
            line = re.sub(r'\[\s*[^\]]+\s*\]', '', line).strip()
            if not line: continue

            is_group_response = (mode == 'yell')
            if is_group_response:
                match = re.match(r'^([^:]+):\s*(.*)$', line)
                if match:
                    actor_name = match.group(1).strip()
                    actor_clean = actor_name.lower()
                    actor_speech = match.group(2).strip()
                    if actor_clean != player_name.lower():
                        # "Name|ID" lets the plugin resolve the speaker
                        full_actor = name_to_id.get(actor_name, actor_name)
                        filtered_lines.append(f"{full_actor}: {actor_speech}")
                        continue
                    else:
                        logging.debug(f"CHAT: Filter: Discarded LLM attempt to speak as {player_name}")
                        continue
            
            lower_line = line.lower()
            if any(lower_line.startswith(prefix) for prefix in [
                "thought:", "thinking:", "observation:", "note:", "(thinking", 
                "*", "as an ai", "i cannot", "here is", "raw llm response:", 
                "timestamp:", "request for:", "prompt:", "user message:",
                "history:", "character:", "personality:", "backstory:", "current condition"
            ]):
                continue
            
            if line.startswith('=') or line.startswith('-') or len(set(line)) <= 2:
                continue
                
            if len(npcs) <= 1:
                prefix_match = re.match(r'^([A-Za-z0-9 _\-\.]+):\s*', line)
                if prefix_match:
                    p = prefix_match.group(1).strip().lower()
                    if p == player_name.lower():
                        logging.debug(f"CHAT: Filter: Discarded player entry {line}")
                        continue
                    if p != primary_npc.lower():
                        logging.debug(f"CHAT: Filter: Discarded line from {p} (expected {primary_npc})")
                        continue
                line = re.sub(r'^[A-Za-z0-9 _\-\.]+:\s*', '', line)
            
            # The LLM sometimes puts several speakers on one line: "Name1: text Name2: text"
            if len(npcs) > 1:
                pattern = r'([A-Z][a-z0-9 \-\.]+):\s*([^:]+?)(?=\s+[A-Z][a-z0-9 \-\.]+:\s*|$)'
                sub_matches = re.findall(pattern, line)
                if sub_matches:
                    for actor, speech in sub_matches:
                        actor_clean = actor.strip()
                        if actor_clean.lower() != player_name.lower():
                            full_actor = name_to_id.get(actor_clean, actor_clean)
                            filtered_lines.append(f"{full_actor}: {speech.strip()}")
                    continue

            if line:
                filtered_lines.append(line)
        
        # Each newline becomes a separate speech bubble in the plugin
        if filtered_lines:
            if mode != 'yell':
                # One speaker: a single bubble avoids rapid-fire flashing
                content = " ".join(filtered_lines)
            else:
                content = "\n".join(filtered_lines)
        else:
            content = "..."

        if len(content) > 500:
            content = content[:497] + "..."
        
        player_faction = PLAYER_CONTEXT.get("faction", "None")
        primary_faction = char_datas.get(primary_npc, {}).get("Faction", "None")
        record_event_to_history("CHAT", player_name, primary_npc, player_message, actor_faction=player_faction, target_faction=primary_faction)

        for name in listeners:
            is_overhearing = name not in npcs
            overheard_tag = "(Overheard) " if is_overhearing else ""
            
            if name not in char_datas:
                char_datas[name] = get_character_data(name, get_local_context(name))
                
            stored_lines = len(char_datas[name]["ConversationHistory"])
            char_datas[name]["ConversationHistory"].append(f"{time_prefix}{overheard_tag}{player_name}{mode_action}: {player_message}")
            
            if "\n" in content:
                for line in content.split('\n'):
                    if not line.strip(): continue
                    
                    history_line = line.strip()
                    if ':' not in history_line:
                         history_line = f"{primary_npc}: {history_line}"
                    
                    if line == filtered_lines[-1] and actions:
                        history_line += f" {' '.join(actions)}"

                    char_datas[name]["ConversationHistory"].append(f"{time_prefix}{overheard_tag}{history_line}")
                    
                    if ':' in history_line:
                        h, m = history_line.split(':', 1)
                        speaker_name = h.strip()
                        speaker_faction = char_datas.get(speaker_name, {}).get("Faction", "None")
                        player_faction = PLAYER_CONTEXT.get("faction", "None")
                        record_event_to_history("CHAT", speaker_name, player_name, m.strip(), actor_faction=speaker_faction, target_faction=player_faction)
                    else:
                        primary_faction = char_datas.get(primary_npc, {}).get("Faction", "None")
                        player_faction = PLAYER_CONTEXT.get("faction", "None")
                        record_event_to_history("CHAT", primary_npc, player_name, history_line, actor_faction=primary_faction, target_faction=player_faction)
            else:
                history_line = content
                if ':' not in history_line:
                     history_line = f"{primary_npc}: {history_line}"
                
                history_entry = f"{time_prefix}{overheard_tag}{history_line}"
                if actions:
                    history_entry += f" {' '.join(actions)}"
                char_datas[name]["ConversationHistory"].append(history_entry)
                
                primary_faction = char_datas.get(primary_npc, {}).get("Faction", "None")
                player_faction = PLAYER_CONTEXT.get("faction", "None")
                record_event_to_history("CHAT", primary_npc, player_name, content, actor_faction=primary_faction, target_faction=player_faction)

            storage_id = char_datas[name].get("ID", name)
            if should_save_profile(name, storage_id, char_datas[name]):
                campaign_db.append_dialogue(storage_id, char_datas[name]["ConversationHistory"][stored_lines:], char_datas[name])
                if name in relation_deltas:
                    new_rel = campaign_db.change_relation(storage_id, relation_deltas[name])
                    logging.info(f"RELATION: {name} personal relation is now {new_rel} (judgment={relation_deltas[name]})")

        logging.debug(f"CHAT: Reply: {content} | Actions: {actions}")
        return jsonify({"text": content, "actions": actions})
    return jsonify({"text": "...", "actions": []})


def record_event_to_history(etype, actor, target, msg, actor_faction="None", target_faction="None"):
    global EVENT_THROTTLE, LAST_STATE_LOG
    if not msg: return
    
    p_fact = PLAYER_CONTEXT.get('faction', 'Nameless')
    a_fact_display = actor_faction
    if actor_faction == "Nameless" or actor_faction == p_fact:
        a_fact_display = f"Player's Squad: {p_fact}"
        
    t_fact_display = target_faction
    if target_faction == "Nameless" or target_faction == p_fact:
        t_fact_display = f"Player's Squad: {p_fact}"

    actor_part = f"{actor} ({a_fact_display})" if a_fact_display and a_fact_display != "None" else actor
    target_part = f"{target} ({t_fact_display})" if t_fact_display and t_fact_display != "None" else target
    
    location = ""
    if PLAYER_CONTEXT:
        env = PLAYER_CONTEXT.get("environment", {})
        town = env.get("town_name", "") if isinstance(env, dict) else ""
        if town:
            location = f" @ {town}"
    
    time_str = get_current_time_prefix().strip()
    prefix = f"{time_str} " if time_str else ""
    evt_str = f"{prefix}[{etype}] {actor_part} -> {target_part}{location}: {msg}"
    
    # State hooks (knockout, recovery) fire repeatedly; log only when the message changes
    state_key = f"{target_part}|{etype}"
    with STATE_LOCK:
        if LAST_STATE_LOG.get(state_key) == msg:
            return
        LAST_STATE_LOG[state_key] = msg
        if len(LAST_STATE_LOG) > 2000: LAST_STATE_LOG.clear()

    throttle_key = f"{etype}|{actor_part}|{target_part}|{msg}"
    now = time.time()
    with THROTTLE_LOCK:
        last_time = EVENT_THROTTLE.get(throttle_key, 0)
        if now - last_time < 30.0:
            return
        EVENT_THROTTLE[throttle_key] = now
        # Trim the oldest half rather than clear, so recent cooldowns still apply
        if len(EVENT_THROTTLE) > 1000:
            sorted_items = sorted(EVENT_THROTTLE.items(), key=lambda x: x[1])
            EVENT_THROTTLE = dict(sorted_items[500:])

    logging.debug(f"EVENT: {evt_str}")

    # Looting events would flood the narrative history
    if etype == "looting":
        return

    try:
        campaign_db.add_event(evt_str)
    except campaign_db.CampaignUnavailable:
        pass  # The event is lost, but the context post that carries it must still update the player's context

def generate_global_narrative_thread():
    settings = load_settings()
    ge_count = settings.get("global_events_count", 10)
    last_chunk = campaign_db.recent_events(max(ge_count, 100))

    # Kept low so short sessions can still synthesize
    min_needed = 5
    if len(last_chunk) < min_needed:
        logging.debug(f"NARRATIVE: Not enough events to synthesize (have {len(last_chunk)}, need {min_needed}).")
        return None

    grouped_events = {}
    for evt in last_chunk:
        location = "Unknown Region"
        if " @ " in evt:
            try:
                parts = evt.split(" @ ")
                if len(parts) > 1:
                    location = parts[1].split(":")[0].strip()
            except: pass
        
        if location not in grouped_events:
            grouped_events[location] = []
        grouped_events[location].append(evt)

    events_text = ""
    for loc, evts in grouped_events.items():
        events_text += f"\n--- {loc.upper()} ---\n"
        events_text += "\n".join(evts) + "\n"
    
    logging.debug(f"NARRATIVE: Grouped {len(last_chunk)} events into {len(grouped_events)} locations.")
    
    past_rumors_block = ""
    rumor_lines = []
    for _, line in campaign_db.rumors()[-20:]:
        match = re.search(r'\[RUMOR:\s*(.*?)\]', line)
        if match:
            rumor_lines.append(f"- {match.group(1).strip()}")
    if rumor_lines:
        past_rumors_block = "\nPREVIOUS RUMORS (Do NOT repeat these):\n" + "\n".join(rumor_lines[-5:])

    p_fact = PLAYER_CONTEXT.get("faction", "The Nameless")
    
    prompt = fill_prompt("prompt_world_synthesis.txt", events_text=events_text, past_rumors_block=past_rumors_block, p_fact=p_fact)

    language = settings.get("language", "English")
    if language and language.lower() != "english":
        prompt += f"\nLANGUAGE: You MUST write the rumor ONLY in {language}. Do not use English."

    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": "Synthesize the rumors of the borderlands."}
    ]
    
    logging.info("NARRATIVE: Calling LLM to synthesize world events...")
    rumor_text = call_llm("synthesis", messages)
    
    if rumor_text:
        rumor_text = rumor_text.strip()
        # The LLM sometimes still wraps the rumor in a [RUMOR: ...] tag
        tag_match = re.search(r'\[RUMOR:\s*(.*?)\]', rumor_text, re.DOTALL)
        if tag_match:
            rumor_text = tag_match.group(1).strip()
        rumor_text = re.sub(r'^[-•*]\s*', '', rumor_text).strip()
        
        if len(rumor_text) > 10:
            time_prefix = get_current_time_prefix().strip()
            rumor_tagged = f"- {time_prefix} [RUMOR: {rumor_text}]"
            try:
                campaign_db.add_rumor(rumor_tagged)
                logging.info(f"NARRATIVE: Generated and saved new global event: {rumor_tagged}")
                send_to_pipe(f"NOTIFY: [WORLD EVENT] {rumor_text}")
                return rumor_tagged
            except Exception as e:
                logging.error(f"NARRATIVE: Cannot save the rumor: {e}")
    return None

@app.route('/synthesize', methods=['POST'])
def manual_synthesize():
    # Synchronous, despite the name, so the result can be returned
    rumor = generate_global_narrative_thread()
    if rumor:
        return jsonify({"status": "ok", "rumor": rumor})
    else:
        return jsonify({"status": "error", "message": "Failed to generate rumor or not enough events (need 5)."}), 400


@app.route('/events', methods=['GET', 'POST'])
def list_events():
    logging.debug(f"HTTP: {request.method} /events")

    rumors = []
    for rumor_id, line in campaign_db.rumors():
        match = re.search(r'\[RUMOR:\s*(.*?)\]', line)
        if not match:
            continue

        inner = match.group(1).strip()

        # "N." numbering rather than "#N": MyGUI parses "#" as a color tag
        words = inner.split()
        short = " ".join(words[:7]) + ("..." if len(words) > 7 else "")
        label = f"{len(rumors) + 1}. {short}"
        rumors.append({"id": str(rumor_id), "title": label[:80], "content": line, "inner": inner})

    formatted = "--- DYNAMIC WORLD RUMORS ---\n" + "\n".join(r["content"] for r in rumors) if rumors else "(No rumors yet. Use 'Synthesize Rumors' to generate some.)"
    return jsonify({"status": "ok", "text": formatted, "events": rumors})


@app.route('/events/content', methods=['POST'])
def events_content():
    """The plugin's SetEventsText renders each newline-separated line as a row."""
    data = request.json or {}
    rumor_id = data.get("day", "")  # "day" holds the rumor id that /events returned

    try:
        raw = campaign_db.rumor(int(rumor_id))
        if raw:
            match = re.search(r'\[RUMOR:\s*(.*?)\]', raw)
            if match:
                inner = match.group(1).strip()
                import textwrap
                wrapped = textwrap.wrap(inner, width=76)
                card_lines = [
                    "=" * 38,
                    "  WORLD RUMOR",
                    "=" * 38,
                    "",
                ] + wrapped + [
                    "",
                    "(Synthesized from recent world events)"
                ]
                return jsonify({"status": "ok", "text": "\n".join(card_lines)})
    except Exception as e:
        logging.error(f"EVENT: Cannot build the events text: {e}")
    return jsonify({"status": "error", "text": "Entry not found."}), 404

@app.route('/context', methods=['POST'])
def update_context():
    global PLAYER_CONTEXT
    data = request.json
    if not data: return jsonify({"status": "error"}), 400
    
    # Skipped while paused or stopped, to prevent event loops
    is_paused = data.get("is_paused", False)
    game_speed = data.get("gamespeed", 1.0)
    
    if not is_paused and game_speed > 0.05:
        new_events = data.get("events", [])
        for e in new_events:
            record_event_to_history(
                e.get("type", "EVENT"),
                e.get("actor", "Unknown"),
                e.get("target", "None"),
                e.get("msg", ""),
                actor_faction=e.get("actor_faction", "None"),
                target_faction=e.get("target_faction", "None")
            )

    note_faction(data, is_player=data.get("type") == "player")
    if data.get("type") == "player":
        prev_paused = PLAYER_CONTEXT.get("is_paused")
        PLAYER_CONTEXT = data
        if prev_paused != data.get("is_paused"):
             logging.debug(f"CONTEXT: Player pause state changed to {data.get('is_paused')} (Speed: {data.get('gamespeed')})")
    else:
        name = data.get("name")
        if name:
            LIVE_CONTEXTS[name] = data
            with STATE_LOCK:
                LAST_STATE_LOG["npc"] = data
    return jsonify({"status": "ok"})


@app.route('/context', methods=['GET'])
def get_context():
    last_npc = None
    if LIVE_CONTEXTS:
        last_npc_id = list(LIVE_CONTEXTS.keys())[-1]
        last_npc = LIVE_CONTEXTS[last_npc_id]
    
    elapsed = SYNTHESIS_STATUS.get("elapsed", 0)
    interval = SYNTHESIS_STATUS.get("interval", 60)

    return jsonify({
        "status": "ok",
        "player": PLAYER_CONTEXT or LAST_STATE_LOG.get("player", {}),
        "npc": last_npc or LAST_STATE_LOG.get("npc", {}),
        "campaign": ACTIVE_CAMPAIGN,
        "synthesis": {
            "elapsed": elapsed,
            "interval": interval
        }
    })

def settings_page_values(settings):
    return {
        "enable_ambient": settings["enable_ambient"],
        "ambient_timer": settings["radiant_delay"],
        "synthesis_timer": settings["synthesis_interval_minutes"],
        "global_events_count": settings["global_events_count"],
        "dialogue_speed": settings["dialogue_speed_seconds"],
        "bubble_life": settings["bubble_life"],
        "radii": {
            "radiant": settings["radiant_range"],
            "talk": settings["talk_radius"],
            "yell": settings["yell_radius"]
        },
        "language": settings["language"],
        "chat_hotkey": settings["chat_hotkey"],
        "enable_welcome": settings["enable_welcome"],
        "open_web_panel_on_start": settings["open_web_panel_on_start"],
        "log_level": log_setup.parse_level(settings["log_level"])
    }

@app.route('/settings/defaults')
def settings_defaults():
    return jsonify(settings_page_values(SETTINGS_DEFAULTS))

@app.route('/settings', methods=['GET', 'POST'])
def settings_endpoint():
    logging.debug(f"HTTP: {request.method} /settings")
    load_configs()

    data = None
    if request.method == 'POST':
        try:
            data = request.get_json(silent=True)
        except:
            data = None

    if not data:
        # An empty-body POST is how the plugin fetches the config
        settings = load_settings()

        return jsonify({
            "status": "ok",
            **settings_page_values(settings),
            "supported_languages": list(LOCALIZATION_CONFIG.keys()),
            "chat_hotkeys": CHAT_HOTKEYS,
            "log_levels": list(log_setup.LEVELS),
            "ui_translation": LOCALIZATION_CONFIG.get(settings["language"], {})
        })

    logging.debug(f"SETTINGS: Update request: {json.dumps(data)}")
    changes = {}

    enable_ambient = data.get("enable_ambient")
    if enable_ambient is not None:
        changes["enable_ambient"] = enable_ambient
        send_to_pipe(f"SET_CONFIG: g_enableAmbient: {'1' if enable_ambient else '0'}")
        logging.info(f"SETTINGS: Ambient enabled set to {enable_ambient}")

    ambient_timer = data.get("ambient_timer")
    if ambient_timer is not None:
        val = int(ambient_timer)
        changes["radiant_delay"] = val
        send_to_pipe(f"SET_CONFIG: g_ambientIntervalSeconds: {val}")
        logging.info(f"SETTINGS: Radiant delay set to {val}")

    radii = data.get("radii")
    if radii:
        r = radii.get("radiant")
        t = radii.get("talk")
        y = radii.get("yell")
        if r is not None:
            send_to_pipe(f"SET_CONFIG: g_radiantRange: {r}")
        if t is not None:
            send_to_pipe(f"SET_CONFIG: g_proximityRadius: {t}")
        if y is not None:
            send_to_pipe(f"SET_CONFIG: g_yellRadius: {y}")
        changes["radii"] = radii

    lang = data.get("language")
    if lang is not None:
        changes["language"] = lang
        send_to_pipe("APPLY_TRANSLATION: " + json.dumps({"ui_translation": LOCALIZATION_CONFIG.get(lang, {})}))
        logging.info(f"SETTINGS: Language set to {lang}")

    hotkey = data.get("chat_hotkey")
    if hotkey in CHAT_HOTKEYS:
        changes["chat_hotkey"] = hotkey
        send_to_pipe(f"SET_CONFIG: g_chatHotkey: {hotkey}")
        logging.info(f"SETTINGS: Chat hotkey set to {hotkey}")

    enable_welcome = data.get("enable_welcome")
    if enable_welcome is not None:
        changes["enable_welcome"] = bool(enable_welcome)
        send_to_pipe(f"SET_CONFIG: g_enableWelcome: {'1' if enable_welcome else '0'}")

    open_web_panel = data.get("open_web_panel_on_start")
    if open_web_panel is not None:
        changes["open_web_panel_on_start"] = bool(open_web_panel)

    log_level = data.get("log_level")
    if log_level in log_setup.LEVELS:
        changes["log_level"] = log_level
        log_setup.set_level(log_level)
        send_to_pipe(f"SET_CONFIG: g_logLevel: {log_level}")
        logging.info(f"SETTINGS: Log level set to {log_level}")

    ge_count = data.get("global_events_count")
    if ge_count is not None:
        try:
            val = int(ge_count)
            changes["global_events_count"] = val
            logging.info(f"SETTINGS: Global events count set to {val}")
        except: pass

    syn_timer = data.get("synthesis_timer")
    if syn_timer is not None:
        try:
            val = int(syn_timer)
            changes["synthesis_interval_minutes"] = val
            logging.info(f"SETTINGS: Synthesis timer set to {val} minutes")
        except: pass

    diag_speed = data.get("dialogue_speed")
    if diag_speed is not None:
        try:
            val = int(diag_speed)
            changes["dialogue_speed_seconds"] = val
            send_to_pipe(f"SET_CONFIG: g_dialogueSpeedSeconds: {val}")
            logging.info(f"SETTINGS: Dialogue speed set to {val} seconds")
        except: pass

    bubble_life = data.get("bubble_life")
    if bubble_life is not None:
        try:
            val = float(bubble_life)
            changes["bubble_life"] = val
            send_to_pipe(f"SET_CONFIG: g_speechBubbleLife: {val}")
            logging.info(f"SETTINGS: Bubble life set to {val} seconds")
        except: pass

    if changes:
        save_settings(changes)

    campaign = data.get("current_campaign")
    if campaign:
        if switch_campaign(campaign):
            changes["current_campaign"] = ACTIVE_CAMPAIGN
            logging.info(f"CAMPAIGN: Switched to {ACTIVE_CAMPAIGN}")

    if changes:
        save_settings(changes)
        logging.info(f"SETTINGS: Saved {len(changes)} changes.")
        return jsonify({"status": "ok", **changes})

    return jsonify({"status": "error", "message": "No valid settings provided"}), 400

def create_campaign(name, template):
    """Returns the folder name of the new campaign. Raises ValueError or world_template.TemplateError with the reason."""
    if not name: raise ValueError("Missing name")
    safe_name = "".join([c for c in name if c.isalnum() or c in (' ', '_', '-')]).strip()
    if not safe_name: raise ValueError("Invalid name")
    cdir = os.path.join(CAMPAIGNS_DIR, safe_name)
    if os.path.exists(cdir): raise ValueError("Campaign already exists")
    seed = world_template.campaign_seed(template, WORLD_TEMPLATES_DIR, USER_TEMPLATES_DIR)
    os.makedirs(cdir)
    try:
        campaign_db.create(cdir, seed)
    except Exception:
        # An empty folder would open later as a campaign of the default template
        import shutil
        shutil.rmtree(cdir, ignore_errors=True)
        raise
    ensure_campaign_seeded(cdir)
    return safe_name

def switch_campaign(name):
    global ACTIVE_CAMPAIGN, LIVE_CONTEXTS
    cdir = os.path.join(CAMPAIGNS_DIR, name)
    if not name or os.path.exists(cdir):
        ACTIVE_CAMPAIGN = name
        save_settings({"current_campaign": name})
        LIVE_CONTEXTS.clear()
        SEEN_FACTIONS.clear()
        load_campaign_config()
        return True
    return False

def template_error(e):
    return jsonify({"status": "error", "errors": e.errors}), 400

@app.route('/api/templates', methods=['GET'])
def list_templates():
    return jsonify({"status": "ok", "templates": world_template.listing(WORLD_TEMPLATES_DIR, USER_TEMPLATES_DIR)})

@app.route('/api/templates/<name>', methods=['GET'])
def get_template(name):
    try:
        template = world_template.load(name, WORLD_TEMPLATES_DIR, USER_TEMPLATES_DIR)
    except world_template.TemplateError as e:
        return template_error(e)
    template["errors"], template["warnings"] = world_template.validate(template)
    return jsonify({"status": "ok", "template": template})

@app.route('/api/templates/<name>/records', methods=['POST'])
def save_template_record(name):
    data = request.get_json(silent=True) or {}
    try:
        record_id, warnings = world_template.save_record(name, data.get("kind"), data.get("id"), data.get("data"), WORLD_TEMPLATES_DIR, USER_TEMPLATES_DIR, category=data.get("category"))
    except world_template.TemplateError as e:
        return template_error(e)
    logging.info(f"TEMPLATE: Saved the {data.get('kind')} {record_id or ''} of {name}")
    return jsonify({"status": "ok", "id": record_id, "warnings": warnings})

@app.route('/api/templates/<name>/records/delete', methods=['POST'])
def delete_template_record(name):
    data = request.get_json(silent=True) or {}
    try:
        world_template.delete_record(name, data.get("kind"), data.get("id"), WORLD_TEMPLATES_DIR, USER_TEMPLATES_DIR, category=data.get("category"))
    except world_template.TemplateError as e:
        return template_error(e)
    logging.info(f"TEMPLATE: Deleted the {data.get('kind')} {data.get('id')} of {name}")
    return jsonify({"status": "ok"})

@app.route('/api/templates/<name>/duplicate', methods=['POST'])
def duplicate_template(name):
    data = request.get_json(silent=True) or {}
    try:
        new_name = world_template.duplicate(name, data.get("new_name"), WORLD_TEMPLATES_DIR, USER_TEMPLATES_DIR)
    except world_template.TemplateError as e:
        return template_error(e)
    logging.info(f"TEMPLATE: Duplicated {name} as {new_name}")
    return jsonify({"status": "ok", "name": new_name})

@app.route('/api/templates/<name>/delete', methods=['POST'])
def delete_template(name):
    try:
        world_template.delete(name, WORLD_TEMPLATES_DIR, USER_TEMPLATES_DIR)
    except world_template.TemplateError as e:
        return template_error(e)
    logging.info(f"TEMPLATE: Deleted {name}")
    return jsonify({"status": "ok"})

def campaign_names():
    return sorted(d for d in os.listdir(CAMPAIGNS_DIR) if os.path.isdir(os.path.join(CAMPAIGNS_DIR, d))) if os.path.exists(CAMPAIGNS_DIR) else []

@app.route('/api/campaigns', methods=['GET'])
def list_campaigns():
    campaigns = []
    for name in campaign_names():
        meta = campaign_db.read_meta(os.path.join(CAMPAIGNS_DIR, name))
        campaigns.append({
            "name": name,
            "active": name == ACTIVE_CAMPAIGN,
            "template": meta.get("template_name", ""),
        })
    return jsonify({"status": "ok", "campaigns": campaigns, "templates": world_template.listing(WORLD_TEMPLATES_DIR, USER_TEMPLATES_DIR), "default_template": DEFAULT_TEMPLATE})

@app.route('/api/campaigns', methods=['POST'])
def create_campaign_from_web():
    data = request.get_json(silent=True) or {}
    try:
        name = create_campaign(data.get("name"), data.get("template") or DEFAULT_TEMPLATE)
    except world_template.TemplateError as e:
        return template_error(e)
    except ValueError as e:
        return jsonify({"status": "error", "errors": [{"field": ["name"], "message": str(e)}]}), 400
    logging.info(f"CAMPAIGN: Created the campaign '{name}' from the web app")
    return jsonify({"status": "ok", "name": name})

@app.route('/api/campaigns/switch', methods=['POST'])
def switch_campaign_from_web():
    name = (request.get_json(silent=True) or {}).get("name")
    # Only a listed folder, so a name such as ../x cannot point the campaign outside the campaigns folder
    if name not in campaign_names():
        return jsonify({"status": "error", "message": f"There is no campaign named {name}."}), 404
    switch_campaign(name)
    logging.info(f"CAMPAIGN: Switched to '{name}' from the web app")
    return jsonify({"status": "ok", "current": ACTIVE_CAMPAIGN})

@app.route('/api/campaigns/delete', methods=['POST'])
def delete_campaign():
    name = (request.get_json(silent=True) or {}).get("name")
    names = campaign_names()
    if name not in names:
        return jsonify({"status": "error", "message": f"There is no campaign named {name}."}), 404
    if name == ACTIVE_CAMPAIGN:
        switch_campaign(next((other for other in names if other != name), ""))
    import shutil
    try:
        shutil.rmtree(os.path.join(CAMPAIGNS_DIR, name))
    except OSError as e:
        logging.error(f"CAMPAIGN: Cannot delete the campaign '{name}': {e}")
        return jsonify({"status": "error", "message": f"Cannot delete {name}: {e}"}), 500
    logging.info(f"CAMPAIGN: Deleted the campaign '{name}' from the web app")
    return jsonify({"status": "ok", "current": ACTIVE_CAMPAIGN})

@app.route('/api/campaign', methods=['GET'])
def get_active_campaign():
    try:
        rumors = []
        for rumor_id, line in campaign_db.rumors():
            match = re.search(r'\[RUMOR:\s*(.*?)\]', line, re.DOTALL)
            rumors.append({"id": rumor_id, "line": line, "text": match.group(1).strip() if match else line})
        return jsonify({
            "status": "ok",
            "name": ACTIVE_CAMPAIGN,
            "template": campaign_db.template_info(),
            "events": [{"id": event_id, "line": line} for event_id, line in campaign_db.events()],
            "rumors": rumors,
        })
    except campaign_db.CampaignUnavailable as e:
        return jsonify({"status": "error", "name": ACTIVE_CAMPAIGN, "message": str(e)}), 409

def campaign_write(data):
    """An error reply when the player switched the campaign in game after the page loaded it, else None."""
    if data.get("campaign") != ACTIVE_CAMPAIGN:
        return jsonify({"status": "error", "message": f"The active campaign is now {ACTIVE_CAMPAIGN}. Discard to load it."}), 409
    return None

@app.route('/api/campaign/canon', methods=['GET'])
def get_campaign_canon():
    try:
        return jsonify({
            "status": "ok",
            "name": ACTIVE_CAMPAIGN,
            "template": campaign_db.template_info(),
            "overview": campaign_db.overview(),
            "history": campaign_db.history(),
            "factions": [
                {"id": f["faction_id"], "data": {"game_id": f["faction_id"], **{key: f[key] for key in campaign_db.FACTION_KEYS}}, "is_player": f["is_player"], "origin": f["origin"], "updated_at": f["updated_at"]}
                for f in campaign_db.list_factions()
            ],
            "characters": [
                {"id": game_id, "data": {"game_id": game_id, "profile": profile}, "origin": origin, "updated_at": updated_at}
                for (game_id,), profile, origin, updated_at in campaign_db.list_records("character")
            ],
            "entities": [
                {"category": category, "id": ext_id, "data": data, "origin": origin, "updated_at": updated_at}
                for (category, ext_id), data, origin, updated_at in campaign_db.list_records("entity")
            ],
        })
    except campaign_db.CampaignUnavailable as e:
        return jsonify({"status": "error", "name": ACTIVE_CAMPAIGN, "message": str(e)}), 409

def record_refusal(errors):
    return jsonify({"status": "error", "errors": errors}), 400

@app.route('/api/campaign/records', methods=['POST'])
def save_campaign_record():
    data = request.get_json(silent=True) or {}
    refused = campaign_write(data)
    if refused: return refused
    kind, record_id, value = data.get("kind"), data.get("id"), data.get("data")
    # A record that the page loaded must name its version, so a missing one counts as stale
    updated_at = None if record_id is None else data.get("updated_at") or ""
    warnings = []
    if kind in ("overview", "history"):
        if kind == "overview" and isinstance(value, str):
            value = value.replace("\r\n", "\n").strip()
        errors, _ = world_template.record_problems(kind, value, [kind])
        if errors: return record_refusal(errors)
        (campaign_db.set_overview if kind == "overview" else campaign_db.set_history)(value)
    elif kind in ("faction", "character", "entity"):
        value = value if isinstance(value, dict) else {}
        if kind != "entity":
            record_id = record_id or value.get("game_id")
        try:
            if kind == "faction":
                warnings = save_campaign_faction(record_id, value, updated_at)
            elif kind == "character":
                character = {"game_id": record_id, "profile": value.get("profile")}
                errors, _ = world_template.record_problems("character", character, ["characters", data.get("id") or "new"])
                if errors: return record_refusal(errors)
                campaign_db.save_record("character", (record_id,), character["profile"], updated_at)
            else:
                category = data.get("category")
                if category not in world_template.CATEGORIES:
                    return record_refusal([{"field": ["category"], "message": f"{category} is not a category. Use races, locations, or regions."}])
                stored = campaign_db.list_records("entity")
                record_id = record_id or world_template.new_id(value, {ext_id for (stored_category, ext_id), *_ in stored if stored_category == category})
                names = world_template.entity_names([entity for key, entity, *_ in stored if key != (category, record_id)] + [value])
                errors, warnings = world_template.record_problems("entity", value, [category, data.get("id") or "new"], names)
                if errors: return record_refusal(errors)
                campaign_db.save_record("entity", (category, record_id), value, updated_at)
        except world_template.TemplateError as e:
            return record_refusal(e.errors)
        except campaign_db.DuplicateRecord:
            field = [data.get("category"), "new"] if kind == "entity" else [f"{kind}s", "new", "game_id"]
            return record_refusal([{"field": field, "message": f"This campaign already holds the {kind} {record_id}."}])
        except campaign_db.StaleRecord:
            name = value.get("name") or (value.get("profile") or {}).get("Name") or record_id
            return jsonify({"status": "error", "message": f"The {kind} {name} changed after the page loaded it, for example in game. Discard to load it again."}), 409
    else:
        return record_refusal([{"field": ["kind"], "message": f"{kind} is not a kind of record."}])
    logging.info(f"CAMPAIGN: Saved the {kind} {record_id or ''} of '{ACTIVE_CAMPAIGN}' from the web app")
    return jsonify({"status": "ok", "id": record_id, "warnings": warnings})

def save_campaign_faction(faction_id, value, updated_at):
    """Returns the warnings. Raises world_template.TemplateError, or a campaign_db error, with the reason."""
    changes = {key: value[key] for key in campaign_db.FACTION_KEYS if key in value}
    if updated_at is None:
        faction = {"aliases": [], "major": False, "fields": {}, "description": "", **changes, "game_id": faction_id}
        errors, warnings = world_template.record_problems("faction", faction, ["factions", "new"])
        if errors: raise world_template.TemplateError(errors)
        campaign_db.add_faction(faction_id, faction)
        return warnings
    stored = campaign_db.find_faction(faction_id)
    if not stored:
        raise campaign_db.StaleRecord(faction_id)
    # The game names the player's faction, and the next context would undo another name
    if stored["is_player"]:
        changes.pop("name", None)
    errors, warnings = world_template.record_problems("faction", dict(stored, game_id=faction_id, **changes), ["factions", faction_id])
    if errors: raise world_template.TemplateError(errors)
    campaign_db.update_faction(faction_id, changes, updated_at)
    return warnings

@app.route('/api/campaign/records/delete', methods=['POST'])
def delete_campaign_record():
    data = request.get_json(silent=True) or {}
    refused = campaign_write(data)
    if refused: return refused
    kind, record_id = data.get("kind"), data.get("id")
    if kind == "faction":
        campaign_db.delete_faction(record_id)
    elif kind == "character":
        campaign_db.delete_record("character", (record_id,))
    elif kind == "entity":
        campaign_db.delete_record("entity", (data.get("category"), record_id))
    else:
        return record_refusal([{"field": ["kind"], "message": f"{kind} is not a kind of record."}])
    logging.info(f"CAMPAIGN: Deleted the {kind} {record_id} of '{ACTIVE_CAMPAIGN}' from the web app")
    return jsonify({"status": "ok"})

@app.route('/api/campaign/rumors', methods=['POST'])
def save_campaign_rumor():
    data = request.get_json(silent=True) or {}
    refused = campaign_write(data)
    if refused: return refused
    text = str(data.get("text") or "").strip()
    line = campaign_db.rumor(data.get("id"))
    if line is None:
        return jsonify({"status": "error", "message": "The rumor is gone. Discard to load the rumors again."}), 404
    if not text:
        return jsonify({"status": "error", "errors": [{"field": ["rumors", data.get("id")], "message": "A rumor needs text. Delete it instead."}]}), 400
    # The brackets would end the tag early, so the chat prompt would read only a part of the rumor
    text = text.replace("[", "(").replace("]", ")")
    prefix = line[:line.index("[RUMOR:")] if "[RUMOR:" in line else ""
    campaign_db.set_rumor(data.get("id"), f"{prefix}[RUMOR: {text}]")
    return jsonify({"status": "ok"})

@app.route('/api/campaign/rumors/delete', methods=['POST'])
def delete_campaign_rumor():
    data = request.get_json(silent=True) or {}
    refused = campaign_write(data)
    if refused: return refused
    campaign_db.delete_rumor(data.get("id"))
    return jsonify({"status": "ok"})

@app.route('/api/campaign/cull', methods=['POST'])
def cull_campaign():
    data = request.get_json(silent=True) or {}
    refused = campaign_write(data)
    if refused: return refused
    return cull_future_data()

# The game always means the active campaign, so this route has no campaign check
@app.route('/cull', methods=['POST'])
def cull_from_game():
    return cull_future_data()

def cull_future_data():
    # Without a game, day 0 would count as now, and the cull would delete the whole history
    if "day" not in PLAYER_CONTEXT:
        return jsonify({"status": "error", "message": "Cull needs the game running, because it deletes what is dated after the current game time."}), 409
    day, hour, minute = int(PLAYER_CONTEXT["day"]), int(PLAYER_CONTEXT.get("hour", 0)), int(PLAYER_CONTEXT.get("minute", 0))
    culled = campaign_db.cull_after(day, hour, minute)
    logging.info(f"CAMPAIGN: Culled {culled['dialogue']} dialogue lines, {culled['event']} events, and {culled['rumor']} rumors after [Day {day}, {hour:02d}:{minute:02d}] in '{ACTIVE_CAMPAIGN}'")
    return jsonify({"status": "ok", "time": f"Day {day}, {hour:02d}:{minute:02d}", "culled": culled})

@app.route('/api/campaign/events/delete', methods=['POST'])
def delete_campaign_event():
    data = request.get_json(silent=True) or {}
    refused = campaign_write(data)
    if refused: return refused
    campaign_db.delete_event(data.get("id"))
    return jsonify({"status": "ok"})

@app.route('/regenerate_profile', methods=['POST'])
def regenerate_profile_route():
    logging.debug("HTTP: POST /regenerate_profile")
    data = request.json
    sid = data.get("sid")
    if not sid: return jsonify({"status": "error", "message": "Missing NPC ID (sid)"}), 400
    
    char_data = campaign_db.get_npc(sid)
    if not char_data:
        logging.warning(f"PROFILE: Regen found no profile for {sid}")
        return jsonify({"status": "error", "message": "Profile not found"}), 404

    try:
        history = char_data.get("ConversationHistory", [])
        if not history:
             logging.info(f"PROFILE: Regen skipped {sid}, because it has no dialogue.")
             return jsonify({"status": "error", "message": "No conversation history to build from. Talk to the NPC first!"}), 400
             
        name = char_data.get("Name", sid)
        race = char_data.get("Race", "Unknown")
        personality = char_data.get("Personality", "Unknown")
        backstory = char_data.get("Backstory", "Unknown")
        faction = char_data.get("Faction", "Unknown")
        
        history_block = "\n".join(history)
        
        logging.info(f"PROFILE: Regen evolving profile for {name} based on {len(history)} lines of memory...")
        
        system_msg = "You are an expert on Kenshi lore and character growth. You write NPC profiles in a grounded, cynical tone. You ALWAYS respond ONLY with a valid JSON object."
        user_msg = f"""Rewrite the Personality and Backstory for the Kenshi NPC "{name}" based on their conversation history.

CURRENT PROFILE:
Personality: {personality}
Backstory: {backstory}
Race: {race} | Faction: {faction}

CONVERSATION HISTORY:
{history_block}

Instructions:
- EVOLVE the profile to reflect their experiences with the player.
- Maintain the Kenshi world's grounded, cynical tone.
- If they've bonded with the player, reflect that. If there was conflict, reflect that too.
- Response MUST be ONLY a JSON object with keys: "Personality", "Backstory", "SpeechQuirks"."""

        messages = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg}
        ]
        response_text = call_llm("profile", messages)
        
        if not response_text:
            logging.error(f"PROFILE: Regen got no reply for {name}. This may be a token limit or content filter issue.")
            return jsonify({"status": "error", "message": f"LLM returned an empty response. The model may have run out of tokens. Try again or use an NPC with fewer memories."}), 500

        result = robust_json_parse(response_text)
        if result:
            campaign_db.upsert_profile(sid, {
                "Personality": result.get("Personality", personality),
                "Backstory": result.get("Backstory", backstory),
                "SpeechQuirks": result.get("SpeechQuirks", char_data.get("SpeechQuirks", "")),
            })

            logging.info(f"PROFILE: Regen evolved the profile of {name}.")
            return jsonify({"status": "ok", "message": f"Successfully evolved {name}'s profile."})
        else:
            logging.error(f"PROFILE: Regen cannot parse the reply for {name}. Raw reply: {response_text[:300]}")
            return jsonify({"status": "error", "message": "LLM response was not valid JSON. Try again."}), 500
                
    except Exception as e:
        logging.error(f"PROFILE: Regen failed for {sid}: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
        
    return jsonify({"status": "error", "message": "Synthesis failed"}), 500


@app.route('/api/llm', methods=['GET'])
def get_llm_config():
    return jsonify({
        "status": "ok",
        "tasks": list(llm_config.TASKS),
        "provider_types": list(llm_config.PROVIDER_TYPES),
        **llm_config.masked(LLM_CONFIG)
    })

@app.route('/api/llm', methods=['POST'])
def save_llm_config():
    global LLM_CONFIG
    data = request.get_json(silent=True) or {}
    new_config = {part: data.get(part) for part in ("providers", "profiles", "default_profile", "routes")}
    errors = llm_config.validate(new_config)
    if errors:
        return jsonify({"status": "error", "errors": errors}), 400
    new_config = llm_config.with_stored_keys(new_config, LLM_CONFIG)
    llm_config.save(LLM_CONFIG_PATH, new_config)
    LLM_CONFIG = new_config
    logging.info("LLM: Saved the LLM configuration from the web app.")
    return get_llm_config()

@app.route('/api/llm/reset', methods=['POST'])
def reset_llm_config():
    global LLM_CONFIG
    new_config = llm_config.reset(default_llm_config(), LLM_CONFIG)
    llm_config.save(LLM_CONFIG_PATH, new_config)
    LLM_CONFIG = new_config
    logging.info("LLM: Reset the LLM configuration to the defaults.")
    return get_llm_config()

@app.route('/api/prompts', methods=['GET'])
def get_prompts():
    return jsonify({"status": "ok", "prompts": prompt_store.listing(PROMPTS_DIR, USER_PROMPTS_DIR, CAMPAIGN_TEXTS)})

@app.route('/api/prompts', methods=['POST'])
def save_prompt():
    data = request.get_json(silent=True) or {}
    name, text = data.get("name"), data.get("text")
    if not isinstance(name, str) or not isinstance(text, str):
        return jsonify({"status": "error", "message": "The request needs a prompt name and its text."}), 400
    try:
        warnings = prompt_store.save(name, text, PROMPTS_DIR, USER_PROMPTS_DIR, CAMPAIGN_TEXTS)
    except ValueError as e:
        return jsonify({"status": "error", "errors": [{"field": [name], "message": str(e)}]}), 400
    logging.info(f"PROMPT: Saved {name} from the web app.")
    return jsonify({"status": "ok", "warnings": warnings})

@app.route('/api/llm/test', methods=['POST'])
def test_llm_profile():
    """Tests the profile and the provider as the web app holds them, so the player can test before a save."""
    data = request.get_json(silent=True) or {}
    profile, provider = data.get("profile"), data.get("provider")
    if not isinstance(profile, dict) or not isinstance(provider, dict):
        return jsonify({"status": "error", "message": "The test needs a profile and its provider."}), 400
    provider_name = profile.get("provider", "")
    errors = llm_config.provider_errors(provider_name, provider) + llm_config.profile_errors(data.get("name", ""), profile, {provider_name: provider})
    if errors:
        return jsonify({"status": "error", "errors": errors}), 400
    provider = llm_config.provider_from_form(provider_name, provider, LLM_CONFIG)
    messages = [{"role": "user", "content": "Keep your response extremely short. Reply with the word: Success"}]
    body = llm_router.build_body({"max_tokens": 200, "temperature": 0.7}, profile, messages)
    try:
        text = send_completion(provider, profile, body, min(profile["timeout"], 30))
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 502
    if not text:
        return jsonify({"status": "error", "message": "The model returned an empty completion."}), 502
    return jsonify({"status": "ok", "response": text})

# POST, because the provider in the form may not be saved.
@app.route('/api/llm/models', methods=['POST'])
def list_llm_models():
    data = request.get_json(silent=True) or {}
    name, provider = data.get("name", ""), data.get("provider")
    if not isinstance(provider, dict):
        return jsonify({"status": "error", "message": "The request needs a provider."}), 400
    errors = llm_config.provider_errors(name, provider)
    if errors:
        return jsonify({"status": "error", "errors": errors}), 400
    provider = llm_config.provider_from_form(name, provider, LLM_CONFIG)
    try:
        response = requests.get(f"{provider['base_url'].rstrip('/')}/models", headers={"Authorization": f"Bearer {provider.get('api_key', '')}"}, timeout=15)
        if response.status_code != 200:
            raise RuntimeError(f"HTTP {response.status_code}: {response.text[:200]}")
        models = llm_config.model_ids(response.json())
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 502
    return jsonify({"status": "ok", "models": models})


@app.route('/history', methods=['POST'])
def get_history():
    logging.debug("HTTP: POST /history")
    data = request.json or {}
    
    npc_name = data.get('npc', data.get('name', 'Someone'))
    
    logging.debug(f"HISTORY: Request for {npc_name}")
    
    clean_npc_name = npc_name.split('|')[0] if '|' in npc_name else npc_name
    context = data.get('context', '')
    
    char_data = campaign_db.get_npc(clean_npc_name)
    if not char_data:
        logging.debug(f"HISTORY: Falling back to get_character_data for {clean_npc_name}")
        char_data = get_character_data(clean_npc_name, context)

    if "Race" not in char_data: char_data["Race"] = "Unknown"
    if "Faction" not in char_data: char_data["Faction"] = "Unknown"
    
    history = char_data.get('ConversationHistory', [])
    
    import textwrap
    def _wrap(text):
        if not text: return ""
        paragraphs = text.split('\n')
        wrapped = []
        for p in paragraphs:
            if not p.strip():
                wrapped.append("")
                continue
            wrapped.extend(textwrap.wrap(p, width=110))
        return "\n".join(wrapped)
        
    lines = []
    lines.append(f"--- PROFILE: {char_data.get('Name', clean_npc_name)} ---")
    lines.append(f"Faction: {char_data.get('Faction', 'Unknown')} | Race: {char_data.get('Race', 'Unknown')}")
    lines.append(generate_relation_bar(char_data.get('Relation', 0)))
    lines.append("-" * 30)
    lines.append("PERSONALITY:")
    lines.append(_wrap(char_data.get('Personality', 'Unknown')))
    lines.append("")
    lines.append("BACKSTORY:")
    lines.append(_wrap(char_data.get('Backstory', 'Unknown')))
    lines.append("-" * 30)
    lines.append(f"CONVERSATION LOG (Showing last 250 of {len(history)} lines):")
    if history:
        # Capped: longer logs freeze the in-game history window
        trimmed_history = history[-250:]
        for log_line in trimmed_history:
            lines.append(_wrap(log_line))
    else:
        lines.append("(No history recorded)")
        
    formatted_output = "\n".join(lines)
    
    logging.debug(f"HISTORY: Returning formatted report for {clean_npc_name} ({len(history)} lines)")
    return jsonify({
        "status": "ok",
        "text": formatted_output
    })

@app.route('/characters', methods=['GET', 'POST'])
def list_characters():
    data = request.json or {}
    sort_mode = data.get("sort", "alphabetical") # alphabetical or latest
    
    logging.debug(f"LIBRARY: Listing the characters of '{ACTIVE_CAMPAIGN}' (sort: {sort_mode})")
    npc_list = [
        {"display": n["name"], "sid": n["storage_id"], "updated_at": n["updated_at"], "is_fav": n["favorite"]}
        for n in campaign_db.list_npcs()
    ]
    favorites = [n["sid"] for n in npc_list if n["is_fav"]]

    unique_npcs = {}
    for n in npc_list:
        name = n["display"]
        if name not in unique_npcs:
            unique_npcs[name] = n
        else:
            if '_' in n["sid"]:
                unique_npcs[name] = n

    final_list = list(unique_npcs.values())

    if sort_mode == "latest":
        final_list.sort(key=lambda x: x["updated_at"], reverse=True)
    else:
        final_list.sort(key=lambda x: x["display"].lower())

    favs = [n for n in final_list if n["is_fav"]]
    others = [n for n in final_list if not n["is_fav"]]
    
    sorted_npcs = favs + others
    
    names = [f"{n['display']}|{n['sid']}" for n in sorted_npcs]
    
    return jsonify({
        "status": "ok",
        "characters": ",".join(names),
        "names": ",".join(names),
        "favorites": favorites
    })

@app.route('/favorite', methods=['POST'])
def toggle_favorite():
    data = request.json or {}
    sid = data.get("sid")
    if not sid:
        return jsonify({"status": "error"}), 400

    is_fav = campaign_db.toggle_favorite(sid)
    if is_fav is None:
        return jsonify({"status": "error", "message": "Profile not found"}), 404

    return jsonify({"status": "ok", "state": "added" if is_fav else "removed"})

def synthesis_loop():
    logging.info("NARRATIVE: Synthesis background loop started.")
    elapsed_minutes = 0
    while True:
        try:
            settings = load_settings()
            interval = settings.get("synthesis_interval_minutes", 5)
            if interval < 1: interval = 1
            
            SYNTHESIS_STATUS["interval"] = interval
            
            if elapsed_minutes >= interval:
                logging.debug(f"NARRATIVE: Interval shortened ({interval}m). Triggering synthesis.")
                generate_global_narrative_thread()
                elapsed_minutes = 0
                SYNTHESIS_STATUS["elapsed"] = 0
                continue

            for _ in range(6):
                time.sleep(10)
            
            speed = PLAYER_CONTEXT.get("gamespeed", 1.0)
            
            if speed > 0.1:
                elapsed_minutes += 1
                SYNTHESIS_STATUS["elapsed"] = elapsed_minutes
                if elapsed_minutes % 10 == 0:
                    logging.debug(f"NARRATIVE: Timer progress: {elapsed_minutes}/{interval} minutes.")
            
            if elapsed_minutes >= interval:
                logging.debug(f"NARRATIVE: Timer reached ({interval}m). Triggering periodic synthesis.")
                generate_global_narrative_thread()
                elapsed_minutes = 0
                SYNTHESIS_STATUS["elapsed"] = 0
                    
        except Exception as e:
            logging.error(f"NARRATIVE: Synthesis loop failed: {e}")
            time.sleep(60)

threading.Thread(target=synthesis_loop, daemon=True).start()

def player2_ping_loop():
    logging.debug("PLAYER2: Health check thread started.")
    
    while True:
        try:
            for name in llm_config.player2_providers_in_use(LLM_CONFIG):
                provider = LLM_CONFIG["providers"][name]
                if not PLAYER2_SESSION_KEY and refresh_player2_session(provider):
                    logging.info("PLAYER2: Session authorized.")

                try:
                    h = {
                        "player2-game-key": provider.get("game_key", ""),
                        "Authorization": f"Bearer {PLAYER2_SESSION_KEY}" if PLAYER2_SESSION_KEY else ""
                    }
                    resp = requests.get(f"{provider['base_url'].rstrip('/')}/health", headers=h, timeout=5)
                    if resp.status_code == 200:
                        logging.debug("PLAYER2: The Player2 app is up.")
                    else:
                        logging.warning(f"PLAYER2: Health check returned status {resp.status_code}")
                except Exception as e:
                    logging.warning(f"PLAYER2: The Player2 app is down or unreachable: {e}")
            
        except Exception as e:
            logging.error(f"PLAYER2: Health check loop failed: {e}")
        
        time.sleep(60)

threading.Thread(target=player2_ping_loop, daemon=True).start()

def monitor_kenshi_process():
    """The plugin launches the server, so the parent is Kenshi; exit when it does."""
    try:
        ppid = os.getppid()
        if ppid <= 1:
            logging.info("SYSTEM: Parent PID is 0 or 1, skipping auto-shutdown monitor.")
            return
            
        logging.info(f"SYSTEM: Monitoring parent process (PID {ppid}) for auto-shutdown.")
        
        PROCESS_QUERY_INFORMATION = 0x0400
        STILL_ACTIVE = 259
        
        kernel32 = ctypes.windll.kernel32
        
        while True:
            handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION, False, ppid)
            if not handle:
                logging.info(f"SYSTEM: Parent Kenshi process (PID {ppid}) no longer found. Shutting down server.")
                os._exit(0)
                
            exit_code = ctypes.c_ulong()
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                if exit_code.value != STILL_ACTIVE:
                    kernel32.CloseHandle(handle)
                    logging.info(f"SYSTEM: Parent Kenshi process (PID {ppid}) has exited. Shutting down server.")
                    os._exit(0)
            else:
                kernel32.CloseHandle(handle)
                logging.warning(f"SYSTEM: Failed to query parent process state. Assuming it closed. Shutting down server.")
                os._exit(0)
            
            kernel32.CloseHandle(handle)
            time.sleep(5) 
            
    except Exception as e:
        logging.error(f"SYSTEM: Error in kenshi process monitor: {e}")

threading.Thread(target=monitor_kenshi_process, daemon=True).start()


if __name__ == '__main__':
    logging.info("SYSTEM: Server starting on port 5000.")
    # A thread, because each message waits up to 0.25 s for a pipe that a closed game never opens
    threading.Thread(target=push_settings_to_plugin, daemon=True).start()
    if "--open-browser" in sys.argv[1:]:
        threading.Thread(target=open_when_ready, args=("127.0.0.1", 5000, PANEL_TABS), daemon=True).start()
    # Threaded: the plugin's polling must not block chat and settings requests
    app.run(host='127.0.0.1', port=5000, threaded=True)
