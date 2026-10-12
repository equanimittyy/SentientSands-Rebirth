"""The words of one character in an LLM reply. A chat reply and a radiant line each speak for one character, so both clean
the reply the same way."""

import logging
import re

# Allows one level of nested brackets: item names like "Bolts [Toothpicks]" contain them
_BRACKETS = re.compile(r"\[\s*(?:[^\[\]]|\[[^\[\]]*\])+\s*\]")
_META = (
    "thought:", "thinking:", "observation:", "note:", "(thinking",
    "as an ai", "i cannot", "here is", "raw llm response:",
    "timestamp:", "request for:", "prompt:", "user message:",
    "history:", "character:", "personality:", "backstory:", "current condition",
)
_LABEL = re.compile(r"^([^:]{1,63}):\s*")


def spoken(content, own_names, other_names):
    """The lines of the reply as one line, or "" when none is left. The names are lowercase. The own label goes from its
    line, also when other_names holds it, because an NPC that talks to itself is its own speaker. A line labeled with
    another name ends the reply, because the lines after it answer words that the model made up for someone else."""
    content = _BRACKETS.sub("", content).strip().replace('"', '').strip()
    kept = []
    for line in content.split("\n"):
        line = re.sub(r"\[\s*[^\]]+\s*\]", "", line.strip()).strip()
        if not line or line.lower().startswith(_META):
            continue
        # A divider such as "===" holds no letters, but an animal's "Grr" does
        if not any(c.isalnum() for c in line):
            continue
        # Only a known name counts as a speaker, so a reply such as "Listen: ..." keeps its first word
        label = _LABEL.match(line)
        if label:
            name = label.group(1).strip().strip("*").lower()
            if name in own_names:
                line = line[label.end():]
            elif name in other_names:
                logging.debug(f"REPLY: Cut the reply at a line voiced as {name}")
                break
        if line:
            kept.append(line)
    # The plugin shows each line as its own speech bubble, so one reply is one line
    return " ".join(kept)
