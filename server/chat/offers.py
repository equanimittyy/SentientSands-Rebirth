"""The offers of the action dialogue (docs/info/architecture.md#action-dialogue).

An NPC that agrees to a deal ends its reply with a short tag: [AGREE: 800 cats] for a deal that the category fixes, such as a
recruit, [GIVE: 200 cats, 1 Katana] for a handover, or [DEAL: 1 Katana for 4600 cats] for a trade. The model left out
longer tags that named each part, so code adds the parts. The tags of the model never reach the plugin: code checks the
offer against the hard limits, writes the popup and the memory lines from the checked offer, and builds each action of the
plugin itself.

The server holds at most one offer, in state.PENDING_OFFER, because the plugin takes no chat line while an offer waits.
"""

import itertools
import math
import re

from chat import action_dialogue
from core import state
from core.settings import load_settings

# An item name can hold brackets, such as "Armoured Rags (colored) [alt]"
_TAG = r"\[\s*{}\s*(?::((?:[^\[\]]|\[[^\[\]]*\])*))?\]"
AGREE_TAG = re.compile(_TAG.format("AGREE"), re.IGNORECASE)
GIVE_TAG = re.compile(_TAG.format("GIVE"), re.IGNORECASE)
DEAL_TAG = re.compile(_TAG.format("DEAL"), re.IGNORECASE)
REFUSE_TAG = re.compile(r"\[\s*REFUSE\s*\]", re.IGNORECASE)
ATTACK_TAG = re.compile(r"\[\s*ATTACK\s*\]", re.IGNORECASE)
CATS_TERM = re.compile(r"\d[\d,]*(?:\s*cats?)?", re.IGNORECASE)
LENGTH_TERM = re.compile(r"\d+\s*(?:hours?|days?)", re.IGNORECASE)
DEAL_LINE = re.compile(r"\((?:[^()]+ (?:accepted|declined): |[^()]+ (?:attacked|treated|dismissed) )[^()]*\)\s*$")

GIVES = {"RECRUIT": {"JOIN_PARTY"}, "FOLLOW": {"HIRE"}, "HEAL": {"FIRST_AID"}, "LIBERATE": {"RELEASE"}, "THREATEN": {"GIVE_CATS", "GIVE_ITEM"}, "BARTER": {"GIVE_CATS", "GIVE_ITEM", "GIVE_FOOD"}}
NEEDS = {"RECRUIT": "JOIN_PARTY", "FOLLOW": "HIRE", "HEAL": "FIRST_AID", "LIBERATE": "RELEASE"}
TAKES = {"RECRUIT": {"TAKE_CATS"}, "FOLLOW": {"TAKE_CATS"}, "HEAL": {"TAKE_CATS"}, "LIBERATE": {"TAKE_CATS"}, "THREATEN": set(), "BARTER": {"TAKE_CATS", "TAKE_ITEM"}}
TERMS_TAGS = {"RECRUIT": AGREE_TAG, "FOLLOW": AGREE_TAG, "HEAL": AGREE_TAG, "LIBERATE": AGREE_TAG, "THREATEN": GIVE_TAG, "BARTER": DEAL_TAG}
# The cheapest food in the game data, at a base value of 40
CHARITY_FOOD = "Dried Gristle Flaps"
CHARITY_CATS = 50
# A gift raises the relation by 1 for each GIFT_WORTH of its worth, so small gifts cannot farm relation
GIFT_WORTH = 500
GIFT_MOST = 10
RELEASE_BRIBE = 500
# (sell share, buy share) of the price for a trader and for any other NPC. Each sells at the price of the game's trade
# window, or a deal would undercut it, and a non-trader pays less for the player's items, because it wants a bigger margin
SHARES = {True: (1.0, 0.8), False: (1.0, 0.6)}
# Percent points of what the NPC gives. It only guides the model: no check enforces it, so the character decides each
# deal.
PROFIT_OFFSETS = {-2: 20, -1: 10, 0: 0, 1: -20, 2: -30}
# (least profit share, lean bonus), the biggest share first. The model refused profits when the lean held only the
# relation.
PROFIT_LEANS = ((0.5, 4), (0.25, 3), (0.0, 2))
# The model agreed to a profit below the one that it wants when that profit moved the lean by nothing
SMALL_PROFIT_LEAN = -1
LOSS_LEAN = -2
# The reasons of check name the parties for the log. The turn message of the barter window speaks to the NPC, which invented
# a reason, such as a sale of an item that it no longer had, when the message gave none.
TABLE_REASONS = {
    "the NPC does not hold": "someone else bought your",
    "the NPC has fewer than": "you have fewer than",
    "the speaker does not hold": "{player} does not have",
    "the player has fewer than": "{player} has fewer than",
    "charity is only GIVE_CATS or GIVE_FOOD": "you give charity only as cats",
}
ACCEPT_LINES = {"RECRUIT": "recruit_accept", "FOLLOW": "follow_accept", "HEAL": "heal_start", "LIBERATE": "liberate_accept", "THREATEN": "threaten_accept", "BARTER": "barter_accept"}
# Keyed by the kinds of ItemKind (plugin/game/Context.cpp). Kenshi files alcohol under narcotics, so a drink is a "drug".
KIND_WORDS = {
    "food": {"food", "meal", "eat", "hungry", "starving", "ration", "grub"},
    "drug": {"drink", "booze", "alcohol", "liquor", "drug", "smoke"},
    "medical": {"medicine", "medical", "bandage", "heal", "healing", "medkit"},
    "repair": {"repair"},
    "armour": {"armour", "armor", "clothes", "clothing", "outfit"},
    "weapon": {"weapon", "sword", "blade"},
    "crossbow": {"crossbow", "bow", "ranged"},
    "ammo": {"ammo", "ammunition", "bolts"},
    "book": {"book", "reading"},
    "blueprint": {"blueprint", "research"},
    "backpack": {"backpack", "bag", "pack"},
    "tool": {"tool"},
    "limb": {"limb", "prosthetic", "robotic"},
}
# Speech words that are also in item names, such as "cats" in "Cat-Lon Letter" or "right" in the severed limbs
COMMON_WORDS = {"the", "and", "for", "all", "can", "one", "out", "day", "man", "way", "boy", "that", "with", "from", "good",
                "great", "long", "thing", "before", "last", "little", "open", "part", "hand", "cat", "money", "left", "right"}
