"""Which known figures the player's squad killed or captured, from the game events.

The plugin keeps no state, so its hooks stay light: it sends the attacks of the player's faction, and the knockouts,
wake-ups, deaths, and imprisonments of everyone. The server keeps the game events of each character in memory and replays them
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
# The rumor is the only account of these events, so they name no characters and no factions
RUMOR_ONLY = ("custom", "auto")

_lock = threading.Lock()
_histories = {}
_newest = None
_campaign = None
_expired = set()


def take(game_events):
    """Reads the game events of a report in their order, and stores the events that they make."""
    for game_event in game_events or []:
        logging.debug(f"GAME EVENT: {game_event}")
        at = game_minutes(game_event)
        if at is None:
            continue
        ended = _attribute(game_event, at)
        if ended:
            try:
                _store(game_event["kind"], game_event["party"], ended, at)
            except campaign_db.CampaignUnavailable:
                pass  # The event is lost, but the report must still update the player's context


def game_minutes(event):
    try:
        at = int(event["day"]) * 1440 + int(event["hour"]) * 60 + int(event["minute"])
    except (KeyError, TypeError, ValueError):
        return None
    # The game clock reads Day 0, 00:00 until it holds a real time, and that time would look like a load
    return at or None


def _attribute(game_event, at):
    """Adds the game event to the history of its character. Returns the attackers of a death or an imprisonment, else None."""
    global _newest, _campaign
    kind = game_event.get("kind")
    if kind == "attack":
        key = game_event.get("target")
    elif kind in ENDS:
        key = (game_event.get("party") or {}).get("id")
    else:
        key = game_event.get("id")
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
        history.append((at, game_event))
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
            for at, game_event in history:
                if now - at > FIGHT_QUIET_MINUTES:
                    continue
                if game_event["kind"] == "attack" and (game_event.get("attacker") or {}).get("id") in npc_ids:
                    return True
                if game_event["kind"] == "knockout" and game_event.get("id") in npc_ids:
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
    logging.info(f"EVENTS: The game time went back to {campaign_db.game_time_text(at)}, so a save was loaded. Dropped {dropped} game events after it.")


def _attackers(history):
    """The attackers of the death or imprisonment at the end of history, from the game events since the one before it."""
    end = history[-1][0]
    start = len(history) - 1
    while start > 0 and history[start - 1][1]["kind"] not in ENDS:
        start -= 1
    attackers, marked = {}, False
    for at, game_event in history[start:-1]:
        if game_event["kind"] == "attack":
            attacker = game_event.get("attacker") or {}
            if attacker.get("id") and attacker.get("player"):
                attackers[attacker["id"]] = (attacker, at)
        elif game_event["kind"] == "knockout":
            marked = True
        # The pickup by a captor also sets another prone state, so only an up that is not carried ends the knockout
        elif game_event["kind"] == "up" and not game_event.get("carried"):
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
    wanted = [bounty for _, bounty in open_bounties() if bounty["target"]["id"] == victim_id]
    if not victim_id.startswith("u:") and not wanted:
        return
    event_kind = "kill" if kind == "death" else "capture"
    doers = campaign_db.add_event(
        event_kind,
        [(canon_id(attacker), attacker.get("name", "")) for attacker in attackers],
        {"npc_id": victim_id, "name": victim.get("name", ""), "faction": victim.get("faction", "")},
        at,
    )
    if doers:
        logging.debug(f"EVENTS: {', '.join(name for _, name in doers)} {'killed' if event_kind == 'kill' else 'captured'} {victim.get('name', '')} ({victim_id}) at {campaign_db.game_time_text(at)}")
        for bounty in wanted:
            end_bounty(bounty)


def bounty_statuses(rows):
    """The status of each bounty event among rows, the (id, game_time, event) of campaign_db.events(), by its ID. A kill or a
    capture of its target that the squad made after it ends a bounty, so the cull of that event opens the bounty again."""
    now = game_minutes(state.PLAYER_CONTEXT)
    ends = {}
    for event_id, _, event in rows:
        if event["kind"] in ("kill", "capture"):
            ends.setdefault(event["victim"]["id"], []).append((event_id, event["kind"]))
    statuses = {}
    for event_id, _, event in rows:
        if event["kind"] != "bounty":
            continue
        end = max((end for end in ends.get(event["target"]["id"], []) if end[0] > event_id), default=None)
        if end:
            statuses[event_id] = "Killed" if end[1] == "kill" else "Captured"
        else:
            statuses[event_id] = "Expired" if now is not None and now > event["expires"] else "Open"
    return statuses


def open_bounties():
    """Each bounty event with the status Open, as (event ID, event)."""
    rows = campaign_db.events()
    statuses = bounty_statuses(rows)
    return [(event_id, event) for event_id, _, event in rows if statuses.get(event_id) == "Open"]


def told_rumors():
    """The rumors that NPCs tell, oldest first: each but the rumor of a bounty that is no longer open, because the kill or
    the capture of its target has a rumor of its own, and a closed bounty calls no one to hunt."""
    statuses = bounty_statuses(campaign_db.events())
    return [rumor for rumor in campaign_db.rumors() if statuses.get(rumor["event_id"], "Open") == "Open"]


def end_bounty(event):
    """Gives the target's squad of a bounty that is no longer open back to the game: the plugin takes it off the world map,
    and clears the persistent flag that SSR set. A squad that another open bounty holds stays as it is."""
    if any(other["squad"] == event["squad"] for _, other in open_bounties()):
        return
    send_to_pipe(f"END_BOUNTY: {event['squad']}|{0 if event['persistent'] else 1}")


def end_expired_bounties():
    """Ends each bounty that expired since the last call. A load can open an expired bounty again, and it can then expire again."""
    global _expired
    rows = campaign_db.events()
    statuses = bounty_statuses(rows)
    expired = {(state.ACTIVE_CAMPAIGN, event_id): event for event_id, _, event in rows if statuses.get(event_id) == "Expired"}
    for key in expired.keys() - _expired:
        end_bounty(expired[key])
    _expired = set(expired)


def events():
    """Each event, newest first, as a dict with its ID, kind ("kill", "capture", "custom", "auto", or "bounty"), game
    time, line, and rumor ID, and the status of a bounty.
    The line names each character by its current name, so a renamed squad member shows with its new name."""
    rows = campaign_db.events()
    names = campaign_db.names_of({npc_id for _, _, event in rows for npc_id in character_ids(event)})
    faction = (campaign_db.player_faction() or {}).get("name")
    rumors = {rumor["event_id"]: rumor["id"] for rumor in campaign_db.rumors()}
    statuses = bounty_statuses(rows)
    return [{"id": event_id, "kind": event["kind"], "time": campaign_db.game_time_text(at) if at is not None else "-", "line": event_line(event, names, faction), "rumor": rumors.get(event_id),
             **({"status": statuses[event_id]} if event_id in statuses else {})}
            for event_id, at, event in rows]


def character_events():
    """The known figures that each squad member killed or captured, oldest first, as text for Campaign Canon."""
    events = [event for _, _, event in campaign_db.events() if event["kind"] in ("kill", "capture")]
    names = campaign_db.names_of({event["victim"]["id"] for event in events})
    summary = {}
    for event in reversed(events):
        line = f"{'Killed' if event['kind'] == 'kill' else 'Captured'} {names.get(event['victim']['id'], event['victim']['name'])}"
        for doer in event["doers"]:
            summary.setdefault(doer["id"], []).append(line)
    return summary


def characters(event):
    if event["kind"] in RUMOR_ONLY:
        return []
    if event["kind"] == "bounty":
        return [(event["target"]["id"], event["target"]["name"])]
    return [(party["id"], party["name"]) for party in [*event["doers"], event["victim"]]]


def character_ids(event):
    return [npc_id for npc_id, _ in characters(event)]


def event_line(event, names, player_faction):
    """names maps an npc_id to its current name; a character with no profile keeps the name of the event. A bounty is no
    act of the squad, so its wanted notice stands in for the line."""
    if event["kind"] == "bounty":
        return event.get("notice") or "Unknown"
    if event["kind"] == "custom":
        return "Written by you"
    if event["kind"] == "auto":
        count = len(event["threads"])
        return f"From {count} conversation{'' if count == 1 else 's'}"
    doers = name_list([names.get(doer["id"], doer["name"]) for doer in event["doers"]])
    victim = names.get(event["victim"]["id"], event["victim"]["name"])
    verb = "killed" if event["kind"] == "kill" else "captured"
    return f"{doers} of {player_faction} {verb} {victim}." if player_faction else f"{doers} {verb} {victim}."


def name_list(names):
    if len(names) < 3:
        return " and ".join(names)
    return f"{', '.join(names[:-1])}, and {names[-1]}"


def the_faction(faction):
    return faction if faction.startswith("The ") else f"the {faction}"
