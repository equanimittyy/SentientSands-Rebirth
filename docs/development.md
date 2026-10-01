# Development

[architecture.md](architecture.md) describes the parts and how they connect. This page covers how to build, run, and release them.

## Plugin

The repo does not contain a build project for the plugin. To build `SentientSands.dll`, set up a 64-bit Windows DLL project as follows:

- Compile every `.cpp` file under `plugin/`.
- Put the KenshiLib `Include` directory on the include path. The sources include `<kenshi/...>` and `<core/...>` from it, and `<mygui/...>` and `<ogre/...>` from the KenshiLib dependencies.
- Link against KenshiLib, and use the compiler toolset that [KenshiLib](https://github.com/KenshiReclaimer/KenshiLib) documents. The plugin shares C++ types with the game, so a different toolset breaks the ABI.

Includes between plugin files are relative (`../core/Utils.h`), so the plugin folders need no include path entry.

To test a build, copy the DLL into an installed `Kenshi/mods/SentientSands/` folder and start the game through `RE_Kenshi.exe`.

## Server

To run the server from the repo:

```
python -m pip install -r server/requirements.txt
python server/scripts/kenshi_llm_server.py
```

From the repo, the server reads `mod/SentientSands_Config.ini` and writes its logs and campaigns under `server/`. Git ignores those runtime files.

`visual_debugger.py` needs Tkinter, which the embedded runtime does not include. Run it with a system Python.

The dev container cannot build the plugin. It also cannot run the server, because it has no `pip` and its firewall blocks PyPI.

## Release

```
python scripts/package_release.py --dll path/to/SentientSands.dll
```

The script writes `dist/SentientSands-<version>.zip` and takes the version from `mod/mod.info`. The zip contains the mod files, the DLL, the server, and an embedded Windows Python runtime with the packages from `server/requirements.txt` already installed. Players unzip it into `Kenshi/mods/` and do not install Python.

The script runs on any OS. It needs Python 3 with `pip`, and internet access to python.org and PyPI. Downloaded runtimes are cached in `dist/cache/`.

Each release must ship the same runtime and packages unless a commit changes them. `PYTHON_VERSION` in `scripts/package_release.py` sets the embedded runtime, and `server/requirements.txt` pins every package, the transitive ones included. Some pinned packages ship a separate wheel for each Python version, so change `PYTHON_VERSION` and the pins in the same commit, and run the script once to confirm that pip finds a wheel for each pin.
