# Architecture

Sentient Sands Rebirth has three parts: a C++ plugin that runs inside Kenshi, a local Python server that talks to the LLM provider, and the Kenshi mod files that make the game load the plugin.

## Repository layout

| Path | Contents |
|---|---|
| `deps/` | Not in git. The KenshiLib and Boost files that the plugin build needs. See [plugin_build_setup.md](plugin_build_setup.md#3-fill-deps). |
| `plugin/SentientSands.vcxproj` | The Visual Studio project that builds `SentientSands.dll`. See [development.md](development.md#plugin). |
| `plugin/main.cpp` | The entry point (`startPlugin`), the game hooks, and the message-queue dispatcher. |
| `plugin/core/` | Shared state and mutexes (`Globals`), logging, INI settings, and server start-up (`Utils`), and the transport to the server (`Comm`). |
| `plugin/game/` | Reads game state into JSON for prompts (`Context`) and applies queued NPC actions to the world (`GameActions`). |
| `plugin/ui/` | The in-game MyGUI windows. `LauncherWindow` is the hub that opens the others. `ChatUIGlobals` holds the shared widget pointers. |
| `server/main.py` | The entry point: it registers the blueprints and runs the start-up (`start`). |
| `server/core/` | The paths (`paths.py`), the session state that the other modules share (`state.py`), the Flask app and its request hooks (`app.py`), the routes that the game calls, such as `/report` and `/history`, and the settings routes (`routes.py`), the pipe to the plugin (`pipe.py`), the INI settings (`settings.py`), the start-up checks for an old server and for the game process (`process.py`), the helpers for the game context (`game.py`), the request checks (`request_guard.py`), and the log files and the log level (`log_setup.py`). |
| `server/chat/` | The chat, banter, synthesis, and Dialogue Library bio routes (`routes.py`), the LLM calls (`llm.py`), the prompt files and the descriptions that fill them (`prompts.py`), the profiles of the characters that the game reports (`characters.py`), the bios (`bio.py`), the conversation memories (`memory.py`), the rumor synthesis (`synthesis.py`), the chat prompt (`chat_prompt.py`) and its scene text (`scene_text.py`), the names (`npc_names.py`), the Current Job (`current_job.py`), the provisional profiles (`provisional_profile.py`), the prompt overrides and placeholders (`prompt_store.py`), and the LLM configuration (`llm_config.py`) and fallback chain (`llm_router.py`). |
| `server/store/` | The campaign database (`campaign_db.py`), the world templates (`world_template.py`), and the creation and the switch of a campaign (`campaigns.py`). |
| `server/dashboard/` | The routes that only the web app calls (`routes.py`) and the browser auto-open (`browser_launch.py`). |
| `server/dashboard/web/` | The web app: plain HTML, CSS, JavaScript, fonts, and images, which the server serves at `http://127.0.0.1:5000/`. |
| `server/tests/` | Unit tests that run with the standard library only. See [development.md](development.md#tests). |
| `server/data/defaults/` | The default providers and models that seed the LLM configuration, and the name and localization JSON. |
| `server/data/prompts/` | The system prompts. |
| `server/data/templates/` | The shipped world templates. See [World templates](#world-templates). |
| `mod/` | The files at the root of the installed mod folder: `mod.info`, `SentientSandsRebirth.mod`, and `RE_Kenshi.json`. A server that runs from the repo also writes its `SentientSands_Config.ini` here, which git ignores. |
| `scripts/` | Release tooling. See [development.md](development.md#release). |
| `package_release.cmd` | A Windows menu that builds the plugin, runs `scripts/package_release.py`, or does both. |

Each server package keeps its Flask routes in `routes.py`, a blueprint that `main.py` registers. Only these modules, `core/app.py`, and `chat/llm.py` import Flask or `requests`, so the tests can import every other module (see [development.md](development.md#tests)). The request guard and the canon hook are hooks of the app in `core/app.py`, because a hook of a blueprint runs only for the routes of that blueprint.

The session state that several modules share is in `core/state.py`. A module reads and assigns it as `state.NAME`, because `from core.state import NAME` copies the value once, and a later assignment, such as a campaign switch, never reaches the copy.

The start-up runs in `start` in `main.py`, not at import, so a module that a test or a tool imports starts no thread and stops no server.

## Installed layout

The release zip unpacks into `Kenshi/mods/` as the tree below. The plugin and the server find each other through these relative paths. Do not change one side without the other.

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

- The plugin takes the mod root from the path of its own DLL (`startPlugin` in `plugin/main.cpp`). A Steam Workshop folder with a numeric name works for this reason.
- The plugin runs `server\python\python.exe server\main.py`. If the embedded runtime is missing, it falls back to `python` on `PATH` (`StartPythonServer` in `plugin/core/Utils.cpp`).
- The server takes its folders from the path of `main.py`. The server root is the folder of `main.py`, and the mod root is the parent of the server root. When the server runs from this repo, it finds the INI in `mod/` instead (`resolve_mod_file` in `server/core/paths.py`).

## Runtime flow

1. RE_Kenshi loads `SentientSands.dll` and calls `startPlugin`. The plugin installs its KenshiLib hooks and starts `MainThread`.
2. `MainThread` waits for `KenshiLib.dll`. Then it starts the pipe listener (`PipeThread`), loads the INI, and starts the server.
3. If `OpenWebPanelOnStart` in the INI is `1`, this first server start passes `--open-browser`. The server waits until its port accepts connections, and then 3 s more, so that a tab from an earlier start can reconnect. It opens the web app in the default browser only when no tab is open (see [Web app](#web-app)). A restart from the launcher does not pass the flag, so the player does not get a second tab.
4. The server listens on `127.0.0.1:5000`. The plugin sends HTTP POST requests to it through WinHTTP (`plugin/core/Comm.cpp`) for chat, history, settings, profiles, and events. The server rejects a request whose `Host` header is not `127.0.0.1:5000` or `localhost:5000`, or whose `Origin` header names another site (`server/core/request_guard.py`). This stops web pages in the player's browser from using the server. A new caller must use one of these two host names.
5. The server sends commands back through the named pipe `\\.\pipe\SentientSands`, which the plugin hosts. Examples are `SET_CONFIG`, `NOTIFY`, and `NPC_RENAME`.
6. The server builds each prompt from the prompt files (see [Prompts](#prompts)) and the campaign state, then sends it down the route of its task (see [LLM routing](#llm-routing)).

## Threading

Background threads do not change game objects or MyGUI widgets. The pipe listener, the HTTP response threads, and the UI worker threads push text messages onto `g_messageQueue` under `g_msgMutex` (`plugin/core/Globals.h`). `playerUpdate_hook` runs on the game thread and drains the queue through `ProcessMessageQueue` (`plugin/main.cpp`). New code that produces results off the game thread must hand them over through this queue.

## Game state

The plugin reads the game state only when a request needs it, and ambient banter is its only post on a timer. This keeps SSR from adding load to the game while no prompt uses the data.

| Request | Game state that it carries |
|---|---|
| Chat (`/chat`) | The context of the target, the context of the squad member who speaks (`speaker`), and the game events |
| Ambient banter (`/ambient`) | The banter NPCs, the player's context (`player_context`), and the game events |
| Cull Future Data (`/cull`) in the SSR HUB, and Generate World Event (`/synthesize`) in the Dynamic World Events Log | A report: the player's context and the game events (`GameReport` in `plugin/game/Context.cpp`) |
| `/report` | A report, when 50 game events wait, or when the server sends `REPORT` through the pipe |
| `/squad_rename` | The context of a member of the player's faction that the game renamed (see [Names](#names)) |

- The server keeps the player's context of the latest request (`take_report`). Its game time and town can be old between requests, so a value that must be current comes with the request that uses it.
- The cull of the web app sends `REPORT` and waits up to 5 s for the report (`report_from_game`). It refuses the cull when no report comes, for example while the game shows the main menu, because a cull by an older game time deletes what the player did after that time.
- Rejected: a context post every 1.5 s. It built two full contexts on the game thread, with the scan for nearby NPCs and the inventory, and it started two HTTP threads, also while no prompt used the data.

### Game events

The hooks in `plugin/main.cpp` log game events, such as combat, trade, and deaths, into a buffer (`LogGameEvent` in `plugin/core/Utils.cpp`). The server writes each event to the campaign (`record_event_to_history`).

- Each event gets the game time and the town of the player when its hook fires, because the event reaches the server only with the next request. That request can come minutes later.
- A request takes the events out of the buffer (`TakeGameEvents`), so the plugin sends each event once.
- The buffer holds 100 events and drops the oldest. The frame hook sends a report when 50 events wait.
- The plugin drops an event while it has no game world, because the event has no game time, and the cull deletes by game time.
- An event is lost when the request that carries it fails, or when the game closes before a request takes it.
- The server drops an event that repeats the last message for its target and type, and the same event within 30 s, because some hooks, such as the knockout hook, fire more than once for one change.
- Rejected: the last 30 events in each context post. The server got each event again every 1.5 s, and its check for repeats let a repeat through after 30 s, so it wrote the same events to the campaign again and again.

## Web app

The server serves `server/dashboard/web/` at `/` and `/web/<file>`. The files are plain HTML, CSS, JavaScript modules, fonts, and images, with no build step, no npm packages, and no assets from a CDN, so the web app works offline and the release needs no extra tools.

The toggle at the top right switches between the light and the dark colours. The browser keeps the choice in `localStorage`, and without a stored choice the page follows the system setting. A small script in the page head sets the theme before the page paints, so a dark page never flashes light.

| Page | Route | Storage |
|---|---|---|
| Settings | `/settings`, `/settings/defaults` | `SentientSands_Config.ini` |
| Models | `/api/llm`, `/api/llm/test`, `/api/llm/models`, `/api/llm/reset` | `server/config/llm_config.json` |
| Prompts | `/api/prompts` | `server/config/prompts/` |
| Campaigns | `/api/campaigns`, `/api/campaign/cull` (see [Campaign routes of the web app](#campaign-routes-of-the-web-app)) | `campaign.db` of each campaign |
| Editor | `/api/campaign/canon`, `/api/campaign/records` (see [Campaign canon](#campaign-canon)); `/api/campaign` and its rumor routes (see [Campaign routes of the web app](#campaign-routes-of-the-web-app)); `/api/templates` (see [World templates](#world-templates)) | `campaign.db` of the active campaign; `server/data/user_templates/` |

A GET route must not change state. A page on another site can send a GET with no `Origin` header, for example through an image tag, so the Origin check from step 4 of the runtime flow does not stop it. The presence stream below is the only exception, because EventSource sends only GET requests. A page on another site that holds the stream open can only stop a new tab from opening.

The server stops when the game closes, and it restarts when the player presses Restart Server, so an open tab can lose the server at any time. The web app reads `GET /context` every 3 s (`poll` in `server/dashboard/web/app.js`). While its requests get no response, it shows a banner and disables its Save buttons, so the player keeps unsaved changes until the server is back. A page that did not load keeps its Save button disabled, and the web app loads it again when the server is back.

Each page with a Save button tracks its unsaved changes and reports them with an `unsaved` DOM event (`reportUnsaved` in `server/dashboard/web/api.js`). While a page has unsaved changes, its nav tab shows a dot, its Discard button loads the saved data again, and the browser asks the player before the tab closes.

Each tab holds `GET /web_panel/presence` open. This event stream sends a heartbeat every second, and the server counts the open streams. The server finds a closed tab only when a heartbeat write fails, so a tab counts as open for up to 2 s after it closes. The stream tells the browser to reconnect 1 s after it loses the server, so an open tab finds a restarted server within the 3 s that the auto-open waits.

**Open Web Panel** in the SSR HUB always opens the web app in a new tab of the default browser. The button does not check for an open tab. A version that brought the browser window of an open tab to the front left an empty box on the game screen in exclusive fullscreen.

Another tab can switch the campaign while a tab is open, so the poll also shows the active campaign. When the poll sees another campaign, it sends a `campaignchange` event. The Campaigns page loads the new campaign, and the open Campaign Canon or Campaign Log subtab of the Editor loads it unless the subtab has unsaved changes.

The save bar of each page has a Refresh button at its right end. Refresh loads the stored data again and keeps the unsaved changes of the page (`refreshers` in `server/dashboard/web/app.js`).

A Refresh click shows a note below the button for 2.5 s. The note says that the page loaded new data, that the page was already up to date, or that the page kept its unsaved changes instead of the new data. When the refresh fails, the note repeats the error of the save bar. Each refresher returns a key of `REFRESH_NOTES`, or nothing when it failed. An auto refresh shows no note.

A message in the save bar that reports an outcome, such as "Saved." or "Deleted X.", clears after 5 s (`flashMessage` in `server/dashboard/web/api.js`). An error, or a message about the state of the page such as "Unsaved changes.", stays until the next message replaces it.

`GET /context` also returns `writes`, the number of writes since the server started. It counts each commit to the campaign database (`campaign_db.writes`) and each successful POST request under `/api/` or to `/settings` (`count_write_requests` in `server/core/app.py`). When the number changes, the poll refreshes each loaded page, so a change from the game or from another tab reaches an open page. The auto refresh waits while a request runs or a dialog is open, because the request or the dialog can still change the page. It also waits while the player types in a field of the page, because the refresh rebuilds the page and the field loses the caret.

A refresh keeps the unsaved changes of each part that a Save writes, and loads the stored data of all other parts:

| Page | A refresh keeps |
|---|---|
| Settings | Each changed field. |
| Prompts | Each changed prompt. |
| Editor | Each changed record, rumor, or memory. A changed record keeps the version that the page loaded, so its save still fails as stale when the record changed elsewhere. |
| Models | The whole page, because Save writes the whole configuration. When another tab changed the models, the page tells the player that Save overwrites that change. |

A refresh changes the message of the save bar only when the unsaved state of the page changes, so a change from elsewhere does not hide a "Saved." that the player did not read. The Editor does not put unsaved changes on the data of another campaign or template, so a refresh after a switch keeps the page as it is until the player discards.

The Editor holds many records. Save sends one request for each changed record, and a record that the server rejects keeps its draft and shows the reason. A delete takes effect at once, after a confirmation.

The Editor has three subtabs. Campaign Canon and Templates share the record list and forms: Campaign Canon edits the canon of the active campaign, and Templates edits the world templates that new campaigns copy. Campaign Log shows the active campaign in two subtabs of its own: Dialogue & Memories, and Events. Events edits the rumors and lists the events. The page holds the data of one subtab and one template at a time, so a switch with unsaved changes asks the player first. A shipped template is read-only, so the page offers a duplicate.

Dialogue & Memories lists the chat threads of the active campaign, newest first, each with the game time of its first exchange and its speakers (see [Chat threads](#chat-threads)). It uses the layout of Campaign Canon: a search field and the list on the left, and the selected thread on the right, with its lines, its memory under Memorised Summary (see [Conversation memories](#conversation-memories)), and its speakers and overhearers under Involved Characters. A thread with a memory shows only its memory, because the memory replaces its lines. The search matches the names of the members, the text of the lines, and the memory, with case ignored. `GET /api/campaign` returns every thread with its lines and its memory, as Campaign Canon loads every record, so the search runs in the page. The lines are the copy of a speaker, because its lines have no `(Overheard)` tag (`campaign_db.threads`). The memory under Memorised Summary is editable: Save writes each changed memory, and Delete removes the conversation after a confirmation (see [Conversation memories](#conversation-memories)). The lines are read-only, and banter has no threads, so it stays out.

On Campaign Canon, **Show seeded data** and **Show provisional characters** start on. While the player turns one off, the record list hides the records whose `origin` is `seed`, or the provisional characters (see [Provisional profiles](#provisional-profiles)). The browser remembers each switch. The overview and the history have no `origin`, so they always show.

**Player faction only** starts off. While the player turns it on, the record list shows only the player's faction and the characters in it. A character is in it when its Current Faction, or its `Faction` while the game reported no Current Faction, names the player's faction or one of its aliases. The `Faction` of a profile keeps the faction of the first meeting, so a recruit counts only after the game reports its Current Faction.

The Facts section of a faction, race, location, or region offers only the categories of its kind (`FACTS` in `server/store/world_template.py`), because the validator refuses any other category. `server/dashboard/web/editor.js` keeps a copy of the categories, so a change to them changes both files. A category holds one text, such as the leader of a faction, or a list of text, such as its enemies.

The Relations section of a race, location, or region lists its children, which the entry stores, and its parents, which are the entries whose children name it. Each row opens its entry. A parent row is read-only, because the relation is stored in the parent entry.

The Race, Sex, and Faction of a character are choices, not free text (`choice` in `server/dashboard/web/editor.js`). Race offers the race entries of the page, Faction offers its factions, and Sex offers Male, Female, and Other. A stored value selects the choice whose name or alias it matches, with case ignored. A blank value or a value that matches no choice shows as Unknown, and a save of the character writes Unknown.

Other Details shows the `Relation` of a character as a bar from -100 to 100, with the labels of the relation bar in game, and its `OriginFaction`. On Campaign Canon it also shows the current faction that the game reported for the character since the server started, so the player can compare it with the Faction that the prompts use, and, at the bottom, the Current Job (see [Current Job](#current-job)). All are read-only, because the game and the chats set them. A save keeps every profile key that the form does not show, as it is.

A provisional character (see [Provisional profiles](#provisional-profiles)) shows as Provisional in the list and on its record. Its Other Details also show its chat count against the Chats before a bio setting. A save that changes its Personality, Backstory, or SpeechQuirks ends the provisional state, because a later bio would overwrite the player's text.

Each character has a Generate Bio button to the left of Delete, with a gap so that a click meant for one button does not hit the other. The button asks the LLM for the full bio or for one part of it, with the player's instructions, and puts the text into the form (`writeBio` in `server/dashboard/web/editor.js`). The text is unsaved, so the player reads it before a save keeps it. A save of a provisional character with the new text ends the provisional state, as a hand edit does. The request carries the profile of the form, so an unsaved race or faction counts.

A save of a character renames the NPC in game (see [Names](#names)), and an open Dialogue Library in game loads its list and its selected NPC again (`REFRESH_LIBRARY`, `RefreshLibraryUI` in `plugin/ui/LibraryWindow.cpp`). A delete of a character also loads the Library again.

## Settings

The server is the only writer of `SentientSands_Config.ini`. The plugin reads the INI once at start, because it starts before the server. After that, it takes changes only through `SET_CONFIG` on the pipe. Two writers with no lock between them would undo each other's changes.

The release does not ship the INI, so an update keeps the player's settings. On the first start, the plugin reads no INI and uses the defaults in `LoadPluginConfig` (`plugin/core/Utils.cpp`). The server then writes the INI with `SETTINGS_DEFAULTS` (`server/core/settings.py`). At each start, the server sends each value that the plugin holds through `SET_CONFIG` (`push_settings_to_plugin`), so the defaults of `LoadPluginConfig` apply only until the server is up. `OpenWebPanelOnStart` is the exception, because the plugin reads it before it starts the server, so its default in `LoadPluginConfig` must agree with `SETTINGS_DEFAULTS`.

The web app's Settings page posts its changes to `/settings`. The server writes the INI and sends each value that the plugin holds through `SET_CONFIG`. A language change sends the new translation table through the pipe as `APPLY_TRANSLATION`.

**Reset to defaults** on the Settings page reads `GET /settings/defaults` and fills the form without a save, so the player can review the values before the usual save sends them. The defaults have a route of their own and are not part of the `/settings` reply. The plugin reads that reply by searching for the first match of each key (`GetJsonValue` in `plugin/core/Utils.cpp`), so a nested copy of the same keys could give it a default instead of the setting.

The plugin re-creates its pipe instance after each message, so a message sent immediately after another can find no instance. `send_to_pipe` retries for 0.25 s for this reason. When the game does not run, each message therefore costs 0.25 s.

## Prompts

Each file in `server/data/prompts/` is a shipped default, and an update replaces it. The player's edit of a prompt is an override in `server/config/prompts/` under the same file name, so an update keeps it. `load_prompt_component` takes the override when it holds text, and the shipped file otherwise. The campaign folder holds no prompts.

The Prompts page of the web app reads `GET /api/prompts` and saves each changed prompt through `POST /api/prompts` (`server/chat/prompt_store.py`).

- A route takes only the name of a shipped `.txt` file, never a path, so a request cannot write outside `server/config/prompts/`.
- A save equal to the shipped text, or an empty save, deletes the override, so the prompt gets later default updates again. **Use default** and **Reset to defaults** fill the form with the shipped text, and the next save deletes the overrides.
- Each save of an override stores the SHA-256 of the shipped text in `server/config/prompts/base_hashes.json`. When an update changes the shipped text, the hash no longer matches, and the page marks the override. An override with no stored hash, for example one made by hand, is marked as unknown.
- An override and `base_hashes.json` are written to a temporary file and then renamed, as `llm_config.save` does.

A placeholder is a `{name}` in a prompt. `prompt_store.render` replaces each placeholder that its caller fills and leaves every other brace as text. A stray brace in an edited prompt therefore cannot fail the LLM call, as it could with `str.format`, and a JSON example in a prompt needs no escaped braces.

- A save is rejected when the override uses a placeholder that the shipped text does not have. A placeholder of the shipped text that the override leaves out gives a warning, because the prompt then loses that data.
- A hand-made override can still hold a wrong placeholder. `fill_prompt` then leaves it as text and logs a warning.
- Rejected: Jinja2. Flask already bundles it, but template logic lets one edit break the whole prompt, and a syntax error fails the call.

A chat request is ordered for a provider's prompt cache, which reuses only an identical start of a request (`chat` in `server/chat/routes.py`, `server/chat/chat_prompt.py`):

| Part | Content | Changes |
|---|---|---|
| System message | `prompt_chat_template.txt`: `prompt_system.txt`, the judgment rule, `npc_chat_template.txt`, then `prompt_chat_scene.txt`: the place, the 5 newest rumors, the player, and the NPC; then the memories of the NPC (see [Conversation memories](#conversation-memories)) | When a new conversation starts, and when a memory of the NPC is written |
| History | The lines of the chat threads of the NPC that have no memory yet, as user and assistant turns, with an overheard note after each chat thread (see [Chat threads](#chat-threads)) | One exchange more each turn |
| Last user message | `prompt_chat_turn.txt`: the player's line, then a one-line reminder of whom to reply as and to end with the judgment | Every turn |

From one turn to the next, only the newest exchange and the last message are new, so the cache can serve the rest. Chats with different NPCs, by any speaker, and banter share the start of the system message.

The scene is a snapshot that the server takes when a conversation starts, and it keeps it for the whole conversation (`CONVERSATION_SCENE`). A conversation lasts until the player chats with another NPC, speaks as another squad member, or switches the campaign, because the plugin sends no signal when a conversation ends. A new name or a new faction of the NPC, for example after a recruit, also starts a new conversation, so the scene shows the NPC as it is now. So does the first exchange of a squad member with an NPC that never spoke with it before, so the scene stops saying that the two never spoke (see [Chat threads](#chat-threads)). A later relation or a new rumor therefore reaches the prompt only in the next conversation. The history of the NPC stays across conversations.

The scene is prose that the NPC reads in the second person, built by `server/chat/scene_text.py` from the game's data: "You feel mildly hostile towards Nameless, the group Drifter travels with." A model reads a sentence more reliably than a raw number, and the cache serves the longer text after the first turn of a conversation. Each number becomes a sentence from a fixed scale, such as the relation, the faction stance, hunger, money, fighting skill, the fighting skill of the player against the NPC, and the age of a rumor. The bounds of the relation at ±25, ±60, and ±90 match the relation bar that the game shows, and steps at ±10 add finer grades. Every other person is "they", so no sentence needs a gendered pronoun.

`prompt_system.txt` holds the rules and the world lore, and `build_system_prompt` fills it. `scene_values` fills the parts that change on each call, for the chat scene and for banter. A block that appears only with data, such as the rumors, keeps its heading in the code, because a placeholder has no conditions. The `{world_lore}` placeholder takes the overview of the campaign (see [Campaign storage](#campaign-storage)).

`npc_chat_template.txt` describes the NPC of a chat from its profile (`describe_npc`). Banter keeps its one-line list of NPCs in the code, because the plugin reads the `Name|ID` of each line.

- The history is a block window of those lines (`chat_prompt.history_window`). It keeps its first line while it grows from 20 to 39 lines, and then it moves on by 20 lines. A window that moved with each new line would change the start of the history on every turn, so the cache could never serve it.
- `chat_prompt.history_turns` makes each line whose speaker is the NPC an assistant turn, without the time and the name, and every other line a user turn (see [Characters](#characters)). The lines of another NPC with the same name therefore do not count as its own turns. A rename relabels the lines that the NPC spoke with the new name (`campaign_db.rename_character`), so its dialogue shows one name.
- The server stores a reply without its bracketed tags, such as the judgment.
- Chat templates of the Mistral v3 family place the system text next to the last user message. With those models, the cache cannot serve the system message.

The server answers a Yell with one NPC, as a Talk. A Yell differs only in that the NPCs within the yell radius overhear it, and the player's line carries a `(Yelled)` prefix, as a whispered line carries `(Whispered)`. The history keeps the prefix, so the NPC remembers how each line was said.

An NPC that overhears a chat stores both lines with an `(Overheard)` prefix, and each line names the one that it was said to, as in `(Overheard) Drifter to Ruka: ...` and `(Overheard) Ruka to Drifter: ...`. Without that name, a listener took the "you" of the line as itself and answered the player as if the line was said to it. A reply rule in `response_rules.txt` also tells the model that an overheard line was not said to the NPC.

The judgment rule sits in the cached system message, and the last message repeats only a short reminder, because a model follows an instruction at the very end of a request most reliably. Banter reads the same reply rules but forbids bracketed text, so the judgment rule stays out of `response_rules.txt`.

The reply text of `/chat` starts with the name of the NPC, because the plugin takes the text before a first colon as the speaker (`plugin/ui/ChatWindow.cpp`). A reply such as "Listen: ..." therefore stays with the NPC. For a generic NPC, the serial of its handle follows the name, as in `Name|serial:`, so the plugin finds the NPC after a rename that its request did not know (see [Names](#names)). The server removes a `*stage direction*` from a person's reply, but an animal replies only in `*actions*`, so those stay.

A chat reply carries no game actions: the prompts offer the LLM no action tags, and the `actions` list of a `/chat` reply is empty. The server reads only the judgment of a reply, which changes the NPC's personal relation. The debug commands of the chat, such as `/attack`, still send their action to the plugin. The scene shows only the equipment that the player and the NPC wear or hold, because the contents of a bag mattered only for trading.

The bio prompt, `prompt_profile_generation.txt`, takes `{race_lore}` from the race entries of the campaign (`describe_race`), or of the template for a character on the Templates page, matched by name or alias with case ignored. A template that describes its races therefore shapes the bios, and a race with no entry gets a line that says so. The player section of the scene gives the description of the player's race entry in the same way, and only the name of a race with no entry.

When the origin faction of an NPC is its current faction, the chat prompt gives the origin as "Same as the current faction." (`describe_origin`), because the prompt already holds the whole entry of that faction.

## LLM routing

Each LLM call names a task: `chat`, `ambient`, `profile`, `synthesis`, or `memory`. The server makes no `synthesis` call while `RUMOR_SYNTHESIS` is off: it stores the events of the game, but the timer does not start and `/synthesize` refuses. `server/config/llm_config.json` holds four parts, and the web app's Models page edits all of them through `/api/llm`.

| Part | Contents |
|---|---|
| Providers | An OpenAI-compatible endpoint: type (`openai` or `player2`), base URL, API key, and the Player2 game key. |
| Profiles | One model on one provider, with a per-attempt timeout and extra request parameters. |
| Default profile | The profile that every route uses at the place of its `null` entry. |
| Routes | For each task, an ordered list of profiles, `max_tokens`, `temperature`, and a deadline. Each list holds `null` once, which stands for the default profile (`llm_config.route_profiles`), so a change of the default reaches every task. |

`llm_router.run_route` tries the profiles of the route in order, one attempt each. It moves to the next profile after an exception, a non-200 status, or an empty completion. Each attempt gets the smaller of the profile's timeout and the time left before the deadline. The default deadline is 55 s, because the plugin stops waiting for a reply after 60 s (`plugin/core/Comm.cpp`).

The request body starts with `model`, `messages`, and `top_p` 0.9. The route's `max_tokens` and `temperature` come next, and the profile's extra request parameters override both.

`log_usage` logs the prompt tokens of each reply and how many of them the provider's cache served, as OpenAI and OpenRouter (`usage.prompt_tokens_details.cached_tokens`), DeepSeek (`usage.prompt_cache_hit_tokens`), and llama.cpp (`timings.cache_n`) report it. It also logs the tokens that the model wrote (`usage.completion_tokens`) and the time of the request. For llama.cpp, it splits that time into reading the prompt and writing the reply, with the writing speed (`timings`), so the log shows whether a slow reply came from a long prompt or from a slow model.

A Player2 provider uses a session key from the local Player2 app. On a 401, `send_completion` gets a new session key and tries the same profile once more.

`/api/llm` never returns a stored API key. It returns only whether a key is set. A key that starts with `YOUR_`, like the placeholders in `default_providers.json`, counts as not set. A save with an empty key field keeps the stored key, so the web app can send back what it received. A renamed provider sends its old name as `previous_name`, so it keeps its stored key (`llm_config.with_stored_keys`). The server writes the file to a temporary name and then renames it, so a crash during a save cannot leave a half-written key file.

A rejected save returns each error with the path of its field, for example `["profiles", "kimi", "model"]`, and the web app marks that field.

`POST /api/llm/test` tests the profile and the provider as the web app holds them, so the player can test before a save. `POST /api/llm/models` lists the model IDs of a provider in the same way, through the provider's OpenAI-compatible `GET /models`. Both fill an empty key field with the stored key only when the base URL is the saved one (`llm_config.provider_from_form`). A request with a mistyped base URL therefore cannot send the stored key to another host.

On a start without `llm_config.json`, the server builds it from `default_providers.json` and `default_models.json` in `server/data/defaults/`. Each task gets one route that holds only the `player2-default` profile.

When the server loads `llm_config.json`, each task that the file lacks gets the default route (`llm_config.default_route`). The file of an earlier version, which lacks the tasks that a later version added, therefore keeps working, and the next save writes the new routes.

**Reset to defaults** on the Models page posts to `/api/llm/reset`, which builds the same configuration and saves it at once. The page does not hold the stored keys, so the reset cannot fill the form for a later save as the Settings page does. The reset removes the providers and profiles that the player added, with their keys. A default provider keeps its stored key only when the stored base URL has the same host as the default one (`llm_config.reset`), so a key for a custom host does not go to the default host. A placeholder key of the defaults never replaces a stored key.

## Campaign storage

`server/store/campaign_db.py` keeps the characters, the dialogue with its chat threads and their memories, the canon, the event history, and the rumors of a campaign in one SQLite file, `campaign.db`, in the campaign folder. The plugin reaches this data only through the server's routes.

- Each write runs in one `BEGIN IMMEDIATE` transaction. A profile write merges only the keys that the caller passes, and the dialogue lines are rows of their own. A route that waits for the LLM must write only the keys that it changed, so that it cannot undo a change that another request made during the wait.
- `/chat` changes the Relation through `change_relation`, which adds the judgment to the stored value in one transaction. Two overlapping chats with the same NPC therefore keep both changes.
- Each operation opens a connection with a 5 s busy timeout and closes it. A campaign switch changes only the database path that `open_campaign` sets.
- The database uses the default rollback journal, not WAL. The campaign folder therefore has no `-wal` or `-shm` file, and a player can copy it while the server is idle.
- No dialogue line is trimmed. The memory of a chat thread replaces its lines (see [Conversation memories](#conversation-memories)), and banter lines stay. The campaign keeps its newest 500 events. An event that the table already holds is not added again.
- Favorites belong to each campaign.
- Rejected: one database for all campaigns, with a `campaign_id` column. A query that missed the filter would leak data between campaigns.

A new campaign is a copy of a world template (see [World templates](#world-templates)): its canon and the name, version, and content hash of the template. After the copy, the campaign does not depend on the template, so a template edit or a deleted template does not change it. Only the Campaigns page of the web app creates and switches campaigns. The game has no campaign window.

`open_campaign` creates `campaign.db` in a campaign folder that has none, from the SSR Vanilla template. It builds the database in `campaign.db.tmp` and then renames it to `campaign.db`. A crash before the rename leaves no database, so the next start creates it again. A database of an earlier schema version is not upgraded: `open_campaign` refuses it, and each later operation fails with the reason until the player switches to another campaign.

After the player deletes the last campaign, the server has no current campaign: `current_campaign` is empty, and each operation fails with the reason until the player creates a campaign. The empty value stays across a restart, so the server does not create a campaign again. When the server has no current campaign, the Campaigns page switches to the campaign that the player creates.

A route that needs the campaign then answers status 409 with the reason, and the server logs one warning line for it instead of a traceback. A context post still updates the player's context, but the server drops the events in it.

A `campaign.db` that is gone while the server runs, for example because the player deleted the folder by hand, makes each operation fail with the reason in the same way. The server creates the folder again only at the next start.

### Campaign canon

The canon of a campaign is its copy of the template records: the overview, the history, the factions, the characters, the races, the locations, and the regions.

| Record | Storage | Key |
|---|---|---|
| Overview, history | `meta` rows; the history as JSON | None |
| Faction | `faction` table (see [Factions](#factions)) | The game ID |
| Character | `character` table (see [Characters](#characters)); the profile as JSON | `u:` and the game ID |
| Race, location, region | `entity` table, with `races`, `locations`, or `regions` as the category; the whole template record as JSON | The category and the entity ID |

- The chat prompt reads the overview, the factions, the race of the player, and the profiles of the characters in the chat. The profile prompts read the races (see [Prompts](#prompts)). No prompt reads the history, the locations, or the regions yet.
- `origin` tells where a record came from: `seed` (the copy of the template at creation), `game` (a faction that a context reported, or a character that the server added in play), or `campaign` (added on the web app).
- A save checks the record with the template validator (`world_template.record_problems`), so a campaign record follows the same rules as a template record. The validator sees only one record, so the database refuses a second faction or character with the same game ID.
- The key of a faction or a character, its game ID or its `npc_id`, cannot change after the record is added.

### Factions

Each campaign holds its own copy of the factions, keyed by the string ID of the faction in the game data. The prompt describes a faction from this copy: its name, its fields, and its description (`describe_faction`).

- The server finds a faction by the `factionID` of a context, or by name or alias when only a name is known, for example the origin faction in a profile. The name match ignores case and is exact, so Holy Nation Outlaws never takes the description of The Holy Nation.
- The loyalty note for members of a major world power reads the `major` flag.
- A faction that a context reports and the copy lacks gets a row with the name that the game gives and an empty description (`note_faction`). The plugin sends the name, or `Neutral`, as the ID of a faction with no string ID, and the server records no row for those.
- The player's faction is the row of the `factionID` of the player's context. Its name follows the game, because the player can rename the faction in game. Its description is the player faction block of the chat prompt, and an empty description leaves the block out.
- The server records each reported faction once per campaign in memory (`SEEN_FACTIONS`), because each chat and banter carries the player's context.

### Characters

The `character` table holds every character of a campaign in one shape: the canon characters of the template, the NPCs that the player meets, and the player's squad. Each row is keyed by the `npc_id` that the plugin builds (`GetNpcId` in `plugin/game/Context.cpp`), because only the plugin sees the game objects:

| Character | `npc_id` |
|---|---|
| A unique NPC, for example Beep | `u:` and the string ID of its template in the game data |
| Every other character | `h:` and the `serial` of its handle |

- A unique NPC has the same `npc_id` in every save and every campaign, so a canon character of a template binds to it. Many generic NPCs share one template, so a generic NPC takes the `serial`, the only part of its handle that survives a save, a town reload, and a recruit ([kenshi_internals.md](kenshi_internals.md#character-identity)).
- Rejected: a hash of the string ID. The template loader in Python and the plugin in C++ would have to compute the same hash, and a hash hides the template and the mod that the ID comes from. JSON and SQLite carry the raw string ID unchanged, also with spaces, `'`, and parentheses, for example `2757496-Bele'coz.mod`.
- A character that the game creates again, for example a guard that replaces a dead guard, is a new NPC with a new profile.
- The server stores an `npc_id` exactly as the plugin sends it. It builds an `npc_id` only for a canon character, `u:<game_id>`, so that chat uses the canon profile instead of a generated one. Dialogue adds to the row and does not change the canon profile.
- A generic NPC whose template is a canon character gets the `npc_id` of that character and counts as unique (`adopt_canon`), so it uses the canon profile and never gets a rolled name. Whether a template is unique depends on the mod list (see [Kenshi internals](kenshi_internals.md#character-identity)). The plugin sends the string ID of the template as `template_id`, and a hook rewrites each NPC of a request before any route reads it, including the contexts that arrive as JSON strings.
- The name is only the `Name` key of the profile, so two NPCs with one name keep two rows, and a rename keeps the row and its dialogue.
- A `Race`, `Sex`, or `Faction` of `Unknown` takes the value that the plugin reports for the character (`get_character_data`). A missing `Race` or `Faction` stays missing. A canon character whose race, sex, or faction the game data does not fix therefore holds `Unknown`, so the first meeting fills it with the value of the spawned NPC.
- The game reports every skeleton as male, so the server gives a skeleton the sex Other in profiles and prompts (`reported_sex`). A skeleton race is a race whose name starts with Skeleton, P2 Unit, P4 Unit, Screamer, or Soldierbot, which covers the skeleton races of vanilla Kenshi and UWE. The race flag `is robot` cannot tell them apart, because it also marks hive queens, robot spiders, and the mechanical hive of UWE.
- Within one chat or banter request, the server keys each NPC by its `npc_id`, because NPCs near the player can share a name, for example two Dust Bandits that the campaign does not hold yet. A banter line names its speaker as `Name|ID`, and the server maps the ID, the serial of the handle, to the `npc_id`.
- Rejected: a number in a duplicate name within a request, such as Dust Bandit (2). The number would reach the LLM and the dialogue history.
- Each dialogue row stores the `npc_id` of its speaker in `speaker`, or nothing when the speaker is unknown. A banter line goes into the history of every NPC nearby, so a name cannot tell whose line it is when two of them share a name.
- Rejected: the `npc_id` of the speaker inside the line text. The text reaches the LLM, the Dialogue Library, and the bio prompt.
- The player section of the chat scene describes the squad member who speaks, the `speaker` of the chat request: its name, race, sex, health, hunger, faction with the description of the player's faction, worn equipment, and the building it is in. Its money stays out, because an NPC cannot see a wallet. Its personality, backstory, and speech quirks stay out, because they serve only an LLM that speaks as that character. The chat window offers the members of the current squad except the talk target, and starts on the last speaker while that character is still in the squad. Ambient banter has no speaker, so it uses squad slot 1 from the player's context.
- The Dialogue Library lists each character with dialogue and each character that is not seeded, so the seeded characters that the player never met stay out of it. A character whose lines are all `(Overheard)` stays out too, because every NPC near a chat overhears it. A member of a chat thread counts as having dialogue, and a speaker as taking part, because a memory replaces the lines (`campaign_db.list_characters`).
- `LIVE_CONTEXTS` keeps a few fields of the latest context of each NPC that a chat reported, by `npc_id`: the race, the faction, the nearby NPCs, and the distance to the player.
- The NPC section of the chat scene reads the whole context of the talk target from the chat request (`npc_scene`), so its fighting skill, health, hunger, money, equipment, task, building, and faction stance reach the scene. It also compares the fighting skill of the speaker with the fighting skill of the NPC, the higher of melee attack and melee defence, for example "Stick looks much weaker than you." (`scene_text.strength_text`).

### Chat threads

Each chat exchange belongs to a chat thread, which records who took part in the conversation. The copies of a line in the histories cannot tell this, because the memory of the thread replaces them.

- The `thread` table holds the ID, the game time of the newest exchange, and the memory (see [Conversation memories](#conversation-memories)). The `thread_id` column of `dialogue` links each chat row to its thread. Banter rows have no thread.
- The `thread_member` table holds each member of a thread: its `npc_id`, its role (`speaker` or `overheard`), the game time when it joined, and whether it was in the player's faction then. The speakers are the squad member who speaks and the NPC, and the overhearers are the listeners of each exchange. Only a character whose copy the server stores becomes a member.
- A member keeps the values of its first join. The history text therefore stays the same from turn to turn, so the cache serves it, and a later recruit or dismissal does not change what an NPC remembers.
- The server keeps the current thread in memory (`CURRENT_THREAD`). A chat with another NPC, a chat as another squad member, a campaign switch, a cull, a server restart, or a pause without a chat reply as long as the Conversation timeout of the Settings page (`conversation_timeout_minutes`, default 3) starts a new thread. The server measures real time, because it sees the game time only in the requests that it gets. The close of the chat window does not end a thread.
- Rejected: a thread that also ends after a long pause in game time, for example when the player speeds the game up. It would add game state to track for each thread, and the real-time pause covers the common case.
- A thread does not follow the scene: a new name of the NPC or the first exchange starts a new scene but not a new thread.
- `thread.id` is `AUTOINCREMENT`, so the ID of a deleted thread never names a new thread. `join_thread` starts a new thread when the current one is gone.
- A cull or the delete of a character deletes each thread that has no memory and that no dialogue row uses any more, with its members. A cull also deletes the members that joined after the cut.
- Rejected: members derived from the rows that hold the thread. The memory replaces the rows, and the headers of the memories and the first meeting read the members.
- Rejected: one stored row for each line, with a table of the characters that heard it. Each copy has its own `(Overheard)` tag and its own relabel after a rename, so the history of a character would have to rebuild both from a join.
- Rejected: one thread for each player message. A conversation of ten messages would be ten threads.

The chat prompt reads the threads and the speaker of each row, so the NPC tells the squad members apart:

- **First meeting.** The NPC spoke before with the squad member who speaks when the two were the speakers of a chat thread (`campaign_db.thread_partners`), or when the history of the NPC holds a line of that squad member without the `(Overheard)` tag, such as a banter line (`chat_prompt.spoken_with`). A thread counts after its memory replaced its lines. The check reads the `npc_id` of each member and row, not the name.
- **Companions.** The scene names the others that the NPC spoke with, by the same check, when they are in the player's faction now: "Earlier you spoke with Stick, who travels with Izumi." A character counts when its `Name` is in the `squad` list of the player's context, which the plugin fills from the player's characters.
- **Relation.** The NPC keeps one `Relation`, which the chats of every squad member change, so the relation sentence names the player's faction: "You feel friendly towards Nameless, the group Izumi travels with." Each step of the scale ends with the name, because the name carries that clause. For an NPC in the player's faction, the sentence reads as its feeling within the group.
- **Overheard notes.** After the last line of each thread in which the NPC is a speaker, the history adds one user line that names the overhearers that were in the player's faction: "Stick and Mikse heard your conversation with Izumi." (`chat_prompt.overheard_notes`). Other overhearers are not named, because only a squad member can later speak to the NPC as the player. A thread that the NPC only overheard gets no note, and a thread with a memory has no lines, so its memory header names the overhearers instead.
- The note of the current thread is at the end of the history, and it moves after each exchange, so the cache loses the tokens of one exchange on each turn. A note at the start of a thread would break the cache from the start of the thread each time a new squad member walks up.

### Conversation memories

The server distills each chat thread into a short memory, which replaces the lines of the thread. The chat prompt, the Dialogue Library, the bio prompt, and the Dialogue & Memories subtab read the memories (see [Web app](#web-app)).

- A thread is pending when it has a line and no memory. When no chat request or reply came for the Conversation timeout (`quiet_seconds`), the server writes the memory of each pending thread of the active campaign, one call at a time, the oldest first (`memory_loop` in `server/chat/memory.py`). The server start, a campaign switch, and a cull start this quiet clock again (`restart_quiet_clock`).
- The distillation runs once in each quiet period. After a failed call, the thread stays pending, the server moves on to the next thread, and the next quiet period tries the failed thread again.
- Before each call, the server checks that the chat is still quiet, so a chat that starts during the distillation waits for one call at most. A local model serves one request at a time, so a call during a chat would delay the reply.
- Before each call, the server also ends the current thread, under `THREAD_LOCK`, so a chat during the call starts a new thread and each memory covers a whole thread. A pause as long as the Conversation timeout therefore splits a conversation into two threads.
- The call takes the `memory` task (see [LLM routing](#llm-routing)) and `prompt_thread_memory.txt`, with the lines of the copy that the subtab shows (`campaign_db.pending_threads`). The memory names each speaker and never says "you" outside a quote, so every member of the thread can read the same text. It tells what came of the conversation, not the order of its lines, and quotes at most one line that stood out word for word, because people remember a sharp line better than a summary of it.
- A thread stores its memory once, and each member reaches it through `thread_member`. Rejected: a memory for each member, written from the view of that member. Each member would cost one call, and a crowd near a chat would multiply the calls.
- The stored text marks each name of a member with the `npc_id` of that member, and the server puts in the current name each time that it reads a memory (`chat_prompt.mark_names`, `chat_prompt.named`). A rename therefore changes the name in every memory. Only a whole name counts, the longest first, so "Dust Bandit" does not match inside "Dust Bandit Josh". A name that two members share stays as text, because its mark could name the wrong member, and so does a short form of a name.
- Rejected: marks in the lines that the call reads. The model writes a better memory from names, and a mark that it dropped or changed would leave a broken name.
- `campaign_db.set_memory` stores the memory and deletes every copy of the lines of the thread in one transaction. The thread keeps its members.
- Nothing else trims the dialogue. The lines of a pending thread stay until its memory is written, so a provider that keeps failing leaves them in the histories. Banter lines have no thread, so they stay for good.
- Memories are not trimmed: a memory is about 500 bytes, so 10,000 conversations add about 5 MB to a campaign.
- A cull deletes each thread whose memory is dated after the cut, because the memory replaced every line, so nothing from before the cut is left to keep. A pending thread loses only its lines after the cut.
- The server drops a memory when the active campaign changed during the call, because the same thread ID can name another thread in the new campaign. It also drops a memory when the game time of the thread changed during the call, for example because a cull removed its newest lines (`campaign_db.set_memory`).

The chat prompt gives the NPC the newest 10 memories of the threads in which it is a member, oldest first, after the scene in the system message (`{memories}` in `prompt_chat_template.txt`, `chat_prompt.memories_block`). The memories are older than every line of the history, so they come before it.

- The heading stays in the code, as for the rumors, so an NPC with no memory gets no heading.
- The server reads the memories on each turn, not with the scene, so a memory that the distillation writes during a conversation reaches the next turn. That turn misses the prompt cache once.
- Each memory gets a header from the view of the NPC, built from the members, so one stored text serves every member: `[Day 3, 14:05] You spoke with Stick. Izumi heard it.` for a speaker, and `[Day 3, 14:05] You overheard Stick and Jorge.` for an overhearer. The header of a speaker names only the overhearers that were in the player's faction, as the overheard note does (see [Chat threads](#chat-threads)).
- The history holds only the lines of the chat threads that have no memory (`chat_prompt.chat_lines`), so an NPC whose threads all have memories gets no history turns. Banter lines stay out, because banter has no threads, so its lines would never get a memory.
- Rejected: threads and memories for banter. Each banter would cost a call, and the memories of banter would push the memories of chats out of the newest 10.
- The Dialogue Library and the bio prompt read each memory as one line, such as `[Day 3, 14:05] (Memory of a conversation with Stick, heard by Izumi) ...`, before the stored lines (`recorded_history`). A header line, such as `(Conversation with Stick, heard by Izumi)`, comes before the lines of each chat thread that has no memory yet (`chat_prompt.headed_lines`). The banter prompt reads only the stored lines.
- The player edits or deletes a memory on the Dialogue & Memories subtab (`POST /api/campaign/memories`, `.../memories/delete`). An edit marks the names of the members again, as after the call. A delete removes the thread with its members, because the memory replaced its lines, so the NPCs forget the conversation, also for the first meeting. The in-game Dialogue Library shows the memories but cannot edit them.

### Names

The game gives most generic NPCs a name of its own, and the server keeps that name (`server/chat/npc_names.py`). The plugin sends the template name of the NPC as `template`, its string ID as `template_id`, and `unique` for a unique NPC, in the context of an NPC, in each NPC of the `nearby` list of a chat, and in each NPC of a banter request. The server makes the `Name` of the profile from the game name and the template name (`name_of`):

| Template | Name in game | `Name` |
|---|---|---|
| A title and a name token, `Barman /GENNAME/` | Barman Arleen | Arleen |
| A name token only, `/GENNAME/` | Nuno | Nuno |
| No token, and the game shows another name, `Drifter` | Nuno | Nuno |
| No token, and the game shows the template name, `Dust Bandit` | Dust Bandit | Josh, a rolled name |
| A unique NPC, `Ruka` | Ruka | Ruka |
| A generic NPC whose template is a canon character, `Yamdu` without UWE | Yamdu | The canon `Name`, Yamdu |

- A name token is a word in capitals between slashes, such as `/GENNAME/` or `/UCNAME/`, and the game puts a name in its place (see [Kenshi internals](kenshi_internals.md#names)). Text after the token, such as `the Blooded` or the `^^` marks of UWE, stays out of the `Name`.
- A game name that a titled template does not match is a name that the player gave, so it is the whole `Name`.
- Rejected: a check for a generic name by lists of keywords. It found Barman in Barman Arleen, a name that the game gave, so the server added a second name, and it found hero in Theron, a name that the player gave.

The server adds no title to a game name. It sends `NPC_RENAME: <npc_id>|<Name>` through the pipe (`send_rename`), and the plugin puts the `Name` in place of the token of the template (`ShownName` in `plugin/main.cpp`). A rename therefore keeps the text that the game shows around the name: Barman Arleen with the `Name` Bob becomes Barman Bob, and Arleen the Blooded keeps "the Blooded".

- The plugin finds the NPC by its `npc_id`. For a `u:` ID, it compares the string ID of the template, because a generic NPC whose template is a canon character carries the `npc_id` of that character.
- The plugin renames only an NPC that the game has loaded. A save on the web app renames a loaded NPC at once. Each other NPC gets the new name at the next chat or banter that it takes part in.
- Outside the player's faction, the profile wins. Each chat or banter renames an NPC whose game name gives another `Name` than its profile (`sync_name`). The rename goes out before the LLM call, so the name changes in game before the reply. This also gives back a name that the game lost, for example after the load of an earlier save.
- The player can rename a squad member in game, so in the player's faction the game name wins, and the server stores it as the `Name`. Only the template name is not a rename by the player, because it shows that the game lost the name, so the server sends the `Name` to the game instead.
- A rename of a squad member in game reaches the profile at once. A hook on `Character::setName` notes each member of the player's faction whose name changes (`setName_hook` in `plugin/main.cpp`). The frame hook then posts its context to `/squad_rename`, and the server stores the game name (`sync_name`). The frame hook builds the context, because a rename can come in the middle of a game update.
- The faction of a banter NPC is its identity faction, so the plugin marks a squad member with `in_player_faction`.
- A name from `/name` in the chat window becomes the `Name` as the player typed it, and the server sends no rename for it. `/rename` stores a profile for an NPC that has none, so the campaign keeps the name when the game loses it. It relabels the dialogue by the stored `Name`, because a titled game name is not the name in the dialogue.
- The prompt and the dialogue history use the `Name`, and `campaign_db.rename_character` relabels the lines that the NPC spoke.
- The chat window keeps the name that its target had when the window opened, so a chat request can name its target by an old name. The server therefore takes the `Name` of the target from the `npc_id` in its context, and it counts a reply line that starts with the old name as a line of the target.
- The server drops a reply line that another NPC near the player speaks, by its game name or by its `Name`, because the two differ for an NPC with a title.

Only an NPC that the game shows by its template name gets a rolled name. It gets a given name from `server/data/defaults/names.json` for the sex of the NPC when a chat or banter first stores it in the campaign. In a chat, this covers the target, the squad member who speaks, and each NPC that overhears.

| Moment | Name in game |
|---|---|
| Before the NPC takes part in a chat or in banter | Starving Bandit |
| The first chat or banter that the NPC takes part in | Josh |

- The server rolls a name only when the campaign stores the profile. The campaign stores no profile named Someone or Unknown (`should_save_profile`), so a rolled name would live only in the game.
- A new given name differs from each `Name` of the campaign (`get_used_names`), so two recruits never share a name.
- Rejected: the template name as a title in front of a rolled name, such as Starving Bandit Josh. It needed a mark for each rolled name and a title drop at each recruit, and the Current Job tells what the NPC does.
- Rejected: a name for each generic NPC on sight. The plugin scanned the NPCs near the player every 2 s and replaced the name of each generic one, so the player lost the game name of an NPC before any chat with it.

### Current Job

The `CurrentJob` of a profile is a short phrase for what the NPC does in game now, for example Guarding a building (`server/chat/current_job.py`). The chat prompt and the bio prompt give it as `CURRENT JOB: ...` (`current_job_line`), and leave the line out when the profile has none.

| Rule, first match wins | `CurrentJob` |
|---|---|
| A hire or escort contract (`temporary_follower`) | Temporary follower of the player's faction |
| The NPC is in the player's faction | Member of the player's faction |
| A shopkeeper node among the squad jobs | Running a shop |
| Another trader (`is_trader`) | Trading |
| A squad job in `TABLE` | Its phrase, for example Patrolling the town |
| No squad job that `TABLE` knows, for example in a squad without an AI package | None: no line in the prompt, and Unknown on the web app |

- The plugin sends the squad jobs of the NPC as the names of KenshiLib's `TaskType` enum, with `is_trader` and `temporary_follower`, in the context of an NPC, in the `nearby` list of a chat, and in each NPC of a banter request (`RoleJson` in `plugin/game/Context.cpp`). It sends only the task types of its `ROLE_TASKS` list, and a test checks that the list and `TABLE` hold the same names.
- Mods rename AI packages, squads, and templates, but the task types belong to the engine (see [Kenshi internals](kenshi_internals.md#roles)), so one squad job gives one phrase in every mod list.
- `TABLE` puts a side task, such as a turret or a bar visit, after the jobs that it would otherwise hide, because many guard and town packages hold one.
- A hire contract comes before the player's faction, because a hired NPC follows the player without a recruit.
- The server updates the `CurrentJob` only when a chat, banter, or rename writes the record of the NPC (`get_character_data`).
- A value of None removes the key (`upsert_profile`), because the template validator takes only text and numbers as profile values.
- Campaign Canon shows the `CurrentJob` read-only, and Templates do not show it, because the game sets it. The text of a canon role, such as Noble of the United Cities, is the first sentence of the `Backstory`.
- Rejected: the template title as the job. A mod can rename a template, one template serves squads with different roles, and the title stayed after a recruit.
- Rejected: the name of the AI package or of the squad. Mods rename them, for example `(LB) Shop-24hr`.
- Rejected: the `NPC class` of the template. It has ten values, some templates have a wrong one, and the live NPC type always equals it.
- `job` in the context of one NPC holds the names of the permajobs of the NPC, joined with commas, or `None` (`GetDetailedContext` in `plugin/game/Context.cpp`). Permajobs are the jobs of the Jobs menu of the player's characters, so almost no NPC has one. The action tags of a routine add them (`ExecuteQueuedActions` in `plugin/game/GameActions.cpp`), and a dismissed recruit gets back the permajobs that it had before the recruit.
- The scene text gives the live permajobs as the current task of the NPC (`npc_text` in `server/chat/scene_text.py`). It tells a trader by `is_trader` or by "shopkeeper" in the live value.

### Current Location

The `CurrentLocation` of a profile tells where the NPC was at its last chat (`location_name` in `server/chat/scene_text.py`). Campaign Canon shows it read-only next to the Current Job.

| The NPC is | `CurrentLocation` |
|---|---|
| In a building of a town | Bar, The Hub |
| Outdoors in a town | The Hub |
| In a building outside the towns | Shack, Vain |
| Outdoors outside the towns | Wilderness, Vain |

- Only the full context of a chat target, a chat speaker, or a rename carries `building_name` (`GetDetailedContext` in `plugin/game/Context.cpp`). A banter or an overheard chat therefore does not update it.
- The zone, for example Vain, is the zone around the camera (`ZoneName` in `plugin/game/Context.cpp`), because the game gives no zone for each character, and a chat happens near the camera. The plugin reads the zone record at slot `0x10` of `WeatherSystem::ActiveRegion` (see [Kenshi internals](kenshi_internals.md#zones)), and sends no `zone_name` when the slot holds no zone record.
- The chat scene reads the building from the live context, not from the profile, so a building from an earlier chat never reaches the prompt. The NPC section says "You are in your shop, …" only to a trader, and "You are inside …" to anyone else (`building_text`). `in_shop` marks every NPC inside a shop or a bar, a customer too, so it does not make a trader.

### Provisional profiles

A character without a stored profile gets one rolled in code at its first meeting (`new_profile`, `server/chat/provisional_profile.py`), with no LLM call. At that point the LLM would know only the race, the faction, and the job, so a bio from it would be no better than the roll. A canon character keeps its canon profile.

| Kind | Profile |
|---|---|
| A person | Three personality traits from `server/data/defaults/personality_traits.json`, the highest tier first, one backstory from `backstories.json`, and one speech quirk from `speech_quirks.json` |
| A skeleton (`is_skeleton`) | The same, without the traits about food and lust, and with a backstory that fits a skeleton |
| An animal (`ANIMAL_RACES`) | One entry of `animal_personalities.json`, and no backstory or speech quirk. The roll is final, because a bio would give the animal a backstory and a speech quirk. |

- The traits are the 36 personality traits of the CK3 mod [More Personality Depth](https://steamcommunity.com/sharedfiles/filedetails/?id=3717989134), each in three tiers. A roll takes three traits that are not opposites, with tier 1 at 60%, tier 2 at 30%, and tier 3 at 10%, so an extreme trait is rare. SSR uses only the trait concepts and the tier names of the mod, and it writes its own text for Kenshi.
- A backstory tells a short story in three parts: the life that the character had, the event that changed it, and how that part of their life ended. It is in the past tense and says nothing about what the character does, wants, owes, or fears now. The roll does not know the job, so a present-day detail could contradict it, and the LLM brought an open goal into replies that did not ask about it. The bio prompt asks for a backstory of the same shape. Each backstory has `kinds`, as each trait has, because a story about a childhood or about food does not fit a skeleton.
- `speech_quirks.json` has 50 universal quirks that fit any race, and 25 quirks each for humans (Greenlander, Scorchlander), Shek, Hivers (any race name with "hive"), and skeletons (`is_skeleton`). A character rolls one quirk from the universal list and the list of its race together, so about one character in three gets a race quirk. A race with no list, such as a Fishman or a modded race, rolls from the universal list only. The race lists follow the speech of the race in the game dialogue, so that a human or a Hiver does not get a quirk that sounds like a machine.
- Each text uses "they" and no name, so a rename cannot make it wrong. The tests check that no text names an SSR Vanilla faction, race, location, or region, and that no text has a gendered pronoun.
- An animal personality describes temperament and tendencies that the animal shows where it stands, such as nudging someone, but never a movement, such as wandering off. The game moves the animal, so the player would see it stand still.
- The roll is seeded by the `npc_id`. Banter and a chat can meet a new NPC at the same moment, and both write its profile, so both must roll the same one.
- The texts are in English. The system prompt sets the reply language, so the replies follow the language setting.

The squad member who speaks in a chat gets a profile at its first chat too, as the target and each listener do. The listeners of a chat leave out the speaker, so without this step a character that only speaks would have no profile. The speaker also keeps the player's line and the reply in its own history, without the `(Overheard)` tag.

A profile is provisional while it holds `Interactions` (`campaign_db.PROVISIONAL`): the number of chat turns in which the NPC replied to the player. An overheard turn and banter do not count.

- Rejected: a separate `Provisional: true` key. The template validator, which the campaign editor also runs, takes only text and numbers as profile values.
- Rejected: a count from the dialogue history. A banter line has no tag, so it looks like a reply to the player, and a memory replaces the lines of a chat.

When the count reaches the Chats before a bio setting (`bio_interactions`, default 5), the LLM writes the full bio of the NPC (`generate_bio`). It runs after the reply, in a background thread, so the reply does not wait for a second LLM call. A setting of 0 writes a bio only on request. It never rewrites a full profile, because the player may have written that profile by hand.

Generate Bio in the editor (see [Web app](#web-app)) and in the Dialogue Library uses the same prompt through `write_bio`, which stores nothing, so the player reads the text before a save keeps it. In the Dialogue Library:

1. A window asks for the part to write and the instructions, as the web app does.
2. `/write_bio` returns the text.
3. A second window shows each part in an edit box. Keep sends the text to `/keep_bio`, and Discard drops it.

Edit Bio in the Dialogue Library skips the LLM. `/read_bio` returns the stored `Personality`, `Backstory`, and `SpeechQuirks` in the shape of the `/write_bio` reply, and the same edit window opens.

- `/keep_bio` writes only the parts whose text changed. A changed part ends the provisional state through `promote_profile`, as a save on Campaign Canon does. A Keep with no change writes nothing, so a provisional NPC still gets the bio of the chat threshold.
- The replies of `/write_bio` and `/read_bio` carry the active campaign, and Keep sends it back. `/keep_bio` refuses the text when that campaign is no longer active, because the same `npc_id` can name another character in another campaign.
- Each close of the window makes the pending reply stale (`CloseBioUI` in `plugin/ui/LibraryWindow.cpp`), because the player can close the window or open it for another NPC while a request runs.

- `prompt_profile_generation.txt` gets the name, the sex, the race, the faction, the job, the race lore, the current `Personality`, `Backstory`, and `SpeechQuirks`, the dialogue so far, and the player's instructions. The current texts carry the rolled traits of a provisional profile. The instructions come right after the task line, because a model that read them after the current texts kept the old text and ignored them. The prompt tells the LLM to drop each current trait, event, or quirk that conflicts with the instructions, and to keep the rest and everything that the NPC said. The instructions win over every other rule.
- The bio keeps each part as strong as it was, takes no speech quirk from the wording of the dialogue, and keeps a goal from the backstory out of the personality and the reason for the job. The chat replies follow the bio, so a bio that grows a quirk or a goal makes the next replies wordier or more fixed on that goal.
- `{parts}` names the parts to write. `write_bio` keeps only those parts of the reply, so a reply cannot change a part that the player did not ask for.
- For an animal, `generate_bio` writes only the `Personality`, so the animal keeps no backstory and no speech quirk.
- `promote_profile` writes `Personality`, `Backstory`, and `SpeechQuirks` and removes `Interactions` in one transaction. It writes nothing when the profile stopped being provisional during the call, for example after an edit on Campaign Canon. `generate_bio` also drops the bio when the campaign changed during the call, because the same `npc_id` can name another character in the new campaign.
- `PROFILES_IN_PROGRESS` stops two bios of one NPC from running together.
- After a failed call, the profile stays provisional, and the count stays at or above the threshold, so the next chat turn tries again.
- The bio takes effect at the next chat turn. The NPC block is in the system message, so that turn misses the prompt cache once.

### Campaign routes of the web app

| Route | Behavior |
|---|---|
| `GET /api/campaigns` | Each campaign, the templates for a new campaign, and the reason that the current campaign cannot open, or `null` |
| `POST /api/campaigns` | Create a campaign from a template, with no switch |
| `POST /api/campaigns/switch` | Make a campaign the current one. The name must be a folder that the campaign list shows, so a name such as `../x` cannot point outside `server/data/campaigns/`. |
| `POST /api/campaigns/delete` | Delete a campaign folder, with the same name check. Before it deletes the current campaign, it switches to the first other one. When no other campaign remains, the server has no current campaign (see [Campaign storage](#campaign-storage)). |
| `GET /api/campaign` | The active campaign: its events, its rumors, and its chat threads with their members, lines, and memories. A refused campaign gives status 409 with the reason. |
| `GET /api/campaign/canon` | The canon of the active campaign, each record with its `origin` and `updated_at`, and each character with the `current_faction` that a chat reported since the server started (`LIVE_CONTEXTS`), or `null`. A refused campaign gives status 409 with the reason. |
| `POST /api/campaign/records`, `.../records/delete` | Save or delete one canon record of the active campaign. A faction, character, race, location, or region with no ID is new. |
| `POST /api/campaign/characters/bio` | The LLM text of the full bio, or of one part, for the form of a character. It stores nothing (see [Provisional profiles](#provisional-profiles)). |
| `POST /api/campaign/rumors`, `.../rumors/delete` | Edit the rumors of the active campaign |
| `POST /api/campaign/memories`, `.../memories/delete` | Edit or delete a memory of the active campaign (see [Conversation memories](#conversation-memories)) |
| `POST /api/campaign/cull` | Delete the dialogue, events, rumors, thread members, and memories dated after the current game time, after the player loads an older save. It asks the running game for a report and refuses the cull without one (see [Game state](#game-state)), because without the game time day 0 would count as now and the cull would delete the whole history. |

- Each edit names the campaign that the page loaded. Another tab can switch the campaign while the page is open, so the server refuses an edit for another campaign instead of writing it into the active one.
- **Cull Future Data** in the SSR HUB posts to `POST /cull`, which does the same cull without the campaign check, because the game always means the active campaign. The plugin shows the result as a game message.
- The cull of the SSR HUB carries a report, and the server writes its events before the cull. The buffer can hold events from before the load of the older save, which are dated after the loaded game time, so the cull deletes them.
- The server writes no rumor until a player context gives it the game time, because the cull never deletes a line without a game time.
- An edit of a faction, a character, a race, a location, or a region carries the `updated_at` that the page loaded, and the server refuses it when the row changed after that, for example when the game renamed the player's faction. An edit without `updated_at` counts as stale. The name of the player's faction is not editable, because the next context would undo it.
- The web app offers no delete for the player's faction. The game reports the faction again, and the server then adds it back with an empty description, so a delete would only lose the description.
- A rumor edit replaces only the text of its `[RUMOR: ...]` tag and keeps its game time. Brackets in the text become parentheses, because the prompt reads the rumor up to the first `]`.

## World templates

A world template is a folder that describes a world. A new campaign copies every record except the manifest (see [Campaign canon](#campaign-canon)). A template holds no rumors and no dialogue, and a campaign cannot become a template, because play state never leaves its campaign.

| File | Content |
|---|---|
| `manifest.json` | `format_version`, `name`, `description`, `version`, `authors`, `credits` |
| `overview.txt` | The lore that goes into every prompt |
| `history.json` | The lore timeline: a list of `title` and `text`, in timeline order |
| `factions/<id>.json` | `game_id`, `name`, `aliases`, `major`, `fields`, `description` |
| `characters/<id>.json` | `game_id`, and a `profile` with the keys of a profile in the character store, such as `Name`, `Race`, `Faction`, and `Personality` |
| `races/<id>.json`, `locations/<id>.json`, `regions/<id>.json` | `name`, `aliases`, `fields`, `description`, and `children`: a list of `entry` and `weight` |

- The ID of a record is its file name without `.json`.
- `fields` holds the facts of a record, in the categories of its kind (see [Web app](#web-app)).
- A child names its entry as `<category>/<entity ID>`, for example `locations/bast`, not by name, because a location and a region can share a name, for example Bast.
- An entry holds no access rules, because what an NPC knows belongs to the character, not to the entry.

| Template | Location | Edits |
|---|---|---|
| SSR Vanilla | `server/data/templates/kenshi_ssr_vanilla/`, shipped | None. An update replaces it, so the player duplicates it first. |
| User templates | `server/data/user_templates/<name>/` | The web app, or by hand |

`server/store/world_template.py` reads, validates, and writes templates, and imports only the standard library.

- One validator runs before each write and each campaign creation. It rejects an unknown `format_version`, a `version` that is not text, a folder that the format does not name, a JSON file that does not parse, a faction or an entity without a name, a faction or a character without `game_id`, two factions or two characters with one `game_id`, a character without a `Name` in its profile, and a fact whose category is not one of its kind or whose value does not have the shape of its category. A child whose `entry` names no race, location, or region of the template is a warning.
- A faction binds to the game by `game_id`, the string ID of the faction in the game data, so a rename in game does not break the link. The IDs of the vanilla factions come from the `FACTION_PROBE` lines of an in-game test ([kenshi_internals.md](kenshi_internals.md#factions)).
- A route takes a template name, a record kind, a category, and a record ID, never a path. The category must be `races`, `locations`, or `regions`, and each other part must match a fixed pattern, so a request cannot write outside the template folders. A new record takes its ID from its name.
- A duplicate copies every file of the template, its credit and licence files included, so a derived template keeps its attribution.
- Players share a template as one JSON file that holds the manifest, the overview, the history, and each record by its ID. The file leaves out other files, such as licence files, so the `credits` of the manifest carry the attribution.
- An imported file can come from anyone, so each record ID must match the ID pattern before it becomes a file name, and the whole template must pass the validator before anything is written.
- A shared template carries text that the LLM reads, so it can steer NPCs against the player's intent. A template gets the same trust as a Kenshi mod, and the Templates page shows the authors and the credits of a file before an import.
- An import is stricter than the validator. It also rejects a key that the format does not name, at any level of the file, so a typo such as `descripton` cannot drop text without notice. The validator accepts such a key, because the editor keeps a key that someone added to a template folder by hand. An import also rejects two IDs in one section that differ only in case, because Windows would save them as one file.
- A new template name must differ from the name and the title of each other template, ignoring case, because the template list shows titles.
- An import and a duplicate write into a staging folder whose name starts with a dot, which the template list ignores, and then rename it, so a failure leaves no template behind. The staging folder makes a temporary file for each file unnecessary, which matters on a mounted drive, where each file operation takes milliseconds.

| Route | Behavior |
|---|---|
| `GET /api/templates` | The name, title, and record counts of each template |
| `GET /api/templates/<name>` | The whole template, with its errors and warnings |
| `POST /api/templates/<name>/records`, `.../records/delete` | Save or delete one record of a user template |
| `POST /api/templates/<name>/duplicate`, `.../delete` | Copy a template as a user template, or delete a user template |
| `POST /api/templates/<name>/characters/bio` | The same as `POST /api/campaign/characters/bio`, with the race and the faction from the template and no dialogue |
| `GET /api/templates/<name>/export` | The shared file of a template |
| `POST /api/templates/import` | Write a shared file as a new user template with the name that the player gives |

### SSR Vanilla

SSR writes the content of SSR Vanilla itself. Each fact comes from the game: its data files, which the Forgotten Construction Set (FCS) opens, its dialogue, and play. The Kenshi wiki can help to find a fact, but no text comes from the wiki or from Kayak. Their licence terms therefore do not apply, and the template carries no Kayak credit or terms file.

- A region is a zone of the game data (record type 95), such as Border Zone or Shem. Record type 28 is a ground texture set and type 99 is a soil type, so neither is a region. Six zones have no towns and almost no data, so the template leaves them out: Akakus, Central, Desert, Empire, Rim Sands, and The Desert.
- A location is a town of the game data (record type 13). The game data does not say which zone holds a town, so the zone comes from the town infobox of the wiki, joined to the game data on the string ID. A camp that a zone places at random, a nest, is not a location.
- The facts and the descriptions describe the start of a game, because a new campaign does not know which world states changed. The `factions` and `animals` of a region therefore leave out each squad whose world state does not hold at the start of a game, such as the death of a leader. A world state tests whether an NPC is dead, alive, or imprisoned, so a gate on "All Slave Masters are not alive" being false holds at the start, and a gate on "Tinfist is not alive" being true does not.
- SSR Vanilla has a record for each vanilla faction that a source describes. It leaves out the factions of wild animals, the owners of ruins, and Nameless, the player's starting faction.
- Spiders, Gutters, and Old Machines are creature factions, but each has a record, because Bugmaster, No-Face, and the Spider Foreman belong to them. A `Faction` that names no faction of the template shows as Unknown in the editor, and a save writes Unknown. The `factions` of a region leave these three out, because its `animals` name their creatures.
- SSR Vanilla also holds the factions and the unique characters of Universal Wasteland Expansion (UWE). They bind by the `game_id` of a UWE record, which a game without UWE never reports, so they change nothing there. The overview, the history, and the entities do not bind by `game_id`, so they hold only facts that are true with and without UWE. Where UWE changes a fact of a vanilla record, for example the race of Bugmaster, the vanilla record sets that field to `Unknown`, so the game fills it (see [Characters](#characters)).
- The `OriginFaction` of an SSR Vanilla character is the character's own faction in the game data. A character without one, which takes its faction from the squad that spawns it, has its `Faction` there.
- A character text that no source supports stays blank, and no text says that its data is missing. The system prompt tells the LLM what a blank field means, so a note such as "his past is unknown" would only take tokens, and the LLM could read it as a trait.

## Logging

The plugin and the server write their logs in the same format, so one tool can read both files and merge them by time:

```
2026-10-02 22:54:01,123 - INFO - SYSTEM: Server starting on port 5000.
```

- Each record is one line. A line break in a message is written as `\n`. On the server, only a traceback continues on the lines after its record.
- The tag after the level names the component, for example `CHAT`, `PIPE`, or `EVENT`. It never names the severity.

| Level | Use |
|---|---|
| DEBUG | Game events, pipe traffic, route traces, prompts, full replies, and other content |
| INFO | Start-up, configuration, campaign changes, one summary line for each LLM call, and two lines for each chat: who hears it, then the player's line, the NPC's reply, and the time that the whole chat took, so a log shows what was said at every level |
| WARN | A retry, a fallback, missing data, or another problem that the code handles |
| ERROR | A failure: the action, the request, or the call did not happen |

`LogLevel` in the INI sets the lowest level that both sides write. The default is `INFO`. The plugin reads the INI at start, and a change on the web app's Settings page reaches the plugin as `SET_CONFIG: g_logLevel` (see [Settings](#settings)).

| File | Writer | Contents | Size |
|---|---|---|---|
| `SentientSands_SDK.log` in the Kenshi folder | Plugin | The log of the current game. At each game start, the plugin renames the log of the previous game to `SentientSands_SDK.old.log`. | One game |
| `server/logs/server.log` | Server | The server log | Rotated at 512 KB, with 3 backups |
| `server/logs/llm.log` | Server | Each prompt and reply of each LLM task, with its line breaks. The server writes it only at `DEBUG`. | Rotated at 2 MB, with 1 backup |

- The plugin keeps its log file open for the whole game and flushes each line, so the lines before a crash reach the file.
- `LogGameEvent` runs on the game thread for each attack, so it checks the level before it builds its message.
- The events of a campaign are in its database, not in a log file.

## Server state

| Location | Contents |
|---|---|
| `server/data/campaigns/<name>/` | One campaign: `campaign.db` (see [Campaign storage](#campaign-storage)). |
| `server/logs/` | `server.log` and `llm.log` (see [Logging](#logging)). |
| `server/config/prompts/` | The player's prompt overrides and `base_hashes.json` (see [Prompts](#prompts)). The release does not ship it, so an update keeps the overrides. |
| `server/data/user_templates/` | The player's world templates (see [World templates](#world-templates)). The release does not ship it, so an update keeps them. |
| `server/config/llm_config.json` | The LLM providers with the player's API keys, the profiles, and the routes (see [LLM routing](#llm-routing)). The release does not ship it, so an update keeps the keys. |
