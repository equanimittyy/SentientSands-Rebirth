import json

from core import state

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
