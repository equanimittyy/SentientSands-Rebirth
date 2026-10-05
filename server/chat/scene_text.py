"""The chat scene as prose that the NPC reads: the NPC is "you", and every other person is "they".

A model reads a sentence more reliably than a raw number, so each number becomes a sentence from a fixed scale. "You" and
"they" both take the plural verb, so no sentence needs a gendered pronoun. The server looks up the campaign data and passes
plain values, so this module never reads the campaign.
"""


def _scale(value, steps):
    """The text of the first step whose bound the value is below; the last step has no bound."""
    for bound, text in steps:
        if bound is None or value < bound:
            return text


# The bounds at -89, -59, -24, 25, 60, and 90 match the relation bar that the game shows (generate_relation_bar)
# Each step ends with the name, because the name of the player's faction comes with a clause: "Nameless, the group Izumi travels with"
RELATION = [
    (-89, "You loathe {name}."),
    (-59, "You feel hostile towards {name}."),
    (-24, "You feel unfriendly towards {name}."),
    (-9, "You feel mildly hostile towards {name}."),
    (10, "You feel neutral towards {name}."),
    (25, "You feel mildly warm towards {name}."),
    (60, "You feel friendly towards {name}."),
    (90, "You trust {name}."),
    (None, "You feel devoted to {name}."),
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
# The fight skill of the person before the NPC minus the fight skill of the NPC
STRENGTH_GAP = [
    (-30, "{name} looks much weaker than you."),
    (-10, "{name} looks weaker than you."),
    (10, "{name} looks about as strong as you."),
    (30, "{name} looks stronger than you."),
    (None, "{name} looks much stronger than you."),
]
MONEY = [
    (50, "You are nearly penniless."),
    (1000, "You have a little money."),
    (10000, "You have a fair amount of money."),
    (None, "You are wealthy."),
]
# Keyed by Kenshi's WeatherAffecting enum values (getCurrentWeatherAffectStatus), worded from the value names only
WEATHER = {1: "A dust storm blows.", 2: "Acid rain falls.", 3: "The air burns.", 4: "Gas hangs in the air.", 5: "Rain falls."}
RUMOR_AGE = [(1, "Earlier today"), (2, "Yesterday"), (7, "A few days ago"), (None, "Some time ago")]

STATES = {
    "imprisoned": "{You} are imprisoned and cannot move freely.",
    "enslaved": "{You} are a slave, shackled to a master.",
    "escaped-slave": "{You} escaped slavery, and {you} are hunted.",
    "unconscious": "{You} are unconscious.",
    "dead": "{You} are dead.",
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


def relation_text(name, group, relation, met, companions=()):
    """name is the squad member who speaks, and group the player's faction. The NPC keeps one relation, which the chats of
    every squad member change, so the sentence gives it as a feeling towards the group."""
    first = "" if met else f"You have never spoken with {name} before."
    earlier = f"Earlier you spoke with {_join(companions)}, who {'travels' if len(companions) == 1 else 'travel'} with {name}." if companions else ""
    feeling = _scale(_number(relation), RELATION).format(name=f"{group}, the group {name} travels with")
    return " ".join(s for s in (first, earlier, feeling) if s)


def overheard_note(listeners, partner):
    heard = f"{_join(listeners)} heard your conversation"
    return f"{heard} with {partner}." if partner else f"{heard}."


def memory_header(partners, listeners, overheard):
    """partners are the other speakers of the conversation, and listeners its overhearers of the player's faction."""
    if overheard:
        return f"You overheard {_join(partners)}."
    heard = f" {_join(listeners)} heard it." if listeners else ""
    return f"You spoke with {_join(partners)}.{heard}"


def conversation_label(partners, listeners, overheard):
    """memory_header without the second person, for the Dialogue Library and the bio prompt, which the NPC does not read."""
    text = _conversation(partners, listeners, overheard)
    return text[0].upper() + text[1:]


def memory_label(partners, listeners, overheard):
    return f"Memory of {_a(_conversation(partners, listeners, overheard))}"


def _conversation(partners, listeners, overheard):
    if overheard:
        return f"overheard conversation of {_join(partners)}"
    heard = f", heard by {_join(listeners)}" if listeners else ""
    return f"conversation with {_join(partners)}{heard}"


def hunger_text(subject, food_level):
    verb = "are" if subject == "You" else "look"
    return f"{subject} {verb} {_scale(_number(food_level, 300), HUNGER)}."


def state_text(subject, state):
    return STATES.get(state, "").format(You=subject, you=subject.lower())


def blood_text(subject, medical):
    max_blood = _number(medical.get("max_blood"), 100)
    share = _number(medical.get("blood"), 100) / max_blood if max_blood > 0 else 1.0
    if _number(medical.get("blood_rate")) > 0.01:
        return f"{subject} are bleeding."
    if share < 0.5:
        return f"{subject} {'are' if subject == 'You' else 'look'} weak from blood loss."
    if share < 0.85:
        return f"{subject} {'are' if subject == 'You' else 'look'} wounded."
    return ""


def health_text(subject, medical):
    """Healthy only when neither the blood nor a limb shows a wound, so a crippled leg never reads as healthy."""
    wounds = [text for text in (blood_text(subject, medical), limbs_text(medical.get("limbs") or {}, "your" if subject == "You" else "their")) if text]
    return " ".join(wounds) if wounds else f"{subject} {'are' if subject == 'You' else 'seem'} healthy."


def limbs_text(limbs, whose="your"):
    hurts = []
    for limb in (key for key in limbs if not key.endswith("_max")):
        hp, hp_max = _number(limbs[limb], 100), _number(limbs.get(f"{limb}_max"), 100)
        if hp <= -hp_max:
            state = "gone"
        elif hp < 0:
            state = "crippled"
        # 0.7 matches Injured in GetHealthStatus (plugin), so the prompt and the web app Status agree
        elif hp_max > 0 and hp / hp_max < 0.7:
            state = "hurt"
        else:
            continue
        hurts.append(f"{whose} {limb.replace('_', ' ')} is {state}")
    if not hurts:
        return ""
    text = _sentence(_join(hurts))
    return text[0].upper() + text[1:]


def _fight_skill(stats):
    skills = [_number(stats[key]) for key in ("melee_attack", "melee_defence") if key in stats]
    return max(skills) if skills else None


def combat_text(stats):
    skill = _fight_skill(stats)
    return _scale(skill, COMBAT) if skill is not None else ""


def strength_text(name, stats, other_stats):
    own, other = _fight_skill(stats), _fight_skill(other_stats)
    if own is None or other is None:
        return ""
    return _scale(other - own, STRENGTH_GAP).format(name=name)


def equipment_text(subject, items):
    equipped = [item for item in items if item.get("equipped") and item.get("name")]
    worn = [item["name"] for item in equipped if item.get("slot") != "weapon"]
    carried = [_a(item["name"]) for item in equipped if item.get("slot") == "weapon"]
    parts = ([f"wear {_join(worn)}"] if worn else []) + ([f"carry {_join(carried)}"] if carried else [])
    return f"{subject} {', and '.join(parts)}." if parts else ""


def building_text(context, trader):
    building = context.get("building_name")
    # in_shop marks every NPC inside a shop or a bar, a customer too, so only a trader owns the shop
    if trader and context.get("in_shop") and _known(building):
        return f"You are in your shop, {building}."
    if _known(building):
        return f"You are inside {building}."
    return "You are indoors." if (context.get("environment") or {}).get("indoors") else ""


def location_name(context):
    """Where the character is, for its profile: "Bar, The Hub", "The Hub", "Shack, Vain", or "Wilderness, Vain". Only a
    full context from the plugin carries the building."""
    environment = context.get("environment") or {}
    building, town = context.get("building_name"), environment.get("town_name")
    place = town if _known(town) else environment.get("zone_name")
    first = building if _known(building) else ("" if _known(town) else "Wilderness")
    return ", ".join(part for part in (first, place) if _known(part))


def location_text(environment):
    town, biome = environment.get("town_name", ""), environment.get("biome", "")
    if town and biome:
        place = f"You are in {town}, in {biome}."
    elif town or biome:
        place = f"You are in {town or biome}."
    else:
        place = "You are somewhere in the wasteland."
    walls = "You are inside the town walls." if environment.get("in_town") else ""
    return " ".join(part for part in (place, walls, WEATHER.get(int(_number(environment.get("weather"))), "")) if part)


def rumors_text(rumors, today):
    """rumors are (game minutes, text) pairs, oldest first. The rumor of a custom deed has None for its game minutes."""
    sentences = []
    for at, text in reversed(rumors):
        heard = f"{_scale(today - at // 1440, RUMOR_AGE)} you heard" if today is not None and at is not None else "You heard"
        sentences.append(f"{heard} a rumour: {_sentence(text)}")
    if sentences:
        sentences.append("These are only rumours; bring them up only when they fit the conversation.")
    return _section("Rumours:", sentences)


def player_text(name, facing, race, sex, race_description, medical, feels_hunger, faction, faction_description, items, building=None, state="normal"):
    """facing is False for banter, which has no NPC in front of the player. building is None outdoors."""
    who = person(race, sex)
    opener = "The individual before you is" if facing else "Nearby is"
    return _section("The person before you:" if facing else "The player:", [
        f"{opener} {name}, {who}." if who else f"{opener} {name}.",
        _sentence(race_description) if race_description else "",
        state_text("They", state),
        health_text("They", medical) if medical else "",
        state_text("They", "unconscious") if medical.get("is_unconscious") and state != "unconscious" else "",
        hunger_text("They", medical["hunger"]) if feels_hunger and "hunger" in medical else "",
        f"They are a member of {faction}." if _known(faction) else "",
        _sentence(faction_description) if faction_description else "",
        equipment_text("They", items),
        f"They are inside {building}." if building else "",
    ])


def npc_text(context, profile, player_name, player_faction, *, met, major, in_player_faction, feels_hunger, faction_description="", companions=(), player_stats=None):
    """context is the live context of the NPC, or its profile when the game has sent none. companions are the names of the
    other squad members that the NPC spoke with, and player_stats the stats of the squad member who talks."""
    faction = context.get("faction") or context.get("Faction") or ""
    old_faction = profile.get("Faction")
    task = context.get("job") or ""
    medical = context.get("medical") or {}
    stats = context.get("stats") or {}
    memories = context.get("memories") or {}
    state = context.get("character_state", "normal")
    sentences = [
        relation_text(player_name, player_faction, profile.get("Relation", 0), met, companions),
        state_text("You", state),
    ]
    if _known(faction) and faction != old_faction:
        sentences.append(f"You belonged to {old_faction}, but now you belong to {faction}." if _known(old_faction) else f"You now belong to {faction}.")
        sentences.append(_sentence(faction_description) if faction_description else "")
    if _known(task):
        sentences.append(f"Your current task: {task}.")
    trader = context.get("is_trader") or "shopkeeper" in task.lower()
    if trader:
        sentences.append("You are a trader.")
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
        sentences.append(health_text("You", medical))
        if medical.get("is_unconscious") and state != "unconscious":
            sentences.append(state_text("You", "unconscious"))
    sentences.append(building_text(context, trader))
    sentences += [combat_text(stats), strength_text(player_name, stats, player_stats or {})]
    if "money" in context:
        sentences.append(_scale(_number(context["money"]), MONEY))
    for table, key in ((SHORT_TERM_MEMORIES, "short_term"), (LONG_TERM_MEMORIES, "long_term")):
        tags = [int(_number(tag, -1)) for tag in memories.get(key, [])]
        sentences += [table[tag].format(name=player_name) for tag in tags if tag in table]
    sentences.append(equipment_text("You", context.get("inventory") or []))
    return _section("You:", sentences)
