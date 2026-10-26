"""The jobs that leaders, guards, and traders give through a QUEST action dialogue (docs/info/architecture.md#quests).

Code picks the target, the count, and the reward of each job, with no LLM call, because a model names targets and prices that
the game does not hold. A job belongs to the player faction, so any squad member can take it, work on it, and collect the
reward. Code counts each job from the game events (world_events.take), and the jobs live in the campaign, not in the save, so
a load of an earlier save rewinds them.

It imports no Flask, so its tests run in the dev container, and no world_events, because world_events calls it.
"""

import logging
import random

from chat import rulers
from chat.retrieval import aliases_of, name_words
from core import state
from store import campaign_db

# The band of the relation bonus +2 of an action dialogue (action_dialogue.relation_bonus)
FIGURE_RELATION = 60
RULER_REWARDS = {"leader": 20000, "nobles": 10000}
COUNTS = (3, 8)
DEFEAT_COUNTS = (10, 20)
DEFEAT_REWARD = 100
RELATION_RAISES = {"figure": 30, "faction": 3, "goods": 1}
# The value of each material in the vanilla game data
MATERIAL_VALUES = {"Raw Iron": 150, "Copper": 300, "Animal Skin": 400, "Fabrics": 300, "Hemp": 100, "Cotton": 50, "Raw Meat": 100,
                   "Greenfruit": 60, "Wheatstraw": 40, "Cactus": 30, "Riceweed": 25}
# The kinds of the goods of each class of trader (ItemKind in plugin/game/Context.cpp), and the materials that its crafting
# chains in the vanilla game data start from. Kenshi has no hide or cloth, so Animal Skin takes the place of hide, and both
# Cotton and Fabrics take the place of cloth.
TRADER_CLASSES = (
    ({"food"}, ("Raw Meat", "Wheatstraw", "Greenfruit", "Cactus", "Riceweed")),
    ({"weapon", "crossbow", "ammo"}, ("Raw Iron",)),
    ({"armour"}, ("Raw Iron", "Animal Skin", "Cotton", "Fabrics")),
    ({"limb", "repair", "electronics"}, ("Copper",)),
    ({"drug"}, ("Hemp",)),
    ({"medical"}, ("Hemp",)),
)
# The items of the vendor list Hi tech junk that ItemKind gives the kind goods
ELECTRONICS = {"CPU Unit", "Electrical Components", "Generator Core", "Motor", "Power Core", "Robotics Components"}


def roll(npc, name, roles, goods):
    """A new job of the NPC, or None. name is the Name of the NPC, roles holds leader, guard, and trader
    (action_dialogue.giver_roles), and goods holds the goods of a trader (offers.goods). A leader can give a figure job and a
    faction job, so code picks one of the kinds that pass their gates at random."""
    if faction_held(npc):
        return None
    kinds = {"figure", "faction"} if "leader" in roles else set()
    if "guard" in roles:
        kinds.add("faction")
    if "trader" in roles:
        kinds.add("goods")
    makers = {"figure": lambda: figure_job(npc), "faction": lambda: faction_job(npc), "goods": lambda: goods_job(goods)}
    jobs = [job for job in (makers[kind]() for kind in sorted(kinds)) if job]
    if not jobs:
        return None
    return {**random.choice(jobs), "giver": npc["npc_id"], "giver_name": name, "giver_faction": npc.get("factionID") or ""}


def held(npc):
    """The open or done job that the NPC gave, or None. Only the giver answers for a job and pays it."""
    return next((job for job in campaign_db.quests() if job["giver"] == npc.get("npc_id")), None)


def faction_held(npc):
    """The open or done job that the player faction holds from the faction of the NPC, or None. A faction gives one job at
    a time."""
    return next((job for job in campaign_db.quests() if npc.get("factionID") and job["giver_faction"] == npc["factionID"]), None)


def enemies(npc):
    """The faction records that the faction record of the NPC names as its enemies, by an exact name or an alias. The player
    faction and the faction of the NPC drop out."""
    own = campaign_db.find_faction(npc.get("factionID"), npc.get("faction"))
    if not own:
        return []
    found = {}
    for enemy in _values(own["fields"].get("enemies")):
        record = campaign_db.find_faction(name=enemy)
        if record and not record["is_player"] and record["faction_id"] != own["faction_id"]:
            found[record["faction_id"]] = record
    return list(found.values())


def figure_job(npc):
    """A job to kill or capture the leader or a noble of an enemy faction, only at a good relation. A target drops out when it
    has no canon record, when the game holds it dead or imprisoned, when it is in the player faction, or when another job
    names it, so one kill never pays two jobs."""
    if (npc.get("relation") or 0) < FIGURE_RELATION:
        return None
    canon = _canon()
    fallen = rulers.character_states()
    taken = {job["target"] for job in campaign_db.quests() if job["kind"] == "figure"}
    targets = {}
    for faction in enemies(npc):
        for field, reward in RULER_REWARDS.items():
            for value in _values(faction["fields"].get(field)):
                # A value can name two rulers, such as "Dimak and Buzan", as rulers.current reads it
                for ruler in [value] if name_words(value) in canon else value.split(" and "):
                    npc_id, target = canon.get(name_words(ruler), (None, None))
                    if npc_id and npc_id not in fallen and npc_id not in taken and not _recruited(npc_id):
                        role = "leader" if field == "leader" else "a noble"
                        targets.setdefault(npc_id, {"kind": "figure", "target": npc_id, "target_name": target, "count": 1, "reward": reward,
                                                    "about": f"{role} of {the(faction['name'])}"})
    return random.choice(list(targets.values())) if targets else None


