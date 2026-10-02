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
| `server/scripts/` | The Flask server (`kenshi_llm_server.py`), the request checks (`request_guard.py`), the browser auto-open (`browser_launch.py`), the LLM configuration (`llm_config.py`) and fallback chain (`llm_router.py`), the Kenshi save parser (`save_reader.py`), and a Tkinter debug tool (`visual_debugger.py`). |
| `server/web/` | The web app: plain HTML, CSS, and JavaScript, which the server serves at `http://127.0.0.1:5000/`. |
| `server/tests/` | Unit tests that run with the standard library only. See [development.md](development.md#tests). |
| `server/config/` | The default providers and models that seed the LLM configuration, and the name, title, and localization JSON. |
| `server/templates/` | Prompt templates and the world lore. |
| `mod/` | The files at the root of the installed mod folder: `mod.info`, `SentientSandsRebirth.mod`, `RE_Kenshi.json`, and the default `SentientSands_Config.ini`. |
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
  SentientSands_Config.ini   settings that the plugin and the server both read
  server/
    scripts/  config/  templates/  web/
    python/                  embedded runtime, added by scripts/package_release.py
    campaigns/  logs/  user/ created at runtime
```

- The plugin takes the mod root from the path of its own DLL (`startPlugin` in `plugin/main.cpp`). A Steam Workshop folder with a numeric name works for this reason.
- The plugin runs `server\python\python.exe server\scripts\kenshi_llm_server.py`. If the embedded runtime is missing, it falls back to `python` on `PATH` (`StartPythonServer` in `plugin/core/Utils.cpp`).
- The server takes its folders from its own script path. The server root is the parent of `scripts/`, and the mod root is the parent of the server root. When the server runs from this repo, it finds the INI in `mod/` instead (`resolve_mod_file` in `server/scripts/kenshi_llm_server.py`).

## Runtime flow

1. RE_Kenshi loads `SentientSands.dll` and calls `startPlugin`. The plugin installs its KenshiLib hooks and starts `MainThread`.
2. `MainThread` waits for `KenshiLib.dll`. Then it starts the pipe listener (`PipeThread`) and the name-assignment thread, loads the INI, and starts the server. After that, it posts the player's context to `/context` at most once every 5 seconds.
3. If `OpenWebPanelOnStart` in the INI is `1`, this first server start passes `--open-browser`. The server then opens the web app in the default browser when its port accepts connections. A restart from the launcher does not pass the flag, so the player does not get a second tab.
4. The server listens on `127.0.0.1:5000`. The plugin sends HTTP POST requests to it through WinHTTP (`plugin/core/Comm.cpp`) for chat, history, settings, campaigns, profiles, and events. The server rejects a request whose `Host` header is not `127.0.0.1:5000` or `localhost:5000`, or whose `Origin` header names another site (`server/scripts/request_guard.py`). This stops web pages in the player's browser from using the server. A new caller must use one of these two host names.
5. The server sends commands back through the named pipe `\\.\pipe\SentientSands`, which the plugin hosts. Examples are `SET_CONFIG`, `NOTIFY`, and `POPULATE_GENERIC`.
6. The server builds each prompt from `server/templates/` and the campaign state, then sends it down the route of its task (see [LLM routing](#llm-routing)).

## Threading

Background threads do not change game objects or MyGUI widgets. The pipe listener, the HTTP response threads, and the UI worker threads push text messages onto `g_messageQueue` under `g_msgMutex` (`plugin/core/Globals.h`). `playerUpdate_hook` runs on the game thread and drains the queue through `ProcessMessageQueue` (`plugin/main.cpp`). New code that produces results off the game thread must hand them over through this queue.

## Settings

The server is the only writer of `SentientSands_Config.ini`. The plugin reads the INI once at start, because it starts before the server. After that, it takes changes only through `SET_CONFIG` on the pipe. Two writers with no lock between them would undo each other's changes.

A default applies only when the INI has no value for a key. The defaults in `LoadPluginConfig` (`plugin/core/Utils.cpp`), the defaults in `load_settings` (`server/scripts/kenshi_llm_server.py`), and the values in `mod/SentientSands_Config.ini` must agree, or the plugin and the server start with different values.

The web app's Settings page posts its changes to `/settings`. The server writes the INI and sends each value that the plugin holds through `SET_CONFIG`. A language change sends the new translation table through the pipe as `APPLY_TRANSLATION`.

The plugin re-creates its pipe instance after each message, so a message sent immediately after another can find no instance. `send_to_pipe` retries for 0.25 s for this reason. When the game does not run, each message therefore costs 0.25 s.

## LLM routing

Each LLM call names a task: `chat`, `ambient`, `profile`, `profile_batch`, or `synthesis`. `server/user/llm_config.json` holds three parts, and the web app's LLM page edits all of them through `/api/llm`.

| Part | Contents |
|---|---|
| Providers | An OpenAI-compatible endpoint: type (`openai` or `player2`), base URL, API key, and the Player2 game key. |
| Profiles | One model on one provider, with a per-attempt timeout and extra request parameters. |
| Routes | For each task, an ordered list of profiles, `max_tokens`, `temperature`, and a deadline. |

`llm_router.run_route` tries the profiles of the route in order, one attempt each. It moves to the next profile after an exception, a non-200 status, or an empty completion. Each attempt gets the smaller of the profile's timeout and the time left before the deadline. The default deadline is 55 s, because the plugin stops waiting for a reply after 60 s (`plugin/core/Comm.cpp`).

The request body starts with `model`, `messages`, and `top_p` 0.9. The route's `max_tokens` and `temperature` come next, and the profile's extra request parameters override both.

A Player2 provider uses a session key from the local Player2 app. On a 401, `send_completion` gets a new session key and tries the same profile once more.

`/api/llm` never returns a stored API key, only its last four characters. A save with an empty key field keeps the stored key, so the web app can send back what it received. The server writes the file to a temporary name and then renames it, so a crash during a save cannot leave a half-written key file.

On a start without `llm_config.json`, the server builds it with one route per task that holds only the profile of the old `CurrentModel` setting. It reads `providers.json` and `models.json` from `server/config/` if an earlier release left them there, else `default_providers.json` and `default_models.json`.

## Server state

| Location | Contents |
|---|---|
| `server/campaigns/<name>/` | One campaign: `characters/*.json` (one file per NPC), `world_events.txt`, `event_history.json`, `logs/`, and `sentient_sands_registry/`. |
| `server/logs/server.log` | The main server log, rotated at 512 KB. |
| `server/debug.log` | The debug log, rotated at 1 MB. |
| `server/user/llm_config.json` | The LLM providers with the player's API keys, the profiles, and the routes (see [LLM routing](#llm-routing)). The release does not ship it, so an update keeps the keys. |
