"""The offers of the action dialogue (docs/plans/action_dialogue/framework.md#offer).

An NPC that agrees to a deal ends its reply with an offer tag, for example [OFFER: JOIN_PARTY; TAKE_CATS: 800]. The tags of
the model never reach the plugin: code checks the offer against the hard limits, writes the popup and the memory lines from
the checked offer, and builds each action of the plugin itself.

The server holds at most one offer, in state.PENDING_OFFER, because the plugin takes no chat line while an offer waits.
"""

import itertools
import math
import re

from chat import action_dialogue, current_job
from core import state

OFFER_TAG = re.compile(r"\[\s*OFFER\s*:((?:[^\[\]]|\[[^\[\]]*\])*)\]", re.IGNORECASE)
REFUSE_TAG = re.compile(r"\[\s*REFUSE\s*\]", re.IGNORECASE)
ATTACK_TAG = re.compile(r"\[\s*ATTACK\s*\]", re.IGNORECASE)
DEAL_LINE = re.compile(r"\((?:[^()]+ (?:accepted|declined): |[^()]+ (?:attacked|treated|dismissed) )[^()]*\)\s*$")

GIVES = {"RECRUIT": {"JOIN_PARTY"}, "FOLLOW": {"HIRE"}, "HEAL": {"FIRST_AID"}, "LIBERATE": {"RELEASE"}, "THREATEN": {"GIVE_CATS", "GIVE_ITEM"}, "BARTER": {"GIVE_CATS", "GIVE_ITEM"}}
NEEDS = {"RECRUIT": "JOIN_PARTY", "FOLLOW": "HIRE", "HEAL": "FIRST_AID", "LIBERATE": "RELEASE"}
TAKES = {"RECRUIT": {"TAKE_CATS"}, "FOLLOW": {"TAKE_CATS"}, "HEAL": {"TAKE_CATS"}, "LIBERATE": {"TAKE_CATS"}, "THREATEN": set(), "BARTER": {"TAKE_CATS", "TAKE_ITEM"}}
# The foods whose base value in the game data is 150 or less
CHEAP_FOODS = ("Dried Gristle Flaps", "Dried Meat", "Rice Bowl", "Gohan", "Cooked Vegetables")
CHARITY_CATS = 50
# A gift raises the relation by 1 for each GIFT_WORTH of its worth, so small gifts cannot farm relation
GIFT_WORTH = 500
GIFT_MOST = 10
ACCEPT_LINES = {"RECRUIT": "recruit_accept", "FOLLOW": "follow_accept", "HEAL": "heal_start", "LIBERATE": "liberate_accept", "THREATEN": "threaten_accept", "BARTER": "barter_accept"}

_ids = itertools.count(1)


def read(content):
    """The parts of the offer tag of a reply as (name, argument) pairs, or None for a reply without one."""
    tag = OFFER_TAG.search(content or "")
    if not tag:
        return None
    parts = []
    for piece in tag.group(1).split(";"):
        name, _, argument = piece.strip().partition(":")
        if name.strip():
            parts.append((name.strip().upper().replace(" ", "_"), argument.strip()))
    return parts


def refused(content):
    return bool(REFUSE_TAG.search(content or ""))


def attacked(content):
    return bool(ATTACK_TAG.search(content or ""))


def cats_of(ctx):
    return int(ctx.get("money") or 0)


def count_of(argument):
    return int(re.sub(r"\D", "", argument) or 0)


def item_of(argument):
    """(count, name) of an item argument such as "2 Bread", "Bread x2", or "Katana"."""
    leading = re.match(r"(\d+)\s*x?\s+(.+)", argument, re.IGNORECASE)
    if leading:
        return int(leading.group(1)), leading.group(2).strip()
    trailing = re.match(r"(.+?)\s*x\s*(\d+)$", argument, re.IGNORECASE)
    if trailing:
        return int(trailing.group(2)), trailing.group(1).strip()
    return 1, argument.strip()


