# Proposal: World Events and Rumors

Status: Draft for review

## 1. Summary

The plugin logs game events, and the server can write a rumor from them (`server/chat/synthesis.py`). The chat scene gives each NPC the 5 newest rumors. Rumor writing is off (`RUMOR_SYNTHESIS = False`), because the rumors that it wrote told of nothing that mattered.

The events are mostly noise. In one played session, the plugin logged 3,566 events: 2,389 knockouts, 1,173 attacks, 2 trades, 2 imprisonments, and no death. Nearly all of them were guards of the United Cities against Bonedogs, Gurglers, and Swamp Ninjas. The synthesis gave the newest 100 event lines to the LLM and asked it to find a pattern in them.

The events also lack the facts that a rumor needs:

- A knockout and a death name no attacker (`plugin/main.cpp`), so no event tells who killed whom.
- An event names each character only by its name. Six Bonedogs look the same, and no event tells a unique NPC from a generic one.
- An event has the town of the player when its hook fires (`LogGameEvent` in `plugin/core/Utils.cpp`), not the town where it happened.

This plan replaces the synthesis with four steps:

1. The plugin sends only the kinds of events that can matter, with the facts of each character in them ([section 3](#3-events-from-the-game)).
2. The server groups the events by place and time into incidents, and fixed rules pick the notable incidents ([section 5](#5-incidents)). No LLM decides what matters.
3. The LLM writes one rumor for each notable incident, from the facts of that incident only ([section 7](#7-rumors)).
4. The server counts the kills of each member of the player's faction, and its knockouts of unique NPCs, as deeds ([section 6](#6-deeds)).

The chat scene keeps the 5 newest rumors, as today, and it tells the NPC the deeds of the squad member who speaks ([section 8](#8-prompt)).

Non-goals:

- A knowledge bank for each NPC. Every NPC gets the same newest rumors, as today, until a later NPC knowledge system decides which rumors an NPC knows. The lore retrieval plan has the same non-goal ([proposal_lore_retrieval.md](proposal_lore_retrieval.md#1-summary)).
- The spread of a rumor over time and distance, such as news of a battle at The Hub that reaches Admag days later.
- Events far from the player. Kenshi runs the full game only near the player, so the plugin sees only the deaths and knockouts there. Only a raid and a new owner of a town come from the whole world.
- An upgrade of an existing campaign. The `event` and `rumor` tables change, and `open_campaign` refuses a database of an earlier schema version ([architecture.md](../info/architecture.md#campaign-storage)).

## 2. Probe

The deeds depend on facts of the game that no test has shown. A probe answers them before the build, and ships on its own ([development.md](../info/development.md#probes)).

- `DEATH_PROBE` writes one line for each call of `declareDead_hook`, and of `setProneState_hook` with `PS_KO`. The line holds the kind, the name, the `npc_id`, and the unique, animal, and player flags of the character, its town, and the name, `npc_id`, and faction of each character that `Character::getAllAttackers` gives (`Character.h:555` of KenshiLib).
- `RAID_PROBE` writes one line for each call of `triggerCampaign_hook`: the faction, the target, the faction of the target, and the name of the campaign data.

| Question | Why it matters |
|---|---|
| Does `declareDead` run when a character dies in a fight, bleeds out, or starves? | The played session logged no death in 3,566 events. When `declareDead` does not run, the deaths need another hook, and the deeds wait for it. |
| Does `declareDead` run again when a save with dead bodies loads? | A death at the load would count a kill twice. |
| Does `getAllAttackers` list the attackers when the death hook or the knockout hook runs? | The deeds and the facts of a death need the attackers. |
| Does a death after a knockout, such as a character that bleeds out, have attackers? | When it has none, the plugin keeps the attackers of the knockout ([section 3](#attackers)). |
| Which characters does `isAnimal` mark, for example Bonedogs, Fishmen, and Skeletons? | The plugin drops the deaths of animals. |
| How often does a raid start, and what are its targets? | Every raid is notable, so frequent raids would flood the rumors. |

[kenshi_internals.md](../info/kenshi_internals.md) records the answers, and the build removes the probe.

## 3. Events from the game

### Kinds

| Kind | Hook | Sent when |
|---|---|---|
| `death` | `declareDead_hook` | The character is not an animal, or it is in the player's faction |
| `knockout` | `setProneState_hook` with `PS_KO` | The character is unique |
| `imprisonment` | `setPrisonMode_hook` | The character is unique or in the player's faction |
| `slavery` | `setChainedMode_hook` | The character is unique or in the player's faction |
| `city_transfer` | `setFaction_hook` | The town gets another owner |
| `raid` | `triggerCampaign_hook` | Always |

- The hooks of attacks (`attackingYou_hook`), damage (`applyDamage_hook`), first aid (`applyFirstAid_hook`), trades (`buyItem_hook`), and loot (`isItOkForMeToLoot_hook`) go, because they only log events.
- The filter is in the plugin, so the buffer of 100 events keeps the events that matter. In the played session, the knockouts of generic NPCs alone would fill the buffer 24 times.
- A knockout of a generic NPC is never an event, because most fights in Kenshi end in knockouts. A fight of guards with wanderers would otherwise be a battle.
- The server stops writing the chat lines as events (`chat` in `server/chat/routes.py`), because the dialogue already holds them. No prompt reads the event log, and banter takes its recent lines from the histories of its NPCs.

### Parties

Each character in an event is a party with these fields:

| Field | Source |
|---|---|
| `id` | `GetNpcId` (`plugin/game/Context.cpp:181`), the `npc_id` of the character table |
| `name` | `getName` |
| `faction` | The name of the faction |
| `unique` | `Character::isUnique` |
| `player` | `Faction::isThePlayer` of the faction of the character |
| `animal` | `Character::isAnimal` gives a value |

- An event of a character holds it as `target`, and up to 5 of its attackers as `attackers`. An `imprisonment` or a `slavery` event also holds `on`, which is false when the character is freed.
- A `city_transfer` event holds the town, the old faction, and the new faction. A `raid` event holds the faction, and the name and faction of the target.
- The `id` links an event to a profile. A deed therefore stays with a character after a rename, and two Dust Bandits with one name stay two characters.
- The town of an event is the town of the target (`getCurrentTownLocation`), or none outside a town. The zone is the zone around the camera (`ZoneName`), as for the Current Location ([architecture.md](../info/architecture.md#current-location)), because a death or a knockout happens near the player.
- A `city_transfer` or a `raid` can happen far from the camera, so it has no zone.

### Attackers

`getAllAttackers` gives the characters that attack the target when the hook runs. Kenshi gives no last hit to these hooks, so each attacker counts as a killer.

When the probe shows that a death after a knockout has no attackers, the plugin keeps the attackers of the last knockout of each character, by the serial of its handle. It does this also for a generic character whose knockout it does not send. A death with no attackers takes them. The map holds the last 200 characters.

### Transport

The frame hook sends a report when 50 events wait ([architecture.md](../info/architecture.md#game-events)). After the filter, 50 events can take hours of play, and the events that wait are lost when the game closes. The frame hook therefore also sends a report when the oldest event waited 60 s. The plugin still builds no report while no event waits.

The server drops a repeat: an event with the kind and the target `id` of an event in the same incident, because the knockout hook can fire more than once for one knockout. The repeat check by name and message goes (`record_event_to_history` in `server/core/game.py`), because it also dropped the knockout of any other character with the same name.

## 4. Event store

The `event` table keeps each event as a row:

| Column | Content |
|---|---|
| `game_time` | The game time of the event, in minutes, as in the other tables |
| `kind` | The kind of [section 3](#kinds) |
| `town`, `zone` | The place of the event |
| `incident_id` | The incident of the event ([section 5](#5-incidents)) |
| `data` | The event as JSON, with its parties |

- The `incident` table holds the place, the game time of the last event, and the state of each incident: `open`, `minor`, `pending`, or `written`.
- The campaign keeps its newest 500 events, as today. The trim also deletes an incident with no event left, except a `pending` incident.
- The cull deletes the events, deeds, and rumors after the game time, and each incident with no event left. An incident that keeps some of its events is `open` again, because its rumor told of the culled events.

## 5. Incidents

### Grouping

An incident is a group of events at one place. The place is the town of an event, or its zone outside a town.

- An event joins the open incident of its place when it came at most 1 game hour after the last event of that incident. Otherwise, it starts a new incident.
- A `city_transfer` or a `raid` is always an incident of its own, because it is one fact.
- An incident closes when the newest game time that the server knows is more than 1 game hour after its last event. The server checks this at each request that carries a game time.
- **Generate World Event** in the in-game Events window closes each open incident at once ([section 9](#9-web-app-and-game-windows)).

### Notable incidents

A closed incident is `pending`, which means that it waits for its rumor, when one of these rules is true. Otherwise it is `minor`.

| Rule | Example |
|---|---|
| A unique character died, was knocked out, or was imprisoned, enslaved, or freed | The Dust King died at The Hub. |
| A member of the player's faction died, or was imprisoned, enslaved, or freed | Izumi was put in chains at Clownsteady. |
| A town got another owner | Bad Teeth went to the Holy Nation Outlaws. |
| A raid started | The Holy Nation sent a raid against an outpost of Nameless. |
| At least 5 characters died | Five Dust Bandits died at The Hub. |
| At least 3 characters died, and a member of the player's faction attacked one of them | Izumi and Stick killed three Dust Bandits. |

- A minor incident gets no rumor, but its kills still count as deeds.
- In the played session of [section 1](#1-summary), every knockout was of a generic NPC, so none of them reaches the server.
- The 1 game hour and the counts 5 and 3 are starting values. Play tunes them.

Rejected:

- An LLM that picks the notable events from the log. It must still read all the noise, and the old synthesis showed that it then finds a pattern in the noise.
- A score with a weight for each kind of event. A fixed rule is easier to test, and the Events list can show which rule an incident met.

## 6. Deeds

The `deed` table holds one row for each kill by a member of the player's faction, and for each knockout of a unique character by one. A row holds the `npc_id` and the name of the doer, the kind, the `npc_id`, name, and faction of the victim, whether the victim is unique, and the game time.

- A death gives a kill to each attacker in the player's faction. A knockout of a unique character gives a knockout to each such attacker.
- The `player` flag of the event decides. A kill before a recruit therefore does not count, and a kill by a squad member who later leaves stays.
- A victim in the player's faction gives no deed.
- The plugin sends no death of an animal outside the player's faction, so an animal never counts as a kill.
- No deed is trimmed, because a count must stay whole for the whole campaign. A deed is a short row.
- The cull deletes the deeds after the game time.

## 7. Rumors

### Facts

The server writes the facts of an incident as plain sentences, and the LLM gets only these facts:

```
Place: The Hub, in the Border Zone.
Time: Day 12, from 14:05 to 14:50.
The player's faction: Nameless, a group of drifters.
Facts:
- Dust King of the Dust Bandits died. Izumi and Stick of Nameless attacked.
- 5 other members of the Dust Bandits died. Members of Nameless attacked 3 of them.
```

- A unique character and a member of the player's faction have their names. Other characters are counted by faction, because the name of a generic character, such as Dust Bandit, tells nothing more.
- A death and a knockout of the same character give only the death.
- A new owner of a town and a raid give one fact each, with the factions.

### Prompt

`prompt_world_synthesis.txt` gets the facts and these rules:

1. Write one rumor of 1 or 2 sentences, as people of the wasteland tell it.
2. Say only what the facts say. Add no cause, no outcome, and no name.
3. The player's faction has no fame beyond these facts.
4. Write only the text of the rumor.

The block of the earlier rumors goes, because each rumor now tells of a different incident. The language instruction stays.

Example of a rumor from the facts above: "Word from The Hub is that the Dust King is dead, cut down by two drifters who call themselves Nameless, and five of the gang went down too."

### Writing

The rumor writer runs in the quiet period of the memory loop, after the memories (`memory_loop` in `server/chat/memory.py`). A local model serves one request at a time, so a chat must not wait for a rumor.

- The writer writes the rumors of the pending incidents, oldest first, with one call of the `synthesis` task for each.
- A failed call leaves the incident `pending` for the next quiet period. A stored rumor makes its incident `written`, so a deleted rumor is not written again.
- A campaign switch during a call drops the rumor, as for a memory.
- The game shows "A new world rumor is spreading." for each new rumor, as today.
- `RUMOR_SYNTHESIS`, `synthesis_loop`, and the Event timer of the Settings page (`synthesis_interval_minutes`) go.

The `rumor` table holds the text, the game time of the last event of the incident, and the incident. The `- [Day 12, 14:50] [RUMOR: ...]` line goes, and with it the parse of that line in `scene_text.py`, `core/routes.py`, `editor.js`, and `scripts/mock_test.py`. The rule that turns brackets in an edited rumor into parentheses goes too.

## 8. Prompt

### Rumors

The scene keeps the 5 newest rumors (`PROMPT_RUMORS`) with their age, as today (`rumors_text`). It reads the text of the rumor rows instead of the `[RUMOR: ...]` lines.

Rejected: an order by the town, the zone, and the faction of the NPC. Which rumors an NPC knows is the task of a later NPC knowledge system, and an order by place would only guess at it.

### Deeds

The player section of the scene gets one sentence about the deeds of the squad member who speaks (`player_text` in `server/chat/scene_text.py`). The sentence is there only when that member has at least 5 kills, or a deed against a unique character:

"People say they have killed more than ten people, among them the Dust King, and that they beat Burn in a fight."

- The count is a phrase from a fixed scale, as the other numbers of the scene: several (5 to 9), more than ten (10 to 24), dozens of (25 to 99), and more than a hundred.
- The sentence names up to 3 unique victims, newest first.
- The sentence starts with "People say", because the NPC did not see the deeds, and it can doubt them.
- Banter uses the same player section, so it gets the deeds of squad slot 1.
- The scene is a snapshot of the conversation, so a new deed reaches the next conversation.

## 9. Web app and game windows

- **Campaign Log > Events** lists each event with the state of its incident (`minor`, `pending`, or `written`) and the rule that it met. The player can see why a fight gave no rumor. The `EVENT_LINE` parse of `editor.js` goes.
- On Campaign Canon, Other Details of a character show its count of kills and its deeds against unique characters, read-only, as for the Current Job.
- The Dynamic World Events Log in game lists the rumors, as today. **Generate World Event** closes each open incident and writes the rumor of the oldest pending incident at once. The quiet period writes the rest, because the game stops waiting for a reply after 60 s.

## 10. Verification

1. [kenshi_internals.md](../info/kenshi_internals.md) records the answers of the probe of [section 2](#2-probe).
2. `server/tests/test_world_events.py` covers:
   - the grouping: the same place within 1 game hour, another place, a gap of more than 1 game hour, and a `city_transfer` or a `raid` alone;
   - the close by game time, and the close by Generate World Event;
   - each rule of [section 5](#notable-incidents), with one death fewer than each count, and exactly each count;
   - a repeat of an event;
   - the deeds: one kill for each attacker in the player's faction, the `player` flag at the time of the event, the knockout of a unique character, and no deed for a victim in the player's faction;
   - the cull of events, deeds, and rumors, and an incident that is `open` again;
   - the facts of an incident: names and counts, and a knockout before a death of the same character;
   - the 5 newest rumors in the scene, from the rumor rows;
   - the deed sentence: each step of the scale, the threshold, and the 3 unique victims.
3. In game:
   - Watch guards fight Bonedogs, and knock out generic NPCs. No event reaches the server.
   - Fight Dust Bandits at The Hub with two squad members until 3 of the bandits die. After 1 game hour and a chat, the Events list shows one `pending` incident. After the quiet period, the incident is `written`, and its rumor names Nameless and the Dust Bandits.
   - Knock out a unique NPC. Its incident is `pending`, and the doers get a knockout deed.
   - Chat as a squad member with 5 kills. The scene in `llm.log` has the deed sentence.
   - Save, fight, load the save, and cull. The deeds and rumors of the fight are gone.
4. The full server test suite passes.

## 11. Open questions

1. Should the kills of animals count as deeds, such as the kill of a Beak Thing?
2. Should the scene also give the deeds of the whole player's faction, not only those of the squad member who speaks?
3. Does a player with a small local model need a switch that turns rumor writing off? Each notable incident costs one LLM call.
4. Should lore retrieval also search the rumors, so that "What happened at The Hub?" finds them?
