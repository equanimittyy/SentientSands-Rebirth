"""Which known figures the player's squad killed or captured, from the game events, the days that the player's faction has
held each captive, the re-key of a character's records when a squad change gives it a new npc_id, and the defeats that
count toward the jobs of the squad and the deaths of givers that fail them (chat/quests.py).

The plugin keeps no state, so its hooks stay light: it sends the attacks of the player's faction, and the knockouts,
wake-ups, deaths, and imprisonments of everyone. The server keeps the game events of each character in memory and replays them
at a death or an imprisonment. Kenshi gives no last hit, so each attacker counts as a killer or as a captor.
"""
import logging
import threading

from chat import quests
from core import state
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


def take(game_events, ctx=None):
    """Reads the game events of a report in their order, stores the events that they make, and counts the jobs by them. The
    game time of ctx, the context of the request, rewinds the jobs before the events and checks them after the events.
    Returns the game messages of the jobs."""
    now = _minutes(ctx or {})
    notes = []
    try:
        quests.rewind(now)
    except campaign_db.CampaignUnavailable:
        pass
    for game_event in game_events or []:
        logging.debug(f"GAME EVENT: {game_event}")
        at = _minutes(game_event)
        if game_event.get("kind") == "rekey":
            _rekey(game_event["old"], game_event["new"], at)
            continue
        if at is None:
            continue
        attackers, down = _attribute(game_event, at)
        if game_event.get("kind") == "death":
            try:
                notes += quests.giver_died(canon_id(game_event["party"]), at)
            except campaign_db.CampaignUnavailable:
                pass
        if attackers:
            try:
                if game_event["kind"] == "knockout":
                    # A drop of a carried character and a load send a knockout of a character that is already down
                    if not down:
                        notes += quests.count_defeat(game_event.get("party") or {}, at)
                    continue
                # A load imprisons each prisoner again with no attackers, so it does not restart the clock
                if game_event["kind"] == "imprisonment":
                    campaign_db.start_captive(game_event["party"]["id"], at)
                done = _store(game_event["kind"], game_event["party"], attackers, at)
                # One kill never pays two jobs, and the knockout of a character that dies down already counted its defeat
                if game_event["kind"] == "death" and not done and not down:
                    done = quests.count_defeat(game_event["party"], at)
                notes += done
            except campaign_db.CampaignUnavailable:
                pass  # The event is lost, but the report must still update the player's context
    try:
        notes += quests.check(now)
    except campaign_db.CampaignUnavailable:
        pass
    return notes


def _rekey(old_id, new_id, at):
    try:
        if campaign_db.rekey(old_id, new_id, at):
            logging.info(f"REKEY: {old_id} is now {new_id}.")
        else:
            logging.warning(f"REKEY: Kept the records of {old_id}, because {new_id} already has records.")
    except campaign_db.CampaignUnavailable:
        pass  # No campaign holds records of the character


def _minutes(event):
    try:
        at = int(event["day"]) * 1440 + int(event["hour"]) * 60 + int(event["minute"])
    except (KeyError, TypeError, ValueError):
        return None
    # The game clock reads Day 0, 00:00 until it holds a real time, and that time would look like a load
    return at or None


def _attribute(game_event, at):
    """Adds the game event to the history of its character. Returns the attackers of a knockout, a death, or an imprisonment,
    and whether the character already lay knocked out before it."""
    global _newest, _campaign
    kind = game_event.get("kind")
    if kind == "attack":
        key = game_event.get("target")
    elif kind in ENDS:
        key = (game_event.get("party") or {}).get("id")
    else:
        key = game_event.get("id")
    if not key or kind not in ("attack", "knockout", "up", *ENDS):
        return [], False
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
        return _attackers(history) if kind in ("knockout", *ENDS) else ([], False)


def fought_recently(npc_ids, ctx):
    """Whether one of the characters attacked someone, or was knocked out, within FIGHT_QUIET_MINUTES before the game time of
    the context. The plugin sends no attack on a character of the player's faction, so taking hits alone is no fight."""
    now = _minutes(ctx)
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


def days_held(npc_id, ctx):
    """The whole game days since the player's squad captured the captive, or None without a game time. A captive with no
    capture in the game events, such as a slave in shackles, which no hook sees, starts its clock at the first call."""
    now = _minutes(ctx)
    return None if now is None else (now - campaign_db.captive_since(npc_id, now)) // 1440


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
    """The attackers of the event at the end of history, from the game events since the death or the imprisonment before
    it, and whether the character lay knocked out at that event."""
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
    return [attacker for attacker, at in attackers.values() if marked or end - at <= ATTACK_WINDOW_MINUTES], marked


def canon_id(party):
    """The npc_id of a generic character whose template is a canon character is the npc_id of that character, as for a
    context (adopt_canon)."""
    npc_id, template_id = party.get("id", ""), party.get("template_id")
    if npc_id.startswith("h:") and template_id and campaign_db.character_exists(f"u:{template_id}"):
        return f"u:{template_id}"
    return npc_id


def _store(kind, victim, attackers, at):
    """Returns the game messages of the jobs that the event does."""
    victim_id = canon_id(victim)
    if victim.get("player") or not victim_id.startswith("u:"):
        return []
    event_kind = "kill" if kind == "death" else "capture"
    doers = campaign_db.add_event(
        event_kind,
        [(canon_id(attacker), attacker.get("name", "")) for attacker in attackers],
        {"npc_id": victim_id, "name": victim.get("name", ""), "faction": victim.get("faction", "")},
        at,
    )
    if not doers:
        return []
    logging.debug(f"EVENTS: {', '.join(name for _, name in doers)} {'killed' if event_kind == 'kill' else 'captured'} {victim.get('name', '')} ({victim_id}) at {campaign_db.game_time_text(at)}")
    return quests.figure_event(victim_id, at)


def events():
    """Each event, newest first, as a dict with its ID, kind ("kill", "capture", "custom", or "auto"), game time, line, and
    rumor ID. The line names each character by its current name, so a renamed squad member shows with its new name."""
    rows = campaign_db.events()
    names = campaign_db.names_of({npc_id for _, _, event in rows for npc_id in character_ids(event)})
    faction = (campaign_db.player_faction() or {}).get("name")
    rumors = {rumor["event_id"]: rumor["id"] for rumor in campaign_db.rumors()}
    return [{"id": event_id, "kind": event["kind"], "time": campaign_db.game_time_text(at) if at is not None else "-", "line": event_line(event, names, faction), "rumor": rumors.get(event_id)}
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
    return [(party["id"], party["name"]) for party in [*event["doers"], event["victim"]]]


def character_ids(event):
    return [npc_id for npc_id, _ in characters(event)]


def event_line(event, names, player_faction):
    """names maps an npc_id to its current name; a character with no profile keeps the name of the event."""
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