PRICE_LINES = 10

_ids = itertools.count(1)


def _tag(content, category):
    pattern = TERMS_TAGS.get(category)
    return pattern.search(content or "") if pattern else None


def offer_text(content, category):
    """The deal tag of a reply as the model wrote it, or None."""
    tag = _tag(content, category)
    return tag.group(0) if tag else None


def _terms(text):
    """The terms of a tag, split at each comma or semicolon outside parentheses and brackets. A comma before a digit stays,
    because it groups the thousands of a number such as 1,500."""
    terms, depth, start = [], 0, 0
    for i, char in enumerate(text):
        depth += (char in "([") - (char in ")]")
        if depth == 0 and char in ",;" and not text[i + 1:i + 2].isdigit():
            terms.append(text[start:i])
            start = i + 1
    terms.append(text[start:])
    return [term.strip() for term in terms if term.strip()]


def _side(text, side):
    """The parts of one side of a handover or a trade: cats, items, or food for charity."""
    parts = []
    for term in _terms(text):
        if term.lower() == "nothing":
            continue
        if side == "GIVE" and term.lower() == "food":
            parts.append(("GIVE_FOOD", ""))
        elif CATS_TERM.fullmatch(term):
            parts.append((f"{side}_CATS", term))
        else:
            parts.append((f"{side}_ITEM", term))
    return parts


def read(content, category):
    """The parts of the deal tag of a reply as (name, argument) pairs, or None for a reply without one. An [AGREE] gets the
    part that its category needs, with the length of a hire as its argument, and its cats are the cats that the player
    pays."""
    tag = _tag(content, category)
    if not tag:
        return None
    text = tag.group(1) or ""
    if category == "BARTER":
        sides = re.split(r"\s+for\s+", text, maxsplit=1, flags=re.IGNORECASE)
        # Each side of a trade can be "nothing", so a tag without "for" names no deal
        if len(sides) < 2:
            return []
        return [*_side(sides[0], "GIVE"), *_side(sides[1], "TAKE")]
    if category == "THREATEN":
        return _side(text, "GIVE")
    terms = _terms(text)
    length = next((term for term in terms if LENGTH_TERM.fullmatch(term)), "")
    return [(NEEDS[category], length), *(("TAKE_CATS", term) for term in terms if CATS_TERM.fullmatch(term))]


def refused(content):
    return bool(REFUSE_TAG.search(content or ""))


