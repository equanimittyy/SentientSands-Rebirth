"""The bounties that SSR puts on NPCs through the bounty system of the game.

The server rolls each bounty and the plugin only applies it, so the roll runs in the unit tests of the dev container. A
placed bounty is a deed of the kind "bounty" (core/deeds.py).
"""
import json
import logging
import os
import random
import time

from core import deeds, state
from core.paths import DEFAULTS_DIR
from core.pipe import send_to_pipe
from core.settings import load_settings
from store import campaign_db

# The order of CrimeEnum in KenshiLib after CRIME_NONE, so the plugin takes CRIMES[i] as the enum value i + 1
CRIMES = (
    "ENSLAVING", "LOCKPICKING", "STEALING", "MURDER", "ASSAULT", "ASSAULT_VIP", "SLAVE_FREEING", "SMUGGLING",
    "TERRORISM", "LOOTING", "TRESPASSING", "ESCAPE_PRISON", "FENCING", "FARM_EATING", "KIDNAPPING", "UNIFORM_THEFT",
)
# The Holy Nation, the United Cities, and the Shek Kingdom by game ID: the law of each of them sets the bounty at one price
ISSUERS = {"1083-gamedata.base": "The Holy Nation", "defaultEmpireFactionSID": "United Cities", "11624-Dialogue (10).mod": "Shek Kingdom"}
# A fixed list of the bandit factions whose generic members can get a bounty, chosen by hand from the Kenshi wiki and the game data
TARGETS = {
    "56595-Dialogue.mod": "Band of Bones",
    "42257-rebirth.mod": "Berserkers",
    "16860-gamedata.base": "Bloodraiders",
    "2757468-Swamps Expanded.mod": "Blue Cleavers",
    "2758392-Bandits Expansion.mod": "Desolate Plunderers",
    "2757432-Dune Rebels.mod": "Dune Renegades",
    "200-gamedata.base": "Dust Bandits",
    "96175-rebirth.mod": "Grass Pirates",
    "2757458-Swamps Expanded.mod": "Green Katanas",
    "2757329-Hill Bandits.mod": "Hill Marauders",
    "2757451-Hook Rebels.mod": "Hook Raiders",
    "51357-rebirth.mod": "Kral's Chosen",
    "54297-rebirth.mod": "Rebel Farmers",
    "51652-rebirth.mod": "Red Sabres",
    "1085-gamedata.base": "Sand Ninjas",
    "95512-rebirth.mod": "Scavengers",
    "42235-rebirth.mod": "Shrieking Bandits",
    "63028-Dialogue.mod": "Skin Bandits",
    "1305-gamedata.base": "Starving Bandits",
    "5065358-Universal Wasteland Expansion.mod": "Starving Vagrants",
    "51638-rebirth.mod": "Swamp Ninjas",
    "2757403-Swamp Bandits.mod": "Swamp Ruffians",
    "1533849-Northern Bandits Expanded.mod": "The Bastards",
    "1533851-Northern Bandits Expanded.mod": "The Deluged",
    "96261-rebirth.mod": "The Gorrillo Bandits",
    "96156-rebirth.mod": "Vagrants",
    "1532482-__May 18 2.mod": "Yabuta Outlaws",
}
with open(os.path.join(DEFAULTS_DIR, "bounty_reasons.json"), encoding="utf-8") as f:
    REASONS = json.load(f)
AMOUNTS = range(2000, 15001, 100)
# The chance of an amount halves with each 1,200 cats above the lowest, so most bounties are small and about 1 in 100
# reaches 10,000 cats, where the game never lets it expire and the skill bonus is at its highest
AMOUNT_WEIGHTS = [0.5 ** ((amount - AMOUNTS[0]) / 1200) for amount in AMOUNTS]
# StatsEnumerated values of the 16 combat skills from the probe; 36 is precision shooting (STAT_FRIENDLY_FIRE)
COMBAT_STATS = (1, 18, 21, 24, 2, 19, 32, 30, 25, 26, 27, 28, 29, 34, 35, 36)
CATS_PER_LEVEL = 500
MAX_LEVEL = 20
JITTER = 2

_last_scan = time.monotonic()
_pending = None


