# Proposal: Web App for Configuration and Data Editing

Status: Draft for review

## 1. Summary

The Python server gets a browser front end. It runs in the same Flask process on the same address (`127.0.0.1:5000`), so the mod gets no new process and no new port.

The web app has three jobs:

1. It opens in the default browser when Kenshi starts.
2. It holds all configuration: LLM providers, LLM profiles, per-task routing with fallback chains, and the gameplay settings that the in-game settings window holds today.
3. It edits the SQLite knowledge store from [proposal_sqlite_knowledge_store.md](proposal_sqlite_knowledge_store.md) through domain editors.

The in-game GUI keeps only what the player needs during play: the chat window, the Dialogue Library, the World Event Log, the Campaign Manager, and the welcome popup.

## 2. Current state

These facts come from the code. They set the constraints for the design.

| Area | Current behavior |
|---|---|
| Server | Flask on `127.0.0.1:5000` with `threaded=True` (`server/scripts/kenshi_llm_server.py`, end of file). No route serves `/`. |
| Model selection | One global model key, `CURRENT_MODEL_KEY`. Every LLM call goes through `call_llm`, which looks up that key in `models.json`. |
| LLM call sites | `chat`, `ambient_event`, `generate_character_profile`, `generate_batch_profiles`, `regenerate_profile_route`, `generate_global_narrative_thread`. They use different `max_tokens` and `temperature` values. |
| Retries | `call_llm` tries the same model three times with a 120 s request timeout each. |
| Plugin wait | `PostToPythonWithResponse` stops waiting after 60 s (`plugin/core/Comm.cpp:101`). A slow LLM call can outlive the plugin's wait, so the reply is lost. |
| In-game settings | `SettingsWindow` holds provider, model, test, restart, radii, radiant timer and toggle, event count, event timer, dialogue delay, bubble life, chat key, and language. |
| Settings storage | `SentientSands_Config.ini`. Both the plugin (`SavePluginConfig`, `plugin/core/Utils.cpp:248`) and the server (`_save_settings_raw`) write it, with no lock between them. |
| API keys | `server/config/providers.json`. The release zip ships this file, so unzipping an update over an install resets the player's keys. |
| Translations | The plugin loads the UI translation table in `PopulateSettingsUI` (`plugin/ui/SettingsWindow.cpp:539`), which also fills the Campaign Manager. |

## 3. Goals and non-goals

### Goals

1. One process and one port for the plugin API and the web app.
2. The browser opens once when Kenshi starts, and the player can turn this off.
3. Per-task LLM routing with an ordered fallback chain of LLM profiles.
4. A configuration change applies at once, with no server or game restart.
5. Domain editors for the SQLite store that keep its derived tables consistent.
6. A lean in-game GUI that holds only what play needs.
7. Player configuration, API keys included, survives a release update.

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
   |-- /chat, /settings, ...    plugin API (unchanged)
   |-- /                        web app shell
   |-- /web/<file>              static HTML, CSS, JS
   |-- /api/...                 JSON API for the web app
   |
   |-- llm_router.py            providers, profiles, routes, fallback
   |-- sentient_db/             SQLite store (separate proposal)

Default browser  -->  http://127.0.0.1:5000/
```

### 4.1 Code layout

| Path | Contents |
|---|---|
| `server/web/` | Static files for the web app: plain HTML, CSS, and JavaScript modules. Vendored, so the web app works offline. |
| `server/scripts/web_api.py` | A Flask blueprint for `/api/...`. |
| `server/scripts/llm_router.py` | LLM configuration, the fallback chain, and the request deadline. |
| `server/user/` | Player-owned files that the release does not ship. Git ignores this folder. |

New modules must not import `kenshi_llm_server`. The server runs as `__main__`, so an import of `kenshi_llm_server` loads a second copy of the module, with its own globals and its own background threads. The main module registers the blueprint and passes in what the blueprint needs.

`llm_router.py` takes the HTTP call as a parameter. Its fallback and deadline logic can then run under stdlib `unittest` in the dev container, which has no Flask and no `requests`.

### 4.2 Request security

Any web page that the player opens can send requests to `127.0.0.1:5000`. A cross-site form POST needs no CORS preflight, and DNS rebinding lets a page read the responses too. With the web app, such a request could point a provider's base URL at an attacker's server, and the next LLM call would then send the API key there. The server applies two checks to every route, plugin routes included:

1. It rejects a request whose `Host` header is not `127.0.0.1:5000` or `localhost:5000`. This stops DNS rebinding. The plugin uses both host names (`plugin/core/Comm.cpp:58` and `:101`).
2. It rejects a request that changes state if the request has an `Origin` header other than `http://127.0.0.1:5000` or `http://localhost:5000`. Browsers send `Origin` on cross-origin POST requests. WinHTTP sends none, so the plugin is not affected.

GET requests must not change state. `/test_llm` accepts GET and spends tokens today, so it becomes POST only.

