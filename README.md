# Sentient Sands Rebirth (Kenshi AI Mod)

Welcome to Sentient Sands Rebirth, a mod that brings the world of Kenshi to life using AI! This mod allows you to interact dynamically with NPCs, generating unscripted, highly contextual encounters based on the world state, character backgrounds, and your actions.

## 🛠️ Requirements

Before installing Sentient Sands Rebirth, you must have the following installed:

1. **[RE_Kenshi](https://github.com/BFrizzleFoShizzle/RE_Kenshi/releases) v0.3.5 or later**: The script extender that loads our C++ plugin into Kenshi. Its installer also installs KenshiLib, the library that our C++ hooks use, so you do not install KenshiLib separately.

---

## 🚀 Installation Guide

### Step 1: Install RE_Kenshi
1. Download the standard `RE_Kenshi_vX.X.X.zip` archive from the releases page. Do not use the `_loose` archive.
2. Extract the complete archive and run the `RE_Kenshi_vX.X.X.exe` installer inside it.
3. Start Kenshi normally. The main menu must show the RE_Kenshi version. If it does not, RE_Kenshi is not installed.

### Step 2: Install Sentient Sands Rebirth
1. Download the Sentient Sands Rebirth release zip.
2. Extract it so that the `SentientSandsRebirth` folder is inside your `Kenshi/mods/` directory.
   *(Expected path: `...\Kenshi\mods\SentientSandsRebirth\SentientSandsRebirth.mod`)*
3. Ensure that `SentientSands.dll` is present in your `Kenshi\mods\SentientSandsRebirth\` directory. Our `RE_Kenshi.json` file will automatically instruct RE_Kenshi to load it from here.

The release includes its own Python runtime (`server\python\`), so you do not need to install Python or any packages.

If the original Sentient Sands is also installed, disable it in the mod launcher. Both mods use the same server port and pipe, so only one can run at a time.

### Step 3: Launching the Game
1. In the Kenshi mod launcher, check **Sentient Sands Rebirth**.
2. Start Kenshi normally. RE_Kenshi loads the plugin, and the plugin starts the AI server.
3. Your default browser opens the web panel. Set up a provider and a model there before you talk to an NPC (see below).

---

## ⚙️ Configuring AI Providers & Models

Sentient Sands Rebirth connects to an embedded Python server running alongside your game. It supports any API that uses the standard OpenAI-compatible format (OpenRouter, local Ollama servers, LM Studio, etc.).

You configure the mod in the web panel at `http://127.0.0.1:5000/`. It opens in your default browser when Kenshi starts, unless a tab of it is already open. You can also open it with **Open Web Panel** in the in-game SSR HUB (F8). When the panel is already open, this button brings its browser window to the front instead of opening a second tab. If the game cannot bring that window to the front, for example because the panel is not the active tab of the window, the button opens a second tab. To stop it from opening on start, clear **Open this web panel on start** on its Settings page.

### Providers
On the **Models** page, a provider is one OpenAI-compatible endpoint: a base URL and an API key. Add a provider from a preset, or pick **Custom** and give it a name, then fill in its fields. The page never shows a stored key, only whether a key is set and its last four characters. Leave the key field empty to keep the stored key. **Rename** keeps the key and updates the profiles that use the provider. The `player2` type also needs a game key, the game ID that you register with Player2.

### Profiles
A profile is one model on one provider. It holds the provider, the exact model ID that the provider expects (for example `anthropic/claude-3.5-sonnet`), a timeout, and optional extra request parameters as JSON. **List models** gets the model IDs from the provider, so the Model ID field can suggest them as you type. **Test** sends a short request to the profile as the page shows it, so you can test before you save. **Test all** tests each profile in turn.

### Tasks
Each task (chat, radiant conversations, NPC profiles, and world events) has an ordered list of profiles. The server tries them in order, and moves to the next profile after an error, a timeout, or an empty reply. List a profile twice to retry it. The game stops waiting after 60 s, so keep each deadline below that.

The server keeps this configuration in `server/user/llm_config.json`. A mod update does not replace it, so your keys stay.

---

## Development

See [docs/info/architecture.md](docs/info/architecture.md) for how the plugin, the server, and the mod files fit together, and [docs/info/development.md](docs/info/development.md) for building, running, and releasing.
