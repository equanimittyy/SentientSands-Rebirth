"""The open chat thread that the chat window of the plugin shows above its input."""

import time

from core import state
from store import campaign_db


def open_thread(npc_id, quiet):
    """The chat thread with the NPC while it is open, or None. quiet is the Conversation timeout in seconds. The thread
    matches by the NPC only, because a switch of the mode or the speaker ends it only at the next line, and each line
    closes the chat window."""
    with state.THREAD_LOCK:
        live = dict(state.CURRENT_THREAD)
    if not npc_id or live.get("key", (None,))[0] != npc_id or time.monotonic() - live["replied"] >= quiet:
        return None
    thread_id = live["id"]
    names = [name or "Unknown" for _, name, role, _ in campaign_db.thread_members([thread_id]).get(thread_id, []) if role == "speaker"]
    speakers = f"{', '.join(names[:2])}, and {len(names) - 2} more" if len(names) > 2 else " and ".join(names)
    action = live.get("action")
    return {
        "title": f"{speakers} | {campaign_db.thread_location(thread_id) or 'Unknown'}",
        "type": action["category"].capitalize() if action else "Chat",
        "lines": "\n".join(line for line, _, line_thread in campaign_db.dialogue(npc_id) if line_thread == thread_id),
    }
