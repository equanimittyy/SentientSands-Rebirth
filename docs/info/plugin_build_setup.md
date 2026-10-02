# Plugin Build Setup

This page sets up a Windows machine to build `SentientSands.dll` and to test it in Kenshi. Do the sections in order. After the setup, [development.md](development.md#plugin) covers each later build.

The plugin shares C++ types with Kenshi, which was built with Visual C++ 2010. For this reason, the build needs the 2010 compiler and the exact library versions that RE_Kenshi uses. A newer compiler or a different library version gives a DLL that crashes the game.

## 1. Install RE_Kenshi

RE_Kenshi loads the plugin into the game. Its installer also installs `KenshiLib.dll`, so KenshiLib needs no separate install in the game.

1. Check that your Kenshi version is one that the current [RE_Kenshi release](https://github.com/BFrizzleFoShizzle/RE_Kenshi/releases) supports. The release title names the versions, for example "For Kenshi 1.0.65 + 1.0.68 (Steam) and 1.0.65 + 1.0.68 (GOG)".
2. Download the standard archive, `RE_Kenshi_v<version>.zip`. Do not use the `_loose` archive.
3. Extract the complete archive, and run the `RE_Kenshi_v<version>.exe` installer in it.
4. Start Kenshi normally. The main menu must show `RE_Kenshi v<version> - Kenshi 1.0.<x> - x64 (Newland)`. If it does not, the install failed.

## 2. Install the compilers

1. Install Visual Studio 2019 or later with the **Desktop development with C++** workload. This gives the editor and MSBuild.
2. Install the Visual C++ 2010 x64 compiler. Use one of these routes. Both give the same compiler.

   | Route | Install, in this order | Toolset |
   |---|---|---|
   | A | Visual Studio 2010 Professional, then Visual Studio 2010 SP1 | `v100`, the project default |
   | B | Visual Studio 2010 Express, then the Windows SDK 7.1, then Visual Studio 2010 SP1, then the Visual C++ 2010 SP1 Compiler Update for the Windows SDK 7.1 | `Windows7.1SDK` |

   On route B, SP1 removes the x64 compilers of the SDK, and the compiler update puts them back. If the SDK 7.1 installer fails, uninstall each newer Microsoft Visual C++ 2010 Redistributable, then try again. The [KenshiLib README](https://github.com/BFrizzleFoShizzle/KenshiLib#compiling) points to copies of Visual Studio 2010 on the Wayback Machine.

## 3. Fill deps/

The build reads KenshiLib and Boost from `deps/` at the repo root. Git ignores this folder. It holds exactly four folders: `Include\` and `Libraries\` from KenshiLib, and `boost\` and `lib64-msvc-10.0\` from Boost.

1. Choose the KenshiLib version that the installed RE_Kenshi ships. On the [KenshiLib releases page](https://github.com/BFrizzleFoShizzle/KenshiLib/releases), the notes of that release say so, for example "KenshiLib v0.5.0 - this is the version shipped in RE_Kenshi 0.3.5". The requirements in `README.md` give the matching minimum RE_Kenshi version for players. When you change the KenshiLib version, change that minimum too.
2. Download two archives of that release:

   | Archive | What you take from it |
   |---|---|
   | `https://github.com/BFrizzleFoShizzle/KenshiLib/archive/refs/tags/v<version>.zip`, the "Source code (zip)" link of the release | The `Include\` and `Libraries\` folders |
   | `KenshiLib_v<version>.zip`, a release asset | The `KenshiLib.lib` file |

   The tag archive matches `KenshiLib.lib` of the same release. **Code > Download ZIP** on the repo page gives the default branch instead, which can be ahead of the release.

3. From the source archive, copy the `Include\` and `Libraries\` folders into `deps\KenshiLib\`.
4. From the release asset, copy `KenshiLib.lib` into `deps\KenshiLib\Libraries\`.
5. Get Boost 1.60.0 built with the Visual C++ 2010 x64 compiler. boost.org offers only source archives, so use the prebuilt installer that the Boost project publishes on SourceForge:
   1. Download [`boost_1_60_0-msvc-10.0-64.exe`](https://sourceforge.net/projects/boost/files/boost-binaries/1.60.0/boost_1_60_0-msvc-10.0-64.exe/download) and run it. Any install folder works, for example the default `C:\local\boost_1_60_0`.
   2. From the install folder, copy the `boost\` and `lib64-msvc-10.0\` folders into `deps\boost_1_60_0\`.

   If the installer is not available, build the libraries from the boost.org source archive instead. This needs the compiler from section 2. In the extracted `boost_1_60_0\` folder, run:

   ```
   bootstrap.bat
   b2 toolset=msvc-10.0 address-model=64 variant=release threading=multi link=static runtime-link=shared --with-thread --with-filesystem --with-system --with-chrono --with-date_time stage
   ```

   Then copy `boost\` into `deps\boost_1_60_0\`, and copy the contents of `stage\lib\` into `deps\boost_1_60_0\lib64-msvc-10.0\`.

6. Check that `deps\` matches this layout. `deps\KenshiLib\` and `deps\boost_1_60_0\` each contain their two folders and nothing else.

   ```
   deps\
     KenshiLib\
       Include\                   the complete folder from the source archive
       Libraries\                 the complete folder from the source archive, plus KenshiLib.lib
         KenshiLib.lib
         mygui\MyGUIEngine_x64.lib
         ogre\OgreMain_x64.lib
     boost_1_60_0\
       boost\                     the Boost headers
       lib64-msvc-10.0\           the built Boost libraries
   ```

These are all the libraries that the plugin needs. The Ogre and MyGUI files in KenshiLib match the game, so the build uses those. The plugin hooks game functions through `KenshiLib::AddHook`, so it needs no MinHook.

## 4. Build the plugin

1. Open the **Developer Command Prompt** of your Visual Studio version, and go to the repo root.
2. Run the build:

   ```
   msbuild plugin\SentientSands.vcxproj
   ```

   On route B, add `-p:PlatformToolset=Windows7.1SDK`.
3. Check that `plugin\x64\Release\SentientSands.dll` exists.

## 5. Install the mod in Kenshi

The plugin starts the Python server from its own mod folder. A test therefore needs the complete mod, not only the DLL.

1. Build a release zip that contains your DLL: run `package_release.cmd` in the repo root. This needs Python 3 with `pip`, and internet access.

2. Extract `dist\SentientSands-<version>.zip` into `Kenshi\mods\`. The result is `Kenshi\mods\SentientSands\`.
3. In the Kenshi launcher, open the mod list and enable **Sentient Sands**.
4. Set `SENTIENT_SANDS_MOD_DIR` to that mod folder. Then each later build copies the DLL into it. Open a new command prompt after this command:

   ```
   setx SENTIENT_SANDS_MOD_DIR "C:\path\to\Kenshi\mods\SentientSands"
   ```

## 6. Test in game

1. Start Kenshi normally, and check the RE_Kenshi text on the main menu.
2. Load a save. Press **F8** to open the AI panel, or press **\\** near an NPC to open the chat.
3. If something fails, read these logs:

   | Log | Contents |
   |---|---|
   | `SentientSands_SDK.log` in the Kenshi folder | The plugin log |
   | `Kenshi\mods\SentientSands\server\logs\server.log` | The server log |
   | **Options > Mods > RE_Kenshi Settings**, debug log tab | RE_Kenshi's own log, which shows plugin load errors |

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `MSB4019: The imported project "...Microsoft.Cpp.Default.props" was not found` | The Visual Studio install has no C++ workload. | Section 2, step 1 |
| `MSB8020: The build tools for v100 ... cannot be found` | The 2010 x64 compiler is missing, or route B was built without its toolset option. | Section 2, step 2, and section 4, step 2 |
| `C1083: Cannot open include file` for a `kenshi/`, `ogre/`, `mygui/`, or `boost/` header | `deps\` is incomplete. | Section 3 |
| `LNK1104: cannot open file 'KenshiLib.lib'` or `'libboost_...-vc100-mt-1_60.lib'` | A library is not where the project looks. | Section 3, steps 4 to 6 |
| `MSB3021` or `MSB3027`: unable to copy `SentientSands.dll` | Kenshi is running and locks the DLL. | Close Kenshi, then build again. |
| The main menu has no RE_Kenshi text | RE_Kenshi is not installed. | Section 1 |
| No `SentientSands_SDK.log` after the game starts | The mod is not enabled, or RE_Kenshi did not load the plugin. | Section 5, step 3, then the RE_Kenshi debug log |
| The game crashes when it loads the plugin | The DLL was built with a different compiler, or against a KenshiLib version that the game does not have. | Sections 2 and 3 |