def hours_of(argument):
    """The hours of a hire length such as "2 days" or "6 hours". A bare number counts in days, as the popup does."""
    length = re.search(r"(\d+)\s*([a-z]*)", argument.lower())
    if not length:
        return 0
    return int(length.group(1)) * (1 if length.group(2).startswith("h") else 24)


def goods(npc, category):
    """The items that the NPC can hand over: what it carries, and in a trade also the stock of its shop, because the trade
    window of a shop shows the items of all its furniture."""
    items = list(npc.get("inventory") or [])
    if category == "BARTER" and current_job.current_job(npc, False, "") == "Running a shop":
        items += npc.get("stock") or []
    return items


def held(items, name):
    """(name, count) of the items that carry the name, whatever its case, or (None, 0). The model can leave out the grade
    of a weapon or an armour, so a name without one finds the item when only one grade of it is held."""
    counts = {}
    for item in items:
        if item.get("name"):
            counts[item["name"]] = counts.get(item["name"], 0) + int(item.get("count") or 1)
    wanted = name.lower()
    found = [label for label in counts if label.lower() == wanted] or [label for label in counts if label.lower().startswith(wanted + " (")]
    if len(found) != 1:
        return None, 0
    return found[0], counts[found[0]]


def price_of(label, *holdings):
    """The highest price of the item in the first holding that has it, so the NPC's stock sets the price."""
    for items in holdings:
        prices = [int(item.get("price") or 0) for item in items if item.get("name") == label]
        if prices:
            return max(prices)
    return 0


def shares(npc):
    """(sell share, buy share) of the price: a non-trader wants a bigger margin."""
    return (0.8, 0.6) if action_dialogue.is_trader(npc) else (1.0, 0.4)


def worth(parts, npc, speaker, side):
    """The worth to the NPC of the cats and the items of one side of a trade: "gives" for the NPC's side at its sell share,
    or "takes" for the player's side at its buy share."""
    sell, buy = shares(npc)
    stock = goods(npc, "BARTER")
    total = 0.0
    for kind, value in parts:
        if kind == "CATS":
            total += value
        elif kind == "ITEM":
            count, label = value
            total += count * (price_of(label, stock) * sell if side == "gives" else price_of(label, stock, speaker.get("inventory") or []) * buy)
    return total


def charity(gives, npc):
    """The checked charity of a trade in which the NPC gives without receiving, or a reason. Charity costs the NPC nothing,
    so the plugin creates the cats or the food, and the NPC need not hold them."""
    if state.CHARITY_DAYS.get(npc.get("npc_id")) == npc.get("day"):
        return None, "the NPC gave charity today"
    if len(gives) == 1 and gives[0][0] == "GIVE_CATS" and gives[0][1] <= CHARITY_CATS:
        return {"category": "BARTER", "gives": [("CATS", gives[0][1])], "takes": [], "charity": True}, None
    if len(gives) == 1 and gives[0][0] == "GIVE_ITEM" and gives[0][1][0] == 1:
        food = next((food for food in CHEAP_FOODS if food.lower() == gives[0][1][1].lower()), None)
        if food:
            return {"category": "BARTER", "gives": [("ITEM", (1, food))], "takes": [], "charity": True}, None
    return None, f"charity is at most {CHARITY_CATS} cats or 1 cheap food"


