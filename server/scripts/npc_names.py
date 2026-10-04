"""The names of generic NPCs.

A generic NPC keeps the name that the game gives it, such as Holy Sentinel, until the player first speaks to it. That
chat adds a given name from the name pool, and the game name stays in front of it as a title: Holy Sentinel Joe. A
recruit drops the title. Only the plugin can tell whether a name is generic in each game language, because only the
plugin sees the game data, so the server names an NPC only when the context of the NPC says so.
"""


def chat_names(profile, game_name, in_player_faction, roll):
    """The Name and the GivenName of a generic NPC at a chat turn. An NPC with a GivenName is never named again, so a game
    name that differs from its Name is one that the game lost, for example after the load of an earlier save."""
    given = profile.get("GivenName")
    if given:
        return profile["Name"], given
    given = roll()
    # A recruit gets no title, so its name changes once, not twice
    return (given if in_player_faction else f"{game_name} {given}"), given


def recruit_name(profile, game_name):
    """The name of a recruit without its title, or None. A game name that differs from the stored Name is one that the
    player gave in game, so it stays."""
    given = profile.get("GivenName")
    if given and game_name == profile["Name"] and game_name != given:
        return given
    return None
