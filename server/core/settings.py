import configparser
import json
import logging
import os

from core import log_setup, state
from core.paths import DEFAULTS_DIR, INI_PATH, LOCALIZATION_PATH, NAMES_PATH
from core.pipe import send_to_pipe

# SetHotkeyFromString in the plugin parses only these keys
CHAT_HOTKEYS = ["\\", "[", "P", "T", "J", "U", "K"]

# The plugin reads the same [Settings] keys, so renaming one breaks it
INI_KEY_MAP = {
    "current_campaign": "ActiveCampaign",
    "enable_radiant": "EnableRadiantConversations",
    "radiant_chat_minutes": "RadiantChatMinutes",
    "npc_radiant_chance": "NpcRadiantChance",
    "radiant_rumor_minutes": "RadiantRumorMinutes",
    "whisper_radius": "WhisperRadius",
    "talk_radius": "TalkRadius",
    "yell_radius": "YellRadius",
    "enable_welcome": "EnableWelcomePopup",
    "dialogue_speed_seconds": "DialogueSpeed",
    "language": "Language",
    "chat_hotkey": "ChatHotkey",
    "open_web_panel_on_start": "OpenWebPanelOnStart",
    "log_level": "LogLevel",
    "bio_interactions": "BioInteractions",
    "prune_profile_days": "PruneProfileDays",
    "conversation_timeout_minutes": "ConversationTimeoutMinutes",
    "retrieval_slots": "RetrievalSlots",
    "memory_slots": "MemorySlots",
    "retrieval_cooldown_turns": "RetrievalCooldownTurns",
    "barter_profit_target": "BarterProfitTargetPercent",
    "barter_relation_offset": "BarterRelationOffsetPercent",
    "characterised_dialogue": "CharacterisedDialogue"
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
    "enable_radiant": True,
    "radiant_chat_minutes": 10,
    "npc_radiant_chance": 50,
    "radiant_rumor_minutes": 30,
    "whisper_radius": 50,
    "talk_radius": 150,
    "yell_radius": 200,
    "enable_welcome": True,
    "dialogue_speed_seconds": 5,
    "language": "English",
    "chat_hotkey": "\\",
    "open_web_panel_on_start": True,
    "log_level": log_setup.DEFAULT_LEVEL,
    "bio_interactions": 5,
    "prune_profile_days": 60,
    "conversation_timeout_minutes": 3,
    "retrieval_slots": 3,
    "memory_slots": 3,
    "retrieval_cooldown_turns": 1,
    "barter_profit_target": 400,
    "barter_relation_offset": 50,
    "characterised_dialogue": False
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
            if "whisper" in v: flat_changes["whisper_radius"] = v["whisper"]
            if "talk" in v: flat_changes["talk_radius"] = v["talk"]
            if "yell" in v: flat_changes["yell_radius"] = v["yell"]
        else:
            flat_changes[k] = v
            
    settings = load_settings()
    settings.update(flat_changes)
    _save_settings_raw(settings)

def settings_page_values(settings):
    return {
        "enable_radiant": settings["enable_radiant"],
        "radiant_chat_minutes": settings["radiant_chat_minutes"],
        "npc_radiant_chance": settings["npc_radiant_chance"],
        "radiant_rumor_minutes": settings["radiant_rumor_minutes"],
        "dialogue_speed": settings["dialogue_speed_seconds"],
        "radii": {
            "whisper": settings["whisper_radius"],
            "talk": settings["talk_radius"],
            "yell": settings["yell_radius"]
        },
        "language": settings["language"],
        "chat_hotkey": settings["chat_hotkey"],
        "enable_welcome": settings["enable_welcome"],
        "open_web_panel_on_start": settings["open_web_panel_on_start"],
        "log_level": log_setup.parse_level(settings["log_level"]),
        "bio_interactions": settings["bio_interactions"],
        "prune_profile_days": settings["prune_profile_days"],
        "conversation_timeout_minutes": settings["conversation_timeout_minutes"],
        "retrieval_slots": settings["retrieval_slots"],
        "memory_slots": settings["memory_slots"],
        "retrieval_cooldown_turns": settings["retrieval_cooldown_turns"],
        "barter_profit_target": settings["barter_profit_target"],
        "barter_relation_offset": settings["barter_relation_offset"],
        "characterised_dialogue": settings["characterised_dialogue"]
    }

def push_settings_to_plugin():
    """On a first start the plugin finds no INI and runs on the defaults of LoadPluginConfig, so the server sends each value that the plugin holds."""
    settings = load_settings()
    for var, value in (
        ("g_enableRadiant", "1" if settings["enable_radiant"] else "0"),
        ("g_radiantIntervalSeconds", settings["radiant_chat_minutes"] * 60),
        ("g_whisperRadius", settings["whisper_radius"]),
        ("g_proximityRadius", settings["talk_radius"]),
        ("g_yellRadius", settings["yell_radius"]),
        ("g_chatHotkey", settings["chat_hotkey"]),
        ("g_enableWelcome", "1" if settings["enable_welcome"] else "0"),
        ("g_logLevel", settings["log_level"]),
        ("g_speechBubbleLife", settings["dialogue_speed_seconds"]),
    ):
        send_to_pipe(f"SET_CONFIG: {var}: {value}")
    logging.debug("PIPE: Sent the settings to the plugin.")

def get_config_radii():
    settings = load_settings()
    t = float(settings.get('talk_radius', 150.0))
    y = float(settings.get('yell_radius', 200.0))
    w = float(settings.get('whisper_radius', 50.0))
    return t, y, w

def load_configs():
    logging.debug("CONFIG: Loading the name and localization files.")
    
    if not os.path.exists(DEFAULTS_DIR):
        os.makedirs(DEFAULTS_DIR)

    if os.path.exists(NAMES_PATH):
        try:
            with open(NAMES_PATH, "r") as f:
                state.NAMES_CONFIG = json.load(f)
            logging.debug(f"CONFIG: Loaded {len(state.NAMES_CONFIG.get('pools', {}))} name pools from names.json.")
        except Exception as e:
            logging.error(f"CONFIG: Cannot load names.json: {e}")

    state.LOCALIZATION_CONFIG = {}
    if os.path.exists(LOCALIZATION_PATH):
        try:
            with open(LOCALIZATION_PATH, "r", encoding="utf-8") as f:
                state.LOCALIZATION_CONFIG = json.load(f)
            logging.debug(f"CONFIG: Loaded {len(state.LOCALIZATION_CONFIG)} language localizations.")
        except Exception as e:
            logging.error(f"CONFIG: Cannot load localization.json: {e}")
