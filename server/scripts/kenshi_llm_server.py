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
import chat_prompt
import scene_text
import provisional_profile
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
DEFAULT_TEMPLATE = "kenshi_ssr_vanilla"

PROFILES_IN_PROGRESS = set()
PROGRESS_LOCK = threading.Lock()
LIVE_CONTEXTS = {}
PLAYER_CONTEXT = {}
PROMPT_RUMORS = 5
# The scene stays fixed for a whole conversation, so the prompt cache can serve it; a chat with another NPC or as another squad member, or a new name or faction of the NPC, starts a new one
CONVERSATION_SCENE = {}
PLAYER2_SESSION_KEY = None
EVENT_THROTTLE = {} 
THROTTLE_LOCK = threading.Lock()
LAST_STATE_LOG = {} # {"<target>|<etype>": last message}
STATE_LOCK = threading.Lock()
SYNTHESIS_STATUS = {"elapsed": 0, "interval": 60}
WRITE_REQUESTS = 0
SEEN_FACTIONS = set()

ANIMAL_RACES = [
    "Bonedog", "Boneyard Wolf", "Garru", "Beak Thing", "Gorillo",
    "Landbat", "Goat", "Bull", "Leviathan", "Blood Spider", "Skin Spider",
    "Cave Crawler", "Crab", "Raptor", "Darkfinger", "Thrasher", "Cleaner",
    "Crimper", "Skimmer", "Beeler", "Bat", "Spider", "Wolf",
    "Dog", "Turtle", "Cleanser", "Gurgler", "Fishman"
]

def describe_faction(name, faction_id=None):
    return faction_text(name, campaign_db.find_faction(faction_id, name) if name and name != "Unknown" else None)

def faction_text(name, faction):
    if not name or name == "Unknown":
        return "Unknown Faction (Remnant or Drifter)"
    if not faction or not (faction.get("description") or faction.get("fields") or faction.get("major")):
        return f"{name}: A minor or specialized group in the wasteland."
    return describe_record(faction)

def describe_origin(origin, current):
    """Most NPCs still belong to their origin faction, whose whole entry the prompt already holds."""
    return "Same as the current faction." if origin == current else origin

def describe_record(record):
    details = "; ".join(f"{key}: {', '.join(value) if isinstance(value, list) else value}" for key, value in record.get("fields", {}).items())
    text = f"{record['name']} ({details})" if details else record["name"]
    return f"{text}: {record['description']}" if record.get("description") else text

def find_named(records, name):
    wanted = str(name).strip().lower()
    return next((record for record in records if wanted in (other.lower() for other in [record.get("name", ""), *record.get("aliases", [])])), None)

def find_race(race):
    return find_named((entry for (category, _), entry, *_ in campaign_db.list_records("entity") if category == "races"), race)

def describe_race(race):
    entry = find_race(race)
    return describe_record(entry) if entry else f"{race}: The campaign has no entry for this race."

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

# The web app polls this count with campaign_db.writes, so an open page loads a change from another tab or the game.
# A POST that only reads, such as a model test, costs an open page one needless load.
@app.after_request
def count_write_requests(response):
    global WRITE_REQUESTS
    if request.method == "POST" and response.status_code < 400 and (request.path.startswith("/api/") or request.path == "/settings"):
        WRITE_REQUESTS += 1
    return response

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
    return cdir

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
    return {c["name"].lower() for c in campaign_db.list_characters() if c["name"]}

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



def context_dict(context):
    if isinstance(context, dict):
        return context
    if isinstance(context, str) and context.strip().startswith('{'):
        try:
            return json.loads(context)
        except ValueError:
            pass
    return {}

# The game reports a skeleton as male. The prefixes cover the skeleton races of vanilla Kenshi and UWE.
SKELETON_RACE_PREFIXES = ("skeleton", "p2 unit", "p4 unit", "screamer", "soldierbot")

def is_skeleton(race):
    return str(race).strip().lower().startswith(SKELETON_RACE_PREFIXES)

def reported_sex(race, gender):
    return "Other" if is_skeleton(race) else gender

def is_animal(race):
    return any(keyword.lower() in str(race).lower() for keyword in ANIMAL_RACES)

def character_kind(race):
    return "animal" if is_animal(race) else "skeleton" if is_skeleton(race) else "person"

def npc_scene(npc_id, profile, player_name):
    context = LIVE_CONTEXTS.get(npc_id) or profile
    faction = context.get("faction") or context.get("Faction", "Unknown")
    player_faction = PLAYER_CONTEXT.get("faction", "Nameless")
    player_faction_id = PLAYER_CONTEXT.get("factionID")
    in_player_faction = faction == player_faction or bool(player_faction_id and context.get("factionID") == player_faction_id)
    record = campaign_db.find_faction(context.get("factionID"), faction) or {}
    major = not in_player_faction and bool(record.get("major"))
    # The player section of the scene already describes the player's faction
    faction_description = "" if in_player_faction else record.get("description", "")
    return scene_text.npc_text(context, profile, player_name, player_faction, met=bool(profile.get("ConversationHistory")),
                               major=major, in_player_faction=in_player_faction, feels_hunger=not is_skeleton(profile.get("Race", "")),
                               faction_description=faction_description)

