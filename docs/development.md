# Development

[architecture.md](architecture.md) describes the parts and how they connect. This page covers how to build, run, and release them.

## Plugin

`plugin/SentientSands.vcxproj` builds `SentientSands.dll`. It builds only Release|x64 with the Visual C++ 2010 toolset (`v100`). The plugin shares C++ types with the game, which was built with Visual C++ 2010, so a different toolset breaks the ABI.

Set up each build machine once:

1. Install Visual Studio 2019 or later with the "Desktop development with C++" workload.
2. Install the Visual C++ 2010 x64 compiler. Use one of these routes, which give the same compiler:
   - Visual Studio 2010 Professional, then Visual Studio 2010 SP1. The project's `v100` toolset uses this compiler.
   - Visual Studio 2010 Express, the Windows SDK 7.1, Visual Studio 2010 SP1, and the Visual C++ 2010 SP1 Compiler Update for the Windows SDK 7.1, in that order. SP1 removes the SDK's x64 compilers, and the update puts them back. Add `-p:PlatformToolset=Windows7.1SDK` to the build command.
3. Choose the KenshiLib release that the current RE_Kenshi release ships. The KenshiLib release notes name it, for example "KenshiLib v0.5.0 - this is the version shipped in RE_Kenshi 0.3.5". A plugin built against that release runs on every RE_Kenshi install of that version, with no separate KenshiLib download.
4. Fill `deps/` at the repo root. Git ignores it.

   | Path | Source |
   |---|---|
   | `deps\KenshiLib\` | The "Source code (zip)" of the chosen [KenshiLib release](https://github.com/BFrizzleFoShizzle/KenshiLib/releases), unpacked so that `Include\` and `Libraries\` are directly inside. |
   | `deps\KenshiLib\Libraries\KenshiLib.lib` | `KenshiLib.lib` from the `KenshiLib_v<version>.zip` asset of the same release. The headers and the `.lib` must come from the same release. |
   | `deps\boost_1_60_0\` | The install folder of `boost_1_60_0-msvc-10.0-64.exe` from the [Boost binaries on SourceForge](https://sourceforge.net/projects/boost/files/boost-binaries/1.60.0/). It holds the `boost\` headers and the `lib64-msvc-10.0\` libraries. |

5. Optional: set `SENTIENT_SANDS_MOD_DIR` to an installed mod folder, for example `Kenshi\mods\SentientSands`. Each build then copies the DLL there.

To build, open the project in Visual Studio and build it, or run this in a Developer Command Prompt:

```
msbuild plugin\SentientSands.vcxproj
```

The DLL goes to `plugin\x64\Release\SentientSands.dll`. Kenshi locks the DLL while it runs, so close the game before a build that copies it.

The project lists each source file, because the Visual Studio IDE does not support wildcards in project items. A new file that you add through Solution Explorer goes into the list. A new file that you create outside Visual Studio must be added to the project, or the link fails.

Includes between plugin files are relative (`../core/Utils.h`), so the plugin folders need no include path entry.

To test a build, put the DLL in the installed mod folder and start the game normally, with RE_Kenshi installed. The plugin writes `SentientSands_SDK.log` in the Kenshi folder.

## Server

To run the server from the repo:

```
python -m pip install -r server/requirements.txt
python server/scripts/kenshi_llm_server.py
```

From the repo, the server reads `mod/SentientSands_Config.ini` and writes its logs and campaigns under `server/`. On first start, it also creates `server/config/providers.json` for your API keys. Git ignores all of these files.

`visual_debugger.py` needs Tkinter, which the embedded runtime does not include. Run it with a system Python.

The dev container cannot build the plugin. It also cannot run the server, because it has no `pip` and its firewall blocks PyPI.

## Tests

```
python -m unittest discover -s server/tests
```

The tests use only the standard library, so they run in the dev container. Code that imports Flask or `requests` cannot be tested there, so keep testable logic in modules that do not import them.

## Release

```
python scripts/package_release.py --dll plugin/x64/Release/SentientSands.dll
```

The script writes `dist/SentientSands-<version>.zip` and takes the version from `mod/mod.info`. The zip contains the mod files, the DLL, the server, and an embedded Windows Python runtime with the packages from `server/requirements.txt` already installed. Players unzip it into `Kenshi/mods/` and do not install Python. The zip leaves out `server/config/providers.json`, so it never contains your keys and never replaces a player's keys.

The script runs on any OS. It needs Python 3 with `pip`, and internet access to python.org and PyPI. Downloaded runtimes are cached in `dist/cache/`.

Each release must ship the same runtime and packages unless a commit changes them. `PYTHON_VERSION` in `scripts/package_release.py` sets the embedded runtime, and `server/requirements.txt` pins every package, the transitive ones included. Some pinned packages ship a separate wheel for each Python version, so change `PYTHON_VERSION` and the pins in the same commit, and run the script once to confirm that pip finds a wheel for each pin.
