# Proposal: NPC Job

Status: Problem. No design chosen.

## 1. Summary

The `Job` field of a profile and the `job` key of the game context have one name, but they hold three kinds of value: a profession, the standing AI tasks of the NPC, and the name of its character template ([section 2](#2-current-state)). The prompts give each kind to the LLM as the job of the NPC. A profile that the server rolls keeps the value of the first meeting, so an NPC that the player first meets on a patrol keeps the patrol as its job in every later chat and in its bio.

## 2. Current state

The sources of the value:

| Source | Value | Where |
|---|---|---|
| A character of a world template | A profession or a role that a person wrote, for example "Noble of the United Cities" or "Fishmonger running his family's fish shop" | `server/world_templates/kenshi_ssr_vanilla/characters/*.json` |
| The context of one NPC | The names of the permajobs of the NPC, joined with commas, or `None` when it has none. Permajobs are the permanent AI tasks of a character, for example a patrol of a town or a stand at a shopkeeper node | `GetDetailedContext` in `plugin/game/Context.cpp` |
| Each NPC of a banter request | The name of the character template of the NPC (`data->name`) | `playerUpdate_hook` in `plugin/main.cpp` |

The mod itself changes the permajobs, so the live value changes with the orders that the NPC gets:

- An action tag of a routine, for example `PATROL_TOWN`, `WANDER_TOWN`, or `STAND_AT_SHOPKEEPER_NODE`, adds a permanent job (`ExecuteQueuedActions` in `plugin/game/GameActions.cpp`).
- A dismissed recruit gets back the permajobs that it had before the player recruited it. When it had none, it gets `WANDER_TOWN` in a town or `WANDERER` outside a town.

The uses of the value:

| Use | Value | Where |
|---|---|---|
| The rolled profile at the first meeting | The `job` key of the request that meets the NPC first: the permajobs for a chat, the template name for a banter | `new_profile` in `server/scripts/kenshi_llm_server.py` |
| A later request | The server replaces only `None` or `Unknown`, so the value of the first meeting stays | `get_character_data` |
| The chat prompt | `JOB: {job}` from the profile | `describe_npc`, `server/prompts/npc_chat_template.txt` |
| The bio prompt | `JOB: {job}` from the profile | `write_bio`, `server/prompts/prompt_profile_generation.txt` |
| The scene text | "Your job right now: {job}." from the live value when it differs from the profile. "You are a trader." when the live value contains "shopkeeper" | `npc_text` in `server/scripts/scene_text.py` |
| General rules | The LLM fills a blank field only with details that fit the job. The NPC offers help only when its job calls for it | `server/prompts/prompt_system.txt`, `server/prompts/response_rules.txt` |
| Views | The `Job` line of the profile in the in-game Dialogue Library and the `Job` field of the web editor | `get_history`, `server/web/editor.js` |

## 3. Problems

- One field holds two meanings. A template profile holds a profession. A rolled profile holds an AI routine or a template name. The prompts present both as a profession.
- The value of the first meeting stays. A rolled profile keeps the routine that the NPC had when the player met it, and the bio prompt gets that routine as the job.
- The kind of value depends on the first request. A banter stores the template name and a chat stores the permajobs, so two NPCs of one template can get different kinds of `Job`.
- The live value works as an activity, but the scene text calls it a job. For a banter profile, the stored template name never equals the live permajobs, so the scene line comes in every chat.

## 4. Options

- Give the live value a name that says what it is, for example `routine`, and use it only in the scene text as the current activity. Keep `Job` of the profile for a profession. A rolled profile starts with no `Job`, and the bio LLM or the player writes it.
- Make the `job` key of a banter NPC use the permajobs, as the context of one NPC does, or give the template name a key of its own.

## 5. Open questions

1. Which strings does `getPermajobName` return: display names or the names of the task types? The KenshiLib headers are not in the repo. One context dump in a game log answers this. The "shopkeeper" check in `npc_text` depends on the answer.
2. Should the bio LLM write the `Job` of a rolled profile, together with `Personality`, `Backstory`, and `SpeechQuirks`?
3. Is the template name of any use to the prompt, for example as a hint for the profession?