def attacked(content):
    return bool(ATTACK_TAG.search(content or ""))


def agreed(content):
    return bool(AGREE_TAG.search(content or ""))


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


def sells_stock(npc, category):
    """A trader in a shop trades only the stock of its shop, the items of all its furniture, because the trade window of a
    shop shows them, and keeps what it carries. The plugin sends stock for each NPC in a shop, and a barman's job can read
    Trading instead of Running a shop, so any trader in a shop sells the stock."""
    return category == "BARTER" and "stock" in npc and action_dialogue.is_trader(npc)


def goods(npc, category):
    """The items that the NPC can hand over: the stock of a trader in a shop, else what the NPC carries."""
    return list((npc["stock"] if sells_stock(npc, category) else npc.get("inventory")) or [])


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
    return SHARES[action_dialogue.is_trader(npc)]


def profit_share(relation):
    return max(0, load_settings()["barter_profit_target"] + PROFIT_OFFSETS[action_dialogue.relation_bonus(relation)]) / 100


def worth(parts, npc, speaker, side, markup=1):
    """The worth to the NPC of the cats and the items of one side of a trade: "gives" for the NPC's side at its sell share,
    or "takes" for the player's side at its buy share. A markup of 1 plus the profit that the NPC wants raises the price of
    each item of the NPC and lowers each item of the player, as the price guide does."""
    sell, buy = shares(npc)
    stock = goods(npc, "BARTER")
    total = 0.0
    for kind, value in parts:
        if kind == "CATS":
            total += value
        elif kind == "ITEM":
            count, label = value[:2]
            total += count * (price_of(label, stock) * sell * markup if side == "gives" else price_of(label, stock, speaker.get("inventory") or []) * buy / markup)
    return total


def charity(gives, npc):
    """The checked charity of a trade in which the NPC gives without receiving, or a reason. Charity costs the NPC nothing,
    so the plugin creates the cats or the food, and the NPC need not hold them. The model often offers more cats than the
    cap, and the cap cuts them instead of dropping the offer."""
    if len(gives) == 1 and gives[0][0] == "GIVE_CATS":
        return {"category": "BARTER", "gives": [("CATS", min(gives[0][1], CHARITY_CATS))], "takes": [], "charity": True}, None
    if len(gives) == 1 and gives[0][0] == "GIVE_FOOD":
        return {"category": "BARTER", "gives": [("ITEM", (1, CHARITY_FOOD))], "takes": [], "charity": True}, None
    return None, "charity is only GIVE_CATS or GIVE_FOOD"


def release_fee(speaker):
    return RELEASE_BRIBE + (speaker.get("bounty") or 0)


def pooled(squad):
    """The items of all the squad mates of the barter window, which price the player's side of a trade."""
    return [item for mate in squad for item in mate.get("inventory") or []]


