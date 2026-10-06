"""Create a campaign filled with mock play data, so the web app and the Dialogue Library have data without a game.

The data goes in through the campaign_db calls that the chat route makes: chat threads with speakers and overhearers,
a whisper and a yell, a radiant conversation of the squad, and the memories of all threads but the newest. The deeds go in as the events of
the game, through the attribution of the server: a known figure captured, with a rumor, and one killed. The script
refuses a campaign name that is taken, so a second run cannot add the data twice. It needs no Flask, so it runs in the dev container.
"""
import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SERVER = REPO / "server"
sys.path.insert(0, str(SERVER))

from chat import chat_prompt
from core import deeds
from store import campaign_db, world_template

SQUAD, SQUAD_ID = "Nameless", "204-gamedata.base"
STICK, IZUMI, MIKSE = "h:910001", "h:910002", "h:910003"
JORGE, JOSH, ABEL = "h:920001", "h:920002", "h:920003"
# Canon characters of SSR Vanilla
RUKA, BEEP, DUST_KING, LONGEN = "u:19576-Dialogue.mod", "u:57390-rebirth.mod", "u:2849-gamedata.base", "u:56365-Dialogue.mod"

PROFILES = {
    STICK: {"Name": "Stick", "Race": "Greenlander", "Sex": "Male", "Faction": SQUAD, "OriginFaction": SQUAD, "Relation": 0,
            "Personality": "Dry humour. Counts every cat twice.", "Backstory": "Worked the door of a bar in The Hub until a debt went bad.", "SpeechQuirks": "Answers a question with a question."},
    IZUMI: {"Name": "Izumi", "Race": "Scorchlander", "Sex": "Female", "Faction": SQUAD, "OriginFaction": SQUAD, "Relation": 0,
            "Personality": "Curious and blunt.", "Backstory": "Walked out of the Great Desert with nothing but a water skin.", "SpeechQuirks": "Short sentences."},
    MIKSE: {"Name": "Mikse", "Race": "Shek", "Sex": "Male", "Faction": SQUAD, "OriginFaction": "Shek Kingdom", "Relation": 0,
            "Personality": "Quiet. Watches before he speaks.", "Backstory": "Left the Shek Kingdom after a duel he refused to finish.", "SpeechQuirks": "Rarely uses names."},
    JORGE: {"Name": "Jorge", "Race": "Greenlander", "Sex": "Male", "Faction": "Drifters", "OriginFaction": "Drifters", "Relation": 18,
            "Personality": "Practical barman with a long memory for unpaid tabs.", "Backstory": "Has run the same bar in The Hub for years.", "SpeechQuirks": "Talks about money in exact numbers."},
    JOSH: {"Name": "Dust Bandit Josh", "Race": "Greenlander", "Sex": "Male", "Faction": "Dust Bandits", "OriginFaction": "Dust Bandits", "Relation": -35,
           "Personality": "Loud and lazy. Picks fights he expects to win.", "Backstory": "Drinks on credit and never pays.", "SpeechQuirks": "Calls people by insulting nicknames."},
    ABEL: {"Name": "Paladin Abel", "Race": "Greenlander", "Sex": "Male", "Faction": "The Holy Nation", "OriginFaction": "The Holy Nation", "Relation": -5,
           "Personality": "Stern and suspicious of outsiders.", "Backstory": "Passing through The Hub on the way to Blister Hill.", "SpeechQuirks": "Ends many sentences with a blessing."},
}
NAMES = {npc_id: profile["Name"] for npc_id, profile in PROFILES.items()} | {RUKA: "Ruka", BEEP: "Beep"}
IN_SQUAD = {STICK, IZUMI, MIKSE}
MODE_TAGS = {"talk": "", "whisper": "(Whispered) ", "yell": "(Yelled) "}


def party(npc_id, name, faction):
    """A character of a game event, as the plugin sends it (EventParty in plugin/game/Context.cpp)."""
    return {"id": npc_id, "template_id": "", "name": name, "faction": faction, "player": faction == SQUAD}


def at(day, hour, minute):
    return {"day": day, "hour": hour, "minute": minute}


def kill(killers, victim, when):
    deeds.take([{"kind": "attack", "attacker": killer, "target": victim["id"], **when} for killer in killers] + [{"kind": "death", "party": victim, **when}])


