"""The Name and the Job of an NPC, from its game name and the name of its template, and the name that the game shows for it.

A generic template names its NPCs in one of three ways. A title with a name token, such as `Barman /GENNAME/` in UWE, makes
the game put a name of its own in place of the token: Barman Arleen is Arleen, a Barman. A template that the game data marks
`named` gets a whole name from the game, for example a Drifter called Nuno. Any other template gives only its own name, such
as Dust Bandit. Only this last kind gets a rolled Name, when a chat or banter first stores the NPC.

Once the campaign stores a generic NPC, the game shows its Job in front of its Name as a title, Drifter Nuno or Dust Bandit
Josh, so an edit of the Name on the web app shows in game. A member of the player's faction drops the title.
"""
import re

NAME_TOKEN = re.compile(r"/[A-Z]+/")
NO_JOB = (None, "", "None", "Unknown")


def split(npc):
    """The Name and the Job of an NPC from its context. The template of a unique NPC is the NPC itself, so it gives no Job."""
    name, template = npc.get("name", ""), npc.get("template", "")
    if npc.get("unique") or not template:
        return name, None
    parts = NAME_TOKEN.split(template, maxsplit=1)
    if len(parts) == 1:
        # The title that shown() puts in front of the Name
        return name.removeprefix(template + " "), template
    # A game name that the template does not match is a name that the player gave
    match = re.fullmatch(re.escape(parts[0]) + "(.+)" + re.escape(parts[1]), name)
    return (match.group(1) if match else name), (parts[0].strip() or None)


def unnamed(npc):
    """Whether the game shows the NPC by the name of its template, with no name of its own."""
    return not npc.get("unique") and bool(npc.get("template")) and npc.get("name") == npc["template"]


def shown(npc_id, profile, in_player_faction):
    """The name that the game shows for a stored NPC. A canon character holds a sentence as its Job, so only a generic NPC
    gets the title."""
    job = profile.get("Job")
    if in_player_faction or not npc_id.startswith("h:") or job in NO_JOB:
        return profile["Name"]
    return f"{job} {profile['Name']}"


def job_text(profile):
    """The Job for the prompts and the views. A recruit keeps its old role as FormerJob (see end_job in the server)."""
    if profile.get("Job") not in NO_JOB:
        return profile["Job"]
    return f"Former {profile['FormerJob']}" if profile.get("FormerJob") else "None"
