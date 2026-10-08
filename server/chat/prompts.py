import logging

from chat import prompt_store, scene_text, towns
from chat.characters import is_skeleton, reported_sex
from core import deeds, state
from core.game import is_player_faction
from core.paths import PROMPTS_DIR, USER_PROMPTS_DIR
from core.settings import load_settings
from store import campaign_db

PROMPT_RUMORS = 5

def describe_faction(name, faction_id=None):
    return faction_text(name, campaign_db.find_faction(faction_id, name) if name and name != "Unknown" else None)

def faction_text(name, faction):
    if not name or name == "Unknown":
        return "Unknown Faction (Remnant or Drifter)"
    if not faction or not (faction.get("description") or faction.get("fields") or faction.get("major")):
        return f"{name}: A minor or specialized group in the wasteland."
    return describe_record(faction)

def describe_origin(origin, current):
    """Most NPCs still belong to their origin faction, whose whole entry the prompt already holds."""
    return "Same as the current faction." if origin == current else origin

def describe_record(record, kind=None):
    details = "; ".join([*([kind] if kind else []), *(f"{key}: {_fact_text(value)}" for key, value in record.get("fields", {}).items())])
    text = f"{record['name']} ({details})" if details else record["name"]
    return f"{text}: {record['description']}" if record.get("description") else text

def _fact_text(value):
    if isinstance(value, dict):
        return ", ".join(f"{name} to the {direction}" for name, direction in value.items())
    return ", ".join(value) if isinstance(value, list) else value

def find_named(records, name):
    wanted = str(name).strip().lower()
    return next((record for record in records if wanted in (other.lower() for other in [record.get("name", ""), *record.get("aliases", [])])), None)

def find_race(race):
    return find_named((entry for (category, _), entry, *_ in campaign_db.list_records("entity") if category == "races"), race)

def find_location(town):
    location = find_named((entry for (category, _), entry, *_ in campaign_db.list_records("entity") if category == "locations"), town)
    return towns.current(location) if location else None

def describe_race(race):
    entry = find_race(race)
    return describe_record(entry) if entry else f"{race}: The campaign has no entry for this race."

def npc_scene(context, profile, player_name, met, companions, player_stats):
    faction = context.get("faction") or context.get("Faction", "Unknown")
    player_faction = state.PLAYER_CONTEXT.get("faction", "Nameless")
    in_player_faction = is_player_faction(faction, context.get("factionID"))
    record = campaign_db.find_faction(context.get("factionID"), faction) or {}
    major = not in_player_faction and bool(record.get("major"))
    # The player section of the scene already describes the player's faction
    faction_description = "" if in_player_faction else record.get("description", "")
    return scene_text.npc_text(context, profile, player_name, player_faction, met=met,
                               major=major, in_player_faction=in_player_faction, feels_hunger=not is_skeleton(profile.get("Race", "")),
                               faction_description=faction_description, companions=companions, player_stats=player_stats)

def load_prompt_component(filename):
    text = prompt_store.load(filename, PROMPTS_DIR, USER_PROMPTS_DIR)
    if not text:
        logging.error(f"PROMPT: {filename} is missing or empty in {PROMPTS_DIR}")
    return text

def fill_prompt(filename, **values):
    template = load_prompt_component(filename)
    unknown = prompt_store.placeholders(template) - values.keys()
    if unknown:
        logging.warning(f"PROMPT: {filename} has placeholders that nothing fills, so they stay as text: {', '.join(sorted(unknown))}")
    return prompt_store.render(template, values)

def current_job_line(profile):
    """The whole prompt line, because an NPC without a Current Job gets no line at all."""
    return f"CURRENT JOB: {profile['CurrentJob']}" if profile.get("CurrentJob") else ""

def alias_line(profile):
    """The whole prompt line, because an NPC without an Alias gets no line at all."""
    return f"ALIAS (the name that the bounty notices give this character): {profile['Alias']}" if profile.get("Alias") else ""

def building_of(ctx):
    """The building that the character is in, or None outdoors. The plugin sends Unknown outdoors."""
    building = ctx.get("building_name")
    return building if building and building != "Unknown" else None

def describe_npc(name, profile, npc_id, template="npc_chat_template.txt"):
    race = profile.get("Race", "Unknown")
    race_entry = find_race(race)
    current_faction = describe_faction(profile.get("Faction"), state.LIVE_CONTEXTS.get(npc_id, {}).get("factionID"))
    return fill_prompt(
        template,
        name=name,
        alias=alias_line(profile),
        race=describe_record(race_entry) if race_entry else race,
        sex=reported_sex(race, profile.get("Sex", "Unknown")),
        current_job=current_job_line(profile),
        current_faction=current_faction,
        origin_faction=describe_origin(describe_faction(profile.get("OriginFaction", "Unknown")), current_faction),
        personality=profile.get("Personality") or "",
        backstory=profile.get("Backstory") or "",
        speech_quirks=profile.get("SpeechQuirks") or "",
    )

def language_instruction():
    # Only player2 infers the language from context; other providers need it stated
    language = load_settings().get("language", "English")
    if language and language.lower() != "english":
        return f"\nLANGUAGE: You MUST respond ONLY in {language}. Do not switch to English under any circumstances.\n"
    return ""

def build_system_prompt(reply_rules=True):
    """The reply rules come last, so a radiant call, which has none, shares the rest with a chat as a cacheable start."""
    world_lore = campaign_db.overview()
    rules = load_prompt_component("response_rules.txt") if reply_rules else ""
    prompt = fill_prompt(
        "prompt_system.txt",
        world_lore=world_lore,
        rules=rules,
        language_instruction=language_instruction()
    )
    return prompt.strip()

def scene_values(player, player_name):
    rumors = [(rumor["game_time"], rumor["text"]) for rumor in deeds.told_rumors()[-PROMPT_RUMORS:]]
    race = player.get("race", "Unknown")
    race_entry = find_race(race)
    player_faction = campaign_db.player_faction()
    environment = player.get("environment") or {}
    location = find_location(environment["town_name"]) if environment.get("town_name") else None
    return {
        "location": " ".join(part for part in (scene_text.location_text(environment), (location or {}).get("change")) if part),
        "rumors": scene_text.rumors_text(rumors, state.PLAYER_CONTEXT.get("day")),
        "player": scene_text.player_text(
            player_name, race, reported_sex(race, player.get("gender", "Unknown")),
            race_entry.get("description", "") if race_entry else "",
            player.get("medical") or {}, not is_skeleton(race),
            player.get("faction", "Nameless"), player_faction["description"].strip() if player_faction else "",
            player.get("inventory") or [],
            building_of(player),
            player.get("character_state", "normal"),
        ),
    }