def chat_thread(speaker, npc, exchanges, overhearers=(), mode="talk", memory=None):
    """exchanges are (game time, line of the squad member, reply of the NPC) triples. memory is the text that the
    distillation would write, with names, or None for a pending thread."""
    thread_id = None
    copies = [speaker, npc, *overhearers]
    members = [(npc_id, "speaker" if npc_id in (speaker, npc) else "overheard", npc_id in IN_SQUAD) for npc_id in copies]
    for when, said, reply in exchanges:
        prefix = f"[{when}] "
        thread_id = campaign_db.join_thread(thread_id, members, campaign_db.game_time(prefix))
        for npc_id in copies:
            heard = npc_id not in (speaker, npc)
            tag = "(Overheard) " if heard else ""
            to_npc, to_speaker = (f" to {NAMES[npc]}", f" to {NAMES[speaker]}") if heard else ("", "")
            lines = [(f"{prefix}{tag}{MODE_TAGS[mode]}{NAMES[speaker]}{to_npc}: {said}", speaker), (f"{prefix}{tag}{NAMES[npc]}{to_speaker}: {reply}", npc)]
            campaign_db.append_dialogue(npc_id, lines, {}, thread_id)
    if memory:
        campaign_db.set_memory(thread_id, chat_prompt.mark_names(memory, [(npc_id, NAMES[npc_id]) for npc_id in copies]), campaign_db.game_time(prefix))


def radiant(when, lines, memory):
    """lines are (npc_id, text) pairs of squad members. Each participant is a speaker of one thread, as the radiant route
    stores it."""
    participants = list(dict.fromkeys(npc_id for npc_id, _ in lines))
    prefix = f"[{when}] "
    thread_id = campaign_db.join_thread(None, [(npc_id, "speaker", True) for npc_id in participants], campaign_db.game_time(prefix))
    rows = [(f"{prefix}{NAMES[npc_id]}: {text}", npc_id) for npc_id, text in lines]
    for npc_id in participants:
        campaign_db.append_dialogue(npc_id, rows, {}, thread_id)
    campaign_db.set_memory(thread_id, chat_prompt.mark_names(memory, [(npc_id, NAMES[npc_id]) for npc_id in participants]), campaign_db.game_time(prefix))


