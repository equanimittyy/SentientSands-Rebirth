import logging
import random

from chat import current_job, npc_names, provisional_profile, scene_text
from core import state
from core.game import context_dict, is_player_faction
from core.pipe import send_to_pipe
from store import campaign_db

# The game reports a skeleton as male. The prefixes cover the skeleton races of vanilla Kenshi and UWE.
SKELETON_RACE_PREFIXES = ("skeleton", "p2 unit", "p4 unit", "screamer", "soldierbot")

def is_skeleton(race):
    return str(race).strip().lower().startswith(SKELETON_RACE_PREFIXES)

def reported_sex(race, gender):
    return "Other" if is_skeleton(race) else gender

def character_kind(animal, race):
    return "animal" if animal else "skeleton" if is_skeleton(race) else "person"

def animal_flag(ctx):
    """The game's own animal flag, which knows the animal races of every mod. The template validator takes no true or
    false as a profile value, so the profile stores 1 or 0."""
    return int(bool(ctx.get("animal")))

KENSHI_NAME_POOL = [
    "Kaelen", "Korg", "Vayn", "Sark", "Mina", "Rook", "Drake", "Silas", "Tane", "Kuna",
    "Zarek", "Jorn", "Lyra", "Kael", "Brena", "Torin", "Sola", "Fen", "Krax", "Vora",
    "Dax", "Nyx", "Garek", "Sora", "Thane", "Kira", "Zane", "Lara", "Marek", "Vina",
    "Rel", "Kaan", "Siv", "Tork", "Meda", "Grox", "Vael", "Syra", "Keld", "Bara",
    "Dorn", "Neld", "Gora", "Sark", "Vane", "Kura", "Zora", "Lena", "Morn", "Vora",
    "Rael", "Kona", "Sima", "Teld", "Mora", "Grak", "Vael", "Sura", "Karn", "Bena",
    "Drak", "Nala", "Gora", "Sina", "Vara", "Kela", "Zana", "Lina", "Mina", "Vorna",
    "Hark", "Skal", "Vorn", "Grek", "Myla", "Rion", "Daka", "Sith", "Tyla", "Korr",
    "Zent", "Lyr", "Brax", "Vort", "Nara", "Grel", "Syk", "Tarn", "Moko", "Vull",
    "Kess", "Tory", "Vann", "Sael", "Miro", "Lorn", "Gryf", "Dael", "Sina", "Kura"
]

def get_used_names():
    return {name.lower() for name in campaign_db.character_names()}

def generate_unique_lore_name(gender="Neutral"):
    used = get_used_names()
    
    gender_key = "Neutral"
    if gender.lower() == "male": gender_key = "Male"
    elif gender.lower() == "female": gender_key = "Female"
    
    pool = state.NAMES_CONFIG.get(gender_key, [])
    if not pool and gender_key != "Neutral":
        pool = state.NAMES_CONFIG.get("Neutral", [])
    
    if not pool:
        pool = KENSHI_NAME_POOL
    
    available = [n for n in pool if n.lower() not in used]
    if not available:
        base = random.choice(pool if pool else KENSHI_NAME_POOL)
        for i in range(1, 1000):
            candidate = f"{base} {i}"
            if candidate.lower() not in used:
                return candidate
        return f"{base}_{random.randint(1000, 9999)}"
    
    return random.choice(available)

def job_of(ctx):
    """The Current Job from the context of one NPC, or None. The faction of a banter NPC is its identity faction, so only
    in_player_faction marks a squad member there."""
    in_squad = ctx.get("in_player_faction") or is_player_faction(ctx.get("faction"), ctx.get("factionID"))
    return current_job.current_job(ctx, in_squad, state.PLAYER_CONTEXT.get("faction", "Nameless"))

def job_field(ctx):
    """The CurrentJob of a new profile. Only a context from the plugin carries the squad jobs."""
    job = job_of(ctx) if "squad_jobs" in ctx else None
    return {"CurrentJob": job} if job else {}

