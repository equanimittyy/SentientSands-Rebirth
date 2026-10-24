"""The open chat thread that the chat window of the plugin shows above its input."""

import time

from core import state
from store import campaign_db


def thread_speakers(thread_id):
    """The npc_id of each speaker of the thread, without its overhearers."""
    return {npc_id for npc_id, _, role, _ in campaign_db.thread_members([thread_id]).get(thread_id, []) if role == "speaker"}


def stays_in(live, thread_key):
    """Whether a line of thread_key stays in the live thread: in the same mode, to its target or to another of its speakers,
    so two squad members that answer each other keep one thread. A thread of lines to Anyone has no target."""
    target, owner = thread_key[0], live["key"][0]
    return live["key"][1:] == thread_key[1:] and (target == owner or bool(target and owner and target in thread_speakers(live["id"])))


def open_thread(npc_id, quiet, anyone=False):
    """The chat thread with the NPC while it is open, or None. quiet is the Conversation timeout in seconds. The thread
    matches each of its speakers, as stays_in does, but not an overhearer. It does not match by the mode or the speaker,
    because a switch of either ends it only at the next line, and each line closes the chat window. With anyone, npc_id is
    the speaker, and only a thread of lines to Anyone matches."""
    with state.THREAD_LOCK:
        live = dict(state.CURRENT_THREAD)
    if not npc_id or not live or time.monotonic() - live["replied"] >= quiet:
        return None
    thread_id = live["id"]
    if npc_id not in thread_speakers(thread_id) or (anyone and live["key"][0] is not None):
        return None
    members = campaign_db.thread_members([thread_id]).get(thread_id, [])
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
        thread.update(speaker=action["speaker"], stock=action["stock"])
    return thread


def thread_lines(npc_id, thread_id):
    """The copy of the lines of the chat thread that the NPC holds."""
    return "\n".join(line for line, _, line_thread in campaign_db.dialogue(npc_id) if line_thread == thread_id)
