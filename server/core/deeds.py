"""Which known figures the player's squad killed or captured, from the events of the game.

The plugin keeps no state, so its hooks stay light: it sends the attacks of the player's faction, and the knockouts,
wake-ups, deaths, and imprisonments of everyone. The server keeps the events of each character in memory and replays them
at a death or an imprisonment. Kenshi gives no last hit, so each attacker counts as a killer or as a captor.
"""
import logging
import threading

from core import state
from core.pipe import send_to_pipe
from store import campaign_db

ATTACK_WINDOW_MINUTES = 180
# A radiant conversation waits this long after a fight, so its participants do not talk about other things right after a battle
FIGHT_QUIET_MINUTES = 180
ENDS = ("death", "imprisonment")
# The rumor is the only account of these deeds, so they name no characters and no factions
RUMOR_ONLY = ("custom", "auto")

_lock = threading.Lock()
_histories = {}
_newest = None
_campaign = None
_expired = set()


def take(events):
    """Reads the events of a report in their order, and stores the deeds that they make."""
    for event in events or []:
        logging.debug(f"EVENT: {event}")
        at = game_minutes(event)
        if at is None:
            continue
        ended = _attribute(event, at)
        if ended:
            try:
                _store(event["kind"], event["party"], ended, at)
            except campaign_db.CampaignUnavailable:
                pass  # The deed is lost, but the report must still update the player's context


def game_minutes(event):
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


def fought_recently(npc_ids, ctx):
    """Whether one of the characters attacked someone, or was knocked out, within FIGHT_QUIET_MINUTES before the game time of
    the context. The plugin sends no attack on a character of the player's faction, so taking hits alone is no fight."""
    now = game_minutes(ctx)
    if now is None:
        return False
    with _lock:
        if _campaign != state.ACTIVE_CAMPAIGN:
            return False
        for history in _histories.values():
            for at, event in history:
                if now - at > FIGHT_QUIET_MINUTES:
                    continue
                if event["kind"] == "attack" and (event.get("attacker") or {}).get("id") in npc_ids:
                    return True
                if event["kind"] == "knockout" and event.get("id") in npc_ids:
                    return True
    return False


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
    """The target of an open bounty counts as a known figure, so its kill or capture by the squad ends the bounty."""
    victim_id = canon_id(victim)
    if victim.get("player"):
        return
    wanted = [deed for _, deed in open_bounties() if deed["target"]["id"] == victim_id]
    if not victim_id.startswith("u:") and not wanted:
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
        for bounty in wanted:
            end_bounty(bounty)


def bounty_statuses(rows):
    """The status of each bounty deed among rows, the (id, game_time, deed) of campaign_db.notables(), by its ID. A kill or a
    capture of its target that the squad made after it ends a bounty, so the cull of that deed opens the bounty again."""
    now = game_minutes(state.PLAYER_CONTEXT)
    ends = {}
    for notable_id, _, deed in rows:
        if deed["deed"] in ("kill", "capture"):
            ends.setdefault(deed["victim"]["id"], []).append((notable_id, deed["deed"]))
    statuses = {}
    for notable_id, _, deed in rows:
        if deed["deed"] != "bounty":
            continue
        end = max((end for end in ends.get(deed["target"]["id"], []) if end[0] > notable_id), default=None)
        if end:
            statuses[notable_id] = "Killed" if end[1] == "kill" else "Captured"
        else:
            statuses[notable_id] = "Expired" if now is not None and now > deed["expires"] else "Open"
    return statuses


def open_bounties():
    """Each bounty deed with the status Open, as (notable ID, deed)."""
    rows = campaign_db.notables()
    statuses = bounty_statuses(rows)
    return [(notable_id, deed) for notable_id, _, deed in rows if statuses.get(notable_id) == "Open"]


def told_rumors():
    """The rumors that NPCs tell, oldest first: each but the rumor of a bounty that is no longer open, because the kill or
    the capture of its target has a rumor of its own, and a closed bounty calls no one to hunt."""
    statuses = bounty_statuses(campaign_db.notables())
    return [rumor for rumor in campaign_db.rumors() if statuses.get(rumor["notable_id"], "Open") == "Open"]


def end_bounty(deed):
    """Gives the target's squad of a bounty that is no longer open back to the game: the plugin takes it off the world map,
    and clears the persistent flag that SSR set. A squad that another open bounty holds stays as it is."""
    if any(other["squad"] == deed["squad"] for _, other in open_bounties()):
        return
    send_to_pipe(f"END_BOUNTY: {deed['squad']}|{0 if deed['persistent'] else 1}")


def end_expired_bounties():
    """Ends each bounty that expired since the last call. A load can open an expired bounty again, and it can then expire again."""
    global _expired
    rows = campaign_db.notables()
    statuses = bounty_statuses(rows)
    expired = {(state.ACTIVE_CAMPAIGN, notable_id): deed for notable_id, _, deed in rows if statuses.get(notable_id) == "Expired"}
    for key in expired.keys() - _expired:
        end_bounty(expired[key])
    _expired = set(expired)


def notable_events():
    """Each notable event, newest first, as a dict with its ID, kind ("kill", "capture", "custom", "auto", or "bounty"), game
    time, line, and rumor ID, and the status of a bounty.
    The line names each character by its current name, so a renamed squad member shows with its new name."""
    rows = campaign_db.notables()
    names = campaign_db.names_of({npc_id for _, _, deed in rows for npc_id in character_ids(deed)})
    faction = (campaign_db.player_faction() or {}).get("name")
    rumors = {rumor["notable_id"]: rumor["id"] for rumor in campaign_db.rumors()}
    statuses = bounty_statuses(rows)
    return [{"id": notable_id, "kind": deed["deed"], "time": campaign_db.game_time_text(at) if at is not None else "-", "line": notable_line(deed, names, faction), "rumor": rumors.get(notable_id),
             **({"status": statuses[notable_id]} if notable_id in statuses else {})}
            for notable_id, at, deed in rows]


def character_deeds():
    """The known figures that each squad member killed or captured, oldest first, as text for Campaign Canon."""
    deeds = [deed for _, _, deed in campaign_db.notables() if deed["deed"] in ("kill", "capture")]
    names = campaign_db.names_of({deed["victim"]["id"] for deed in deeds})
    summary = {}
    for deed in reversed(deeds):
        line = f"{'Killed' if deed['deed'] == 'kill' else 'Captured'} {names.get(deed['victim']['id'], deed['victim']['name'])}"
        for doer in deed["doers"]:
            summary.setdefault(doer["id"], []).append(line)
    return summary


def character_ids(deed):
    if deed["deed"] in RUMOR_ONLY:
        return []
    if deed["deed"] == "bounty":
        return [deed["target"]["id"]]
    return [doer["id"] for doer in deed["doers"]] + [deed["victim"]["id"]]


def notable_line(deed, names, player_faction):
    """names maps an npc_id to its current name; a character with no profile keeps the name of the deed. A bounty is no
    deed of the squad, so its wanted notice stands in for the line."""
    if deed["deed"] == "bounty":
        return deed.get("notice") or "Unknown"
    if deed["deed"] == "custom":
        return "Written by you"
    if deed["deed"] == "auto":
        count = len(deed["threads"])
        return f"From {count} conversation{'' if count == 1 else 's'}"
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
