"""The chat scene as prose that the NPC reads: the NPC is "you", and every other person is "they".

A model reads a sentence more reliably than a raw number, so each number becomes a sentence from a fixed scale. "You" and
"they" both take the plural verb, so no sentence needs a gendered pronoun. The server looks up the campaign data and passes
plain values, so this module never reads the campaign.
"""

import re


def _scale(value, steps):
    """The text of the first step whose bound the value is below; the last step has no bound."""
    for bound, text in steps:
        if bound is None or value < bound:
            return text


# The bounds at -89, -59, -24, 25, 60, and 90 match the relation bar that the game shows (generate_relation_bar)
RELATION = [
    (-89, "You loathe {name}."),
    (-59, "You are hostile towards {name}."),
    (-24, "You are unfriendly towards {name}."),
    (-9, "You are mildly hostile towards {name}."),
    (10, "You feel neutral towards {name}."),
    (25, "You are mildly warm towards {name}."),
    (60, "You are friendly towards {name}."),
    (90, "You trust {name} as an ally."),
    (None, "You are devoted to {name}."),
]
FACTION_STANCE = [(-29, "hostile"), (-9, "unfriendly"), (10, "neutral"), (50, "friendly"), (None, "allied")]
# The food level that the plugin sends: higher is fuller
HUNGER = [(80, "starving"), (200, "very hungry"), (250, "hungry"), (None, "well fed")]
COMBAT = [
    (10, "You have little skill with a weapon."),
    (30, "You can hold your own in a fight."),
    (60, "You are a seasoned fighter."),
    (80, "You are a formidable fighter."),
    (None, "Few in the world can match you in a fight."),
]
MONEY = [
    (50, "You are nearly penniless."),
    (1000, "You have a little money."),
    (10000, "You have a fair amount of money."),
    (None, "You are wealthy."),
]
DISTANCE = [(2.5, "right beside you"), (10, "close by"), (30, "nearby"), (None, "some distance away")]
RUMOR_AGE = [(1, "Earlier today"), (2, "Yesterday"), (7, "A few days ago"), (None, "Some time ago")]

# (at 50 or more, under 15)
ATTRIBUTES = {
    "strength": ("strong", "weak"),
    "dexterity": ("quick", "clumsy"),
    "toughness": ("tough", "frail"),
    "perception": ("perceptive", "inattentive"),
    "athletics": ("fast", "slow"),
}

STATES = {
    "imprisoned": "You are imprisoned and cannot move freely.",
    "enslaved": "You are a slave, shackled to a master.",
    "escaped-slave": "You escaped slavery, and you are hunted.",
    "unconscious": "You are unconscious.",
    "dead": "You are dead.",
}

# Keyed by Kenshi's memory-tag enum values, worded from the tag names only
SHORT_TERM_MEMORIES = {
    1: "You take {name} for an intruder.",
    2: "You take {name} for an aggressor.",
    3: "You count {name} as an ally for now.",
    4: "You count {name} as an enemy for now.",
    5: "You take {name} for a prisoner.",
    6: "{name} has been looted.",
    7: "You take {name} for a criminal.",
}
LONG_TERM_MEMORIES = {
    1: "{name} once intruded on you.",
    2: "{name} once saved your life.",
    3: "{name} once freed you.",
    4: "{name} once stole from you.",
    5: "{name} once held you captive.",
    6: "You know {name} as a friendly acquaintance.",
    7: "{name} once defeated your squad.",
    8: "Your squad once defeated {name}'s.",
    14: "{name} killed a friend of yours.",
    15: "You once wronged {name}.",
}

# GetHealthStatus in plugin/game/Context.cpp
NEARBY_HEALTH = {
    "Healthy": "They seem healthy.",
    "Injured": "They look injured.",
    "Crippled": "They look crippled.",
    "Unconscious": "They are unconscious.",
    "Dead": "They are dead.",
    "Playing Dead": "They lie still, playing dead.",
}

_RUMOR = re.compile(r"\[Day (\d+)[^\]]*\]\s*\[RUMOR:\s*(.*?)\]\s*$")


