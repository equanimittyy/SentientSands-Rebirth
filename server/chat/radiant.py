"""The topic and the reply of a radiant conversation, a talk between the player's characters that one LLM call writes."""

import random
import re

from chat import chat_prompt

_LINE = re.compile(r"^([^:|\n]{1,63})\|(\d+)\s*:\s*(.*)$")
# Allows one level of nested brackets, as the chat reply does: item names like "Bolts [Toothpicks]" contain them
_BRACKETS = re.compile(r"\[\s*(?:[^\[\]]|\[[^\[\]]*\])+\s*\]")


def topic(memories, environment, rumors, choice=random.choice):
    """The topic from one kind with material, each kind with an equal chance, or None when no kind has material. memories
    are shared_memories of the participants, environment is the one of the center, and rumors are texts."""
    kinds = []
    if memories:
        kinds.append(lambda: f"A conversation that some of them remember. {chat_prompt.shared_memory(choice(memories))}")
    if environment.get("town_name") or environment.get("biome"):
        kinds.append(lambda: "The place where they are.")
    if rumors:
        kinds.append(lambda: f"A rumour that they heard: {choice(rumors)}")
    return choice(kinds)() if kinds else None


def lines(content, serials):
    """The (serial, text) of each line of the reply whose serial names a participant. A line of anyone else, or with no
    speaker, would reach the game as a line of nobody."""
    found = []
    for line in content.splitlines():
        match = _LINE.match(line.strip())
        if not match or match.group(2) not in serials:
            continue
        text = _BRACKETS.sub("", match.group(3)).strip().strip('"').strip()
        if text:
            found.append((match.group(2), text))
    return found
