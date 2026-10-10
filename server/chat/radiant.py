"""The topic and the reply of a radiant conversation, a talk between the player's characters, or between NPCs near them,
that one LLM call writes."""

import random
import re

from chat import chat_prompt, current_job, retrieval
from chat.prompts import describe_record

_LINE = re.compile(r"^([^:|\n]{1,63})\|(\d+)\s*:\s*(.*)$")
# Allows one level of nested brackets, as the chat reply does: item names like "Bolts [Toothpicks]" contain them
_BRACKETS = re.compile(r"\[\s*(?:[^\[\]]|\[[^\[\]]*\])+\s*\]")
# Left to choose, the model writes a long conversation every time, so the server picks the length of each one
LENGTHS = (
    ((2, 4), "A remark gets a reply or two, and the talk dies out."),
    ((5, 7), "The talk goes back and forth a few times."),
    ((8, 12), "The talk catches, and it goes somewhere new before it ends."),
)
REPLY_SHARE = 0.5
SPEAKERS = (2, 5)
_BONDS = ((10, "know each other well"), (3, "know each other"), (1, "have talked a little"), (0, "have never talked"))


def topic(memories, environment, rumors, choice=random.choice, location=None):
    """The topic from one kind with material, each kind with an equal chance, or None when no kind has material. memories
    are shared_memories of the participants, environment is the one of the center, rumors are texts, and location is the
    lore record of the town of the center, or None."""
    kinds = []
    if memories:
        kinds.append(lambda: f"A conversation that some of them remember. {chat_prompt.shared_memory(choice(memories))}")
    if environment.get("town_name") or environment.get("zone_name"):
        kinds.append(lambda: place_topic(location))
    if rumors:
        kinds.append(lambda: f"A rumour that they heard: {choice(rumors)}")
    return choice(kinds)() if kinds else None


def turns(keys, count, rng=random):
    """The (speaker, addressee) of each line, with None for everyone. Left to choose, the model gives each character one
    turn in a fixed round, and no line answers another. So the opener speaks to everyone, and then the one addressed
    answers, or a third character cuts in, and either speaks to the last speaker."""
    speaker, addressee = rng.choice(keys), None
    order = []
    for _ in range(count):
        order.append((speaker, addressee))
        thirds = [key for key in keys if key not in (speaker, addressee)]
        if addressee and (not thirds or rng.random() < REPLY_SHARE):
            speaker, addressee = addressee, speaker
        else:
            speaker, addressee = rng.choice(thirds), speaker
    return order


def script(names, rng=random):
    """The TURNS of the prompt: the length and its feel, then the speaker and the addressee of each line. names maps each
    handle key to its Name."""
    (fewest, most), feel = rng.choice(LENGTHS)
    order = turns(list(names), rng.randint(fewest, most), rng)
    rows = [f"{index}. {names[speaker]}|{speaker} to {names[addressee] if addressee else 'everyone'}" for index, (speaker, addressee) in enumerate(order, 1)]
    return "\n".join([f"{len(order)} lines. {feel}", *rows])


def npc_group(npcs, has_profile, rng=random):
    """The NPCs of an NPC radiant conversation: a rolled count of 2 to 5 members of one squad at a bar, or none. npcs come
    nearest first. The nearest squad in which an NPC has a profile wins, else the nearest squad. Its members with a profile
    talk first, and the others fill the rolled places, so each of them gets a new profile."""
    squads = {}
    for npc in npcs:
        if current_job.current_job(npc, False, "") == current_job.AT_A_BAR:
            squads.setdefault(npc["squad"], []).append(npc)
    groups = [members for members in squads.values() if len(members) >= 2]
    if not groups:
        return []
    known = {npc["npc_id"] for members in groups for npc in members if has_profile(npc["npc_id"])}
    members = next((members for members in groups if any(npc["npc_id"] in known for npc in members)), groups[0])
    return sorted(members, key=lambda npc: npc["npc_id"] not in known)[:rng.randint(*SPEAKERS)]


def npc_talk(npcs, rumors, chance, roll=random.random):
    """Whether the NPCs near the center talk in place of the squad. They talk only about a rumour, so never without one.
    chance is a percent."""
    return bool(npcs and rumors) and roll() * 100 < chance


def place_topic(location):
    """Without the lore, the place is only a name, so every character can say only the same few things about a town."""
    if not location:
        return "The place where they are."
    entry = describe_record({**location, "description": retrieval.clipped(location.get("description") or "")}, "location")
    return f"The place where they are. Its lore follows. They may know only a part of it, and they never recite it.\n{entry}"


def acquaintance(names, partners):
    """One line for each pair of participants, because strangers have more to ask each other than old companions. names maps
    each npc_id to its name in the order of the participants, and partners maps it to its thread_partners."""
    ids = list(names)
    pairs = []
    for index, first in enumerate(ids):
        for second in ids[index + 1:]:
            count = partners[first].count(second)
            bond = next(words for least, words in _BONDS if count >= least)
            pairs.append(f"- {names[first]} and {names[second]} {bond}.")
    return "\n".join(pairs)


def lines(content, keys):
    """The (handle key, text) of each line of the reply, or none when a line is not the line of a participant. That line
    would reach the game as a line of nobody, and the conversation without it can make no sense."""
    found = []
    for line in content.splitlines():
        if not line.strip():
            continue
        match = _LINE.match(line.strip())
        if not match or match.group(2) not in keys:
            return []
        text = _BRACKETS.sub("", match.group(3)).strip().strip('"').strip()
        if text:
            found.append((match.group(2), text))
    return found