def check(category, parts, npc, speaker, squad=None):
    """(offer, None) for an offer that keeps the hard limits, or (None, reason). An offer holds the parts that the NPC gives
    and the parts that the player gives, as (kind, value) pairs: CATS with a count, ITEM with (count, name), HIRE with the
    hours, and JOIN_PARTY, FIRST_AID, or RELEASE with None. squad holds the key and the inventory of each squad mate of the
    barter window: each TAKE_ITEM part names its holder as a third element, and its ITEM value gets the key of the holder."""
    if category not in GIVES:
        return None, f"{category} makes no offers"
    holders = [(str(mate.get("key")), mate.get("inventory") or []) for mate in squad] if squad else [(None, speaker.get("inventory") or [])]
    parsed = []
    for name, argument, *holder in parts:
        if name not in GIVES[category] | TAKES[category]:
            return None, f"{name} is not a part of a {category} deal"
        if name in ("GIVE_CATS", "TAKE_CATS"):
            count = count_of(argument)
            # A model that agrees to a deal for free can still write 0 cats
            if count:
                parsed.append((name, count))
        elif name in ("GIVE_ITEM", "TAKE_ITEM"):
            count, item = item_of(argument)
            if count < 1:
                return None, f"{name} has no count"
            parsed.append((name, (count, item, holder[0] if holder else None)))
        elif name == "HIRE":
            hours = hours_of(argument)
            if hours < 1:
                return None, "HIRE has no length"
            parsed.append((name, hours))
        else:
            parsed.append((name, None))
    if category == "BARTER" and parsed and all(name in GIVES["BARTER"] for name, _ in parsed):
        return charity(parsed, npc)
    if any(name == "GIVE_FOOD" for name, _ in parsed):
        return None, "GIVE_FOOD is only for charity"
    gives, takes = [], []
    for name, value in parsed:
        if name == "GIVE_ITEM":
            count, item, _ = value
            found, has = held(goods(npc, category), item)
            if not found or has < count:
                return None, f"the NPC does not hold {count} {item}"
            gives.append(("ITEM", (count, found)))
        elif name == "TAKE_ITEM":
            count, item, wanted = value
            for key, items in holders:
                found, has = held(items, item)
                if wanted in (None, key) and found and has >= count:
                    break
            else:
                return None, f"the speaker does not hold {count} {item}"
            takes.append(("ITEM", (count, found, key) if key else (count, found)))
        elif name in ("GIVE_CATS", "TAKE_CATS"):
            (gives if name == "GIVE_CATS" else takes).append(("CATS", value))
        else:
            gives.append((name, value))
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
    fee = release_fee(speaker)
    if any(kind == "RELEASE" for kind, _ in gives) and paid < fee:
        return None, f"a release costs a bribe of at least {fee} cats"
    offer = {"category": category, "gives": gives, "takes": takes}
    if sells_stock(npc, category):
        offer["stock"] = True
    if category == "BARTER" and not gives:
        side = dict(speaker, inventory=pooled(squad)) if squad else speaker
        offer["gift"] = min(GIFT_MOST, int(worth(takes, npc, side, "takes") // GIFT_WORTH))
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
            count, name = value[:2]
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
        return {"popup": "your release", "offered": f"to release {player}", "accepted": f"releases {player}"}[voice]
    goods = goods_text(offer["gives"])
    return f"gives {player} {goods}" if voice == "accepted" else goods


def popup_text(offer, npc, player):
    paid = goods_text(offer["takes"])
    if not offer["gives"]:
        return f"{npc} accepts your gift of {paid}."
    return f"{npc} offers {deal_text(offer, 'popup', player)}{f' for {paid}' if paid else ''}."


def hire_terms(offer):
    """(hours, fee) of a hire, or None for a deal without one."""
    hours = sum(value for kind, value in offer["gives"] if kind == "HIRE")
    return (hours, sum(value for kind, value in offer["takes"] if kind == "CATS")) if hours else None


def renewal_text(npc, hours, fee):
    return f"{npc} offers to renew following you for {length_text(hours)}{f' for {fee:,} cats' if fee else ''}."


def accepted_line(offer, npc, player):
    paid = goods_text(offer["takes"])
    if not offer["gives"]:
        return f"({player} accepted: {npc} takes {paid} as a gift.)"
    return f"({player} accepted: {npc} {deal_text(offer, 'accepted', player)}{f' for {paid}' if paid else ''}.)"


def accept_end(offer, npc, speaker):
    """The end whose preset line the NPC says at the accept. A fellow captive agrees while the captors still hold both, so
    its lines keep the escape quiet."""
    if offer["category"] == "RECRUIT" and action_dialogue.fellow_captives(npc, speaker):
        return "recruit_captive_accept"
    return ACCEPT_LINES[offer["category"]]


def declined_line(offer, npc, player):
    paid = goods_text(offer["takes"])
    if not offer["gives"]:
        return f"({player} declined: {npc} asked for {paid} as a gift.)"
    return f"({player} declined: {npc} offered {deal_text(offer, 'offered', player)}{f' for {paid}' if paid else ''}.)"


def actions(offer):
    return [action for _, action in _acts(offer)]


def voiced(offer, voice):
    """The actions of the deal, each with the voice that the plugin acts on. An item of a squad mate leaves that squad mate,
    so its key takes the place of the speaker's key after the >."""
    npc = voice.partition(">")[0]
    return [f"{npc}>{holder}: {action}" if holder else f"{voice}: {action}" for holder, action in _acts(offer)]


def _acts(offer):
    """(holder, action) of each plugin action of the deal, the holder None for the speaker. A join carries the fee, because
    each action is its own pipe message: the plugin then recruits only when the player can pay, and pays the fee into no
    purse, where a recruit's purse would hand it back to the player. The player's side goes before the NPC's, because the
    plugin skips the NPC's handover after a payment that fell short. A sale from the stock is SELL_ITEM, which the plugin
    takes only from the furniture, so a trader never hands over an item that it carries, and a purchase into the stock is
    BUY_ITEM, which the plugin puts into the furniture, where the trader sells it again."""
    if offer.get("charity"):
        kind, value = offer["gives"][0]
        return [(None, f"[ACTION: ADD_CATS: {value}]" if kind == "CATS" else f"[ACTION: SPAWN_ITEM: {value[1]}]")]
    joins = any(kind == "JOIN_PARTY" for kind, _ in offer["gives"])
    fee = sum(value for kind, value in offer["takes"] if kind == "CATS")
    out = [(None, f"[ACTION: JOIN_PARTY: {fee}]")] if joins else []
    for kind, value in offer["takes"]:
        if kind == "ITEM":
            take = "BUY_ITEM" if offer.get("stock") else "TAKE_ITEM"
            out.append((value[2] if len(value) > 2 else None, f"[ACTION: {take}: {value[1]}: {value[0]}]"))
        elif not joins:
            out.append((None, f"[ACTION: TAKE_CATS: {value}]"))
    for kind, value in offer["gives"]:
        if kind == "CATS":
            out.append((None, f"[ACTION: GIVE_CATS: {value}]"))
        elif kind == "ITEM":
            out.append((None, f"[ACTION: {'SELL_ITEM' if offer.get('stock') else 'GIVE_ITEM'}: {value[1]}: {value[0]}]"))
        elif kind == "HIRE":
            out.append((None, f"[ACTION: HIRE: {value}]"))
        elif kind == "RELEASE":
            out.append((None, "[ACTION: RELEASE_PRISONER]"))
        elif kind != "JOIN_PARTY":
            out.append((None, f"[ACTION: {kind}]"))
    return out


def holder_of(value, side):
    """The holder of an item in the CHECK and DEAL lines: npc, player for the speaker, or the key of a squad mate."""
    return value[2] if len(value) > 2 else side


def checks(offer):
    """The CHECK lines of the offer command: what each side must still hold when the player accepts, and a ROOM line for
    each item that the NPC must find room for, named with its giver. A trader in a shop puts its purchases into the
    furniture, so it needs no ROOM line."""
    lines = []
    if offer.get("charity"):
        return lines
    for side, parts in (("player", offer["takes"]), ("npc", offer["gives"])):
        total = sum(value for kind, value in parts if kind == "CATS")
        if total:
            lines.append(f"CHECK: CATS {side} {total}")
        lines += [f"CHECK: ITEM {holder_of(value, side)} {value[0]} {value[1]}" for kind, value in parts if kind == "ITEM"]
    if not offer.get("stock"):
        lines += [f"CHECK: ROOM {holder_of(value, 'player')} {value[0]} {value[1]}" for kind, value in offer["takes"] if kind == "ITEM"]
    return lines


def deal_lines(offer):
    """The DEAL lines of a trade, which the barter window loads into its lists. Unlike the CHECK lines, they hold charity
    too, which the NPC need not hold."""
    lines = []
    for side, parts in (("player", offer["takes"]), ("npc", offer["gives"])):
        total = sum(value for kind, value in parts if kind == "CATS")
        if total:
            lines.append(f"DEAL: CATS {side} {total}")
        lines += [f"DEAL: ITEM {holder_of(value, side)} {value[0]} {value[1]}" for kind, value in parts if kind == "ITEM"]
    return lines


def box_order(part):
    """Cats first, then the items by the biggest count, and items of one count by name."""
    kind, value = part
    return (0, 0, "") if kind == "CATS" else (1, -value[0], value[1].lower())


def boxes(offer):
    """The BOX lines of a trade, which the plugin shows in the two boxes of the offer popup."""
    lines = []
    for side, parts in (("player", offer["takes"]), ("npc", offer["gives"])):
        ordered = sorted(parts, key=box_order)
        lines += [f"BOX: {side} {value:,} cats" if kind == "CATS" else f"BOX: {side} {value[0]} {value[1]}" for kind, value in ordered]
    return lines


def command(offer_id, offer, npc, npc_key, speaker_key, text, window=False):
    """The pipe command that opens the popup: the ID, the keys of the NPC and the speaker, the name of the NPC, the text of
    the popup, the CHECK lines, and the RESTOCK and BOX lines of a trade, one to a line. RESTOCK names where Accept puts a
    copy of an item that the NPC lost. Only a trade restocks, because the player pays for each copy, and a handover costs
    nothing. An agreement in the barter window adds the DEAL lines, so the window loads only a deal of its own table."""
    trade = offer["category"] == "BARTER" and not offer.get("charity")
    restock = [f"RESTOCK: {'stock' if offer.get('stock') else 'inventory'}"] if trade else []
    shown = boxes(offer) + (deal_lines(offer) if window else []) if offer["category"] == "BARTER" else []
    return "CMD: OFFER: " + "\n".join([str(offer_id), f"{npc_key} {speaker_key}", npc, text, *checks(offer), *restock, *shown])


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


def stem(word):
    return word[:-1] if len(word) > 3 and word.endswith("s") else word


def words_of(text):
    return {stem(word) for word in re.findall(r"[a-z]+", text.lower()) if len(word) >= 3} - COMMON_WORDS


def asked(items, said):
    """The labels of the items that the text names by a word of their name, the grade left out, or by their kind."""
    said_words = words_of(said)
    kinds = {kind for kind, words in KIND_WORDS.items() if said_words & {stem(word) for word in words}}
    labels = []
    for item in items:
        label = item.get("name")
        if label and label not in labels and (said_words & words_of(label.split(" (")[0]) or item.get("kind") in kinds):
            labels.append(label)
    return labels


def price_guide(said, npc, speaker, player_name, relation=None):
    """The count and the price of each item that the text asks for, in the goods of the NPC or of the speaker, at the share
    of the NPC and with the profit that it wants, so the model gives the real price and does no sums. A kind word such as
    "food" can ask for a whole shop, so each side gives at most PRICE_LINES items."""
    sell, buy = shares(npc)
    markup = 1 + profit_share(relation)
    stock = goods(npc, "BARTER")
    carried = speaker.get("inventory") or []
    lines = []
    # The tolerance keeps float noise, such as 3000 * 1.1 = 3300.0000000000005, from moving a price by a cat
    for label in asked(stock, said)[:PRICE_LINES]:
        lines.append(f"You have {held(stock, label)[1]} {label}: you sell each for at least {math.ceil(price_of(label, stock) * sell * markup - 1e-6):,} cats.")
    for label in asked(carried, said)[:PRICE_LINES]:
        lines.append(f"{player_name} has {held(carried, label)[1]} {label}: you pay at most {math.floor(price_of(label, stock, carried) * buy / markup + 1e-6):,} cats each.")
    return lines


def with_lost(npc, lost):
    """The NPC with the items that it lost from the table of the barter window among its goods, because the plugin
    restocks them at Accept."""
    if not lost:
        return npc
    key = "stock" if sells_stock(npc, "BARTER") else "inventory"
    return {**npc, key: [*(npc.get(key) or []), *lost]}


def table_parts(deal):
    """The offer parts of the deal on the table of the barter window. An item of the player's side names its holder."""
    parts = [("GIVE_CATS", str(deal["give_cats"]))] if int(deal.get("give_cats") or 0) > 0 else []
    parts += [("GIVE_ITEM", f"{item['count']} {item['name']}") for item in deal.get("give") or []]
    parts += [("TAKE_CATS", str(deal["take_cats"]))] if int(deal.get("take_cats") or 0) > 0 else []
    parts += [("TAKE_ITEM", f"{item['count']} {item['name']}", str(item.get("holder"))) for item in deal.get("take") or []]
    return parts


def profit_lean(received, handed, gap):
    """The (bonus, reason) of a deal on the table that meets the profit that the NPC wants: the bonus by the profit at the
    NPC's shares, and the reason by the gap at the prices of the price guide. A gift hands over nothing, so it is a big
    profit."""
    share = max(received - handed, 0) / handed if handed else math.inf
    bonus = next(bonus for least, bonus in PROFIT_LEANS if share >= least)
    return bonus, f"The deal on the table beats your desired profit by {math.floor(gap + 1e-6):,} cats." if gap >= 1 else "The deal on the table meets your desired profit."


def on_table(deal, npc, speaker, squad, player_name, relation=None):
    """(offer, reason, lines, lean) of the deal on the table of the barter window: the checked offer that [AGREE] takes, or
    None and the reason, the lines that describe the deal in the turn message, and the (bonus, reason) pairs that the
    profit or the loss adds to the lean. A reason names in cats how far the deal misses or beats the desired profit, so the
    model does no sums."""
    parts = table_parts(deal)
    if not parts:
        return None, "the table is empty", ["Nothing is on the table yet."], []
    offer, reason = check("BARTER", parts, npc, speaker, squad)
    gives = [("CATS", count_of(argument)) if name == "GIVE_CATS" else ("ITEM", item_of(argument)) for name, argument, *_ in parts if name.startswith("GIVE")]
    takes = [("CATS", count_of(argument)) if name == "TAKE_CATS" else ("ITEM", item_of(argument)) for name, argument, *_ in parts if name.startswith("TAKE")]
    lines = [f"On the table, {player_name} gives {goods_text(takes) or 'nothing'}, and they want {goods_text(gives) or 'nothing'} from you."]
    side = dict(speaker, inventory=pooled(squad))
    received, handed = worth(takes, npc, side, "takes"), worth(gives, npc, side, "gives")
    markup = 1 + profit_share(relation)
    # A gap measured from the break-even worth contradicted the price lines of the turn message
    gap = worth(takes, npc, side, "takes", markup) - worth(gives, npc, side, "gives", markup)
    lean = []
    if offer and offer.get("charity"):
        lines.append("It is a plea for charity.")
    elif offer and not offer["gives"]:
        lines.append("It is a gift to you.")
        lean.append(profit_lean(received, handed, gap))
    elif offer and gap + 1e-6 >= 0:
        lean.append(profit_lean(received, handed, gap))
    elif offer:
        missed = f"The deal on the table misses your desired profit by {math.ceil(-gap - 1e-6):,} cats"
        lean.append((SMALL_PROFIT_LEAN, f"{missed}.") if received + 1e-6 >= handed else (LOSS_LEAN, f"{missed}, and you lose on it."))
    else:
        why = next((words.format(player=player_name) + reason[len(start):] for start, words in TABLE_REASONS.items() if reason.startswith(start)), reason)
        lines.append(f"You cannot agree to it as it is, because {why}.")
    return offer, reason, lines, lean


def facts(category, npc, speaker, player_name, lean, said="", table=(), relation=None):
    """The facts of the hard limits and the lean, for the turn message, because they change each turn. said is the text in
    which the price guide of a trade looks for item names, table holds the lines of the deal on the table of the barter
    window, and relation sets the profit that the NPC wants in a trade."""
    lines = []
    if category in ("THREATEN", "BARTER"):
        lines.append(f"You have {cats_of(npc):,} cats.")
    if category == "THREATEN":
        carried = [f"{item.get('count') or 1} {item['name']}" for item in npc.get("inventory") or [] if item.get("name")]
        lines.append(f"You carry: {', '.join(carried)}." if carried else "You carry no items.")
    if category == "BARTER":
        lines.append(f"As charity, you give at most {CHARITY_CATS} cats.")
        if speaker.get("character_state") == "imprisoned":
            lines.append(f"{player_name} is imprisoned." + (" You are imprisoned too." if npc.get("character_state") == "imprisoned" else ""))
        lines += price_guide(said, npc, speaker, player_name, relation)
        lines.append("A trade that gets you more than you give is a profit: the bigger the profit, the more gladly you take it.")
        lines += table
    if category == "HEAL" and speaker.get("needs_repair"):
        lines.append(f"{player_name} has damaged robotic parts, and you repair them with your repair kit." if npc.get("has_repair_kit")
                     else f"{player_name} has damaged robotic parts, but you have no repair kit, so you treat only the flesh wounds.")
    if category == "LIBERATE":
        bounty = speaker.get("bounty") or 0
        lines.append(f"You release {player_name} only for a bribe of at least {release_fee(speaker):,} cats"
                     + (f": the bounty of {bounty:,} cats on {player_name}, and {RELEASE_BRIBE} more." if bounty else "."))
    if category == "FOLLOW" and action_dialogue.mercenary_rate(npc):
        lines.append(f"You are a mercenary: you never follow for free, and you charge at least {action_dialogue.mercenary_rate(npc):,} cats for each day.")
    deal = "DEAL FACTS:\n" + "\n".join(f"- {line}" for line in lines) + "\n\n" if lines else ""
    thought = action_dialogue.thought(lean, player_name)
    # The turn message comes before the reply, so the server cannot tell a plea from a trade, and a plea gets its own band
    if category == "BARTER" and action_dialogue.gave_charity_today(npc):
        plea = action_dialogue.lean_text(sum(bonus for bonus, _ in lean) - 2)
        thought += f"\n- If {player_name} begs for charity: {plea} You already gave charity today."
    return f"{deal}YOUR THOUGHT: {thought}"
