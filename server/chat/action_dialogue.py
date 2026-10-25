"""The action dialogue: a chat thread that the player marks with "!", so that the NPC can make a deal that the game carries
out (docs/info/architecture.md#action-dialogue).

The checks here read only the contexts that the plugin sends, so they hold no state. routes.chat keeps the action dialogue
in state.CURRENT_THREAD, because it ends with its chat thread.
"""

import json
import random
import re

from chat import current_job, quests, scene_text
from chat.characters import is_skeleton
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
    ("q", "quest", "QUEST", "A request for a job or for work, or a report on a job"),
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
FIGHT_REASONS = {2: "{player} fights far better than you, and you dare not defy {player}.", 1: "{player} fights better than you.",
                 -1: "You fight better than {player}.", -2: "You fight far better than {player}, and you do not fear {player}."}
FOOD_BONUS = {"starving": 2, "very hungry": 1, "hungry": 1}
# The Savage Hive lost its hives, and the machines of the Mechanical Hive have no Queen
QUEEN_HIVES = {"Western Hive", "Midland Hive", "Northern Hive", "Southern Hive"}
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


def mark_chat(npc, speaker, in_player_faction):
    """The reason that each marked line to the NPC, and each line of an open action dialogue, goes to plain chat, before
    any classify call, or None. A fight stops a deal that started before it."""
    if npc.get("animal"):
        return "You are an animal and make no deals."
    if in_player_faction:
        return "You are in {player}'s faction, so you make no deals with {player}."
    if npc.get("in_combat"):
        return "You are in a fight, so you make no deals right now."
    if speaker.get("in_combat"):
        return "{player} is in a fight, so you make no deals with {player} right now."
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
        if not fellow_captives(npc, speaker):
            if speaker_state in ("imprisoned", "enslaved"):
                return f"{{player}} is {speaker_state}, so you cannot {verb} {{player}}."
            if npc_state in ("imprisoned", "enslaved") and not captive_of(npc, speaker):
                return f"You are {npc_state}, so you cannot {verb} {{player}}."
        if current_job.is_leader(npc):
            return f"You lead {npc.get('faction') or 'your faction'} and will not leave it."
    elif category == "QUEST":
        if npc_state == "imprisoned":
            if quests.held(npc):
                return "You are locked in a cage, so you pay {player}'s group for your job only after {player} gets you out of the cage."
            if giver_roles(npc):
                return "You are locked in a cage, so you give {player} work only after {player} gets you out of the cage."
        if not giver_roles(npc):
            return "You have no work to give."
        if speaker_state == "imprisoned":
            return "{player} is locked in a cage, so {player} cannot take work."
    return None


def fellow_captives(npc, speaker):
    """Both the speaker and the NPC are held, in a cage or in shackles, by any faction. An escaped slave is not held."""
    return all(ctx.get("character_state") in ("imprisoned", "enslaved") for ctx in (npc, speaker))


def captive_of(npc, speaker):
    """The faction of the speaker holds the NPC, in a cage or in shackles. A captive cannot leave its captor, but the
    captor can take it into the squad, and the plugin frees it at the join (DoJoinParty in plugin/game/GameActions.cpp)."""
    return bool(npc.get("captor")) and npc.get("captor") == speaker.get("factionID")


def runs_as(category, npc, speaker):
    """The category that a line of the category runs as. A fellow captive joins instead of following, because a hired
    follower stays out of the player's control, so the player could not lead it out. A captive of the speaker's faction
    joins too, because the player does not hire a captive that the player holds."""
    return "RECRUIT" if category == "FOLLOW" and (fellow_captives(npc, speaker) or captive_of(npc, speaker)) else category


def kits(npc, speaker):
    """The kits of the NPC that fit the wounds of the speaker. The plugin reads the needs per body part (TreatmentNeeds in
    plugin/game/Context.cpp), because a character with robotic limbs can need both kits."""
    return [kit for kit, need, has in KITS if speaker.get(need) and npc.get(has)]


def is_guard(npc):
    return current_job.current_job(npc, False, "") in GUARD_JOBS or JAILER_TASK in (npc.get("squad_jobs") or [])


def is_trader(npc):
    return current_job.current_job(npc, False, "") in TRADER_JOBS


def giver_roles(npc):
    """The roles of the NPC that give a QUEST job (chat/quests.py): leader, guard, and trader."""
    return {role for role, holds in (("leader", current_job.is_leader(npc)), ("guard", is_guard(npc)), ("trader", is_trader(npc))) if holds}


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


