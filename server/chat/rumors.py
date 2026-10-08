"""The facts of an event, which the LLM turns into a rumor. The server writes the rumor of each event in a quiet
period of the chat (write_rumors in chat/memory.py), and Generate Rumor writes it again with the player's instruction. An
auto event is a rumor that the LLM spins from the conversation memories (auto_prompt), so its rumor is its only account. The
notice and the rumor of a bounty tell the facts of the game bounty, so only the rumor pass writes them, with the alias of its
target."""
import logging
import re

from chat.characters import reported_sex
from chat.chat_prompt import memory_text
from chat.prompts import fill_prompt
from core import state, world_events
from core.settings import load_settings
from store import campaign_db

_FIRST_SENTENCE = re.compile(r".+?[.!?](?=\s|$)", re.S)
AUTO_POOL = 40
AUTO_TOLD = 30
BOUNTY_PARTS = ("notice", "rumor", "alias")
ALIAS_WORDS = 6
CRIME_WORDS = {"ASSAULT_VIP": "assault of a VIP"}


def prompt(at, event, instruction, rumor_so_far):
    return in_language(fill_prompt(
        "prompt_world_synthesis.txt",
        instruction=instruction.strip() or "None.",
        facts=facts(at, event),
        rumor=rumor_so_far.strip() or "None.",
    ))


def auto_pool():
    """The memories that a pass of the auto rumors reads, or None when the pass waits: for the memories and the rumors of the
    events, which come first, or for a memory that no pass read, so a pool without a new memory costs no LLM call."""
    try:
        pool = campaign_db.rumor_pool(AUTO_POOL)
        if not any(memory["passes"] == 0 for memory in pool) or campaign_db.pending_threads() or any(event["rumor"] is None for event in world_events.events()):
            return None
    except campaign_db.CampaignUnavailable:
        return None
    return pool


def auto_prompt(memories):
    """memories are rumor_pool dicts. A label stands for each memory, because a short label is harder for the LLM to get
    wrong than a thread ID."""
    told = [rumor["text"] for rumor in campaign_db.rumors()[-AUTO_TOLD:]]
    return in_language(fill_prompt(
        "prompt_auto_rumor.txt",
        faction=player_line()[1],
        memories="\n".join(f"[{label}] {memory_line(memory)}" for label, memory in enumerate(memories, 1)),
        rumors="\n".join(f"- {text}" for text in told) or "None.",
    ))


def memory_line(memory):
    where = [campaign_db.game_time_text(memory["game_time"])] if memory["game_time"] is not None else []
    where += [memory["location"]] if memory["location"] else []
    return f"({'; '.join(where)}) {memory_text(memory)}" if where else memory_text(memory)


def keep_auto_rumor(reply, memories, campaign):
    """Stores the auto event of reply, the parsed JSON of the LLM, and counts the pass that read the memories. A reply that is
    not valid changes nothing, because the LLM judged no memory."""
    parsed = auto_reply(reply, memories)
    if parsed is None:
        logging.warning("RUMOR: The LLM gave no valid reply for the auto rumor, so the memories wait for the next pass.")
        return
    # The same thread ID can name another thread in another campaign
    if state.ACTIVE_CAMPAIGN != campaign:
        logging.info("RUMOR: Dropped the auto rumor, because the active campaign changed while the LLM wrote it.")
        return
    text, cited = parsed
    if text:
        event_id = campaign_db.add_auto_event(text, cited)
        if event_id is None:
            logging.info("RUMOR: Dropped the auto rumor, because a delete or a cull changed its memories while the LLM wrote it.")
            return
        logging.info(f"RUMOR: Stored the auto event {event_id} from the memories of the chat threads {', '.join(map(str, cited))}.")
    else:
        logging.info("RUMOR: The LLM found no story in the memories.")
    campaign_db.count_rumor_pass(memory["id"] for memory in memories)


def auto_reply(reply, memories):
    """The rumor of reply with the thread IDs of the memories that it cites, each once, or None when the reply is not valid:
    not a JSON object, or a rumor that cites no memory of the pass. An empty rumor cites nothing."""
    if not isinstance(reply, dict) or "rumor" not in reply or not isinstance(reply["rumor"], (str, type(None))):
        return None
    rumor = clean(reply["rumor"])
    if not rumor:
        return "", []
    threads = {str(label): memory["id"] for label, memory in enumerate(memories, 1)}
    labels = reply.get("memories") if isinstance(reply.get("memories"), list) else []
    cited = list(dict.fromkeys(threads[key] for key in (str(label).strip("[] ") for label in labels) if key in threads))
    return (rumor, cited) if cited else None


def in_language(text):
    language = load_settings().get("language", "English")
    if language and language.lower() != "english":
        text += f"\nLANGUAGE: Write the rumor ONLY in {language}. Do not use English.\n"
    return text


