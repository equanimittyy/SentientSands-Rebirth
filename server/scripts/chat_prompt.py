"""The messages of a 1:1 chat, ordered so that a provider's prompt cache can reuse their start.

A prefix cache reuses only an identical start of a request. The system message is therefore the same on every turn
with one NPC, the stored history follows as chat turns that only grow inside a window, and everything that changes
each turn comes last, in the final user message.
"""

import re

_TIME_PREFIX = re.compile(r"^\[Day [^\]]*\]\s*")
# Some chat templates require the turns after the system message to start with a user message
EARLIER = "(Earlier conversation)"


def history_window(lines, block):
    """Keeps its first line while it grows from one block to two lines long, then moves on by one block."""
    return lines[max(0, block * (len(lines) // block) - block):]


def history_turns(lines, npc_name):
    name = npc_name.lower()
    turns = []
    for line in lines:
        text = _TIME_PREFIX.sub("", line)
        if text.lower().startswith((f"{name}:", f"{name}|")):
            role, content = "assistant", text[len(name):].split(":", 1)[1].strip()
        else:
            role, content = "user", line.strip()
        content = content or "..."
        if turns and turns[-1]["role"] == role:
            turns[-1]["content"] += "\n" + content
        else:
            turns.append({"role": role, "content": content})
    if turns and turns[0]["role"] == "assistant":
        turns.insert(0, {"role": "user", "content": EARLIER})
    return turns


def chat_messages(system, turns, tail):
    """A trailing user turn takes the tail, because some chat templates refuse two user messages in a row."""
    messages = [{"role": "system", "content": system}, *turns]
    if turns and turns[-1]["role"] == "user":
        return messages[:-1] + [{"role": "user", "content": f"{turns[-1]['content']}\n\n{tail}"}]
    return messages + [{"role": "user", "content": tail}]
