# Proposal: Web App for Configuration and Data Editing

Status: Draft for review

## 1. Summary

The Python server gets a browser front end. It runs in the same Flask process on the same address (`127.0.0.1:5000`), so the mod gets no new process and no new port.

The web app has three jobs:

1. It opens in the default browser when Kenshi starts.
2. It holds all configuration: LLM providers and models, the gameplay settings that the in-game AI Settings window holds today, and the player profile that the Profile Editor holds today. A later phase adds LLM profiles and per-task routing with fallback chains.
3. It edits the SQLite knowledge store from [proposal_sqlite_knowledge_store.md](proposal_sqlite_knowledge_store.md) through domain editors.

The configuration moves to the web app first, on the files that hold it today. The AI Settings and Profile Editor windows go after that, so each setting always has a place where the player can change it. The in-game GUI then keeps only what the player needs during play: the chat window, the Dialogue Library, the World Event Log, the Campaign Manager, and the welcome popup.

## 2. Current state

These facts come from the code. They set the constraints for the design.

| Area | Current behavior |
|---|---|
| Server | Flask on `127.0.0.1:5000` with `threaded=True` (`server/scripts/kenshi_llm_server.py`, end of file). No route serves `/`. |
| Model selection | One global model key, `CURRENT_MODEL_KEY`. Every LLM call goes through `call_llm`, which looks up that key in `models.json`. |
| LLM call sites | `chat`, `ambient_event`, `generate_character_profile`, `generate_batch_profiles`, `regenerate_profile_route`, `generate_global_narrative_thread`. They use different `max_tokens` and `temperature` values. |
| Retries | `call_llm` tries the same model three times with a 120 s request timeout each. |
| Plugin wait | `PostToPythonWithResponse` stops waiting after 60 s (`plugin/core/Comm.cpp:101`). |
| In-game settings | `SettingsWindow` holds provider, model, test, restart, radii, radiant timer and toggle, event count, event timer, dialogue delay, bubble life, chat key, and language. It also has a button that opens `server/config` in Explorer, which is the only in-game path to the API keys and the model list. |
| Player profile | `ProfileEditorWindow` reads and writes the player backstory and the faction description through `/player_profile`. The server keeps them in `character_bio.txt` and `player_faction_description.txt` in the active campaign. |
| Settings storage | `SentientSands_Config.ini`, which the release ships. Both the plugin (`SavePluginConfig`, `plugin/core/Utils.cpp:248`) and the server (`_save_settings_raw`) write it. |
| API keys | `server/config/providers.json`. The server copies it from `default_providers.json` on first start, and the release does not ship it. |
| Model list | `server/config/models.json`, which the release ships. |
| Translations | `ApplyUITranslation` (`plugin/ui/SettingsWindow.cpp:387`) loads the UI translation table. `PopulateSettingsUI` calls it, and also fills the Campaign Manager. The startup fetch (`WelcomeResponseThread`) and the AI Settings window both go through `PopulateSettingsUI`. |
| Request checks | The server rejects requests with a foreign `Host` or `Origin` header (`server/scripts/request_guard.py`). `/test_llm` accepts only POST. |

### 2.1 Known problems

These problems exist in the current code. The plan fixes each one in the phase named here.

| Problem | Fix |
|---|---|
| A slow LLM call can outlive the plugin's 60 s wait. The plugin then loses the reply, and the second and third attempts in `call_llm` cannot reach it. | W4: the route deadline (section 7.3) |
| The plugin and the server write the INI with no lock between them, so one write can undo the other. | W3: the server as the only writer (section 8.2) |
| The plugin reads `GlobalEventsCount` into `g_worldEventIntervalDays`, which nothing in the plugin uses, and `SavePluginConfig` writes it back. The welcome popup's Close button calls `SavePluginConfig`, so it puts back the value from game start over a value that the player saved since. | W3: the server as the only writer (section 8.2) |
| The release ships `models.json`, so an update overwrites a player's edited model list. | W2 (section 6.3) |
| The release ships the INI, so an update resets the player's gameplay settings and current model. | Open question 1 |
| The plugin, the server, and the shipped INI disagree on defaults (table below). A default applies only when the INI has no value, so the defaults must agree before the INI stops shipping. | W3 |
| The shipped INI holds `ProximityRadius` and `DialogueSpeedSeconds`, which nothing reads. The readers use `TalkRadius` and `DialogueSpeed`. | W3 |

