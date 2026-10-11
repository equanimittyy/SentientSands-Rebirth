# Development

[architecture.md](architecture.md) describes the parts and how they connect. This page covers how to build, run, and release them.

## Plugin

`plugin/SentientSands.vcxproj` builds `SentientSands.dll`. It builds only Release|x64 with the Visual C++ 2010 toolset (`v100`). The plugin shares C++ types with the game, which was built with Visual C++ 2010, so a different toolset breaks the ABI.

[plugin_build_setup.md](plugin_build_setup.md) sets up a build machine and an in-game test install, step by step. Do it once per machine.

To build, open the project in Visual Studio and build it, or run this in a Developer Command Prompt:

```
msbuild plugin\SentientSands.vcxproj
```

The DLL goes to `plugin\x64\Release\SentientSands.dll`. Kenshi locks the DLL while it runs, so close the game before a build that copies it.

The project lists each source file, because the Visual Studio IDE does not support wildcards in project items. A new file that you add through Solution Explorer goes into the list. A new file that you create outside Visual Studio must be added to the project, or the link fails.

Includes between plugin files are relative (`../core/Utils.h`), so the plugin folders need no include path entry.

When `SENTIENT_SANDS_MOD_DIR` names an installed mod folder, each build copies the DLL into it. To test the build, start the game normally. The plugin writes `SentientSands_SDK.log` in the `logs` folder of the mod. At each game start, it renames the log of the previous game to `SentientSands_SDK.old.log`, so the folder holds the logs of two games at most.

## Server

To run the server from the repo:

```
python -m pip install -r server/requirements.txt
python server/main.py
```

The web app is at `http://127.0.0.1:5000/`. Add `--open-browser` to open it when the server is ready and no tab of it is open, as the plugin does at game start.

From the repo, the server keeps its INI in `mod/SentientSands_Config.ini` and writes its logs and campaigns under `server/`. On first start, it also creates `server/config/llm_config.json` for your API keys. Git ignores all of these files.

The dev container cannot build the plugin. To run the server there, install its packages in a virtual environment (`python3 -m venv`).

## Tests

```
python -m unittest discover -s server/tests
```

The tests use only the standard library, so they run in the dev container. Code that imports Flask or `requests` cannot be tested there, so keep testable logic in modules that do not import them.

## Mock data

```
python scripts/mock_test.py [name]
```

The script creates a campaign from SSR Vanilla, named `mock` by default, and fills it with a squad, NPCs, chat threads, a radiant conversation of the squad, the memories of all threads but the newest, and the game events of the capture of a known figure, with a rumor, and of the kill of another, which go through the attribution of the server. Dialogue & Memories and Events on Campaign Canon, and the Dialogue Library, then have data without a game. The script refuses a name that a campaign already uses, so a second run cannot add the data twice. It needs no Flask, so it runs in the dev container. Switch to the campaign on the Campaigns page.

## Tutorial videos

The Tutorial tab of the web app shows short videos of the web app. `scripts/tutorial_video/` makes them in two steps:

| Step | Command | Result |
|---|---|---|
| Capture | `python scripts/tutorial_video/capture.py [scene ...]` | The screenshots and a `timeline.json` of each scene, in `scripts/tutorial_video/captures/` |
| Render | `python scripts/tutorial_video/render.py [scene ...]` | `server/dashboard/web/videos/<scene>.mp4` and its poster `<scene>.jpg` |

Without a scene name, each script does all scenes. The steps need Python 3.10 or later. The dev container has the browser and its libraries, so there they need only a virtual environment (`python3 -m venv`) for the packages. Set up a machine once:

```
python -m pip install -r scripts/tutorial_video/requirements.txt
python -m playwright install chromium
```

- `scripts/tutorial_video/scenes.py` holds the browser steps and the bubble notes of each scene. The ID of a scene names its video.
- Each scene runs on its own copy of the server, which `scripts/mock_test.py` fills. The LLM calls of the page get fixed replies. So a capture needs no API key, and it changes none of your data.
- The server accepts only the host `127.0.0.1:5000`, so the capture needs port 5000. Close Kenshi, stop the SSR server, and stop a forwarded port 5000 of the dev container first. At start, the server kills each process that listens on port 5000, so the capture stops when the port is in use.
- When a step fails, the capture saves the page as `failed.png` in the folder of the scene, and goes on with the next scene.
- `render.py` draws each frame with Pillow and encodes it with the ffmpeg that the `imageio-ffmpeg` package includes. `scripts/tutorial_video/motion.py` holds the timing and the motion, without Pillow.
- After a change to a page of the web app, capture and render its scenes again.

