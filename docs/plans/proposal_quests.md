# Proposal: Quests

## 1. Summary

SSR has no quests. An NPC can trade, heal, release, or join through an action dialogue ([architecture.md](../info/architecture.md#action-dialogue)), but no NPC gives the player a job.

In this plan, QUEST is a new action category with the mark `!q`. The player asks a quest giver for work. Code picks the job, and the NPC tells it in its own words. A popup lets the player take the job. Code tracks the job from the game events, and a Quests tab of the Journal window lists each open job. The player goes back to the giver for the reward.

| Job | Giver | The player | Done when |
|---|---|---|---|
| Figure | A faction leader, only at a good relation | Kills or captures the leader or a noble of an enemy faction | A `kill` or a `capture` event of the target names a squad member |
| Faction | A faction leader or a guard | Kills a number of members of an enemy faction | The squad killed that number |
| Goods | A trader | Brings a number of one raw material that fits the goods of the trader | The speaker hands the items to the trader |

- Code picks the target, the count, and the reward of each job, with no LLM call, because a model names targets and prices that the game does not hold.
- A job belongs to the player faction. Any squad member can take it, work on it, and collect the reward.

Non-goals:

- Jobs that the LLM writes, chains of jobs, and jobs with steps.
- Escorts, deliveries to a place, and quest items.
- A generic NPC as the target, because the game despawns patrolling squads. SSR removed its own bounties for this reason.

[Sections 2 to 8](#2-entry) hold the decided design.

## 2. Entry

`q` and `quest` name QUEST in `CATEGORIES` (`server/chat/action_dialogue.py:18`), with the classify text "A request for a job or for work, or a report on a job". The Help window (`plugin/ui/HelpWindow.cpp:72`) and the Help page of the web app (`server/dashboard/web/index.html:235`) get the line "`!q`: Ask for a job, or report on a job."

A QUEST line goes to plain chat with the reason as the NPC's thought (`plain_chat`) in these cases:

| Case | Thought |
|---|---|
| The NPC is not a leader (`current_job.is_leader`), a guard (`is_guard`), or a trader (`is_trader`) | "You have no work to give." |
| The NPC or the speaker is `imprisoned` | "You are locked in a cage, so you cannot give work." or "{player} is locked in a cage, so {player} cannot take work." |
| The NPC has no open job and no job to give ([section 3](#3-jobs)) | "You have no work for {player} now." |

A leader can give a figure job and a faction job. When both pass their gates, code picks one at random.

## 3. Jobs

`server/chat/quests.py` picks each job (`quests.roll`). It imports no Flask, so its tests run in the dev container.

- A giver with an open job gives no new job, so each giver holds at most one open job.
- The job of the first QUEST line stays in `CURRENT_THREAD` (`action`), so each turn of the action dialogue names the same job. A new chat thread rolls again.
- Code finds the enemies of the giver in the `enemies` field of the giver's faction record, by an exact name or an alias (`campaign_db.find_faction`, `server/store/campaign_db.py:912`). A name that finds no faction, the player faction, and the giver's own faction drop out.

### Figure

- The relation of the player faction with the giver's faction (`relation` of the context, `plugin/game/Context.cpp:856`) must be 60 or more, the band of the relation bonus +2 (`relation_bonus`, `server/chat/action_dialogue.py:169`).
- The targets are the `leader` and the `nobles` of each enemy faction record. Code finds the canon character record of each target by its name words, as `rulers.fallen` does (`server/chat/rulers.py:27`). A value that names two people, such as "Dimak and Buzan", is split at "and".
- A target drops out when it has no canon record, when the game holds it dead or imprisoned (`rulers.character_states`), when it is in the player faction, or when another open job names it. So one kill never pays two jobs.
- The job is done at a `kill` or a `capture` event of the target after the accept, with a squad member as a doer (`world_events._store`, `server/core/world_events.py:161`). Either event counts, so the player chooses how to do the job. A capture into a cage of the player faction counts too.
- The job fails when the game holds the target dead or imprisoned, and no such event came. Code checks this after the events of each request, so an event and a state in one request mark the job done. A game event that a failed request lost ([architecture.md](../info/architecture.md#game-events)) therefore fails the job.
- The job fails when the game holds the giver dead or imprisoned.

### Faction

- The target is an enemy faction of the giver. The count is 3 to 8.
- Each `death` game event counts when its party belongs to the target faction and `world_events._attribute` gives it an attacker of the player faction. The death counts only after the accept.
- A death counts toward only the oldest open faction job against that faction, so one kill never pays two jobs.
- `EventParty` (`plugin/game/Context.cpp:347`) gets `factionID`, because the party now holds only the game name of the faction, and the faction records are keyed by the game ID ([architecture.md](../info/architecture.md#factions)).
- A faction job of a guard is paid by any guard of the giver's faction, or by its leader. Generic guards look alike and have rolled names, so the player could not find the one guard that gave the job.

### Goods

The class of a trader comes from the `kind` of its goods (`offers.goods`, `server/chat/offers.py:191`, `ItemKind` in `plugin/game/Context.cpp:597`). The class needs at least half of the item stacks, because a general store sells a few items of each class. A trader without a class gives no job.

| Class | Kinds of the goods | Materials |
|---|---|---|
| Food | `food` | Raw Meat, Wheatstraw, Greenfruit, Cactus, Riceweed |
| Weapons | `weapon`, `crossbow`, `ammo` | Raw Iron |
| Armour | `armour` | Raw Iron, Animal Skin, Cotton, Fabrics |
| Electronics | `limb`, `repair`, and the `goods` items in `ELECTRONICS` | Copper |
| Drugs | `drug` | Hemp |
| Medical | `medical` | Hemp |

- The materials follow the crafting chains of the vanilla game data: Raw Iron makes Iron Plates and Armour Plating, and Iron Plates make Steel bars; Animal Skin makes Leather; Cotton makes Fabrics; Copper makes Electrical Components and goes into the robotics bench; Hemp makes Hashish and the Advanced First Aid Kit. Kenshi has no item named hide or cloth, so Animal Skin takes the place of hide, and both Cotton, the raw form, and Fabrics take the place of cloth.
- `ELECTRONICS` holds the items of the vendor list `Hi tech junk` that `ItemKind` gives the kind `goods`: CPU Unit, Electrical Components, Generator Core, Motor, Power Core, and Robotics Components.
- Code picks one material of the class that the goods of the trader do not hold, because the player could buy it from the trader and sell it back at the reward. A class with no such material gives no job.
- The count is 3 to 8. The job is done at the hand-over ([section 4](#4-flow)).
- A trader keeps its handle across a town reload ([kenshi_internals.md](../info/kenshi_internals.md#character-identity)), so only the giver pays a goods job.

### Rewards

| Job | Reward |
|---|---|
| Figure | 20,000 cats for a leader, 10,000 cats for a noble |
| Faction | 500 cats for each kill |
| Goods | Twice the value of the material in the vanilla game data for each item: Raw Iron 150, Copper 300, Animal Skin 400, Fabrics 300, Hemp 100, Cotton 50, Raw Meat 100, Greenfruit 60, Wheatstraw 40, Cactus 30, Riceweed 25 |

- The reward is fixed. The turn message says so, and the NPC cannot bargain it.
- The plugin creates the cats with `ADD_CATS`, as for charity, because a giver can carry fewer cats than the reward.

## 4. Flow

1. The player sends `!q` and a line to a giver. The gates of [section 2](#2-entry) run.
2. When the giver holds an open job, the turn message gives its progress, for example "{player} has killed 2 of 5 Dust Bandits.", or "{player} has done the job. Pay the reward." Else code rolls a job, and the turn message names it, for example "You want {player} to kill 5 Dust Bandits. You pay 2,500 cats when it is done."
3. The system message ends with `prompt_action_quest.txt` for a new job, and with `prompt_action_quest_report.txt` for an open job. Each tells the NPC to tell the job or the progress in its own words, and to keep the target, the count, and the reward of the facts.
4. The reply to each marked QUEST line carries the popup (`CMD: OFFER:`): the new job, or the reward of a done job. A line without the mark carries no popup. QUEST has no deal tag and no lean, because the NPC never refuses, and code already knows the job.
5. Accept of a new job stores it (`campaign_db.add_quest`), writes the deal line, sends a line of `quest_accept` from `server/data/defaults/action_end_lines.json`, and ends the chat thread. The job shows in the Quests tab ([section 6](#6-quests-tab)).
6. Each counted death and each change of state sends a game message (`NOTIFY:`), for example "Job for Sergeant Rook: 3 of 5 Dust Bandits killed.", "Job done: go back to Sergeant Rook for the reward.", and "Job failed: Tinfist is dead."
7. Accept of a reward sends `ADD_CATS`, marks the job paid, writes the deal line, sends a line of `quest_paid`, and ends the chat thread.

| Popup | Text |
|---|---|
| A new job | "Sergeant Rook offers a job: kill 5 Dust Bandits. Reward: 2,500 cats." |
| A new figure job | "Holy Lord Phoenix offers a job: kill or capture Tinfist, leader of the Anti-Slavers. Reward: 20,000 cats." |
| A reward | "Sergeant Rook pays 2,500 cats for the job." |
| A goods reward | "Harvag offers 1,500 cats for 5 Raw Iron." |

- A goods job has no done state before the hand-over. Its report gives the count that the speaker carries. The popup comes only when the speaker carries the whole count, and it holds a `CHECK:` line for the items (`offers.checks`).
- The hand-over is `BUY_ITEM` for a trader in a shop, so the items go into the stock, and `TAKE_ITEM` with a `CHECK: ROOM` line for any other trader, as in a trade (`offers._acts`).
- `DoGiveCats` (`plugin/game/GameActions.cpp:658`) checks `HeldBack` for `ADD_CATS` too, so a hand-over that falls short pays no reward. Today it checks only `GIVE_CATS`.
- The chat scene of a giver names its open job and the progress, so a plain chat line can talk about it.

## 5. Storage

The campaign database gets two tables, and the schema goes from 23 to 24 with a step in `migrations.STEPS` (`server/store/migrations.py:29`). The step only adds the tables, so it changes no stored data.

| Table | Columns |
|---|---|
| `quest` | `id` (`AUTOINCREMENT`), `giver` (`npc_id`), `giver_name`, `giver_faction` (game ID), `kind` (`figure`, `faction`, or `goods`), `target` (an `npc_id`, a faction game ID, or an item name), `count`, `reward`, `state` (`open`, `done`, `failed`, or `paid`), `accepted_at`, `changed_at` |
| `quest_kill` | `quest_id`, `game_time` |

- `id` is `AUTOINCREMENT`, because the Quests tab keeps the ID of the selected job, and a late Abandon must never reach a new job.
- `quest_kill` keeps the game time of each death, so a load can undo the deaths after it ([Loads](#loads)).
- A `rekey` event changes `giver` as it changes the other rows (`campaign_db.rekey`).

### Loads

The jobs live in the campaign, not in the save, so a load of an earlier save must undo the later changes. Without this, a player who loads a save from before a paid reward loses the cats and keeps the paid job.

- Each request that carries a game time runs `quests.rewind(at)` before it counts its events, when `at` is before the newest `accepted_at`, `changed_at`, or `quest_kill.game_time`.
- The rewind deletes each job accepted after `at` and each death after `at`. It sets each job whose `changed_at` is after `at` back to `open`, and then counts each job again.
- The cull of the web app runs the same rewind at its game time (`campaign_db.cull_after`, `server/store/campaign_db.py:783`).
- A game time of Day 0, 00:00 runs no rewind, because the game clock reads that until it holds a real time (`world_events._minutes`).

## 6. Quests tab

The Journal window of the SSR HUB (`plugin/ui/JournalWindow.cpp`) gets two tab buttons at the top: Entries and Quests. Entries shows the notebook of the player as today ([architecture.md](../info/architecture.md#journal)), and the window opens on it. Quests shows the jobs in place of the search, the page buttons, New Entry, and the boxes of an entry. The journal table does not change, and no job is a journal entry.

The Quests tab lists each job that is `open` or `done`, newest first by its accept, with the giver and the job as the label, for example "Sergeant Rook: Kill 5 Dust Bandits". A read-only box shows the selected job (`quests.details`):

| Line | Text |
|---|---|
| Giver | "Giver: Sergeant Rook of the United Cities, last seen at Bar, Heng." The place is the `CurrentLocation` of the giver's profile. A faction job of a guard adds "Any guard of the United Cities pays the reward." |
| Reward | "Reward: 2,500 cats." |
| Progress | "Progress: 2 of 5 killed." or "Done. Go back to Sergeant Rook for the reward." A goods job reads "Bring 5 Raw Iron to Harvag." |

Abandon asks "Give up the job for Sergeant Rook?" in a popup, as Delete does for an entry. Yes deletes the job and its deaths, so its giver can give a new job.

| Route | Behavior |
|---|---|
| `POST /quests` | The `open` and `done` jobs with their details, and the active campaign |
| `POST /quests/abandon` | Delete a job and its deaths |

- A paid or a failed job leaves the list. Its game message told the player.
- Each switch to the Quests tab asks for the list again, and the tab drops a reply that a newer request made stale, as the Journal window does.
- Each write sends back the campaign of the tab, and the server refuses it with status 409 after a campaign switch, because the same ID can name another job in another campaign.
- The list escapes `#` in each label, and the box takes its text with `setOnlyText`, because MyGUI reads `#` as a colour tag ([kenshi_gotchas.md](../info/kenshi_gotchas.md#mygui)).

## 7. Tests

| Test file | Checks |
|---|---|
| A new `server/tests/test_quests.py` | The gates of each job. The enemy targets from the faction records. A dead, imprisoned, recruited, or taken figure drops out. The class of a trader, the half rule, and a material that the goods hold. A death before the accept, a death with no squad attacker, and a second open job against one faction. Done and failed figure jobs, also in one request. The rewind and the cull. |
| `server/tests/test_action_dialogue.py` | `!q` and `!quest` parse. The classify list holds QUEST. The plain chat reasons. |
| `server/tests/test_offers.py` | The popup texts. The checks and the actions of a goods hand-over, in a shop and outside one. |
| `server/tests/test_campaign_db.py` | The step from schema 23 gives the tables of a new campaign. The list of `/quests` holds only `open` and `done` jobs, newest first. Abandon deletes the job and its deaths, and a write for another campaign is refused. |

## 8. Rejected

| Alternative | Reason |
|---|---|
| A deal tag, such as `[AGREE]`, for the job | The NPC never refuses a job, so code sends the popup with no tag. |
| A lean for the job | A giver with work gives it. Only the figure job has a gate, the relation of section 3. |
| Enemies from the live relations of the game | It needs a plugin read of each pair of factions at each QUEST line. The faction records already hold the enemies, and the player can edit them on Campaign Canon. |
| A reward from the purse of the giver | A giver can carry fewer cats than the reward. |
| A reward that the NPC bargains | It needs a hard limit and a lean for each job. A fixed reward needs neither. |
| A journal entry for each job | The journal is the notebook of the player. An entry that code writes at each change of its job would need its own rules for edits, deletes, and the cull. |

When the build is done, the decided rules move into [architecture.md](../info/architecture.md#action-dialogue), and this plan is deleted.