def lean(category, npc, speaker, relation, overheard=(), mode="talk", days_held=None):
    """The (bonus, reason) pairs of the game state for the deal of the category, each bonus + or -. A reason names the
    speaker as {player}. overheard is the nearby list of the chat request, the characters near the speaker, and mode is
    its chat mode. days_held is the whole game days that the speaker's faction has held the NPC captive
    (world_events.days_held), or None."""
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
        captive = fellow_captives(npc, speaker)
        pairs += [(npc.get("character_state") == "escaped-slave", "You escaped slavery."),
                  (2 * captive, "{player} is a fellow captive, and like most captives, you want to escape."),
                  # Outweighs the best relation and the captive bonus together, so a plan said aloud always leans to a refusal
                  (-6 * (captive and mode != "whisper"), "{player} says it out loud, where your captors can hear, so you refuse and deny any plan to escape."),
                  (-bool(npc.get("unique")), "You are no common drifter."),
                  (-2 * is_guard(npc), "You are a guard."),
                  (-2 * is_trader(npc), "You have a trade to run."),
                  (-(category == "FOLLOW" and not mercenary_rate(npc)), "You have no reason to follow {player}.")]
        if category == "RECRUIT" and not captive:
            pairs += people_pairs(npc, speaker)
        if captive_of(npc, speaker):
            fight = fight_bonus(npc, speaker)
            pairs += [(1, "{player}'s faction holds you captive, and joining the squad sets you free."), (fight, FIGHT_REASONS.get(fight))]
            if days_held is not None:
                pairs.append(captivity_pair(days_held))
    return [(int(bonus), reason) for bonus, reason in pairs if bonus]


def people_pairs(npc, speaker):
    """The ways of specific people, from the vanilla dialogue and the race and faction records of SSR Vanilla."""
    shek, holy, fight = is_shek(npc), npc.get("faction") == "Holy Nation", fight_bonus(npc, speaker)
    escaped = npc.get("character_state") == speaker.get("character_state") == "escaped-slave"
    return [(shek * fight, "The Shek idolize the strong." if fight > 0 else "The Shek do not serve the weak."),
            (shek and is_shek(speaker), "{player} is Shek, your kin."),
            (-2 * (holy and speaker.get("race") != npc.get("race")), "{player} is not of your race, and you serve only Okran's children."),
            (-(holy and speaker.get("gender") == "female"), "{player} is a woman, and you will not serve a woman."),
            (-2 * (is_hiver(npc) and npc.get("faction") in QUEEN_HIVES), "You are bound to your Queen and live for the Hive."),
            (escaped, "{player} escaped slavery too."),
            (-2 * (npc.get("faction") == "Anti-Slavers" and captive_of(npc, speaker)), "You fight slavery, and {player}'s faction holds you like a slaver."),
            hunger_pair(npc, speaker),
            wealth_pair(npc, speaker)]


def is_shek(ctx):
    return str(ctx.get("race", "")).lower().startswith("shek")


def is_hiver(ctx):
    return str(ctx.get("race", "")).lower().startswith("hive")


def hunger_pair(npc, speaker):
    """The hunger state of the chat prompt (scene_text.hunger_state), so a reason never contradicts that line."""
    level = (npc.get("medical") or {}).get("hunger")
    food = any(item.get("kind") == "food" for item in speaker.get("inventory") or [])
    if level is None or is_skeleton(npc.get("race", "")) or not food:
        return 0, None
    hunger = scene_text.hunger_state(level)
    return FOOD_BONUS.get(hunger, 0), f"You are {hunger}, and {{player}} carries food."


def wealth_pair(npc, speaker):
    if not mercenary_rate(npc):
        return 0, None
    cats = int(speaker.get("money") or 0)
    if cats >= 20000:
        return 2, "{player}'s faction is rich enough to pay you well."
    if cats >= 10000:
        return 1, "{player}'s faction can pay you."
    if cats < 1000:
        return -1, "{player}'s faction has few cats to pay you."
    return 0, None


def fight_bonus(npc, speaker):
    """How much stronger the speaker looks in the chat prompt (scene_text.strength_step), from -2 to 2, so a reason never
    contradicts that line."""
    return scene_text.strength_step(npc.get("stats") or {}, speaker.get("stats") or {}) or 0


def captivity_pair(days):
    """A new captive defies its captors, and a long captivity wears its will down."""
    if days >= 14:
        return 2, f"{{player}}'s faction took you captive {days} days ago, and your will to resist is broken."
    if days >= 9:
        return 1, f"{{player}}'s faction took you captive {days} days ago, and your will to resist wears thin."
    if days >= 5:
        return 0, None
    if days >= 3:
        return -1, f"{{player}}'s faction took you captive only {days} days ago, and you still defy your captors."
    when = f"{days} day{'s' if days > 1 else ''} ago" if days else "today"
    return -2, f"{{player}}'s faction took you captive {when}, and your anger is fresh."


def gave_charity_today(npc):
    charity_day = state.CHARITY_DAYS.get(npc.get("npc_id"))
    return charity_day is not None and charity_day == npc.get("day")


def threat_lean(npc, speaker, overheard):
    def sign(n):
        return (n > 0) - (n < 0)

    squad, own = sides(npc, speaker, overheard)
    fight, numbers = fight_bonus(npc, speaker), sign(squad - own)
    leader = current_job.is_leader(npc)
    pairs = [(fight, FIGHT_REASONS.get(fight)),
             (numbers, "{player}'s side outnumbers yours here." if numbers > 0 else "Your side outnumbers {player}'s here."),
             (npc.get("health") in ("Injured", "Crippled"), "You are hurt."),
             (-(speaker.get("health") in ("Injured", "Crippled")), "{player} is hurt."),
             (-bool(leader or npc.get("unique")), "You lead your faction." if leader else "You are no common drifter.")]
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
