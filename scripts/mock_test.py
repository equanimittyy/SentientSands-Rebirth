"""Create a campaign filled with mock play data, so the web app and the Dialogue Library have data without a game.

The data goes in through the campaign_db calls that the chat route makes: chat threads with speakers and overhearers,
a whisper and a yell, one banter, events, and rumors. The script refuses a campaign name that is taken, so a second run
cannot add the data twice. It needs no Flask, so it runs in the dev container.
"""
import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SERVER = REPO / "server"
sys.path.insert(0, str(SERVER / "scripts"))

import campaign_db
import world_template

SQUAD = "Nameless"
STICK, IZUMI, MIKSE = "h:910001", "h:910002", "h:910003"
JORGE, JOSH, ABEL = "h:920001", "h:920002", "h:920003"
# Canon characters of SSR Vanilla
RUKA, BEEP = "u:19576-Dialogue.mod", "u:57390-rebirth.mod"

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
FACTIONS = {npc_id: profile["Faction"] for npc_id, profile in PROFILES.items()} | {RUKA: "Shek Kingdom", BEEP: "Drifters"}
IN_SQUAD = {STICK, IZUMI, MIKSE}
MODE_TAGS = {"talk": "", "whisper": "(Whispered) ", "yell": "(Yelled) "}


def party(npc_id):
    """An actor or a target of an event line, as record_event_to_history writes it."""
    return f"{NAMES[npc_id]} (Player's Squad: {SQUAD})" if npc_id in IN_SQUAD else f"{NAMES[npc_id]} ({FACTIONS[npc_id]})"


def chat_thread(speaker, npc, exchanges, overhearers=(), mode="talk", town="The Hub"):
    """exchanges are (game time, line of the squad member, reply of the NPC) triples."""
    thread_id = None
    for when, said, reply in exchanges:
        prefix = f"[{when}] "
        copies = [speaker, npc, *overhearers]
        members = [(npc_id, "speaker" if npc_id in (speaker, npc) else "overheard", npc_id in IN_SQUAD) for npc_id in copies]
        thread_id = campaign_db.join_thread(thread_id, members, campaign_db.game_time(prefix))
        for npc_id in copies:
            heard = npc_id not in (speaker, npc)
            tag = "(Overheard) " if heard else ""
            to_npc, to_speaker = (f" to {NAMES[npc]}", f" to {NAMES[speaker]}") if heard else ("", "")
            lines = [(f"{prefix}{tag}{MODE_TAGS[mode]}{NAMES[speaker]}{to_npc}: {said}", speaker), (f"{prefix}{tag}{NAMES[npc]}{to_speaker}: {reply}", npc)]
            campaign_db.append_dialogue(npc_id, lines, {}, thread_id)
        campaign_db.add_event(f"[{when}] [CHAT] {party(speaker)} -> {party(npc)} @ {town}: {said}")
        campaign_db.add_event(f"[{when}] [CHAT] {party(npc)} -> {party(speaker)} @ {town}: {reply}")


def banter(lines, town="The Hub"):
    """lines are (game time, npc_id, text) triples. Each NPC of the banter stores every line, with no thread."""
    rows = [(f"[{when}] {NAMES[npc_id]}: {text}", npc_id) for when, npc_id, text in lines]
    for npc_id in {npc_id for _, npc_id, _ in lines}:
        campaign_db.append_dialogue(npc_id, rows, {})
    for when, npc_id, text in lines:
        campaign_db.add_event(f"[{when}] [BANTER] {party(npc_id)} -> Nearby @ {town}: {text}")


