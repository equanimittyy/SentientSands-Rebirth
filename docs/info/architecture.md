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
  _SentientSandsRebirth.info the Steam Workshop data of the mod
  SentientSandsRebirth.mod   its header holds the mod version, which FCS sets
  LICENSE                    the GPL text
  NOTICE                     the copyright notices and the additional term
  SentientSands_Config.ini   settings, created by the server on first start
  logs/                      the plugin and server logs, created at runtime
  server/
    main.py
    core/  chat/  store/  dashboard/
    data/templates/  data/prompts/  data/defaults/
    python/                  embedded runtime, added by scripts/package_release.py
    config/                  created at runtime
    data/campaigns/  data/user_templates/   created at runtime
```

- The plugin takes the mod root from the path of its DLL, and runs `server\python\python.exe server\main.py`, or `python` on `PATH` (`StartPythonServer` in `plugin/core/Utils.cpp`).
- The mod root is the parent of the folder of `main.py`. From the repo, the server finds the INI and `logs/` in `mod/` (`resolve_mod_file`).

## Runtime flow

1. RE_Kenshi loads the DLL and calls `startPlugin`. It finds the game world through KenshiLib and loads the INI before it installs the hooks, so no hook runs without them. Without the game world, the plugin installs no hook and stays off. It then starts the pipe listener.
2. A thread starts the server (`ServerThread` in `plugin/main.cpp`). With `OpenWebPanelOnStart=1`, it passes `--open-browser`, and the server opens the web app when no earlier tab reconnects.
3. The plugin sends HTTP POST requests to `127.0.0.1:5000` (`plugin/core/Comm.cpp`). The server rejects a `Host` other than `127.0.0.1:5000` or `localhost:5000`, and a foreign `Origin` (`server/core/request_guard.py`), so web pages cannot use it.
4. The server sends commands back through the named pipe `\\.\pipe\SentientSands`, such as `NOTIFY` and `NPC_SAY` (see [Line pacing](#line-pacing)).
5. Each prompt comes from the prompt files (see [Prompts](#prompts)) and the campaign state, and goes down the route of its task (see [LLM routing](#llm-routing)).

## Threading

Background threads never change game objects or MyGUI widgets. They push messages onto `g_messageQueue` with `QueueMessage` (`plugin/core/Comm.cpp`), and a request whose reply changes a window goes through `PostForGameThread`, which queues the reply as a `CMD:` message with a tag. `playerUpdate_hook` drains the queue on the game thread (`ProcessMessageQueue`). The drain takes the whole queue under the lock and runs the messages after it, so the pipe thread never waits for the game work of a message, and `send_to_pipe` does not drop a message for lack of a pipe instance. A message that the game thread queues during the drain runs on the next frame. New code that makes results off the game thread must use this queue.

## Game state

The plugin reads the game state only when a request needs it. Do not post it on a timer: that built full contexts on the game thread while no prompt used them.

| Request | Game state that it carries |
|---|---|
| `/chat` | The contexts of the target and of the squad member who speaks, the game events, the changed towns, and the towns that the line names (see [Directions](#directions)) |
| `/radiant` | The participants, the NPCs near the center, the context of the center, the game events, and the changed towns |
| `/cull`, `/report` | A report: the player's context, the game events, and the changed towns (`GameReport`). `/report` goes when 50 events wait, when the oldest event waited 60 s, when a `rekey` event waits, or on `REPORT` from the pipe. |
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
| `rekey` | `addActiveObject_hook`, `addCharacterAt_hook` | A squad change gave a character that already had a handle a new `npc_id`; holds `old` and `new` (see [Characters](#characters)) |

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

The rumor tells only news of the world that a speaker told in a conversation. It never tells what the speakers did in the conversation, because those deeds are mostly everyday trades and plans. It never tells what the player's faction did, because a kill or a capture of the squad gets the rumor of its event.

`memory_loop` runs a pass when the timer passed, the chat is quiet, no memory or event rumor waits, and the pool holds a memory that no pass read. The pass runs in the thread of the memories, so its call overlaps no other call.

- The pool holds each memory whose `thread.rumor_passes` is less than 6 (`RUMOR_PASSES`). A pass reads the newest 40 (`campaign_db.rumor_pool`).
- After a valid reply, a cited memory goes to 6, a memory that was read and not cited gets +1, and an older memory in the pool goes to 6 (`count_rumor_pass`). So dull memories leave, and a theme can build over several passes.
- The prompt (`prompt_auto_rumor.txt`) holds the player's faction, the memories with labels 1 to N, and the newest 30 rumors. The faction line names each member of the player's faction in the memories (`thread_member.in_player_faction`), because a memory names a character but not its faction. The reply is `{"rumor": "...", "memories": [1, 2]}`. The empty rumor is the default.
- `campaign_db.add_auto_event` stores the event and its rumor, and sets the cited threads to 6, in one transaction. Nothing is written when the active campaign changed or a cited thread left the pool during the call.
- The event takes the newest game time of its threads, so the cull deletes it, and the auto rumors do not hold the 3 newest places for good.

### Events window

The Events window of the SSR HUB mirrors Campaign Canon > Events through `/events`, `/events/content`, `/write_rumor`, `/read_rumor`, `/keep_rumor`, `/add_event`, `/delete_event`, and `/delete_rumor`. These share the code of the web app routes in `server/chat/routes.py`.

- The reads return the active campaign, and each write sends it back. A write is refused when that campaign is no longer active, because the same ID can name another event.
- Each close of a popup makes the pending reply stale (`CloseEditor` in `plugin/ui/Widgets.cpp`).

### Changed towns

A world state can swap the data of a town for an override with another owner or type. The location records describe the start of a game, so the server lays the changes over them (`server/chat/towns.py`).

- Each chat, radiant conversation, and report carries `changed_towns` (`ChangedTowns`): each town whose `getGameData` is not its `getOriginalGameData`, with its owner, owner game ID, and type. The server keeps only the latest list, because a load can undo a change.
- `towns.current` lays the change over the location record of that name, so it reaches the knowledge, the lore hits, the place records of the chat scene, and the radiant place topic (see [Own records](#own-records)).
- A sentence such as "Brink is now a town held by Reavers." leads the description. It gives no time, because the plugin sees only that a change holds.
- A town that falls to ruins keeps its owner as the former owner, and a new owner of a ruin changes nothing (see [Links](#links)).
- The game decides which world states hold, so the overrides of a mod work too.

### Dead and imprisoned unique NPCs

The game keeps the state of each unique NPC that it spawned: alive, dead, or imprisoned. The faction and character records describe the start of a game, so the server lays the deaths and the imprisonments over the factions of the leaders and the nobles and over the canon character records (`server/chat/rulers.py`).

- Each chat, radiant conversation, and report carries `unique_states` (`UniqueStates` in `plugin/game/Context.cpp`): the string ID, the name, and the state (`dead` or `imprisoned`) of each unique NPC that is not alive. The server keeps only the latest list, because a load can undo a death.
- The plugin reads the states from a class of the game that KenshiLib does not declare (see [Kenshi internals](kenshi_internals.md#unique-npc-states)). On a game version without a known address, it sends `null` and logs a warning, because an empty list would mean that every unique NPC lives.
- `rulers.current` gives a faction whose `leader` or `nobles` names such an NPC a `dead` or an `imprisoned` field, for example "leader: Tinfist; imprisoned: Tinfist". The `leader` and the `nobles` stay, so the links of the record hold.
- The fields reach the lore hits and the current and origin factions of the NPC in the system message (`describe_faction`). Each NPC that knows the faction knows the state, as for a changed town.
- A name matches by its name words: the game name of the NPC, or the `Name` of its canon character record, whose `npc_id` is `u:` and the string ID. A value that names two NPCs, such as "Dimak and Buzan", is split at "and" when it matches no one as a whole.
- The canon character record of such an NPC gets a `state` field (see [Lore records](#lore-records)).
- Campaign Canon shows the state of each unique character in the Dead and Imprisoned rows (`rulers.game_state`). A generic character has no such rows, because the game keeps no state of it. The rows show Unknown while the server holds no states.

## Web app

The server serves `server/dashboard/web/` at `/` and `/web/<file>`: plain HTML, CSS, and JavaScript modules with no build step and no CDN, so the web app works offline.

| Page | Route | Storage |
|---|---|---|
| Settings | `/settings`, `/settings/defaults` | `SentientSands_Config.ini` |
| Models | `/api/llm`, `/api/llm/test`, `/api/llm/models`, `/api/llm/reset` | `server/config/llm_config.json` |
| Prompts | `/api/prompts` | `server/config/prompts/` |
| Campaigns | `/api/campaigns`, `/api/campaign/cull` (see [Campaign routes of the web app](#campaign-routes-of-the-web-app)) | `campaign.db` of each campaign |
| Editor | `/api/campaign/canon`, `/api/campaign/records` (see [Campaign canon](#campaign-canon)); `/api/campaign/search`, `/api/templates/<name>/search` (see [Test search](#test-search)); `/api/campaign`; `/api/templates` (see [World templates](#world-templates)) | `campaign.db` of the active campaign; `server/data/user_templates/` |
| Tutorial | None: static text in `index.html`, and the videos that `scripts/tutorial_video/` renders into `videos/` ([development.md](development.md#tutorial-videos)) | None |

- A GET route must not change state, because a page on another site can send a GET without an `Origin` header. The presence stream is the only exception, because EventSource sends only GET.
- The web app polls `GET /context` every 3 s (`poll` in `app.js`). Without an answer, it shows a banner and disables Save, so unsaved changes survive a server restart. The reply also holds the active campaign and `writes`, a count of database commits and successful POSTs (`count_write_requests`); a change refreshes each loaded page, unless a request runs, a dialog is open, or the player types.
- Each tab holds `GET /web_panel/presence` open, so the server can count the open tabs.
- The Tutorial links to YouTube for the setup of other services, such as Player2 or Ollama, so SSR does not keep their steps up to date.
- The Help window (`plugin/ui/HelpWindow.cpp`) opens from the SSR HUB and from `/help` in the chat window. It shows the topics of the Tutorial that concern the game. Each topic has a card with the same title and text on the Tutorial tab, so a change to one needs the same change to the other. `server/tests/test_tutorial.py` checks the titles.
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
- The release ships no INI, so an update keeps the settings. On the first start the plugin keeps the defaults of its globals (`plugin/core/Globals.cpp`, read by `LoadPluginConfig`), and the server writes `SETTINGS_DEFAULTS` (`server/core/settings.py`) and pushes each plugin value (`push_settings_to_plugin`).
- `OpenWebPanelOnStart` is read before the server starts, so its default (`g_openWebPanelOnStart` in `plugin/core/Globals.cpp`) must agree with `SETTINGS_DEFAULTS`.
- `GET /settings/defaults` is a separate route, because the plugin reads the `/settings` reply by the first match of each key (`GetJsonValue`).
- `send_to_pipe` retries for 0.25 s, because the plugin re-creates its pipe instance after each message.

## Prompts

- `server/data/prompts/` holds the shipped defaults. An override with the same name in `server/config/prompts/` wins when it holds text (`load_prompt_component`), so an update keeps it.
- `/api/prompts` (`server/chat/prompt_store.py`) takes only the name of a shipped `.txt` file, never a path. An empty save or a save equal to the default deletes the override. `base_hashes.json` holds the SHA-256 of the default at each save, so the page marks an override whose default changed.
- `prompt_system.txt` sets the common speech of Kenshi for chats and radiant conversations (`HOW PEOPLE TALK`): casual talk in common words and simple sentences, short lines, talk of concrete needs, dark humor, and free swearing. It comes from the squad and bar talk of the game (the biome entry and bar patron dialogues), whose median line has 8 words. The dialogue of the game swears often, for example with fuck, hell, damn, and shit. Without it, radiant lines had a median of 18 words, and a third of them used formal words or poetic images. With a request for plain words only, the lines became short but kept stiff, roundabout sentences, so it also asks for simple sentences as people say them out loud. The personality and the `SPEECH` of a character win over it, because some rolled manners and canon characters, such as the Phoenix and Hobbs, talk formally or ramble.
- `prompt_store.render` fills only known `{name}` placeholders and leaves other braces as text, so a stray brace cannot fail a call. An override may not add an unknown placeholder. Rejected: Jinja2, because template logic lets one edit break the whole prompt.

A chat request is ordered for the provider's prompt cache, which reuses only an identical start (`chat` in `server/chat/routes.py`, `server/chat/chat_prompt.py`):

| Part | Content | Changes |
|---|---|---|
| System message | `prompt_chat_template.txt`: `prompt_system.txt` (`prompt_animal_system.txt` for an animal), the judgment rule, `npc_template.txt` and `npc_persona_template.txt`, `prompt_chat_scene.txt`, the newest memories of the NPC's threads (see [Conversation memories](#conversation-memories)), then `prompt_action_rules.txt` in an action dialogue | When a conversation starts, such a memory is written, or the action rules change |
| History | The NPC's thread lines without a memory, as user and assistant turns (see [Chat threads](#chat-threads)) | One exchange more each turn |
| Last user message | `prompt_chat_turn.txt`: the found memories, rumors, and lore (see [Lore retrieval](#lore-retrieval)), the player's line, a short reminder | Every turn |

- The action rules come last in the system message, because a chat thread can go from plain chat to an action dialogue and from one category to another. A change then keeps the cache of the rest of the system message, but the history after it is read again.
- Only earlier threads decide whether the NPC has met the speaker, so the first-meeting sentence of the scene stays for the whole conversation, and the second turn keeps the cache.
- The scene is a snapshot for the whole conversation (`CONVERSATION_SCENE`). A conversation ends when the player chats with another NPC, speaks as another squad member, switches the campaign, when the NPC's name or faction changes, when the other speakers of the current chat thread change, or when the NPC moves to another town or region, because the search skips the place records of the scene by the current place (see [Order of the lore](#order-of-the-lore)).
- `server/chat/scene_text.py` writes the scene as second-person prose, because a model reads a sentence more reliably than a number. The relation bounds match the relation labels of the Dialogue Library.
- The history is a block window (`chat_prompt.history_window`) that moves by 20 lines, so its start stays cacheable. `history_turns` makes only the NPC's own lines assistant turns.
- An overheard line is stored as `(Overheard) Speaker to Target: ...`, because without the target a listener took "you" as itself. An animal never overhears, and neither does a dead or knocked-out NPC (`chat_prompt.overhearers`). An NPC that plays dead is awake, so it overhears.
- The judgment is the change in how the NPC feels about the player, from -5 to 5. Rejected: a judgment of politeness, because a scornful NPC grew friendlier with each apology.
- Each reply line starts with `Name|key:` (see [Line pacing](#line-pacing)), because the plugin takes the text before the first colon as the speaker (`TakeSpeaker` in `plugin/main.cpp`). An animal replies only in `*actions*`.
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
| Character | `Name`, `Alias` of the profile | `race` and `faction` of the profile | `Backstory` | `campaign_db.list_records("character")` |

- A record with an empty text is no hit, but a link or a `known_by` can still name it.
- A field with an empty value is left out of each lore line (`describe_record`), because the editor saves a fact row that the author left empty.
- A character record also holds the `Sex` and the `Personality` of the profile as its `sex` and `personality` fields, so the lore line tells the model the sex and the nature of the character. The search skips these fields, because "female" would find every female character and "proud" every proud one. The `SpeechQuirks` stay out, because they are written for the model that speaks as the character.
- A character that the game holds dead or imprisoned also gets a `state` field (see [Dead and imprisoned unique NPCs](#dead-and-imprisoned-unique-npcs)). The search skips it, because "Who is dead?" would find every dead character.
- A character is a record only when it is canon (`origin` `seed` or `campaign`), because a rolled backstory is invented.
- The index is built in memory for each line, so an edit reaches the next line. The search uses SQLite FTS5 ([development.md](development.md#probes)).

### Name matching

1. The line and each name become lowercase words, split at each character that is not a letter or a digit. A word of 4 or more letters loses a final "s", except "cats" (`CURRENCY`): a barter names the money on every line, and as "cat" it found the character Cat.
2. A name loses a leading "the".
3. A name matches when its words appear in the line in order, with no word between them.
4. A match inside a longer match is dropped.

### Content search

An FTS5 table holds one row per record (name, aliases, fields, text) with the `porter unicode61` tokenizer.

1. A word of the line searches only when it is in the vocabulary of names, aliases, and field values, is not a stop word or "cats", and appears in no more than a tenth of the records (`COMMON_SHARE`). The stemmer turns "cats" into "cat", which found Cat-Lon in the fields of the Second and the Third Empire. The vocabulary keeps chat words out, because BM25 ranks rare words high.
2. The search is an OR of these words, ranked by BM25 with the weights in `WEIGHTS`.
3. A hit below 60% of the best score is dropped (`SCORE_RATIO`).

### Order of the lore

- Name matches come first. Content hits follow by place, each group by score (`place_order`): the current location (`town_name`), the current region (`zone_name`, see [Current Location](#current-location)), its locations, the neighbouring regions (either side names the other in `neighbours`), then the others.
- The place order adds no entry, because the model talks about the text that it gets.
- A record that the system message holds is skipped (`background.in_system_message`).
- The chat scene holds the records of the current location and the current region that the NPC knows (`background.scene_place`), so a line about "this town" or "around here" needs no name. The search skips them. The region leaves out its `neighbours`, because few lines ask for a direction, and the directions line gives them when a line does (see [Directions](#directions)). An animal gets no place records.
- An entry's text and each text field end at the last sentence end before 700 characters (`clipped`), so a long character personality is cut like the text. A list field is not cut.

### Directions

The lore of a turn ends with the directions from the NPC to the places that the turn asks about (`background.directions`), for example "From here, Okran's Gulf lies to the north and Squin to the west." The line takes no slot and has no cooldown.

| The player's line | Places in the line |
|---|---|
| Names a direction, such as "east" | The neighbours of the NPC's region that lie that way |
| Asks for a "direction" | All neighbours of the NPC's region |
| Names a neighbouring region, or a location in one | That region |
| Names a location other than the NPC's town | That location, with its direction from the game |

- The record of a neighbour gives the directions from its own side, and only on the turn that names it. With that alone, the model put Okran's Gulf east of the Border Zone, not north.
- Only a name match counts, because a content hit such as "bonedogs" finds most regions.
- Rejected: all directions in the chat scene, because few turns need them.
- The game data holds no town positions, so the plugin reads them in play. Only a line that names a town reads a position: `NamedTowns` (`plugin/game/Context.cpp`) matches each town name in the line as the server matches a name, and sends the offset of the nearest town of that name from the NPC as `named_towns`. The server turns each offset into one of the 8 directions (`background.town_directions`).
- A place that a line carries from the last turn (see [Follow-up lines](#follow-up-lines)) gets its direction again. A town keeps the direction that the plugin gave on its own turn, so "Where is it from here?" can follow "Have you heard of Squin?".
- A named town whose location record the NPC cannot know (see [Knowledge](#knowledge)) gets the line "You do not know the way to Clownsteady." in place of a direction (`background.unknown_towns`). Without it, the model made up a way. A town without a location record gets neither line, because nothing tells whether the NPC knows it.

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

### Follow-up lines

The hits of a turn stay out of the history (see [Block](#block)). So when a line names nothing, the hits that the last line found by name come first again (`carried` of `background.search`): "What does she rule?" gets the entry that "Who is Esata?" found.

- A line names something when it names a lore record, even one that the NPC cannot know (`background.names_record`), or a town that the plugin found (`named_towns`). The search drops a record that the NPC cannot know, so without this rule "How about to Clownsteady?" names nothing, and "Where is it?" gets the direction of the town before it.
- The lore, the memories, and the rumors carry alike. Only a name match carries, because a content hit is often wrong. A carried hit passes the cooldown, as a name match does.
- A hit carries for one turn only (`background.named`), so it does not stay for the rest of the conversation.
- The server keeps the named hits, the directions of the named towns, the towns that the NPC does not know the way to, and the items that the price guide of a trade priced, of the last line per pair of speaker and NPC (`LAST_NAMED`). Another pair, or a campaign switch, drops them.
- Rejected: fuzzy name matching, which would find "Esata" from "Estata" but would also find wrong records.

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
- A search as a character also shows the line of [Directions](#directions). Without the game, a named town shows "(direction from the game)" in place of its direction (`GAME_DIRECTION`), and each named location that the NPC cannot know shows as a town that it does not know the way to. A search has no earlier turn, so it carries nothing.

## Radiant conversations

A radiant conversation is a talk between 3 to 5 of the player's characters, or between 2 to 5 NPCs near them (see [NPC radiant conversations](#npc-radiant-conversations)), in which one LLM call writes each line. The plugin asks for one each `RadiantChatMinutes` (10 by default) of unpaused real time, and on Trigger Radiant.

1. The plugin picks the center: the selected character if it can talk, or else the first squad member that can (`GetRadiantParticipants` in `plugin/game/Context.cpp`).
2. The participants are the center and the nearest of the player's characters within `TalkRadius`, up to 5. With fewer than 3, the plugin sends no participants.
3. The NPCs are the characters outside the player's faction that can talk and stand within `YellRadius` of the center, nearest first, each with the handle of its squad (`GetRadiantNpcs`).
4. The plugin posts the participants, the NPCs, the center's context as `player_context`, and the game events to `/radiant`. It sends nothing when both lists are empty.
5. The server picks 2 to 5 NPCs of one squad (`radiant.npc_group`, see [NPC radiant conversations](#npc-radiant-conversations)). It lets them talk when a rumor exists and a roll is under the NPC radiant chance (`npc_radiant_chance`, default 50 %, `radiant.npc_talk`). Else it picks the participants.
6. The server makes no call when the picked list is empty, when one of the picked characters fought within 3 game hours (`world_events.fought_recently`), when no topic has material, or when a conversation plays.
7. Otherwise it answers at once, and a server thread writes each line with its own `radiant` call and shows it (`play_radiant` in `server/chat/routes.py`, see [Line pacing](#line-pacing)). The call for the next line runs while the line before it shows. After the last line, the server stores the lines as a new thread (`remember_radiant`). The participants that spoke join the thread as speakers, and the others as overhearers.

The server, not the LLM, picks one topic kind at random from those with material (`radiant.topic`):

| Kind | Material |
|---|---|
| Shared memory | A memory of a thread with at least 2 participants (`campaign_db.shared_memories`) |
| Surroundings | The center's place and the lore entry of its town (`radiant.place_topic`) |
| Rumor | One of the 3 newest rumors |

- The system message is `prompt_system.txt` without the chat reply rules (`response_rules.txt`), which are written for one NPC who answers the player. The user message is the frame (`prompt_radiant.txt`), then `prompt_radiant_line.txt`. The frame describes each participant with `npc_template.txt` only: what anyone can see, such as the race and the factions. The rules of the frame give the conversation an opening, an exchange, and a closing line, and make each participant keep its own voice, take up the point of the line before it, add something new, and give its opinion. Without these rules, one call writes one same-voiced remark on the topic for each participant, and stops mid-thread. With a rule that only asked each line to follow from the one before it, most lines opened on a word of the line before and added nothing, so the talk drifted from word to word.
- Each call gives the persona of its speaker alone (`npc_persona_template.txt`: the personality, the backstory, and the speech). When one call wrote all the lines with every persona in its context, Gemma 4 gave the manner of one speaker, such as rhymes or clipped words, to every speaker.
- The line prompt holds the lines so far (`radiant.talk`), the persona of the speaker, and the next turn (`radiant.turn`). The system message and the frame stay the same for each line, and the lines so far grow only at their end, so each call reuses the provider's cache of the call before it up to the newest line. Only the persona and the next turn are new to the cache.
- The next turn tells where the line stands, such as "Line 1 of 6, which opens the talk" or "Line 6 of 6, the last, which closes the talk", because a call sees only the lines before it.
- The server picks the line count at random from 2 to 4, 5 to 7, or 8 to 10 (`radiant.LENGTHS`). The frame gives the count with its feel, such as "The talk goes back and forth a few times", so that each line fits the shape of the talk.
- The server also picks the speaker and the addressee of each line (`radiant.turns`), because the model, left to choose, gave each participant one turn in a fixed round, and no line answered another, also under a rule against it. The first speaker speaks to everyone. Then the one addressed answers, or a third participant cuts in, at even odds (`REPLY_SHARE`), and either speaks to the last speaker. Two participants take turns. The next turn names the speaker as `Name|ID` and the addressee by name, and a speaker can speak to everyone instead where that fits.
- The prompt tells how well each pair of participants knows each other (`radiant.acquaintance`), so strangers ask about each other and old companions skip the introductions. That hint sits on the label of the list, because Gemma 4 ignored it as one of the radiant rules. The phrase comes from the count of the earlier threads in which both were speakers (`campaign_db.thread_partners`): 0 is "have never talked", 1 to 2 is "have talked a little", 3 to 9 is "know each other", and 10 or more is "know each other well".
- The reply holds only the words of the line, because the server knows the speaker. `reply_text.spoken` cleans it as it cleans a chat reply: it drops the label of the speaker, which the model copies from the lines so far, and it ends the reply at a line of another participant (`radiant.voices`). A failed call, or a reply without words, ends the talk, and the server stores the lines so far.
- A campaign switch during the talk ends it, and the server stores nothing, because the same `npc_id` can name another character in another campaign.
- A radiant conversation does not change `CURRENT_THREAD` or the quiet clock. The memory loop runs after each one (`state.LAST_RADIANT`).

### NPC radiant conversations

An NPC radiant conversation takes the place of a talk of the player's characters. Its only topic is one of the 3 newest rumors, so without a rumor the player's characters talk instead.

- The NPCs belong to one squad, because NPCs that stand near each other only by chance have no reason to talk. So its frame (`prompt_radiant_npc.txt`) says that they know each other, and it has no lines on how well each pair knows each other.
- Only an NPC whose Current Job is Hanging out at a bar talks (see [Current Job](#current-job)). The server picks the squad, because the job table also decides when a bar visit is only the side task of a guard.
- The server rolls the count of NPCs, from 2 to 5 (`radiant.SPEAKERS`). The nearest squad that has a member with a profile wins, else the nearest squad. Its members with a profile talk first, nearest first, and members without one fill the rest of the count. Each NPC without a profile gets one as at a first meeting. A squad with fewer members than the count talks with all of them.
- A player with fewer than 3 characters together gets an NPC radiant conversation at the NPC radiant chance, and no radiant conversation otherwise.
- For an NPC, only a knockout counts as a fight, because the game events hold only the attacks of the player's faction (see [Game events](#game-events)).
- The name of an NPC comes from `npc_name`, as in a chat, and the thread stores each NPC as a member outside the player's faction.

## Chat target

The chat key opens the chat window on the NPC that the player has selected. When no NPC is selected, the window opens on the last character that the player sent a line to, an NPC or a squad member (`CreateChatUI` in `plugin/ui/ChatWindow.cpp`). A target that the window only showed does not replace that character. When no NPC is selected or remembered and no other player character stands within Talk range of the squad, the window opens on a talk to itself (see [Talking to itself](#talking-to-itself)), so the chat key always opens the window. Rejected: the last NPC that the player selected, because a click on an NPC that the player never spoke to replaced the conversation.

## Chat range

The plugin sends a chat line only when the target stands within range of the speaker: `WhisperRadius` for a whisper, else `TalkRadius` (`SendChatLine` in `plugin/ui/ChatWindow.cpp`). Otherwise the chat window shows "{name} is too far away.", the plugin log names the distance and the range, and the line goes nowhere.

- A plain yell is the exception, because it goes to each NPC within `YellRadius`, not only to the target (see [Yells](#yells)). A plain yell at a target beyond `YellRadius` goes out as a yell at the speaker, so only the NPCs in range can answer, and the chat window shows "{name} is too far away.".
- An action dialogue in Yell mode needs the target within `TalkRadius`, because its offer belongs to one NPC.
- A test command, a line that starts with `/`, skips the check, because no character says it.

## Yells

A plain chat line in Yell mode can get up to 3 replies, one after another, from the NPCs that hear it (`chat` in `server/chat/routes.py`). An action dialogue in Yell mode gets one reply from its NPC, because an offer and a judgment belong to one NPC.

- The NPCs that can answer are the target and each NPC within `YellRadius` that is outside the player's faction and awake (`radiant.can_answer`). A target beyond `YellRadius` does not hear the yell, so the plugin sends it as a yell at the speaker (see [Chat range](#chat-range)). An animal never answers, and a yell at an animal outside the squad gets only the reply of the animal.
- Only the player's speaker speaks for the squad. So a yell at the speaker or at a squad member gets only the replies of the other NPCs, and no reply when no other NPC can answer.
- A yell at the speaker itself is a yell at everyone. Each NPC that answers it gets the line as spoken to it, for example `(Yelled) Stick: ...`, and each other NPC overhears it, for example `(Overheard) (Yelled) Stick to everyone: ...`.
- The "..." bubble goes to the NPC that answers first (see [Chat lines](#chat-lines)), because only the server knows which NPC answers a yell. No reply of a yell shows the "{name} is thinking..." status.
- A plain chat reason of the target (see [Action dialogue](#action-dialogue)) does not reach another NPC that answers first, because the reason judges only the target.
- The server rolls the count of replies: 1 at 50 %, 2 at 30 %, or 3 at 20 % (`radiant.YELL_REPLIES`). When only one NPC can answer, the count is 1.
- The server picks the speaker and the addressee of each reply (`radiant.yell_turns`), as in a radiant conversation. The first reply speaks to the player's speaker. Then the NPC addressed answers back, or another NPC cuts in, at even odds (`REPLY_SHARE`), and speaks to the last speaker or to the player's speaker.
- Each pick takes a favoured NPC at 75 % (`FAVOURED_SHARE`): the target, an NPC whose name the line holds, or an NPC that spoke in the yell thread. So in a crowd the NPC that the player meant mostly answers, but the target does not have to.
- The first reply is a chat reply of its speaker, with its memories, the lore search, and the judgment. When another NPC answers first, its chat call takes the `nearby` entry of that NPC, and the player's line reaches it as overheard, for example `(Overheard) (Yelled) Stick to Jorge: ...`.
- Each later reply is a radiant line with the `radiant` task (`play_yell`): the frame `prompt_yell.txt`, then `prompt_radiant_line.txt` with the lines so far and the persona of the speaker. It has no judgment. It plays on the stage after the first reply, so no other reply plays between the lines, and the call for the next line runs while the line before it shows.
- Each later line joins the chat thread when it shows, and its speaker becomes a speaker of the thread. A failed call or a campaign switch ends the yell, and the lines so far stay.
- All plain yells share one chat thread, with the key `(None, "yell")`, so the NPCs that answered one yell are favoured at the next.
- A reader that neither spoke a line nor was spoken to gets the line as `(Overheard)` with its addressee (`chat_prompt.heard_line`).
- The plugin sends `animal` in each `nearby` entry (`PartyFields` in `plugin/game/Context.cpp`), so neither an answer nor an overheard copy goes to an animal.

## Talking to itself

A squad member talks to itself in Talk or Whisper mode when the speaker button and the target button of the chat window show the same character. A press of one of the buttons does this. The chat window also opens on a talk to itself when the last line was a talk to itself, and when no one else is within Talk range and no NPC is the target. A selection of a squad member makes it the speaker, and a selection of several makes the first of them in the order of the player's characters the speaker. A selection of the target makes the target the speaker and the last speaker the target, so two squad members talk in turns in one chat thread (see [Chat threads](#chat-threads)) until the player selects another character. Otherwise the chat window never opens with the target as the speaker (`SelectChatSpeaker` and `CreateChatUI` in `plugin/ui/ChatWindow.cpp`). A yell at the speaker itself is a yell at everyone (see [Yells](#yells)).

- The server takes a line as talk to itself when the speaker and the target have the same `npc_id` and the mode is not Yell (`self_talk` in `chat` in `server/chat/routes.py`).
- The scene has no section for the person before the NPC, and its first sentence is "You are talking to yourself." The sentences that set the speaker apart from the NPC go: the relation, the squad leader, the strength comparison, and the game memories of the speaker (`scene_text.npc_text`). The last instruction is "Answer yourself as Beep."
- The personality of the character sets how mad the talk sounds. Rejected: a scene sentence that tells the character to answer its words as another voice, because it pushes every character towards madness, also a character that only mutters to itself.
- The prompt has no judgment rule, and the server ignores a judgment in the reply, so the relation does not change.
- The thread key is `(npc_id, mode, "self")`, so the talk does not join a thread in which another squad member talks to the character. Otherwise the memory would take the words of the character to itself as words to that squad member.
- An overhearer stores the lines as `(Overheard) Beep to themself: ...` (`chat_prompt.heard_line`). The memory header of a thread with no other speaker is `You talked to yourself.`, and its Library label is `Talk with oneself`. `prompt_thread_memory.txt` tells the model that a person who spoke alone talked to themself.
- The reply keeps a line labeled with the name of the character, although that name is also the name of the speaker (`reply_text.spoken`).

## Action dialogue

A chat line that starts with `!` marks its chat thread as an action dialogue. The NPC talks under the action prompt, and it can make an offer of a deal that the game carries out when the player accepts it.

- `action_dialogue.parse` (`server/chat/action_dialogue.py`) reads the mark. `chat` in `server/chat/routes.py` then checks the blocks, runs the classify call for a line of `!` and a space, and sends the action call. Both calls take the `action` route.
- The mark is the word after the `!`, up to the first character that is not a letter, in any case. A letter or a word of [Categories](#categories) names the category, a space runs the classify call, and `e` or `end` ends the action dialogue. Any other word, a category with no text after it, and a lone `!` are a failure. A `!` before any other character, such as `!!!` or `!?`, is plain chat.
- The classify prompt (`prompt_action_classify.txt`) holds only the player's line and a numbered list of the categories, in the order of `CATEGORIES`, and it asks for the number of one choice. The list ends with "None of these", so that the model can reject a line that fits no category instead of forcing it into one. That choice, an output with no number of a choice, and a call that gets no reply are a failure. A failure sends no action call, stores no line, and shows "X didn't understand what you meant.".
- The blocks read only the contexts of the request. A knockout of the speaker or the NPC blocks every line, plain chat too, and DISMISS of an NPC that is not a hired follower is blocked (`gate_block`). The classify list leaves out a blocked category.
- The plugin stops each line of a knocked-out speaker or NPC before the request (`SendChatLine` in `plugin/ui/ChatWindow.cpp`), because the speaker's bubble and the NPC's "..." show before the reply. A test command still goes, because it shows no bubble.
- A line of a deal that the story allows but code rules out goes to plain chat instead, with the reason as the NPC's thought in the turn message: a marked line to an animal or to a member of the player faction (`mark_chat`), and a line that fails a gate of its category (`plain_chat`), for example a threat from a cage.
- The plugin sends `slave`, `captor`, `bounty`, `has_first_aid`, `has_repair_kit`, `needs_first_aid`, and `needs_repair` in each context (`GetDetailedContext` in `plugin/game/Context.cpp`), because a slave in a cage reads as `imprisoned`, the player can recruit a captive of the player faction, the bribe of a LIBERATE release adds the bounty, and HEAL needs a kit that fits a wound of the speaker.
- `CURRENT_THREAD` holds the category and the speaker of the action dialogue (`action`). A line without a mark keeps the category. A marked line that goes to plain chat ends the action dialogue but not the chat thread, because an action dialogue holds one category at a time, and a later mark starts the next one in the same chat thread. A line of another squad member starts a new chat thread (`thread_of`). The ending tag `[END]`, `!end`, a failure, and an error of the action call end the chat thread.
- The system message ends with `prompt_action_rules.txt` (see [Prompts](#prompts)). It holds the file of the category (`prompt_action_<category>.txt`), or a variant that code picks from the game state (`prompt_action_barter_table.txt` for the barter window, and `prompt_action_follow_mercenary.txt` for a mercenary): the request, the shape of the deal tag with one example, and the tags that end the category. The model writes no category tag, because code adds it to the bubble.
- The turn message of an action call starts with the facts of the hard limits, for example the cats of the NPC, and the lean as a thought of the NPC in one of three bands, with the facts of the lean as reasons to agree and to refuse (`offers.facts`, `action_dialogue.lean`, `action_dialogue.thought`), because both change each turn.
- The lean adds up the bonuses of the facts of the category. A sum of +2 or more reads "You are inclined to agree.", -1 to +1 reads "You could go either way.", and -2 or less reads "You are inclined to refuse.", because a small model follows a plain band better than a number. BARTER, HEAL, LIBERATE, RECRUIT, and FOLLOW count the NPC's `Relation`: +2 at 60 or more, +1 from 25 to 59, -1 from -59 to -25, and -2 at -60 or less (`relation_bonus`). [Categories](#categories) holds the other facts of each lean.
- The action call keeps the judgment of plain chat, so each reply can change the NPC's `Relation`, and a threat can cost relation.
- The server sends each system message through the pipe as `NOTIFY:`: a block, a failure, the refusal of RECRUIT or FOLLOW, and "X made an offer it can't keep. (LLM hallucinated an offer it can't make)".
- A short deal tag names the deal: `[AGREE]` or `[AGREE: 800 cats]` for RECRUIT, HEAL, and LIBERATE, `[AGREE: 2 days, 500 cats]` for FOLLOW, `[GIVE: 200 cats, 1 Katana]` for the handover of THREATEN, and `[DEAL: 1 Katana for 4600 cats]` for BARTER. `offers.read` turns the tag into the parts of the deal and adds the part that the category fixes, such as `JOIN_PARTY`, because the model left out longer tags that named each part. `offers.check` (`server/chat/offers.py`) checks the parts that the category allows, the cats and the items of each side, and the daily rate of a mercenary. The server drops and logs an offer that breaks a limit, and the action dialogue goes on. No prompt gives the cats of the player faction, because an NPC that saw them asked for all of them. It builds every plugin action from the checked offer, never from the tag.
- The server holds a valid offer in `state.PENDING_OFFER` and sends `CMD: OFFER:` after the last line of the reply (`play_lines`). The command holds, one to a line, the offer ID, the keys of the NPC and the speaker, the name of the NPC, the text of the popup ("X offers A for B.", with no "for B" when the player gives nothing, `offers.popup_text`), a `CHECK:` line for the cats and each item that a side gives, and a `CHECK: ROOM` line for each item that the NPC must carry (`offers.checks`). A trade adds `RESTOCK: stock` or `RESTOCK: inventory`, where Accept puts a copy of an item that the NPC lost. Only a trade restocks, because the player pays for each copy, and a handover of THREATEN or charity costs the player nothing.
- `/offer` takes the answer. `accept` sends the actions and the preset line of the category, and ends the chat thread. `decline` keeps the action dialogue, and the plugin sends the player's reply as the next line. `cancel`, after a save load, a knockout, or a death, and `failed`, when a side no longer holds its part, end the chat thread. An answer to an offer that the server no longer holds, for example after a restart, ends the chat thread too.
- While an offer waits, `/chat` takes no line and shows "Answer X's offer first.", `/radiant` starts no conversation, and the chat never counts as quiet, so the chat thread keeps its memory until the answer.
- Some ends run at once, with no offer: `[ATTACK]` in THREATEN sends `ATTACK` and the preset line `threaten_attack`, a HEAL offer with no fee sends the treatment and `heal_start`, and DISMISS sends `END_HIRE` and `dismiss_end` with no LLM call. `[REFUSE]` ends RECRUIT and FOLLOW.
- Each line and action of a chat reply starts with `Name|key>speaker key:`, so each action acts on the squad member that spoke the line. The plugin sends the key of the speaker as `speaker_key`, and `ATTACK`, the release, `HIRE`, `FIRST_AID`, and the item actions act on the squad member of the key after `>` (`TakeSpeaker` and `QueueTagAction` in `plugin/main.cpp`). `GIVE_CATS`, `TAKE_CATS`, and the fee of `JOIN_PARTY` keep the first character, because the cats belong to the whole player faction.
- The plugin opens the popup on `CMD: OFFER:` (`ShowOfferUI` in `plugin/ui/OfferWindow.cpp`). The game does not pause, so the NPC can lose an item of a trade before the player accepts. The plugin notes the record, the grade, the maker, and the level of each item of the NPC when an action dialogue line goes to the NPC, because the offer comes from that context, and at each refresh of the Barter window (`NoteNpcItems`). Accept first puts a copy of each item that the NPC no longer holds where `RESTOCK:` names (`RestockLost`, `Restock` in `plugin/game/GameActions.cpp`). The plugin makes a copy only where it has room, so no free copy lies on the ground. Accept then checks each `CHECK:` line against the cats and the items that each side holds now (`Shortfall`), because the game does not pause while the offer waits. A `ROOM` line stops the deal with "X can't carry all that." when no carried section of the NPC has room for the whole count of the item (`HasRoomFor` in `plugin/game/Context.cpp`). Decline asks for a reply, "No." when blank, which goes to `/offer` and then to the NPC as the next chat line (`SendChatLine` in `plugin/ui/ChatWindow.cpp`). When the plugin refuses that line, for example because the NPC is out of range, the decline still goes to `/offer`, so the server does not hold the offer. Back leaves the reply and shows the offer again.
- The reply of `/chat` holds `offer`, so the plugin holds each chat line from then on with "Answer X's offer first.". A held line asks the server with `show` to send the popup again, because the pipe drops a message that finds no pipe instance in time. The server sends the command again, or `CMD: OFFER_GONE` when it holds no offer, which ends the hold (`DropOfferUI` in `plugin/ui/OfferWindow.cpp`).
- Each frame while the popup is open, `WatchOffer` cancels the offer when the NPC or the speaker is knocked out, dies, or is gone, or when its key finds a new object, because a save load gives the same handles to new objects.
- `HIRE` starts the `Bodyguard` contract (`5090-gamedata.base`) with the hours of the offer (`Blackboard::_setContractJob`), and `END_HIRE` ends it (`endContractJob`). `HIRE` first ends a contract that runs, because a renewal finds the old contract still running. `FIRST_AID` gives the NPC the `FIRST_AID_ORDER` order on the speaker for the flesh wounds, and the `FIRST_AID_ROBOT` order for the damage of a robot body or a robotic limb, each only when the NPC carries the kit (`StartTreatment` in `plugin/game/GameActions.cpp`). A character with robotic limbs can need both orders, so the repair queues behind the first aid. `JOIN_PARTY` ends a hire contract before the recruit, so that the contract cannot run out later. After the recruit, `JOIN_PARTY` frees a recruit that the player faction holds in a cage or in shackles (`HeldByPlayer` in `plugin/game/Context.cpp`): `UnlockPrisoner` unlocks it as for a release, and `StateBroadcastData::setSlaveState` with `NOT_SLAVE` clears the slave state, as Lucius64's KenshiExtensionPlugin does, because slavers hunt an escaped slave. A fellow captive stays locked up, because it joins to escape with the player.
- The server keeps the hours and the fee of each hire of a FOLLOW deal or of `/follow [hours]` in the `hire` table (`campaign_db.set_hire`), because a save holds the contract but the plugin keeps nothing across a save load. Every 2 s, the plugin scans the characters that the game updates for a hire contract, and it asks `/hire_terms` once for each new contract (`WatchHires` in `plugin/ui/RenewWindow.cpp`). 0.1 game hours before a hire with terms expires, the plugin pauses the game and opens the renewal popup. A hire of the game's own dialogues has no terms, so it expires as in the game. Accept queues `TAKE_CATS` and `HIRE` with the same terms, and `HIRE` goes to the squad member nearest to the NPC, because the plugin does not read the giver of the old contract (`NearestMember`). Decline and the close button queue `END_HIRE` and send `/hire_end`, which deletes the terms, as DISMISS and `/follow [line ID]` do. `/follow end` on a hire with terms sends `EXPIRE_HIRE`, which opens the popup at once (`ExpireHire`).
- The plugin also runs `RAID_TOWN` and `TRAVEL_TO_TARGET_TOWN`, which give the NPC the task of that name toward the town that the tag names (`DoSetTask` in `plugin/game/GameActions.cpp`). No deal sends them, and only the test commands `/raid` and `/travel` reach them, but they stay for a later action. `DoSetTask` gives the task both as a job (`addJob`) and as a goal (`addGoal`), and no in-game test shows which call moves the NPC.
- `GIVE_ITEM`, `SELL_ITEM`, `TAKE_ITEM`, and `BUY_ITEM` move only the count of the deal and split a bigger stack (`MoveItems` in `plugin/game/GameActions.cpp`), and they take an item with the exact name before an item whose name holds it (`FindNamedItem`).
- An item that the player's character cannot fit, from a deal or a spawn, drops at its feet (`GiveOrDrop`). `GiveOrDrop` calls `giveItem` with `dropOnFail` only after a call without it fails, because what `giveItem` returns after a drop is unknown. An item that the NPC cannot fit goes back to the player, and the game shows "X can't carry all that.".
- A `TAKE_CATS`, `TAKE_ITEM`, or `BUY_ITEM` that moves less than the deal holds back the NPC's side: `GIVE_ITEM`, `SELL_ITEM`, `GIVE_CATS`, `HIRE`, `FIRST_AID`, and the release, until the NPC's next line (`HeldBack` in `plugin/game/GameActions.cpp`). The hold lasts across frames, because each action is its own pipe message. `JOIN_PARTY` carries the fee of a recruit, so a fee that the player cannot pay stops the recruit and takes no cats (`DoJoinParty`). The fee goes to no purse, because the recruit's purse becomes the player's.
- The name of each item in a context holds the maker and the grade of a weapon, or the grade of an armour (`ItemLabel` in `plugin/game/Context.cpp`), so a deal names the right one of two items with one name and different prices. A name without the grade finds the item when only one grade of it is held (`offers.held`).
- The context of an NPC in a shop holds `stock`, the items of all the furniture of the building (`GetShopItems`), because the trade window of a shop shows them as its stock. A trader in a shop trades only the stock and keeps what it carries (`offers.sells_stock`), so it never sells the clothes and gear that it wears. Any trader in a shop counts, not only one whose Current Job is `Running a shop`, because a barman's Current Job can read `Trading`. A trader away from a shop, and any other NPC, trades what it carries. A sale from the stock is `SELL_ITEM`, which takes the item only from the furniture (`FindStockItem` in `plugin/game/GameActions.cpp`), because `GIVE_ITEM` takes an item that the NPC carries first. `GIVE_ITEM` takes an item from the furniture when the NPC carries none. A purchase into the stock is `BUY_ITEM`, which puts the item into the first furniture of the building with room (`Stock`), so the trader sells it again and needs no `ROOM` line.
- A trade weighs the worth of each side (`offers.worth`): what the NPC receives against what it gives, each item at its full price. The worth only guides the model, and no check enforces it. Code does the sums, so the turn message gives no worth and no percent: the price of each item that the NPC buys drops by the profit that it wants (`offers.profit_share`), and the barter window names in cats how far the table misses or beats that profit. The NPC's stock sets the price of an item, at its highest, and an item that the stock lacks takes the highest price in the speaker's inventory (`offers.price_of`).
- The system prompt of a trade lists the goods of the NPC with no prices (`offers.stocktake`), and the turn message gives the count and the price of each item that the player's line or the NPC's last reply asks for, less the profit that the NPC wants for an item that it buys (`offers.price_guide`). So a neutral trader at the default target of 400% sells an item at its full price and pays at most 20% of it (100% ÷ 5). A line asks for an item by a word of its name, for example "water" for Water Jug, or by a kind word, for example "food" or "drink", which matches the kind that the plugin gives each item (`ItemKind` in `plugin/game/Context.cpp`). Words that fill everyday speech, such as "cats" or "right", match no name, and each side gives at most 10 items.
- A trade line that asks for no item, with the NPC's last reply, gets the prices of the items of the last turn (`offers.named_items`, `LAST_NAMED`), so "How many cats?" after "How much for the pie?" still gets the price of the pie. Without them, the model named a price of its own. Unlike a lore hit (see [Follow-up lines](#follow-up-lines)), the items carry until a line asks for an item, because a haggle can run several lines that name no item.
- Charity, a trade in which the NPC gives and receives nothing, is at most 50 cats or 1 Dried Gristle Flaps. The server cuts a bigger cat charity to 50 cats, and the turn message of a trade states the cap. After a charity, the thought of that NPC gives a plea for more charity the lean -2 for the rest of the game day (`state.CHARITY_DAYS`), and a trade keeps its lean. For food the model writes `GIVE_FOOD` and code picks the food, so the prompt names no food that the model could take for its stock. The plugin creates the cats (`ADD_CATS`) or the food (`SPAWN_ITEM`) for the speaker, so charity costs the NPC nothing. A gift, a trade in which the NPC gives nothing, raises its Relation by 1 for each 500 of its worth, at most by 10.
- The popup of a trade shows two boxes instead of the line of text: the `BOX:` lines of the command fill the boxes "You are offering:" and "They are offering:", the cats first, then the items by the biggest count and items of one count by name (`offers.box_order`). The `DEAL:` lines of an agreement in the Barter window go to that window (see [Barter window](#barter-window)).
- Each accept and decline, each attack, free treatment, and dismissal writes a deal line, for example `(Zaps declined: Bandit offered 200 cats.)`, into the chat thread of the NPC and the speaker as an exchange (`record_deal`), so the model sees it on the next turn, and a thread that ends in a deal is not deleted as a thread of one exchange.
- The bubble of an action reply starts with the category tag, for example `[THREATEN] Hell no!`. The stored line has no tag. The plugin strips every other tag from a bubble, so it keeps only a leading category tag (`LeadingCategoryTag` in `plugin/main.cpp`).
- At `!end`, the NPC says a random line of `server/data/defaults/action_end_lines.json`, which holds the preset lines of each end.
- The reply of `/chat` holds `action_dialogue`, which is true while the action dialogue stays open. While the reply to a line of an action dialogue is pending, a send closes the chat window, drops the line, and shows "{name} is still thinking." (`OnChatSendClick` in `plugin/ui/ChatWindow.cpp`). A marked line is such a line, and so is each line to the NPC of the open action dialogue. The speech bubble of the player and the stored line leave out the mark, so a line of only a mark, such as `!end`, shows no bubble.

### Categories

Each category has its own gates, hard limits, and lean. A line that fails a gate goes to plain chat with the reason as the NPC's thought (`plain_chat`), and only DISMISS has a block instead (`gate_block`).

| Mark | Category | The player |
|---|---|---|
| `t`, `threaten` | THREATEN | Threatens the NPC, demands its cats or items, or challenges it to a fight |
| `b`, `barter` | BARTER | Trades items with the NPC, gives it a gift, or begs it for charity |
| `h`, `heal` | HEAL | Asks the NPC to treat the speaker's wounds or repair its robotic parts |
| `l`, `liberate` | LIBERATE | Asks a guard to release the speaker from a cage for a bribe |
| `r`, `recruit` | RECRUIT | Asks the NPC to join the squad for good |
| `f`, `follow` | FOLLOW | Asks the NPC to follow the squad for a time |
| `d`, `dismiss` | DISMISS | Ends the hire of a temporary follower |

- A guard is an NPC whose Current Job is `Guarding the town`, `Guarding a building`, `Patrolling the town`, `Keeping the peace`, or `Working as a slaver`, or whose squad jobs hold the jailer task `FIND_CAGE_AND_PUT_DEADGUY_IN` (`action_dialogue.is_guard`). The jailer task counts because the captain of a bounty desk stands at a shopkeeper node, so its Current Job reads `Running a shop`. A trader is an NPC whose Current Job is `Trading`, `Running a shop`, or `Travelling as a trader` (`is_trader`).
- THREATEN: A threat from an `imprisoned` speaker goes to plain chat, but a chained slave can threaten. The NPC gives in with `[GIVE: ...]`, only from the cats and the items that it carries, fights with `[ATTACK]`, or refuses, and the action dialogue goes on. The lean counts no relation (`threat_lean`): -2 to +2 by how much stronger or weaker the speaker looks than the NPC in the chat prompt (`fight_bonus`, `scene_text.strength_step`), +1 or -1 when the player faction near the NPC outnumbers the NPC's faction near it or has fewer members there, +1 when the NPC is `Injured` or `Crippled`, -1 when the speaker is, and -1 when the NPC leads its faction or is unique. The `nearby` list of the NPC leaves out the first squad character, so `sides` adds it when it speaks or stands near the speaker.
- `ATTACK` marks each member of the NPC's squad and of the speaker's squad as a temporary enemy of the other squad, because the game marks only the hitter of a character as its enemy (`StartFight` in `plugin/game/GameActions.cpp`). A pack animal stays out, because it does not fight, so the fight would go on until it died. The fight ends when each member of one squad is knocked out or dead, or after 30 s of unpaused game time in which neither squad attacks the other. `WatchFights` then clears the marks and the AI goals of the NPC's squad, because the NPC attacked the speaker again when the speaker got up. `DoAttack` also calls `attackTarget` and adds the `MELEE_ATTACK` goal, and the attack works in the game with both calls.
- BARTER: A trade is between the speaker and the NPC: the cats of the whole player faction and the items of the speaker, except in the [Barter window](#barter-window). An `imprisoned` speaker can trade, and the turn message says so. Each NPC sells at the full price of an item, as the game's trade window does, and takes its profit only when it buys. The profit that the NPC wants is the profit target on the Settings page (`BarterProfitTargetPercent`, 400% by default), plus steps of the relationship offset on the Settings page (`BarterRelationOffsetPercent`, 50 points by default) by the relation bonus (`offers.PROFIT_STEPS`): 2 steps at -2, 1 at -1, 0 at 0, -2 at +1, and -3 at +2, plus 1 step for an NPC that is not a trader (`offers.NON_TRADER_STEPS`). The sum stops at 0%, so the turn message never tells the NPC to take a loss. So by default a trader wants a profit of at least 500% at -2, 450% at -1, 400% at 0, 300% at +1, and 250% at +2.
- HEAL: The speaker needs a wound, a body part whose flesh plus its bandage is below full health (`TreatmentNeeds` in `plugin/game/Context.cpp`), because the game counts the bandage as healed when it picks a patient for first aid. The NPC needs a kit that fits a wound, a first aid item for flesh or a repair kit for a robot body or a robotic limb, and it must not be `imprisoned`. Any NPC can treat a wound, with no medical skill. Treatment has no price, so only the cats of the player bound the fee. The lean adds +1 when the speaker is `Injured` and +2 when it is `Crippled`, because a worse wound raises the demand for treatment.
- LIBERATE: The speaker must be `imprisoned` and not a slave, and the NPC must be a guard that is not `imprisoned`. The bribe is at least 500 cats plus the bounty of the speaker (`offers.release_fee`, `getTotalBounty` in `plugin/game/Context.cpp`), and the turn message names it. The lean adds +1 when the speaker is `Crippled`, because a crippled prisoner cannot escape, so the guard takes the bribe at no risk.
- The release gives the NPC the `RELEASE_PRISONER` order (`DoRelease` in `plugin/game/GameActions.cpp`). When the speaker is still locked up after 30 s of unpaused game time, `WatchReleases` unlocks it, because the package of a jailer can keep it at its desk. `UnlockPrisoner` unlocks the door of the cage and the shackles, and it sends the speaker the game event `EV_UNLOCK_MY_CAGE_OR_SHACKLES`, as Lucius64's KenshiExtensionPlugin does, so the game lets the speaker out and the plugin writes no prison state. LIBERATE has no breakout, because `BREAKOUT_PRISONER` moved no NPC toward the cage ([kenshi_internals.md](kenshi_internals.md#orders-and-contracts)). The guard says its accept line while the speaker is still in the cage, so the lines of `liberate_accept` promise the release and do not send the speaker away.
- RECRUIT: Neither the speaker nor the NPC may be `imprisoned` or `enslaved`, and the NPC must not lead its faction, because the faction would lose its leader in the world. Fellow captives pass the first gate: both are held, each in a cage or in shackles, by any faction (`action_dialogue.fellow_captives`), so that they can escape together. An escaped slave is not held. A fellow captive accepts with a line of `recruit_captive_accept`, which keeps the escape quiet. A captive of the speaker's faction passes the NPC side of the first gate: the NPC's `captor` is the speaker's `factionID` (`action_dialogue.captive_of`), because a captive cannot leave its captor, but the captor can take it into the squad.
- `JOIN_PARTY` calls `PlayerInterface::recruit` with no check of the faction limit or the squad limit, because SSR assumes that the game refuses a recruit at the limit. No game test has shown it ([kenshi_internals.md](kenshi_internals.md#recruitment)). The join also skips the vanilla condition `DC_IS_RECRUITABLE`, as many vanilla join dialogues do.
- The NPC of RECRUIT or FOLLOW agrees with `[AGREE]`, bargains, or refuses with `[REFUSE]`. Only these two categories have a refusal tag, because only they end on a refusal, and without the tag code cannot tell a refusal from a reply that still bargains. The refusal shows "X has refused your invitation to join Y." for RECRUIT, where Y is the faction of the speaker, and "X refused to follow you." for FOLLOW.
- The lean of RECRUIT adds +1 for an `escaped-slave` NPC, +2 for a fellow captive, -6 for a fellow captive whose line is not a whisper, -1 for a unique NPC, -2 for a guard, and -2 for a trader. The -6 outweighs the best relation and the captive bonus together, so a plan that the captors can hear always leans to a refusal.
- The lean of a captive of the speaker's faction adds +1 for the freedom that the join gives, because this reason is the only place where the NPC learns that the speaker is its captor. It also adds a bonus for the fight and one for the days held (`fight_bonus`, `captivity_pair`), because a captive that fights worse than its captor obeys more readily, and a new captive defies its captors until a long captivity wears its will down. The relation still counts.
- The fight bonus of the captive and of THREATEN is the step of the strength line in the chat prompt (`scene_text.strength_step`), so a reason never contradicts how strong the speaker looks. The gap is the fight skill of the speaker minus the NPC's, and the fight skill is the higher of the melee attack and the melee defence. Both take the same reasons (`FIGHT_REASONS`).

| Bonus | Fight skill gap | Whole game days held |
|---|---|---|
| -2 | -31 or less | 0 to 2 |
| -1 | -30 to -11 | 3 to 4 |
| 0 | -10 to 9 | 5 to 8 |
| +1 | 10 to 29 | 9 to 13 |
| +2 | 30 or more | 14 or more |

- The lean of RECRUIT adds the ways of specific people (`people_pairs`), except between fellow captives, because two captives that plan an escape do not weigh these things. Each rule covers a whole race, faction, or kind of NPC, and follows the vanilla dialogue: "Because the Shek idolize the strong...", the Shek call each other kin, and the Holy Nation scorns women, Shek, and skeletons ("Okran hates liars. And skeletons. And loose women."). The race and faction records of SSR Vanilla give the rest: "those still bound to a Queen live for the Hive", and the Anti-Slavers fight slavery.

| People | Check | Bonus |
|---|---|---|
| A Shek NPC | The fight bonus counts again, so a captive Shek counts it twice | -2 to +2 |
| A Shek NPC | The speaker is a Shek | +1 |
| An NPC that is not a skeleton | The speaker carries food, and the NPC is starving | +2 |
| An NPC that is not a skeleton | The speaker carries food, and the NPC is hungry or very hungry (`scene_text.hunger_state`) | +1 |
| A member of the Holy Nation | The speaker is not of the NPC's race | -2 |
| A member of the Holy Nation | The speaker is a woman | -1 |
| A mercenary (`MERCENARY_RATES`) | The cats of the speaker's faction: 20,000 or more, 10,000 or more, or less than 1,000 | +2, +1, or -1 |
| A Hiver of the Western, Midland, Northern, or Southern Hive (`QUEEN_HIVES`) | Always: a Hiver bound to a Queen does not leave the Hive. The Savage Hive and the Mechanical Hive have no Queen. | -2 |
| An `escaped-slave` NPC | The speaker is an `escaped-slave` too | +1 |
| A member of the Anti-Slavers | The speaker's faction holds the NPC captive | -2 |

- The `captive` table keeps the game time at which each captivity started (`world_events.days_held`). An `imprisonment` game event with attackers of the player's squad starts it (`campaign_db.start_captive`). A load imprisons each prisoner again with no attackers, so it keeps the start. A captive with no capture in the game events, such as a slave in shackles, which no hook sees, starts at the first RECRUIT line to it. A start after the game time of a line, from a load of an earlier save, restarts at that line (`campaign_db.captive_since`).
- FOLLOW: FOLLOW takes the gates, the hard limits, and the lean of RECRUIT except the ways of specific people, and an NPC that is not a mercenary takes -1 more, because it is wary to follow for no reason. A FOLLOW line to a fellow captive runs as RECRUIT (`runs_as`), because a hired follower stays out of the player's control, so the player could not lead it out. A FOLLOW line to a captive of the speaker's faction also runs as RECRUIT, because the player does not hire a captive that the player holds.
- A mercenary of FOLLOW gets `prompt_action_follow_mercenary.txt`, and any other NPC gets `prompt_action_follow.txt`, because one request that called each follow the work of a hired guard made other NPCs refuse "hired guard work" and write a fee of 0 cats. A mercenary charges at least the daily rate of its faction times the hours of the hire divided by 24 (`MERCENARY_RATES`): 2,000 cats for the Mercenary Guild, the Tech Hunters, and the Vagrants, and 2,500 cats for Black Dog. The rates come from the `Bodyguard` contracts of the hire dialogues `mercenary shop`, `bodyguard for hire`, `Thug2`, and `Black dog random extortion`. The Cannibal Hunters sell only an outpost guard contract, in which the hired squad does not follow, so they are not mercenaries.
- DISMISS: A block stops DISMISS of an NPC that is not a temporary follower. The NPC never refuses, so DISMISS has no lean and no offer, and the player gets no part of the fee back.

### Barter window

The Barter window lets the player build the deal of a BARTER action dialogue from the real items and cats of both sides, so only the player sets a deal that the window can accept (`plugin/ui/BarterWindow.cpp`). The chat window shows a Barter button while the open chat thread of its NPC is a BARTER action dialogue (`type` of `/chat_thread`, see [Chat history](#chat-history)). The window works next to the `!b` lines of the chat window, which do not change.

- `/chat_thread` gives the window the thread lines, the mode, the speaker (`npc_id`), and `stock` of the action dialogue. Each line of the window goes as that speaker in that mode, because another speaker or another mode starts a new chat thread (see [Chat threads](#chat-threads)).
- The left side shows the cats of the player faction and the items of one squad member. The squad members are the speaker, then each squad member within `TalkRadius` of the NPC when the window opens, because only a squad member near the NPC can hand it an item. A button goes to the next squad member, because a drop-down list opens under the window ([kenshi_gotchas.md](kenshi_gotchas.md#mygui)). The right side shows the cats of the NPC and its goods, as `offers.goods` reads them: the items of the furniture of its shop when `stock` is true, else the items that it carries.
- Each side has a list of its holdings, a list of what it offers, and a box for its cats. A double-click moves one item between the two lists, and Shift with a double-click moves the whole stack. The box of the player's cats takes at most the cats of the player faction. The box of the NPC has no cap, because charity creates its cats.
- A line under the boxes shows the estimated profit or loss of the deal for the NPC at the full price of each item, so the player sees how much the NPC fleeces them. The model sees how far the deal misses or beats the profit that the NPC wants (see [Action dialogue](#action-dialogue)). The server also counts each item at its full price, so a loss on the line is a loss to the NPC, and the NPC cannot agree to the deal, except to charity. A profit does not mean that the NPC agrees. The plugin takes the highest price of each item in the goods of the NPC, else in the items of the squad members, as `offers.price_of` does.
- A deal of the window can hold the items of several squad members, and each item leaves its own holder. A deal of a `!b` line in the chat window holds only the items of the speaker.
- Send posts `!b` and the line, or "How about this deal?" for a blank line, to `/chat` with `barter`: the deal (`take_cats`, `give_cats`, `take` with the key of the holder of each item, and `give`), and the key, the name, and the inventory of each squad member, the speaker first. The mark keeps the line in BARTER after the action dialogue ended.
- The game does not pause, so a side can lose an item that lies on the table. Each refresh of the lists and each Send take a lost item of a squad member off the table, and show "{name} no longer has {what}." in the status line and as a game message (`TrimDeal`). A Send that trims does not go, because the player wrote the line for the table before the trim. A squad member does not get a lost item back, because the player could then sell an item, drop it, and keep the cats.
- A lost item of the NPC stays on the table. The window keeps the price of each item of the NPC that it saw, and each Send holds the lost items in `lost` of the deal. The server counts them as goods of the NPC (`offers.with_lost`), so the NPC trades them as usual. Accept restocks them as it restocks the items of each trade (see [Action dialogue](#action-dialogue)), so the trade of the window and the trade of a `!b` line end alike. Without room for a copy, the checks refuse the sale with "{name} no longer has {what}.". Rejected: a copy at once when the item is lost, because the player could then take the item from the furniture again and again for free copies.
- The system prompt takes the request `prompt_action_barter_table.txt` instead of `prompt_action_barter.txt`, so it names `[AGREE]` and no `[DEAL]` tag, and the turn message adds the deal on the table (`offers.on_table`). The profit or the loss of that deal moves the lean (`offers.profit_lean`): +2 at the profit that the NPC wants, +3 at a profit of 25% or more of what it gives, +4 at 50% or more or for a gift, -1 at a smaller profit, and -2 at a loss. The reason names the kind of the deal first, a big, good, fair, or suboptimal profit, or a loss, and then about how many cats it misses or beats the desired profit by, with each side at the prices of the price guide, because a gap from the break-even worth contradicted the price lines. So in a swap, the NPC takes its profit only from the items of the player. The model refused deals at a profit when the lean counted only the relation, and it agreed to a profit below the one that it wants when that profit moved the lean by nothing. The price guide covers the items on the table and the items of all the squad members.
- The NPC takes the deal on the table with `[AGREE]`. The server checks it as an offer (`offers.check`), and an `[AGREE]` that breaks a hard limit gets the message of an offer that the NPC can't keep. The turn message of such a table names the broken limit (`offers.TABLE_REASONS`), because without it the NPC invented a reason, such as a sale of an item that it no longer had. An `[END]` in the same reply does not close the trade, because the NPC leaves only on the deal, and an accepted deal ends the thread anyway.
- The NPC asks for another deal only in words, and the server ignores a `[DEAL]` tag of a line of the window. Rejected: a `[DEAL]` tag as a counter-offer that loads into the lists, because the deal of the model took the place of the player's table, and the player accepted a deal that took another item.
- The `DEAL:` lines of `CMD: OFFER:` hold the cats of each side and each item with its holder, also for charity, which has no `CHECK:` lines (`offers.deal_lines`). Only an agreement in the window has them (`offers.command`), and the open window loads them into its lists instead of the popup.
- An item of a squad member names the key of its holder in its `CHECK:` line (`CHECK: ITEM <key> <count> <name>`, `Shortfall` in `plugin/ui/OfferWindow.cpp`) and in the voice of its action (`Name|npcKey>holderKey:`, `offers.voiced`).
- After the lines of each reply to a line of the window, the server sends `CMD: BARTER_TURN:` with `1` while the action dialogue stays open or `0` after it ended, then the lines of the chat thread (`chat_window.thread_lines`). The plugin queues `error` instead when `/chat` fails. The window then takes the next line.
- Accept is on only while the window holds the offer and its deal is the deal that the NPC agreed to, because the NPC agreed only to the deal that it saw. Accept runs the checks and the answer of the popup (`AcceptOffer` in `plugin/ui/OfferWindow.cpp`). A send of the window and Close decline a held offer, so the deal line of the decline reaches the NPC.
- An offer that waits in the popup when the window opens stays in the popup, because the model wrote it. A send of the window declines it (`OfferHeldFor`).
- The hotkey of the chat window does nothing while the window is open.

## Characterised dialogue

When Characterised player dialogue is on (`characterised_dialogue` on the Settings page, off by default), one LLM call rewrites each chat line of the player in the words of the speaker before the NPC hears it (`server/chat/player_voice.py`). The prompt gives the line as the gist of what the speaker says, not the words, so the rewrite says the same thing in the phrasing that fits the personality and the manner of speech of the speaker. A prompt that asked to keep the line and change only the words gave the line of the player back with a few words changed.

- `chat` in `server/chat/routes.py` runs the rewrite after the check of a failure and before the check of `!end`.
- A line that the game refuses keeps the raw line: a line while an offer waits, a blocked line, and a failure, also of the classify call. The game tells the player that the line failed, so the bubble shows what the player typed, and the classify call read the same words.
- A line that the world hears gets the rewrite, also when no chat call follows: `!end` with text after the mark, DISMISS of a hired follower, and a yell that no one can answer. So with the setting on, DISMISS makes one call.
- A line with no words outside `*actions*`, a line of an animal speaker, and the line "How about this deal?" that a blank Send of the [Barter window](#barter-window) sends, in the language of the Settings page (`player_voice.BLANK_DEAL`), get no call. The player did not write that line, so it has no gist to reword.
- The `rephrase` task has a deadline of 15 s, because the chat call of the same request waits for it (see [LLM routing](#llm-routing)).
- `prompt_player_voice.txt` holds the race and the persona of the speaker (`describe_persona`), who hears the line and how, and the line. It holds no scene, no lore, and no line of the chat thread, because a model with more context adds facts that the player did not say. With the last line of the chat thread, the rewrite of "Five hundred" after an NPC line that named two other prices became an offer of six hundred.
- The prompt takes its wording from the chat reply rules (`response_rules.txt`): the personality shows in how the speaker says the gist and never in what they say, and the output holds only the spoken words, with no preamble and no meta-talk. A prompt that asked for the sentence shape and the length that fit the personality padded short lines, such as "Hey" as "The thing is, Omulo.", turned "What might he mean?" into a line about meat from a speaker who thinks about food, and once gave the reasoning of the model as the line.
- The prompt calls the gist shorthand: the model fills in the words that the gist leaves out and keeps each offer and question of the gist. The personality and the manner of speech of the speaker set the length of the line, so a talkative speaker can say a short gist at length. A prompt that told the model to match the length of the gist kept its word count, so a rough speaker clipped the line, such as "Looking to trade" as "Trade lookin'", and dropped a question, such as "fine how about fifty." as "Fifty, fine.", which turned a counteroffer into a yes.
- The prompt tells the model to keep each number as the gist writes it, in digits or in words, and to add no other number, because the check of the digits does not see numbers in words.
- The prompt names the parts in asterisks only when the line has one (`actions`), because Gemma 4 put asterisks around the reworded words of a line without actions when the prompt named them.
- The rewrite is cleaned as a chat reply (`reply_text.spoken`). A call with no reply, and a rewrite that leaves out a number of the raw line, give the raw line, because a lost price breaks a trade. The check compares the digits without thousands separators, so "two hundred" for "200" also gives the raw line.
- The NPC hears the rewrite, and the chat thread, the overheard copies, the later lines of a yell, and the memory hold it. The code that matches words reads the raw line: the names of a yell (`radiant.named`), the lore search, the directions, and the price guide. The rewrite adds words of the speaker's manner, such as "by the Holy Flame", that would find lore that the player did not ask for, and it can change an item word, such as "water" to "drink".
- The bubble of the speaker shows the rewrite, so the raw words of a line that the NPC hears never show (see [Chat lines](#chat-lines)). A line that stops before the rewrite shows the raw line, without its mark, from `reply` in `chat` (`player_voice.bubble`). Without it, the "..." over the speaker would stay for a minute.

## Line pacing

The server paces the lines of every conversation (`say` and `think` in `server/chat/routes.py`). The reply of `/chat` and `/radiant` holds no text. A server thread sends the actions as `NPC_ACTION`, then each line as `NPC_SAY: Name|key: line`, or a line of the player as `PLAYER_SAY: Name: line`. A conversation shows a line and the "..." of the next speaker:

1. A line shows for `DialogueSpeed` (5 s by default). The plugin reads `DialogueSpeed` from the INI at start, the server sends it on each change, and the plugin gives each line that bubble life (`g_speechBubbleLife`).
2. As soon as the line shows, the next speaker shows "..." (`NPC_THINK: Name|key: ...`), so the player sees who speaks next.
3. The line of the next speaker replaces its "..." when the line before it has gone and the LLM call for it has returned, but at least 0.2 s after the "..." (`THINK_MIN`).

- Only the bubbles wait, so each LLM call starts as soon as it can. A radiant conversation and the later replies of a yell write each line as soon as the call before it returns (`write_ahead`).
- The "..." of the NPC that answers also shows while the line of the player is up.
- A "..." stays until the line of its speaker, because a call can take longer than `DialogueSpeed` (`THINKING_LIFE` in `plugin/game/GameActions.cpp`). When the line does not come, the server sends an empty line (`hush`), and the plugin ends the bubble.
- The key is a number that the plugin gives a character for the game session (`HandleKey` in `plugin/game/Context.cpp`). Each character of a request carries its key, and the server sends it back unchanged. The plugin finds the character of a line by its key, and by its name only when the key finds no character.
- The key stands for the full handle, because characters of other squads can have the same `serial` ([kenshi_internals.md](kenshi_internals.md#character-identity)). A squad change gives the character a new handle, and `RekeyCharacter` gives the key that handle (see [Characters](#characters)).
- One conversation plays at a time, and chat replies queue (`reply_loop`). A radiant conversation holds the stage (`_STAGE`) to its last line, and so does a yell (see [Yells](#yells)).
- The actions go first, so an AI state change cannot clear a bubble that is already up.
- A line that finds no character, or a character with no dialogue object, logs an error and shows no bubble (`ProcessMessage` in `plugin/main.cpp`, `DoSay` in `plugin/game/GameActions.cpp`).
- The plugin shows at most two bubbles: the newest line or `...`, and the line before it. A bubble on a third character ends the oldest bubble (`KeepTwoBubbles` in `plugin/game/GameActions.cpp`), so the participants of a radiant conversation do not all talk at once.

### Chat lines

The line of the player waits its turn on the queue of replies as a line of an NPC does (`play_lines` with `player`). The bubbles of a chat line come in this order:

1. When the player sends the line, the plugin names the speaker with a `PLAYER_SAY` that holds no words (`SendChatLine` in `plugin/ui/ChatWindow.cpp`), and no bubble shows.
2. With [Characterised dialogue](#characterised-dialogue), the server queues the "..." of the speaker, which shows while the rewrite runs.
3. The server queues the line as `PLAYER_SAY` (`player_says` in `chat`): at once, or with Characterised dialogue after the rewrite. A line that starts with `/` and a line of only a mark show no bubble.
4. Just before the chat call, the server queues the "..." of the NPC that answers and, except for a yell, the "{name} is thinking..." status, so they show right after the line of the speaker.
5. The reply replaces the "...". A chat call that gives no reply ends the "...".

- `!end`, DISMISS, and a yell that no one can answer stop before the chat call, so no "..." shows over an NPC that does not answer.
- A squad member that talks to itself shows no "..." before its reply, because the "..." would replace its own line at once.
- The message at Send names the speaker, also for a line that shows no bubble, so `TakePlayerSpeaker` sets the squad member that the actions of the reply fall back to (`plugin/main.cpp`).
- A line of the player waits for the end of a radiant conversation that holds the stage, as a reply does.

## LLM routing

Each LLM call names a task: `chat`, `radiant`, `profile`, `synthesis`, `memory`, `action`, or `rephrase`. `server/config/llm_config.json` holds the providers, the profiles, the default profile, and the routes, and the Models page edits them through `/api/llm`.

| Part | Contents |
|---|---|
| Provider | An OpenAI-compatible endpoint: type (`openai` or `player2`), base URL, API key, Player2 game key |
| Profile | One model on one provider, with a per-attempt timeout and extra request parameters |
| Route | Per task: an ordered list of profiles with `null` once for the default profile, `max_tokens`, `temperature`, and a deadline |

- `llm_router.run_route` tries each profile once, in order, and moves on after an exception, a non-200 status, or an empty completion. The default deadline is 55 s, because the plugin stops waiting after 60 s.
- The calls of one chat request end by 55 s after the request starts (`until` of `run_route`, passed by `chat` in `server/chat/routes.py`), because a request can make three calls, the classify call, the rewrite of [Characterised dialogue](#characterised-dialogue), and the chat or action call, and each route has its own deadline.
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

- `open_campaign` builds a missing `campaign.db` from SSR Vanilla through `campaign.db.tmp`.
- `open_campaign` migrates schema 22, of releases 1 and 2, to 23, which adds the `captive` table (`_migrate_from_22`). It first copies the database to `campaign_ssr2_backup.db` in the campaign folder with the SQLite backup API, so a player who goes back to SSR 2 keeps the campaign. Then one transaction changes the schema. A failed copy or migration leaves schema 22 and closes the campaign with the error.
- Each database holds the mod version that created or last migrated it in the `ssr_version` meta row. `open_campaign` refuses any other schema version, and the reason names the SSR version of that row, because only that version is sure to open the campaign. A database with no `ssr_version` row predates the releases, so the reason says to start a new campaign.
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
| Every other character | `h:` and its whole handle: `index-serial-container-containerSerial` |

- A `u:` ID is the same in every save and campaign, so a canon character binds to it.
- Characters of other squads can have the same `serial`, and two squads of one origin can hold members with the same `serial` and template, so an `h:` ID holds the whole handle. A save, a load, and a town reload keep the whole handle ([kenshi_internals.md](kenshi_internals.md#character-identity)).
- A squad change gives the character a new handle. After `ActivePlatoon::addActiveObject` (a recruit or a leave) and `ActivePlatoon::addCharacterAt` (a move between the player's squads), `RekeyCharacter` in `plugin/game/Context.cpp` moves the origin caches and the chat key to the new handle, and queues a `rekey` game event. `world_events.take` reads it in order with the other game events, and `campaign_db.rekey` gives every row and every `{npc_id}` mark of a memory the new `npc_id`. It changes nothing when the new `npc_id` already has records.
- The `rekey` table keeps each re-key with its game time. A cull undoes the re-keys after its game time, newest first, so the records go back to the handles of the loaded save.
- A character that the game stores keeps the game time of its first save (`game_time`), so a cull deletes the characters met after its game time. A record of the template or of the web app has no game time, and the cull keeps it.
- The server stores an `npc_id` as the plugin sends it, and builds one only for a canon character (`u:<game_id>`). A generic NPC whose `template_id` is a canon character takes that `npc_id` (`adopt_canon`).
- The name is only the `Name` key of the profile, so two NPCs with one name keep two rows. In one request, the server keys NPCs by `npc_id`, and each dialogue row stores its speaker's `npc_id` in `speaker`.
- A `Race`, `Sex`, or `Faction` of `Unknown` takes the value that the plugin reports (`get_character_data`).
- The game reports every skeleton as male, so a skeleton gets the sex Other (`reported_sex`).
- `LIVE_CONTEXTS` keeps a few fields of the latest context of each character that takes part in a chat or a radiant conversation (`merge_live_context`).

### Chat threads

Each chat exchange belongs to a chat thread, which records who took part.

- `thread` holds the ID (`AUTOINCREMENT`, so an ID is never reused), the game time of the newest exchange, the start place, the memory, the count of auto rumor passes that did not cite the memory (see [Auto rumors](#auto-rumors)), the count of chat exchanges, the game time of the newest use of the memory (`used_at`, see [Pruned profiles](#pruned-profiles)), and the kinds of the thread (`kind`). A radiant conversation counts no exchange. `dialogue.thread_id` links each row. Each radiant conversation is a thread (see [Radiant conversations](#radiant-conversations)).
- `kind` is a JSON list of what the thread held, each kind once, in the order of its first exchange: the mode (`talk`, `whisper`, `yell`, or `radiant`), then each action category in lowercase, for example `["talk", "barter", "threaten"]`. A thread holds several kinds, because a new category mark keeps the chat thread, so the memory keeps the cause of each deal.
- `thread_member` holds the `npc_id`, the role (`speaker` or `overheard`), the join time, and whether the member was in the player's faction then. A member keeps the join time and the faction of its first join, so the history text stays stable for the cache. An overhearer that speaks becomes a speaker, so the NPC later knows that it spoke with it (`campaign_db.thread_partners`).
- `CURRENT_THREAD` ends at a chat with a character that is not a speaker of the thread, a switch between Whisper, Talk, and Yell, a campaign switch, a cull, a restart, or a real-time pause of the Conversation timeout (`conversation_timeout_minutes`, default 3). A chat as another squad member stays in the thread, so one memory covers all the exchanges of the squad with the NPC. A chat with another speaker of the thread also stays in it, so two squad members that answer each other keep one thread (`chat_window.stays_in`). An overhearer is not a speaker, so a chat with it starts a new thread. An action dialogue is the exception: it belongs to its speaker, and each of its ends also ends the thread (see [Action dialogue](#action-dialogue)). A plain yell is another exception: all plain yells share one thread, whichever NPC the player yells at (see [Yells](#yells)). A squad member that talks to itself also gets its own thread (see [Talking to itself](#talking-to-itself)).
- A cull or a character delete deletes each thread with no memory and no dialogue row. A cull recounts the exchanges of each thread that it cuts, from the copy of the NPC, which holds 2 lines for each exchange.

The chat prompt uses the threads (`npc_id`, not names):

- **First meeting:** the NPC and the speaker were both speakers of an earlier thread (`campaign_db.thread_partners`), or the NPC's history holds a line of the speaker without `(Overheard)` in an earlier thread (`chat_prompt.spoken_with`).
- **Companions:** the scene names the others that the NPC spoke with and that are in the player's faction now.
- **Partners:** the scene names the companions that spoke in the current chat thread as a part of this conversation, not as earlier talk. Without this, a squad member who took over the talk got a scene that put the lines of the last speaker in the past.
- **Relation:** one `Relation` for the whole squad, so the sentence names the player's faction.
- **Overheard notes:** after the last line of each thread, one user line names the overhearers from the player's faction and every other speaker of the thread (`chat_prompt.overheard_notes`).

### Chat history

Above the input, the chat window shows a header line with the type and the title of the open chat thread, and the lines of the thread below the header (`BuildChatWindow` in `plugin/ui/ChatWindow.cpp`).

- `POST /chat_thread` (`server/chat/chat_window.py`) returns the thread while the target is a speaker of `CURRENT_THREAD` and its last reply is within the Conversation timeout. So the panel shows the thread that a line to the target stays in, and an NPC that only overheard the thread gets a clear panel. It does not compare the mode or the speaker, because a change of either ends the thread only at the next line, and each line closes the chat window.
- The reply holds the type (`Chat` or the action category), the title (the speakers and the start place, as on Dialogue & Memories), the mode, and the copy of the thread lines of the NPC. The reply of an action dialogue also holds its speaker and `stock`, for the Barter window (see [Barter window](#barter-window)).
- The window asks at each open and at each switch of the target, by a selection or by the target button, and drops a reply that a newer request made stale (`ShowChatTarget`). So a switch to another NPC clears the panel, and a switch back to the NPC of the open thread shows the thread again. A thread that ends while the window is open shows until the next request.
- The panel adds its height above the input, so the input rows keep their size and the window grows upward.

### Conversation memories

The server distils each chat thread into a short memory, which replaces the lines of the thread (`server/chat/memory.py`).

- After the Conversation timeout with no chat (`quiet_seconds`), `memory_loop` writes a memory for each pending thread (a line and no memory), one call at a time, oldest first, then the rumors of the events follow (see [Rumors](#rumors)), then the prune of the profiles (see [Pruned profiles](#pruned-profiles)). It also runs after each radiant conversation. A failed thread stays pending.
- A chat thread of one exchange gets no memory. `memory_loop` deletes it with its members and lines (`campaign_db.delete_pending_thread`), so the NPCs forget it, and the next chat of the same speakers is a first meeting.
- Before each call, the server checks that the chat is still quiet, because a local model serves one request at a time. It ends the current thread under `THREAD_LOCK`, so each memory covers a whole thread.
- The call uses the `memory` task (see [LLM routing](#llm-routing)) and `prompt_thread_memory.txt`, or `prompt_action_memory.txt` for a thread that holds a deal line (`offers.DEAL_LINE`), so that the memory keeps each deal. The memory names each speaker and never says "you" outside a quote, so every member reads the same text.
- The rules of both memory prompts come before the lines of the thread, so the calls of one distillation share a cacheable start.
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
- A rolled name comes from `server/data/defaults/names.json`, differs from each `Name` of the campaign (`get_used_names`), and is set only when the profile is first stored.
- The pool of a rolled name follows the race, then the faction, then the general pool (`name_pool`), with the pool of each sex, or of both sexes for a skeleton. The pools copy the cultures of the name lists of UWE: biblical names for the Holy Nation, Japanese names for the United Cities, Slavic and steppe names for the Shek, short sounds and object words for hivers, and odd Kenshi names for the rest. The race comes first and a skeleton always takes the general pool, because UWE gives a Shek, a hiver, or a skeleton of the United Cities the names of its race. An animal, such as a Bonedog, takes the animal pool, one pool for every species, because the game flags the animal races of every mod (see [Kenshi internals](kenshi_internals.md#deaths-and-captures)).

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
- An NPC whose Current Job is Holding court leads its faction, as the leader that the game data names does (`current_job.is_leader`), because the game data names only one leader for each faction. The phrase decides, not the `SIT_ON_THRONE` squad job, because the squad of a barman can hold that job.

### Current Location

The `CurrentLocation` of a profile tells where the NPC was at its last chat (`location_name` in `server/chat/scene_text.py`), such as `Bar, The Hub` or `Wilderness, Vain`.

- The zone is the zone around the camera (`ZoneName`), from slot `0x10` of `WeatherSystem::ActiveRegion` (see [Kenshi internals](kenshi_internals.md#zones)), because the game gives no zone for each character.
- The chat scene reads the building from the live context, not from the profile.

### Provisional profiles

A character without a profile gets one rolled in code at its first meeting (`new_profile` in `server/chat/provisional_profile.py`), with no LLM call. A canon character keeps its canon profile.

- A person rolls three traits, a backstory, a speech manner, and a speech quirk from `server/data/defaults/` (`personality_traits.json`, `backstories.json`, `speech_manners.json`, `speech_quirks.json`). Entries have `kinds`, so a skeleton gets only what fits. An animal (`Animal` is 1, from `Character::isAnimal`) rolls only `animal_personalities.json`.
- A backstory is in the past tense and says nothing about the present, because the roll does not know the job.
- `SpeechQuirks` holds the manner, then the quirk. The `SPEECH` label of `npc_persona_template.txt` tells them apart: the manner shows lightly in every line and changes how a line sounds, not the point that it makes, and the habit, which can be a topic such as money, comes out only once in a while. The label hint sits on the field of each character, because a single hint in the radiant rules let a habit come out in every line. The label says that a manner keeps the point of a line, because a manner such as half sentences made every line of a character an empty fragment. The `PERSONALITY` label says that the personality shows in attitude and choices, in words of the character's own, because the model put words of the description in the lines, such as "Realist says" from a character who calls herself a realist.
- The roll is seeded by the `npc_id`, because a chat and a radiant conversation can both write a new profile.

A profile is provisional while it holds `Interactions` (`campaign_db.PROVISIONAL`), the count of the chat turns in which the NPC replied. At Chats before a bio (`bio_interactions`, default 5, 0 for on request only), `generate_bio` writes the full bio in a background thread. It never rewrites a full profile. An animal is provisional too, but its bio writes only the `Personality`, so it keeps no backstory and no speech.

- Generate Bio uses `write_bio`, which stores nothing. The Dialogue Library uses `/write_bio`, `/read_bio`, and `/keep_bio`. `/keep_bio` writes only changed parts and refuses the text when the campaign changed.
- `promote_profile` writes the bio and removes `Interactions` in one transaction. `generate_bio` drops the bio when the campaign changed during the call.

### Pruned profiles

The server deletes a provisional profile that took part in no chat thread, and whose memories no prompt used, for the game days of Prune profiles after (`prune_profile_days`, default 60, 0 for never), because each NPC near a chat gets a profile (`prune_profiles` in `server/chat/characters.py`).

- The age of an NPC comes from the newest of its first save, the game times of its threads, as a speaker or an overhearer, and the uses of their memories. A profile with no game time stays.
- A memory is used when it is a starting memory or a search hit of a chat turn, the topic of a radiant conversation, or a citation of an auto rumor. `campaign_db.use_memories` dates the use with the current game time, so a memory that comes up again keeps each of its members. A cull clears each use after its game time.
- A favorite of the Dialogue Library stays. A character that was in the player's faction at a join of a thread (`thread_member.in_player_faction`) stays, and so does a name of the player's characters in the report (`squad`), because a squad member that only works at a base can be in no thread for a long time.
- The prune asks the game for a report first, because the player's context of the latest request can come from a save that a load replaced, and a later game time prunes more.
- `campaign_db.prune_profiles` writes the name of the NPC over its mark in each memory (see [Conversation memories](#conversation-memories)), so the other members still remember the conversation. Then it deletes the thread members, the row, and the lines of the NPC, and each of its threads with no member left, or with no memory and no line.
- The NPC is a stranger at its next meeting. The seeded roll gives it the same personality, backstory, and speech again.

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
| `POST /api/campaign/cull` | Undo the re-keys, and delete the characters, dialogue, events, rumors, thread members, captives, and memories dated after the current game time, except custom events and their rumors (see [Characters](#characters)). It refuses without a game report (see [Game state](#game-state)). |

- A refused campaign gives status 409. Each edit names the campaign that the page loaded, and the server refuses it for another campaign.
- A record edit carries the `updated_at` that the page loaded, and the server refuses it when the row changed after that.
- `POST /cull` from the SSR HUB is the same cull without the campaign check.

### Journal

The Journal window of the SSR HUB is a notebook of the player (`plugin/ui/JournalWindow.cpp`). Each campaign has its own journal in the `journal` table: the title, the text, and the game time at which the player created each entry. No prompt reads the journal, and the cull keeps it.

| Route | Behavior |
|---|---|
| `POST /journal` | One page of 20 entries (`JOURNAL_PAGE`), newest first by creation, with the active campaign and the page count. A search keeps each entry whose title or text holds the query, case-insensitive. A page number outside the range moves into it. |
| `POST /journal/read` | The title, the text, and the game time of an entry |
| `POST /journal/add` | Store an empty entry at the game time that the plugin sends |
| `POST /journal/save`, `.../delete` | Save the title and the text of an entry, or delete it |

- The `id` is `AUTOINCREMENT`, because the window keeps the ID of the selected entry, and a late save must never reach a new entry.
- An edit does not move an entry, because the move would take the entry to another page.
- The search runs on the server, because the window holds only one page. It folds the case in Python (`str.casefold`), because the SQLite `lower()` folds only ASCII letters.
- The label of an entry is the day and the title, or the first line of the text when the title is blank (`_journal_label` in `server/store/campaign_db.py`).
- Each write sends back the campaign of the page, and the server refuses it with status 409 after a campaign switch, because the same ID can name another entry in another campaign.
- `/journal/add` carries the game time from the plugin (`GameTimeFields` in `plugin/game/Context.cpp`), because the player's context of the latest request can be old (see [Game state](#game-state)).

The window:

- It saves a changed entry before the player leaves it: at the select of another entry, a page change, New Entry, and the close of the window. Save saves at once.
- Each page request and each read takes a number, and the window drops a reply that a newer request made stale, because Search sends a request at each keystroke.
- It escapes `#` in each label and loads the boxes with `setOnlyText`, because MyGUI reads `#` as a colour tag.

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
- A canon character whose name holds a title or an epithet has its own name as its `Alias`, for example Esata for Esata the Stone Golem and Shiro for Lord Shiro, so a line that uses only that name finds it by name. An alias that names another record stays out: King Gurgler has none, because "Gurglers" names the Fishmen.

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

All log files are in the `logs/` folder of the mod root.

| File | Writer | Contents | Size |
|---|---|---|---|
| `SentientSands_SDK.log` | Plugin | The current game. The previous game becomes `SentientSands_SDK.old.log`. | One game |
| `server.log` | Server | The server log | 512 KB, 3 backups |
| `llm.log` | Server | Each prompt and reply, only at `DEBUG` | 2 MB, 1 backup |

The plugin flushes each line, so the lines before a crash reach the file.

## Server state

| Location | Contents |
|---|---|
| `server/data/campaigns/<name>/` | One campaign: `campaign.db` (see [Campaign storage](#campaign-storage)). |
| `server/config/prompts/` | The player's prompt overrides and `base_hashes.json` (see [Prompts](#prompts)). |
| `server/data/user_templates/` | The player's world templates (see [World templates](#world-templates)). |
| `server/config/llm_config.json` | The LLM providers with the player's API keys, the profiles, and the routes (see [LLM routing](#llm-routing)). |

The release does not ship the prompt overrides, the user templates, or `llm_config.json`, so an update keeps them.
