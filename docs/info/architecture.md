# Architecture

Sentient Sands Rebirth has three parts: a C++ plugin that runs inside Kenshi, a local Python server that talks to the LLM provider, and the Kenshi mod files that make the game load the plugin.

## Repository layout

| Path | Contents |
|---|---|
| `deps/` | Not in git. KenshiLib and Boost for the plugin build ([plugin_build_setup.md](plugin_build_setup.md#3-fill-deps)). |
| `plugin/` | The plugin ([development.md](development.md#plugin)). `main.cpp` holds `startPlugin`, the hooks, and the message-queue dispatcher; `core/` the shared state, INI, and transport; `game/` the game state as JSON (`Context`) and the NPC actions; `ui/` the MyGUI windows. |
| `server/` | `main.py` starts the server. `core/` holds the app, the game routes, the pipe, and the settings; `chat/` the chat, prompts, LLM calls, memories, and lore; `store/` the campaign database and the world templates; `dashboard/` the web app and its routes; `data/` the defaults, prompts, and shipped templates; `tests/` the unit tests ([development.md](development.md#tests)). |
| `mod/` | The root files of the installed mod. A server that runs from the repo writes its git-ignored INI here. |
| `scripts/`, `package_release.cmd` | The release tooling ([development.md](development.md#release)). |

- Each server package keeps its routes in a `routes.py` blueprint. Only these modules, `core/app.py`, and `chat/llm.py` import Flask or `requests`, so the tests can import every other module.
- Read the shared session state as `state.NAME`, because `from core.state import NAME` misses a later assignment, such as a campaign switch.
- The start-up runs in `start`, not at import, so an import starts no thread.

## Installed layout

The release zip unpacks into `Kenshi/mods/`. The plugin and the server find each other through these relative paths, so change both sides together.

```
SentientSandsRebirth/
  SentientSands.dll          built from plugin/
  RE_Kenshi.json             makes RE_Kenshi load the DLL
  mod.info
  SentientSandsRebirth.mod
  SentientSands_Config.ini   settings, created by the server on first start
  server/
    main.py
    core/  chat/  store/  dashboard/
    data/templates/  data/prompts/  data/defaults/
    python/                  embedded runtime, added by scripts/package_release.py
    config/  logs/           created at runtime
    data/campaigns/  data/user_templates/   created at runtime
```

- The plugin takes the mod root from the path of its DLL, and runs `server\python\python.exe server\main.py`, or `python` on `PATH` (`StartPythonServer` in `plugin/core/Utils.cpp`).
- The mod root is the parent of the folder of `main.py`. From the repo, the server finds the INI in `mod/` (`resolve_mod_file`).

## Runtime flow

1. RE_Kenshi loads the DLL and calls `startPlugin`, which installs the hooks and starts `MainThread`.
2. `MainThread` waits for `KenshiLib.dll`, starts the pipe listener, loads the INI, and starts the server. With `OpenWebPanelOnStart=1`, it passes `--open-browser`, and the server opens the web app when no earlier tab reconnects.
3. The plugin sends HTTP POST requests to `127.0.0.1:5000` (`plugin/core/Comm.cpp`). The server rejects a `Host` other than `127.0.0.1:5000` or `localhost:5000`, and a foreign `Origin` (`server/core/request_guard.py`), so web pages cannot use it.
4. The server sends commands back through the named pipe `\\.\pipe\SentientSands`, such as `NOTIFY` and `NPC_SAY` (see [Line pacing](#line-pacing)).
5. Each prompt comes from the prompt files (see [Prompts](#prompts)) and the campaign state, and goes down the route of its task (see [LLM routing](#llm-routing)).

## Threading

Background threads never change game objects or MyGUI widgets. They push messages onto `g_messageQueue` under `g_msgMutex` (`plugin/core/Globals.h`), and `playerUpdate_hook` drains the queue on the game thread (`ProcessMessageQueue`). New code that makes results off the game thread must use this queue.

## Game state

The plugin reads the game state only when a request needs it. Do not post it on a timer: that built full contexts on the game thread while no prompt used them.

| Request | Game state that it carries |
|---|---|
| `/chat` | The contexts of the target and of the squad member who speaks, the game events, and the changed towns |
| `/radiant` | The participants, the NPCs near the center, the context of the center, the game events, and the changed towns |
| `/cull`, `/report` | A report: the player's context, the game events, and the changed towns (`GameReport`). `/report` goes when 50 events wait, when the oldest event waited 60 s, or on `REPORT` from the pipe. |
| `/squad_rename` | The context of a renamed member of the player's faction (see [Names](#names)) |

- The server keeps the player's context of the latest request (`take_report`). It can be old, so a value that must be current comes with its own request.
- The cull of the web app asks for a report and refuses without one, because a cull by an old game time deletes newer play.

### Game events

The hooks in `plugin/main.cpp` buffer the game events (`QueueGameEvent`). The server decides who did what (see [Events](#events)).

| Kind | Hook | Added when |
|---|---|---|
| `attack` | `attackingYou_hook` | The attacker is in the player's faction, once for each attacker and target in a report |
| `knockout` | `setProneState_hook` with `PS_KO` | The character was not knocked out before |
| `up` | `setProneState_hook`, other state | The character was knocked out before; holds `isBeingCarried` |
| `death` | `declareDead_hook` | Each call |
| `imprisonment` | `setPrisonMode_hook` with `on` | Each call |

- A party (`EventParty`) holds `id` (the `npc_id`), `template_id`, the name, the faction, and `player`.
- Each event holds the game time of its hook, read under `g_eventMutex`, so a step back of the game time means a load.
- `attackingYou_hook` runs many times a second, so it checks the faction first and dedupes by handle serials without building a string.
- A request takes the events out of the buffer (`TakeGameEvents`), so each event goes once, and a failed request loses them. The buffer holds 100 events.
- Without a game world, an event has no game time, so the plugin drops it.

### Events

`server/core/world_events.py` decides which squad members killed or captured a known figure. It keeps the game events of each `npc_id` in memory for the active campaign. A `death` or an `imprisonment` takes the attackers since the last one:

- While a `knockout` mark is set, all attackers count, because a capture in Kenshi is a knockout, a carry, and a cell ([kenshi_internals.md](kenshi_internals.md#deaths-and-captures)). An `up` that is not carried clears the mark. A carried `up` changes nothing.
- Else each attacker whose last attack is in the 3 game hours before counts. Kenshi gives no last hit.
- An event with a game time before the newest event is a load, and drops the kept events after that time. The server skips events at Day 0, 00:00, because the clock reads that until it holds a real time.

The `event` table holds one row for each event, with the game time and, as JSON in `data`, the kind (`kill`, `capture`, `custom`, or `auto`) and its facts.

- Only a known figure outside the player's faction makes an event: a unique character (`npc_id` starts with `u:`), or a generic character that took a canon `npc_id` (`adopt_canon`, see [Characters](#characters)).
- A capture counts once for each captor and figure, because `setPrisonMode` runs again for each prisoner when a save loads.
- A custom event is a rumor that the player writes (`POST /api/campaign/events/add`). It has no game time, so it counts as the newest and the cull keeps it.
- The server deletes only a custom or an auto event, always with its rumor. The cull deletes the rows after its game time (see [Campaign routes of the web app](#campaign-routes-of-the-web-app)).

### Rumors

The server writes the rumor of each event in the quiet period of the memories, after them, one call at a time (`write_rumors` in `server/chat/memory.py`, see [Conversation memories](#conversation-memories)).

- A failed call leaves no rumor, and the next run tries again.
- The server stores the text only when the event still has no rumor, and drops it when the active campaign changed during the call.
- The player can generate a rumor with an instruction (`POST /api/campaign/rumors/generate`, the `synthesis` task), which stores nothing until Save. The instruction wins over the rumor so far.
- The LLM gets only plain facts (`server/chat/rumors.py`), so it invents no other event: the player's faction, the event, the time, the profiles of its characters, and the allies and enemies of the victim's faction. A custom or an auto event gives no characters and no factions, because its rumor is the only account.

The `rumor` table holds the text, the game time of its event, the instruction, and the event. An event has at most one rumor. The chat scene gives each NPC the 3 newest rumors with their age (`PROMPT_RUMORS`), and a radiant conversation can take one of them as its topic. An NPC radiant conversation always takes one (see [NPC radiant conversations](#npc-radiant-conversations)). The search of a chat line finds an older rumor (see [Rumor search](#rumor-search)).

### Auto rumors

At most once in each period of the Radiant rumor timer (`radiant_rumor_minutes`, default 30 real minutes), the LLM can spin one rumor from the memories that no rumor used. The rumor is an auto event (see [Events](#events)).

`memory_loop` runs a pass when the timer passed, the chat is quiet, no memory or event rumor waits, and the pool holds a memory that no pass read. The pass runs in the thread of the memories, so its call overlaps no other call.

- The pool holds each memory whose `thread.rumor_passes` is less than 6 (`RUMOR_PASSES`). A pass reads the newest 40 (`campaign_db.rumor_pool`).
- After a valid reply, a cited memory goes to 6, a memory that was read and not cited gets +1, and an older memory in the pool goes to 6 (`count_rumor_pass`). So dull memories leave, and a theme can build over several passes.
- The prompt (`prompt_auto_rumor.txt`) holds the player's faction, the memories with labels 1 to N, and the newest 30 rumors. The reply is `{"rumor": "...", "memories": [1, 2]}`. The empty rumor is the default.
- `campaign_db.add_auto_event` stores the event and its rumor, and sets the cited threads to 6, in one transaction. Nothing is written when the active campaign changed or a cited thread left the pool during the call.
- The event takes the newest game time of its threads, so the cull deletes it, and the auto rumors do not hold the 3 newest places for good.

### Events window

The Events window of the SSR HUB mirrors Campaign Canon > Events through `/events`, `/events/content`, `/write_rumor`, `/read_rumor`, `/keep_rumor`, `/add_event`, `/delete_event`, and `/delete_rumor`. These share the code of the web app routes in `server/chat/routes.py`.

- The reads return the active campaign, and each write sends it back. A write is refused when that campaign is no longer active, because the same ID can name another event.
- Each close of a popup makes the pending reply stale (`CloseRumorUI`).

### Changed towns

A world state can swap the data of a town for an override with another owner or type. The location records describe the start of a game, so the server lays the changes over them (`server/chat/towns.py`).

- Each chat, radiant conversation, and report carries `changed_towns` (`ChangedTowns`): each town whose `getGameData` is not its `getOriginalGameData`, with its owner, owner game ID, and type. The server keeps only the latest list, because a load can undo a change.
- `towns.current` lays the change over the location record of that name, so it reaches the knowledge, the lore hits, and the radiant place topic (see [Own records](#own-records)).
- A sentence such as "Brink is now a town held by Reavers." leads the description. It gives no time, because the plugin sees only that a change holds.
- A town that falls to ruins keeps its owner as the former owner, and a new owner of a ruin changes nothing (see [Links](#links)).
- The game decides which world states hold, so the overrides of a mod work too.

## Web app

The server serves `server/dashboard/web/` at `/` and `/web/<file>`: plain HTML, CSS, and JavaScript modules with no build step and no CDN, so the web app works offline.

| Page | Route | Storage |
|---|---|---|
| Settings | `/settings`, `/settings/defaults` | `SentientSands_Config.ini` |
| Models | `/api/llm`, `/api/llm/test`, `/api/llm/models`, `/api/llm/reset` | `server/config/llm_config.json` |
| Prompts | `/api/prompts` | `server/config/prompts/` |
| Campaigns | `/api/campaigns`, `/api/campaign/cull` (see [Campaign routes of the web app](#campaign-routes-of-the-web-app)) | `campaign.db` of each campaign |
| Editor | `/api/campaign/canon`, `/api/campaign/records` (see [Campaign canon](#campaign-canon)); `/api/campaign/search`, `/api/templates/<name>/search` (see [Test search](#test-search)); `/api/campaign`; `/api/templates` (see [World templates](#world-templates)) | `campaign.db` of the active campaign; `server/data/user_templates/` |

- A GET route must not change state, because a page on another site can send a GET without an `Origin` header. The presence stream is the only exception, because EventSource sends only GET.
- The web app polls `GET /context` every 3 s (`poll` in `app.js`). Without an answer, it shows a banner and disables Save, so unsaved changes survive a server restart. The reply also holds the active campaign and `writes`, a count of database commits and successful POSTs (`count_write_requests`); a change refreshes each loaded page, unless a request runs, a dialog is open, or the player types.
- Each tab holds `GET /web_panel/presence` open, so the server can count the open tabs.
- A refresh (`refreshers` in `app.js`) keeps the unsaved parts of a page. An Editor record keeps the version that the page loaded, so its save still fails as stale. Models keeps the whole page, because Save writes the whole configuration.

The Editor:

- **Campaign Canon** shows the active campaign in Database, Dialogue & Memories, and Events (see [Events](#events)). **Templates** edits the world templates; a shipped template is read-only.
- Save sends one request per changed record. A rejected record keeps its draft.
- Dialogue & Memories shows the threads (see [Chat threads](#chat-threads)). A thread with a memory shows only the memory, which is editable.
- Facts offer only the categories of the kind (`FACTS` in `server/store/world_template.py`, copied in `editor.js`). The `neighbours` of a region have a direction menu per name that starts at Unknown, which the validator refuses.
- The default knowledge tier saves no `knowledge` key, and only a Secret record saves `known_by` (see [Knowledge](#knowledge)).
- Race, Sex, and Faction are choices (`choice` in `editor.js`); a value that matches none saves as Unknown.
- A save keeps every profile key that the form does not show. A save that changes the Personality, Backstory, or SpeechQuirks of a provisional character ends that state (see [Provisional profiles](#provisional-profiles)).
- A save of a character renames the NPC in game (see [Names](#names)), and a save or delete reloads an open Dialogue Library (`REFRESH_LIBRARY`).

## Settings

- The server is the only writer of `SentientSands_Config.ini`. The plugin reads it once at start and then takes changes only through `SET_CONFIG`, because two writers without a lock undo each other.
- The release ships no INI, so an update keeps the settings. On the first start the plugin uses `LoadPluginConfig` (`plugin/core/Utils.cpp`), and the server writes `SETTINGS_DEFAULTS` (`server/core/settings.py`) and pushes each plugin value (`push_settings_to_plugin`).
- `OpenWebPanelOnStart` is read before the server starts, so its default in `LoadPluginConfig` must agree with `SETTINGS_DEFAULTS`.
- `GET /settings/defaults` is a separate route, because the plugin reads the `/settings` reply by the first match of each key (`GetJsonValue`).
- `send_to_pipe` retries for 0.25 s, because the plugin re-creates its pipe instance after each message.

## Prompts

- `server/data/prompts/` holds the shipped defaults. An override with the same name in `server/config/prompts/` wins when it holds text (`load_prompt_component`), so an update keeps it.
- `/api/prompts` (`server/chat/prompt_store.py`) takes only the name of a shipped `.txt` file, never a path. An empty save or a save equal to the default deletes the override. `base_hashes.json` holds the SHA-256 of the default at each save, so the page marks an override whose default changed.
- `prompt_system.txt` sets the common speech of Kenshi for chats and radiant conversations (`HOW PEOPLE TALK`): plain words, short lines, talk of concrete needs, and dark humor. It comes from the squad and bar talk of the game (the biome entry and bar patron dialogues), whose median line has 8 words. Without it, radiant lines had a median of 18 words, and a third of them used formal words or poetic images. The personality and the `SPEECH` of a character win over it, because some rolled manners and canon characters, such as the Phoenix and Hobbs, talk formally or ramble.
- `prompt_store.render` fills only known `{name}` placeholders and leaves other braces as text, so a stray brace cannot fail a call. An override may not add an unknown placeholder. Rejected: Jinja2, because template logic lets one edit break the whole prompt.

A chat request is ordered for the provider's prompt cache, which reuses only an identical start (`chat` in `server/chat/routes.py`, `server/chat/chat_prompt.py`):

| Part | Content | Changes |
|---|---|---|
| System message | `prompt_chat_template.txt`: `prompt_system.txt` (`prompt_animal_system.txt` for an animal), the judgment rule, `npc_template.txt`, `prompt_chat_scene.txt`, then the newest memories of the NPC's threads (see [Conversation memories](#conversation-memories)) | When a conversation starts or such a memory is written |
| History | The NPC's thread lines without a memory, as user and assistant turns (see [Chat threads](#chat-threads)) | One exchange more each turn |
| Last user message | `prompt_chat_turn.txt`: the found memories, rumors, and lore (see [Lore retrieval](#lore-retrieval)), the player's line, a short reminder | Every turn |

- The scene is a snapshot for the whole conversation (`CONVERSATION_SCENE`). A conversation ends when the player chats with another NPC, speaks as another squad member, switches the campaign, when the NPC's name or faction changes, or when the other speakers of the current chat thread change.
- `server/chat/scene_text.py` writes the scene as second-person prose, because a model reads a sentence more reliably than a number. The relation bounds match the relation labels of the Dialogue Library.
- The history is a block window (`chat_prompt.history_window`) that moves by 20 lines, so its start stays cacheable. `history_turns` makes only the NPC's own lines assistant turns.
- An overheard line is stored as `(Overheard) Speaker to Target: ...`, because without the target a listener took "you" as itself. An animal never overhears.
- The judgment is the change in how the NPC feels about the player, from -5 to 5. Rejected: a judgment of politeness, because a scornful NPC grew friendlier with each apology.
- Each reply line starts with `Name|serial:`, because the plugin takes the text before the first colon as the speaker (`ProcessMessageQueue`). An animal replies only in `*actions*`.
- A chat reply carries no game actions; the server reads only the judgment.

## Lore retrieval

The last user message holds the lore entries, memories, and rumors that the player's line is about (`server/chat/retrieval.py`). Name matching finds the entries that the line names; content search finds the entries that hold its lore words. `retrieval.py` uses plain values and the standard library; `server/chat/background.py` reads the records, for chats and the test search alike.

- A search finds words, not meaning, so the slots, the score cut, the cooldown, and the note of the block keep a wrong hit cheap. No embeddings.
- An NPC finds only the records that it can know (see [Knowledge](#knowledge)), the memories of its own threads, and the rumors that its chat scene does not hold.

### Lore records

| Record | Name | Fields | Text | Source |
|---|---|---|---|---|
| Race, location, region | `name`, `aliases` | the values of `fields`, except `neighbours` | `description` | `campaign_db.list_records("entity")` |
| Faction | `name`, `aliases` | the values of `fields` | `description` | `campaign_db.list_factions()` |
| History entry | `title` | none | `text` | `campaign_db.history()` |
| Character | `Name` | `race` and `faction` of the profile | `Backstory` | `campaign_db.list_records("character")` |

- A record with an empty text is no hit, but a link or a `known_by` can still name it.
- A character is a record only when it is canon (`origin` `seed` or `campaign`), because a rolled backstory is invented.
- The index is built in memory for each line, so an edit reaches the next line. The search uses SQLite FTS5 ([development.md](development.md#probes)).

### Name matching

1. The line and each name become lowercase words, split at each character that is not a letter or a digit. A word of 4 or more letters loses a final "s".
2. A name loses a leading "the".
3. A name matches when its words appear in the line in order, with no word between them.
4. A match inside a longer match is dropped.

### Content search

An FTS5 table holds one row per record (name, aliases, fields, text) with the `porter unicode61` tokenizer.

1. A word of the line searches only when it is in the vocabulary of names, aliases, and field values, is not a stop word, and appears in no more than a tenth of the records (`COMMON_SHARE`). The vocabulary keeps chat words out, because BM25 ranks rare words high.
2. The search is an OR of these words, ranked by BM25 with the weights in `WEIGHTS`.
3. A hit below 60% of the best score is dropped (`SCORE_RATIO`).

### Order of the lore

- Name matches come first. Content hits follow by place, each group by score (`place_order`): the current location (`town_name`), the current region (`zone_name`, see [Current Location](#current-location)), its locations, the neighbouring regions (either side names the other in `neighbours`), then the others.
- The place order adds no entry, because the model talks about the text that it gets.
- A record that the system message holds is skipped (`background.in_system_message`).
- An entry's text ends at its last sentence end before 700 characters (`clipped`). The fields are not cut.

### Knowledge

Each lore record has a tier (`server/chat/knowledge.py`), and the search of a chat line finds only the records that the NPC can know:

| Tier | The NPC finds the record when |
|---|---|
| Global | Always |
| Limited | The record is an own record of the NPC, or links to one |
| Secret | Its `known_by` names the NPC, its current faction, its origin faction, or its race |

- The default tier is Limited for a character, a location, and a region, and Global for a race, a faction, and a history entry.
- `background.search` drops unknowable records before `find_lore` builds its index, so they cannot set the score cut or the common share of a word.
- Access reads only the seeded data with the changed towns, the current place, and the places of past chats. What an NPC hears in a chat stays out, because its memories hold it.

#### Links

A link joins two records when one names the other, in both directions.

- A field value links to each record with the same name words (`retrieval.name_words`). A value of `neighbours` links nothing.
- `Faction` and `OriginFaction` link only to factions. `Race` is no link.
- The text of a history entry links to each record that it names (`retrieval.name_matches`). The text of another record links nothing, because a text match finds wrong names.
- A ruin links only to the regions of its `zone`.
- Links do not depend on the tier.

#### Own records

The own records of an NPC are the start of its links (`knowledge.known`, with the NPC from `background.identity`):

| Own record | Source |
|---|---|
| Character record | The NPC itself, for a canon character |
| Current and origin faction | The context `factionID` or the profile `Faction`; the profile `OriginFaction` |
| Race | The profile `Race` |
| Home | The places that the `territory`, `bases`, or `capital` of the origin faction names, the locations it owns, and their regions, except ruins |
| Current place | As for the place order (see [Order of the lore](#order-of-the-lore)) |
| Past places | The place of each thread with the NPC as a member (`campaign_db.thread_places`) |
| Neighbouring regions | The regions next to a region of the current or a past place |
| Holding factions | Each faction whose `territory`, `bases`, or `capital` names one of these places, and each `owner` of one of these locations, except ruins |

- Links go one hop from the own records. The holding factions give the only second hop, so an NPC in the Hub knows the Dust King through the Dust Bandits, who hold the Border Zone.
- Rejected: a second hop through every link. A member of the Holy Nation would know Tinfist through the `enemies` of its faction.

#### Base and travels

`knowledge.known` splits the own records into two groups, so the prompt can tell the NPC where it learned a Limited record:

- Base: the character record, the factions, the race, the home, and each current or past place inside the home, with its neighbouring regions and holding factions.
- Travels: each current or past place away from the home, with its neighbouring regions and holding factions.
- A Limited record that links only to travel records goes under its own heading in the block (see [Block](#block)). Global and Secret records are base knowledge.
- The home itself takes no neighbouring region and no holding faction, because the home of a large faction would span a third of the world.
- An NPC whose origin faction holds no land has no home, so it knows each place from its travels.
- The past places come from the threads at each chat line (see [Chat threads](#chat-threads)), so a deleted memory or a culled thread removes its place.

#### Secret access

- A holding faction does not count. A Secret record with an empty `known_by` reaches no NPC.
- `known_by` names match by name words (`knowledge.knowers`), and a name that matches more than one record names each of them.
- The server compares the `npc_id`, the faction ID, and the race record, not names, because a generic NPC can carry the name of a canon character (see [Names](#names)).

### Memory search

Each memory of a thread with the NPC as a member is a record, except the memories that the system message holds (see [Conversation memories](#conversation-memories)).

- A memory matches by name when the line names one of its members, or a lore name in its text.
- Content search uses an FTS5 table of the memory texts. A content hit needs at least 2 different words of the line (`TEXT_WORDS`), and the score cut of the lore applies.

### Rumor search

Each rumor (`campaign_db.rumors`) is a record, except the 3 newest, which the chat scene holds (`background.rumor_records`). Each NPC can find each rumor, because each NPC hears the newest rumors in its scene.

- A rumor matches by name when the line names a character of its event, or a lore name in its text. The NPC itself does not count, because the player names the NPC to address it.
- Content search works as for the memories (`retrieval.find_texts`).

### Slots and cooldown

| Setting | INI key | Default | Effect |
|---|---|---|---|
| Retrieval slots | `RetrievalSlots` | 3 | The hits of a turn. 0 turns the search off. |
| Memory slots | `MemorySlots` | 3 | The slots that memories and rumors can take together. The memories come first, then the rumors, each newest first (`retrieval.chosen`). |
| Retrieval cooldown | `RetrievalCooldownTurns` | 1 | The turns for which a content-only hit stays out. A name match always passes. |

- The server keeps the recent hit keys per pair of speaker and NPC (`RECENT_HITS`). Another pair, or a campaign switch, drops them.
- The plugin does not use these values, so `SET_CONFIG` does not send them.

### Block

The hits go into `{background}` of `prompt_chat_turn.txt`, before the player's line (`chat_prompt.background_block`), so they stay out of the cached system message and the stored dialogue.

- The block opens with "Background, not said aloud", lists memories, then rumors with their age, then lore (`describe_record`), then travel lore, and ends with a note that the lists may not fit. An empty list leaves no heading, and no hit leaves no block.
- It cannot be a system message of its own, because some chat templates accept a system message only at the start.
- An animal and a radiant conversation get no search.

### Test search

The Test search box of Campaign Canon and Templates shows what a line finds and why (`renderTestSearch` in `server/dashboard/web/editor.js`).

- It shows only while the Log level is `DEBUG` (`debug` from `GET /context`).
- On Campaign Canon, a picked character makes it search as that character, at the `CurrentLocation` of its profile (`background.place_of`). Otherwise it gives a lore search of every record.
- The routes are `GET /api/campaign/search?message=...&npc=...&speaker=...` and `GET /api/templates/<name>/search?message=...`. They are GETs, because a POST under `/api/` counts as a write and refreshes every open page (`count_write_requests`).

## Radiant conversations

A radiant conversation is a talk between 3 to 5 of the player's characters, or between 2 to 5 NPCs near them (see [NPC radiant conversations](#npc-radiant-conversations)), which one LLM call writes. The plugin asks for one each `RadiantChatMinutes` (10 by default) of unpaused real time, and on Trigger Radiant.

1. The plugin picks the center: the selected character if it can talk, or else the first squad member that can (`GetRadiantParticipants` in `plugin/game/Context.cpp`).
2. The participants are the center and the nearest of the player's characters within `TalkRadius`, up to 5. With fewer than 3, the plugin sends no participants.
3. The NPCs are the characters outside the player's faction that can talk and stand within `YellRadius` of the center, nearest first, each with the handle of its squad (`GetRadiantNpcs`).
4. The plugin posts the participants, the NPCs, the center's context as `player_context`, and the game events to `/radiant`. It sends nothing when both lists are empty.
5. The server picks 2 to 5 NPCs of one squad (`radiant.npc_group`, see [NPC radiant conversations](#npc-radiant-conversations)). It lets them talk when a rumor exists and a roll is under the NPC radiant chance (`npc_radiant_chance`, default 50 %, `radiant.npc_talk`). Else it picks the participants.
6. The server makes no call when the picked list is empty, when one of the picked characters fought within 3 game hours (`world_events.fought_recently`), when no topic has material, or when a conversation plays.
7. Otherwise it makes one `radiant` call, stores the lines as a new thread, and paces them (see [Line pacing](#line-pacing)). The participants that speak join the thread as speakers, and the others as overhearers. Nothing shows during the call, because the player does not wait for a radiant conversation.

The server, not the LLM, picks one topic kind at random from those with material (`radiant.topic`):

| Kind | Material |
|---|---|
| Shared memory | A memory of a thread with at least 2 participants (`campaign_db.shared_memories`) |
| Surroundings | The center's place and the lore entry of its town (`radiant.place_topic`) |
| Rumor | One of the 3 newest rumors |

- The prompt is `prompt_system.txt` without the chat reply rules (`response_rules.txt`), which are written for one NPC who answers the player, plus `prompt_radiant.txt`. Each participant is described with `npc_template.txt`, as the NPC of a chat is. The radiant rules give the conversation an opening, an exchange, and a closing line, and make each participant keep its own voice, follow from the lines before it, and give its opinion. Without these rules, one call writes one same-voiced remark on the topic for each participant, and stops mid-thread.
- The server picks the line count at random from 2 to 4, 5 to 7, or 8 to 12 (`radiant.LENGTHS`), because the model, left to choose, writes a long conversation every time.
- The server also picks the speaker and the addressee of each line (`radiant.turns`), because the model, left to choose, gave each participant one turn in a fixed round, and no line answered another, also under a rule against it. The first speaker speaks to everyone. Then the one addressed answers, or a third participant cuts in, at even odds (`REPLY_SHARE`), and either speaks to the last speaker. Two participants take turns. The prompt lists the turns as `Name|ID to Name` (`radiant.script`), and a speaker can speak to everyone instead where that fits.
- The prompt tells how well each pair of participants knows each other (`radiant.acquaintance`), so strangers ask about each other and old companions skip the introductions. The phrase comes from the count of the earlier threads in which both were speakers (`campaign_db.thread_partners`): 0 is "have never talked", 1 to 2 is "have talked a little", 3 to 9 is "know each other", and 10 or more is "know each other well".
- The reply holds `Name|serial: line` lines (`radiant.lines`). A line of a non-participant, or a failed call, leaves everyone silent.
- A radiant conversation does not change `CURRENT_THREAD` or the quiet clock. The memory loop runs after each one (`state.LAST_RADIANT`).

### NPC radiant conversations

An NPC radiant conversation takes the place of a talk of the player's characters. Its only topic is one of the 3 newest rumors, so without a rumor the player's characters talk instead.

- The NPCs belong to one squad, because NPCs that stand near each other only by chance have no reason to talk. So the prompt (`prompt_radiant_npc.txt`) says that they know each other, and it has no lines on how well each pair knows each other.
- Only an NPC whose Current Job is Hanging out at a bar talks (see [Current Job](#current-job)). The server picks the squad, because the job table also decides when a bar visit is only the side task of a guard.
- The server rolls the count of NPCs, from 2 to 5 (`radiant.SPEAKERS`). The nearest squad that has a member with a profile wins, else the nearest squad. Its members with a profile talk first, nearest first, and members without one fill the rest of the count. Each NPC without a profile gets one as at a first meeting. A squad with fewer members than the count talks with all of them.
- A player with fewer than 3 characters together gets an NPC radiant conversation at the NPC radiant chance, and no radiant conversation otherwise.
- For an NPC, only a knockout counts as a fight, because the game events hold only the attacks of the player's faction (see [Game events](#game-events)).
- The name of an NPC comes from `npc_name`, as in a chat, and the thread stores each NPC as a member outside the player's faction.

## Line pacing

The server paces the lines of every conversation (`say` in `server/chat/routes.py`). The reply of `/chat` and `/radiant` holds no text. A server thread sends the actions as `NPC_ACTION`, then each line as `NPC_SAY: Name|serial: line`, at least `DialogueSpeed` (5 s by default) after the line before it.

- One conversation plays at a time, and chat replies queue (`reply_loop`). A radiant conversation holds the stage (`_STAGE`) to its last line.
- In a radiant conversation, the speaker of each line shows `...` for the last 40% of the delay before the line (`THINK_SHARE`), so the lines seem to come one by one, although one call wrote them all.
- The actions go first, so an AI state change cannot clear a bubble that is already up.
- The plugin shows at most two bubbles: the newest line or `...`, and the line before it. A bubble on a third character ends the oldest bubble (`KeepTwoBubbles` in `plugin/game/GameActions.cpp`), so the participants of a radiant conversation do not all talk at once.

## LLM routing

Each LLM call names a task: `chat`, `radiant`, `profile`, `synthesis`, or `memory`. `server/config/llm_config.json` holds the providers, the profiles, the default profile, and the routes, and the Models page edits them through `/api/llm`.

| Part | Contents |
|---|---|
| Provider | An OpenAI-compatible endpoint: type (`openai` or `player2`), base URL, API key, Player2 game key |
| Profile | One model on one provider, with a per-attempt timeout and extra request parameters |
| Route | Per task: an ordered list of profiles with `null` once for the default profile, `max_tokens`, `temperature`, and a deadline |

- `llm_router.run_route` tries each profile once, in order, and moves on after an exception, a non-200 status, or an empty completion. The default deadline is 55 s, because the plugin stops waiting after 60 s.
- The profile's extra parameters override the route's `max_tokens` and `temperature`.
- A Player2 provider gets a new session key and retries once on a 401.
- `/api/llm` never returns a stored API key. An empty key field keeps the stored key, and a renamed provider sends `previous_name` (`llm_config.with_stored_keys`).
- `POST /api/llm/test` and `POST /api/llm/models` fill an empty key only when the base URL is the saved one, so a mistyped URL cannot leak the key (`llm_config.provider_from_form`).
- Defaults come from `server/data/defaults/`. A task that the file lacks gets the default route. A reset keeps a stored key only for a provider on the same host (`llm_config.reset`).

## Campaign storage

`server/store/campaign_db.py` keeps all data of a campaign in one SQLite file, `campaign.db`, in the campaign folder. The plugin reaches it only through the server's routes.

- Each write is one `BEGIN IMMEDIATE` transaction, and a profile write merges only the keys it passes, so a route that waits for the LLM cannot undo another request's change.
- Each operation opens and closes its own connection (5 s busy timeout). The database uses the rollback journal, not WAL, so an idle campaign folder is safe to copy.
- No dialogue line and no event is trimmed.
- Rejected: one database for all campaigns, because a query that missed the `campaign_id` filter would leak data.

A new campaign is a copy of a world template (see [World templates](#world-templates)) and does not depend on it afterwards. Only the Campaigns page creates and switches campaigns.

- `open_campaign` builds a missing `campaign.db` from SSR Vanilla through `campaign.db.tmp`. It refuses an earlier schema version.
- With no current campaign, or a deleted `campaign.db`, each operation fails with the reason, and a route answers 409.

### Campaign canon

The canon of a campaign is its copy of the template records.

| Record | Storage | Key |
|---|---|---|
| Overview, history | `meta` rows; the history as JSON | None |
| Faction | `faction` table (see [Factions](#factions)) | The game ID |
| Character | `character` table (see [Characters](#characters)); the profile as JSON, `knowledge` and `known_by` as columns | `u:` and the game ID |
| Race, location, region | `entity` table, with the category; the whole record as JSON | The category and the entity ID |

- `origin` is `seed`, `game`, or `campaign`.
- A save checks the record with `world_template.record_problems`, and the database refuses a duplicate game ID.
- The key of a faction or a character cannot change.

### Factions

Each campaign holds its own copy of the factions, keyed by the game's string ID. The prompt describes a faction from it (`describe_faction`).

- The server finds a faction by `factionID`, or by an exact, case-insensitive name or alias.
- A reported faction that the copy lacks gets a row with the game name (`note_faction`). A faction with no string ID gets no row.
- The player's faction follows the game name. Its description is the player faction block of the chat prompt.

### Characters

The `character` table holds every character of a campaign: canon characters, met NPCs, and the squad. The key is the `npc_id` from the plugin (`GetNpcId` in `plugin/game/Context.cpp`):

| Character | `npc_id` |
|---|---|
| A unique NPC | `u:` and the string ID of its template |
| Every other character | `h:` and the `serial` of its handle |

- A `u:` ID is the same in every save and campaign, so a canon character binds to it. The `serial` is the only part of a handle that survives a save, a town reload, and a recruit ([kenshi_internals.md](kenshi_internals.md#character-identity)).
- The server stores an `npc_id` as the plugin sends it, and builds one only for a canon character (`u:<game_id>`). A generic NPC whose `template_id` is a canon character takes that `npc_id` (`adopt_canon`).
- The name is only the `Name` key of the profile, so two NPCs with one name keep two rows. In one request, the server keys NPCs by `npc_id`, and each dialogue row stores its speaker's `npc_id` in `speaker`.
- A `Race`, `Sex`, or `Faction` of `Unknown` takes the value that the plugin reports (`get_character_data`).
- The game reports every skeleton as male, so a skeleton gets the sex Other (`reported_sex`).
- `LIVE_CONTEXTS` keeps a few fields of the latest context of each character that takes part in a chat or a radiant conversation (`merge_live_context`).

### Chat threads

Each chat exchange belongs to a chat thread, which records who took part.

- `thread` holds the ID (`AUTOINCREMENT`, so an ID is never reused), the game time of the newest exchange, the start place, the memory, and the count of auto rumor passes that did not cite the memory (see [Auto rumors](#auto-rumors)). `dialogue.thread_id` links each row. Each radiant conversation is a thread (see [Radiant conversations](#radiant-conversations)).
- `thread_member` holds the `npc_id`, the role (`speaker` or `overheard`), the join time, and whether the member was in the player's faction then. A member keeps the join time and the faction of its first join, so the history text stays stable for the cache. An overhearer that speaks becomes a speaker, so the NPC later knows that it spoke with it (`campaign_db.thread_partners`).
- `CURRENT_THREAD` ends at a chat with another NPC, a switch between Whisper, Talk, and Yell, a campaign switch, a cull, a restart, or a real-time pause of the Conversation timeout (`conversation_timeout_minutes`, default 3). A chat as another squad member stays in the thread, so one memory covers all the exchanges of the squad with the NPC.
- A cull or a character delete deletes each thread with no memory and no dialogue row.

The chat prompt uses the threads (`npc_id`, not names):

- **First meeting:** the NPC and the speaker were both speakers of a thread (`campaign_db.thread_partners`), or the NPC's history holds a line of the speaker without `(Overheard)` (`chat_prompt.spoken_with`).
- **Companions:** the scene names the others that the NPC spoke with and that are in the player's faction now.
- **Partners:** the scene names the companions that spoke in the current chat thread as a part of this conversation, not as earlier talk. Without this, a squad member who took over the talk got a scene that put the lines of the last speaker in the past.
- **Relation:** one `Relation` for the whole squad, so the sentence names the player's faction.
- **Overheard notes:** after the last line of each thread, one user line names the overhearers from the player's faction and every other speaker of the thread (`chat_prompt.overheard_notes`).

### Conversation memories

The server distils each chat thread into a short memory, which replaces the lines of the thread (`server/chat/memory.py`).

- After the Conversation timeout with no chat (`quiet_seconds`), `memory_loop` writes a memory for each pending thread (a line and no memory), one call at a time, oldest first, then the rumors of the events follow (see [Rumors](#rumors)). It also runs after each radiant conversation. A failed thread stays pending.
- Before each call, the server checks that the chat is still quiet, because a local model serves one request at a time. It ends the current thread under `THREAD_LOCK`, so each memory covers a whole thread.
- The call uses the `memory` task (see [LLM routing](#llm-routing)) and `prompt_thread_memory.txt`. The memory names each speaker and never says "you" outside a quote, so every member reads the same text.
- The stored text marks each member name with its `npc_id`, and each read puts in the current name (`chat_prompt.mark_names`, `chat_prompt.named`), so a rename changes every memory.
- `campaign_db.set_memory` stores the memory and deletes the line copies in one transaction. It drops the memory when the campaign or the thread's game time changed during the call.
- The system message holds the newest 5 memories of the threads in which the NPC was a speaker (`chat_prompt.starting_memories`). The search finds older and overheard ones (see [Memory search](#memory-search)).
- Each memory gets a header from the view of the NPC: `[Day 3, 14:05] You spoke with Stick. Izumi heard it.`
- The history holds only the lines of the threads without a memory (`chat_prompt.chat_lines`).
- The player edits or deletes a memory on Dialogue & Memories. A delete removes the thread, so the NPCs forget the conversation.

### Names

The game gives most generic NPCs a name, and the server keeps it (`name_of` in `server/chat/npc_names.py`):

| Template | Name in game | `Name` |
|---|---|---|
| `Barman /GENNAME/` | Barman Arleen | Arleen |
| No token, and another name shows | Nuno | Nuno |
| No token, and the template name shows: `Dust Bandit` | Dust Bandit | A rolled name |
| A unique NPC or a canon template | Ruka | The game or canon `Name` |

- A name token is a capitalised word between slashes (see [Kenshi internals](kenshi_internals.md#names)).
- The server sends `NPC_RENAME: <npc_id>|<Name>` (`send_rename`), and the plugin puts the `Name` in place of the token (`ShownName` in `plugin/main.cpp`), so Barman Arleen renamed Bob shows as Barman Bob.
- Outside the player's faction, the profile wins: a chat renames an NPC whose game name differs (`sync_name`). In the player's faction, the game name wins: `setName_hook` notes a rename, and the frame hook posts it to `/squad_rename`.
- A rolled name comes from `server/data/defaults/names.json`, differs from each `Name` of the campaign (`get_used_names`), and is set only when the profile is first stored. An animal keeps its template name.

### Current Job

The `CurrentJob` of a profile is a short phrase for what the NPC does now (`server/chat/current_job.py`), sent as `CURRENT JOB: ...`.

| Rule, first match wins | `CurrentJob` |
|---|---|
| A hire or escort contract (`temporary_follower`) | Temporary follower of the player's faction |
| In the player's faction | Member of the player's faction |
| A shopkeeper squad job | Running a shop |
| Another trader (`is_trader`) | Trading |
| A squad job in `TABLE` | Its phrase |
| None of these | No line, and Unknown on the web app |

- The plugin sends the squad jobs as KenshiLib `TaskType` names from `ROLE_TASKS` (`RoleJson` in `plugin/game/Context.cpp`). A test keeps `ROLE_TASKS` and `TABLE` equal. Task types belong to the engine, so they hold in every mod list (see [Kenshi internals](kenshi_internals.md#roles)).
- Rejected: the template title and the AI package name, which mods rename.

### Current Location

The `CurrentLocation` of a profile tells where the NPC was at its last chat (`location_name` in `server/chat/scene_text.py`), such as `Bar, The Hub` or `Wilderness, Vain`.

- The zone is the zone around the camera (`ZoneName`), from slot `0x10` of `WeatherSystem::ActiveRegion` (see [Kenshi internals](kenshi_internals.md#zones)), because the game gives no zone for each character.
- The chat scene reads the building from the live context, not from the profile.

### Provisional profiles

A character without a profile gets one rolled in code at its first meeting (`new_profile` in `server/chat/provisional_profile.py`), with no LLM call. A canon character keeps its canon profile.

- A person rolls three traits, a backstory, a speech manner, and a speech quirk from `server/data/defaults/` (`personality_traits.json`, `backstories.json`, `speech_manners.json`, `speech_quirks.json`). Entries have `kinds`, so a skeleton gets only what fits. An animal (`Animal` is 1, from `Character::isAnimal`) rolls only `animal_personalities.json`.
- A backstory is in the past tense and says nothing about the present, because the roll does not know the job.
- `SpeechQuirks` holds the manner, then the quirk. The `SPEECH` label of `npc_template.txt` tells them apart: the manner shows lightly in every line, and the habit, which can be a topic such as money, comes out only once in a while. The label hint sits on the field of each character, because a single hint in the radiant rules let a habit come out in every line.
- The roll is seeded by the `npc_id`, because a chat and a radiant conversation can both write a new profile.

A profile is provisional while it holds `Interactions` (`campaign_db.PROVISIONAL`), the count of the chat turns in which the NPC replied. At Chats before a bio (`bio_interactions`, default 5, 0 for on request only), `generate_bio` writes the full bio in a background thread. It never rewrites a full profile.

- Generate Bio uses `write_bio`, which stores nothing. The Dialogue Library uses `/write_bio`, `/read_bio`, and `/keep_bio`. `/keep_bio` writes only changed parts and refuses the text when the campaign changed.
- `promote_profile` writes the bio and removes `Interactions` in one transaction. `generate_bio` drops the bio when the campaign changed during the call.

### Campaign routes of the web app

| Route | Behavior |
|---|---|
| `GET /api/campaigns` | The campaigns, the templates, and why the current campaign cannot open |
| `POST /api/campaigns` | Create a campaign from a template |
| `POST /api/campaigns/switch`, `.../delete` | Switch to or delete a campaign. The name must be a listed folder, so it cannot point outside `server/data/campaigns/`. |
| `GET /api/campaign` | Events (see [Events](#events)), rumors, and chat threads with members, lines, and memories |
| `GET /api/campaign/search` | Test search hits (see [Test search](#test-search)) |
| `GET /api/campaign/canon` | Canon records with `origin`, `updated_at`, and live `current_faction` and `status` |
| `POST /api/campaign/records`, `.../records/delete` | Save or delete a canon record |
| `POST /api/campaign/characters/bio` | LLM bio text, not stored (see [Provisional profiles](#provisional-profiles)) |
| `POST /api/campaign/rumors/generate` | LLM rumor text, not stored (see [Rumors](#rumors)) |
| `POST /api/campaign/rumors`, `.../rumors/delete` | Save or delete a rumor |
| `POST /api/campaign/events/add`, `.../events/delete` | Add a custom event, or delete an event |
| `POST /api/campaign/memories`, `.../memories/delete` | Edit or delete a memory (see [Conversation memories](#conversation-memories)) |
| `POST /api/campaign/cull` | Delete the dialogue, events, rumors, thread members, and memories dated after the current game time, except custom events and their rumors. It refuses without a game report (see [Game state](#game-state)). |

- A refused campaign gives status 409. Each edit names the campaign that the page loaded, and the server refuses it for another campaign.
- A record edit carries the `updated_at` that the page loaded, and the server refuses it when the row changed after that.
- `POST /cull` from the SSR HUB is the same cull without the campaign check.

## World templates

A world template is a folder that describes a world. A new campaign copies every record except the manifest (see [Campaign canon](#campaign-canon)).

| File | Content |
|---|---|
| `manifest.json` | `format_version`, `name`, `description`, `version`, `authors`, `credits` |
| `overview.txt` | The lore that goes into every prompt |
| `history.json` | The lore timeline: a list of `title` and `text`, in timeline order |
| `factions/<id>.json` | `game_id`, `name`, `aliases`, `major`, `fields`, `description` |
| `characters/<id>.json` | `game_id`, and a `profile` with the keys of a character profile |
| `races/<id>.json`, `locations/<id>.json`, `regions/<id>.json` | `name`, `aliases`, `fields`, `description` |

- The ID of a record is its file name without `.json`.
- `fields` holds the facts of a record, in the categories of its kind (`FACTS`, see [Web app](#web-app)). The `neighbours` of a region map each bordering region to one of 8 `DIRECTIONS`.
- Each record and history entry can hold `knowledge` and `known_by` (see [Knowledge](#knowledge)), beside the `profile` of a character.

SSR Vanilla (`server/data/templates/kenshi_ssr_vanilla/`) ships read-only, because an update replaces it. The player edits a duplicate in `server/data/user_templates/<name>/`.

`server/store/world_template.py` reads, validates, and writes templates.

- One validator runs before each write and each campaign creation; an error stops it. A name that names nothing, or a neighbour pair whose two directions are not opposite, is only a warning. Names compare by their name words (`template_names`), as the server matches them.
- A faction binds to the game by `game_id`, so a rename in game does not break the link. The vanilla IDs come from the `FACTION_PROBE` lines ([kenshi_internals.md](kenshi_internals.md#factions)).
- A route takes names and IDs that match fixed patterns, never a path, so a request cannot write outside the template folders.
- Players share a template as one JSON file, so the `credits` of the manifest carry the attribution. An import also rejects unknown keys and IDs that differ only in case (Windows saves them as one file).
- An import and a duplicate write into a dot-named staging folder and then rename it, so a failure leaves no template behind.

| Route | Behavior |
|---|---|
| `GET /api/templates` | The name, title, and record counts of each template |
| `GET /api/templates/<name>` | The whole template, with its errors and warnings |
| `POST /api/templates/<name>/records`, `.../records/delete` | Save or delete one record of a user template |
| `POST /api/templates/<name>/duplicate`, `.../delete` | Copy a template as a user template, or delete a user template |
| `POST /api/templates/<name>/characters/bio` | The same as `POST /api/campaign/characters/bio`, with the race and the faction from the template |
| `GET /api/templates/<name>/search` | A test search in the template (see [Test search](#test-search)) |
| `GET /api/templates/<name>/export` | The shared file of a template |
| `POST /api/templates/import` | Write a shared file as a new user template |

### SSR Vanilla

Each fact comes from the game: its data files (FCS), its dialogue, and play. The wiki helps to find a fact, but no text comes from the wiki, so the template carries no wiki licence terms.

- The facts and the descriptions describe the start of a game. The server lays only the changed towns over them (see [Changed towns](#changed-towns)).
- A region is a zone of the game data (record type 95); the six zones without towns have no record. A location is a town (record type 13); its zone comes from the wiki town infobox.
- The `territory` of a faction names each region where its own squads spawn at the start, or where it owns a live town. The `hazards` of a region come from the game data (`WeatherAffecting`) and must hold with and without UWE.
- The `neighbours` come from a map of the zones, read by hand, because the game data holds no list. A pair counts when the zones share a stretch of border, not only a corner. Raptor Island–Dreg and Cheaters Run–Sonorous Dark also count across a None area.
- A direction is the bearing between the centroids of the two zones. Four pairs have a set direction, because a wide or wrapping zone misleads the centroid: the Arm of Okran lies west of Okran's Valley, Watcher's Rim north of Arach, Dreg southwest of the Fog Islands, and Purple Sands south of the Iron Trail.
- The UWE factions and characters bind by a UWE `game_id`, so they change nothing without UWE. Where UWE changes a vanilla fact, the field is `Unknown`, so the game fills it (see [Characters](#characters)).
- A character text that no source supports stays blank.

The `major` factions are Global. The other factions, the locations, the regions, and the canon characters are Limited. Each tier that differs from the default of its kind has a source in the game dialogue or the wiki. These records are Secret:

| Record | `known_by` |
|---|---|
| Obedience (history) | Skeleton |
| The Chaos Age (history) | Skeleton |
| Kenshi is a Moon (history) | None |
| Elder (character) | None |

A longer name wins in a history text, so the texts say "the Second Empire", not "the empire", which names the United Cities through its alias.

## Logging

The plugin and the server write the same line format, so one tool can merge both files by time:

```
2026-10-02 22:54:01,123 - INFO - SYSTEM: Server starting on port 5000.
```

Each record is one line (a line break is written as `\n`). The tag after the level names the component.

| Level | Use |
|---|---|
| DEBUG | Game events, pipe traffic, prompts, full replies |
| INFO | Start-up, configuration, campaign changes, one line per LLM call, and the lines of each chat and radiant conversation |
| WARN | A problem that the code handles |
| ERROR | A failure: the action did not happen |

`LogLevel` in the INI sets the lowest level for both sides. The default is `INFO`. A change on the Settings page reaches the plugin as `SET_CONFIG: g_logLevel` (see [Settings](#settings)).

| File | Writer | Contents | Size |
|---|---|---|---|
| `SentientSands_SDK.log` in the Kenshi folder | Plugin | The current game. The previous game becomes `SentientSands_SDK.old.log`. | One game |
| `server/logs/server.log` | Server | The server log | 512 KB, 3 backups |
| `server/logs/llm.log` | Server | Each prompt and reply, only at `DEBUG` | 2 MB, 1 backup |

The plugin flushes each line, so the lines before a crash reach the file.

## Server state

| Location | Contents |
|---|---|
| `server/data/campaigns/<name>/` | One campaign: `campaign.db` (see [Campaign storage](#campaign-storage)). |
| `server/logs/` | `server.log` and `llm.log` (see [Logging](#logging)). |
| `server/config/prompts/` | The player's prompt overrides and `base_hashes.json` (see [Prompts](#prompts)). |
| `server/data/user_templates/` | The player's world templates (see [World templates](#world-templates)). |
| `server/config/llm_config.json` | The LLM providers with the player's API keys, the profiles, and the routes (see [LLM routing](#llm-routing)). |

The release does not ship the prompt overrides, the user templates, or `llm_config.json`, so an update keeps them.
