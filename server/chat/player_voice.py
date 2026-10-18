"""Characterised player dialogue: one LLM call rewrites a chat line of the player in the words of the speaker.

The NPC hears the rewrite, but the code that matches words, such as the lore search, reads the raw line, because the
rewrite adds words of the speaker's manner.
"""

import logging
import re

from chat import reply_text
from chat.llm import call_llm
from chat.prompts import describe_persona, fill_prompt, language_instruction
from core import state
from core.settings import load_settings

_ACTIONS = re.compile(r"\*[^*]*\*")
_NUMBER = re.compile(r"\d[\d,]*")
_MARK = re.compile(r"^![A-Za-z]* *")
_VERBS = {"talk": "says", "whisper": "whispers", "yell": "yells"}
# The barter window sends this line for a blank Send (SendBarterLine in plugin/ui/BarterWindow.cpp). The player did not
# write it, so it has no gist to reword.
BLANK_DEAL = "How about this deal?"


def bubble(message):
    """The words of the bubble of the speaker, without the action mark that IsActionMark in plugin/ui/ChatWindow.cpp
    finds."""
    if message.startswith("/"):
        return ""
    second = message[1:2]
    marked = message.startswith("!") and (second.isascii() and second.isalpha() or second == " " and bool(message[2:].strip()))
    return _MARK.sub("", message) if marked else message


def _numbers(text):
    return {number.replace(",", "") for number in _NUMBER.findall(text)}


def rewrite(line, name, profile, listener, mode, until=None):
    """The line in the words of the speaker, or the line itself when it needs no call, the call fails, or the rewrite
    loses a number of the line, because a lost price breaks a trade."""
    blank = state.LOCALIZATION_CONFIG.get(load_settings()["language"], {}).get(BLANK_DEAL, BLANK_DEAL)
    if profile.get("Animal") or not re.search(r"\w", _ACTIONS.sub("", line)) or line == blank:
        return line
    prompt = fill_prompt(
        "prompt_player_voice.txt",
        speaker=name,
        race=profile.get("Race") or "Unknown",
        persona=describe_persona(profile),
        addressee=f"{name} {_VERBS.get(mode, 'says')} it to {listener}.",
        line=line,
        # Only with actions, because Gemma 4 put asterisks around the reworded words when the prompt named them
        actions="Keep each part in asterisks as it is." if _ACTIONS.search(line) else "",
        language_instruction=language_instruction(),
    )
    text = reply_text.spoken(call_llm("rephrase", [{"role": "user", "content": prompt}], until) or "", {name.lower()}, {listener.lower()})
    if not text:
        logging.warning(f"CHAT: The rewrite of the line of {name} got no reply, so the NPC hears the raw line.")
        return line
    if not _numbers(line) <= _numbers(text):
        logging.info(f'CHAT: The rewrite of the line of {name} lost a number, so the NPC hears the raw line: "{text}"')
        return line
    logging.info(f'CHAT: {name} says "{line}" as "{text}"')
    return text
