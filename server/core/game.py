import json
import logging

from core import deeds, state
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

def take_report(player, events, towns):
    """Keeps the player's context and the changed towns, and takes the deeds of the game events that a request from the
    plugin carries. The plugin sends the context only with a request, so the player's context is the one of the latest
    request. A load of an older save can undo a change of a town, so only the latest list counts."""
    if player:
        state.PLAYER_CONTEXT = player
        note_faction(player, is_player=True)
    towns = towns or []
    if towns != state.CHANGED_TOWNS:
        listed = "; ".join(f"{town.get('name')}: owner {town.get('owner') or 'none'} ({town.get('owner_id')}), type {town.get('type')}" for town in towns)
        logging.debug(f"TOWNS: {listed or 'No changed town.'}")
    state.CHANGED_TOWNS = towns
    deeds.take(events)

def report_from_game(timeout=5):
    """Asks the game for a report and waits for it. False when no report comes, for example from the main menu."""
    state.GAME_REPORTED.clear()
    send_to_pipe("REPORT:")
    return state.GAME_REPORTED.wait(timeout)
