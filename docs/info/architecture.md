# Architecture

Sentient Sands has three parts: a C++ plugin that runs inside Kenshi, a local Python server that talks to the LLM provider, and the Kenshi mod files that make the game load the plugin.

## Repository layout

| Path | Contents |
|---|---|
| `deps/` | Not in git. The KenshiLib and Boost files that the plugin build needs. See [plugin_build_setup.md](plugin_build_setup.md#3-fill-deps). |
| `plugin/SentientSands.vcxproj` | The Visual Studio project that builds `SentientSands.dll`. See [development.md](development.md#plugin). |
| `plugin/main.cpp` | The entry point (`startPlugin`), the game hooks, and the message-queue dispatcher. |
| `plugin/core/` | Shared state and mutexes (`Globals`), logging, INI settings, and server start-up (`Utils`), and the transport to the server (`Comm`). |
| `plugin/game/` | Reads game state into JSON for prompts (`Context`) and applies queued NPC actions to the world (`GameActions`). |
| `plugin/ui/` | The in-game MyGUI windows. `LauncherWindow` is the hub that opens the others. `ChatUIGlobals` holds the shared widget pointers. |
| `server/scripts/` | The Flask server (`kenshi_llm_server.py`), the request checks (`request_guard.py`), the Kenshi save parser (`save_reader.py`), and a Tkinter debug tool (`visual_debugger.py`). |
| `server/tests/` | Unit tests that run with the standard library only. See [development.md](development.md#tests). |
| `server/config/` | Provider, model, name, title, and localization JSON. |
| `server/templates/` | Prompt templates and the world lore. |
| `mod/` | The files at the root of the installed mod folder: `mod.info`, `SentientSands.mod`, `RE_Kenshi.json`, and the default `SentientSands_Config.ini`. |
| `scripts/` | Release tooling. See [development.md](development.md#release). |

## Installed layout

The release zip unpacks into `Kenshi/mods/` as the tree below. The plugin and the server find each other through these relative paths. Do not change one side without the other.

```
SentientSands/
  SentientSands.dll          built from plugin/
  RE_Kenshi.json             makes RE_Kenshi load the DLL
  mod.info
  SentientSands.mod
  SentientSands_Config.ini   settings that the plugin and the server both read
  server/
    scripts/  config/  templates/
    python/                  embedded runtime, added by scripts/package_release.py
    campaigns/  logs/        created at runtime
```

- The plugin takes the mod root from the path of its own DLL (`startPlugin` in `plugin/main.cpp`). A Steam Workshop folder with a numeric name works for this reason.
- The plugin runs `server\python\python.exe server\scripts\kenshi_llm_server.py`. If the embedded runtime is missing, it falls back to `python` on `PATH` (`StartPythonServer` in `plugin/core/Utils.cpp`).
- The server takes its folders from its own script path. The server root is the parent of `scripts/`, and the mod root is the parent of the server root. When the server runs from this repo, it finds the INI in `mod/` instead (`resolve_mod_file` in `server/scripts/kenshi_llm_server.py`).

## Runtime flow

1. RE_Kenshi loads `SentientSands.dll` and calls `startPlugin`. The plugin installs its KenshiLib hooks and starts `MainThread`.
2. `MainThread` waits for `KenshiLib.dll`. Then it starts the pipe listener (`PipeThread`) and the name-assignment thread, loads the INI, and starts the server. After that, it posts the player's context to `/context` at most once every 5 seconds.
3. The server listens on `127.0.0.1:5000`. The plugin sends HTTP POST requests to it through WinHTTP (`plugin/core/Comm.cpp`) for chat, history, settings, campaigns, profiles, and events. The server rejects a request whose `Host` header is not `127.0.0.1:5000` or `localhost:5000`, or whose `Origin` header names another site (`server/scripts/request_guard.py`). This stops web pages in the player's browser from using the server. A new caller must use one of these two host names.
4. The server sends commands back through the named pipe `\\.\pipe\SentientSands`, which the plugin hosts. Examples are `SET_CONFIG`, `NOTIFY`, and `POPULATE_GENERIC`.
5. The server builds each prompt from `server/templates/` and the campaign state, then calls the OpenAI-compatible provider that `server/config/providers.json` and `models.json` select.

## Threading

Background threads do not change game objects or MyGUI widgets. The pipe listener, the HTTP response threads, and the UI worker threads push text messages onto `g_messageQueue` under `g_msgMutex` (`plugin/core/Globals.h`). `playerUpdate_hook` runs on the game thread and drains the queue through `ProcessMessageQueue` (`plugin/main.cpp`). New code that produces results off the game thread must hand them over through this queue.

## Server state

| Location | Contents |
|---|---|
| `server/campaigns/<name>/` | One campaign: `characters/*.json` (one file per NPC), `world_events.txt`, `event_history.json`, `logs/`, and `sentient_sands_registry/`. |
| `server/logs/server.log` | The main server log, rotated at 512 KB. |
| `server/debug.log` | The debug log, rotated at 1 MB. |
| `server/config/providers.json` | Provider base URLs and the player's API keys. The server copies it from `default_providers.json` on first start. The release does not ship it, so an update keeps the keys. |