def check(category, parts, npc, speaker, guard=False):
    """(offer, None) for an offer that keeps the hard limits, or (None, reason). An offer holds the parts that the NPC gives
    and the parts that the player gives, as (kind, value) pairs: CATS with a count, ITEM with (count, name), HIRE with the
    hours, RELEASE with whether a guard releases, and JOIN_PARTY or FIRST_AID with None."""
    if category not in GIVES:
        return None, f"{category} makes no offers"
    parsed = []
    for name, argument in parts:
        if name not in GIVES[category] | TAKES[category]:
            return None, f"{name} is not a part of a {category} deal"
        if name in ("GIVE_CATS", "TAKE_CATS"):
            count = count_of(argument)
            if count < 1:
                return None, f"{name} has no count"
            parsed.append((name, count))
        elif name in ("GIVE_ITEM", "TAKE_ITEM"):
            count, item = item_of(argument)
            if count < 1:
                return None, f"{name} has no count"
            parsed.append((name, (count, item)))
        elif name == "HIRE":
            hours = hours_of(argument)
            if hours < 1:
                return None, "HIRE has no length"
            parsed.append((name, hours))
        else:
            parsed.append((name, guard if name == "RELEASE" else None))
    if category == "BARTER" and parsed and all(name in GIVES["BARTER"] for name, _ in parsed):
        return charity(parsed, npc)
    gives, takes = [], []
    for name, value in parsed:
        if name in ("GIVE_ITEM", "TAKE_ITEM"):
            count, item = value
            found, has = held(goods(npc, category) if name == "GIVE_ITEM" else speaker.get("inventory") or [], item)
            if not found or has < count:
                return None, f"{'the NPC' if name == 'GIVE_ITEM' else 'the speaker'} does not hold {count} {item}"
            (gives if name == "GIVE_ITEM" else takes).append(("ITEM", (count, found)))
        elif name in ("GIVE_CATS", "TAKE_CATS"):
            (gives if name == "GIVE_CATS" else takes).append(("CATS", value))
        else:
            gives.append((name, value))
    needed = NEEDS.get(category)
    if needed and needed not in {kind for kind, _ in gives}:
        return None, f"a {category} deal needs {needed}"
    if not gives and not takes:
        return None, "the offer is empty"
    paid = sum(count for kind, count in takes if kind == "CATS")
    if paid > cats_of(speaker):
        return None, f"the player has fewer than {paid} cats"
    given = sum(count for kind, count in gives if kind == "CATS")
    if given > cats_of(npc):
        return None, f"the NPC has fewer than {given} cats"
    rate = action_dialogue.mercenary_rate(npc)
    hours = sum(value for kind, value in gives if kind == "HIRE")
    if rate and paid < math.ceil(rate * hours / 24):
        return None, f"a mercenary charges at least {rate} cats a day"
    offer = {"category": category, "gives": gives, "takes": takes}
    if category == "BARTER":
        received, handed = worth(takes, npc, speaker, "takes"), worth(gives, npc, speaker, "gives")
        if received + 1e-6 < handed:
            return None, f"the NPC would receive a worth of {received:.0f} for {handed:.0f}"
        if not gives:
            offer["gift"] = min(GIFT_MOST, int(received // GIFT_WORTH))
    return offer, None


def length_text(hours):
    if hours % 24:
        return f"{hours} hour{'s' if hours != 1 else ''}"
    return f"{hours // 24} day{'s' if hours != 24 else ''}"


def goods_text(parts):
    words = []
    for kind, value in parts:
        if kind == "CATS":
            words.append(f"{value:,} cats")
        elif kind == "ITEM":
            count, name = value
            words.append(f"{count} {name}" if count > 1 else f"{'an' if name[:1].lower() in 'aeiou' else 'a'} {name}")
    if len(words) < 2:
        return "".join(words)
    return ", ".join(words[:-1]) + " and " + words[-1]


def deal_text(offer, voice, player):
    """The words of the NPC's side of the deal: voice is "popup" for the popup, "offered" for a declined offer, or
    "accepted" for a deal that runs."""
    kinds = {kind: value for kind, value in offer["gives"]}
    if "JOIN_PARTY" in kinds:
        return {"popup": "to join your squad", "offered": f"to join {player}'s squad", "accepted": f"joins {player}'s squad"}[voice]
    if "HIRE" in kinds:
        length = length_text(kinds["HIRE"])
        return {"popup": f"to follow you for {length}", "offered": f"to follow {player} for {length}", "accepted": f"follows {player} for {length}"}[voice]
    if "FIRST_AID" in kinds:
        return {"popup": "treatment", "offered": f"to treat {player}", "accepted": f"treats {player}"}[voice]
    if "RELEASE" in kinds:
        if kinds["RELEASE"]:
            return {"popup": "your release", "offered": f"to release {player}", "accepted": f"releases {player}"}[voice]
        return {"popup": "to break you out", "offered": f"to break {player} out", "accepted": f"breaks {player} out"}[voice]
    goods = goods_text(offer["gives"])
    return f"gives {player} {goods}" if voice == "accepted" else goods


def popup_text(offer, npc, player):
    paid = goods_text(offer["takes"])
    if not offer["gives"]:
        return f"{npc} accepts your gift of {paid}."
    return f"{npc} offers {deal_text(offer, 'popup', player)}{f' for {paid}' if paid else ''}."


def accepted_line(offer, npc, player):
    paid = goods_text(offer["takes"])
    if not offer["gives"]:
        return f"({player} accepted: {npc} takes {paid} as a gift.)"
    return f"({player} accepted: {npc} {deal_text(offer, 'accepted', player)}{f' for {paid}' if paid else ''}.)"


def declined_line(offer, npc, player):
    paid = goods_text(offer["takes"])
    if not offer["gives"]:
        return f"({player} declined: {npc} asked for {paid} as a gift.)"
    return f"({player} declined: {npc} offered {deal_text(offer, 'offered', player)}{f' for {paid}' if paid else ''}.)"


def actions(offer):
    """The plugin actions of the deal. A join goes first, because the plugin pays no fee to a member of the player faction,
    and the fee would land back in the player's purse. The player's side goes next, because the plugin skips the NPC's
    handover after a payment that fell short."""
    if offer.get("charity"):
        kind, value = offer["gives"][0]
        return [f"[ACTION: ADD_CATS: {value}]" if kind == "CATS" else f"[ACTION: SPAWN_ITEM: {value[1]}]"]
    out = ["[ACTION: JOIN_PARTY]" for kind, _ in offer["gives"] if kind == "JOIN_PARTY"]
    for kind, value in offer["takes"]:
        out.append(f"[ACTION: TAKE_CATS: {value}]" if kind == "CATS" else f"[ACTION: TAKE_ITEM: {value[1]}: {value[0]}]")
    for kind, value in offer["gives"]:
        if kind == "CATS":
            out.append(f"[ACTION: GIVE_CATS: {value}]")
        elif kind == "ITEM":
            out.append(f"[ACTION: GIVE_ITEM: {value[1]}: {value[0]}]")
        elif kind == "HIRE":
            out.append(f"[ACTION: HIRE: {value}]")
        elif kind == "RELEASE":
            out.append("[ACTION: RELEASE_PRISONER]" if value else "[ACTION: BREAKOUT_PRISONER]")
        elif kind != "JOIN_PARTY":
            out.append(f"[ACTION: {kind}]")
    return out


def checks(offer):
    """The CHECK lines of the offer command: what each side must still hold when the player accepts."""
    lines = []
    if offer.get("charity"):
        return lines
    for side, parts in (("player", offer["takes"]), ("npc", offer["gives"])):
        total = sum(value for kind, value in parts if kind == "CATS")
        if total:
            lines.append(f"CHECK: CATS {side} {total}")
        lines += [f"CHECK: ITEM {side} {value[0]} {value[1]}" for kind, value in parts if kind == "ITEM"]
    return lines


def boxes(offer):
    """The BOX lines of a trade, which the plugin shows in the two boxes of the barter window, cats first."""
    lines = []
    for side, parts in (("player", offer["takes"]), ("npc", offer["gives"])):
        ordered = sorted(parts, key=lambda part: part[0] != "CATS")
        lines += [f"BOX: {side} {value:,} cats" if kind == "CATS" else f"BOX: {side} {value[0]} {value[1]}" for kind, value in ordered]
    return lines


def command(offer_id, offer, npc, npc_key, speaker_key, text):
    """The pipe command that opens the popup: the ID, the keys of the NPC and the speaker, the name of the NPC, the text of
    the popup, the CHECK lines, and the BOX lines of a trade, one to a line."""
    shown = boxes(offer) if offer["category"] == "BARTER" else []
    return "CMD: OFFER: " + "\n".join([str(offer_id), f"{npc_key} {speaker_key}", npc, text, *checks(offer), *shown])


def hold(offer, **details):
    """Holds a checked offer until the player answers it, and returns its ID."""
    offer_id = next(_ids)
    state.PENDING_OFFER = {"id": offer_id, "offer": offer, **details}
    return offer_id


def take(offer_id):
    """The held offer of the ID, which stops being held, or None when the server holds no such offer, for example after a
    restart."""
    held_offer = state.PENDING_OFFER
    if not held_offer or str(held_offer["id"]) != str(offer_id):
        return None
    state.PENDING_OFFER = None
    return held_offer


def stocktake(npc):
    """The goods of the NPC for the prompt of a trade: the name and the count of each item, with no prices, because the
    price guide gives the real price of each item that the deal is about."""
    counts = {}
    for item in goods(npc, "BARTER"):
        if item.get("name"):
            counts[item["name"]] = counts.get(item["name"], 0) + int(item.get("count") or 1)
    return "YOUR GOODS: " + (", ".join(f"{count} {name}" for name, count in counts.items()) or "nothing") + "."


def price_guide(said, npc, speaker, player_name):
    """The price of each item that the text names, in the goods of the NPC or of the speaker, at the share that the worth
    rule allows, so the model gives a price that the check keeps instead of inventing one."""
    text = said.lower()
    sell, buy = shares(npc)
    stock = goods(npc, "BARTER")
    carried = speaker.get("inventory") or []
    lines = []
    for items, own in ((stock, True), (carried, False)):
        for label in dict.fromkeys(item["name"] for item in items if item.get("name")):
            base = label.split(" (")[0].lower()
            if not base or not re.search(rf"\b{re.escape(base)}s?\b", text):
                continue
            if own:
                lines.append(f"You sell {label} for at least {math.ceil(price_of(label, stock) * sell):,} cats each.")
            else:
                lines.append(f"You pay at most {math.floor(price_of(label, stock, carried) * buy):,} cats each for the {label} of {player_name}.")
    return lines


def facts(category, npc, speaker, player_name, lean, said=""):
    """The facts of the hard limits and the lean, for the turn message, because they change each turn. said is the text in
    which the price guide of a trade looks for item names."""
    lines = []
    if "TAKE_CATS" in TAKES[category]:
        lines.append(f"{player_name}'s squad has {cats_of(speaker):,} cats.")
    if category in ("THREATEN", "BARTER"):
        lines.append(f"You have {cats_of(npc):,} cats.")
    if category == "THREATEN":
        carried = [f"{item.get('count') or 1} {item['name']}" for item in npc.get("inventory") or [] if item.get("name")]
        lines.append(f"You carry: {', '.join(carried)}." if carried else "You carry no items.")
    if category == "BARTER":
        if speaker.get("character_state") == "imprisoned":
            lines.append(f"{player_name} is imprisoned." + (" You are imprisoned too." if npc.get("character_state") == "imprisoned" else ""))
        if state.CHARITY_DAYS.get(npc.get("npc_id")) == npc.get("day"):
            lines.append("You already gave charity today.")
        lines += price_guide(said, npc, speaker, player_name)
    if category == "FOLLOW":
        rate = action_dialogue.mercenary_rate(npc)
        lines.append(f"You are a mercenary: you never follow for free, and you charge at least {rate:,} cats for each day." if rate
                     else "You are no mercenary, so you ask no fee to follow.")
    deal = "DEAL FACTS:\n" + "\n".join(f"- {line}" for line in lines) + "\n\n" if lines else ""
    return f"{deal}YOUR THOUGHT: {action_dialogue.lean_text(lean)}"
