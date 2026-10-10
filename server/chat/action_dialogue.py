"""The action dialogue: a chat thread that the player marks with "!", so that the NPC can make a deal that the game carries
out (docs/plans/action_dialogue/framework.md).

The checks here read only the contexts that the plugin sends, so they hold no state. routes.chat keeps the action dialogue
in state.CURRENT_THREAD, because it ends with its chat thread.
"""

import json
import random
import re

from chat import current_job
from core.paths import DEFAULTS_DIR

# In the order of the classify list
CATEGORIES = [
    ("t", "threaten", "THREATEN", "A threat or demand"),
    ("b", "barter", "BARTER", "A request to trade items, a gift, or a plea for charity"),
    ("h", "heal", "HEAL", "A request to treat wounds"),
    ("l", "liberate", "LIBERATE", "A request to be freed from prison or slavery"),
    ("r", "recruit", "RECRUIT", "A request to join the squad for good, as a new member"),
    ("f", "follow", "FOLLOW", 'A request to come along or be hired for a while, such as "follow me"'),
    ("d", "dismiss", "DISMISS", "An order for a hired follower to leave"),
]
NONE_OF_THESE = "None of these"
GUARD_JOBS = {"Guarding the town", "Guarding a building", "Patrolling the town", "Keeping the peace", "Working as a slaver"}
END_LINES_PATH = f"{DEFAULTS_DIR}/action_end_lines.json"
_WORD = re.compile(r"[^\W\d_]+")


def parse(message):
    """(kind, category, text) of a player line. kind is None for plain chat, or "category", "classify", "end", or "failure".
    text is the line without its mark."""
    message = message.strip()
    if len(message) < 2 or message[0] != "!":
        return None, None, message
    if message[1] == " ":
        return "classify", None, message[1:].strip()
    word = _WORD.match(message, 1)
    if not word:
        return None, None, message
    text = message[word.end():].strip()
    name = word.group(0).lower()
    if name in ("e", "end"):
        return "end", None, text
    for letter, full, category, _ in CATEGORIES:
        if name in (letter, full):
            return "category", category, text
    return "failure", None, text


def knockout_block(npc, speaker, npc_name, speaker_name):
    """The block of every line, plain chat too, because a knocked-out character cannot talk."""
    for ctx, name in ((speaker, speaker_name), (npc, npc_name)):
        if ctx.get("character_state") == "unconscious":
            return f"{name} is unconscious."
    return None


def mark_block(npc, npc_name, in_player_faction):
    """The block of every marked line, before any classify call."""
    if npc.get("animal"):
        return f"{npc_name} is an animal and makes no deals."
    if in_player_faction:
        return f"{npc_name} is a member of your faction."
    return None


def gate_block(category, npc, speaker, npc_name):
    """The message of the first gate of the category that fails, or None. The classify list leaves out each category that
    this blocks, so a named mark and the classify call reach the same categories."""
    npc_state, speaker_state = npc.get("character_state"), speaker.get("character_state")
    if category == "THREATEN":
        if speaker_state == "imprisoned":
            return "You can't threaten anyone while imprisoned."
    elif category == "HEAL":
        if not wounded(speaker):
            return "You have no wounds to treat."
        if not npc.get("has_first_aid"):
            return f"{npc_name} has no first aid kit."
        if npc_state == "imprisoned":
            return f"{npc_name} can't treat you while imprisoned."
    elif category == "LIBERATE":
        if speaker_state not in ("imprisoned", "enslaved"):
            return "You are neither imprisoned nor enslaved."
        if npc_state == "imprisoned":
            return f"{npc_name} can't free you while imprisoned."
        # A slave in a cage reads as imprisoned, so the slave state comes apart from character_state
        if speaker.get("slave") and is_guard(npc):
            return f"{npc_name} is a guard, and a guard never frees a slave."
    elif category in ("RECRUIT", "FOLLOW"):
        verb = "recruit" if category == "RECRUIT" else "hire"
        if speaker_state in ("imprisoned", "enslaved"):
            return f"You can't {verb} anyone while {speaker_state}."
        if npc_state in ("imprisoned", "enslaved"):
            return f"{npc_name} can't {'join' if category == 'RECRUIT' else 'follow'} you while {npc_state}."
        if npc.get("is_leader"):
            return f"{npc_name} leads {npc.get('faction') or 'a faction'} and will not leave it."
    elif category == "DISMISS":
        if not npc.get("temporary_follower"):
            return f"{npc_name} is not a hired follower."
    return None


def wounded(ctx):
    """A body part below its full health, so a slight wound counts too: the Injured of health needs a part below 70%."""
    limbs = (ctx.get("medical") or {}).get("limbs") or {}
    hurt = any(hp < limbs.get(f"{part}_max", hp) for part, hp in limbs.items() if not part.endswith("_max"))
    return hurt or ctx.get("health") in ("Injured", "Crippled")


def is_guard(npc):
    return current_job.current_job(npc, False, "") in GUARD_JOBS


def choices(npc, speaker, npc_name):
    """The categories of the classify list: each one that the game state does not rule out."""
    return [category for _, _, category, _ in CATEGORIES if not gate_block(category, npc, speaker, npc_name)]


def choice_list(categories):
    """The numbered list of the classify prompt, which ends in the escape hatch."""
    labels = {category: label for _, _, category, label in CATEGORIES}
    return "\n".join(f"{number}. {text}" for number, text in enumerate([*(labels[c] for c in categories), NONE_OF_THESE], 1))


def chosen(output, categories):
    """The category of the number that the classify call gave, or None for the escape hatch or any other output."""
    number = re.search(r"\d+", output or "")
    index = int(number.group(0)) - 1 if number else -1
    return categories[index] if 0 <= index < len(categories) else None


def ended(content):
    return bool(re.search(r"\[\s*END\s*\]", content, re.IGNORECASE))


def end_line(end):
    """A random preset line of the end, for example "end" for !end."""
    with open(END_LINES_PATH, "r", encoding="utf-8") as f:
        return random.choice(json.load(f)[end])
