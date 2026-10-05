import logging
import threading

from chat import chat_prompt
from chat.characters import reported_sex
from chat.llm import call_llm, robust_json_parse
from chat.prompts import current_job_line, describe_faction, describe_race, fill_prompt
from core import state
from core.settings import load_settings
from store import campaign_db

PROFILES_IN_PROGRESS = set()
PROGRESS_LOCK = threading.Lock()

BIO_PARTS = ("Personality", "Backstory", "SpeechQuirks")

def write_bio(profile, parts, instructions, history, race_lore, faction):
    """The parts of the bio that the LLM wrote, or None when its reply lacks one. Stores nothing."""
    race = profile.get("Race", "Unknown")
    names = ", ".join(parts)
    prompt = fill_prompt(
        "prompt_profile_generation.txt",
        parts=names,
        name=profile.get("Name", "Unknown"),
        race=race,
        sex=reported_sex(race, profile.get("Sex", "Unknown")),
        faction=faction,
        current_job=current_job_line(profile),
        race_lore=race_lore,
        current="\n".join(f"{part}: {profile.get(part) or ''}" for part in BIO_PARTS),
        history="\n".join(history) or "None yet.",
        instructions=instructions.strip() or "None.",
    )
    language = load_settings().get("language", "English")
    if language and language.lower() != "english":
        prompt += f"\nLANGUAGE: The JSON values ({names}) MUST be written entirely in {language}. Do not use English.\n"
    result = robust_json_parse(call_llm("profile", [{"role": "user", "content": prompt}]))
    # Only the requested parts, so a reply cannot change a part that the player did not ask for
    bio = {part: result[part].strip() for part in parts if isinstance((result or {}).get(part), str) and result[part].strip()}
    return bio if len(bio) == len(parts) else None

def recorded_history(npc_id):
    """The memories of the NPC, oldest first, then its stored lines, because a memory replaces the lines of its chat thread."""
    rows = campaign_db.dialogue(npc_id)
    members = campaign_db.thread_members({thread_id for _, _, thread_id in rows if thread_id is not None})
    return chat_prompt.memory_lines(campaign_db.memories_of(npc_id), npc_id) + chat_prompt.headed_lines(rows, members, npc_id)

def generate_bio(npc_id):
    """Has the LLM write the bio of a provisional NPC and stores it. It never touches a full profile, because the player may
    have written it by hand."""
    with PROGRESS_LOCK:
        if npc_id in PROFILES_IN_PROGRESS:
            logging.debug(f"PROFILE: The LLM is already writing the bio of {npc_id}.")
            return
        PROFILES_IN_PROGRESS.add(npc_id)
    campaign = state.ACTIVE_CAMPAIGN
    try:
        profile = campaign_db.get_character(npc_id)
        if campaign_db.PROVISIONAL not in (profile or {}):
            return
        name, race = profile.get("Name", npc_id), profile.get("Race", "Unknown")
        logging.info(f"PROFILE: Writing the bio of {name} ({npc_id})...")
        bio = write_bio(
            profile,
            # An animal keeps no backstory and no speech quirk
            ["Personality"] if profile.get("Animal") else list(BIO_PARTS),
            "",
            recorded_history(npc_id),
            describe_race(race),
            describe_faction(profile.get("Faction"), (state.LIVE_CONTEXTS.get(npc_id) or {}).get("factionID")),
        )
        if not bio:
            logging.warning(f"PROFILE: The LLM gave no usable bio for {name}, so the profile stays as it is.")
            return
        # A thread can outlive a campaign switch, and the same npc_id can name another character in the new campaign
        if state.ACTIVE_CAMPAIGN != campaign:
            logging.info(f"PROFILE: Dropped the bio of {name}, because the active campaign changed while the LLM wrote it.")
            return
        if not campaign_db.promote_profile(npc_id, bio):
            logging.info(f"PROFILE: Dropped the bio of {name}, because its profile stopped being provisional while the LLM wrote it.")
            return
        logging.info(f"PROFILE: Stored the bio of {name} ({npc_id}).")
    except Exception as e:
        # The chat threshold runs this in a thread, where nothing else would log the error
        logging.error(f"PROFILE: The bio of {npc_id} failed: {e}")
    finally:
        with PROGRESS_LOCK:
            PROFILES_IN_PROGRESS.discard(npc_id)