def location_field(ctx):
    """The CurrentLocation of a new profile."""
    return {"CurrentLocation": scene_text.location_name(ctx)} if "building_name" in ctx else {}

def new_profile(name, npc_id, ctx_data):
    """The profile of an NPC at its first meeting, rolled in code. The LLM would know no more than the race, the faction, and
    the job yet, so the roll loses nothing; the LLM writes the bio later (generate_bio). An animal's roll is final, because a
    bio would give it a backstory and a speech quirk."""
    live_ctx = state.LIVE_CONTEXTS.get(npc_id) or {}

    def fact(key, missing="Unknown"):
        value = ctx_data.get(key, missing)
        return live_ctx.get(key, missing) if value == missing else value

    race = fact("race")
    animal = animal_flag(ctx_data)
    kind = character_kind(animal, race)
    faction = fact("faction")
    # Modded factions often report no name through the hooks
    if faction == "Unknown":
        faction = ctx_data.get("factionID") or live_ctx.get("factionID") or "Unknown"
    logging.info(f"PROFILE: Rolled the profile of {name} ({npc_id})")
    return {
        "Name": name,
        "Race": race,
        "Animal": animal,
        "Sex": reported_sex(race, fact("gender")),
        "Faction": faction,
        "OriginFaction": fact("origin_faction"),
        **job_field(ctx_data),
        **location_field(ctx_data),
        **provisional_profile.roll(npc_id, kind, race),
        "ConversationHistory": [],
        "Relation": int(float(ctx_data.get("relation", 0)) / 2),
        **({} if kind == "animal" else {campaign_db.PROVISIONAL: 0}),
    }

def get_character_data(name, context=""):
    """The profile of the NPC that the context names by npc_id. Without an npc_id the profile is a stand-in that is never stored."""
    name = str(name).split('|')[0].strip()
    ctx_data = context_dict(context)
    npc_id = ctx_data.get("npc_id")

    data = campaign_db.get_character(npc_id) if npc_id else None
    stored = dict(data) if data else {}

    if ctx_data:
        try:
            if data:
                current_race = ctx_data.get("race", "Unknown")
                current_sex = reported_sex(current_race, ctx_data.get("gender", "Unknown"))
                current_faction = ctx_data.get("faction", "Unknown")
                needs_save = False
                
                if data.get("Race") == "Unknown" and current_race != "Unknown":
                    logging.debug(f"PROFILE: Updating Race for {name}: {current_race}")
                    data["Race"] = current_race
                    needs_save = True
                    
                if "animal" in ctx_data and data.get("Animal") != animal_flag(ctx_data):
                    logging.debug(f"PROFILE: Updating Animal for {name}: {animal_flag(ctx_data)}")
                    data["Animal"] = animal_flag(ctx_data)
                    needs_save = True

                if data.get("Sex") in ("Unknown", None) and current_sex not in ("Unknown", None):
                    logging.debug(f"PROFILE: Updating Sex for {name}: {current_sex}")
                    data["Sex"] = current_sex
                    needs_save = True
                    
                if data.get("Faction") == "Unknown" and current_faction != "Unknown":
                    logging.debug(f"PROFILE: Updating Faction for {name}: {current_faction}")
                    data["Faction"] = current_faction
                    needs_save = True

                current_origin = ctx_data.get("origin_faction", "Unknown")
                if data.get("OriginFaction") == "Unknown" and current_origin != "Unknown":
                    logging.debug(f"PROFILE: Updating OriginFaction for {name}: {current_origin}")
                    data["OriginFaction"] = current_origin
                    needs_save = True

                # Only a context from the plugin carries the squad jobs
                if "squad_jobs" in ctx_data:
                    job = job_of(ctx_data)
                    if job != data.get("CurrentJob"):
                        logging.debug(f"PROFILE: Updating CurrentJob for {name}: {job}")
                        data["CurrentJob"] = job
                        needs_save = True

                # Only the full context of a chat target, a speaker, or a rename carries the building
                if "building_name" in ctx_data:
                    location = scene_text.location_name(ctx_data)
                    if location != data.get("CurrentLocation"):
                        logging.debug(f"PROFILE: Updating CurrentLocation for {name}: {location}")
                        data["CurrentLocation"] = location
                        needs_save = True

                # Bypasses should_save_profile, which would drop generic-content profiles
                if needs_save:
                    campaign_db.upsert_profile(npc_id, {k: data[k] for k in ("Race", "Animal", "Sex", "Faction", "OriginFaction", "CurrentJob", "CurrentLocation") if k in data})
                    if data.get("CurrentJob") is None:
                        data.pop("CurrentJob", None)
        except Exception as e:
            logging.error(f"PROFILE: Cannot update the profile from the context: {e}")

    if not data:
        if not npc_id:
            logging.debug(f"PROFILE: {name} has no npc_id, so the chat uses a stand-in profile.")
            return {
                "Name": name,
                "Race": ctx_data.get("race", "Unknown"),
                "Animal": animal_flag(ctx_data),
                "Sex": reported_sex(ctx_data.get("race", "Unknown"), ctx_data.get("gender", "Unknown")),
                "Faction": ctx_data.get("faction", "Unknown"),
                "OriginFaction": ctx_data.get("origin_faction", "Unknown"),
                **job_field(ctx_data),
                "Personality": "A quiet traveler.",
                "Backstory": f"A {ctx_data.get('race', 'person')} from {ctx_data.get('faction', 'the borderlands')}.",
                "SpeechQuirks": "",
                "ConversationHistory": [],
                "Relation": int(float(ctx_data.get("relation", 0)) / 2),
            }
        data = new_profile(name, npc_id, ctx_data)

    if should_save_profile(name, npc_id, data):
        # Only the changed keys, so the write cannot undo a change that another request made since the read
        changes = {k: v for k, v in data.items() if stored.get(k) != v}
        if changes:
            campaign_db.upsert_profile(npc_id, changes)
    return data

