"""The action dialogue: a chat thread that the player marks with "!", so that the NPC can make a deal that the game carries
out (docs/plans/action_dialogue/framework.md).

The checks here read only the contexts that the plugin sends, so they hold no state. routes.chat keeps the action dialogue
in state.CURRENT_THREAD, because it ends with its chat thread.
"""

import json
import random
import re

from chat import current_job
from core import state
from core.paths import DEFAULTS_DIR

# In the order of the classify list, one choice for each category
CATEGORIES = [
    ("t", "threaten", "THREATEN", "A threat or demand"),
    ("b", "barter", "BARTER", "A request to buy, sell, or swap items, a gift, or a plea for charity"),
    ("h", "heal", "HEAL", "A request to treat wounds or repair robotic parts, paid or free"),
    ("l", "liberate", "LIBERATE", "A request to be freed from prison or slavery, paid or free"),
    ("r", "recruit", "RECRUIT", "A request to join the squad for good, as a new member"),
    ("f", "follow", "FOLLOW", 'A request to come along or be hired for a while, such as "follow me"'),
    ("d", "dismiss", "DISMISS", "An order for a hired follower to leave"),
]
NONE_OF_THESE = "None of these"
GUARD_JOBS = {"Guarding the town", "Guarding a building", "Patrolling the town", "Keeping the peace", "Working as a slaver"}
# A jailer such as the captain of a bounty desk stands at a shopkeeper node, so its job reads Running a shop
JAILER_TASK = "FIND_CAGE_AND_PUT_DEADGUY_IN"
TRADER_JOBS = {"Trading", "Running a shop", "Travelling as a trader"}
MERCENARY_RATES = {"Mercenary Guild": 2000, "Tech Hunters": 2000, "Vagrants": 2000, "Black Dog": 2500}
# A small model follows a plain band better than a number
LEAN_BANDS = ((2, "You are inclined to agree."), (-1, "You could go either way."))
REFUSED_LEAN = "You are inclined to refuse."
RELATION_REASONS = {2: "You like {player}'s group a lot.", 1: "You like {player}'s group.", -1: "You dislike {player}'s group.",
                    -2: "You hate {player}'s group."}
END_LINES_PATH = f"{DEFAULTS_DIR}/action_end_lines.json"
KITS = (("first aid kit", "needs_first_aid", "has_first_aid"), ("repair kit", "needs_repair", "has_repair_kit"))
_WORD = re.compile(r"[^\W\d_]+")


def parse(message):
    """(kind, category, text) of a player line. kind is None for plain chat, or "category", "classify", "end", or "failure".
    text is the line without its mark."""
    message = message.strip()
    if not message.startswith("!"):
        return None, None, message
    if message == "!":
        return "failure", None, ""
    if message[1] == " ":
        return "classify", None, message[1:].strip()
    word = _WORD.match(message, 1)
    if not word:
        return None, None, message
    text = message[word.end():].strip()
    name = word.group(0).lower()
    if name in ("e", "end"):
        return "end", None, text
    for letter, full, category, _ in CATEGORIES:
        if name in (letter, full) and text:
            return "category", category, text
    return "failure", None, text


def knockout_block(npc, speaker, npc_name, speaker_name):
    """The block of every line, plain chat too, because a knocked-out character cannot talk."""
    for ctx, name in ((speaker, speaker_name), (npc, npc_name)):
        if ctx.get("character_state") == "unconscious":
            return f"{name} is unconscious."
    return None


def mark_chat(npc, in_player_faction):
    """The reason that each marked line to the NPC goes to plain chat, before any classify call, or None."""
    if npc.get("animal"):
        return "You are an animal and make no deals."
    if in_player_faction:
        return "You are in {player}'s faction, so you make no deals with {player}."
    return None


def gate_block(category, npc, speaker, npc_name):
    """The message of a deal that cannot happen at all, or None. The classify list leaves out each category that this
    blocks, so a named mark and the classify call reach the same categories."""
    if category == "DISMISS" and not npc.get("temporary_follower"):
        return f"{npc_name} is not a hired follower."
    return None


def plain_chat(category, npc, speaker):
    """The reason that a line of the category goes to plain chat instead, or None, because the story allows the deal but
    the game cannot carry it out. The NPC can name the reason, and the model never gets the prompt of the category, so it
    never learns how to make the deal. A reason names the speaker as {player}. A slave in a cage reads as imprisoned, so the
    slave state comes apart from character_state."""
    npc_state, speaker_state = npc.get("character_state"), speaker.get("character_state")
    if category == "THREATEN" and speaker_state == "imprisoned":
        return "{player} is locked in a cage, so you do not take the threat seriously."
    if category == "HEAL":
        needed = [kit for kit, need, _ in KITS if speaker.get(need)]
        if not needed:
            return "{player} has no wounds to treat."
        if not kits(npc, speaker):
            return f"You have no {' or '.join(needed)}."
        if npc_state == "imprisoned":
            return "You are locked in a cage, so you cannot treat {player}."
    elif category == "LIBERATE":
        if speaker.get("slave"):
            return "{player} is a slave, and no one releases a slave."
        if speaker_state != "imprisoned":
            return "{player} is free already."
        if npc_state == "imprisoned":
            return "You are locked in a cage too, so you cannot free {player}."
        if not is_guard(npc):
            return "You are not a guard, so you cannot release {player}."
    elif category in ("RECRUIT", "FOLLOW"):
        verb = "join" if category == "RECRUIT" else "follow"
        if speaker_state in ("imprisoned", "enslaved"):
            return f"{{player}} is {speaker_state}, so you cannot {verb} {{player}}."
        if npc_state in ("imprisoned", "enslaved"):
            return f"You are {npc_state}, so you cannot {verb} {{player}}."
        if npc.get("is_leader"):
            return f"You lead {npc.get('faction') or 'your faction'} and will not leave it."
    return None


