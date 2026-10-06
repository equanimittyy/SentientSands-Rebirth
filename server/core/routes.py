import json
import logging

from flask import Blueprint, jsonify, request

from chat.bio import recorded_history
from chat.characters import get_character_data, reported_sex, sync_name
from core import deeds, log_setup, state
from core.game import context_dict, generate_relation_bar, take_report
from core.pipe import send_to_pipe
from core.settings import CHAT_HOTKEYS, SETTINGS_DEFAULTS, load_configs, load_settings, save_settings, settings_page_values
from store import campaign_db
from store.campaigns import switch_campaign

bp = Blueprint("core", __name__)

@bp.route('/squad_rename', methods=['POST'])
def squad_rename():
    """The plugin posts the context of a squad member that the player renamed in game, and the profile takes the name."""
    ctx = request.get_json(silent=True) or {}
    if not ctx.get("npc_id"):
        return jsonify({"status": "error", "message": "Missing the NPC ID"}), 400
    try:
        profile = campaign_db.get_character(ctx["npc_id"])
    except campaign_db.CampaignUnavailable as e:
        return jsonify({"status": "error", "message": str(e)}), 409
    if profile:
        sync_name(ctx, profile, True)
    return jsonify({"status": "ok"})

@bp.route('/rename', methods=['POST'])
def rename_character():
    data = request.json
    if not data: return jsonify({"status": "error"}), 400

    new_name = data.get('new_name')
    npc_id = context_dict(data.get('context', '')).get('npc_id')
    if not npc_id or not new_name:
        return jsonify({"status": "error", "message": "Missing the NPC ID or the new name"}), 400

    # The stored profile keeps the name when the game loses it, for example after the load of an earlier save
    if not campaign_db.character_exists(npc_id):
        get_character_data(new_name, data.get('context', ''))
    # The dialogue names the NPC by its stored Name, which lacks the title of its game name
    old_name = (campaign_db.get_character(npc_id) or {}).get("Name", data.get('old_name', ''))
    campaign_db.rename_character(npc_id, old_name, new_name)
    logging.info(f"RENAME: {old_name} is now {new_name} ({npc_id})")
    return jsonify({"status": "ok"})

@bp.route('/events', methods=['GET', 'POST'])
def list_events():
    """The deeds for the Deeds window, newest first. The plugin finds the keys of each deed after its "id", so each key must
    sort after "id", as Flask sorts them. The window sends the campaign back with Add Deed and Delete, because the same ID
    can name another deed in another campaign."""
    events = []
    rumors = {rumor["id"]: rumor for rumor in campaign_db.rumors()}
    for event in deeds.notable_events():
        rumor = rumors.get(event["rumor"])
        custom = event["kind"] == "custom"
        # The line of a custom deed is only its kind, so its rumor tells it apart in the list
        words = (f"Custom: {rumor['text']}" if custom and rumor else event["line"]).split()
        mark = " (rumor)" if rumor and not custom else ""
        # "N." numbering rather than "#N": MyGUI parses "#" as a color tag
        title = f"{len(events) + 1}. " + " ".join(words[:7]) + ("..." if len(words) > 7 else "")
        events.append({"id": str(event["id"]), "title": title[:80] + mark, "inner": event["line"] + (" " + rumor["text"] if rumor else ""),
                       "instruction": rumor["instruction"] if rumor else "", "kind": event["kind"], "rumor": str(rumor["id"]) if rumor else ""})
    return jsonify({"status": "ok", "campaign": state.ACTIVE_CAMPAIGN, "events": events})

@bp.route('/events/content', methods=['POST'])
def events_content():
    """The plugin's SetEventsText renders each newline-separated line as a row."""
    import textwrap
    data = request.json or {}
    event = next((event for event in deeds.notable_events() if str(event["id"]) == str(data.get("id"))), None)
    if not event:
        return jsonify({"status": "error", "text": "The deed is gone."}), 404
    rumor = next((rumor for rumor in campaign_db.rumors() if rumor["id"] == event["rumor"]), None)
    line = "Custom deed - add any rumours you would like characters to possibly comment on" if event["kind"] == "custom" else event["line"]
    lines = (["=" * 38, "  DEED", "=" * 38, ""] + textwrap.wrap(line, width=76) + ["", f"Kind: {event['kind'].capitalize()}", f"Time: {event['time']}", "", "RUMOR:"]
             + (textwrap.wrap(rumor["text"], width=76) if rumor else ["None yet. Press Generate Rumor to write one."]))
    return jsonify({"status": "ok", "text": "\n".join(lines)})

