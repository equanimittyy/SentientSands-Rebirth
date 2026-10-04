"""The Name of an NPC, from its game name and the name of its template.

A generic template names its NPCs in one of three ways. A title with a name token, such as `Barman /GENNAME/` in UWE, makes
the game put a name of its own in place of the token: Barman Arleen is Arleen. A template that the game data marks `named`
gets a whole name from the game, for example a Drifter called Nuno. Any other template gives only its own name, such as
Dust Bandit. Only this last kind gets a rolled Name, when a chat or banter first stores the NPC.

The server adds no title to a game name. A rename in game puts the Name in place of the token of the template, so the
game keeps the text around the name (NPC_RENAME in plugin/main.cpp).
"""
import re

NAME_TOKEN = re.compile(r"/[A-Z]+/")


def name_of(npc):
    """The Name of an NPC from its context. The template of a unique NPC is the NPC itself, so its game name is the Name."""
    name, template = npc.get("name", ""), npc.get("template", "")
    parts = NAME_TOKEN.split(template, maxsplit=1)
    if npc.get("unique") or len(parts) == 1:
        return name
    # A game name that the template does not match is a name that the player gave
    match = re.fullmatch(re.escape(parts[0]) + "(.+)" + re.escape(parts[1]), name)
    return match.group(1) if match else name


def unnamed(npc):
    """Whether the game shows the NPC by the name of its template, with no name of its own."""
    return not npc.get("unique") and bool(npc.get("template")) and npc.get("name") == npc["template"]
