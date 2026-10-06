"""The messages of a 1:1 chat, ordered so that a provider's prompt cache can reuse their start.

A prefix cache reuses only an identical start of a request. The system message is therefore the same on every turn
with one NPC, the stored history follows as chat turns that only grow inside a window, and everything that changes
each turn comes last, in the final user message.
"""

import re

from chat import retrieval, scene_text
from chat.characters import animal_flag
from chat.prompts import describe_record
from store.campaign_db import game_time_text

_TIME_PREFIX = re.compile(r"^\[Day [^\]]*\]\s*")
# Some chat templates require the turns after the system message to start with a user message
EARLIER = "(Earlier conversation)"
MEMORY_LIMIT = 5


def chat_lines(entries):
    """The (line, speaker, thread_id) rows of threads. A row with no thread never gets a memory, so it would stay in every
    chat of the NPC."""
    return [entry for entry in entries if entry[2] is not None]


def history_window(lines, block):
    """Keeps its first line while it grows from one block to two lines long, then moves on by one block."""
    return lines[max(0, block * (len(lines) // block) - block):]


def overhearers(nearby, radius, excluded_ids):
    """The NPCs of nearby within radius, one for each npc_id, because NPCs near the player can share a name. A radius of
    None means that nobody overhears. An animal never overhears, because it cannot understand speech."""
    if radius is None:
        return []
    found = {}
    for npc in nearby:
        npc_id = npc.get("npc_id")
        if npc_id and npc_id not in excluded_ids and npc.get("dist", 999.0) <= radius and not animal_flag(npc):
            found.setdefault(npc_id, npc)
    return list(found.values())


def _overheard(line):
    return _TIME_PREFIX.sub("", line).startswith("(Overheard)")


def spoken_with(entries, partners, npc_id):
    """The characters that the NPC spoke with, in order: partners, the other speakers of its chat threads
    (campaign_db.thread_partners), which stay after a memory replaced the lines, then the speakers of its stored lines that
    it did not only overhear. The speaker, not the name, marks a line."""
    found = []
    for speaker in [*partners, *(speaker for line, speaker, *_ in entries if not _overheard(line))]:
        if speaker and speaker != npc_id and speaker not in found:
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


def starting_memories(memories, npc_id):
    """The newest MEMORY_LIMIT memories of memories_of in which the NPC was a speaker. An NPC near many chats, such as a
    barman, overhears more conversations than it has, so its overheard memories would push its own out. The search of
    the player's message finds the others."""
    return [memory for memory in memories if any(member_id == npc_id and role == "speaker" for member_id, _, role, _ in memory["members"])][-MEMORY_LIMIT:]


def memories_block(memories, npc_id):
    """The memories of the NPC, campaign_db.memories_of, each under a header that names the members from the view of the
    NPC, so one stored text serves every member. Empty without a memory, so the heading stays out."""
    if not memories:
        return ""
    parts = ["Memories of your earlier conversations, oldest first. You know what happened in them. When the talk turns to one, reply truthfully or with a lie. You are not required to uphold the past:"]
    for memory in memories:
        partners, listeners, overheard = _members_seen_by(memory["members"], npc_id)
        parts.append(_dated(memory, scene_text.memory_header(partners, listeners, overheard)))
        parts.append(memory_text(memory))
    return "\n".join(parts)


def background_block(memories, entries, npc_id, speaker):
    """The memories of memories_of and the lore records of retrieval.lore_records that the player's message found, for the
    last user message. The block is a part of the user message, so its mark keeps a model from taking it for words of
    the player. Empty without either, so the block stays out."""
    if not memories and not entries:
        return ""
    parts = []
    if memories:
        parts.append(f"Memories that {speaker}'s words may touch on:")
        for memory in memories:
            parts.append(_dated(memory, scene_text.memory_header(*_members_seen_by(memory["members"], npc_id))))
            parts.append(retrieval.clipped(memory_text(memory)))
    if entries:
        parts.append(f"Lore that {speaker}'s words may touch on:")
        parts += [f"- {describe_record({**entry, 'description': retrieval.clipped(entry['description'])}, entry['kind'])}" for entry in entries]
    # A search finds words, not meaning, and a model tends to use all the text that it gets
    if memories and entries:
        parts.append(f"These memories and this lore may have nothing to do with what {speaker} means, and you may know less than the lore says. Use them only where they fit your reply, and never recite them or turn the talk towards them.")
    elif memories:
        parts.append(f"These memories may have nothing to do with what {speaker} means. Use them only where they fit your reply, and never recite them or turn the talk towards them.")
    else:
        parts.append(f"This lore may have nothing to do with what {speaker} means, and you may know less than it says. Use it only where it fits your reply, and never recite it or turn the talk towards it.")
    return "(Background, not said aloud. " + "\n".join(parts) + ")"


def memory_lines(memories, npc_id):
    """Each memory as one line in the form of a stored line, for the Dialogue Library and the bio prompt."""
    return [_dated(memory, f"({scene_text.memory_label(*_members_seen_by(memory['members'], npc_id))}) {memory_text(memory)}") for memory in memories]


def shared_memory(memory):
    """A memory of memories_of, under a header that names its members, for the prompt of a radiant conversation."""
    speakers = [name or "someone" for _, name, role, _ in memory["members"] if role == "speaker"]
    listeners = [name for _, name, role, _ in memory["members"] if role == "overheard" and name]
    return _dated(memory, f"({scene_text.shared_memory_label(speakers, listeners)}) {memory_text(memory)}")


def headed_lines(entries, members, npc_id):
    """entries are (line, speaker, thread_id) rows, and members the thread_members of their threads. A header names the
    others of each chat thread before its lines, for the Dialogue Library and the bio prompt."""
    lines, previous = [], None
    for line, _, thread_id in entries:
        if thread_id is not None and thread_id != previous:
            lines.append(f"({scene_text.conversation_label(*_members_seen_by(members.get(thread_id, []), npc_id))})")
        lines.append(line)
        previous = thread_id
    return lines


def _members_seen_by(members, npc_id):
    """The other speakers, the overhearers that were in the player's faction, and whether the NPC only overheard. Only those
    overhearers count, as in overheard_notes."""
    overheard = any(member_id == npc_id and role == "overheard" for member_id, _, role, _ in members)
    partners = [name or "someone" for member_id, name, role, _ in members if role == "speaker" and member_id != npc_id]
    listeners = [name for member_id, name, role, in_faction in members if role == "overheard" and in_faction and name and member_id != npc_id]
    return partners, listeners, overheard


def _dated(memory, text):
    return f"[{game_time_text(memory['game_time'])}] {text}" if memory["game_time"] is not None else text


def memory_text(memory):
    return named(memory["memory"], {member_id: name or "someone" for member_id, name, _, _ in memory["members"]})


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
