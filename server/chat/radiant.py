"""The topic and the reply of a radiant conversation, a talk between the player's characters that one LLM call writes."""

import random
import re

from chat import chat_prompt, retrieval
from chat.prompts import describe_record

_LINE = re.compile(r"^([^:|\n]{1,63})\|(\d+)\s*:\s*(.*)$")
# Allows one level of nested brackets, as the chat reply does: item names like "Bolts [Toothpicks]" contain them
_BRACKETS = re.compile(r"\[\s*(?:[^\[\]]|\[[^\[\]]*\])+\s*\]")


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


def place_topic(location):
    """Without the lore, the place is only a name, so every character can say only the same few things about a town."""
    if not location:
        return "The place where they are."
    entry = describe_record({**location, "description": retrieval.clipped(location.get("description") or "")}, "location")
    return f"The place where they are. Its lore follows. They may know only a part of it, and they never recite it.\n{entry}"


def lines(content, serials):
    """The (serial, text) of each line of the reply, or none when a line is not the line of a participant. That line would
    reach the game as a line of nobody, and the conversation without it can make no sense."""
    found = []
    for line in content.splitlines():
        if not line.strip():
            continue
        match = _LINE.match(line.strip())
        if not match or match.group(2) not in serials:
            return []
        text = _BRACKETS.sub("", match.group(3)).strip().strip('"').strip()
        if text:
            found.append((match.group(2), text))
    return found