| INI key | Plugin default | Server default | Shipped INI |
|---|---|---|---|
| `TalkRadius` | 40 | 100 | 100 |
| `YellRadius` | 100 | 200 | 200 |
| `GlobalEventsCount` | 10 | 5 | 10 |
| `SynthesisIntervalMinutes` | Not read | 15 | 5 |

## 3. Goals and non-goals

### Goals

1. One process and one port for the plugin API and the web app.
2. The browser opens once when Kenshi starts, and the player can turn this off.
3. Per-task LLM routing with an ordered fallback chain of LLM profiles.
4. A configuration change applies at once, with no server or game restart.
5. Domain editors for the SQLite store that keep its derived tables consistent.
6. A lean in-game GUI that holds only what play needs.
7. Player configuration survives a release update.

### Non-goals

- Access from another device. The server stays bound to `127.0.0.1`.
- User accounts or login.
- A frontend build step, npm packages, or assets from a CDN.
- Raw SQL editing or a generic table editor.
- Editing a campaign other than the active one.

## 4. Architecture

```
Kenshi + SentientSands.dll
   |  HTTP POST (plugin routes, unchanged)       ^  named pipe (SET_CONFIG, ...)
   v                                             |
Flask server, 127.0.0.1:5000 ---------------------
   |-- /chat, /settings, ...    plugin API, which the web app also uses
   |-- /                        web app shell
   |-- /web/<file>              static HTML, CSS, JS
   |-- /api/...                 JSON API for the web app
   |
   |-- config_store.py          providers.json and models.json
   |-- llm_router.py            profiles, routes, fallback (W4)
   |-- sentient_db/             SQLite store (separate proposal)

Default browser  -->  http://127.0.0.1:5000/
```

### 4.1 Code layout

| Path | Contents |
|---|---|
| `server/web/` | Static files for the web app: plain HTML, CSS, and JavaScript modules. Vendored, so the web app works offline. `scripts/package_release.py` must add it to `SERVER_DIRS`, or the release ships no web app. |
| `server/scripts/web_api.py` | A Flask blueprint for `/api/...`. |
| `server/scripts/browser_launch.py` | The wait for the server port and the browser open from section 5. |
| `server/scripts/config_store.py` | Reads and writes `providers.json` and `models.json`: atomic saves, API key masking, and reference checks (section 6.3). |
| `server/scripts/llm_router.py` | LLM configuration, the fallback chain, and the request deadline (W4). |
| `server/user/` | Player-owned files that the release does not ship (W4). Git ignores this folder. |

New modules must not import `kenshi_llm_server`. The server runs as `__main__`, so an import of `kenshi_llm_server` loads a second copy of the module, with its own globals and its own background threads. The main module registers the blueprint and passes in what the blueprint needs.

`browser_launch.py` and `config_store.py` use only the standard library. `llm_router.py` takes the HTTP call as a parameter. Their logic can then run under stdlib `unittest` in the dev container, which has no Flask and no `requests`.

### 4.2 Request security

