"""The Current Job of an NPC: a short phrase for what the NPC does in game now.

The plugin sends the jobs that the squad of the NPC gives it, as the names of KenshiLib's TaskType enum (RoleJson in
plugin/game/Context.cpp). Mods rename AI packages, squads, and templates freely, but the task types belong to the engine,
so the same squad job gives the same phrase in every mod list.
"""

# In order: the first entry that the squad jobs hold wins. A squad job such as a turret or a bar visit is a side task of
# many guard and town packages, so it comes after the jobs that it would otherwise hide.
TABLE = [
    ({"STAND_AT_SHOPKEEPER_NODE"}, "Running a shop"),
    ({"WANDERING_TRADER"}, "Travelling as a trader"),
    ({"SIT_ON_THRONE"}, "Holding court"),
    ({"MAN_THE_GATE", "STAND_AT_GUARD_NODE_HOMETOWN_OUTSIDE"}, "Guarding the town"),
    ({"STAND_AT_GUARD_NODE_HOMEBUILDING_IN_OUT", "STAND_AT_GUARD_NODE_HOMEBUILDING_INDOORS_ONLY", "STAND_AT_BUILDING_GUARD_NODE",
      "STAND_AT_BUILDING_DEFENSIVE_NODE"}, "Guarding a building"),
    ({"WORK_THE_SLAVES", "NEW_SLAVE_PROCESSING", "PROCESS_AND_STRIP_NEW_SLAVE", "CAPTURE_NEW_SLAVES", "CAPTURE_ESCAPING_SLAVES"},
     "Working as a slaver"),
    ({"HUNT_BOUNTIES", "FIND_CAGE_AND_PUT_IN_IF_BOUNTY"}, "Hunting bounties"),
    ({"POLICE_FREE_PRISONERS_WHEN_DONE"}, "Keeping the peace"),
    ({"AUTO_LABOURING_MINES", "AUTO_LABOURING_MINES_PRETEND", "OPERATE_MACHINERY", "OPERATE_AUTOMATIC_MACHINERY",
      "PRETEND_TO_OPERATE_MACHINERY"}, "Labouring"),
    ({"RAID_TOWN", "ATTACK_TOWN", "ASSAULT_FORTIFICATIONS_PREFER_GATES"}, "Raiding"),
    ({"BODYGUARD"}, "Working as a bodyguard"),
    ({"RELAX_IN_TOWN_PACKAGE", "GO_TO_THE_BAR_AND_DRINK"}, "Hanging out at a bar"),
    ({"PATROL_TOWN"}, "Patrolling the town"),
    ({"PATROL"}, "Patrolling the area"),
    ({"MAN_A_TURRET", "MAN_A_TURRET_ON_BUILDING", "USE_TURRET"}, "Manning a turret"),
    ({"TRAVEL_TO_TARGET_TOWN", "TRAVEL_TO_TARGET_TOWN_FAST", "TRAVEL_TO_TARGET_PACKAGE"}, "Travelling"),
    ({"WANDERER"}, "Wandering"),
    ({"SHOPPING"}, "Shopping"),
    ({"WANDER_TOWN"}, "Wandering the town"),
    ({"FOLLOW_SLAVEMASTER"}, "Serving as a slave"),
    ({"STAY_IN_HOME", "SIT_AROUND"}, "Staying at home"),
    ({"FOLLOW_SQUADLEADER"}, "Travelling with their squad"),
]
TASKS = set().union(*(tasks for tasks, _ in TABLE))


def current_job(ctx, in_player_faction, player_faction):
    """None when the game gives the NPC no squad job that the table knows, for example in a squad without an AI package.
    A hire contract comes first, because a hired NPC follows the player without a recruit."""
    if ctx.get("temporary_follower"):
        return f"Temporary follower of {player_faction}"
    if in_player_faction:
        return f"Member of {player_faction}"
    jobs = set(ctx.get("squad_jobs") or [])
    # A shopkeeper is also a trader, and its shop says more
    if ctx.get("is_trader") and "STAND_AT_SHOPKEEPER_NODE" not in jobs:
        return "Trading"
    return next((phrase for tasks, phrase in TABLE if jobs & tasks), None)