def _number(value, default=0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _join(items):
    if len(items) < 3:
        return " and ".join(items)
    return f"{', '.join(items[:-1])}, and {items[-1]}"


def _a(word):
    return f"{'an' if word[:1].lower() in 'aeiou' else 'a'} {word}"


def _sentence(text):
    text = text.strip()
    return text if text.endswith((".", "!", "?")) else f"{text}."


def _section(heading, sentences):
    sentences = [s for s in sentences if s]
    return f"{heading}\n{' '.join(sentences)}" if sentences else ""


def _known(value):
    return value and str(value).strip().lower() not in ("unknown", "none")


def person(race, sex):
    """"a Shek woman", or "a Skeleton" when the sex is Other or Unknown."""
    if not _known(race):
        return ""
    sex_word = {"male": " man", "female": " woman"}.get(str(sex).strip().lower(), "")
    return _a(f"{race}{sex_word}")


def relation_text(name, relation, met):
    first = "" if met else f"You have never spoken with {name} before."
    return " ".join(s for s in (first, _scale(_number(relation), RELATION).format(name=name)) if s)


def hunger_text(subject, food_level):
    verb = "are" if subject == "You" else "look"
    return f"{subject} {verb} {_scale(_number(food_level, 300), HUNGER)}."


def blood_text(subject, medical):
    max_blood = _number(medical.get("max_blood"), 100)
    share = _number(medical.get("blood"), 100) / max_blood if max_blood > 0 else 1.0
    if _number(medical.get("blood_rate")) > 0.01:
        return f"{subject} are bleeding."
    if share < 0.5:
        return f"{subject} {'are' if subject == 'You' else 'look'} weak from blood loss."
    if share < 0.85:
        return f"{subject} {'are' if subject == 'You' else 'look'} wounded."
    return f"{subject} {'are' if subject == 'You' else 'seem'} healthy."


def limbs_text(limbs):
    hurts = []
    for limb in (key for key in limbs if not key.endswith("_max")):
        hp, hp_max = _number(limbs[limb], 100), _number(limbs.get(f"{limb}_max"), 100)
        if hp <= -hp_max:
            state = "gone"
        elif hp < 0:
            state = "crippled"
        elif hp_max > 0 and hp / hp_max < 0.5:
            state = "hurt"
        else:
            continue
        hurts.append(f"your {limb.replace('_', ' ')} is {state}")
    if not hurts:
        return ""
    text = _sentence(_join(hurts))
    return text[0].upper() + text[1:]


def attributes_text(stats):
    high = [word for key, (word, _) in ATTRIBUTES.items() if key in stats and _number(stats[key]) >= 50]
    low = [word for key, (_, word) in ATTRIBUTES.items() if key in stats and _number(stats[key]) < 15]
    if high and low:
        return f"You are {_join(high)}, but {_join(low)}."
    return f"You are {_join(high or low)}." if high or low else ""


def combat_text(stats):
    skills = [_number(stats[key]) for key in ("melee_attack", "melee_defence") if key in stats]
    return _scale(max(skills), COMBAT) if skills else ""


def equipment_text(subject, items):
    equipped = [item for item in items if item.get("equipped") and item.get("name")]
    worn = [item["name"] for item in equipped if item.get("slot") != "weapon"]
    carried = [_a(item["name"]) for item in equipped if item.get("slot") == "weapon"]
    parts = ([f"wear {_join(worn)}"] if worn else []) + ([f"carry {_join(carried)}"] if carried else [])
    return f"{subject} {', and '.join(parts)}." if parts else ""


def location_text(environment):
    town, biome = environment.get("town_name", ""), environment.get("biome", "")
    if town and biome:
        return f"You are in {town}, in {biome}."
    if town or biome:
        return f"You are in {town or biome}."
    return "You are somewhere in the wasteland."


def rumors_text(lines, today):
    sentences = []
    for line in reversed(lines):
        match = _RUMOR.search(line)
        if not match:
            continue
        heard = f"{_scale(today - int(match.group(1)), RUMOR_AGE)} you heard" if today is not None else "You heard"
        sentences.append(f"{heard} a rumour: {_sentence(match.group(2))}")
    if sentences:
        sentences.append("These are only rumours; bring them up only when they fit the conversation.")
    return _section("Rumours:", sentences)


def player_text(name, facing, race, sex, race_description, medical, feels_hunger, faction, faction_description, items):
    """facing is False for banter, which has no NPC in front of the player."""
    who = person(race, sex)
    opener = "The individual before you is" if facing else "Nearby is"
    return _section("The person before you:" if facing else "The player:", [
        f"{opener} {name}, {who}." if who else f"{opener} {name}.",
        _sentence(race_description) if race_description else "",
        blood_text("They", medical) if medical else "",
        hunger_text("They", medical["hunger"]) if feels_hunger and "hunger" in medical else "",
        f"They are a member of {faction}." if _known(faction) else "",
        _sentence(faction_description) if faction_description else "",
        equipment_text("They", items),
    ])


def npc_text(context, profile, player_name, player_faction, *, met, major, in_player_faction, feels_hunger):
    """context is the live context of the NPC, or its profile when the game has sent none."""
    faction = context.get("faction") or context.get("Faction") or ""
    job = context.get("job") or context.get("Job") or ""
    medical = context.get("medical") or {}
    stats = context.get("stats") or {}
    memories = context.get("memories") or {}
    state = context.get("character_state", "normal")
    sentences = [
        relation_text(player_name, profile.get("Relation", 0), met),
        STATES.get(state, ""),
    ]
    if _known(faction) and faction != profile.get("Faction"):
        sentences.append(f"You now belong to {faction}.")
    if _known(job) and job != profile.get("Job"):
        sentences.append(f"Your job right now: {job}.")
    if context.get("is_trader") or context.get("in_shop") or "shopkeeper" in job.lower():
        sentences.append("You are a trader.")
    if context.get("in_shop"):
        sentences.append(f"You are in your shop, {context.get('building_name', 'Unknown')}.")
    if context.get("is_leader") and _known(faction):
        sentences.append(f"You lead {faction}.")
    if in_player_faction:
        sentences.append(f"You travel in {player_name}'s squad, and {player_name} leads it.")
    else:
        if context.get("relation") is not None and _known(faction):
            stance = _scale(_number(context["relation"]), FACTION_STANCE)
            sentences.append(f"Your faction, {faction}, is {stance} towards {player_faction}.")
        if major:
            sentences.append(f"You belong to {faction}, a major world power. You will not leave it for {player_name}'s squad without an extremely compelling reason, such as {player_name} saving your life more than once.")
    if medical:
        if feels_hunger and "hunger" in medical:
            sentences.append(hunger_text("You", medical["hunger"]))
        sentences.append(blood_text("You", medical))
        if medical.get("is_unconscious") and state != "unconscious":
            sentences.append(STATES["unconscious"])
        sentences.append(limbs_text(medical.get("limbs") or {}))
    if (context.get("environment") or {}).get("indoors"):
        sentences.append("You are indoors.")
    sentences += [attributes_text(stats), combat_text(stats)]
    if "money" in context:
        sentences.append(_scale(_number(context["money"]), MONEY))
    for table, key in ((SHORT_TERM_MEMORIES, "short_term"), (LONG_TERM_MEMORIES, "long_term")):
        tags = [int(_number(tag, -1)) for tag in memories.get(key, [])]
        sentences += [table[tag].format(name=player_name) for tag in tags if tag in table]
    sentences.append(equipment_text("You", context.get("inventory") or []))
    return _section("You:", sentences)


def nearby_text(people, player_name, player_faction):
    """Each person's gender is the sex that the server reports, so a Skeleton has none."""
    sentences = []
    for other in people:
        who = person(other.get("race"), other.get("gender"))
        faction = other.get("faction", "")
        if faction in ("Nameless", player_faction):
            description = ", ".join(part for part in (who, f"one of {player_name}'s squad") if part)
        elif _known(faction):
            description = f"{who} of {faction}" if who else f"of {faction}"
        else:
            description = who
        name = other.get("name", "Someone")
        subject = f"{name}, {description}," if description else name
        sentences.append(f"{subject} is {_scale(_number(other.get('dist'), 999), DISTANCE)}.")
        sentences.append(NEARBY_HEALTH.get(other.get("health"), ""))
        if other.get("equipment"):
            sentences.append(f"They wear or carry {other['equipment']}.")
    return _section("Around you:", sentences)
