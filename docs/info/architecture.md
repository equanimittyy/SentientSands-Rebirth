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
| `server/scripts/` | The Flask server (`kenshi_llm_server.py`), the campaign database (`campaign_db.py`), the world templates (`world_template.py`), the request checks (`request_guard.py`), the browser auto-open (`browser_launch.py`), the LLM configuration (`llm_config.py`) and fallback chain (`llm_router.py`), the prompt overrides and placeholders (`prompt_store.py`), the log files and the log level (`log_setup.py`), and a Tkinter debug tool (`visual_debugger.py`). |
| `server/web/` | The web app: plain HTML, CSS, JavaScript, fonts, and images, which the server serves at `http://127.0.0.1:5000/`. |
| `server/tests/` | Unit tests that run with the standard library only. See [development.md](development.md#tests). |
| `server/config/` | The default providers and models that seed the LLM configuration, and the name and localization JSON. |
| `server/prompts/` | The system prompts, and the default player profile of a new campaign. |
| `server/world_templates/` | The shipped world templates. See [World templates](#world-templates). |
| `mod/` | The files at the root of the installed mod folder: `mod.info`, `SentientSandsRebirth.mod`, and `RE_Kenshi.json`. A server that runs from the repo also writes its `SentientSands_Config.ini` here, which git ignores. |
| `scripts/` | Release tooling. See [development.md](development.md#release). |
| `package_release.cmd` | A Windows menu that builds the plugin, runs `scripts/package_release.py`, or does both. |

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
    scripts/  config/  prompts/  web/  world_templates/
    python/                  embedded runtime, added by scripts/package_release.py
    campaigns/  logs/  user/ created at runtime
```

- The plugin takes the mod root from the path of its own DLL (`startPlugin` in `plugin/main.cpp`). A Steam Workshop folder with a numeric name works for this reason.
- The plugin runs `server\python\python.exe server\scripts\kenshi_llm_server.py`. If the embedded runtime is missing, it falls back to `python` on `PATH` (`StartPythonServer` in `plugin/core/Utils.cpp`).
- The server takes its folders from its own script path. The server root is the parent of `scripts/`, and the mod root is the parent of the server root. When the server runs from this repo, it finds the INI in `mod/` instead (`resolve_mod_file` in `server/scripts/kenshi_llm_server.py`).

## Runtime flow

1. RE_Kenshi loads `SentientSands.dll` and calls `startPlugin`. The plugin installs its KenshiLib hooks and starts `MainThread`.
2. `MainThread` waits for `KenshiLib.dll`. Then it starts the pipe listener (`PipeThread`) and the name-assignment thread, loads the INI, and starts the server. After that, it posts the player's context to `/context` at most once every 5 seconds.
3. If `OpenWebPanelOnStart` in the INI is `1`, this first server start passes `--open-browser`. The server waits until its port accepts connections, and then 3 s more, so that a tab from an earlier start can reconnect. It opens the web app in the default browser only when no tab is open (see [Web app](#web-app)). A restart from the launcher does not pass the flag, so the player does not get a second tab.
4. The server listens on `127.0.0.1:5000`. The plugin sends HTTP POST requests to it through WinHTTP (`plugin/core/Comm.cpp`) for chat, history, settings, profiles, and events. The server rejects a request whose `Host` header is not `127.0.0.1:5000` or `localhost:5000`, or whose `Origin` header names another site (`server/scripts/request_guard.py`). This stops web pages in the player's browser from using the server. A new caller must use one of these two host names.
5. The server sends commands back through the named pipe `\\.\pipe\SentientSands`, which the plugin hosts. Examples are `SET_CONFIG`, `NOTIFY`, and `POPULATE_GENERIC`.
6. The server builds each prompt from the prompt files (see [Prompts](#prompts)) and the campaign state, then sends it down the route of its task (see [LLM routing](#llm-routing)).

## Threading

Background threads do not change game objects or MyGUI widgets. The pipe listener, the HTTP response threads, and the UI worker threads push text messages onto `g_messageQueue` under `g_msgMutex` (`plugin/core/Globals.h`). `playerUpdate_hook` runs on the game thread and drains the queue through `ProcessMessageQueue` (`plugin/main.cpp`). New code that produces results off the game thread must hand them over through this queue.

## Web app

The server serves `server/web/` at `/` and `/web/<file>`. The files are plain HTML, CSS, JavaScript modules, fonts, and images, with no build step, no npm packages, and no assets from a CDN, so the web app works offline and the release needs no extra tools.

The toggle at the top right switches between the light and the dark colours. The browser keeps the choice in `localStorage`, and without a stored choice the page follows the system setting. A small script in the page head sets the theme before the page paints, so a dark page never flashes light.

| Page | Route | Storage |
|---|---|---|
| Settings | `/settings`, `/settings/defaults` | `SentientSands_Config.ini` |
| Models | `/api/llm`, `/api/llm/test`, `/api/llm/models`, `/api/llm/reset` | `server/user/llm_config.json` |
| Prompts | `/api/prompts` | `server/user/prompts/` |
| Campaigns | `/api/campaigns`, `/api/campaign` (see [Campaign routes of the web app](#campaign-routes-of-the-web-app)) | `campaign.db` of each campaign |
| Editor | `/api/campaign/canon`, `/api/campaign/records` (see [Campaign canon](#campaign-canon)); `/api/templates` (see [World templates](#world-templates)) | `campaign.db` of the active campaign; `server/user/world_templates/` |

A GET route must not change state. A page on another site can send a GET with no `Origin` header, for example through an image tag, so the Origin check from step 4 of the runtime flow does not stop it. The presence stream below is the only exception, because EventSource sends only GET requests. A page on another site that holds the stream open can only stop a new tab from opening.

The server stops when the game closes, and it restarts when the player presses Restart Server, so an open tab can lose the server at any time. The web app reads `GET /context` every 3 s (`poll` in `server/web/app.js`). While its requests get no response, it shows a banner and disables its Save buttons, so the player keeps unsaved changes until the server is back. A page that did not load keeps its Save button disabled, and the web app loads it again when the server is back.

Each page tracks its unsaved changes and reports them with an `unsaved` DOM event (`reportUnsaved` in `server/web/api.js`). While a page has unsaved changes, its nav tab shows a dot, its Discard button loads the saved data again, and the browser asks the player before the tab closes.

Each tab holds `GET /web_panel/presence` open. This event stream sends a heartbeat every second, and the server counts the open streams. The server finds a closed tab only when a heartbeat write fails, so a tab counts as open for up to 2 s after it closes. The stream tells the browser to reconnect 1 s after it loses the server, so an open tab finds a restarted server within the 3 s that the auto-open waits.

**Open Web Panel** in the SSR HUB always opens the web app in a new tab of the default browser. The button does not check for an open tab. A version that brought the browser window of an open tab to the front left an empty box on the game screen in exclusive fullscreen.

Another tab can switch the campaign while a tab is open, so the poll also shows the active campaign. When the poll sees another campaign, it sends a `campaignchange` event, and the Campaigns page and the Campaign Canon subtab of the Editor load the new campaign unless they have unsaved changes.

The Campaigns and Editor pages hold many records. Save sends one request for each changed record, and a record that the server rejects keeps its draft and shows the reason. A delete takes effect at once, after a confirmation.

The Editor has two subtabs with the same record list and forms. Campaign Canon edits the canon of the active campaign, and Templates edits the world templates that new campaigns copy. The page holds the records of one subtab and one template at a time, so a switch with unsaved changes asks the player first. A shipped template is read-only, so the page offers a duplicate.

## Settings

The server is the only writer of `SentientSands_Config.ini`. The plugin reads the INI once at start, because it starts before the server. After that, it takes changes only through `SET_CONFIG` on the pipe. Two writers with no lock between them would undo each other's changes.

The release does not ship the INI, so an update keeps the player's settings. On the first start, the plugin reads no INI and uses the defaults in `LoadPluginConfig` (`plugin/core/Utils.cpp`). The server then writes the INI with `SETTINGS_DEFAULTS` (`server/scripts/kenshi_llm_server.py`). At each start, the server sends each value that the plugin holds through `SET_CONFIG` (`push_settings_to_plugin`), so the defaults of `LoadPluginConfig` apply only until the server is up. `OpenWebPanelOnStart` is the exception, because the plugin reads it before it starts the server, so its default in `LoadPluginConfig` must agree with `SETTINGS_DEFAULTS`.

The web app's Settings page posts its changes to `/settings`. The server writes the INI and sends each value that the plugin holds through `SET_CONFIG`. A language change sends the new translation table through the pipe as `APPLY_TRANSLATION`.

**Reset to defaults** on the Settings page reads `GET /settings/defaults` and fills the form without a save, so the player can review the values before the usual save sends them. The defaults have a route of their own and are not part of the `/settings` reply. The plugin reads that reply by searching for the first match of each key (`GetJsonValue` in `plugin/core/Utils.cpp`), so a nested copy of the same keys could give it a default instead of the setting.

The plugin re-creates its pipe instance after each message, so a message sent immediately after another can find no instance. `send_to_pipe` retries for 0.25 s for this reason. When the game does not run, each message therefore costs 0.25 s.

## Prompts

Each file in `server/prompts/` is a shipped default, and an update replaces it. The player's edit of a prompt is an override in `server/user/prompts/` under the same file name, so an update keeps it. `load_prompt_component` takes the override when it holds text, and the shipped file otherwise. The campaign folder holds no prompts.

The Prompts page of the web app reads `GET /api/prompts` and saves each changed prompt through `POST /api/prompts` (`server/scripts/prompt_store.py`).

- A route takes only the name of a shipped `.txt` file, never a path, so a request cannot write outside `server/user/prompts/`. The player profile file `character_bio.txt` is not a prompt, so the page does not list it.
- A save equal to the shipped text, or an empty save, deletes the override, so the prompt gets later default updates again. **Use default** and **Reset to defaults** fill the form with the shipped text, and the next save deletes the overrides.
- Each save of an override stores the SHA-256 of the shipped text in `server/user/prompts/base_hashes.json`. When an update changes the shipped text, the hash no longer matches, and the page marks the override. An override with no stored hash, for example one made by hand, is marked as unknown.
- An override and `base_hashes.json` are written to a temporary file and then renamed, as `llm_config.save` does.

A placeholder is a `{name}` in a prompt. `prompt_store.render` replaces each placeholder that its caller fills and leaves every other brace as text. A stray brace in an edited prompt therefore cannot fail the LLM call, as it could with `str.format`, and a JSON example in a prompt needs no escaped braces.

- A save is rejected when the override uses a placeholder that the shipped text does not have. A placeholder of the shipped text that the override leaves out gives a warning, because the prompt then loses that data.
- A hand-made override can still hold a wrong placeholder. `fill_prompt` then leaves it as text and logs a warning.
- Rejected: Jinja2. Flask already bundles it, but template logic lets one edit break the whole prompt, and a syntax error fails the call.

`prompt_system.txt` is the skeleton of the chat system prompt: its headings, the order of its sections, and the rules on what an NPC can see of the player. `build_system_prompt` fills it. A block that appears only with data, such as the events or the player faction description, keeps its heading in the code, because a placeholder has no conditions. The `{world_lore}` placeholder takes the overview of the campaign (see [Campaign storage](#campaign-storage)).

## LLM routing

Each LLM call names a task: `chat`, `ambient`, `profile`, `profile_batch`, or `synthesis`. `server/user/llm_config.json` holds four parts, and the web app's Models page edits all of them through `/api/llm`.

| Part | Contents |
|---|---|
| Providers | An OpenAI-compatible endpoint: type (`openai` or `player2`), base URL, API key, and the Player2 game key. |
| Profiles | One model on one provider, with a per-attempt timeout and extra request parameters. |
| Default profile | The profile that every route uses at the place of its `null` entry. |
| Routes | For each task, an ordered list of profiles, `max_tokens`, `temperature`, and a deadline. Each list holds `null` once, which stands for the default profile (`llm_config.route_profiles`), so a change of the default reaches every task. |

`llm_router.run_route` tries the profiles of the route in order, one attempt each. It moves to the next profile after an exception, a non-200 status, or an empty completion. Each attempt gets the smaller of the profile's timeout and the time left before the deadline. The default deadline is 55 s, because the plugin stops waiting for a reply after 60 s (`plugin/core/Comm.cpp`).

The request body starts with `model`, `messages`, and `top_p` 0.9. The route's `max_tokens` and `temperature` come next, and the profile's extra request parameters override both.

A Player2 provider uses a session key from the local Player2 app. On a 401, `send_completion` gets a new session key and tries the same profile once more.

`/api/llm` never returns a stored API key. It returns only whether a key is set. A key that starts with `YOUR_`, like the placeholders in `default_providers.json`, counts as not set. A save with an empty key field keeps the stored key, so the web app can send back what it received. A renamed provider sends its old name as `previous_name`, so it keeps its stored key (`llm_config.with_stored_keys`). The server writes the file to a temporary name and then renames it, so a crash during a save cannot leave a half-written key file.

A rejected save returns each error with the path of its field, for example `["profiles", "kimi", "model"]`, and the web app marks that field.

`POST /api/llm/test` tests the profile and the provider as the web app holds them, so the player can test before a save. `POST /api/llm/models` lists the model IDs of a provider in the same way, through the provider's OpenAI-compatible `GET /models`. Both fill an empty key field with the stored key only when the base URL is the saved one (`llm_config.provider_from_form`). A request with a mistyped base URL therefore cannot send the stored key to another host.

On a start without `llm_config.json`, the server builds it from `default_providers.json` and `default_models.json` in `server/config/`. Each task gets one route that holds only the `player2-default` profile.

**Reset to defaults** on the Models page posts to `/api/llm/reset`, which builds the same configuration and saves it at once. The page does not hold the stored keys, so the reset cannot fill the form for a later save as the Settings page does. The reset removes the providers and profiles that the player added, with their keys. A default provider keeps its stored key only when the stored base URL has the same host as the default one (`llm_config.reset`), so a key for a custom host does not go to the default host. A placeholder key of the defaults never replaces a stored key.

## Campaign storage

`server/scripts/campaign_db.py` keeps the NPC profiles, the dialogue, the canon, the event history, and the rumors of a campaign in one SQLite file, `campaign.db`, in the campaign folder. The plugin reaches this data only through the server's routes, which keep their request and response shapes. The player bio stays a text file in the campaign folder, `character_bio.txt` (`load_campaign_text`). A new campaign gets a copy of the shipped file of the same name in `server/prompts/`.

- Each write runs in one `BEGIN IMMEDIATE` transaction. A profile write merges only the keys that the caller passes, and the dialogue lines are rows of their own. A route that waits for the LLM must write only the keys that it changed, so that it cannot undo a change that another request made during the wait.
- `/chat` changes the Relation through `change_relation`, which adds the judgment to the stored value in one transaction. Two overlapping chats with the same NPC therefore keep both changes.
- A profile key that starts with `_` is not stored. Such a key describes only the copy of one request, for example `_transient` on a stand-in profile.
- Each operation opens a connection with a 5 s busy timeout and closes it. A campaign switch changes only the database path that `open_campaign` sets.
- The database uses the default rollback journal, not WAL. The campaign folder therefore has no `-wal` or `-shm` file, and a player can copy it while the server is idle.
- A storage ID is the NPC name with only its letters, digits, spaces, `_`, and `-`, and it ignores case.
- Each NPC keeps its newest 250 dialogue lines, and the campaign keeps its newest 500 events. An event that the table already holds is not added again.
- Favorites belong to each campaign.

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
| Character | `character` table; the profile as JSON | The game ID |
| Race, location, region | `entity` table, with `races`, `locations`, or `regions` as the category; the whole template record as JSON | The category and the entity ID |

- The chat prompt reads only the overview and the factions. No prompt reads the history, the characters, the races, the locations, or the regions yet, and chat takes NPC profiles only from the `npc` table.
- `origin` tells where a record came from: `template` (the copy at creation), `game` (a faction that a context reported), or `campaign` (added on the web app).
- A save checks the record with the template validator (`world_template.record_problems`), so a campaign record follows the same rules as a template record. The validator sees only one record, so the database refuses a second faction or character with the same game ID.
- The game ID of a faction or a character is its key in the campaign, so it cannot change after the record is added.

### Factions

Each campaign holds its own copy of the factions, keyed by the string ID of the faction in the game data. The prompt describes a faction from this copy: its name, its fields, and its description (`describe_faction`).

- The server finds a faction by the `factionID` of a context, or by name or alias when only a name is known, for example the origin faction in a profile. The name match ignores case and is exact, so Holy Nation Outlaws never takes the description of The Holy Nation.
- The loyalty note for members of a major world power reads the `major` flag.
- A faction that a context reports and the copy lacks gets a row with the name that the game gives and an empty description (`note_faction`). The plugin sends the name, or `Neutral`, as the ID of a faction with no string ID, and the server records no row for those.
- The player's faction is the row of the `factionID` of the player's context. Its name follows the game, because the player can rename the faction in game. Its description is the player faction block of the chat prompt, and an empty description leaves the block out.
- The server records each reported faction once per campaign in memory (`SEEN_FACTIONS`), because the plugin posts the player's context every 5 s.

### Campaign routes of the web app

| Route | Behavior |
|---|---|
| `GET /api/campaigns` | Each campaign, and the templates for a new campaign |
| `POST /api/campaigns` | Create a campaign from a template, with no switch |
| `POST /api/campaigns/switch` | Make a campaign the current one. The name must be a folder that the campaign list shows, so a name such as `../x` cannot point outside `server/campaigns/`. |
| `POST /api/campaigns/delete` | Delete a campaign folder, with the same name check. Before it deletes the current campaign, it switches to the first other one. When no other campaign remains, the server has no current campaign (see [Campaign storage](#campaign-storage)). |
| `GET /api/campaign` | The active campaign: its events and rumors. A refused campaign gives status 409 with the reason. |
| `GET /api/campaign/canon` | The canon of the active campaign, each record with its `origin` and `updated_at`. A refused campaign gives status 409 with the reason. |
| `POST /api/campaign/records`, `.../records/delete` | Save or delete one canon record of the active campaign. A faction, character, race, location, or region with no ID is new. |
| `POST /api/campaign/rumors`, `.../rumors/delete`, `.../events/delete` | Edit the rumors and events of the active campaign |
| `POST /api/campaign/cull` | Delete the dialogue, events, and rumors dated after the current game time, after the player loads an older save. It needs the player's context from the running game, because without it day 0 would count as now and the cull would delete the whole history. |

- Each edit names the campaign that the page loaded. Another tab can switch the campaign while the page is open, so the server refuses an edit for another campaign instead of writing it into the active one.
- **Cull Future Data** in the SSR HUB posts to `POST /cull`, which does the same cull without the campaign check, because the game always means the active campaign. The plugin shows the result as a game message.
- An edit of a faction, a character, a race, a location, or a region carries the `updated_at` that the page loaded, and the server refuses it when the row changed after that, for example when the game renamed the player's faction. An edit without `updated_at` counts as stale. The name of the player's faction is not editable, because the next context would undo it.
- The web app offers no delete for the player's faction. The game reports the faction again, and the server then adds it back with an empty description, so a delete would only lose the description.
- A rumor edit replaces only the text of its `[RUMOR: ...]` tag and keeps its game time. Brackets in the text become parentheses, because the prompt reads the rumor up to the first `]`.

## World templates

A world template is a folder that describes a world: `manifest.json` (format version, name, description, version, authors, credits), `overview.txt` (the lore that goes into every prompt), `history.json`, `factions/<id>.json`, `characters/<id>.json`, `races/<id>.json`, `locations/<id>.json`, and `regions/<id>.json`. The format is in [proposal_data_layers.md](../plans/proposal_data_layers.md#3-world-template-format). A new campaign copies every record except the manifest (see [Campaign canon](#campaign-canon)).

| Template | Location | Edits |
|---|---|---|
| SSR Vanilla | `server/world_templates/vanilla_kenshi/`, shipped | None. An update replaces it, so the player duplicates it first. |
| User templates | `server/user/world_templates/<name>/` | The web app, or by hand |

`server/scripts/world_template.py` reads, validates, and writes templates, and imports only the standard library.

- One validator runs before each write and each campaign creation. It rejects an unknown `format_version`, a `version` that is not text, a folder that the format does not name, a JSON file that does not parse, a faction or an entity without a name, a faction or a character without `game_id`, two factions or two characters with one `game_id`, and a character without a `Name` in its profile. A child that names no entity is a warning.
- A faction binds to the game by `game_id`, the string ID of the faction in the game data, so a rename in game does not break the link. The IDs of the vanilla factions come from the `FACTION_PROBE` lines of an in-game test ([kenshi_internals.md](kenshi_internals.md#factions)).
- SSR Vanilla also holds the factions and the unique characters of Universal Wasteland Expansion (UWE). They bind by the `game_id` of a UWE record, which a game without UWE never reports, so they change nothing there. The overview, the history, and the entities do not bind by `game_id`, so they hold only facts that are true with and without UWE. Where UWE changes a fact of a vanilla record, for example the race of Bugmaster, the vanilla record leaves that field out.
- A route takes a template name, a record kind, a category, and a record ID, never a path. The category must be `races`, `locations`, or `regions`, and each other part must match a fixed pattern, so a request cannot write outside the template folders. A new record takes its ID from its name.
- A duplicate copies every file of the template, its credit and licence files included, so a derived template keeps its attribution.
- Players share a template as one JSON file that holds the manifest, the overview, the history, and each record by its ID. The file leaves out other files, such as licence files, so the `credits` of the manifest carry the attribution.
- An imported file can come from anyone, so each record ID must match the ID pattern before it becomes a file name, and the whole template must pass the validator before anything is written.
- An import is stricter than the validator. It also rejects a key that the format does not name, at any level of the file, so a typo such as `descripton` cannot drop text without notice. The validator accepts such a key, because the editor keeps a key that someone added to a template folder by hand. An import also rejects two IDs in one section that differ only in case, because Windows would save them as one file.
- A new template name must differ from the name and the title of each other template, ignoring case, because the template list shows titles.
- An import and a duplicate write into a staging folder whose name starts with a dot, which the template list ignores, and then rename it, so a failure leaves no template behind. The staging folder makes a temporary file for each file unnecessary, which matters on a mounted drive, where each file operation takes milliseconds.

| Route | Behavior |
|---|---|
| `GET /api/templates` | The name, title, and record counts of each template |
| `GET /api/templates/<name>` | The whole template, with its errors and warnings |
| `POST /api/templates/<name>/records`, `.../records/delete` | Save or delete one record of a user template |
| `POST /api/templates/<name>/duplicate`, `.../delete` | Copy a template as a user template, or delete a user template |
| `GET /api/templates/<name>/export` | The shared file of a template |
| `POST /api/templates/import` | Write a shared file as a new user template with the name that the player gives |

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
| INFO | Start-up, configuration, campaign changes, and one summary line for each chat and each LLM call |
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
- The events of a campaign are in its database, not in a log file. `visual_debugger.py` reads them from there.

## Server state

| Location | Contents |
|---|---|
| `server/campaigns/<name>/` | One campaign: `campaign.db` (see [Campaign storage](#campaign-storage)) and `character_bio.txt`. |
| `server/logs/` | `server.log` and `llm.log` (see [Logging](#logging)). |
| `server/user/prompts/` | The player's prompt overrides and `base_hashes.json` (see [Prompts](#prompts)). The release does not ship it, so an update keeps the overrides. |
| `server/user/world_templates/` | The player's world templates (see [World templates](#world-templates)). The release does not ship it, so an update keeps them. |
| `server/user/llm_config.json` | The LLM providers with the player's API keys, the profiles, and the routes (see [LLM routing](#llm-routing)). The release does not ship it, so an update keeps the keys. |
