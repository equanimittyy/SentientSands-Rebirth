"""The facts of a notable event, which the LLM turns into a rumor. The server writes the rumor of each deed in a quiet
period of the chat (write_rumors in chat/memory.py), and Generate Rumor writes it again with the player's instruction."""
import re

from chat.characters import reported_sex
from chat.prompts import fill_prompt
from core import deeds
from core.settings import load_settings
from store import campaign_db

_FIRST_SENTENCE = re.compile(r".+?[.!?](?=\s|$)", re.S)


def prompt(at, deed, instruction, rumor_so_far):
    text = fill_prompt(
        "prompt_world_synthesis.txt",
        instruction=instruction.strip() or "None.",
        facts=facts(at, deed),
        rumor=rumor_so_far.strip() or "None.",
    )
    language = load_settings().get("language", "English")
    if language and language.lower() != "english":
        text += f"\nLANGUAGE: Write the rumor ONLY in {language}. Do not use English.\n"
    return text


def facts(at, deed):
    """Plain sentences, because the LLM gets only these facts and must invent no other event."""
    ids = deeds.character_ids(deed)
    names = campaign_db.names_of(ids)
    player = campaign_db.player_faction() or {}
    faction = player.get("name") or "Nameless"
    description = (player.get("description") or "").strip()
    lines = [f"The player's faction: {faction}." + (f" {description}" if description else ""), f"The deed: {deed_sentence(deed, names, faction)}"]
    if at is not None:
        lines.append(f"Time: {campaign_db.game_time_text(at)}.")
    # The victim first, because a known figure is the news
    people = [person_line(profile) for profile in (campaign_db.get_character(npc_id) for npc_id in [*ids[-1:], *ids[:-1]]) if profile]
    if people:
        lines += ["Who they are:", *people]
    stance = faction_line(deed["victim"]["faction"]) if deed["deed"] != "custom" else None
    if stance:
        lines += ["The factions:", stance]
    return "\n".join(lines)


def deed_sentence(deed, names, player_faction):
    # The player wrote the rumor of a custom deed, so it is the only account of the deed
    if deed["deed"] == "custom":
        return "The one that the rumor so far tells."
    doers = deeds.name_list([names.get(doer["id"], doer["name"]) for doer in deed["doers"]])
    victim = names.get(deed["victim"]["id"], deed["victim"]["name"])
    faction = deed["victim"]["faction"]
    of = f" of {deeds.the_faction(faction)}" if faction and faction != "Neutral" else ""
    return f"{doers} of {player_faction} {'killed' if deed['deed'] == 'kill' else 'captured'} {victim}{of}."


def person_line(profile):
    """The sex tells the LLM which pronouns fit, and the first sentence of the backstory why the character matters."""
    race = profile.get("Race", "Unknown")
    sex = reported_sex(race, profile.get("Sex", "Unknown"))
    kind = f"{sex.lower()} {race}" if sex.lower() in ("male", "female") else f"{race}, no sex" if sex == "Other" else race
    first = _FIRST_SENTENCE.match((profile.get("Backstory") or "").strip())
    return f"- {profile.get('Name', 'Unknown')} ({kind})" + (f": {first.group(0)}" if first else "")


def faction_line(name):
    """The allies and enemies of the faction tell the LLM who cheers the news and who fears it."""
    fields = ((campaign_db.find_faction(None, name) if name else None) or {}).get("fields", {})
    parts = [f"{label}: {', '.join(fields[key])}" for key, label in (("allies", "Allies"), ("enemies", "Enemies")) if fields.get(key)]
    return f"- {name}. {'. '.join(parts)}." if parts else None


def clean(text):
    """The text of the rumor without the quotes, the bullet, or the line breaks that a model adds now and then."""
    text = " ".join((text or "").split())
    return re.sub(r"^[-*•]\s*", "", text).strip().strip('"“”').strip()