def should_save_profile(name, npc_id, data):
    if not name or name in ("Unknown", "Someone"):
        return False
        
    personality = data.get("Personality", "").lower()
    is_generic_content = any(x in personality for x in ("unknown", "generic npc"))
    has_history = len(data.get("ConversationHistory", [])) > 0
    
    if is_generic_content and not has_history:
        return False
        
                
    return True

def send_rename(npc_id, name):
    """The plugin puts the name in place of the token of the template, so the game keeps its own title (npc_names)."""
    send_to_pipe(f"NPC_RENAME: {npc_id}|{name}")

def sync_name(npc, profile, in_squad):
    """Renames a stored NPC in game to match its profile, and returns its Name. The player can rename a squad member in game,
    so there the profile follows the game name instead."""
    npc_id, game_name = npc["npc_id"], npc_names.name_of(npc)
    name = profile["Name"]
    if npc_names.unnamed(npc) and name == game_name:
        name = generate_unique_lore_name(profile.get("Sex", "Neutral"))
    elif in_squad and not npc_names.unnamed(npc):
        name = game_name
    if name != profile["Name"]:
        campaign_db.rename_character(npc_id, profile["Name"], name)
        logging.info(f"NAME: {profile['Name']} ({npc_id}) is now {name}")
        profile["Name"] = name
    if game_name != name:
        send_rename(npc_id, name)
    return name

def npc_name(npc):
    """The Name of an NPC in a chat or banter request. The rename goes out before the LLM call, so the name changes in game
    while the player waits for the reply."""
    name = npc_names.name_of(npc)
    npc_id = npc.get("npc_id")
    if not npc_id:
        return name
    profile = get_character_data(name, npc)
    # The campaign stores no profile named Someone or Unknown, so a rolled name would live only in the game
    if not campaign_db.character_exists(npc_id):
        return name
    # The faction of a banter NPC is its identity faction, so only in_player_faction marks a squad member there
    in_squad = npc.get("in_player_faction") or is_player_faction(npc.get("faction"), npc.get("factionID"))
    return sync_name(npc, profile, in_squad)
