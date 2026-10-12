"""The open chat thread that the chat window of the plugin shows above its input."""

import time

from chat import offers
from core import state
from store import campaign_db


def open_thread(npc_id, quiet):
    """The chat thread with the NPC while it is open, or None. quiet is the Conversation timeout in seconds. The thread
    matches by the NPC only, because a switch of the mode or the speaker ends it only at the next line, and each line
    closes the chat window. The yell thread belongs to no one NPC, so it matches each of its members."""
    with state.THREAD_LOCK:
        live = dict(state.CURRENT_THREAD)
    if not npc_id or not live or time.monotonic() - live["replied"] >= quiet:
        return None
    thread_id = live["id"]
    members = campaign_db.thread_members([thread_id]).get(thread_id, [])
    owner = live["key"][0]
    if owner != npc_id and (owner is not None or all(member_id != npc_id for member_id, *_ in members)):
        return None
    names = [name or "Unknown" for _, name, role, _ in members if role == "speaker"]
    speakers = f"{', '.join(names[:2])}, and {len(names) - 2} more" if len(names) > 2 else " and ".join(names)
    action = live.get("action")
    thread = {
        "title": f"{speakers} | {campaign_db.thread_location(thread_id) or 'Unknown'}",
        "type": action["category"].capitalize() if action else "Chat",
        "mode": live["key"][1],
        "lines": thread_lines(npc_id, thread_id),
    }
    if action:
        sell, buy = offers.SHARES[action["trader"]]
        thread.update(speaker=action["speaker"], trader=action["trader"], sell_share=sell, buy_share=buy)
    return thread


def thread_lines(npc_id, thread_id):
    """The copy of the lines of the chat thread that the NPC holds."""
    return "\n".join(line for line, _, line_thread in campaign_db.dialogue(npc_id) if line_thread == thread_id)
