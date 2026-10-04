"""The Name and the Job of an NPC, from its game name and the name of its template.

A generic template names its NPCs in one of three ways. A title with a name token, such as `Barman /GENNAME/` in UWE, makes
the game put a name of its own in place of the token: Barman Arleen is Arleen, a Barman. A template that the game data marks
`named` gets a whole name from the game, for example a Drifter called Nuno. Any other template gives only its own name, such
as Dust Bandit. Only this last kind gets a rolled Name, when a chat or banter first stores the NPC, and the game shows the
template name in front of it as a title: Dust Bandit Josh. A recruit drops the title.
"""
import re

NAME_TOKEN = re.compile(r"/[A-Z]+/")


def split(npc):
    """The Name and the Job of an NPC from its context. The template of a unique NPC is the NPC itself, so it gives no Job."""
    name, template = npc.get("name", ""), npc.get("template", "")
    if npc.get("unique") or not template:
        return name, None
    parts = NAME_TOKEN.split(template, maxsplit=1)
    if len(parts) == 1:
        return name, template
    # A game name that the template does not match is a name that the player gave
    match = re.fullmatch(re.escape(parts[0]) + "(.+)" + re.escape(parts[1]), name)
    return (match.group(1) if match else name), (parts[0].strip() or None)


def unnamed(npc):
    """Whether the game shows the NPC by the name of its template, with no name of its own."""
    return not npc.get("unique") and bool(npc.get("template")) and npc.get("name") == npc["template"]


def names(profile, game_name, in_player_faction, roll):
    """The Name of an unnamed NPC and the name that the game shows for it. A stored Name that differs from the game name is a
    name that the game lost, for example after the load of an earlier save. Only a rolled Name, which GivenName marks, gets the
    title, so a name that the player gave stays bare."""
    name = profile["Name"]
    rolled = profile.get("GivenName") == name
    if name == game_name:
        name, rolled = roll(), True
    return name, (f"{game_name} {name}" if rolled and not in_player_faction else name)


def recruit_name(npc, profile):
    """The name of a recruit without its title, or None. A game name other than the titled one is a name that the player
    gave in game, so it stays."""
    name = profile.get("Name")
    if name and profile.get("GivenName") == name and npc.get("name") == f"{npc.get('template')} {name}":
        return name
    return None
