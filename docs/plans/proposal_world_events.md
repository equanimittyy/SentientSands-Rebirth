# Proposal: World Events and Rumors

Status: Draft for review

## 1. Summary

The plugin logs game events, and the server can write a rumor from them (`server/chat/synthesis.py`). The chat scene gives each NPC the 5 newest rumors. Rumor writing is off (`RUMOR_SYNTHESIS = False`), because the rumors that it wrote told of nothing that mattered.

The events are mostly noise. In one played session, the plugin logged 3,566 events: 2,389 knockouts, 1,173 attacks, 2 trades, 2 imprisonments, and no death. Nearly all of them were guards of the United Cities against Bonedogs, Gurglers, and Swamp Ninjas. The synthesis gave the newest 100 event lines to the LLM and asked it to find a pattern in them.

The events also lack the facts that a rumor needs:

- A knockout and a death name no attacker (`plugin/main.cpp`), so no event tells who killed whom.
- An event names each character only by its name. Six Bonedogs look the same, and no event tells a unique NPC from a generic one.
- An event has the town of the player when its hook fires (`LogGameEvent` in `plugin/core/Utils.cpp`), not the town where it happened.

This plan makes the rumors tell of what the player's squad achieved:

1. The plugin sends only the deaths and the captures in which a member of the player's faction took part, with the facts of each character in them ([section 3](#3-events-from-the-game)).
2. The server keeps them as deeds ([section 4](#4-deeds)). When the deeds reach a threshold, the server adds a notable event to the log, such as "Beep has killed 100 members of the Dust Bandits", "Beep has killed 100 Beak Things", or "Beep and Izumi of Nameless captured Tinfist" ([section 5](#5-notable-events)).
3. SSR writes no rumor by itself. On the web app, the player picks a notable event, writes an instruction such as "Beep is known as the Stickman of the Dust", and generates a rumor, as for a bio ([section 6](#6-rumors)). The player reads and edits the text, and a save makes it a world rumor. The rumor of a kill count grows with the count, from "hundreds of bandits" to "countless".
4. The chat scene keeps the 5 newest rumors, as today ([section 7](#7-prompt)).

Non-goals:

- A knowledge bank for each NPC. Every NPC gets the same newest rumors, as today, until a later NPC knowledge system decides which rumors an NPC knows. The lore retrieval plan has the same non-goal ([proposal_lore_retrieval.md](proposal_lore_retrieval.md#1-summary)).
- Events in which the squad takes no part, such as the death of a known figure by other hands, a raid, or a new owner of a town.
- The spread of a rumor over time and distance, such as news from The Hub that reaches Admag days later.
- An upgrade of an existing campaign. The `event` table goes, the `rumor` table changes, and `open_campaign` refuses a database of an earlier schema version ([architecture.md](../info/architecture.md#campaign-storage)).

## 2. Probe

The deeds depend on facts of the game that no test has shown. A probe answers them before the build, and ships on its own ([development.md](../info/development.md#probes)).

`DEATH_PROBE` (`LogDeathProbe` in `plugin/game/Context.cpp`) writes one line for each new knockout (`ko`), each call of `declareDead_hook` (`dead`), and each call of `setPrisonMode_hook` (`prison_on` or `prison_off`). The line holds the name, the `npc_id`, the faction, the player flag, the race, the animal flag, and the town of the character. Its `hits` hold each character that attacked the character in the last 3 game hours ([section 3](#attackers)), with the name, the `npc_id`, the faction, the player flag, and the game minutes since its last attack (`age_min`). `RecordProbeHit` keeps these attackers from `attackingYou_hook`.

A knockout is new when the prone state of the character was not `PS_KO` before the call, because the game sets `PS_KO` again on a character that is already knocked out.

No session has logged the `hits` yet. The sessions before them ran an earlier build of the probe, which logged the attackers that `getAllAttackers` gives. The first build with the `hits` read them only on the game thread, and the hooks never ran on it.

The played sessions answered these questions:

| Question | Answer |
|---|---|
| Does `declareDead` run for a death in a fight, and for a character that bleeds out after a knockout? | Yes, for animals and for people. A Swamp Ninja Bowman died under the attacks of Blood Spiders. Bonedogs died 1 to 2 minutes after the last attack on a Bonedog, while they lay knocked out. |
| Does `Character::getAllAttackers` (`Character.h:555` of KenshiLib) list the attackers when the knockout hook, the death hook, or the prison hook runs? | Almost never. It gave an attacker for 1 of 56 knockouts, and for none of 17 deaths and 16 prison changes, also when an attack came in the same second. |
| Does the game set `PS_KO` again on a character that is already knocked out? | Yes, about 10 times a second, also after the last attack of the fight. A character that wakes up and goes down again gets a new `ko` line. |
| Which characters does `isAnimal` mark? | Bonedogs, Blood Spiders, and Bog Dogs. A Gurgler, of the race Fishman, is not an animal. |
| Does `declareDead` run again when a save with dead bodies loads? | No. A save and a load after 5 deaths gave no `dead` line. |
| What do the other hooks do at a load? | The knockout hook runs again for each character that lies knocked out, and `setPrisonMode` with `on` runs again for a prisoner in a cage, a few seconds after the load. |
| Does a character that goes into a cage call `setPrisonMode` with `on`? | Yes. The player character that the player put into a cage got `on`, with no knockout and no attack before it, and `on` false when it left. |
| Do the knockout, death, and prison hooks run on the game thread? | No. All 33 lines of one session came from another thread. The game thread is the thread that started the plugin (`g_mainThreadId`), because the chat context reads the inventory only on that thread, and it holds the inventory. |
| Does `getCurrentTownLocation` give only towns? | No. It also gives animal dens, such as `Bog Dog Den 9`. |
| Do the races of one kind of animal have one name? | No. A mod can add variants: `Wolf_Headgear.mod` gives Bonedogs the races `Bonedog (white)`, `Bonedog (yellow)`, and `Bonedog (darkbrown)` besides `Bonedog`. The name of each of these Bonedogs stays `Bonedog`. |

These questions are open:

| Question | Why it matters |
|---|---|
| Do the `hits` hold the attackers of each death and capture, also of a character that bleeds out after its knockout? | A deed needs its doers. |
| Does a knocked-out character that a squad member puts into a cage call `setPrisonMode` with `on`? | The `imprisonment` event comes from this call. The played sessions showed it only for a character that went into a cage by itself, and for a prisoner at a load. |
| How does a capture count only once, when `setPrisonMode` runs again with `on` at a load? | A capture of a known figure in the 3 game hours before a save would count again at each load of the save. |
| How does the plugin drop the attacks of play that a load undid? | The attackers stay in the memory of the plugin at a load, while the game time goes back, so an attack of the undone play could count for a later death. |

The test needs no strong squad, because only the player flag of the hits is about the squad:

1. Set **Log level** on the Settings page to `DEBUG`.
2. Watch a fight until some of the characters die.
3. Let one squad member hit a character that someone else knocked out, until the character dies.
4. Pick up a character that is knocked out, and put it in a prisoner cage.

[kenshi_internals.md](../info/kenshi_internals.md) records the answers, and the build removes the probe.

## 3. Events from the game

### Kinds

| Kind | Hook | Sent when |
|---|---|---|
| `death` | `declareDead_hook` | A member of the player's faction is among its attackers |
| `imprisonment` | `setPrisonMode_hook` with `on` | A member of the player's faction is among its captors |

- `attackingYou_hook` sends no event. It keeps the attackers of each character for the death and the imprisonment that follow ([Attackers](#attackers)).
- The hooks of knockouts (`setProneState_hook`), damage (`applyDamage_hook`), first aid (`applyFirstAid_hook`), trades (`buyItem_hook`), loot (`isItOkForMeToLoot_hook`), raids (`triggerCampaign_hook`), new owners of towns (`setFaction_hook`), and slavery (`setChainedMode_hook`) go, because they only log events, and none of these events can make a deed.
- The filter is in the plugin, so the buffer of 100 events holds only the deeds of the squad.
- The plugin does not filter by `isUnique`. The server decides who is a known figure ([section 5](#known-figures)), so a generic character with a canon template, such as Yamdu without UWE ([kenshi_internals.md](../info/kenshi_internals.md#character-identity)), counts too.
- The server stops writing the chat lines as events (`chat` in `server/chat/routes.py`), because the dialogue already holds them. No prompt reads the event log, and banter takes its recent lines from the histories of its NPCs.

### Parties

Each character in an event is a party with these fields:

| Field | Source |
|---|---|
| `id` | `GetNpcId` (`plugin/game/Context.cpp:181`), the `npc_id` of the character table |
| `template_id` | The string ID of the template (`npc->data->stringID`), so the server binds a generic character with a canon template to the canon profile, as for a context (`adopt_canon`) |
| `name` | `getName` |
| `faction` | The name of the faction |
| `player` | `Faction::isThePlayer` of the faction of the character |
| `race` | The name of the race, as a context sends it |
| `animal` | `Character::isAnimal` gives a value |

- An event holds the character as `target`, and up to 5 of its attackers or captors as `attackers`, the members of the player's faction first.
- The `id` links an event to a profile. A deed therefore stays with a character after a rename, and two Dust Bandits with one name stay two characters.
- The town of an event is the town of the target (`getCurrentTownLocation`), or none outside a town. The zone is the zone around the camera (`ZoneName`), as for the Current Location ([architecture.md](../info/architecture.md#current-location)), because a deed of the squad happens near the player.

### Attackers

`attackingYou_hook` runs for each attack, with the attacker and the target. `getAllAttackers` gives no attacker when the knockout hook or the death hook runs ([section 2](#2-probe)).

The plugin keeps the attackers of each character by the serial of its handle: the `npc_id` of each attacker once, with the game time of its last attack. A `death` and an `imprisonment` take as their attackers each character that attacked the target in the last 3 game hours. Kenshi gives no last hit, so each of them counts as a killer, or as a captor.

- The 3 game hours cover a character that bleeds out after a fight, and a capture, which in Kenshi is a knockout, a carry, and a cell. The prison hook names no captor.
- The hook runs many times a second for each attacker, for example 2,182 times in 15 s for one attacker and one target. A call for a known attacker therefore only sets its time.
- The map takes a lock, because the hooks run off the game thread ([section 2](#2-probe)).
- The plugin drops each attacker older than 3 game hours, and each character with no attacker left, so the map holds only the fights of the last 3 game hours.

### Transport

The frame hook sends a report when 50 events wait ([architecture.md](../info/architecture.md#game-events)). After the filter, 50 events can take hours of play, and the events that wait are lost when the game closes. The frame hook therefore also sends a report when the oldest event waited 60 s. The plugin still builds no report while no event waits.

The server drops a repeat: an event with the kind and the target `id` of an event in the last game hour, because some hooks fire more than once for one change. The repeat check by name and message goes (`record_event_to_history` in `server/core/game.py`), because it also dropped the event of any other character with the same name.

## 4. Deeds

The `deed` table replaces the `event` table. It holds one row for each doer of each deed: the kind, `kill` or `capture`, the `npc_id` and name of the doer, the `npc_id`, name, faction, and race of the victim, whether the victim is an animal or a known figure, the town, the zone, and the game time.

- A death gives a kill to each attacker in the player's faction. An imprisonment of a known figure gives a capture to each captor in the player's faction. An imprisonment of another character gives no deed.
- The `player` flag of the event decides. A kill before a recruit therefore does not count, and a kill by a squad member who later leaves stays.
- A victim in the player's faction gives no deed.
- No deed is trimmed, because a count must stay whole for the whole campaign. A deed is a short row.
- The cull deletes the deeds after the game time.
- The event lines, the trim to 500 events, and the `EVENT_LINE` parse of `editor.js` go. `server.log` keeps each event of the game at the `DEBUG` level, for a check of the plugin.

## 5. Notable events

A notable event is a deed, or a count of deeds, that is worth a rumor. The server adds it to the `notable` table when the deed comes:

| Kind | When | Example |
|---|---|---|
| `figure` | A member of the player's faction killed or captured a known figure | Beep and Izumi of Nameless captured Tinfist. |
| `count` | The kills of a squad member against one faction, or one animal race, reach a step of the scale | Beep has killed 100 members of the Dust Bandits. |

- A row holds the kind, the game time, the place, and the deed as JSON: the doers, and the known figure, or the faction and the count.
- The Events list shows each line with the current names, as for a memory (`chat_prompt.named`), so a renamed squad member shows with its new name.
- The cull deletes the notable events after the game time, and puts a `count` back to the step of the deeds that remain.
- Rejected: a notable event for a knockout of a known figure. A knockout is a step of a capture or of a kill, and it would add a line for each fight.

### Known figures

A known figure is a character with a canon profile: a character of the campaign canon whose `origin` is `seed` or `campaign` ([architecture.md](../info/architecture.md#campaign-canon)), found by the `npc_id` of the event. SSR Vanilla has 211, for example Holy Lord Phoenix (`u:17225-Dialogue.mod`), Tinfist, the Dust King, and Beep.

- A character that the server added in play (`origin` `game`) is not a known figure, because each NPC that the player talks to gets a profile.
- A template author decides who matters to the world by adding a character to the canon.
- Rejected: the `leader` and `nobles` fields of the canon factions. They hold names, and the names do not match the characters: the field of The Holy Nation names Holy Lord Phoenix LXII, and the character is Holy Lord Phoenix.

### Counts

Each squad member has one `count` row for each faction that it killed members of, and for each animal race that it killed. The row holds the number of kills, and the step of the scale that the number reached:

| Step | Kills | Phrase |
|---|---|---|
| 1 | 25 to 99 | dozens of |
| 2 | 100 to 249 | more than a hundred |
| 3 | 250 to 499 | hundreds of |
| 4 | 500 or more | countless |

- Each kill updates the number. The row shows in the Events list from step 1, and it moves to the top of the list each time it reaches a new step.
- The count holds only the victims that are not known figures. A known figure makes its own notable event.
- One death with two squad attackers counts for both.
- An animal counts by its race, such as Beak Thing, because the faction of an animal, such as Wolves for a Bonedog, does not tell what it is. A title such as Beak Slayer then has a race to fit.
- The line names a faction as its members, such as "members of the Dust Bandits" or "members of The Holy Nation", because many faction names are not plural. It names an animal race in the plural, with an s unless the name ends in s, such as "Beak Things".
- The rumor of a count grows with it ([section 6](#growth)), so the count is one row and not one row for each step.
- The scale starts at 25, because a few kills are part of any trip through the wasteland. The bounds are starting values.
- Rejected: a count for the whole player's faction. A rumor of a count tells of one character, and its title, such as the Stickman of the Dust, fits one character.

## 6. Rumors

### Generate

On Campaign Log > Events, each notable event has one **Generate Rumor** button. The button opens a dialog with an Instructions field, as Generate Bio does (`askBio` and `writeBio` in `server/dashboard/web/editor.js`).

1. The player presses Generate Rumor, types an instruction in the dialog, such as "Beep is known as the Stickman of the Dust", and confirms.
2. `POST /api/campaign/rumors/generate` sends the facts of the notable event and the instruction to the LLM, with the `synthesis` task, and returns the text. It stores nothing.
3. The page puts the text into the rumor of the notable event in the Rumors list, or into a new rumor. The text is unsaved, so the player reads and edits it before a save keeps it.
4. Save stores the rumor (`POST /api/campaign/rumors`) with its notable event, its instruction, and the game time of the notable event.

- An empty instruction is allowed. The LLM then tells the deed as it sees fit.
- A notable event has at most one rumor, and the list marks the notable events that have one.
- The cull deletes a rumor with its notable event, because the two have the same game time.
- Rejected: a rumor that SSR writes by itself for each notable event. The player decides which deed is worth a rumor and how the wasteland tells it, and a call for each notable event would load a small local model in the middle of play.

### In game

The Dynamic World Events Log in game mirrors the web app, as the Dialogue Library mirrors Generate Bio ([architecture.md](../info/architecture.md#provisional-profiles)).

1. The list on the left holds the notable events, newest first, with the same marks as the web app. The right side shows the line of the selected notable event and its rumor.
2. **Generate Rumor**, which replaces Generate World Event, opens a window that asks for the instruction. The window starts with the instruction of the rumor, if any.
3. `/write_rumor` returns the text, and a second window shows it in an edit box. Keep sends the text to `/keep_rumor`, and Discard drops it.
4. **Edit Rumor** skips the LLM and opens the same edit box with the stored text, as Edit Bio does.

- `/write_rumor` and `/keep_rumor` share the code of the routes of the web app, as `/write_bio` and `/keep_bio` share the code of Generate Bio.
- The reply of `/write_rumor` carries the active campaign, and Keep sends it back. `/keep_rumor` refuses the text when that campaign is no longer active, because the same notable event ID can name another deed in another campaign.
- Each close of the window makes a pending reply stale, as `CloseBioUI` does in `plugin/ui/LibraryWindow.cpp`.

### Growth

A `count` that reaches a new step after its rumor was saved shows as grown in the Events list, for example "Grown to hundreds of".

- The dialog starts with the instruction of the rumor, so a new Generate Rumor keeps the angle of the player, such as the Stickman of the Dust.
- The LLM gets the text of the rumor so far, and the rule to grow it: keep its names and titles, and tell the new size of the deed.
- The new text replaces the text of the rumor. A save gives the rumor the game time of the new step, so the rumor is news again.

Example: "Heard Beep's killed hundreds of Dust Bandits now." grows into "They say the Stickman of the Dust has put countless Dust Bandits in the sand."

### Facts

The server writes the facts of a notable event as plain sentences, and the LLM gets only these facts:

```
The player's faction: Nameless, a group of drifters.
The deed: Beep of Nameless has killed hundreds of members of the Dust Bandits.
Place and time: The Hub, in the Border Zone, Day 63, 18:20.
Who they are:
- Beep (male Hive Worker Drone): Wanderer.
```

```
The player's faction: Nameless, a group of drifters.
The deed: Beep and Izumi of Nameless captured Tinfist of the Anti-Slavers.
Place and time: Okran's Pride, Day 40, 03:10.
Who they are:
- Tinfist (Skeleton, no sex): Leader of the Anti-Slavers.
- Beep (male Hive Worker Drone): Wanderer.
The factions:
- Anti-Slavers. Enemies: The Holy Nation, United Cities, Traders Guild, Slave Traders.
```

- A `count` gives the phrase of its step, not the number, because a rumor does not count exactly.
- Each known figure, and each squad member with a profile, gets its sex, its race, and the first sentence of its canon `Backstory`. The LLM then knows why the figure matters, and which pronouns fit.
- The faction of the victim gets its `allies` and `enemies` from the canon factions, when the canon has them. The LLM then knows who cheers the news and who fears it.

### Prompt

`prompt_world_synthesis.txt` gets the instruction of the player, the facts, the rumor so far, if any, and these rules:

1. Write one world rumor of 1 or 2 sentences, as people of the wasteland tell it from bar to bar. Make it vivid.
2. Follow the instruction of the player. It wins over every other rule.
3. Tell the deed of the facts, and invent no other event.
4. Tell how the wasteland takes the news, from who the figures are, and from the allies and enemies of their factions.
5. Grow the rumor so far: keep its names and titles, and tell the new size of the deed.
6. Write only the text of the rumor.

The instruction comes right after the task line, because a model that read the instructions of the bio prompt after the current texts ignored them ([architecture.md](../info/architecture.md#provisional-profiles)). The block of the earlier rumors goes. The language instruction stays.

### Storage

The `rumor` table holds the text, the game time, the instruction, and the notable event. The `- [Day 12, 14:50] [RUMOR: ...]` line goes, and with it the parse of that line in `scene_text.py`, `core/routes.py`, `editor.js`, and `scripts/mock_test.py`. The rule that turns brackets in an edited rumor into parentheses goes too.

The automatic synthesis goes: `RUMOR_SYNTHESIS`, `synthesis_loop`, `generate_global_narrative_thread`, the `/synthesize` route, the Event timer of the Settings page (`synthesis_interval_minutes`), and the notice "A new world rumor is spreading.". The `synthesis` task of the Models page stays for Generate Rumor.

## 7. Prompt

The scene keeps the 5 newest rumors (`PROMPT_RUMORS`) with their age (`rumors_text`). It reads the rumor rows instead of the `[RUMOR: ...]` lines, and it orders them by game time instead of by ID, so a grown rumor counts as new.

A rumor names the squad member, and the scene names the squad member who speaks, so an NPC can tell that the drifter before it is the one in the rumor.

Rejected:

- An order of the rumors by the town, the zone, and the faction of the NPC. Which rumors an NPC knows is the task of a later NPC knowledge system, and an order by place would only guess at it.
- A search of the rumors by lore retrieval ([proposal_lore_retrieval.md](proposal_lore_retrieval.md)). The rumors are in the system message only, and a rumor that is not among the 5 newest is old news.
- A sentence in the scene about the deeds of the squad member who speaks, such as "People say they have killed more than ten people." The rumors carry the deeds that the player chose, and which NPC knows a deed is the task of the knowledge system too.

## 8. Web app and game windows

- **Campaign Log > Events** lists the notable events, newest first, each with its line, its game time, its place, its Generate Rumor button, and a mark when it has a rumor or has grown. The Rumors list below keeps its editable texts. `GET /api/campaign` returns the notable events instead of the events.
- On Campaign Canon, Other Details of a character show its kills for each faction and the known figures that it killed or captured, read-only, as for the Current Job.
- The Dynamic World Events Log in game lists the notable events and offers Generate Rumor and Edit Rumor ([section 6](#in-game)). Its **Generate World Event** button goes with `/synthesize`, and `/events` and `/events/content` return the notable events and their rumors.
- The cull of the SSR HUB reports the deeds, the notable events, and the rumors that it deleted, instead of the events (`plugin/ui/LauncherWindow.cpp`).

## 9. Verification

1. [kenshi_internals.md](../info/kenshi_internals.md) records the answers of the probe of [section 2](#2-probe).
2. `server/tests/test_world_events.py` covers:
   - the deeds: one kill for each attacker in the player's faction, the `player` flag at the time of the event, the capture of a known figure, no deed for the capture of another character, and no deed for a victim in the player's faction;
   - a repeat of an event within 1 game hour, and after it;
   - the known figures: a canon character by `npc_id`, a generic character with a canon template, and a character with the `origin` `game`;
   - the notable events: the kill and the capture of a known figure, the first step of a count, each further step, a kill that reaches no new step, two factions, an animal race, two squad members, and a known figure that does not count;
   - the line of a count: a faction with and without a leading "The", and an animal race with and without a final s;
   - the cull of deeds, notable events, and rumors, and a count that goes back a step;
   - the facts: the phrase of each step, the sex, race, and first sentence of the backstory of a known figure, and the allies and enemies of a faction;
   - the generate route: the facts, the instruction, and the rumor so far reach the prompt, and nothing is stored;
   - the 5 newest rumors in the scene by game time, with a grown rumor.
3. In game and on the web app:
   - Watch guards fight Bonedogs, and knock out generic NPCs. No event reaches the server.
   - Let Beep kill 25 Dust Bandits. After a chat, the Events list shows "Beep has killed 25 members of the Dust Bandits".
   - Let Beep kill 25 Bonedogs. The Events list shows a count of the Bonedog race, not of its faction.
   - Type "Beep is known as the Stickman of the Dust", and press Generate Rumor. The rumor holds the title, and the next conversation has it in the scene.
   - Let Beep reach 100 kills of Dust Bandits. The count shows as grown. Generate Rumor again: the dialog holds the instruction, and the new text keeps the title and tells the new size.
   - In the Dynamic World Events Log, select the count of Beep, press Generate Rumor, and keep the text. The web app shows the same rumor. Switch the campaign on the web app while the window waits for the LLM, and press Keep: `/keep_rumor` refuses the text.
   - Knock out Tinfist and put Tinfist in a cell. The Events list shows the capture with the names of the captors.
   - Save, fight, load the save, and cull. The deeds, the notable events, and the rumors of the fight are gone.
4. The full server test suite passes.
