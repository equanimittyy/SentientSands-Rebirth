# Proposal: Dynamic Bounties

Status: Draft for review

## 1. Summary

Kenshi has its own bounties. Police see a wanted character, bounty hunters hunt it, and the law of a faction pays the player for the captive. SSR uses no bounty now: the only deeds are the kills and captures of known figures, and the rumors that the player writes or that SSR spins from conversations ([architecture.md](../info/architecture.md#deeds)).

This plan lets SSR post bounties of its own:

1. Code rolls the bounty without an LLM call: a target from the loaded members of a fixed list of bandit factions, a crime, an amount, and a bonus for each skill. The Holy Nation, the United Cities, and the Shek Kingdom each set the bounty at the same amount ([section 4](#4-roll)).
2. The plugin puts the bounty on the target through the bounty system of the game, raises the target's skills, keeps the target's squad in the save, and marks that squad on the world map ([section 5](#5-target-and-persistence)).
3. The bounty becomes a deed of the new kind `bounty`. The LLM writes its rumor with a prompt of its own, so NPCs gossip about it. The player can delete the deed, but cannot edit its rumor ([section 6](#6-bounty-deeds)).
4. The game pays the reward, as for any vanilla bounty. SSR pays nothing.

The deed lives in the JSON of its `notable` row, so the campaign schema does not change.

Non-goals:

- Wanted posters. The game sells a `WANTED:` item for each vanilla bounty, but SSR adds no item.
- Bounties on characters that are not loaded. The plugin can reach only a loaded character ([section 5](#5-target-and-persistence)).
- A reward that SSR pays, and bounties of factions that have no law to pay them.

## 2. Kenshi bounties

The headers of KenshiLib and the game data files show these facts. The probe confirms the facts that need the game ([section 9](#9-probe)).

| Fact | Source |
|---|---|
| Each character holds one bounty for each faction in `Character::crimes`, a `BountyManager`. | `deps/KenshiLib/Include/kenshi/Character.h:209`, `BountyManager.h:16` |
| A `Bounty` holds the amount and a bit mask of crimes (`CrimeEnum`, 16 crimes). | `Bounty.h:6-38` |
| `unfairAddToBounty(enforcer, amount)` adds to a bounty, and `Bounty::addCrime` adds a crime. | `BountyManager.h:30`, `Bounty.h:37` |
| The bounty saves with the character (`BountyManager::save`). | `BountyManager.h:39` |
| A bounty expires after `getBountyExpirationTime(bounty)`. | `BountyManager.h:58` |
| A faction can have a law enforcement faction (`Faction::getLawEnforcementFaction`). | `Faction.h:123-125` |
| `GameWorld::getCharacterUpdateList` lists each loaded character. | `GameWorld.h:140` |
| `CharStats::getStatRef` gives a writable stat level. | `CharStats.h:80` |
| `Platoon::setPersistentSquad` marks a squad that the game keeps. | `Platoon.h:166-168` |
| `MapScreen::addSquad` puts a squad on the world map, and `removeSquad` takes it off. `ManagementScreen::getSingleton()->mapScreen` gives the map. | `gui/MapScreen.h:64-65`, `gui/ManagementScreen.h:87,129` |
| Most vanilla bounties on generic characters are 500 to 6,000 cats, for example 500 to 1,500 for bar thugs and 4,000 for a Sand Ninja. Unique leaders have 10,000 to 100,000. | `bounty amount` of the CHARACTER records |

## 3. Flow

1. The bounty timer passes, and fewer bounties are open than the setting allows ([section 7](#7-settings)). The server sends `BOUNTY_SCAN` through the pipe, and restarts the timer.
2. The plugin lists the candidates, and posts them to `/bounty/candidates` ([section 8](#8-plugin)).
3. The server rolls the bounty. With no candidate, the pass ends.
4. The server sends `PLACE_BOUNTY` with the roll.
5. On the game thread, the plugin finds the target by the serial of its handle, applies the bounty, and posts the result to `/bounty/placed`.
6. The server stores the target as at a first meeting, so a generic target gets a rolled name, and stores the bounty deed without a rumor.
7. The rumor pass writes the rumor with the bounty prompt in the next quiet period (`write_rumors` in `server/chat/memory.py`).

- A pass makes no LLM call. Only the rumor of a placed bounty costs one, in the existing rumor pass of the deeds.
- The timer counts real time from each scan, also from a scan that finds no candidate, so a game in a place without candidates costs one scan in each period.
- A target that unloads between the scan and `PLACE_BOUNTY` gives a failed result, and the next period tries again.

## 4. Roll

`server/core/bounties.py` rolls the bounty. It imports no Flask, so its tests run in the dev container.

### Factions

The Holy Nation, the United Cities, and the Shek Kingdom issue every bounty (`bounties.ISSUERS`). Each of them sets it with its law, at the same amount and for the same crime. The targets are the members of 16 bandit factions that attack people in general (`bounties.TARGETS`), chosen from the bandit factions of the Kenshi wiki and the default relations of the game data. The server finds the faction of a candidate by the game ID that the plugin sends.

1. The roll keeps each candidate whose faction is a target faction.
2. It picks the target among them at random.

- Rival gangs that fight only certain factions stay out, such as the Reavers, the Crab Raiders, the Red Sabres, and the Swamp Ninjas. So do the tribes, the creatures, the armies, and the Skeleton bandits that attack everyone, such as the Cannibals, the Fogmen, the Second Empire, the Skeleton Legion, and the Thrall Masters.

### Crime and amount

Each of the 16 crimes of `CrimeEnum` can come up, with the same chance. The crime sets the range of the amount, which the roll rounds to 100 cats:

| Tier | Crimes | Amount (cats) |
|---|---|---|
| Petty | Farm eating, trespassing, lockpicking, uniform theft, fencing, looting | 500 to 1,500 |
| Serious | Stealing, smuggling, assault, prison escape, slave freeing, enslaving | 1,500 to 4,000 |
| Grave | Murder, kidnapping, assault of a VIP, terrorism | 4,000 to 10,000 |

- The ranges stay near the vanilla bounties of generic characters, because a target is a generic character.
- The server keeps the crimes in the order of `CrimeEnum` and sends the index, so the list must match the enum of KenshiLib.
- Rejected: a list of crimes for each issuer. It would be invented lore, and a farm eater with a Holy Nation bounty is part of the fun.

### Skill bonus

Each of the 16 combat skills gets a bonus of its own, so a big bounty is a hard fight:

| Group | Skills (`StatsEnumerated`) |
|---|---|
| Attributes | Strength, dexterity, toughness, perception |
| Combat | Melee attack, melee defence, dodge, martial arts |
| Weapons | Katanas, sabres, hackers, heavy weapons, blunt, polearms, crossbows, precision shooting (`STAT_FRIENDLY_FIRE`) |

The roll of each skill:

1. The level L of the bonus is the amount divided by 500, at most 20.
2. For each skill, the roll adds a jitter to L and rounds the sum to whole levels. The jitter comes from a triangular distribution from -2 to 2, with its peak at 0. A bonus is never less than 0.
3. The plugin adds the bonus to the skill, and keeps the skill between 0 and 100.

| Amount (cats) | L | Bonus of one skill (levels) |
|---|---|---|
| 1,200 | 2.4 | 0 to 4 |
| 4,000 | 8 | 6 to 10 |
| 10,000 | 20 | 18 to 22 |

- A higher bounty raises the level of the bonus, but not its spread. The jitter is the same at each level, so the skills of one target differ by a few levels, and no two targets get the same flat bonus.
- Only the combat skills get a bonus. High work skills, such as robotics or smithing, would make the target a prize to recruit instead of a bounty to claim.
- Athletics, stealth, assassination, and turrets get no bonus, because they do not make the target harder to beat in a fight.

The plugin raises the base levels through `CharStats::getStatRef`. The `_skillBonusAttack` and `_skillBonusDefence` fields of `CharStats` hold the bonuses of the equipment (`setEquipmentStatBonuses`), so the next change of equipment would overwrite a bonus there.

## 5. Target and persistence

A target is a loaded character, because a squad that is not loaded has no `Character` object. A candidate is:

- In `getCharacterUpdateList`, alive, and not imprisoned.
- Not unique, because the deeds already track the unique characters, and many of them have vanilla bounties.
- Not an animal, and not in the player's faction.
- Not the target of another open bounty.

A generic roaming squad is temporary, and the game deletes it after it unloads. The plugin marks the target's squad persistent (`Platoon::setPersistentSquad(true)`), so the squad keeps its AI and its members, and stays in the save. The target keeps the `npc_id` of its serial ([kenshi_internals.md](../info/kenshi_internals.md#character-identity)).

The game checks the persistence of a squad again when it unloads (`Platoon::reCheckPersistenceOnUnload`), so the flag can fail for a squad without a unique character. The probe decides. If the flag fails, the fallback is a pool of unique squads in `SentientSandsRebirth.mod`:

- Vanilla keeps a roaming unique squad with a `UNIQUE_SQUAD_TEMPLATE`, which has a `persistent` flag, a leader, members, and a fallback AI package. The squad of the Dust King is one: the Dust King, 5 Dust Bandits, and Patrol map (short range).
- The mod would add such squads that no faction lists under `special squads`, so the game never spawns them alone. The plugin would spawn one for each bounty near the player's squads, and SSR would rename its leader.
- The pool size would cap the bounties of a campaign. Each spawn call is untested: `RootObjectFactory::createRandomSquad`, or the private `FactionUniqueSquadManager::spawnNewUniqueSquad` by its address.

The plugin adds the target's squad to the world map (`MapScreen::addSquad`), so the player can find a roaming target. The probe showed the squad on the map while the squad was unloaded, and after a load.

When the bounty ends, the plugin gives the squad back to the game: it takes the squad off the map (`MapScreen::removeSquad`), and clears the persistent flag that SSR set (`setPersistentSquad(false)`), so the game can delete the squad again after an unload.

- The plugin finds the squad by its handle among the active and the unloaded squads of each faction (`Faction::getActivePlatoons`, `getUnloadedPlatoons`). The handle stays the same through a save and a load ([kenshi_internals.md](../info/kenshi_internals.md#character-identity)), but a squad pointer does not.
- The plugin clears the flag only when the squad was not persistent before the placement. The game keeps some squads itself, such as the residents of a town, and a cleared flag would delete them.
- The server ends the hold only when no other open bounty has a target in the same squad.
- The skill bonus stays, and so does the game bounty of a target that is still alive.

## 6. Bounty deeds

### Storage

The `notable` row holds the game time of the placement, and as JSON:

```json
{"deed": "bounty", "target": {"id": "h:3051296712", "name": "Arleen", "faction": "Dust Bandits"}, "crime": "FARM_EATING", "amount": 1200, "place": "Stack", "expires": 23760}
```

- `expires` is the game time at which the game bounty ends, from `getBountyExpirationTime` at the placement.
- `place` is the town of the target, or its zone outside a town.
- `squad` is the handle of the target's squad (`hand::toString`), which finds the squad when the bounty ends. `persistent` tells whether the squad was persistent before the placement.

### Line and status

The Deed column shows the line of the deed, with its status at the end:

| Status | When |
|---|---|
| Open | No other status holds |
| Captured or Killed | A capture or a kill deed of the player's squad has the target as its victim |
| Expired | The latest game time is after `expires` |

For example: "1,200 cats on Arleen of the Dust Bandits for farm eating. Open."

- The status comes from the other deeds and the game time, so the cull of a kill deed opens the bounty again.
- The target of an open bounty counts as a known figure for the deeds, so its kill or capture by the squad makes a deed and a rumor (`_store` in `server/core/deeds.py:137`).
- A death without the squad leaves the bounty open until it expires. The death of a target that is not loaded makes no game event.
- The setting of open bounties counts the deeds with the status Open.
- When the status leaves Open, the server sends `END_BOUNTY` ([section 5](#5-target-and-persistence)).

### Rumor

The rumor pass writes the rumor of a bounty deed in the next quiet period, as for the other deeds (`write_rumors`), but with `prompt_bounty_rumor.txt` (`rumors.bounty_prompt`). The call takes the `synthesis` task.

- The prompt holds the player's faction, the issuers, the amount, the crime, the target with its race, sex, and faction, the place, and the allies and enemies of the target's faction.
- It asks for one or two sentences of gossip about the wanted character, which tell who pays, how much, for what, and where the target was last seen. A petty crime with a big price can read as a joke.
- The reply is plain text, which `rumors.clean` trims, as for a deed rumor.
- Rejected: the deed rumor prompt. A deed rumor tells the news of a deed that is done, and a bounty rumor is a call to hunt, with a price and a place.

### Edit and delete

- The rumor of a bounty cannot be edited. Its row shows the rumor as text, with no Save, no robot, and no Generate Rumor, and shows Unknown until the rumor exists. The rumor tells the facts of the game bounty, so an edit could give it another price, crime, or faction than the game.
- The routes that save or write a rumor refuse a bounty deed, because both the web app and the in-game Deeds window call them.
- Delete removes the deed and its rumor after a confirmation, as for a custom or an auto deed (`delete_custom_deed`). The game bounty stays, because the plugin can clear it only while the target is loaded. The server sends `END_BOUNTY`, as when the status leaves Open.
- The cull deletes a bounty deed placed after the game time. The game bounty stays in a save that the player keeps.
- Campaign Canon lists no bounty under the Deeds of a squad member, because a bounty has no doers (`deeds.character_deeds`).

## 7. Settings

| Setting | Key | INI key | Default | Effect |
|---|---|---|---|---|
| Radiant bounty timer (min) | `radiant_bounty_minutes` | `RadiantBountyMinutes` | 120 | The shortest real time between two scans |
| Open bounties | `max_open_bounties` | `MaxOpenBounties` | 3 | The most bounties with the status Open. 0 turns the bounties off. |

- The plugin does not use the values, so the server does not send them through `SET_CONFIG`.
- The bounty timer counts in real time, as the radiant rumor timer does ([architecture.md](../info/architecture.md#auto-rumors)).

## 8. Plugin

| Message | Direction | Content |
|---|---|---|
| `BOUNTY_SCAN` | Pipe, server to plugin | None |
| `/bounty/candidates` | HTTP, plugin to server | For each candidate: `npc_id`, name, faction, faction game ID, and place |
| `PLACE_BOUNTY` | Pipe, server to plugin | JSON: the serial of the target, the game IDs of the issuers, the crime index, the amount, and the 16 skill bonuses, each with its `StatsEnumerated` index |
| `/bounty/placed` | HTTP, plugin to server | The detailed context of the target (`GetDetailedContext`), the handle of its squad, whether that squad was persistent before, the game time, and the expiry time, or a failure |
| `END_BOUNTY` | Pipe, server to plugin | The handle of the target's squad, and whether to clear its persistent flag |

`PLACE_BOUNTY` does these steps on the game thread (`ExecuteQueuedActions` in `plugin/game/GameActions.cpp`):

1. It finds the target in `getCharacterUpdateList` by the serial of its handle.
2. It notes whether the target's squad is persistent, and marks it persistent.
3. For each issuer, it calls `unfairAddToBounty` with the law enforcement faction of the issuer and the same amount, and adds the crime to that bounty.
4. It adds the bonus of each skill to its level (`CharStats::getStatRef`).
5. It adds the target's squad to the world map (`MapScreen::addSquad`).

`END_BOUNTY` finds the squad by its handle, takes it off the map (`MapScreen::removeSquad`), and clears its persistent flag when the message says so. A squad that the game deleted is not found, and needs nothing.

The in-game Deeds window gets the kind button Bounty. The rumor of a bounty shows without the edit box and the robot, and Delete removes a bounty deed (`DeletesWholeDeed` in `plugin/ui/EventsWindow.cpp`).

## 9. Probe

Before the build, a debug command of the chat puts a bounty on the chat target, for a faction that it names, with a crime and an amount. It logs:

- The law enforcement faction of each faction (`getLawEnforcementFaction`, `isALawEnforcementFaction`).
- `getTotalBounty` and `getActualBounty` of the target after the call, and `getBountyExpirationTime` of the amount, with its unit.
- `CharStats::getStatName` of each of the 16 combat skills, so the index of precision shooting is sure.

In the game, the probe checks:

1. The character screen shows the bounty and the crime, and the police react to the target.
2. The law of an issuer pays for the captive, and pays half for the body.
3. A roaming squad with `setPersistentSquad(true)`: the player goes far away until the squad unloads, saves, loads, and comes back. The target is there, with the same serial, the bounty, and the raised skills.
4. The raised skills stay after the target changes its equipment.
5. The target's squad shows on the world map while it is unloaded, and after a load.
6. A bounty under 10,000 cats whose start time the probe moved ahead (`Bounty::bountyAssignmentStartedTime`) stays after its expiry time passes and after a load, and the law still pays for the captive.

The result of step 3 decides between the persistent flag and the pool of unique squads ([section 5](#5-target-and-persistence)). The probe results go into [kenshi_internals.md](../info/kenshi_internals.md).

## 10. Build order

1. The probe.
2. The server: the settings, `bounties.py` with its tests, the bounty deed in `deeds.py`, `rumors.py`, and `campaign_db.py`, `prompt_bounty_rumor.txt`, the two routes, the refusal of the rumor routes, and the timer in `memory_loop`.
3. The plugin: `BOUNTY_SCAN`, `PLACE_BOUNTY`, `END_BOUNTY`, and the Deeds window.
4. The web app: the kind Bounty on Deeds, its rumor as text, its delete, the two settings, the bounty prompt on the Prompts page, and the hints.
5. The docs: architecture.md, README.md, and the deletion of this plan.

## 11. Rejected alternatives

| Alternative | Reason |
|---|---|
| SSR pays the reward on a kill or a capture | The cats would come from nowhere, and the game already pays a bounty. |
| Any enemy faction with a police faction as the issuer | Three fixed powers are easy to follow, and need no scan of the police factions. |
| The enemies of the template factions as the targets | The game data gives some of the most common bandits, such as the Starving Bandits, no hostile relation with the three issuers. |
| An LLM picks the target, the crime, or the amount | A weak model picks badly, and code makes the same picks without a call. |
| The plugin rolls the bounty | A roll in Python runs in the unit tests of the dev container. |
| Delete clears the game bounty | The plugin can reach the target only while it is loaded. |
| An editable bounty rumor | An edit could give the rumor another price, crime, or faction than the game bounty. |
| SSR adds the bounty again when it expires | The game decides how long a bounty lasts, as for every other bounty. |
| A unique target | The deeds already track the unique characters, and many of them have vanilla bounties. |

## 12. Verification

Unit tests, which run with the standard library only (`server/tests/`):

- The roll: only a member of a target faction as the target, an amount in the range of the crime and rounded to 100, 16 bonuses within 2 levels of L and not below 0, L at most 20, and no roll without a candidate.
- The filter of the candidates: a unique, an animal, a member of the player's faction, and the target of an open bounty drop out.
- The due check: the timer, the count of open bounties, and 0 open bounties.
- The deed: the line with each status, the facts of the rumor, the known figure check of `_store`, the delete, the cull, `character_deeds`, and `END_BOUNTY` when the status leaves Open and at a delete, with the flag clear only for a squad that SSR made persistent, and no `END_BOUNTY` while another open bounty has a target in the same squad.
- `/bounty/placed`: a failed result stores nothing, and a campaign switch between the scan and the result stores nothing.
- The bounty prompt: the fill names the issuers, the amount, the crime, the target, and the place. The routes that save or write a rumor refuse a bounty deed.

In the game and the web app:

1. Set the bounty timer to 1 minute, and stand near a roaming bandit squad.
2. The server logs the scan and the roll. The target gets a bounty, the world map shows its squad, and Campaign Canon > Deeds shows the bounty deed with the status Open.
3. After the next quiet period, the deed has a rumor, and an NPC who is asked about news may mention the bounty.
4. Capture the target, and hand the captive to the law of an issuer. The game pays, the deed shows Captured, and the squad leaves the map.
5. The rumor of the bounty has no edit box and no robot. Delete the deed. The game bounty stays, and the squad leaves the map.
6. In the in-game Deeds window, the kind button shows Bounty, the rumor has no edit box and no robot, and Delete removes the bounty deed.