@bp.route('/report', methods=['POST'])
def game_report():
    data = request.get_json(silent=True) or {}
    take_report(data.get("player"), data.get("events"))
    state.GAME_REPORTED.set()
    return jsonify({"status": "ok"})

@bp.route('/context', methods=['GET'])
def get_context():
    last_npc = None
    if state.LIVE_CONTEXTS:
        last_npc_id = list(state.LIVE_CONTEXTS.keys())[-1]
        last_npc = state.LIVE_CONTEXTS[last_npc_id]
    
    return jsonify({
        "status": "ok",
        "player": state.PLAYER_CONTEXT,
        "npc": last_npc or {},
        "campaign": state.ACTIVE_CAMPAIGN,
        "debug": logging.getLogger().isEnabledFor(logging.DEBUG),
        # Both counts only grow, so the sum changes when either does
        "writes": campaign_db.writes + state.WRITE_REQUESTS,
    })

@bp.route('/settings/defaults')
def settings_defaults():
    return jsonify(settings_page_values(SETTINGS_DEFAULTS))

@bp.route('/settings', methods=['GET', 'POST'])
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
            "supported_languages": list(state.LOCALIZATION_CONFIG.keys()),
            "chat_hotkeys": CHAT_HOTKEYS,
            "log_levels": list(log_setup.LEVELS),
            "ui_translation": state.LOCALIZATION_CONFIG.get(settings["language"], {})
        })

    logging.debug(f"SETTINGS: Update request: {json.dumps(data)}")
    changes = {}

    enable_radiant = data.get("enable_radiant")
    if enable_radiant is not None:
        changes["enable_radiant"] = enable_radiant
        send_to_pipe(f"SET_CONFIG: g_enableRadiant: {'1' if enable_radiant else '0'}")
        logging.info(f"SETTINGS: Radiant conversations enabled set to {enable_radiant}")

    radiant_delay = data.get("radiant_delay")
    if radiant_delay is not None:
        val = int(radiant_delay)
        changes["radiant_delay"] = val
        send_to_pipe(f"SET_CONFIG: g_radiantIntervalSeconds: {val}")
        logging.info(f"SETTINGS: Radiant delay set to {val}")

    radii = data.get("radii")
    if radii:
        t = radii.get("talk")
        y = radii.get("yell")
        if t is not None:
            send_to_pipe(f"SET_CONFIG: g_proximityRadius: {t}")
        if y is not None:
            send_to_pipe(f"SET_CONFIG: g_yellRadius: {y}")
        changes["radii"] = radii

    lang = data.get("language")
    if lang is not None:
        changes["language"] = lang
        send_to_pipe("APPLY_TRANSLATION: " + json.dumps({"ui_translation": state.LOCALIZATION_CONFIG.get(lang, {})}))
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

    bio_interactions = data.get("bio_interactions")
    if bio_interactions is not None:
        try:
            val = max(0, int(bio_interactions))
            changes["bio_interactions"] = val
            logging.info(f"SETTINGS: Bio threshold set to {val} chats")
        except: pass

    conversation_timeout = data.get("conversation_timeout_minutes")
    if conversation_timeout is not None:
        try:
            val = max(1, int(conversation_timeout))
            changes["conversation_timeout_minutes"] = val
            logging.info(f"SETTINGS: Conversation timeout set to {val} minutes")
        except: pass

    for key in ("retrieval_slots", "memory_slots", "retrieval_cooldown_turns"):
        value = data.get(key)
        if value is not None:
            try:
                changes[key] = max(0, int(value))
                logging.info(f"SETTINGS: {key} set to {changes[key]}")
            except: pass

    diag_speed = data.get("dialogue_speed")
    if diag_speed is not None:
        try:
            val = int(diag_speed)
            changes["dialogue_speed_seconds"] = val
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
            changes["current_campaign"] = state.ACTIVE_CAMPAIGN
            logging.info(f"CAMPAIGN: Switched to {state.ACTIVE_CAMPAIGN}")

    if changes:
        save_settings(changes)
        logging.info(f"SETTINGS: Saved {len(changes)} changes.")
        return jsonify({"status": "ok", **changes})

    return jsonify({"status": "error", "message": "No valid settings provided"}), 400

# The game always means the active campaign, so this route has no campaign check
@bp.route('/cull', methods=['POST'])
def cull_from_game():
    data = request.get_json(silent=True) or {}
    take_report(data.get("player"), data.get("events"))
    return cull_future_data()

