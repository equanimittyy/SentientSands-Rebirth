"""The topic and the lines of a radiant conversation, a talk between the player's characters, or between NPCs near them,
in which one LLM call writes each line. The replies of a yell after the first one are written the same way."""

import random
import re

from chat import chat_prompt, current_job, retrieval
from chat.prompts import describe_record

LENGTHS = (
    ((2, 4), "A remark gets a reply or two, and the talk dies out."),
    ((5, 7), "The talk goes back and forth a few times."),
    ((8, 10), "The talk catches, and it goes somewhere new before it ends."),
)
REPLY_SHARE = 0.5
SPEAKERS = (2, 5)
YELL_REPLIES = ((1, 2, 3), (50, 30, 20))
FAVOURED_SHARE = 0.75
_SILENT = ("Dead", "Unconscious", "Playing Dead")
_BONDS = ((10, "know each other well"), (3, "know each other"), (1, "have talked a little"), (0, "have never talked"))


def topic(memories, environment, rumors, choice=random.choice, location=None):
    """The topic from one kind with material, each kind with an equal chance, and the thread ID of its memory, or (None,
    None) when no kind has material. memories are shared_memories of the participants, environment is the one of the
    center, rumors are texts, and location is the lore record of the town of the center, or None."""
    kinds = []
    if memories:
        def remembered():
            memory = choice(memories)
            return f"A conversation that some of them remember. {chat_prompt.shared_memory(memory)}", memory["id"]
        kinds.append(remembered)
    if environment.get("town_name") or environment.get("zone_name"):
        kinds.append(lambda: (place_topic(location), None))
    if rumors:
        kinds.append(lambda: (f"A rumour that they heard: {choice(rumors)}", None))
    return choice(kinds)() if kinds else (None, None)


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


def yell_turns(keys, favoured, player, target, rng=random):
    """The (speaker, addressee) of each line of a yell: the player's line to the target, then 1 to 3 replies of the NPCs of
    keys, mostly 1. The first reply speaks to the player. Then, as in turns, the one addressed answers, or another NPC cuts
    in and speaks to the last speaker or to the player. Each pick takes an NPC of favoured at FAVOURED_SHARE, so a crowd
    does not drown out the NPC that the player meant."""
    count = rng.choices(*YELL_REPLIES)[0] if len(keys) > 1 else 1
    order = [(player, target)]
    speaker, addressee = _pick(keys, favoured, rng), player
    for index in range(count):
        if index:
            thirds = [key for key in keys if key not in (speaker, addressee)]
            if addressee != player and (not thirds or rng.random() < REPLY_SHARE):
                speaker, addressee = addressee, speaker
            else:
                speaker, addressee = _pick(thirds, favoured, rng), rng.choice((speaker, player))
        order.append((speaker, addressee))
    return order


def _pick(keys, favoured, rng):
    liked = [key for key in keys if key in favoured]
    rest = [key for key in keys if key not in favoured]
    return rng.choice(liked if liked and (not rest or rng.random() < FAVOURED_SHARE) else rest)


def can_answer(npc):
    """Whether a bystander of a yell can answer it: an NPC outside the player's faction that is awake."""
    return not npc.get("in_player_faction") and npc.get("health") not in _SILENT


def named(message, aliases):
    """The keys of aliases, which maps each key to the names of its NPC, whose name the message holds as a whole word."""
    lowered = message.lower()
    return {key for key, names in aliases.items() if any(re.search(rf"(?<!\w){re.escape(name.lower())}(?!\w)", lowered) for name in names if name)}


def plan(keys, rng=random):
    """The LENGTH of the prompt, which is the line count and its feel, and the turns of the lines."""
    (fewest, most), feel = rng.choice(LENGTHS)
    order = turns(keys, rng.randint(fewest, most), rng)
    return f"{len(order)} lines. {feel}", order


def turn(index, order, names):
    """The NEXT LINE of the prompt. Each call sees only the lines before it, so the line must know where it stands in the
    talk to open it or to close it. names maps each handle key to its Name."""
    speaker, addressee = order[index]
    where = f"Line {index + 1} of {len(order)}"
    if index == len(order) - 1:
        where += ", the last, which closes the talk"
    elif index == 0:
        where += ", which opens the talk"
    return f"{where}. {names[speaker]}|{speaker} speaks to {names[addressee] if addressee else 'everyone'}."


def talk(spoken, names):
    """THE TALK SO FAR of the prompt. spoken holds the (handle key, text) of each line."""
    return "\n".join(f"{names[key]}|{key}: {text}" for key, text in spoken) or "Nobody has spoken yet."


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


def voices(names, speaker):
    """The own names and the other names of reply_text.spoken for a line of the speaker. The model can start the reply
    with the label of the speaker, as THE TALK SO FAR shows each line, and go on with the lines of others."""
    own = {names[speaker].lower(), f"{names[speaker]}|{speaker}".lower()}
    others = {label.lower() for key, name in names.items() if key != speaker for label in (name, f"{name}|{key}")}
    return own, others - own