def player_line():
    """The name of the player's faction, and a sentence that names and describes it."""
    player = campaign_db.player_faction() or {}
    faction = player.get("name") or "Nameless"
    description = (player.get("description") or "").strip()
    return faction, f"The player's faction: {faction}." + (f" {description}" if description else "")


def facts(at, event):
    """Plain sentences, because the LLM gets only these facts and must invent no other event."""
    ids = world_events.character_ids(event)
    names = campaign_db.names_of(ids)
    faction, faction_sentence = player_line()
    lines = [faction_sentence, f"The event: {event_sentence(event, names, faction)}"]
    if at is not None:
        lines.append(f"Time: {campaign_db.game_time_text(at)}.")
    # The victim first, because a known figure is the news
    people = [person_line(profile) for profile in (campaign_db.get_character(npc_id) for npc_id in [*ids[-1:], *ids[:-1]]) if profile]
    if people:
        lines += ["Who they are:", *people]
    stance = faction_line(event["victim"]["faction"]) if event["kind"] not in world_events.RUMOR_ONLY else None
    if stance:
        lines += ["The factions:", stance]
    return "\n".join(lines)


def event_sentence(event, names, player_faction):
    if event["kind"] in world_events.RUMOR_ONLY:
        return "The one that the rumor so far tells."
    doers = world_events.name_list([names.get(doer["id"], doer["name"]) for doer in event["doers"]])
    victim = names.get(event["victim"]["id"], event["victim"]["name"])
    faction = event["victim"]["faction"]
    of = f" of {world_events.the_faction(faction)}" if faction and faction != "Neutral" else ""
    return f"{doers} of {player_faction} {'killed' if event['kind'] == 'kill' else 'captured'} {victim}{of}."


def person_line(profile):
    """The sex tells the LLM which pronouns fit, and the first sentence of the backstory why the character matters."""
    first = _FIRST_SENTENCE.match((profile.get("Backstory") or "").strip())
    return f"- {profile.get('Name', 'Unknown')} ({kind_text(profile)})" + (f": {first.group(0)}" if first else "")


def kind_text(profile):
    race = profile.get("Race", "Unknown")
    sex = reported_sex(race, profile.get("Sex", "Unknown"))
    return f"{sex.lower()} {race}" if sex.lower() in ("male", "female") else f"{race}, no sex" if sex == "Other" else race


def bounty_prompt(at, event):
    return in_language(fill_prompt("prompt_bounty_rumor.txt", facts=bounty_facts(at, event)))


def bounty_facts(at, event):
    """Plain sentences, because the LLM gets only these facts and must invent no other crime. The whole profile of the target
    goes in, because the alias must fit the character."""
    target = event["target"]
    profile = campaign_db.get_character(target["id"]) or {"Name": target["name"]}
    # A lone payer is news, while the major factions are the usual payers and naming them adds only noise
    payer = f", paid by {world_events.the_faction(event['issuers'][0])}" if len(event["issuers"]) == 1 else ""
    lines = [
        f"The bounty: {event['amount']:,} cats (the money of Kenshi) for the wanted character{payer}.",
        f"The crime ({CRIME_WORDS.get(event['crime'], event['crime'].lower())}): {event['reason']}",
        f"The wanted character: {profile.get('Name') or target['name']} ({kind_text(profile)}) of {world_events.the_faction(target['faction'])}.",
    ]
    lines += [f"{key}: {profile[key]}" for key in ("Personality", "Backstory") if profile.get(key)]
    if event["place"]:
        lines.append(f"Last seen: {event['place']}.")
    if at is not None:
        lines.append(f"Time: {campaign_db.game_time_text(at)}.")
    stance = faction_line(target["faction"])
    if stance:
        lines += ["The factions:", stance]
    return "\n".join(lines)


def bounty_reply(reply):
    """The notice, the rumor, and the alias of reply, the parsed JSON of the LLM, or None unless each holds text and the alias
    is short."""
    if not isinstance(reply, dict) or not all(isinstance(reply.get(key), str) for key in BOUNTY_PARTS):
        return None
    parts = tuple(clean(reply[key]) for key in BOUNTY_PARTS)
    return parts if all(parts) and len(parts[2].split()) <= ALIAS_WORDS else None


def faction_line(name):
    """The allies and enemies of the faction tell the LLM who cheers the news and who fears it."""
    fields = ((campaign_db.find_faction(None, name) if name else None) or {}).get("fields", {})
    parts = [f"{label}: {', '.join(fields[key])}" for key, label in (("allies", "Allies"), ("enemies", "Enemies")) if fields.get(key)]
    return f"- {name}. {'. '.join(parts)}." if parts else None


def clean(text):
    """The text of the rumor without the quotes, the bullet, or the line breaks that a model adds now and then."""
    text = " ".join((text or "").split())
    return re.sub(r"^[-*•]\s*", "", text).strip().strip('"“”').strip()