def fill():
    for npc_id, profile in PROFILES.items():
        campaign_db.upsert_profile(npc_id, profile)
    campaign_db.upsert_profile(RUKA, {"Relation": 8})
    campaign_db.upsert_profile(BEEP, {"Relation": 30})

    chat_thread(STICK, JORGE, [
        ("Day 3, 14:05", "Any work going, barkeep?", "Depends. Can you swing a sword, or can you only drink?"),
        ("Day 3, 14:06", "Both, if the pay is right.", "Guard the door tonight. Two hundred cats, and you stop anyone who starts trouble."),
        ("Day 3, 14:07", "Deal. Who usually starts it?", "Dust Bandits, mostly. They come in thirsty and leave without paying."),
    ], overhearers=[IZUMI, ABEL])
    chat_thread(IZUMI, JORGE, [
        ("Day 3, 14:40", "Hey, have we met?", "No, but your friend Stick took the door shift. You with him?"),
        ("Day 3, 14:41", "Unfortunately.", "Then keep him awake past midnight."),
    ])
    chat_thread(STICK, RUKA, [
        ("Day 4, 09:12", "You look like you've seen a fight or two.", "A few. We do not count the fights, only the ones we lost."),
        ("Day 4, 09:13", "Looking for work?", "Not from a door guard. Prove yourself first."),
    ], overhearers=[MIKSE])
    banter([
        ("Day 4, 09:30", RUKA, "Your ale tastes of rust."),
        ("Day 4, 09:30", JORGE, "Everything here does."),
        ("Day 4, 09:31", RUKA, "Then why do they keep drinking it?"),
        ("Day 4, 09:31", JORGE, "Because it is the only ale for a day's walk."),
    ])
    campaign_db.add_event(f"[Day 5, 18:02] [trade] {party(MIKSE)} -> {party(JORGE)} @ The Hub: Bought Dried Meat")
    chat_thread(MIKSE, BEEP, [
        ("Day 5, 20:30", "Beep, can you keep a secret?", "Beep is very good at secrets! Beep forgets most things anyway."),
        ("Day 5, 20:31", "We leave The Hub tonight.", "Beep will pack! Beep has one bag and it is empty."),
    ], mode="whisper")
    chat_thread(STICK, JOSH, [
        ("Day 6, 11:00", "You owe Jorge for three drinks!", "Come and collect it yourself, door boy!"),
        ("Day 6, 11:01", "Last warning.", "Big words for a man with a borrowed sword."),
    ], overhearers=[IZUMI, MIKSE], mode="yell")
    campaign_db.add_event(f"[Day 6, 11:02] [combat] {party(JOSH)} -> {party(STICK)} @ The Hub: Initiated attack")
    campaign_db.add_event(f"[Day 6, 11:03] [knockout] Unknown -> {party(JOSH)} @ The Hub: Was knocked unconscious")
    campaign_db.add_event(f"[Day 6, 11:08] [healing] {party(IZUMI)} -> {party(STICK)} @ The Hub: Applying first aid")
    chat_thread(IZUMI, JORGE, [
        ("Day 6, 11:20", "Josh will not pay. Stick knocked him out instead.", "A sleeping bandit does not fill my till. Bring me the cats, not the story."),
    ], overhearers=[STICK])

    campaign_db.add_rumor("- [Day 5, 00:00] [RUMOR: Dust Bandits drink in The Hub without paying, and the barman wants them gone.]")
    campaign_db.add_rumor("- [Day 6, 12:00] [RUMOR: A door guard at The Hub knocked out a Dust Bandit over a bar tab.]")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("campaign", nargs="?", default="mock", help="the name of the new campaign (default: mock)")
    name = parser.parse_args().campaign
    # The characters that create_campaign keeps, so a name such as ../x cannot reach outside the campaigns folder
    if not re.fullmatch(r"[A-Za-z0-9 _-]+", name) or name != name.strip():
        sys.exit(f"Use only letters, digits, spaces, '_', and '-' in the campaign name: {name!r}")
    folder = SERVER / "campaigns" / name
    if folder.exists():
        sys.exit(f"The campaign {name} already exists. Delete it on the Campaigns page, or give another name.")
    seed = world_template.campaign_seed("kenshi_ssr_vanilla", str(SERVER / "world_templates"), str(SERVER / "user" / "world_templates"))
    folder.mkdir(parents=True)
    campaign_db.open_campaign(str(folder), lambda: seed)
    fill()
    print(f"Created the campaign {name} with {len(campaign_db.threads())} chat threads, {len(campaign_db.events())} events, and {len(campaign_db.rumors())} rumors.")
    print("Switch to it on the Campaigns page of the web app.")


if __name__ == "__main__":
    main()
