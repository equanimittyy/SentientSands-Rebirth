# Proposal: Dynamic Bounties

Status: Built, not tested in the game. [architecture.md](../info/architecture.md#bounties) describes the built system.

## 1. Summary

Kenshi has its own bounties. Police see a wanted character, bounty hunters hunt it, and the law of a faction pays the player for the captive. SSR uses no bounty now: the only deeds are the kills and captures of known figures, and the rumors that the player writes or that SSR spins from conversations ([architecture.md](../info/architecture.md#deeds)).

This plan lets SSR post bounties of its own:

1. Code rolls the bounty without an LLM call: a target from the loaded members of a fixed list of bandit factions, a reason from a pool with its crime, an amount, and a bonus for each skill. The Holy Nation, the United Cities, and the Shek Kingdom each set the bounty at the same amount, or the nearest faction with its own law when none of them stands ([section 4](#4-roll)).
2. The plugin puts the bounty on the target through the bounty system of the game, raises the target's skills, keeps the target's squad in the save, and marks that squad on the world map ([section 5](#5-target-and-persistence)).
3. The bounty becomes a deed of the new kind `bounty`. The target gets a rolled name and a provisional profile, as at a first meeting. The LLM then writes a wanted notice, which the Deeds page shows as the deed, a rumor, which NPCs gossip about, and an alias for the target, which goes into the target's profile. The player can delete the deed, but cannot edit its notice or its rumor ([section 6](#6-bounty-deeds)).
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
6. The server stores the target as at a first meeting (`characters.new_profile`), so a generic target gets a rolled name and a provisional profile, and stores the bounty deed without a rumor.
7. The rumor pass writes the notice, the rumor, and the alias with the bounty prompt in the next quiet period (`write_rumors` in `server/chat/memory.py`).

- A pass makes no LLM call. Only the rumor of a placed bounty costs one, in the existing rumor pass of the deeds.
- The timer counts real time from each scan, also from a scan that finds no candidate, so a game in a place without candidates costs one scan in each period.
- A target that unloads between the scan and `PLACE_BOUNTY` gives a failed result, and the next period tries again.

## 4. Roll

`server/core/bounties.py` rolls the bounty. It imports no Flask, so its tests run in the dev container.

### Factions

The Holy Nation, the United Cities, and the Shek Kingdom issue every bounty (`bounties.ISSUERS`). Each of them that still holds a town sets it with its law, at the same amount and for the same crime. A major faction that holds no town counts as eliminated by the player. The targets are the members of 27 bandit factions (`bounties.TARGETS`), a fixed list chosen by hand from the bandits, the raiders, the rebels, and the vagrants of the Kenshi wiki and the game data. The server finds the faction of a candidate by the game ID that the plugin sends.

1. The roll keeps each candidate whose faction is a target faction.
2. It picks the target among them at random.

- The gangs of the Swamp that are bandits are targets: the Red Sabres, the Swamp Ninjas, the Swamp Ruffians, the Blue Cleavers, and the Green Katanas. The five gangs that run the towns of the Swamp, such as the Hounds, are not.
- The Vagrants are the starving vagrants of a vanilla game, and the Starving Vagrants are those of a UWE game. The Vagrants also hold the bar thugs and some bar patrons, so these can get a bounty too.
- The Reavers and the Crab Raiders stay out of the targets. So do the tribes, the creatures, the armies, and the Skeleton bandits that attack everyone, such as the Cannibals, the Fogmen, the Second Empire, the Skeleton Legion, and the Thrall Masters.

When no major faction holds a town, the plugin picks a fallback issuer (`NearestLaw` in `plugin/game/Context.cpp`):

1. It keeps each faction that is its own law enforcement faction, and is neither the player's faction nor the target's faction.
2. It drops each faction that is a friend of the target's faction, with a relation above 0 either way.
3. It picks the faction that holds the town closest to the target.

The fallback issuers are the 42 factions other than the three major factions that are their own law enforcement faction in the faction probe of one UWE game. This table gives the targets that each of them can post a bounty on, from the starting relations of the vanilla and UWE game data. A target drops out when its relation with the issuer is above 0 either way, and the number is the higher relation. The plugin reads the relation in the game at the placement, so a relation that changes in play changes the table. A faction that holds no town is never picked.

| Fallback issuer | Targets |
|---|---|
| Anti-Slavers | All 27 except Rebel Farmers (+30) |
| Bele'coz | All 27 |
| Blackshifters | All 27 |
| Cannibal Hunters | All 27 except Rebel Farmers (+60) |
| Crab Raiders | All 27 except Dune Renegades (+30) |
| Deadcat | All 27 |
| The Dominion | All 27 |
| Dune Renegades | All 27 except Dune Renegades, its own faction, Hook Raiders (+100), and Rebel Farmers (+100) |
| Empire Peasants | All 27 except Dune Renegades (+50), Hook Raiders (+30), and Rebel Farmers (+100) |
| Flotsam Ninjas | All 27 |
| Free Traders | All 27 |
| Grayflayers | All 27 |
| Herdsmen | All 27 |
| Highlanders | All 27 except Band of Bones and Berserkers (+30 each) |
| Holy Nation Outlaws | All 27 except Dust Bandits, Hill Marauders, and Starving Bandits (+30 each) |
| Hook Raiders | All 27 except Hook Raiders, its own faction, Dune Renegades (+100), and Rebel Farmers (+100) |
| Hounds | All 27 |
| Inhuman Hunters | All 27 |
| Kobura Syndicate | All 27 |
| Mechanical Hive | All 27 |
| Mercenary Police | All 27 |
| Midland Hive | All 27 |
| Narko's Disciples | All 27 |
| Natives | All 27 |
| Northern Hive | All 27 except Dune Renegades, Rebel Farmers, and Yabuta Outlaws (+30 each) |
| Northern Nobles | All 27 |
| The Order of Chitrin | All 27 |
| Police | All 27 |
| Reavers | All 27 |
| The Reawakened | All 27 |
| Rebel Farmers | All 27 except Rebel Farmers, its own faction, Dune Renegades (+100), and Hook Raiders (+100) |
| Republic of Tertius | All 27 |
| Savage Hive | All 27 |
| Skeletons | All 27 except The Deluged (+30) |
| Southern Nobles | All 27 |
| The Sturmijaz | All 27 |
| Swampers | All 27 |
| Tech Hunters | All 27 except Band of Bones, Berserkers, Rebel Farmers, Starving Bandits, Starving Vagrants, The Bastards, and The Deluged (+30 each) |
| Traders Guild | All 27 |
| Twinblades | All 27 |
| Western Hive | All 27 |
| Western Nobles | All 27 |

### Reason, crime, and amount

The roll picks a reason from `server/data/defaults/bounty_reasons.json`, with the same chance for each. A reason is a sentence in the past tense, such as "They killed a camp of miners for the ore in their packs.", and names the crime of `CrimeEnum` that the game bounty gets.

- The pool holds only the crimes that fit the amounts: murder, kidnapping, terrorism, assault, assault of a VIP, and stealing. A petty crime, such as farm eating or trespassing, would not be worth thousands of cats.
- The kinds of crime come from the bounty notices of the game, the descriptions of the `WANTED:` items of vanilla and UWE. Each reason is new, and none copies a notice.
- No reason names a faction, a town, or a person, because all three issuers post each bounty. The LLM adds the place.
- Each reason uses "they", as the texts of the provisional profile do, so no reason needs a gendered pronoun.

The amount is 2,000 to 15,000 cats, with the same chance for each, rounded to 100 cats.

- Every amount is at least 2,000 cats, above most vanilla bounties of generic characters, so each SSR bounty is worth a hunt.
- From 10,000 cats, the game never lets a bounty expire.
- The server keeps the crimes in the order of `CrimeEnum` and sends the index, so the list must match the enum of KenshiLib.
- Rejected: reasons for each issuer. One bounty has all three issuers, so its reason must fit each of them.

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
| 2,000 | 4 | 2 to 6 |
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

The probe showed that the flag holds through an unload, a save, and a load ([kenshi_internals.md](../info/kenshi_internals.md#bounties)), so SSR needs no squads of its own.

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
{"deed": "bounty", "target": {"id": "h:3051296712", "name": "Arleen", "faction": "Dust Bandits"}, "reason": "They killed a camp of miners for the ore in their packs.", "crime": "MURDER", "amount": 3200, "issuers": ["The Holy Nation", "United Cities", "Shek Kingdom"], "place": "Stack", "expires": 6023760, "squad": "0-2714-11-3051296700-4", "persistent": false, "notice": "WANTED: Arleen the Pickaxe, ..."}
```

- `reason` and `crime` are the rolled reason and its crime.
- `expires` is the game time at which the game bounty ends, from the moved start time and `getBountyExpirationTime` at the placement.
- `issuers` are the names of the factions that posted the bounty in the game.
- `notice` is the wanted notice, which the rumor pass adds with the rumor.
- `place` is the town of the target, or its zone outside a town.
- `squad` is the handle of the target's squad (`hand::toString`), which finds the squad when the bounty ends. `persistent` tells whether the squad was persistent before the placement.

### Columns and status

A bounty is not a deed of the player's squad, so its Deed column shows the wanted notice, and Unknown until the notice exists. The Rumor column shows its rumor. The Kind column shows its status after the kind, for example "Bounty (Open)":

| Status | When |
|---|---|
| Open | No other status holds |
| Captured or Killed | A capture or a kill deed of the player's squad has the target as its victim |
| Expired | The latest game time is after `expires` |

- The status comes from the other deeds and the game time, so the cull of a kill deed opens the bounty again.
- The target of an open bounty counts as a known figure for the deeds, so its kill or capture by the squad makes a deed and a rumor (`_store` in `server/core/deeds.py:137`).
- A death without the squad leaves the bounty open until it expires. The death of a target that is not loaded makes no game event.
- The setting of open bounties counts the deeds with the status Open.
- When the status leaves Open, the server sends `END_BOUNTY` ([section 5](#5-target-and-persistence)).

### Rumor and alias

The rumor pass writes the rumor of a bounty deed in the next quiet period, as for the other deeds (`write_rumors`), but with `prompt_bounty_rumor.txt` (`rumors.bounty_prompt`). The call takes the `synthesis` task, and writes the notice, the rumor, and the alias of the target in one reply.

- The prompt holds the amount, the reason with its crime, the place, the target's profile (name, race, sex, faction, personality, and backstory), and the allies and enemies of the target's faction.
- It asks for a wanted notice as the bounty notices of the game are written: the name and the alias, the crime, a warning to the hunter, and the reward in cats.
- It asks for a rumor as a fanciful tale of the bars, not a copy of the notice: hearsay and exaggeration about the target from the crime, the personality, and the backstory, with the alias, the amount, and the place where the target was last seen. The hearsay invents no other crime, victim, or reward.
- The notice names the issuer only when one faction posted the bounty. The three major factions are the usual payers, so naming them adds nothing.
- It asks for an alias of 1 to 3 words that fits the reason and the profile, blunt and crude as the bounty notices of Kenshi name their targets, such as "Four-Teeth" or "the Gutless". The prompt gives such names only as examples, and the alias never reuses one.
- The reply is JSON with `notice`, `rumor`, and `alias`. `rumors.clean` trims each. A reply without all three stores nothing, so the deed waits for the next pass, as a deed with a failed call does.
- `campaign_db.add_bounty_rumor` adds the rumor and the notice in one write.
- NPCs tell the rumor only while the bounty is open (`deeds.told_rumors`), because the kill or the capture of the target has a rumor of its own. The Deeds page keeps it.
- The server writes the alias into the `Alias` field of the target's profile, unless the field already holds one.
- Rejected: the deed rumor prompt. A deed rumor tells the news of a deed that is done, and a bounty rumor is a call to hunt, with a price and a place.

### Alias field

The character profile gets the field `Alias`: the name by which the bounty notices know the character.

- Campaign Canon shows the field under the name, and the player can edit it.
- The character's own prompt holds it, so the target knows the name that the notices give it.
- Other NPCs know the alias from the rumor, so the name matching of the server needs no change.

### Edit and delete

- The notice and the rumor of a bounty cannot be edited. The row shows the rumor as text, with no Save, no robot, and no Generate Rumor, and shows Unknown until the rumor exists. Both tell the facts of the game bounty, so an edit could give them another price, crime, or faction than the game.
- The routes that save or write a rumor refuse a bounty deed, because both the web app and the in-game Deeds window call them.
- Delete removes the deed and its rumor after a confirmation, as for a custom or an auto deed (`delete_custom_deed`). The game bounty stays, because the plugin can clear it only while the target is loaded. The server sends `END_BOUNTY`, as when the status leaves Open. The alias stays in the profile, where the player can edit it.
- The cull deletes a bounty deed placed after the game time. The game bounty stays in a save that the player keeps.
- Campaign Canon lists no bounty under the Deeds of a squad member, because a bounty has no doers (`deeds.character_deeds`).

## 7. Settings

| Setting | Key | INI key | Default | Effect |
|---|---|---|---|---|
| Radiant bounty timer (min) | `radiant_bounty_minutes` | `RadiantBountyMinutes` | 60 | The shortest real time between two scans |
| Open bounties | `max_open_bounties` | `MaxOpenBounties` | 3 | The most bounties with the status Open. 0 turns the bounties off. |

- The plugin does not use the values, so the server does not send them through `SET_CONFIG`.
- The bounty timer counts in real time, as the radiant rumor timer does ([architecture.md](../info/architecture.md#auto-rumors)).

## 8. Plugin

| Message | Direction | Content |
|---|---|---|
| `BOUNTY_SCAN:` | Pipe, server to plugin | None |
| `/bounty/candidates` | HTTP, plugin to server | For each candidate: `npc_id`, name, faction, faction game ID, and place |
| `PLACE_BOUNTY: serial\|crime\|amount\|issuers\|bonuses` | Pipe, server to plugin | The serial of the target, the crime as its `CrimeEnum` value, the amount, the game IDs of the issuers separated by commas, and `stat:bonus` for each of the 16 skills with its `StatsEnumerated` value |
| `/bounty/placed` | HTTP, plugin to server | `placed`, the handle of the target's squad, whether that squad was persistent before, `expires` in game minutes, the names of the factions that posted the bounty, and the detailed context of the target (`GetDetailedContext`), or `placed` false with a reason |
| `END_BOUNTY: squad\|clear` | Pipe, server to plugin | The handle of the target's squad, and 1 to clear its persistent flag |

`PLACE_BOUNTY` does these steps on the game thread (`ProcessMessageQueue` calls `PlaceBounty` in `plugin/game/Context.cpp`):

1. It finds the target in `getCharacterUpdateList` by the serial of its handle.
2. It keeps each issuer that holds a town, or the fallback issuer when none does ([section 4](#factions)).
3. For each issuer, it calls `unfairAddToBounty` with the law enforcement faction of the issuer and the same amount, adds the crime to that bounty, and moves the start time of that bounty 100,000 game hours ahead.
4. It notes whether the target's squad is persistent, and marks it persistent.
5. It adds the target's squad to the world map (`MapScreen::addSquad`).
6. It adds the bonus of each skill to its level (`CharStats::getStatRef`).

`END_BOUNTY` finds the squad by its handle, takes it off the map (`MapScreen::removeSquad`), and clears its persistent flag when the message says so. A squad that the game deleted is not found, and needs nothing.

The in-game Deeds window gets the kind button Bounty. A bounty shows its notice as its deed, Generate Rumor and Edit Rumor refuse it, and Delete removes a bounty deed (`DeletesWholeDeed` in `plugin/ui/EventsWindow.cpp`).

## 9. Probe

The bounty probe answered the questions of the game, and the build removed it. [kenshi_internals.md](../info/kenshi_internals.md#bounties) holds its results. Two checks are still open, and the in-game test of [section 12](#12-verification) covers them:

1. The raised skills stay after the target changes its equipment.
2. A bounty under 10,000 cats whose start time moved ahead (`Bounty::bountyAssignmentStartedTime`) stays after its expiry time passes and after a load, and the law still pays for the captive.

## 10. Build order

1. The probe.
2. The server: the settings, `bounties.py` with its tests, the bounty deed in `deeds.py`, `rumors.py`, and `campaign_db.py`, `prompt_bounty_rumor.txt`, the `Alias` field in the character prompt, the two routes, the refusal of the rumor routes, and the timer in `memory_loop`. The reason pool `bounty_reasons.json` is already written.
3. The plugin: `BOUNTY_SCAN`, `PLACE_BOUNTY`, `END_BOUNTY`, and the Deeds window.
4. The web app: the kind Bounty on Deeds with its status, its notice as its deed, its rumor as text, its delete, the `Alias` field on Campaign Canon, the two settings, the bounty prompt on the Prompts page, and the hints.
5. The docs: architecture.md, README.md, and the deletion of this plan.

## 11. Rejected alternatives

| Alternative | Reason |
|---|---|
| SSR pays the reward on a kill or a capture | The cats would come from nowhere, and the game already pays a bounty. |
| Any enemy faction with a police faction as the issuer while a major faction stands | Three fixed powers are easy to follow. The scan of the police factions runs only when no major faction stands. |
| The enemies of the template factions as the targets | The game data gives some of the most common bandits, such as the Starving Bandits, no hostile relation with the three issuers. |
| An LLM picks the target, the reason, the crime, or the amount | A weak model picks badly, and code makes the same picks without a call. |
| The plugin rolls the bounty | A roll in Python runs in the unit tests of the dev container. |
| Delete clears the game bounty | The plugin can reach the target only while it is loaded. |
| An editable bounty rumor | An edit could give the rumor another price, crime, or faction than the game bounty. |
| SSR adds the bounty again when it expires | The game decides how long a bounty lasts, as for every other bounty. |
| A unique target | The deeds already track the unique characters, and many of them have vanilla bounties. |

## 12. Verification

Unit tests, which run with the standard library only (`server/tests/`):

- The roll: only a member of a target faction as the target, a reason of the pool with its crime, an amount from 2,000 to 15,000 and rounded to 100, 16 bonuses within 2 levels of L and not below 0, L at most 20, and no roll without a candidate.
- The pool: each reason names a crime of `CrimeEnum`, and no two reasons share a text (`test_bounties.py`).
- The filter of the candidates: a unique, an animal, a member of the player's faction, and the target of an open bounty drop out.
- The due check: the timer, the count of open bounties, and 0 open bounties.
- The deed: the notice as its deed, Unknown before it, and each status after its kind, the facts of the rumor, the known figure check of `_store`, the delete, the cull, `character_deeds`, and `END_BOUNTY` when the status leaves Open and at a delete, with the flag clear only for a squad that SSR made persistent, and no `END_BOUNTY` while another open bounty has a target in the same squad.
- `/bounty/placed`: a failed result stores nothing, and a campaign switch between the scan and the result stores nothing.
- The bounty prompt: the fill names the amount, the issuer only when one faction posted the bounty, the reason, the target with its profile, and the place. A reply without the notice, the rumor, or the alias stores nothing. The alias goes into a profile only when its `Alias` field is empty. The routes that save or write a rumor refuse a bounty deed.

In the game and the web app:

1. Set the bounty timer to 1 minute, and stand near a roaming bandit squad.
2. The server logs the scan and the roll. The target gets a bounty, the world map shows its squad, and Campaign Canon > Deeds shows the bounty deed with the status Open.
3. After the next quiet period, the deed shows a wanted notice, it has a rumor, the target's profile on Campaign Canon has an alias, and an NPC who is asked about news may mention the bounty.
4. Capture the target, and hand the captive to the law of an issuer. The game pays, the deed shows Captured, and the squad leaves the map.
5. The rumor of the bounty has no edit box and no robot. Delete the deed. The game bounty stays, and the squad leaves the map.
6. In the in-game Deeds window, the kind button shows Bounty, Generate Rumor and Edit Rumor refuse the bounty, and Delete removes the bounty deed.
7. Post `/bounty 2000` on a bandit, and leave the bounty open for 100 game hours, longer than the 80 hours that the game would give it without the moved start time. Save and load. The bounty stays, and the law pays for the captive.
8. Swap the target's weapon and armour. The raised skills stay.
9. In a game where the three major factions stand, the log shows no `holds no town` line at a placement, and the deed holds all three issuers.
10. In a save where none of the three holds a town, the log names the fallback issuer, the game bounty is of that faction, and the notice names it.
