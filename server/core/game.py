import json
import logging
import threading
import time

from core import state
from core.pipe import send_to_pipe
from store import campaign_db

def context_dict(context):
    if isinstance(context, dict):
        return context
    if isinstance(context, str) and context.strip().startswith('{'):
        try:
            return json.loads(context)
        except ValueError:
            pass
    return {}

def get_current_time_prefix(ctx=None):
    ctx = state.PLAYER_CONTEXT if ctx is None else ctx
    if "day" in ctx:
        day = ctx['day']
        hour = int(ctx.get('hour', 0))
        minute = int(ctx.get('minute', 0))
        return f"[Day {day}, {hour:02d}:{minute:02d}] "
    return ""

def is_player_faction(faction, faction_id):
    player_faction_id = state.PLAYER_CONTEXT.get("factionID")
    return faction == state.PLAYER_CONTEXT.get("faction", "Nameless") or bool(player_faction_id and faction_id == player_faction_id)

EVENT_THROTTLE = {} 
THROTTLE_LOCK = threading.Lock()
LAST_STATE_LOG = {} # {"<target>|<etype>": last message}
STATE_LOCK = threading.Lock()

def note_faction(ctx, is_player=False):
    """Records each faction that the game reports, so the player can describe a modded or minor faction on the Campaigns page."""
    faction_id, name = ctx.get("factionID"), ctx.get("faction")
    # The plugin sends the name as the ID, or "Neutral", when the faction has no string ID
    if not faction_id or not name or faction_id in (name, "Neutral"):
        return
    key = (faction_id, name, is_player)
    if key in state.SEEN_FACTIONS:
        return
    try:
        campaign_db.note_faction(faction_id, name, is_player)
        state.SEEN_FACTIONS.add(key)
    except campaign_db.CampaignUnavailable:
        pass  # load_campaign_config already logged why
    except Exception as e:
        logging.warning(f"CAMPAIGN: Cannot record the faction {name}: {e}")

def adopt_canon(node):
    """Gives each NPC whose template is a canon character the npc_id of that character, and marks it unique, so it uses the
    canon profile and never gets a rolled name. Whether a template is unique depends on the mod list: UWE makes the Yabuta
    Chief generic, and without UWE Yamdu is generic. Contexts can arrive as JSON strings inside the request. Returns whether
    anything changed."""
    changed = False
    if isinstance(node, dict):
        canon_id = f"u:{node.get('template_id')}"
        if node.get("template_id") and not node.get("unique") and campaign_db.character_exists(canon_id):
            node["npc_id"], node["unique"], changed = canon_id, True, True
        children = list(node.items())
    elif isinstance(node, list):
        children = list(enumerate(node))
    else:
        return False
    for key, child in children:
        if isinstance(child, str) and child.startswith("{"):
            parsed = context_dict(child)
            if adopt_canon(parsed):
                node[key], changed = json.dumps(parsed), True
        elif adopt_canon(child):
            changed = True
    return changed

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

def npc_serial(npc_id):
    """The handle serial in the npc_id of a generic NPC, or None for a unique NPC."""
    return npc_id[2:] if npc_id and npc_id.startswith("h:") else None

def record_event_to_history(etype, actor, target, msg, actor_faction="None", target_faction="None", when=None):
    """`when` holds the game time and the player's town of an event from the game, which can arrive minutes after it.
    An event of the server takes them from the player's context."""
    global EVENT_THROTTLE, LAST_STATE_LOG
    if not msg: return
    
    p_fact = state.PLAYER_CONTEXT.get('faction', 'Nameless')
    a_fact_display = actor_faction
    if actor_faction == "Nameless" or actor_faction == p_fact:
        a_fact_display = f"Player's Squad: {p_fact}"
        
    t_fact_display = target_faction
    if target_faction == "Nameless" or target_faction == p_fact:
        t_fact_display = f"Player's Squad: {p_fact}"

    actor_part = f"{actor} ({a_fact_display})" if a_fact_display and a_fact_display != "None" else actor
    target_part = f"{target} ({t_fact_display})" if t_fact_display and t_fact_display != "None" else target
    
    if when is None:
        env = state.PLAYER_CONTEXT.get("environment", {})
        when = {**state.PLAYER_CONTEXT, "town": env.get("town_name", "") if isinstance(env, dict) else ""}
    location = f" @ {when['town']}" if when.get("town") else ""
    
    time_str = get_current_time_prefix(when).strip()
    # The game clock reads Day 0, 00:00 until it holds a real time, so the event has no true time
    if time_str == "[Day 0, 00:00]":
        return
    prefix = f"{time_str} " if time_str else ""
    # The Editor's event table parses this format with EVENT_LINE in server/dashboard/web/editor.js
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

def take_report(player, events):
    """Keeps the player's context and records the game events that a request from the plugin carries. The plugin sends
    neither on a timer, so the player's context is the one of the latest request."""
    if player:
        state.PLAYER_CONTEXT = player
        note_faction(player, is_player=True)
    for e in events or []:
        record_event_to_history(e.get("type", "EVENT"), e.get("actor", "Unknown"), e.get("target", "None"), e.get("msg", ""),
                                actor_faction=e.get("actor_faction", "None"), target_faction=e.get("target_faction", "None"), when=e)

def report_from_game(timeout=5):
    """Asks the game for a report and waits for it. False when no report comes, for example from the main menu."""
    state.GAME_REPORTED.clear()
    send_to_pipe("REPORT:")
    return state.GAME_REPORTED.wait(timeout)