The server already rejects requests from other sites ([architecture.md](../info/architecture.md#runtime-flow)). The web app depends on this check. Without it, a page on any site could point a provider's base URL at its own server, and the next LLM call would send the API key there. The web app's own requests pass, because they come from `http://127.0.0.1:5000`.

A GET route in `/api/` must not change state. A page on another site can send a GET with no `Origin` header, for example through an image tag, so the Origin check does not stop it.

The API never returns a stored API key. A read returns only the last four characters. A save with an empty key field keeps the stored key.

## 5. Opening the browser on Kenshi start

The plugin decides when Kenshi starts, because only the plugin knows that. The server decides when it can accept connections.

1. `LoadPluginConfig` reads `OpenWebPanelOnStart` from the INI. The default is `1`, and the shipped INI holds `1`. The plugin only reads this key. The server writes it when the player changes it on the Settings page (W2).
2. On the first server start in a game session, `StartPythonServer` (`plugin/core/Utils.cpp`) adds `--open-browser` to the command line if `OpenWebPanelOnStart` is `1`.
3. A server restart from the in-game launcher does not add the flag, so the player does not get a second tab.
4. With the flag, the server waits until its port accepts connections, then calls `webbrowser.open("http://127.0.0.1:5000/")`. An earlier call shows a connection error page. If the port does not accept connections within 30 s, the server opens no browser.
5. A server that runs from the repo opens no browser unless the developer passes the flag.

In W1, the page shows the server status, the active campaign, and the current model. W2 adds the configuration pages.

Risk: the browser takes focus. Kenshi in exclusive fullscreen can minimize when it loses focus. The INI key and the web app's Settings page let the player turn auto-open off. The in-game launcher always has an "Open Web Panel" button, which opens the same URL through `ShellExecute`.

## 6. Configuration on the current files

W2 moves all configuration into the web app. The web app edits each value in the file that holds it today. The only storage change is that the release stops shipping `models.json` (section 6.3). W4 later moves the LLM part to `server/user/llm_config.json`.

### 6.1 Pages

| Page | Fields | Storage | Takes effect |
|---|---|---|---|
| Settings | Talk, yell, and radiant radii; radiant conversations on or off; radiant delay; world event count; synthesis interval; dialogue speed; speech bubble life; language; chat hotkey; welcome popup on start; web app on start | `SentientSands_Config.ini` | At once. The server sends the plugin's values through `SET_CONFIG`. "Web app on start" applies at the next game start. |
| LLM | Providers: name, base URL, API key, and the Player2 game key. Models: name, provider, and model ID. The current model. A Test button. | `server/config/providers.json`, `server/config/models.json`, and `CurrentModel` in the INI | At once, for the next LLM call. |
| Player profile | Player backstory and faction description | `character_bio.txt` and `player_faction_description.txt` in the active campaign | At the next prompt. |

These pages hold every field of the AI Settings and Profile Editor windows. The LLM page replaces the button that opens `server/config` in Explorer.

### 6.2 Routes

The Settings page and the current model use `/settings`, and the Player profile page uses `/player_profile`. The plugin uses the same two routes today. They already write the files and send changes to the plugin, so a second route for the same writes would duplicate that logic. W2 extends `/settings`:

1. The POST accepts `chat_hotkey`, `enable_welcome`, and `open_web_panel_on_start`, and the GET returns them. `INI_KEY_MAP` gets `ChatHotkey` and `OpenWebPanelOnStart`.
2. A change to the chat hotkey, the language, or the welcome popup goes to the plugin through `SET_CONFIG`, as a change to the radii does today.

The Test button uses `/test_llm`, which tests the current model.

Providers and models use new routes in `web_api.py`:

| Route | Method | Effect |
|---|---|---|
| `/api/providers` | GET | Returns every provider, with each API key masked. |
| `/api/providers` | POST | Adds or changes one provider. |
| `/api/providers/<name>` | DELETE | Deletes one provider. |
| `/api/models` | GET | Returns every model. |
| `/api/models` | POST | Adds or changes one model. |
| `/api/models/<name>` | DELETE | Deletes one model. |

The main module gives the blueprint the two file paths, a function that returns the current model, and `load_configs`.

### 6.3 Rules for providers and models

1. The API never returns a stored API key (section 4.2).
2. `config_store.py` writes each file to a temporary name and then renames it, so a crash during a save cannot leave a half-written key file.
3. After a save, the server calls `load_configs`, so the next LLM call uses the change.
4. The API rejects a model whose provider does not exist, the deletion of a provider that a model uses, and the deletion of the current model.
5. The release ships the model list as `server/config/default_models.json`. On a start without `models.json`, the server copies it, as it does for `providers.json` today. Git and the release leave out `models.json`, so an update keeps the player's model list. An install from an earlier release keeps its `models.json`, because the new zip does not contain one.

### 6.4 Plugin changes

1. `SET_CONFIG` gets `g_chatHotkey`, `g_language`, and `g_enableWelcome`. The web app offers only the hotkeys that `SetHotkeyFromString` can parse.
2. After a `g_language` change, the plugin fetches the translation table again on a worker thread and hands the result to the game thread through `g_messageQueue`, as the threading rule in [architecture.md](../info/architecture.md#threading) requires.

During W2, `SavePluginConfig` still writes the INI. It writes the plugin's values, which `SET_CONFIG` keeps equal to the server's values, so it undoes no web change except through the `GlobalEventsCount` problem from section 2.1. W3 removes `SavePluginConfig`.

## 7. LLM routing

W4 replaces the single current model with per-task routes. Its LLM page and routes replace the W2 LLM page and the `/api/providers` and `/api/models` routes.

### 7.1 Model

| Object | Fields | Role |
|---|---|---|
| Provider | name, type (`openai` or `player2`), base URL, API key | One endpoint and its credentials. The type selects provider-specific auth, such as the Player2 session key refresh in `call_llm`. Today that logic keys on the provider name. |
| Profile | name, provider, model, timeout, extra request parameters (JSON object) | One model on one provider. Several tasks can share a profile. |
| Route | task, ordered list of profiles, `max_tokens`, `temperature`, deadline | What a task asks for and which profiles serve it. |

Sampling values sit on the route, because the output length and creativity that a task needs do not depend on the model. Extra request parameters on the profile hold model-specific options. The request body is built in this order, and a later step overrides an earlier one:

1. `model` and `messages`.
2. The route's `max_tokens` and `temperature`.
3. The profile's extra request parameters.

### 7.2 Tasks

| Task | Call sites | Plugin waits | Default `max_tokens` / `temperature` |
|---|---|---|---|
| `chat` | `chat` | Yes | 2048 / 0.8 |
| `ambient` | `ambient_event` | Yes | 2048 / 0.8 |
| `profile` | `generate_character_profile`, `regenerate_profile_route` | Yes | 1500 / 0.7 |
| `profile_batch` | `generate_batch_profiles` | Yes | 1500 / 0.7 |
| `synthesis` | `generate_global_narrative_thread` | Only through `/synthesize` | 2048 / 0.8 |

The defaults are the values that the call sites pass today. `generate_character_profile` passes 600 today. The `profile` route uses 1500, the value of `regenerate_profile_route`, because `max_tokens` is only a cap.

### 7.3 Fallback

The router replaces the three-attempt retry loop in `call_llm`.

1. The router tries the profiles of the route in order. Each profile gets one attempt. A player who wants a retry lists the same profile twice.
2. The router moves to the next profile after a transport error, a timeout, a non-2xx status, or an empty completion.
3. Each attempt gets the smaller of the profile's timeout and the time left before the route's deadline.
4. The deadline for a task that the plugin waits on defaults to 55 s. This keeps the whole chain inside the plugin's 60 s wait.
5. The log records which profile served the request and why each earlier profile failed.

### 7.4 Storage and migration

The server keeps the LLM configuration in `server/user/llm_config.json`. It writes the file to a temporary name and then renames it, so a crash during a save cannot leave a half-written key file. A save applies at once in memory.

On the first start without `server/user/llm_config.json`, the server builds it:

1. One provider from each entry of `server/config/providers.json`, keys included.
2. One profile from each entry of `models.json`.
3. One route for each task, with the old `CurrentModel` profile as the only entry and the defaults from section 7.2.

This reproduces the behavior before W4. W2 keeps `providers.json` and `models.json` out of the release, so the migration finds the player's keys and model list after an update.

`visual_debugger.py` reads `/models` and posts `current_model` to `/settings` to switch the model, so the debugger moves to routes or drops its model switch.

## 8. Lean in-game GUI

W3 removes the in-game windows whose fields moved to the web app in W2.

### 8.1 In-game windows

| Window | After the change |
|---|---|
| Chat | Stays. |
| Launcher (AI panel) | Stays. The "AI Settings" and "Profile Editor" buttons go. W1 adds "Open Web Panel", and W3 adds "Restart Server". Restart stays in game because the web app cannot restart a server that does not answer. |
| Dialogue Library | Stays. |
| World Event Log | Stays. |
| Campaign Manager | Stays. |
| Welcome popup | Stays. Its "Show on Startup" toggle posts to `/settings` instead of writing the INI. |
| AI Settings | Goes. Its fields moved to the web app's Settings and LLM pages in W2. |
| Profile Editor | Goes. The player backstory and faction description moved to the web app in W2, where long text is easier to paste and edit. |

"Restart Server" starts a new server process, as the RESTART button in AI Settings does today. The new process first ends any process that listens on port 5000 (`kill_old_servers`), so the button also replaces a server that runs but does not answer.

### 8.2 Settings ownership

The server becomes the only writer of `SentientSands_Config.ini`. The plugin reads the INI at start, because it starts before the server, and after that it takes changes only through the pipe. This removes the unlocked double write and the `GlobalEventsCount` overwrite from section 2.1.

The plugin gets these changes:

1. `SavePluginConfig` and its callers go. `LoadPluginConfig` stops reading `GlobalEventsCount`.
2. `PopulateSettingsUI` also applies the translation table and fills the Campaign Manager, so those parts move out of `SettingsWindow.cpp` before the file goes.
3. The defaults of the plugin and the server agree, and the shipped INI holds no key that nothing reads (section 2.1).

## 9. Data editor

The data editor depends on phases 1 and 2 of the SQLite proposal. Until then, the web app edits the player profile over the current per-campaign text files (section 6.1).

### 9.1 Scope

The editor works on the template database and the active campaign database. Campaign switching stays in the in-game Campaign Manager. The web app shows the name of the active campaign and reloads its data when the campaign changes.

| Page | Edits |
|---|---|
| Entities | Search and filter by category. Fields, aliases, children with weights, and access rules. |
| NPCs | Profile, dialogue history, and stats of the active campaign. |
| World events | The event history of the active campaign. |
| Player profile | Player backstory and faction description. |

### 9.2 Consistency

- The API writes only through `sentient_db` functions, never through SQL built in a route. The `link` table and the `entity_fts` index derive from fields and aliases ([SQLite proposal, section 6](proposal_sqlite_knowledge_store.md#6-data-model)), and only `sentient_db` keeps them in step.
- An edit to the template becomes a patch ([SQLite proposal, section 7.2](proposal_sqlite_knowledge_store.md#72-step-2-local-patch-layer)), so a re-import of upstream data keeps it. An edit to a campaign writes the campaign database directly.
- The game changes the same records during play, for example "Regen Bio" in the Dialogue Library. Each editable record carries `updated_at`, and a save with an older value is rejected so that the web app reloads the record. The `entity` table needs this column added.
- Each request thread opens its own SQLite connection, with WAL mode and a `busy_timeout`. A web save then waits for a game write in progress instead of failing.

## 10. Phases

| Phase | Deliverable | Depends on | Acceptance criteria |
|---|---|---|---|
| W1. Shell and auto-open | `/` serves the web app; `server/web/` in the release; `--open-browser` and `OpenWebPanelOnStart`; "Open Web Panel" in the launcher | None | The browser opens once on Kenshi start. It does not open on an in-game restart or with `OpenWebPanelOnStart` at `0`. All plugin routes still work. |
| W2. Configuration | The Settings, LLM, and Player profile pages (section 6.1); `config_store.py` and the `/api` routes; the new `/settings` keys and `SET_CONFIG` keys; `default_models.json` | W1 | Each field of the AI Settings and Profile Editor windows can be changed in the web app and takes effect without a restart. No response contains a stored API key. The keys and the model list survive a release update. |
| W3. Lean in-game GUI | The AI Settings and Profile Editor windows removed; "Restart Server" in the launcher; the server as the only INI writer; aligned defaults and no unread INI keys (section 2.1) | W2 | The launcher shows only the windows from section 8.1. A web change survives the welcome popup's Close button. Without an INI, the plugin and the server start with the same values. |
| W4. LLM routing | Profiles and routes pages; `llm_router.py`; `server/user/llm_config.json` and its migration; a test button per profile | W2 | A migrated install sends every task to the old current model. A failing first profile falls through to the next inside the deadline. Keys survive a release update. |
| W5. Data editor | The pages from section 9.1 on the SQLite store | SQLite phase 2 | An entity edit appears in the next prompt that retrieves it. A stale save is rejected. A search finds a renamed entity. |

W1 to W4 do not need the SQLite store. They can run before or alongside SQLite phases 0 and 1.

## 11. Verification

- `browser_launch.py`: a unit test of the port wait against a local listening socket, and of the 30 s limit. It runs in the dev container.
- `config_store.py`: unit tests for the key masking, the save with an empty key, the reference checks, and the atomic write. They run in the dev container.
- `llm_router.py`: unit tests with a fake HTTP call, for chain order, the fall-through conditions, and the deadline. They run in the dev container.
- Release update: an install from an earlier release, upgraded with a new release zip, keeps its `providers.json` and `models.json`. After W4, it routes every task to the old current model.
- Plugin: the dev container cannot build the plugin, so a Windows build checks the launcher, the new `SET_CONFIG` keys, the hotkey and language changes, and the auto-open flag in game.

## 12. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| The browser takes focus from fullscreen Kenshi | The game minimizes at start | INI key and Settings page toggle; the flag only on the first start |
| A malicious page sends requests to the server | Stolen API key or changed settings | Host and Origin checks on every route |
| A fallback chain outlives the plugin's wait | The player gets no reply | Route deadline under 60 s |
| A web edit and a game write hit the same record | One change is lost without notice | `updated_at` check; `busy_timeout` |
| A release update overwrites player files | Lost keys or model list | `providers.json` and `models.json` not shipped (W2); `server/user/` not shipped (W4) |
| A player who has a `models.json` does not get the default models of a later release | A new model needs a manual add | The LLM page adds a model without a file edit |

## 13. Open questions

1. Should the release stop shipping `SentientSands_Config.ini`, so that an update keeps the player's gameplay settings and current model? The defaults in section 2.1 must agree first.