def fill():
    for npc_id, profile in PROFILES.items():
        campaign_db.upsert_profile(npc_id, profile)
    campaign_db.upsert_profile(RUKA, {"Relation": 8})
    campaign_db.upsert_profile(BEEP, {"Relation": 30})

    chat_thread(STICK, JORGE, [
        ("Day 3, 14:05", "Any work going, barkeep?", "Depends. Can you swing a sword, or can you only drink?"),
        ("Day 3, 14:06", "Both, if the pay is right.", "Guard the door tonight. Two hundred cats, and you stop anyone who starts trouble."),
        ("Day 3, 14:07", "Deal. Who usually starts it?", "Dust Bandits, mostly. They come in thirsty and leave without paying."),
    ], overhearers=[IZUMI, ABEL], memory=(
        "Stick asked Jorge for work. Jorge doubted that Stick could fight, but offered 200 cats to guard the door of the bar"
        " for the night and stop anyone who started trouble. Stick agreed. Jorge named the Dust Bandits as the usual"
        " trouble, because they drink and leave without paying."
    ))
    chat_thread(IZUMI, JORGE, [
        ("Day 3, 14:40", "Hey, have we met?", "No, but your friend Stick took the door shift. You with him?"),
        ("Day 3, 14:41", "Unfortunately.", "Then keep him awake past midnight."),
    ], memory="Izumi asked Jorge whether they had met. Jorge said no, but knew that Izumi travelled with Stick, the new door guard. Izumi admitted it without joy. Jorge asked Izumi to keep Stick awake past midnight.")
    chat_thread(STICK, RUKA, [
        ("Day 4, 09:12", "You look like you've seen a fight or two.", "A few. We do not count the fights, only the ones we lost."),
        ("Day 4, 09:13", "Looking for work?", "Not from a door guard. Prove yourself first."),
    ], overhearers=[MIKSE], memory=(
        "Stick told Ruka that Ruka looked like a fighter. Ruka answered that they counted only the fights they lost. Stick"
        " asked whether Ruka wanted work, and Ruka refused work from a door guard until Stick proved himself."
    ))
    radiant("Day 4, 09:30", [
        (STICK, "That Ruka counts only the fights lost?"),
        (IZUMI, "Odd way to keep score."),
        (MIKSE, "An honest one."),
        (STICK, "Honest, or just short?"),
    ], memory=(
        "Stick, Izumi, and Mikse talked about Ruka, who counted only the fights that Ruka lost. Izumi found it an odd way"
        " to keep score, Mikse called it honest, and Stick asked whether the count was only short."
    ))
    chat_thread(MIKSE, BEEP, [
        ("Day 5, 20:30", "Beep, can you keep a secret?", "Beep is very good at secrets! Beep forgets most things anyway."),
        ("Day 5, 20:31", "We leave The Hub tonight.", "Beep will pack! Beep has one bag and it is empty."),
    ], mode="whisper", memory=(
        "Mikse whispered to Beep and asked Beep to keep a secret. Beep promised, and said that Beep forgets most things"
        " anyway. Mikse told Beep that the group would leave The Hub that night. Beep offered to pack, though the only bag"
        " of Beep was empty."
    ))
    chat_thread(STICK, JOSH, [
        ("Day 6, 11:00", "You owe Jorge for three drinks!", "Come and collect it yourself, door boy!"),
        ("Day 6, 11:01", "Last warning.", "Big words for a man with a borrowed sword."),
    ], overhearers=[IZUMI, MIKSE], mode="yell", memory=(
        "Stick yelled at Dust Bandit Josh that Josh owed Jorge for three drinks. Josh told Stick to come and collect it and"
        " called Stick a door boy. Stick gave a last warning, and Josh mocked the borrowed sword of Stick. The debt stayed"
        " unpaid."
    ))
    chat_thread(IZUMI, JORGE, [
        ("Day 6, 11:20", "Josh will not pay. Stick knocked him out instead.", "A sleeping bandit does not fill my till. Bring me the cats, not the story."),
    ], overhearers=[STICK])

    stick, izumi, mikse = (party(npc_id, NAMES[npc_id], SQUAD) for npc_id in (STICK, IZUMI, MIKSE))
    king = party(DUST_KING, "Dust King", "Dust Bandits")
    deeds.take([{"kind": "attack", "attacker": member, "target": DUST_KING, **at(8, 12, 0)} for member in (stick, izumi, mikse)]
               + [{"kind": "knockout", "id": DUST_KING, **at(8, 12, 1)}, {"kind": "up", "id": DUST_KING, "carried": True, **at(8, 12, 5)},
                  {"kind": "imprisonment", "party": king, **at(8, 14, 0)}])

    (capture,) = deeds.notable_events()
    campaign_db.save_rumor(None, capture["id"], "Word in the bars is that the Cage Crew of Nameless dragged the Dust King to a cage, and the Dust Bandits want them dead.",
                           "Call the squad the Cage Crew.")
    kill([izumi, mikse], party(LONGEN, "Longen", "Traders Guild"), at(9, 20, 30))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("campaign", nargs="?", default="mock", help="the name of the new campaign (default: mock)")
    name = parser.parse_args().campaign
    # The characters that create_campaign keeps, so a name such as ../x cannot reach outside the campaigns folder
    if not re.fullmatch(r"[A-Za-z0-9 _-]+", name) or name != name.strip():
        sys.exit(f"Use only letters, digits, spaces, '_', and '-' in the campaign name: {name!r}")
    folder = SERVER / "data" / "campaigns" / name
    if folder.exists():
        sys.exit(f"The campaign {name} already exists. Delete it on the Campaigns page, or give another name.")
    seed = world_template.campaign_seed("kenshi_ssr_vanilla", str(SERVER / "data" / "templates"), str(SERVER / "data" / "user_templates"))
    folder.mkdir(parents=True)
    campaign_db.open_campaign(str(folder), lambda: seed)
    campaign_db.note_faction(SQUAD_ID, SQUAD, is_player=True)
    fill()
    threads = campaign_db.threads()
    print(f"Created the campaign {name} with {len(threads)} chat threads, {sum(thread['memory'] is not None for thread in threads)} of them with a memory, {len(campaign_db.notables())} notable events, and {len(campaign_db.rumors())} rumors.")
    print("Switch to it on the Campaigns page of the web app.")


if __name__ == "__main__":
    main()
