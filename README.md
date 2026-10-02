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
2. Extract it so that the `SentientSands` folder is inside your `Kenshi/mods/` directory.
   *(Expected path: `...\Kenshi\mods\SentientSands\SentientSands.mod`)*
3. Ensure that `SentientSands.dll` is present in your `Kenshi\mods\SentientSands\` directory. Our `RE_Kenshi.json` file will automatically instruct RE_Kenshi to load it from here.

The release includes its own Python runtime (`server\python\`), so you do not need to install Python or any packages.

### Step 3: Launching the Game
1. In the Kenshi mod launcher, check **Sentient Sands Rebirth**.
2. Start Kenshi normally. RE_Kenshi loads the plugin, and the plugin starts the AI server.

---

## ⚙️ Configuring AI Providers & Models

Sentient Sands Rebirth connects to an embedded Python server running alongside your game. It supports any API that uses the standard OpenAI-compatible format (OpenRouter, local Ollama servers, LM Studio, etc.).

You can add your own custom providers and models without modifying any code. Both configuration files are located in the mod folder at:
`Kenshi/mods/SentientSands/server/config/`

### Adding a New Provider
Edit `providers.json`. The server creates it from `default_providers.json` on its first start, and a mod update does not replace it, so your keys stay. A provider strictly requires an `api_key` and a `base_url`.

**Example `providers.json`:**
```json
{
    "openrouter": {
        "api_key": "sk-or-your-api-key-here",
        "base_url": "https://openrouter.ai/api/v1"
    },
    "ollama_local": {
        "api_key": "ollama",
        "base_url": "http://localhost:11434/v1"
    }
}
```

### Adding a New Model
Edit `models.json`. This file links a user-friendly name (which appears in the game's UI) to the exact model string the provider expects.

**Example `models.json`:**
```json
{
    "Llama-3-8B-Instruct": {
        "provider": "ollama_local",
        "model": "llama3"
    },
    "Claude-3.5-Sonnet": {
        "provider": "openrouter",
        "model": "anthropic/claude-3.5-sonnet"
    }
}
```

1. **Top-level key** (e.g., `"Claude-3.5-Sonnet"`): The name you will select in the in-game Settings menu.
2. **`provider`**: Must perfectly match a top-level key from your `providers.json`.
3. **`model`**: The exact model identifier required by the provider.

### Selecting Your Model In-Game
Once you have added models to your config, launch the game, open the Sentient Sands Rebirth **Settings Window**, and select your desired model from the dropdown menu!

---

## Development

See [docs/info/architecture.md](docs/info/architecture.md) for how the plugin, the server, and the mod files fit together, and [docs/info/development.md](docs/info/development.md) for building, running, and releasing.
