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

You configure the mod in the web panel at `http://127.0.0.1:5000/`. It opens in your default browser when Kenshi starts, unless a tab of it is already open. You can also open it with **Open Web Panel** in the in-game SSR HUB (F8). This button always opens a new tab. To stop it from opening on start, clear **Open this web panel on start** on its Settings page.

### Providers
On the **Models** page, a provider is one OpenAI-compatible endpoint: a base URL and an API key. To add a provider, give it a name and choose its type, then fill in its fields. The page never shows a stored key, only whether a key is set. Leave the key field empty to keep the stored key. To rename a provider or a profile, open its card and press the pencil next to its name. A renamed provider keeps its key, and its profiles move with it. The `player2` type also needs a game key, the game ID that you register with Player2.

### Profiles
A profile is one model on one provider, and the page shows it in the card of that provider. It holds the exact model ID that the provider expects (for example `anthropic/claude-3.5-sonnet`), a timeout, and optional extra request parameters as JSON. **List models** gets the model IDs from the provider, so the Model ID field can suggest them as you type. **Test** sends a short request to the profile as the page shows it, so you can test before you save.

### Default profile
The **Default LLM Profile** box at the top of the **Models** page sets the profile that every task uses. Each task list shows the default in bold. You can move it up or down, but you cannot remove it. To remove the default profile or its provider, choose another default first.

### Tasks
Each task (chat, radiant conversations, NPC profiles, and world events) has an ordered list of profiles. The server tries them in order, and moves to the next profile after an error, a timeout, or an empty reply. List a profile twice to retry it. The game stops waiting after 60 s, so keep each deadline below that.

The server keeps this configuration in `server/user/llm_config.json`. A mod update does not replace it, so your keys stay.

### Campaigns and world templates
The **Campaigns** page lists your campaigns and creates a new one from a world template. It also edits the current campaign: the overview that every NPC knows, the factions, and the rumors and events of the world. To switch campaigns, use the Campaign Manager in the SSR HUB.

The **Editor** page edits world templates: the overview, history, factions, characters, and world entries, such as towns and zones, of a world. Vanilla Kenshi ships with the mod and is read-only, so duplicate it to make your own. A new campaign copies its template, so a template edit changes only the campaigns that you create later. The server keeps your templates in `server/user/world_templates/`, and a mod update keeps them.

---

## Credits

Sentient Sands Rebirth builds on the original Sentient Sands mod and on its Kayak lore system.

SentientSands Kayak by Harvicus and Pineaxe.

| Project | Links |
|---|---|
| Sentient Sands | [Source](https://github.com/harvicusdev-glitch/SentientSands), [Nexus Mods](https://www.nexusmods.com/kenshi/mods/1872), [Steam Workshop](https://steamcommunity.com/sharedfiles/filedetails/?id=3675880187) |
| Kayak | [Source](https://github.com/Starswimmer/Kayak), [Nexus Mods](https://www.nexusmods.com/kenshi/mods/2067) |

---

## Development

See [docs/info/architecture.md](docs/info/architecture.md) for how the plugin, the server, and the mod files fit together, and [docs/info/development.md](docs/info/development.md) for building, running, and releasing.
