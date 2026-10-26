import json
import logging

from core import state, world_events
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

def sync_outposts(towns):
    """Keeps a location record for each town of the player's faction that the game lists, so the radiant place topic has a
    record of it, and deletes the record of each outpost that the game no longer lists. A plugin without the list sends
    None, which keeps every record."""
    if towns is None:
        return
    try:
        owner = (campaign_db.player_faction() or {}).get("name")
        if (owner, towns) == state.SEEN_OUTPOSTS:
            return
        listed = "; ".join(f"{town['name']} ({town['key']}) in {town['zone'] or 'an unknown zone'}" for town in towns)
        logging.debug(f"OUTPOSTS: {listed or 'The player holds no town.'}")
        for town in towns:
            change = campaign_db.note_outpost(town["key"], town["name"], town["zone"], owner)
            if change:
                logging.info(f"CAMPAIGN: {change.capitalize()} the record of the outpost {town['name']} ({town['key']}).")
        for name in campaign_db.forget_outposts({town["key"] for town in towns}):
            logging.info(f"CAMPAIGN: Deleted the record of the outpost {name}, because the game no longer has it.")
        state.SEEN_OUTPOSTS = (owner, towns)
    except campaign_db.CampaignUnavailable:
        pass
    except Exception as e:
        logging.warning(f"CAMPAIGN: Cannot keep the records of the outposts in step with the game: {e}")

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

def relation_text(rel):
    try:
        rel = int(rel)
    except:
        rel = 0

    label = "NEUTRAL"
    if rel <= -90: label = "ARCH-ENEMY"
    elif rel <= -60: label = "HOSTILE"
    elif rel <= -25: label = "UNFRIENDLY"
    elif rel >= 90: label = "SOUL-MATE"
    elif rel >= 60: label = "ALLIED"
    elif rel >= 25: label = "FRIENDLY"
    return f"{label} ({rel:+} pts)"

def take_report(player, events, towns, uniques, player_towns=None):
    """Keeps the player's context, the changed towns, and the unique NPCs that are not alive, takes the events that the
    game events of a request from the plugin carries, shows the game messages of the jobs that they change, and keeps the
    records of the player's outposts in step. The plugin sends the context only with a request, so the player's context is
    the one of the latest request. A load of an older save can undo a change of a town or a death, so only the latest lists
    count."""
    if player:
        state.PLAYER_CONTEXT = player
        note_faction(player, is_player=True)
    sync_outposts(player_towns)
    towns = towns or []
    if towns != state.CHANGED_TOWNS:
        listed = "; ".join(f"{town.get('name')}: owner {town.get('owner') or 'none'} ({town.get('owner_id')}), type {town.get('type')}" for town in towns)
        logging.debug(f"TOWNS: {listed or 'No changed town.'}")
    state.CHANGED_TOWNS = towns
    if uniques != state.UNIQUE_STATES:
        listed = "The game sent none." if uniques is None else "; ".join(f"{unique['name']} ({unique['id']}): {unique['state']}" for unique in uniques)
        logging.debug(f"UNIQUES: {listed or 'No unique NPC is dead or imprisoned.'}")
    state.UNIQUE_STATES = uniques
    for note in world_events.take(events, player):
        send_to_pipe(f"NOTIFY: {note}")

def report_from_game(timeout=5):
    """Asks the game for a report and waits for it. False when no report comes, for example from the main menu."""
    state.GAME_REPORTED.clear()
    send_to_pipe("REPORT:")
    return state.GAME_REPORTED.wait(timeout)
