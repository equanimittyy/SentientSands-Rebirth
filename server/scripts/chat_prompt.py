"""The messages of a 1:1 chat, ordered so that a provider's prompt cache can reuse their start.

A prefix cache reuses only an identical start of a request. The system message is therefore the same on every turn
with one NPC, the stored history follows as chat turns that only grow inside a window, and everything that changes
each turn comes last, in the final user message.
"""

import re

import scene_text

_TIME_PREFIX = re.compile(r"^\[Day [^\]]*\]\s*")
# Some chat templates require the turns after the system message to start with a user message
EARLIER = "(Earlier conversation)"


def history_window(lines, block):
    """Keeps its first line while it grows from one block to two lines long, then moves on by one block."""
    return lines[max(0, block * (len(lines) // block) - block):]


def overhearers(nearby, radius, excluded_ids):
    """The NPCs of nearby within radius, one for each npc_id, because NPCs near the player can share a name. A radius of
    None means that nobody overhears."""
    if radius is None:
        return []
    found = {}
    for npc in nearby:
        npc_id = npc.get("npc_id")
        if npc_id and npc_id not in excluded_ids and npc.get("dist", 999.0) <= radius:
            found.setdefault(npc_id, npc)
    return list(found.values())


def _overheard(line):
    return _TIME_PREFIX.sub("", line).startswith("(Overheard)")


def has_spoken_with(entries, speaker_id):
    """entries are the (line, speaker, ...) rows of the NPC. The speaker, not the name, marks the lines of the squad
    member, and a line that the NPC only overheard does not count."""
    return any(speaker == speaker_id and not _overheard(line) for line, speaker, *_ in entries)


def companions(entries, npc_id, speaker_id):
    """The other speakers of the lines that the NPC did not only overhear, in the order of their first line."""
    found = []
    for line, speaker, *_ in entries:
        if speaker and speaker not in (npc_id, speaker_id, *found) and not _overheard(line):
            found.append(speaker)
    return found


def overheard_notes(members, npc_id):
    """The note of each thread in which the NPC is a speaker, by thread ID, from thread_members. Only the overhearers that
    were in the player's faction count, because only they can later speak to the NPC as the player."""
    notes = {}
    for thread_id, group in members.items():
        if not any(member_id == npc_id and role == "speaker" for member_id, _, role, _ in group):
            continue
        listeners = [name for _, name, role, in_faction in group if role == "overheard" and in_faction and name]
        partner = next((name for member_id, name, role, _ in group if role == "speaker" and member_id != npc_id and name), None)
        if listeners:
            notes[thread_id] = scene_text.overheard_note(listeners, partner)
    return notes


def with_notes(entries, notes):
    """entries are (line, speaker, thread_id) triples. Each note follows the last line of its thread, as a line with no
    speaker, so the history turns make it a user turn."""
    last = {thread_id: i for i, (_, _, thread_id) in enumerate(entries)}
    lines = []
    for i, (line, speaker, thread_id) in enumerate(entries):
        lines.append((line, speaker))
        if thread_id in notes and last[thread_id] == i:
            lines.append((notes[thread_id], None))
    return lines


def mark_names(text, members):
    """Replaces each name of members, (npc_id, name) pairs, in text with the mark of its npc_id, so named() gives the current
    name after a rename. It matches whole words only, the longest name first, so "Dust Bandit" stays inside "Dust Bandit
    Josh". A name that two members share stays as text, because its mark could name the wrong member."""
    owners = {}
    for npc_id, name in members:
        if name:
            owners.setdefault(name, set()).add(npc_id)
    marks = {name: _mark(*ids) for name, ids in owners.items() if len(ids) == 1}
    if not marks:
        return text
    pattern = re.compile(r"(?<!\w)(" + "|".join(re.escape(name) for name in sorted(marks, key=len, reverse=True)) + r")(?!\w)")
    return pattern.sub(lambda match: marks[match.group(1)], text)


def named(text, names):
    """The text of mark_names with the name of each npc_id in names."""
    for npc_id, name in names.items():
        text = text.replace(_mark(npc_id), name)
    return text


def _mark(npc_id):
    return "{" + npc_id + "}"


def history_turns(entries, npc_id):
    """entries are (line, speaker) pairs. The speaker, not the name, marks the lines of the NPC, because NPCs near the player
    can share a name."""
    turns = []
    for line, speaker in entries:
        if npc_id and speaker == npc_id:
            role, content = "assistant", _TIME_PREFIX.sub("", line).split(":", 1)[-1].strip()
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