def kits(npc, speaker):
    """The kits of the NPC that fit the wounds of the speaker. The plugin reads the needs per body part (TreatmentNeeds in
    plugin/game/Context.cpp), because a character with robotic limbs can need both kits."""
    return [kit for kit, need, has in KITS if speaker.get(need) and npc.get(has)]


def is_guard(npc):
    return current_job.current_job(npc, False, "") in GUARD_JOBS or JAILER_TASK in (npc.get("squad_jobs") or [])


def is_trader(npc):
    return current_job.current_job(npc, False, "") in TRADER_JOBS


def mercenary_rate(npc):
    return MERCENARY_RATES.get(npc.get("faction"))


def relation_bonus(relation):
    relation = relation or 0
    if relation >= 60:
        return 2
    if relation >= 25:
        return 1
    if relation <= -60:
        return -2
    if relation <= -25:
        return -1
    return 0


def lean(category, npc, speaker, relation, overheard=()):
    """The (bonus, reason) pairs of the game state for the deal of the category, each bonus + or -. A reason names the
    speaker as {player}. overheard is the nearby list of the chat request, the characters near the speaker."""
    if category == "THREATEN":
        return threat_lean(npc, speaker, overheard)
    bonus = relation_bonus(relation)
    pairs = [(bonus, RELATION_REASONS.get(bonus))]
    health = speaker.get("health")
    if category == "HEAL":
        pairs.append(({"Injured": 1, "Crippled": 2}.get(health, 0), f"{{player}} is {str(health).lower()}."))
    elif category == "LIBERATE":
        pairs.append((health == "Crippled", "{player} is crippled."))
    elif category in ("RECRUIT", "FOLLOW"):
        pairs += [(npc.get("character_state") == "escaped-slave", "You escaped slavery."),
                  (-bool(npc.get("unique")), "You are no common drifter."),
                  (-is_guard(npc), "You are a guard."),
                  (-is_trader(npc), "You have a trade to run."),
                  (-(category == "FOLLOW" and not mercenary_rate(npc)), "You are no mercenary.")]
    return [(int(bonus), reason) for bonus, reason in pairs if bonus]


def gave_charity_today(npc):
    charity_day = state.CHARITY_DAYS.get(npc.get("npc_id"))
    return charity_day is not None and charity_day == npc.get("day")


def threat_lean(npc, speaker, overheard):
    def melee(ctx):
        stats = ctx.get("stats") or {}
        return stats.get("melee_attack", 0) + stats.get("melee_defence", 0)

    def sign(n):
        return (n > 0) - (n < 0)

    squad, own = sides(npc, speaker, overheard)
    fight, numbers = sign(melee(speaker) - melee(npc)), sign(squad - own)
    pairs = [(fight, "{player} fights better than you." if fight > 0 else "You fight better than {player}."),
             (numbers, "{player}'s side outnumbers yours here." if numbers > 0 else "Your side outnumbers {player}'s here."),
             (npc.get("health") in ("Injured", "Crippled"), "You are hurt."),
             (-(speaker.get("health") in ("Injured", "Crippled")), "{player} is hurt."),
             (-bool(npc.get("is_leader") or npc.get("unique")), "You lead your faction." if npc.get("is_leader") else "You are no common drifter.")]
    return [(int(bonus), reason) for bonus, reason in pairs if bonus]


def sides(npc, speaker, overheard):
    """The counts of the player faction and of the NPC's faction near the NPC. The nearby list of the NPC leaves out the
    first squad character, so that character counts when it speaks or stands near the speaker."""
    near = npc.get("nearby") or []
    squad = sum(1 for other in near if other.get("faction") == speaker.get("faction"))
    members = speaker.get("squad") or []
    if members and (members[0] == speaker.get("name") or members[0] in {other.get("name") for other in overheard}):
        squad += 1
    own = sum(1 for other in near if other.get("faction") == npc.get("faction"))
    return squad, own


def lean_text(value):
    return next((text for floor, text in LEAN_BANDS if value >= floor), REFUSED_LEAN)


def thought(lean, player_name):
    """The band of the lean, then its reasons, so the reply can name what sways the NPC."""
    lines = [lean_text(sum(bonus for bonus, _ in lean))]
    for label, sign in (("Reasons to agree", 1), ("Reasons to refuse", -1)):
        reasons = [reason.format(player=player_name) for bonus, reason in lean if bonus * sign > 0]
        if reasons:
            lines.append(f"- {label}: {' '.join(reasons)}")
    return "\n".join(lines)


def choices(npc, speaker, npc_name):
    """The categories of the classify list: each one that the game state does not rule out."""
    return [category for _, _, category, _ in CATEGORIES if not gate_block(category, npc, speaker, npc_name)]


def choice_list(categories):
    """The numbered list of the classify prompt, which ends in the escape hatch."""
    labels = {category: label for _, _, category, label in CATEGORIES}
    return "\n".join(f"{number}. {text}" for number, text in enumerate([*(labels[c] for c in categories), NONE_OF_THESE], 1))


def chosen(output, categories):
    """The category of the number that the classify call gave, or None for the escape hatch or any other output."""
    number = re.search(r"\d+", output or "")
    index = int(number.group(0)) - 1 if number else -1
    return categories[index] if 0 <= index < len(categories) else None


def ended(content):
    return bool(re.search(r"\[\s*END\s*\]", content, re.IGNORECASE))


def end_line(end):
    """A random preset line of the end, for example "end" for !end."""
    with open(END_LINES_PATH, "r", encoding="utf-8") as f:
        return random.choice(json.load(f)[end])