The API never returns a stored API key. A read returns only the last four characters. A save with an empty key field keeps the stored key.

## 5. Opening the browser on Kenshi start

The plugin decides when Kenshi starts, because only the plugin knows that. The server decides when it can accept connections.

1. On the first server start in a game session, `StartPythonServer` (`plugin/core/Utils.cpp`) adds `--open-browser` to the command line if `OpenWebPanelOnStart` in the INI is `1`. The default is `1`.
2. A server restart from the in-game launcher does not add the flag, so the player does not get a second tab.
3. With the flag, the server waits until its port accepts connections, then calls `webbrowser.open("http://127.0.0.1:5000/")`. An earlier call shows a connection error page.
4. A server that runs from the repo opens no browser unless the developer passes the flag.

Risk: the browser takes focus. Kenshi in exclusive fullscreen can minimize when it loses focus. The INI toggle and the web app's settings page let the player turn auto-open off. The in-game launcher always has an "Open Web Panel" button, which opens the same URL through `ShellExecute`.

## 6. LLM configuration

### 6.1 Model

| Object | Fields | Role |
|---|---|---|
| Provider | name, type (`openai` or `player2`), base URL, API key | One endpoint and its credentials. The type selects provider-specific auth, such as the Player2 session key refresh in `call_llm`. Today that logic keys on the provider name. |
| Profile | name, provider, model, timeout, extra request parameters (JSON object) | One model on one provider. Several tasks can share a profile. |
| Route | task, ordered list of profiles, `max_tokens`, `temperature`, deadline | What a task asks for and which profiles serve it. |

Sampling values sit on the route, because the output length and creativity that a task needs do not depend on the model. Extra request parameters on the profile hold model-specific options. The request body is built in this order, and a later step overrides an earlier one:

1. `model` and `messages`.
2. The route's `max_tokens` and `temperature`.
3. The profile's extra request parameters.

### 6.2 Tasks

| Task | Call sites | Plugin waits | Default `max_tokens` / `temperature` |
|---|---|---|---|
| `chat` | `chat` | Yes | 2048 / 0.8 |
| `ambient` | `ambient_event` | Yes | 2048 / 0.8 |
| `profile` | `generate_character_profile`, `regenerate_profile_route` | Yes | 1500 / 0.7 |
| `profile_batch` | `generate_batch_profiles` | Yes | 1500 / 0.7 |
| `synthesis` | `generate_global_narrative_thread` | Only through `/synthesize` | 2048 / 0.8 |

The defaults are the values that the call sites pass today. `generate_character_profile` passes 600 today. The `profile` route uses 1500, the value of `regenerate_profile_route`, because `max_tokens` is only a cap.

### 6.3 Fallback

The router replaces the three-attempt retry loop in `call_llm`.

1. The router tries the profiles of the route in order. Each profile gets one attempt. A player who wants a retry lists the same profile twice.
2. The router moves to the next profile after a transport error, a timeout, a non-2xx status, or an empty completion.
3. Each attempt gets the smaller of the profile's timeout and the time left before the route's deadline.
4. The deadline for a task that the plugin waits on defaults to 55 s. This keeps the whole chain inside the plugin's 60 s wait.
5. The log records which profile served the request and why each earlier profile failed.

### 6.4 Storage and migration

The server keeps the LLM configuration in `server/user/llm_config.json`. It writes the file to a temporary name and then renames it, so a crash during a save cannot leave a half-written key file. A save applies at once in memory.

On the first start without `server/user/llm_config.json`, the server builds it:

1. One provider from each entry of the old `server/config/providers.json`, keys included.
2. One profile from each entry of `models.json`.
3. One route for each task, with the old `CurrentModel` profile as the only entry and the defaults from section 6.2.

This reproduces today's behavior. The release then ships its provider and model seeds under new names (`default_providers.json`, `default_models.json`), so the first update that contains this change does not overwrite the old `providers.json` before the migration reads it.

## 7. Settings move and the lean in-game GUI

### 7.1 In-game windows

| Window | After the change |
|---|---|
| Chat | Stays. |
| Launcher (AI panel) | Stays. The "AI Settings" and "Profile Editor" buttons go. "Open Web Panel" and "Restart Server" come in. Restart stays in game because the web app cannot restart a server that does not answer. |
| Dialogue Library | Stays. |
| World Event Log | Stays. |
| Campaign Manager | Stays. |
| Welcome popup | Stays. Its "do not show again" choice posts to the server instead of writing the INI. |
| AI Settings | Goes. Its fields move to the web app's Settings and LLM pages. |
| Profile Editor | Goes. The player backstory and faction description move to the web app, where long text is easier to paste and edit. |

### 7.2 Settings ownership

The server becomes the only writer of `SentientSands_Config.ini`. The plugin reads the INI at start, because it starts before the server, and after that it takes changes only through the pipe. This removes the unlocked double write from section 2.

