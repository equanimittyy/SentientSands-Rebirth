# Proposal: Server Layout

Status: Draft for review

## 1. Summary

All server code is in `server/scripts/`, and most of it is in one file, `kenshi_llm_server.py`, with 2918 lines. The shipped content and the player files are in five folders at the server root. Two of the names mislead: `server/config/` holds shipped defaults, and `server/user/` holds the player's settings.

The refactor gives each concern of the server one folder:

```
server/
  main.py            entry point: start-up order, blueprints, background threads
  core/              shared infrastructure and the routes that the plugin calls
  chat/              prompts, profiles, LLM calls, bios, memories, synthesis, chat routes
  store/             campaign database, world templates, campaign create and switch
  dashboard/         the web app and the routes that only the web app calls
  data/              shipped templates, prompts, and defaults; player templates; campaigns
  config/            player settings: llm_config.json and prompt overrides
  tests/
  logs/              unchanged
  python/            unchanged: the embedded runtime of the release
  requirements.txt   unchanged
```

The refactor has two phases:

1. Phase 1 moves files and changes paths and imports only ([section 3](#3-phase-1-moves)).
2. Phase 2 splits `main.py` into modules of the new folders ([section 4](#4-phase-2-split)).

Each step of a phase is one commit. After each step, the tests pass and the server works ([section 5](#5-verification)).

Non-goals:

- A change of behaviour: of a route, a reply, a prompt, a log line, or the campaign schema.
- A migration of old player files, because SSR v0.1 has no users.
- A rewrite of a function body. Phase 2 moves code between files and does not restructure it.

## 2. Target layout

| Folder | Contents | In the release |
|---|---|---|
| `core/` | Paths, session state, the Flask app and its request hooks, the pipe, the INI settings, logging, the request guard, the process monitor, the game routes, and `visual_debugger.py` | Yes |
| `chat/` | The prompt and scene modules, the profiles and names, the LLM configuration, router, and calls, the bios, the memories, the synthesis, and the chat routes | Yes |
| `store/` | `campaign_db.py`, `world_template.py`, and the campaign create and switch | Yes |
| `dashboard/` | The routes of the web app and `browser_launch.py`; the web app files in `dashboard/web/` | Yes |
| `data/templates/` | SSR Vanilla | Yes |
| `data/prompts/` | The shipped prompts | Yes |
| `data/defaults/` | The default providers and models, names, personality traits, backstories, speech quirks, animal personalities, and localization | Yes |
| `data/user_templates/` | The player's world templates, created at runtime | No |
| `data/campaigns/` | The campaigns, created at runtime | No |
| `config/` | `llm_config.json`, and `prompts/` with the overrides and `base_hashes.json`, created at runtime | No |

- The web app files go in `dashboard/web/`, not in `dashboard/`. Flask serves every file of its static folder, so a static folder that also held the Python routes would serve their source and `__pycache__` at `/web/`.
- The URL of the web app files stays `/web/`, so no HTML or JavaScript changes.
- The routes under `/api/`, `/`, and `/web_panel/presence` go in `dashboard/`, because only the web app calls them. The plugin calls no route under `/api/`.
- `SentientSands_Config.ini` stays in the mod root. The plugin reads it before it starts the server, so a move would change the plugin and gain nothing.
- `logs/` stays at the server root. A log is neither content nor a player setting.
- `visual_debugger.py` goes in `core/`. It is a debugging tool, it fits no other folder, and it still ships.
- `chat/`, `core/`, `store/`, and `dashboard/` are packages, each with an empty `__init__.py`. The tests run without Flask, so an `__init__.py` must not import it. `data/`, `config/`, and `tests/` are not packages.
- `main.py` puts its own folder, `server/`, first on `sys.path`, as `kenshi_llm_server.py` does with `server/scripts/` today. The `._pth` file of the embedded runtime does not add the folder of the script (`install_python` in `scripts/package_release.py`).

## 3. Phase 1: moves

### Step 1: content

| Now | After |
|---|---|
| `server/world_templates/` | `server/data/templates/` |
| `server/prompts/` | `server/data/prompts/` |
| `server/config/*.json` | `server/data/defaults/` |
| `server/web/` | `server/dashboard/web/` |
| `server/user/llm_config.json` | `server/config/llm_config.json` |
| `server/user/prompts/` | `server/config/prompts/` |
| `server/user/world_templates/` | `server/data/user_templates/` |
| `server/campaigns/` | `server/data/campaigns/` |

Git ignores the last four, so for them the step changes only the paths in the code.

- The path constants of `kenshi_llm_server.py` (lines 70–84) and the folder that `load_configs` creates (line 314).
- `CONFIG_DIR` in `provisional_profile.py`, and the log and campaign paths in `visual_debugger.py` (lines 368 and 418).
- The template paths of `test_provisional_profile.py` and `test_world_template.py`, and the paths of `scripts/mock_test.py` (lines 149 and 152).
- `SERVER_DIRS` in `scripts/package_release.py`: `scripts`, `dashboard/web`, `data/templates`, `data/prompts`, and `data/defaults`.
- `.gitignore`: `server/campaigns/` and `server/user/` become `server/data/campaigns/`, `server/data/user_templates/`, and `server/config/`. After the step, `server/config/` holds only player files, so git ignores the whole folder.

### Step 2: code

| Now, in `server/scripts/` | After |
|---|---|
| `kenshi_llm_server.py` | `server/main.py` |
| `campaign_db.py`, `world_template.py` | `server/store/` |
| `chat_prompt.py`, `scene_text.py`, `npc_names.py`, `current_job.py`, `provisional_profile.py`, `prompt_store.py`, `llm_config.py`, `llm_router.py` | `server/chat/` |
| `log_setup.py`, `request_guard.py`, `visual_debugger.py` | `server/core/` |
| `browser_launch.py` | `server/dashboard/` |

- An import such as `import campaign_db` becomes `from store import campaign_db`, so a call such as `campaign_db.open_campaign(...)` does not change. `chat_prompt.py` and `llm_router.py` import their neighbours in the same way.
- `SCRIPT_DIR` and `KENSHI_SERVER_DIR` in `main.py` become one `SERVER_DIR`, the folder of `main.py`.
- Each test puts `server/` on `sys.path` in place of `server/scripts/`.
- `StartPythonServer` in `plugin/core/Utils.cpp` starts `server\main.py`. The comment at `plugin/game/Context.cpp:253` names `server/chat/current_job.py`.
- The DLL must be rebuilt on Windows. A DLL from before this step cannot start the new server, so a test install needs the new DLL and the new server together.
- `SERVER_DIRS` lists `core`, `chat`, `store`, `dashboard`, and the three shipped folders of `data/`, and `stage_files` also copies `main.py`. The release must not contain `config/`, `data/campaigns/`, or `data/user_templates/`.

## 4. Phase 2: split

### Rules

1. Each piece of mutable state has one owner module, and other modules read and assign it as `owner.NAME`. The state that several packages share and that has no natural owner goes in `core/state.py`.
2. No module imports mutable state with `from x import NAME`. That import copies the value once, so a later assignment, such as a campaign switch, never reaches the copy. A reader imports the module: `from core import state`, then `state.ACTIVE_CAMPAIGN`.
3. Only `main.py`, `core/app.py`, `chat/llm.py`, the `routes.py` of each package, and the standalone `core/visual_debugger.py` import Flask or `requests`. The tests run without both, so testable logic stays in the other modules ([development.md](../info/development.md#tests)).
4. The imports between modules have no cycle.
5. The request hooks and the error handler stay on the app object in `core/app.py`. A hook on a blueprint runs only for the routes of that blueprint, so the request guard would no longer check the other routes and the static files.
6. Nothing runs at import. Each start-up action moves into `main.py`, in the order of [Start-up](#start-up).

### Module map

| Module | Takes from `main.py` |
|---|---|
| `core/paths.py` | `SERVER_DIR`, `MOD_DIR`, `resolve_mod_file`, `INI_PATH`, each folder and file path, `DEFAULT_TEMPLATE` |
| `core/state.py` | `ACTIVE_CAMPAIGN`, `PLAYER_CONTEXT`, `LIVE_CONTEXTS`, `SEEN_FACTIONS`, `CONVERSATION_SCENE`, `CURRENT_THREAD`, `THREAD_LOCK`, `QUIET_SINCE`, `restart_quiet_clock`, `GAME_REPORTED`, `WRITE_REQUESTS` |
| `core/app.py` | The Flask app, `handle_exception`, `reject_foreign_requests`, `adopt_canon_ids`, `count_write_requests`, the `.js` MIME type |
| `core/pipe.py` | `send_to_pipe` |
| `core/settings.py` | `CHAT_HOTKEYS`, `INI_KEY_MAP`, `SETTINGS_DEFAULTS`, `_save_settings_raw`, `load_settings`, `save_settings`, `push_settings_to_plugin`, `settings_page_values`, `get_config_radii`, `LOCALIZATION_CONFIG` with its half of `load_configs` |
| `core/process.py` | `kill_old_servers`, `monitor_kenshi_process` |
| `core/game.py` | `adopt_canon`, `context_dict`, `get_current_time_prefix`, `is_player_faction`, `npc_serial`, `note_faction`, `take_report`, `report_from_game`, `EVENT_THROTTLE`, `LAST_STATE_LOG`, their locks, `record_event_to_history` |
| `core/routes.py` | `/report`, `/context`, `/events`, `/events/content`, `/cull`, `/settings`, `/settings/defaults`, `/history`, `/characters`, `/favorite`, `/rename`, `/squad_rename`, `cull_future_data` |
| `store/campaigns.py` | `get_campaign_dir`, `load_campaign_config`, `init_server_state`, `create_campaign`, `switch_campaign`, `campaign_names` |
| `chat/llm.py` | `default_llm_config`, `load_llm_config`, `LLM_CONFIG`, `PLAYER2_SESSION_KEY`, `refresh_player2_session`, `extract_completion`, `send_completion`, `log_usage`, `call_llm`, `player2_ping_loop`, `sanitize_llm_text`, `robust_json_parse` |
| `chat/prompts.py` | `PROMPT_RUMORS`, `load_prompt_component`, `fill_prompt`, `build_system_prompt`, `scene_values`, `describe_npc`, `describe_faction`, `faction_text`, `describe_origin`, `describe_record`, `find_named`, `find_race`, `describe_race`, `current_job_line`, `job_of`, `job_field`, `building_of`, `location_field`, `npc_scene`, `generate_relation_bar` |
| `chat/characters.py` | `ANIMAL_RACES`, `SKELETON_RACE_PREFIXES`, `is_skeleton`, `reported_sex`, `is_animal`, `character_kind`, `NAMES_CONFIG` with its half of `load_configs`, `KENSHI_NAME_POOL`, `get_used_names`, `generate_unique_lore_name`, `get_character_data`, `should_save_profile`, `new_profile`, `send_rename`, `sync_name`, `npc_name` |
| `chat/bio.py` | `BIO_PARTS`, `PROFILES_IN_PROGRESS`, `PROGRESS_LOCK`, `write_bio`, `recorded_history`, `generate_bio` |
| `chat/memory.py` | `quiet_seconds`, `write_memory`, `distill_threads`, `memory_loop` |
| `chat/synthesis.py` | `RUMOR_SYNTHESIS`, `SYNTHESIS_STATUS`, `generate_global_narrative_thread`, `synthesis_loop` |
| `chat/routes.py` | `/chat`, `/ambient`, `/synthesize`, `/write_bio`, `/read_bio`, `/keep_bio` |
| `dashboard/routes.py` | `/`, `/web_panel/presence`, `PANEL_TABS`, each route under `/api/`, `template_error`, `campaign_write`, `record_refusal`, `bio_refusal`, `bio_reply`, `save_campaign_faction` |

- `switch_campaign` clears the chat state of the old campaign. That state is in `core/state.py`, so `store/campaigns.py` imports no `chat/` module.
- `cull_future_data` returns a Flask reply, so it goes in `core/routes.py`, and the cull route of `dashboard/routes.py` imports it from there.
- `web_app` calls `current_app.send_static_file`, because a blueprint has no `app` name.
- `main.py` keeps only `sys.path`, the start-up, and the registration of the blueprints. Each route keeps its path and its methods. Only its endpoint name gets the prefix of its blueprint, and no code reads endpoint names, because the server has no `url_for`.

### Start-up

Today these actions run at import, in this order. `main.py` runs them in the same order:

1. Set up the log files (`log_setup.setup`).
2. Stop an old server on port 5000 (`kill_old_servers`).
3. Load the names and the localization (`load_configs`).
4. Read the INI, set the log level and the active campaign, and open the campaign (`init_server_state`).
5. Load the LLM configuration (`load_llm_config`).
6. Start the threads: `synthesis_loop` when `RUMOR_SYNTHESIS` is on, `memory_loop`, `player2_ping_loop`, and `monitor_kenshi_process`.
7. Start `push_settings_to_plugin`, then `open_when_ready` with `--open-browser`, then `app.run`.

### Steps

| Step | Moves |
|---|---|
| 3 | `core/paths.py`, `core/state.py`, `core/pipe.py`, `core/settings.py`, `core/process.py`, `core/app.py` |
| 4 | `store/campaigns.py` |
| 5 | `chat/llm.py`, `chat/prompts.py`, `chat/characters.py`, `chat/bio.py`, `chat/memory.py`, `chat/synthesis.py` |
| 6 | `core/game.py`, and the three `routes.py` as blueprints. The start-up moves into `main.py`. |

## 5. Verification

Each step passes these checks before its commit:

1. `python3 -m unittest discover -s server/tests` passes.
2. The route list is the same. Before step 1, a script in the scratchpad lists each rule of `app.url_map` with its methods. After each step, the list has the same paths and methods.
3. The server runs from a copy in the scratchpad, with Flask from the staged release runtime. A stub provider in the scratchpad answers each `/chat/completions` request with a fixed reply. A request to each page of the web app, a campaign create and switch, `/chat`, `/ambient`, and `/write_bio` succeed. The checks of rule 2 also hold: `grep -rn "from core.state import" server` finds nothing.
4. After steps 1 and 2: `stage_files` writes into the scratchpad, and the staged tree holds the shipped folders and no `config/`, `data/campaigns/`, `data/user_templates/`, `logs/`, or `tests/`.

After step 2, and after step 6, an in-game test on Windows:

1. Rebuild the DLL, package the release, and install it.
2. Start the game. `server/logs/server.log` shows the start, and the web app opens.
3. Chat with an NPC, let banter run, open the Dialogue Library, and switch the campaign on the web app.

## 6. Documents and comments

Each step updates the documents that it makes wrong, in the same commit:

| File | Change |
|---|---|
| [architecture.md](../info/architecture.md) | The repository layout table, the installed layout tree and its bullets, the server state table, and each `server/scripts/` reference |
| [development.md](../info/development.md) | The run command, the `visual_debugger.py` path, and the sentence on what the zip leaves out. That sentence names `server/config/providers.json`, which `package_release.py` never excludes. |
| `README.md` | The paths of `llm_config.json`, the player templates, and the campaigns (lines 55 and 64) |
| [proposal_lore_retrieval.md](proposal_lore_retrieval.md) | `server/scripts/retrieval.py` becomes `server/chat/retrieval.py`, and the reference to `count_write_requests` names `core/app.py` |
| Code comments | The docblocks of `prompt_store.py`, `world_template.py`, `llm_config.py`, and `provisional_profile.py`, `server/web/editor.js` lines 19 and 34, and `plugin/game/Context.cpp:253` |

## 7. Risks

- Rule 2 is the most likely bug. A copy of `ACTIVE_CAMPAIGN` or `LLM_CONFIG` works until the first campaign switch or Models save, and then it reads the old value with no error.
- Git records a move as a rename only when the file stays similar enough. Each step therefore keeps the content edits of a moved file small. After phase 2, `git blame -C -C` follows the code into its new module.
- The JSON defaults, the prompts, and `plugin/core/Utils.cpp` are CRLF in the index. `git mv` keeps their bytes, and an edit must keep their line endings.
- A developer's local runtime files must move by hand: `server/user/llm_config.json`, `server/user/prompts/`, `server/user/world_templates/`, and `server/campaigns/`. Without the move, the server builds a new `llm_config.json` without the API keys.
