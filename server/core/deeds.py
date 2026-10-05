"""Which known figures the player's squad killed or captured, from the events of the game.

The plugin keeps no state, so its hooks stay light: it sends the attacks of the player's faction, and the knockouts,
wake-ups, deaths, and imprisonments of everyone. The server keeps the events of each character in memory and replays them
at a death or an imprisonment. Kenshi gives no last hit, so each attacker counts as a killer or as a captor.
"""
import logging
import threading

from core import state
from store import campaign_db

ATTACK_WINDOW_MINUTES = 180
ENDS = ("death", "imprisonment")

_lock = threading.Lock()
_histories = {}
_newest = None
_campaign = None


def take(events):
    """Reads the events of a report in their order, and stores the deeds that they make."""
    for event in events or []:
        logging.debug(f"EVENT: {event}")
        at = _minutes(event)
        if at is None:
            continue
        ended = _attribute(event, at)
        if ended:
            try:
                _store(event["kind"], event["party"], ended, at)
            except campaign_db.CampaignUnavailable:
                pass  # The deed is lost, but the report must still update the player's context


def _minutes(event):
    try:
        at = int(event["day"]) * 1440 + int(event["hour"]) * 60 + int(event["minute"])
    except (KeyError, TypeError, ValueError):
        return None
    # The game clock reads Day 0, 00:00 until it holds a real time, and that time would look like a load
    return at or None


def _attribute(event, at):
    """Adds the event to the history of its character. Returns the attackers of a death or an imprisonment, else None."""
    global _newest, _campaign
    kind = event.get("kind")
    if kind == "attack":
        key = event.get("target")
    elif kind in ENDS:
        key = (event.get("party") or {}).get("id")
    else:
        key = event.get("id")
    if not key or kind not in ("attack", "knockout", "up", *ENDS):
        return None
    with _lock:
        if _campaign != state.ACTIVE_CAMPAIGN:
            _histories.clear()
            _newest, _campaign = None, state.ACTIVE_CAMPAIGN
        # The game time goes back only at a load, and the play after the loaded time did not happen in the loaded save
        if _newest is not None and at < _newest:
            _rewind(at)
        _newest = at
        history = _histories.setdefault(key, [])
        history.append((at, event))
        return _attackers(history) if kind in ENDS else None


def _rewind(at):
    dropped = 0
    for key in list(_histories):
        kept = [entry for entry in _histories[key] if entry[0] <= at]
        dropped += len(_histories[key]) - len(kept)
        if kept:
            _histories[key] = kept
        else:
            del _histories[key]
    logging.info(f"DEEDS: The game time went back to {campaign_db.game_time_text(at)}, so a save was loaded. Dropped {dropped} events after it.")


def _attackers(history):
    """The attackers of the death or imprisonment at the end of history, from the events since the one before it."""
    end = history[-1][0]
    start = len(history) - 1
    while start > 0 and history[start - 1][1]["kind"] not in ENDS:
        start -= 1
    attackers, marked = {}, False
    for at, event in history[start:-1]:
        if event["kind"] == "attack":
            attacker = event.get("attacker") or {}
            if attacker.get("id") and attacker.get("player"):
                attackers[attacker["id"]] = (attacker, at)
        elif event["kind"] == "knockout":
            marked = True
        # The pickup by a captor also sets another prone state, so only an up that is not carried ends the knockout
        elif event["kind"] == "up" and not event.get("carried"):
            marked = False
            attackers = {key: (attacker, at) for key, (attacker, _) in attackers.items()}
    return [attacker for attacker, at in attackers.values() if marked or end - at <= ATTACK_WINDOW_MINUTES]


def canon_id(party):
    """The npc_id of a generic character whose template is a canon character is the npc_id of that character, as for a
    context (adopt_canon)."""
    npc_id, template_id = party.get("id", ""), party.get("template_id")
    if npc_id.startswith("h:") and template_id and campaign_db.character_exists(f"u:{template_id}"):
        return f"u:{template_id}"
    return npc_id


def _store(kind, victim, attackers, at):
    victim_id = canon_id(victim)
    if victim.get("player") or not victim_id.startswith("u:"):
        return
    deed = "kill" if kind == "death" else "capture"
    doers = campaign_db.add_deed(
        deed,
        [(canon_id(attacker), attacker.get("name", "")) for attacker in attackers],
        {"npc_id": victim_id, "name": victim.get("name", ""), "faction": victim.get("faction", "")},
        at,
    )
    if doers:
        logging.debug(f"DEEDS: {', '.join(name for _, name in doers)} {'killed' if deed == 'kill' else 'captured'} {victim.get('name', '')} ({victim_id}) at {campaign_db.game_time_text(at)}")


def notable_events():
    """Each notable event, newest first, as a dict with its ID, kind ("kill", "capture", or "custom"), game time, line, and
    rumor ID.
    The line names each character by its current name, so a renamed squad member shows with its new name."""
    rows = campaign_db.notables()
    names = campaign_db.names_of({npc_id for _, _, deed in rows for npc_id in character_ids(deed)})
    faction = (campaign_db.player_faction() or {}).get("name")
    rumors = {rumor["notable_id"]: rumor["id"] for rumor in campaign_db.rumors()}
    return [{"id": notable_id, "kind": deed["deed"], "time": campaign_db.game_time_text(at) if at is not None else "-", "line": notable_line(deed, names, faction), "rumor": rumors.get(notable_id)}
            for notable_id, at, deed in rows]


def character_deeds():
    """The known figures that each squad member killed or captured, oldest first, as text for Campaign Canon."""
    deeds = [deed for _, _, deed in campaign_db.notables() if deed["deed"] != "custom"]
    names = campaign_db.names_of({deed["victim"]["id"] for deed in deeds})
    summary = {}
    for deed in reversed(deeds):
        line = f"{'Killed' if deed['deed'] == 'kill' else 'Captured'} {names.get(deed['victim']['id'], deed['victim']['name'])}"
        for doer in deed["doers"]:
            summary.setdefault(doer["id"], []).append(line)
    return summary


def character_ids(deed):
    if deed["deed"] == "custom":
        return []
    return [doer["id"] for doer in deed["doers"]] + [deed["victim"]["id"]]


def notable_line(deed, names, player_faction):
    """names maps an npc_id to its current name; a character with no profile keeps the name of the deed."""
    if deed["deed"] == "custom":
        return deed["text"]
    doers = name_list([names.get(doer["id"], doer["name"]) for doer in deed["doers"]])
    victim = names.get(deed["victim"]["id"], deed["victim"]["name"])
    verb = "killed" if deed["deed"] == "kill" else "captured"
    return f"{doers} of {player_faction} {verb} {victim}." if player_faction else f"{doers} {verb} {victim}."


def name_list(names):
    if len(names) < 3:
        return " and ".join(names)
    return f"{', '.join(names[:-1])}, and {names[-1]}"


def the_faction(faction):
    return faction if faction.startswith("The ") else f"the {faction}"