# SetHotkeyFromString in the plugin parses only these keys
CHAT_HOTKEYS = ["\\", "[", "P", "T", "J", "U", "K"]

# The plugin reads the same [Settings] keys, so renaming one breaks it
INI_KEY_MAP = {
    "current_campaign": "ActiveCampaign",
    "enable_ambient": "EnableAmbientConversations",
    "radiant_delay": "RadiantDelay",
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
    "log_level": "LogLevel",
    "bio_interactions": "BioInteractions"
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
    "log_level": log_setup.DEFAULT_LEVEL,
    "bio_interactions": 5
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

def describe_npc(name, profile, npc_id):
    race = profile.get("Race", "Unknown")
    current_faction = describe_faction(profile.get("Faction"), LIVE_CONTEXTS.get(npc_id, {}).get("factionID"))
    return fill_prompt(
        "npc_chat_template.txt",
        name=name,
        race=race,
        sex=reported_sex(race, profile.get("Sex", "Unknown")),
        job=profile.get("Job", "None"),
        current_faction=current_faction,
        origin_faction=describe_origin(describe_faction(profile.get("OriginFaction", "Unknown")), current_faction),
        personality=profile.get("Personality") or "",
        backstory=profile.get("Backstory") or "",
        speech_quirks=profile.get("SpeechQuirks") or "",
    )

def build_system_prompt():
    world_lore = campaign_db.overview()
    rules = load_prompt_component("response_rules.txt")

    # Only player2 infers the language from context; other providers need it stated
    language = load_settings().get("language", "English")
    language_instruction = ""
    if language and language.lower() != "english":
        language_instruction = f"\nLANGUAGE: You MUST respond ONLY in {language}. Do not switch to English under any circumstances.\n"

    prompt = fill_prompt(
        "prompt_system.txt",
        world_lore=world_lore,
        rules=rules,
        language_instruction=language_instruction
    )
    return prompt.strip()

def scene_values(player, player_name, facing=True):
    """facing is False for banter, which has no NPC in front of the player."""
    rumors = [line for _, line in campaign_db.rumors() if line.startswith("- [")][-PROMPT_RUMORS:]
    race = player.get("race", "Unknown")
    race_entry = find_race(race)
    player_faction = campaign_db.player_faction()
    return {
        "location": scene_text.location_text(player.get("environment") or {}),
        "rumors": scene_text.rumors_text(rumors, PLAYER_CONTEXT.get("day")),
        "player": scene_text.player_text(
            player_name, facing, race, reported_sex(race, player.get("gender", "Unknown")),
            race_entry.get("description", "") if race_entry else "",
            player.get("medical") or {}, not is_skeleton(race),
            player.get("faction", "Nameless"), player_faction["description"].strip() if player_faction else "",
            player.get("inventory") or [],
        ),
    }


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
    log_cache_use(profile["model"], data)
    return extract_completion(data, profile["model"])

def log_cache_use(model, data):
    """Shows whether the provider's prompt cache served the stable start of a prompt. Each provider reports it under its own key."""
    if not isinstance(data, dict):
        return
    usage = data.get("usage") or {}
    cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens", usage.get("prompt_cache_hit_tokens", (data.get("timings") or {}).get("cache_n")))
    logging.info(f"LLM: {model} read {usage.get('prompt_tokens', 'an unknown number of')} prompt tokens, {'an unknown number' if cached is None else cached} of them from its cache")

def call_llm(task, messages):
    """Returns the completion text from the first profile of the task's route that answers, or None."""
    llm_log.debug(f"{task} request:\n" + "\n".join(f"[{m['role']}]\n{m['content']}" for m in messages))
    text = llm_router.run_route(LLM_CONFIG, task, messages, send_completion)
    llm_log.debug(f"{task} reply:\n{text}")
    return text

LLM_CONFIG = load_llm_config()

def new_profile(name, npc_id, ctx_data):
    """The profile of an NPC at its first meeting, rolled in code. The LLM would know no more than the race, the faction, and
    the job yet, so the roll loses nothing; the LLM writes the bio later (generate_bio). An animal's roll is final, because a
    bio would give it a backstory and a speech quirk."""
    live_ctx = LIVE_CONTEXTS.get(npc_id) or {}

    def fact(key, missing="Unknown"):
        value = ctx_data.get(key, missing)
        return live_ctx.get(key, missing) if value == missing else value

    race = fact("race")
    kind = character_kind(race)
    faction = fact("faction")
    # Modded factions often report no name through the hooks
    if faction == "Unknown":
        faction = ctx_data.get("factionID") or live_ctx.get("factionID") or "Unknown"
    logging.info(f"PROFILE: Rolled the profile of {name} ({npc_id})")
    return {
        "Name": name,
        "Race": race,
        "Sex": reported_sex(race, fact("gender")),
        "Faction": faction,
        "OriginFaction": fact("origin_faction"),
        "Job": fact("job", "None"),
        **provisional_profile.roll(npc_id, kind),
        "ConversationHistory": [],
        "Relation": int(float(ctx_data.get("relation", 0)) / 2),
        **({} if kind == "animal" else {campaign_db.PROVISIONAL: 0}),
    }

BIO_PARTS = ("Personality", "Backstory", "SpeechQuirks")

def write_bio(profile, parts, instructions, history, race_lore, faction):
    """The parts of the bio that the LLM wrote, or None when its reply lacks one. Stores nothing."""
    race = profile.get("Race", "Unknown")
    names = ", ".join(parts)
    prompt = fill_prompt(
        "prompt_profile_generation.txt",
        parts=names,
        name=profile.get("Name", "Unknown"),
        race=race,
        sex=reported_sex(race, profile.get("Sex", "Unknown")),
        faction=faction,
        job=profile.get("Job") or "None",
        race_lore=race_lore,
        current="\n".join(f"{part}: {profile.get(part) or ''}" for part in BIO_PARTS),
        history="\n".join(history) or "None yet.",
        instructions=instructions.strip() or "None.",
    )
    language = load_settings().get("language", "English")
    if language and language.lower() != "english":
        prompt += f"\nLANGUAGE: The JSON values ({names}) MUST be written entirely in {language}. Do not use English.\n"
    result = robust_json_parse(call_llm("profile", [{"role": "user", "content": prompt}]))
    # Only the requested parts, so a reply cannot change a part that the player did not ask for
    bio = {part: result[part].strip() for part in parts if isinstance((result or {}).get(part), str) and result[part].strip()}
    return bio if len(bio) == len(parts) else None

def generate_bio(npc_id, provisional_only=True):
    """Has the LLM rewrite the bio of a stored NPC. Returns None once the bio is stored, else the reason it is not. The chat
    threshold must not touch a full profile, because the player may have written it by hand."""
    with PROGRESS_LOCK:
        if npc_id in PROFILES_IN_PROGRESS:
            logging.debug(f"PROFILE: The LLM is already writing the bio of {npc_id}.")
            return "The LLM is already writing the bio of this character."
        PROFILES_IN_PROGRESS.add(npc_id)
    campaign = ACTIVE_CAMPAIGN
    try:
        profile = campaign_db.get_character(npc_id)
        if not profile:
            return "The character has no profile."
        provisional = campaign_db.PROVISIONAL in profile
        if provisional_only and not provisional:
            return "The character has no provisional profile."
        name, race = profile.get("Name", npc_id), profile.get("Race", "Unknown")
        logging.info(f"PROFILE: Writing the bio of {name} ({npc_id})...")
        bio = write_bio(
            profile,
            # An animal keeps no backstory and no speech quirk
            ["Personality"] if is_animal(race) else list(BIO_PARTS),
            "",
            profile.get("ConversationHistory", []),
            describe_race(race),
            describe_faction(profile.get("Faction"), (LIVE_CONTEXTS.get(npc_id) or {}).get("factionID")),
        )
        if not bio:
            logging.warning(f"PROFILE: The LLM gave no usable bio for {name}, so the profile stays as it is.")
            return "The LLM gave no usable bio. Try again."
        # A thread can outlive a campaign switch, and the same npc_id can name another character in the new campaign
        if ACTIVE_CAMPAIGN != campaign:
            logging.info(f"PROFILE: Dropped the bio of {name}, because the active campaign changed while the LLM wrote it.")
            return "The active campaign changed while the LLM wrote the bio."
        if not provisional:
            campaign_db.upsert_profile(npc_id, bio)
        elif not campaign_db.promote_profile(npc_id, bio):
            logging.info(f"PROFILE: Dropped the bio of {name}, because its profile stopped being provisional while the LLM wrote it.")
            return "The profile stopped being provisional while the LLM wrote the bio, for example after an edit on Campaign Canon."
        logging.info(f"PROFILE: Stored the bio of {name} ({npc_id}).")
        return None
    except Exception as e:
        # The chat threshold runs this in a thread, where nothing else would log the error
        logging.error(f"PROFILE: The bio of {npc_id} failed: {e}")
        return f"The bio failed: {e}"
    finally:
        with PROGRESS_LOCK:
            PROFILES_IN_PROGRESS.discard(npc_id)

def get_character_data(name, context=""):
    """The profile of the NPC that the context names by npc_id. Without an npc_id the profile is a stand-in that is never stored."""
    name = str(name).split('|')[0].strip()
    ctx_data = context_dict(context)
    npc_id = ctx_data.get("npc_id")

    data = campaign_db.get_character(npc_id) if npc_id else None
    stored = dict(data) if data else {}

    if ctx_data:
        try:
            if data:
                current_race = ctx_data.get("race", "Unknown")
                current_sex = reported_sex(current_race, ctx_data.get("gender", "Unknown"))
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
                    campaign_db.upsert_profile(npc_id, {k: data[k] for k in ("Race", "Sex", "Faction", "OriginFaction", "Job")})
        except Exception as e:
            logging.error(f"PROFILE: Cannot update the profile from the context: {e}")

    if not data:
        if not npc_id:
            logging.debug(f"PROFILE: {name} has no npc_id, so the chat uses a stand-in profile.")
            return {
                "Name": name,
                "Race": ctx_data.get("race", "Unknown"),
                "Sex": reported_sex(ctx_data.get("race", "Unknown"), ctx_data.get("gender", "Unknown")),
                "Faction": ctx_data.get("faction", "Unknown"),
                "OriginFaction": ctx_data.get("origin_faction", "Unknown"),
                "Job": ctx_data.get("job", "None"),
                "Personality": "A quiet traveler.",
                "Backstory": f"A {ctx_data.get('race', 'person')} from {ctx_data.get('faction', 'the borderlands')}.",
                "SpeechQuirks": "",
                "ConversationHistory": [],
                "Relation": int(float(ctx_data.get("relation", 0)) / 2),
            }
        data = new_profile(name, npc_id, ctx_data)

    if should_save_profile(name, npc_id, data):
        # Only the changed keys, so the write cannot undo a change that another request made since the read
        changes = {k: v for k, v in data.items() if stored.get(k) != v}
        if changes:
            campaign_db.upsert_profile(npc_id, changes)
    return data

def should_save_profile(name, npc_id, data):
    if not name or name in ("Unknown", "Someone"):
        return False
        
    personality = data.get("Personality", "").lower()
    is_generic_content = any(x in personality for x in ("unknown", "generic npc"))
    has_history = len(data.get("ConversationHistory", [])) > 0
    
    if is_generic_content and not has_history:
        return False
        
                
    return True


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

    new_name = data.get('new_name')
    npc_id = context_dict(data.get('context', '')).get('npc_id')
    if not npc_id or not new_name:
        return jsonify({"status": "error", "message": "Missing the NPC ID or the new name"}), 400

    if not campaign_db.character_exists(npc_id):
        logging.info(f"RENAME: No profile for {npc_id}, so the next chat creates one with the name {new_name}")
        return jsonify({"status": "ok", "message": "No profile to rename"})

    campaign_db.rename_character(npc_id, data.get('old_name', ''), new_name)
    logging.info(f"RENAME: {data.get('old_name')} is now {new_name} ({npc_id})")
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
    
    npc_limit = npcs_data[:12]

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
            char_profiles += f"\n- {name}|{nid} ({reported_sex(npc.get('race'), npc.get('gender'))} {npc.get('race')}, {npc.get('faction')}) | Health: {health} | Gear: {gear} | Personality: {d.get('Personality') or ''} | Speech quirks: {d.get('SpeechQuirks') or ''}"
        else:
            name_to_id[npc] = 0
            d = get_character_data(npc, "")
            
            if d.get("ConversationHistory"):
                recent_dialogue.extend(d["ConversationHistory"][-15:])
                
            char_profiles += f"\n- {npc} (A traveler): {d.get('Personality') or ''} | Speech quirks: {d.get('SpeechQuirks') or ''}"

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

    dynamic_system_prompt = build_system_prompt()
    scene = scene_values(PLAYER_CONTEXT, player_name, facing=False)

    ambient_system_prompt = f"""{dynamic_system_prompt}

{scene['location']}

{scene['rumors']}

{scene['player']}

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
        npc_ids = {}
        for npc_obj in npc_limit:
            name = npc_obj.get('name') if isinstance(npc_obj, dict) else npc_obj
            memories[name] = get_character_data(name, context=json.dumps(npc_obj) if isinstance(npc_obj, dict) else "")
            if isinstance(npc_obj, dict) and npc_obj.get('npc_id'):
                npc_ids[name] = npc_obj['npc_id']

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
            if name in npc_ids:
                campaign_db.append_dialogue(npc_ids[name], banter, d)

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
    
    def register(raw):
        if not raw: return ""
        return raw.split('|')[0] if '|' in raw else raw

    primary_npc = register(raw_npc)
    npcs = [register(n) for n in raw_npcs]
    
    player_name = data.get('player', 'Drifter')
    mode = data.get('mode', 'talk')
    
    # Names map to an npc_id only among the NPCs of this request; name assignment keeps them apart
    npc_ids = {}
    nearby = data.get('nearby', [])
    for n in nearby:
        name, npc_id = n.get('name'), n.get('npc_id')
        if name and npc_id:
            npc_ids[name] = npc_id
            LIVE_CONTEXTS[npc_id] = {
                "race": n.get('race', 'Unknown'),
                "faction": n.get('faction', 'Unknown'),
                "gender": n.get('gender', 'Unknown'),
                "nearby": [x for x in nearby if x.get('name') != name],
                "player_dist": n.get('dist', 999.0)
            }

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

    # A new profile and the scene read race/faction from LIVE_CONTEXTS
    if primary_npc and context:
        try:
            ctx_dict = context_dict(context)
            if ctx_dict:
                note_faction(ctx_dict)
            if ctx_dict.get('npc_id'):
                npc_ids[primary_npc] = ctx_dict['npc_id']
                # Merge rather than replace, to keep the nearby list and other tracked fields
                target = LIVE_CONTEXTS.setdefault(ctx_dict['npc_id'], {})
                if ctx_dict.get('race'): target["race"] = ctx_dict.get('race')
                if ctx_dict.get('faction'): target["faction"] = ctx_dict.get('faction')
                if ctx_dict.get('factionID'): target["factionID"] = ctx_dict.get('factionID')
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
                
        npc_id = npc_ids.get(clean_target)
        if npc_id in LIVE_CONTEXTS:
            return json.dumps(dict(LIVE_CONTEXTS[npc_id], npc_id=npc_id))
            
        return ""

    raw_listeners = list(set([primary_npc] + npcs_in_radius))
    listeners = []
    for l in raw_listeners:
        clean_l = l.split('|')[0] if '|' in l else l
        if clean_l not in listeners: listeners.append(clean_l)


    char_datas = {}
    for name in listeners:
        try:
            char_datas[name] = get_character_data(name, get_local_context(name))
        except Exception as e:
            logging.error(f"PROFILE: Cannot fetch the profile of {name}: {e}")

    # The squad member who talks
    speaker = context_dict(data.get('speaker'))

    primary_data = char_datas.get(primary_npc)
    if not primary_data:
        logging.warning(f"PROFILE: No profile for {primary_npc}, so the chat uses a generic one.")
        primary_data = char_datas[primary_npc] = {"Name": primary_npc, "Personality": "A generic NPC.", "Backstory": "", "ConversationHistory": []}

    logging.info(f"CHAT: {mode} with {primary_npc} ({len(listeners) - 1} others hear it)...")

    primary_race = primary_data.get('Race', 'Unknown')
    animal = is_animal(primary_race)

    if animal:
        system_prompt = f"CRITICAL: {primary_npc} is an ANIMAL ({primary_race}). Animals in Kenshi CANNOT speak human languages. They do not use words, symbols, or telegram-style speech. They ONLY react with brief physical actions, sounds, or gestures described within asterisks."
        final_instruction = f"Respond as {primary_npc} (the animal). Provide a single, BRIEF action description or sound in asterisks (e.g. *Growls*, *Tilts head*, *Nuzzles hand*). DO NOT USE WORDS OR SPEECH. Keep it under 6 words."
        judgment = ""
    else:
        system_prompt = build_system_prompt()
        judgment = "" if is_ambient else "JUDGMENT: End every reply with [JUDGMENT: n], from -5 (the player was hostile or insulting) to 5 (the player was friendly or respectful); 0 is neutral."
        final_instruction = f"Reply as {primary_npc}{', quietly' if mode == 'whisper' else ''}.{' End with [JUDGMENT: n].' if judgment else ''}"

    mode_tag = {"whisper": "(Whispered) ", "yell": "(Yelled) "}.get(mode, "")
    time_prefix = get_current_time_prefix()
    full_player_entry = f"{time_prefix}{mode_tag}{player_name}: {player_message}"

    live = LIVE_CONTEXTS.get(npc_ids.get(primary_npc), {})
    conversation = (speaker.get("npc_id"), npc_ids.get(primary_npc) or primary_npc, primary_npc, live.get("faction"))
    scene = CONVERSATION_SCENE.get(conversation)
    if scene is None:
        scene = fill_prompt(
            "prompt_chat_scene.txt",
            **scene_values(speaker or PLAYER_CONTEXT, player_name),
            npc=npc_scene(npc_ids.get(primary_npc), primary_data, player_name),
        )
        CONVERSATION_SCENE.clear()
        CONVERSATION_SCENE[conversation] = scene
    system = fill_prompt("prompt_chat_template.txt", system_prompt=system_prompt, judgment=judgment, primary_npc=primary_npc, npc_profiles=describe_npc(primary_npc, primary_data, npc_ids.get(primary_npc)), scene=scene)
    turn = fill_prompt("prompt_chat_turn.txt", player_line=full_player_entry, final_instruction=final_instruction)
    history = chat_prompt.history_window(primary_data["ConversationHistory"], campaign_db.DIALOGUE_BLOCK)
    messages = chat_prompt.chat_messages(system, chat_prompt.history_turns(history, primary_npc), turn)

    content = call_llm("chat", messages)
    if not content:
        logging.error("CHAT: No reply from the LLM.")
    
    if content:
        judged = re.search(r'\[[^\]]*JUDGMENT\D*?(-?\d+)[^\]]*\]', content, re.IGNORECASE)
        judgment_value = max(-5, min(5, int(judged.group(1)))) if judged else 0
        relation_deltas = {}
        if judgment_value and not is_ambient:
            # Applied as a delta at save time: the profile read before the LLM call can be stale by then
            relation_deltas[primary_npc] = judgment_value

        # Allows one level of nested brackets: item names like "Bolts [Toothpicks]" contain them
        content = re.sub(r'\[\s*(?:[^\[\]]|\[[^\[\]]*\])+\s*\]', '', content).strip()


        content = content.replace('"', '').strip()
        
        lines = content.split('\n')
        other_names = {name.lower() for name in [*npcs, *npc_ids]} - {primary_npc.lower()}
        filtered_lines = []
        for line in lines:
            line = line.strip()
            if not line: continue
            
            line = re.sub(r'\[\s*[^\]]+\s*\]', '', line).strip()
            if not animal:
                # An animal speaks only in *actions*; a person's *nods* is a stage direction, so it goes and the words stay
                line = re.sub(r'\*[^*]*\*', '', line).replace('*', '').strip()
            if not line: continue

            lower_line = line.lower()
            if any(lower_line.startswith(prefix) for prefix in [
                "thought:", "thinking:", "observation:", "note:", "(thinking", 
                "as an ai", "i cannot", "here is", "raw llm response:", 
                "timestamp:", "request for:", "prompt:", "user message:",
                "history:", "character:", "personality:", "backstory:", "current condition"
            ]):
                continue
            
            # A divider such as "===" holds no letters, but an animal's "Grr" does
            if not any(c.isalnum() for c in line):
                continue
                
            # Only a known name counts as a speaker, so a reply such as "Listen: ..." keeps its first word
            prefix_match = re.match(r'^([^:]{1,63}):\s*', line)
            if prefix_match:
                p = prefix_match.group(1).strip().lower()
                if p == player_name.lower() or p in other_names:
                    logging.debug(f"CHAT: Filter: Discarded a line voiced as {p} (expected {primary_npc})")
                    continue
                if p == primary_npc.lower():
                    line = line[prefix_match.end():]
            
            if line:
                filtered_lines.append(line)
        
        # The plugin shows each line as its own speech bubble, so one reply is one line
        content = " ".join(filtered_lines) if filtered_lines else "..."

        if len(content) > 500:
            content = content[:497] + "..."
        
        player_faction = PLAYER_CONTEXT.get("faction", "None")
        primary_faction = primary_data.get("Faction", "None")
        record_event_to_history("CHAT", player_name, primary_npc, player_message, actor_faction=player_faction, target_faction=primary_faction)
        record_event_to_history("CHAT", primary_npc, player_name, content, actor_faction=primary_faction, target_faction=player_faction)

        reply_line = f"{primary_npc}: {content}"

        for name in listeners:
            overheard_tag = "" if name == primary_npc else "(Overheard) "

            if name not in char_datas:
                char_datas[name] = get_character_data(name, get_local_context(name))

            stored_lines = len(char_datas[name]["ConversationHistory"])
            char_datas[name]["ConversationHistory"].append(f"{time_prefix}{overheard_tag}{mode_tag}{player_name}: {player_message}")
            char_datas[name]["ConversationHistory"].append(f"{time_prefix}{overheard_tag}{reply_line}")

            npc_id = npc_ids.get(name)
            if npc_id and should_save_profile(name, npc_id, char_datas[name]):
                campaign_db.append_dialogue(npc_id, char_datas[name]["ConversationHistory"][stored_lines:], char_datas[name])
                if name in relation_deltas:
                    new_rel = campaign_db.change_relation(npc_id, relation_deltas[name])
                    logging.info(f"RELATION: {name} personal relation is now {new_rel} (judgment={relation_deltas[name]})")

        primary_id = npc_ids.get(primary_npc)
        interactions = campaign_db.count_interaction(primary_id) if primary_id and not is_ambient else None
        threshold = load_settings()["bio_interactions"]
        if interactions is not None and threshold and interactions >= threshold:
            # In the background, so the reply does not wait for a second LLM call
            threading.Thread(target=generate_bio, args=(primary_id,), daemon=True).start()

        logging.debug(f"CHAT: Reply: {content}")
        # The plugin takes the text before a first colon as the speaker, so the reply names its NPC first
        return jsonify({"text": f"{primary_npc}: {content}", "actions": []})
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
    # A rumor without a game time is never culled
    if "day" not in PLAYER_CONTEXT:
        logging.debug("NARRATIVE: No game time yet, so no synthesis.")
        return None
    settings = load_settings()
    last_chunk = campaign_db.recent_events(100)

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
    
    # An event without a game time is never culled; the plugin sends its recent events again with each post
    if not is_paused and game_speed > 0.05 and "day" in PLAYER_CONTEXT:
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
        npc_id = data.get("npc_id")
        if npc_id:
            LIVE_CONTEXTS[npc_id] = data
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
        # Both counts only grow, so the sum changes when either does
        "writes": campaign_db.writes + WRITE_REQUESTS,
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
        "log_level": log_setup.parse_level(settings["log_level"]),
        "bio_interactions": settings["bio_interactions"]
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

    syn_timer = data.get("synthesis_timer")
    if syn_timer is not None:
        try:
            val = int(syn_timer)
            changes["synthesis_interval_minutes"] = val
            logging.info(f"SETTINGS: Synthesis timer set to {val} minutes")
        except: pass

    bio_interactions = data.get("bio_interactions")
    if bio_interactions is not None:
        try:
            val = max(0, int(bio_interactions))
            changes["bio_interactions"] = val
            logging.info(f"SETTINGS: Bio threshold set to {val} chats")
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
    return safe_name

def switch_campaign(name):
    global ACTIVE_CAMPAIGN, LIVE_CONTEXTS
    cdir = os.path.join(CAMPAIGNS_DIR, name)
    if not name or os.path.exists(cdir):
        ACTIVE_CAMPAIGN = name
        save_settings({"current_campaign": name})
        LIVE_CONTEXTS.clear()
        SEEN_FACTIONS.clear()
        CONVERSATION_SCENE.clear()
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

@app.route('/api/templates/<name>/export', methods=['GET'])
def export_template(name):
    try:
        data = world_template.export_template(name, WORLD_TEMPLATES_DIR, USER_TEMPLATES_DIR)
    except world_template.TemplateError as e:
        return template_error(e)
    # Not jsonify: it sorts the keys, and the shared file reads best in the order of the template folder
    return app.response_class(json.dumps(data, ensure_ascii=False), mimetype="application/json")

@app.route('/api/templates/import', methods=['POST'])
def import_template():
    data = request.get_json(silent=True) or {}
    try:
        name = world_template.import_template(data.get("template"), data.get("name"), WORLD_TEMPLATES_DIR, USER_TEMPLATES_DIR)
    except world_template.TemplateError as e:
        return template_error(e)
    logging.info(f"TEMPLATE: Imported {name}")
    return jsonify({"status": "ok", "name": name})

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
    campaigns = [{"name": name, "active": name == ACTIVE_CAMPAIGN} for name in campaign_names()]
    return jsonify({"status": "ok", "campaigns": campaigns, "refusal": campaign_db.unavailable_reason(), "templates": world_template.listing(WORLD_TEMPLATES_DIR, USER_TEMPLATES_DIR), "default_template": DEFAULT_TEMPLATE})

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
            "bio_interactions": load_settings()["bio_interactions"],
            "overview": campaign_db.overview(),
            "history": campaign_db.history(),
            "factions": [
                {"id": f["faction_id"], "data": {"game_id": f["faction_id"], **{key: f[key] for key in campaign_db.FACTION_KEYS}}, "is_player": f["is_player"], "origin": f["origin"], "updated_at": f["updated_at"]}
                for f in campaign_db.list_factions()
            ],
            "characters": [
                {"id": npc_id, "data": {"game_id": npc_id.removeprefix("u:"), "profile": profile}, "origin": origin, "updated_at": updated_at, "current_faction": LIVE_CONTEXTS.get(npc_id, {}).get("faction")}
                for (npc_id,), profile, origin, updated_at in campaign_db.list_records("character")
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
                if data.get("id") is None:
                    record_id = campaign_db.unique_npc_id(record_id)
                elif campaign_db.PROVISIONAL in character["profile"]:
                    # A later bio would overwrite text that the player wrote
                    stored = campaign_db.get_character(record_id) or {}
                    if any(character["profile"].get(key) != stored.get(key) for key in ("Personality", "Backstory", "SpeechQuirks")):
                        del character["profile"][campaign_db.PROVISIONAL]
                campaign_db.save_record("character", (record_id,), character["profile"], updated_at)
            else:
                category = data.get("category")
                if category not in world_template.CATEGORIES:
                    return record_refusal([{"field": ["category"], "message": f"{category} is not a category. Use races, locations, or regions."}])
                stored = campaign_db.list_records("entity")
                record_id = record_id or world_template.new_id(value, {ext_id for (stored_category, ext_id), *_ in stored if stored_category == category})
                entries = {f"{stored_category}/{ext_id}" for (stored_category, ext_id), *_ in stored} | {f"{category}/{record_id}"}
                errors, warnings = world_template.record_problems("entity", value, [category, data.get("id") or "new"], entries)
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

def bio_refusal(data):
    parts, profile = data.get("parts"), data.get("profile")
    if isinstance(profile, dict) and isinstance(parts, list) and parts and set(parts) <= set(BIO_PARTS):
        return None
    return jsonify({"status": "error", "message": f"Name the parts to write: {', '.join(BIO_PARTS)}."}), 400

def bio_reply(data, history, race_lore, faction):
    """The web app puts the parts into its form, and the usual record save stores them, so the player can read them first."""
    parts = [part for part in BIO_PARTS if part in data["parts"]]
    bio = write_bio(data["profile"], parts, str(data.get("instructions") or ""), history, race_lore, faction)
    if not bio:
        return jsonify({"status": "error", "message": "The LLM gave no usable text. Try again."}), 500
    return jsonify({"status": "ok", "bio": bio})

@app.route('/api/campaign/characters/bio', methods=['POST'])
def write_campaign_bio():
    data = request.get_json(silent=True) or {}
    refused = campaign_write(data) or bio_refusal(data)
    if refused: return refused
    profile = data["profile"]
    stored = campaign_db.get_character(str(data["id"])) if data.get("id") else None
    # By name only, so a faction that the player changed in the form counts, not the one the game reports
    return bio_reply(data, (stored or {}).get("ConversationHistory", []), describe_race(profile.get("Race", "Unknown")), describe_faction(profile.get("Faction")))

@app.route('/api/templates/<name>/characters/bio', methods=['POST'])
def write_template_bio(name):
    data = request.get_json(silent=True) or {}
    refused = bio_refusal(data)
    if refused: return refused
    try:
        template = world_template.load(name, WORLD_TEMPLATES_DIR, USER_TEMPLATES_DIR)
    except world_template.TemplateError as e:
        return template_error(e)
    profile = data["profile"]
    race, faction = profile.get("Race", "Unknown"), profile.get("Faction")
    race_entry = find_named(template["entities"]["races"].values(), race)
    race_lore = describe_record(race_entry) if race_entry else f"{race}: The template has no entry for this race."
    return bio_reply(data, [], race_lore, faction_text(faction, find_named(template["factions"].values(), faction)))

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
    
    char_data = campaign_db.get_character(sid)
    if not char_data:
        logging.warning(f"PROFILE: Regen found no profile for {sid}")
        return jsonify({"status": "error", "message": "Profile not found"}), 404

    reason = generate_bio(sid, provisional_only=False)
    if reason:
        return jsonify({"status": "error", "message": reason}), 500
    return jsonify({"status": "ok", "message": f"Wrote the bio of {char_data.get('Name', sid)}."})


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
    return jsonify({"status": "ok", "prompts": prompt_store.listing(PROMPTS_DIR, USER_PROMPTS_DIR)})

@app.route('/api/prompts', methods=['POST'])
def save_prompt():
    data = request.get_json(silent=True) or {}
    name, text = data.get("name"), data.get("text")
    if not isinstance(name, str) or not isinstance(text, str):
        return jsonify({"status": "error", "message": "The request needs a prompt name and its text."}), 400
    try:
        warnings = prompt_store.save(name, text, PROMPTS_DIR, USER_PROMPTS_DIR)
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
    
    npc_id = data.get('npc', '')
    logging.debug(f"HISTORY: Request for {npc_id}")
    char_data = campaign_db.get_character(npc_id) or {}

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
    lines.append(f"--- PROFILE: {char_data.get('Name', npc_id)} ---")
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
    
    logging.debug(f"HISTORY: Returning formatted report for {npc_id} ({len(history)} lines)")
    return jsonify({
        "status": "ok",
        "text": formatted_output
    })

@app.route('/characters', methods=['GET', 'POST'])
def list_characters():
    data = request.json or {}
    sort_mode = data.get("sort", "alphabetical") # alphabetical or latest
    
    logging.debug(f"LIBRARY: Listing the characters of '{ACTIVE_CAMPAIGN}' (sort: {sort_mode})")
    # Leaves out the seeded characters that nobody has met, so the template does not fill the library
    final_list = [
        {"display": c["name"] or c["npc_id"], "sid": c["npc_id"], "updated_at": c["updated_at"], "is_fav": c["favorite"]}
        for c in campaign_db.list_characters() if c["has_dialogue"] or c["origin"] != "seed"
    ]
    favorites = [n["sid"] for n in final_list if n["is_fav"]]

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
