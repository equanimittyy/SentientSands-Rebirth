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

When `SENTIENT_SANDS_MOD_DIR` names an installed mod folder, each build copies the DLL into it. To test the build, start the game normally. The plugin writes `SentientSands_SDK.log` in the Kenshi folder. At each game start, it renames the log of the previous game to `SentientSands_SDK.old.log`, so the folder holds the logs of two games at most.

## Server

To run the server from the repo:

```
python -m pip install -r server/requirements.txt
python server/scripts/kenshi_llm_server.py
```

The web app is at `http://127.0.0.1:5000/`. Add `--open-browser` to open it when the server is ready and no tab of it is open, as the plugin does at game start.

From the repo, the server keeps its INI in `mod/SentientSands_Config.ini` and writes its logs and campaigns under `server/`. On first start, it also creates `server/user/llm_config.json` for your API keys. Git ignores all of these files.

`visual_debugger.py` needs Tkinter, which the embedded runtime does not include. Run it with a system Python.

The dev container cannot build the plugin. It also cannot run the server, because it has no `pip` and its firewall blocks PyPI.

## Tests

```
python -m unittest discover -s server/tests
```

The tests use only the standard library, so they run in the dev container. Code that imports Flask or `requests` cannot be tested there, so keep testable logic in modules that do not import them.

## Probes

Some questions of the plans need data from the game. The plugin writes probe lines to `SentientSands_SDK.log` for them. All probe functions are in `plugin/game/Context.cpp`, and `OnChatSendClick` (`plugin/ui/ChatWindow.cpp`) calls them. A probe is removed when the change that needs its answer is built.

| Line | Written | Function | Answers |
|---|---|---|---|
| `ID_PROBE` | At each chat, for the target NPC | `LogNpcIdentity` | Which candidate ID of an NPC stays the same ([proposal_npc_ids.md](../plans/proposal_npc_ids.md#9-not-yet-verified)) |
| `ZONE_PROBE` | At each chat, for the target NPC. The first chat also lists every zone record. | `LogNpcZone` | Which slot of the zone object (`AreaBiomeGroup`) holds its zone record, so that the context can name the zone, for example Stenn Desert. `ZoneManager::getBiome` gives only the ground type, such as Canyonland FlatTop, so it cannot name the zone. |
| `FACTION_PROBE` | At the first chat of each game, one line for each faction | `LogFactionList` | Whether the string ID of each faction stays the same when the mod list changes ([proposal_data_layers.md](../plans/proposal_data_layers.md#not-yet-verified)) |
| `SQUAD_PROBE` | At each chat | `LogCurrentSquad` | Whether `PlayerInterface::getCurrentPlatoon` gives the squad that the player selected, which the speaker picker needs |

One test session gives the data for all of them. The label of each step names the question that it answers.

1. **Setup.** Build the plugin, and load a save that has two squads.
2. **IDs and zones.** In a town, chat with a unique NPC, for example Beep, and with a generic NPC, for example a barman. Then chat with someone outside a town in two different zones, and note the zone name that the map shows for each.
3. **Squad.** Select the other squad, and chat again.
4. **Save and load: does the handle survive a load?** Save, load the save, and chat with the same NPCs again.
5. **Town reload: does the handle survive an unload?** Travel far from the town until it unloads, come back, and chat with the same generic NPC again.
6. **Recruit: does the handle survive a move into the player's squad?** Recruit an NPC, and chat with it again.
7. **Mod list, optional: do the IDs survive a change of the mod list?** Change the mod list, start the game again, and chat with the same NPCs. The restart moves the earlier lines to `SentientSands_SDK.old.log`.
8. **Collect.** Copy `SentientSands_SDK.log` and `SentientSands_SDK.old.log` from the Kenshi folder into `temp/` in the repo, which git ignores.

A generic NPC has only its handle as an ID, so a handle that changes in step 4, 5, or 6 makes the NPC a stranger to its campaign: it loses its profile, its dialogue memory, and its relation to the player. A unique NPC uses the ID of its template, which only the removal of its mod changes.

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

The script writes `dist/SentientSandsRebirth-<version>.zip` and takes the version from `mod/mod.info`. The zip contains the mod files, the DLL, the server, and an embedded Windows Python runtime with the packages from `server/requirements.txt` already installed. Players unzip it into `Kenshi/mods/` and do not install Python. The zip leaves out `server/user/` and `server/config/providers.json`, so it never contains your keys and never replaces a player's keys. It also leaves out `SentientSands_Config.ini`, so an update keeps a player's settings.

The script runs on any OS. It needs Python 3 with `pip`, and internet access to python.org and PyPI. Downloaded runtimes are cached in `dist/cache/`.

Each release must ship the same runtime and packages unless a commit changes them. `PYTHON_VERSION` in `scripts/package_release.py` sets the embedded runtime, and `server/requirements.txt` pins every package, the transitive ones included. Some pinned packages ship a separate wheel for each Python version, so change `PYTHON_VERSION` and the pins in the same commit, and run the script once to confirm that pip finds a wheel for each pin.