## Probes

Some questions of the plans need data from the game. The plugin writes probe lines to `SentientSands_SDK.log` for them, but only at the `DEBUG` log level. Set **Log level** on the Settings page to `DEBUG` before an in-game test. All probe functions are in `plugin/game/Context.cpp`. A probe is removed when the change that needs its answer is built.

| Line | Written | Function | Answers |
|---|---|---|---|
| `FACTION_PROBE` | At the first chat of each game, one line for each faction | `LogFactionList` | The string ID of each faction, and whether it stays the same when the mod list changes |
| `ROLE_PROBE` | For the chat target, each NPC in chat range, and each radiant participant, again when a value changes | `LogNpcRole` | Which game data tells the role of an NPC, and whether a hired NPC holds a contract (`contract=1`) |
| `STOCK_PROBE` | At each `/stock` test command of the chat | `ProbeStock` | Where a trader keeps its stock, and which data of an item holds the grade that the game shows for a weapon or an armour |
| `FIRSTAID_PROBE` | At each `/firstaid` test command of the chat | `ProbeFirstAid` | Whether the chat target carries a first aid item, and whether `FIRST_AID_ORDER` makes it treat the speaker |
| `HIRE_PROBE` | At each `/hire` test command of the chat | `ProbeHire` | Which call starts a hire contract with an expiry time, and which call ends it |

`/stock` changes nothing. `/firstaid` gives the chat target the `FIRST_AID_ORDER` task on the speaker. `/hire [hours]` gives the chat target the `Bodyguard` contract for that many hours, `/hire [line ID]` starts the contract of a dialogue line of the game, `/hire end` ends the contract, and `/hire` alone only logs.

[kenshi_internals.md](kenshi_internals.md) records the answers of the in-game tests.

Two questions need no probe:

- FTS5 in the embedded runtime, which retrieval needs. In an installed release, run `server\python\python.exe -c "import sqlite3; sqlite3.connect(':memory:').execute('CREATE VIRTUAL TABLE t USING fts5(x)'); print(sqlite3.sqlite_version)"`. A version number means that FTS5 is available. An error means that it is not.
- Whether the local Player2 API lists its models. Press **List models** on a profile of a Player2 provider on the Models page.

## Release

On Windows, run `package_release.cmd` in the repo root, and select one of its options:

| Option | Result |
|---|---|
| 1. Rebuild and repackage | Builds the plugin, then packages it. It does not package after a failed build. |
| 2. Rebuild only | Builds the plugin. |
| 3. Repackage | Packages the DLL that is already built. |
| 4. Exit | Closes the window. |

The build uses the newest MSBuild that `vswhere.exe` finds. To package a DLL that is already built, you can also run this on any OS:

```
python scripts/package_release.py
```

The script packages `plugin/x64/Release/SentientSands.dll`. Use `--dll` to package a different DLL. Before it packages, it prints the mod version and the build time, size, and SHA-256 of the DLL. It stops if the DLL does not import the Visual C++ 2010 runtime, because a DLL from a newer toolset crashes the game.

The script writes `dist/SentientSandsRebirth-<version>.zip` and takes the version from `mod/mod.info`. The zip contains the mod files, the DLL, the server, and an embedded Windows Python runtime with the packages from `server/requirements.txt` already installed. Players unzip it into `Kenshi/mods/` and do not install Python. The zip leaves out `server/config/`, `server/data/campaigns/`, and `server/data/user_templates/`, so it never contains your keys or your campaigns, and an update never replaces a player's keys, campaigns, or templates. It also leaves out `SentientSands_Config.ini`, so an update keeps a player's settings.

The script runs on any OS. It needs Python 3 with `pip`, and internet access to python.org and PyPI. Downloaded runtimes are cached in `dist/cache/`.

Each release must ship the same runtime and packages unless a commit changes them. `PYTHON_VERSION` in `scripts/package_release.py` sets the embedded runtime, and `server/requirements.txt` pins every package, the transitive ones included. Some pinned packages ship a separate wheel for each Python version, so change `PYTHON_VERSION` and the pins in the same commit, and run the script once to confirm that pip finds a wheel for each pin.