def faction_job(npc):
    targets = enemies(npc)
    if not targets:
        return None
    faction, count = random.choice(targets), random.randint(*DEFEAT_COUNTS)
    return {"kind": "faction", "target": faction["faction_id"], "target_name": faction["name"], "count": count, "reward": count * DEFEAT_REWARD}


def goods_job(goods):
    """A job to bring a material of the class of the trader that its goods do not hold, because the player could buy a
    material that the trader holds and sell it back at the reward."""
    held_names = {str(item.get("name", "")).lower() for item in goods}
    materials = [material for material in trader_materials(goods) if material.lower() not in held_names]
    if not materials:
        return None
    material, count = random.choice(materials), random.randint(*COUNTS)
    return {"kind": "goods", "target": material, "target_name": material, "count": count, "reward": count * MATERIAL_VALUES[material] * 6 // 5}


def trader_materials(goods):
    """The materials of the class that holds at least half of the item stacks of the goods, because a general store sells a
    few items of each class. A trader without a class has none."""
    kinds = ["electronics" if item.get("kind") == "goods" and item.get("name") in ELECTRONICS else item.get("kind") for item in goods]
    return next((materials for wanted, materials in TRADER_CLASSES if kinds and 2 * sum(kind in wanted for kind in kinds) >= len(kinds)), ())


def _canon():
    """The npc_id and the Name of each canon character, by the name words of its Name and of each alias, as rulers.fallen
    matches a name."""
    found = {}
    for (npc_id,), profile, origin, _ in campaign_db.list_records("character"):
        if origin in ("seed", "campaign") and npc_id.startswith("u:"):
            for name in (profile.get("Name"), *aliases_of(profile)):
                if name:
                    found.setdefault(name_words(name), (npc_id, profile.get("Name") or name))
    return found


def _recruited(npc_id):
    live = state.LIVE_CONTEXTS.get(npc_id, {})
    return bool(live.get("factionID")) and live.get("factionID") == state.PLAYER_CONTEXT.get("factionID")


def _values(value):
    return value if isinstance(value, list) else [value] if value else []


def the(faction):
    return faction if faction.lower().startswith("the ") else f"the {faction}"


def job_text(job):
    """What the job asks for, such as "defeat 12 members of the Dust Bandits"."""
    if job["kind"] == "figure":
        return f"kill or capture {job['target_name']}" + (f", {job['about']}" if job.get("about") else "")
    if job["kind"] == "faction":
        return f"defeat {job['count']} members of {the(job['target_name'])}"
    return f"bring {job['count']} {job['target_name']}"


def carried(speaker, item):
    return sum(int(entry.get("count") or 1) for entry in speaker.get("inventory") or [] if str(entry.get("name", "")).lower() == item.lower())


def payable(job, speaker):
    """Whether the reward of a held job is due: the job is done, or the speaker carries the goods of a goods job in full."""
    if job["kind"] == "goods":
        return carried(speaker, job["target"]) >= job["count"]
    return job["state"] == "done"


def progress(job, speaker, player):
    """The sentences of the job and of how far it is, from the view of the NPC, so the model tells them and invents none."""
    goods = job["kind"] == "goods"
    if "id" not in job:
        lines = [f"You want {player} to bring you {job['count']} {job['target_name']}." if goods else f"You want {player}'s group to {job_text(job)}.",
                 f"You pay {job['reward']:,} cats for them." if goods else f"You pay {job['reward']:,} cats when it is done."]
    elif goods:
        lines = [f"You asked {player} to bring you {job['count']} {job['target_name']}, for {job['reward']:,} cats."]
        has = carried(speaker, job["target"])
        lines.append(f"{player} carries the {job['count']} {job['target_name']} that you asked for." if has >= job["count"]
                     else f"{player} carries only {has} of the {job['count']} {job['target_name']}." if has else f"{player} carries none of the {job['count']} {job['target_name']}.")
    else:
        lines = [f"You gave {player}'s group a job: {job_text(job)}, for {job['reward']:,} cats."]
        if job["state"] == "done":
            lines.append(f"{player}'s group has done the job, so you owe it the {job['reward']:,} cats.")
        elif job["kind"] == "faction":
            lines.append(f"{player}'s group has defeated {job['defeats']} of the {job['count']} so far.")
        else:
            lines.append(f"{player}'s group has not killed or captured {job['target_name']} yet.")
    return lines


def heard_text(job, player):
    """The thought of a member of the giver's faction while the faction's job is held, so the NPC sends the player to the
    giver."""
    where = f", and that {job['giver_name']} is at {job['giver_location']}" if job["giver_location"] else ""
    return (f"You heard that {job['giver_name']} of your faction gave {player}'s group a job: {job_text(job)}{where}. Only {job['giver_name']} pays for that job, "
            f"so you have no other work for {player} now.")


def facts(job, speaker, player):
    """The JOB FACTS of the turn message."""
    lines = [*progress(job, speaker, player), "The reward is fixed."]
    return "JOB FACTS:\n" + "\n".join(f"- {line}" for line in lines)


def scene_text(job, speaker, player):
    """The sentences of the chat scene of an NPC that answers for a job (held), so a plain chat line can talk about it."""
    return " ".join(progress(job, speaker, player)) if job else ""


def accept(job, at):
    """Stores a new job, or pays a held one, at the game time at. Returns False when the job no longer stands, for example
    because the player abandoned it, or a load rewound it, while its offer waited."""
    if "id" not in job:
        quest_id = campaign_db.add_quest(job, at)
        if quest_id is not None:
            logging.info(f"QUEST: Took the job {quest_id} of {job['giver_name']}: {job_text(job)}")
        return quest_id is not None
    paid = campaign_db.set_quest_state(job["id"], "paid", at, job["state"])
    if paid:
        logging.info(f"QUEST: Paid {job['reward']:,} cats for the job {job['id']} of {job['giver_name']}.")
    return paid


def rewind(now):
    """Runs before the events of each request that carries a game time, so a load of an earlier save undoes what the jobs
    gained after it."""
    if now and campaign_db.rewind_quests(now):
        logging.info(f"QUEST: The game time went back to {campaign_db.game_time_text(now)}, so the jobs lost what they gained after it.")


def count_defeat(party, at):
    """The game messages by job ID of a knockout or a death of a character that the squad defeated at the game time at, which
    counts toward a faction job against its faction."""
    quest_id = campaign_db.count_quest_defeat(party.get("factionID"), at) if party.get("factionID") else None
    job = campaign_db.quest(quest_id) if quest_id else None
    if not job:
        return {}
    if job["state"] == "done":
        return {quest_id: _done(job)}
    return {quest_id: f"Job for {job['giver_name']}: {job['defeats']} of {job['count']} members of {the(job['target_name'])} defeated."}


def figure_event(victim_id, at):
    """The game messages by job ID of a kill or a capture of a known figure at the game time at, with a squad member as a
    doer. Either event does the job, so the player chooses how to do it."""
    return {quest_id: _done(campaign_db.quest(quest_id)) for quest_id in campaign_db.finish_figure_quests(victim_id, at)}


def giver_died(victim_id, at):
    """The game messages by job ID of a death at the game time at, which fails each job that the dead character gave,
    because only the giver pays a job."""
    notes = {}
    for job in campaign_db.quests():
        if job["giver"] == victim_id:
            notes.update(_fail(job, job["giver_name"], "dead", at))
    return notes


def check(now):
    """Fails each job whose giver the game holds dead, and each open figure job whose target it holds dead or imprisoned, at
    the game time now. A giver in a cage keeps its job, because the player can get it out and then collect. It runs after
    the events of the request, so an event and a state in one request mark the job done, and a game event that a failed
    request lost fails the job. Returns the game messages by job ID."""
    if not now:
        return {}
    fallen, notes = rulers.character_states(), {}
    for job in campaign_db.quests():
        if job["kind"] == "figure" and job["state"] == "open" and job["target"] in fallen:
            notes.update(_fail(job, job["target_name"], fallen[job["target"]], now))
        elif fallen.get(job["giver"]) == "dead":
            notes.update(_fail(job, job["giver_name"], "dead", now))
    return notes


def _fail(job, name, fate, at):
    """The game message by job ID of the failure of the job, or none when the job left its state meanwhile."""
    if not campaign_db.set_quest_state(job["id"], "failed", at, job["state"]):
        return {}
    logging.info(f"QUEST: The job {job['id']} of {job['giver_name']} failed, because {name} is {fate}.")
    return {job["id"]: f"Job failed: {name} is {fate}."}


def _done(job):
    return f"Job done: go back to {job['giver_name']} for the reward."


def entry(job):
    """The row of the job in the Quests tab of the Journal window, with the text of its box."""
    label = job_text(job)
    return {"id": str(job["id"]), "giver": job["giver_name"], "label": f"{job['giver_name']}: {label[:1].upper()}{label[1:]}", "details": details(job)}


def details(job):
    faction = the(job["giver_faction_name"]) if job["giver_faction_name"] else ""
    lines = [f"Giver: {job['giver_name']}{f' of {faction}' if faction else ''}{', last seen at ' + job['giver_location'] if job['giver_location'] else ''}."]
    lines.append(f"Reward: {job['reward']:,} cats.")
    if job["state"] == "done":
        lines.append(f"Progress: Done. Go back to {job['giver_name']} for the reward.")
    elif job["kind"] == "goods":
        lines.append(f"Progress: Bring {job['count']} {job['target_name']} to {job['giver_name']}.")
    elif job["kind"] == "faction":
        lines.append(f"Progress: {job['defeats']} of {job['count']} defeated.")
    else:
        lines.append("Progress: Not done yet.")
    return "\n".join(lines)