The plugin gets these changes:

1. `SavePluginConfig` and its callers go.
2. `SET_CONFIG` gets `g_chatHotkey` and `g_language`. The web app offers only the hotkeys that `SetHotkeyFromString` can parse.
3. `PopulateSettingsUI` also fills the Campaign Manager, so that part moves out of `SettingsWindow.cpp` before the file goes.
4. The plugin loads the translation table once the server answers at start, not in `PopulateSettingsUI`. After a `g_language` change, it loads the table again on a worker thread and hands the result to the game thread through `g_messageQueue`, as the threading rule in [architecture.md](architecture.md#threading) requires.
5. The plugin stops reading the model fields of the `/settings` response. `visual_debugger.py` still reads `/models` and posts `current_model` to switch the model, so the debugger moves to routes or drops its model switch.

## 8. Data editor

The data editor depends on phases 1 and 2 of the SQLite proposal. Until then, the web app edits the player profile over the current per-campaign text files.

### 8.1 Scope

The editor works on the template database and the active campaign database. Campaign switching stays in the in-game Campaign Manager. The web app shows the name of the active campaign and reloads its data when the campaign changes.

| Page | Edits |
|---|---|
| Entities | Search and filter by category. Fields, aliases, children with weights, and access rules. |
| NPCs | Profile, dialogue history, and stats of the active campaign. |
| World events | The event history of the active campaign. |
| Player profile | Player backstory and faction description. |

### 8.2 Consistency

- The API writes only through `sentient_db` functions, never through SQL built in a route. The `link` table and the `entity_fts` index derive from fields and aliases ([SQLite proposal, section 6](proposal_sqlite_knowledge_store.md#6-data-model)), and only `sentient_db` keeps them in step.
- An edit to the template becomes a patch ([SQLite proposal, section 7.2](proposal_sqlite_knowledge_store.md#72-step-2-local-patch-layer)), so a re-import of upstream data keeps it. An edit to a campaign writes the campaign database directly.
- The game changes the same records during play, for example "Regen Bio" in the Dialogue Library. Each editable record carries `updated_at`, and a save with an older value is rejected so that the web app reloads the record. The `entity` table needs this column added.
- Each request thread opens its own SQLite connection, with WAL mode and a `busy_timeout`. A web save then waits for a game write in progress instead of failing.

## 9. Phases

| Phase | Deliverable | Depends on | Acceptance criteria |
|---|---|---|---|
| W1. Shell | `/` serves the web app; the Host and Origin checks; `--open-browser`; "Open Web Panel" in the launcher | None | The browser opens once on Kenshi start and not on an in-game restart. A cross-origin POST gets 403. All plugin routes still work. |
| W2. LLM config | Providers, profiles, and routes pages; `llm_router.py`; `server/user/llm_config.json` and its migration; a test button per profile | W1 | A migrated install sends every task to the old `CurrentModel`. A failing first profile falls through to the next inside the deadline. Keys survive a release update. |
| W3. Settings move | All settings in the web app; the server as the only INI writer; the new `SET_CONFIG` keys; the AI Settings and Profile Editor windows removed | W2 | A setting changed in the web app takes effect in game without a restart. The launcher shows only the windows from section 7.1. |
| W4. Data editor | The pages from section 8.1 on the SQLite store | SQLite phase 2 | An entity edit appears in the next prompt that retrieves it. A stale save is rejected. A search finds a renamed entity. |

W1 to W3 do not need the SQLite store. They can run before or alongside SQLite phases 0 and 1.

## 10. Verification

- `llm_router.py`: unit tests with a fake HTTP call, for chain order, the fall-through conditions, and the deadline. These tests run in the dev container.
- Request checks: Flask test-client tests for a foreign `Host`, a foreign `Origin`, no `Origin` (the plugin case), and a same-origin request. These tests need Flask, so they run outside the dev container.
- Migration: an install with the old `providers.json`, `models.json`, and `CurrentModel`, upgraded with a release zip, keeps its keys and routes every task to the old model.
- Plugin: the dev container cannot build the plugin, so a Windows build checks the launcher, the new `SET_CONFIG` keys, the hotkey and language changes, and the auto-open flag in game.

## 11. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| The browser takes focus from fullscreen Kenshi | The game minimizes at start | INI toggle; the flag only on the first start |
| A malicious page sends requests to the server | Stolen API key or changed settings | Host and Origin checks on every route |
| A fallback chain outlives the plugin's wait | The player gets no reply | Route deadline under 60 s |
| A web edit and a game write hit the same record | One change is lost without notice | `updated_at` check; `busy_timeout` |
| A release update overwrites player files | Lost keys | `server/user/` is not shipped; seeds renamed |

## 12. Open questions

1. Should the release stop shipping `SentientSands_Config.ini`? Today an update resets the player's gameplay settings in the same way that it resets the keys.
2. Does the player need the Profile Editor during play? This proposal moves it to the web app.