def roll(candidates, taken, amount=None, rng=random):
    """A bounty on one of the candidates, the dicts that the plugin posts, whose faction is a target faction and whose npc_id
    is not in taken. None without such a candidate. amount None rolls the amount."""
    pool = [candidate for candidate in candidates if candidate.get("faction_id") in TARGETS and candidate.get("npc_id") not in taken]
    if not pool:
        return None
    reason = rng.choice(REASONS)
    amount = amount or rng.choices(AMOUNTS, AMOUNT_WEIGHTS)[0]
    return {"target": rng.choice(pool), "reason": reason["text"], "crime": reason["crime"], "amount": amount, "bonuses": skill_bonuses(amount, rng)}


def skill_bonuses(amount, rng=random):
    """The bonus of each combat skill by its StatsEnumerated index. Each skill gets a jitter of its own, so no two targets
    get the same flat bonus."""
    level = min(amount / CATS_PER_LEVEL, MAX_LEVEL)
    return {stat: max(0, round(level + rng.triangular(-JITTER, JITTER, 0))) for stat in COMBAT_STATS}


def due(seconds_since_scan, minutes, open_count, max_open):
    return max_open > 0 and open_count < max_open and seconds_since_scan >= minutes * 60


def tick():
    """Ends the bounties that expired, and asks the plugin for the candidates when the bounty timer passed and fewer bounties
    are open than the setting allows. The timer restarts at each scan, also at one that finds no candidate."""
    global _last_scan
    settings = load_settings()
    try:
        deeds.end_expired_bounties()
        open_count = len(deeds.open_bounties())
    except campaign_db.CampaignUnavailable:
        return
    if due(time.monotonic() - _last_scan, settings["radiant_bounty_minutes"], open_count, settings["max_open_bounties"]):
        _last_scan = time.monotonic()
        logging.info("BOUNTY: Asking the game for the candidates of a bounty.")
        send_to_pipe("BOUNTY_SCAN:")


def place(candidates):
    """Rolls a bounty on one of the candidates of a scan, and sends it to the plugin."""
    try:
        taken = {deed["target"]["id"] for _, deed in deeds.open_bounties()}
    except campaign_db.CampaignUnavailable:
        return
    bounty = roll(candidates, taken)
    if bounty:
        send(bounty)
    else:
        logging.info(f"BOUNTY: No candidate among the {len(candidates)} loaded characters.")


def send(bounty):
    """PLACE_BOUNTY carries serial|crime|amount|issuers|bonuses, and the plugin finds the target by the serial of its handle."""
    global _pending
    _pending = (state.ACTIVE_CAMPAIGN, bounty)
    target = bounty["target"]
    logging.info(f"BOUNTY: Placing {bounty['amount']} cats on {target['name']} ({target['npc_id']}) of the {target['faction']} for {bounty['crime']}.")
    send_to_pipe("PLACE_BOUNTY: " + "|".join([
        target["npc_id"].removeprefix("h:"), str(CRIMES.index(bounty["crime"]) + 1), str(bounty["amount"]), ",".join(ISSUERS),
        ",".join(f"{stat}:{bonus}" for stat, bonus in bounty["bonuses"].items()),
    ]))


def take_pending(npc_id):
    """The roll that the last PLACE_BOUNTY sent for the npc_id, or None, also after a campaign switch. The result of a
    placement takes it, so a second result stores nothing."""
    global _pending
    pending, _pending = _pending, None
    if not pending or pending[0] != state.ACTIVE_CAMPAIGN or pending[1]["target"]["npc_id"] != npc_id:
        return None
    return pending[1]


def store(bounty, name, result):
    """Stores the deed of a bounty that the plugin placed, with the result of the plugin and the stored name of the target.
    Returns its notable event ID."""
    target, context = bounty["target"], result["context"]
    held = next((deed for _, deed in deeds.open_bounties() if deed["squad"] == result["squad"]), None)
    notable_id = campaign_db.add_bounty_deed({
        "target": {"id": target["npc_id"], "name": name, "faction": target["faction"]},
        "reason": bounty["reason"],
        "crime": bounty["crime"],
        "amount": bounty["amount"],
        "issuers": result["issuers"],
        "place": target["place"],
        "expires": int(result["expires"]),
        "squad": result["squad"],
        # SSR made the squad of another open bounty persistent, so the flag of that bounty tells what the game set
        "persistent": held["persistent"] if held else bool(result["persistent"]),
    }, deeds.game_minutes(context))
    state.LAST_BOUNTY = time.monotonic()
    return notable_id