def cull_future_data():
    # Without a game, day 0 would count as now, and the cull would delete the whole history
    if "day" not in state.PLAYER_CONTEXT:
        return jsonify({"status": "error", "message": "Cull needs the game running, because it deletes what is dated after the current game time."}), 409
    day, hour, minute = int(state.PLAYER_CONTEXT["day"]), int(state.PLAYER_CONTEXT.get("hour", 0)), int(state.PLAYER_CONTEXT.get("minute", 0))
    culled = campaign_db.cull_after(day, hour, minute)
    # The player loaded an earlier save, so the next chat starts a conversation of its own
    state.CURRENT_THREAD.clear()
    state.restart_quiet_clock()
    logging.info(f"CAMPAIGN: Culled {culled['dialogue']} dialogue lines, {culled['notable']} notable events, and {culled['rumor']} rumors after [Day {day}, {hour:02d}:{minute:02d}] in '{state.ACTIVE_CAMPAIGN}'")
    return jsonify({"status": "ok", "time": f"Day {day}, {hour:02d}:{minute:02d}", "culled": culled})

@bp.route('/history', methods=['POST'])
def get_history():
    logging.debug("HTTP: POST /history")
    data = request.json or {}
    
    npc_id = data.get('npc', '')
    logging.debug(f"HISTORY: Request for {npc_id}")
    char_data = campaign_db.get_character(npc_id) or {}

    if "Race" not in char_data: char_data["Race"] = "Unknown"
    if "Faction" not in char_data: char_data["Faction"] = "Unknown"
    
    history = recorded_history(npc_id)
    
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
    race = char_data['Race']
    lines.append(f"--- PROFILE: {char_data.get('Name', npc_id)} ---")
    lines.append(f"Race: {race} | Sex: {reported_sex(race, char_data.get('Sex', 'Unknown'))} | Current Job: {char_data.get('CurrentJob') or 'Unknown'}")
    lines.append(f"Faction: {char_data['Faction']} | Origin Faction: {char_data.get('OriginFaction', 'Unknown')}")
    lines.append(generate_relation_bar(char_data.get('Relation', 0)))
    if campaign_db.PROVISIONAL in char_data:
        chats, threshold = int(char_data[campaign_db.PROVISIONAL]), load_settings()["bio_interactions"]
        lines.append(f"BIO: Provisional. The LLM writes the full bio at {threshold} chats ({chats} so far), or press Generate Bio." if threshold
                     else f"BIO: Provisional. Press Generate Bio to have the LLM write the full bio ({chats} chats so far).")
    lines.append("-" * 30)
    for part, title in (("Personality", "PERSONALITY"), ("Backstory", "BACKSTORY"), ("SpeechQuirks", "SPEECH")):
        lines.append(f"{title}:")
        lines.append(_wrap(char_data.get(part)) or "None")
        lines.append("")
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

@bp.route('/characters', methods=['GET', 'POST'])
def list_characters():
    data = request.json or {}
    sort_mode = data.get("sort", "alphabetical") # alphabetical or latest
    
    logging.debug(f"LIBRARY: Listing the characters of '{state.ACTIVE_CAMPAIGN}' (sort: {sort_mode})")
    # Leaves out the seeded characters that nobody has met, so the template does not fill the library, and the characters
    # that only overheard chats, because every NPC near a chat overhears it
    final_list = [
        {"display": c["name"] or c["npc_id"], "sid": c["npc_id"], "updated_at": c["updated_at"], "is_fav": c["favorite"]}
        for c in campaign_db.list_characters() if not c["only_overheard"] and (c["has_dialogue"] or c["origin"] != "seed")
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

@bp.route('/favorite', methods=['POST'])
def toggle_favorite():
    data = request.json or {}
    sid = data.get("sid")
    if not sid:
        return jsonify({"status": "error"}), 400

    is_fav = campaign_db.toggle_favorite(sid)
    if is_fav is None:
        return jsonify({"status": "error", "message": "Profile not found"}), 404

    return jsonify({"status": "ok", "state": "added" if is_fav else "removed"})

def campaign_write(data):
    """An error reply when the player switched the campaign in game after the page loaded it, else None."""
    if data.get("campaign") != state.ACTIVE_CAMPAIGN:
        return jsonify({"status": "error", "message": f"The active campaign is now {state.ACTIVE_CAMPAIGN}. Discard to load it."}), 409
    return None
