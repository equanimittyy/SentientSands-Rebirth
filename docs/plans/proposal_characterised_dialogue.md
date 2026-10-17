# Proposal: Characterised Player Dialogue

## 1. Summary

When the player turns on Characterised player dialogue on the Settings page, each chat line of the player goes through one LLM call before the NPC hears it. The call rewrites the line as the speaker would say it. The rewrite keeps the intent and the meaning of the line, and it changes only the words, to fit the speech habits and the personality of the speaker.

- The NPC hears the rewrite, the chat thread stores it, and the speech bubble of the speaker shows it.
- A line of `!` and a space runs the classify call on the raw line (`server/chat/routes.py:460`). The action call then takes the rewrite of the text after the mark.
- The setting is off by default.

## 2. Setting

| Part | Value |
|---|---|
| Settings key | `characterised_dialogue`, default `False` (`SETTINGS_DEFAULTS`, `server/core/settings.py:63`) |
| INI key | `CharacterisedDialogue` (`INI_KEY_MAP`, `server/core/settings.py:14`) |
| Plugin global | `g_characterisedDialogue`, default `false` (`plugin/core/Globals.cpp`) |
| Settings page | A check box in the Conversations fieldset (`server/dashboard/web/index.html:78`) |

- The plugin reads the INI key in `LoadPluginConfig` (`plugin/core/Utils.cpp:383`), and it takes a change through `SET_CONFIG` (`plugin/main.cpp:140`). The save route sends `SET_CONFIG` as it does for `enable_welcome` (`server/core/routes.py:260`), and `push_settings_to_plugin` (`server/core/settings.py:157`) sends the value at each server start.
- The plugin needs the setting, because it shows the first bubble of the line (see [section 5](#5-speech-bubbles)).
- The tip of the check box: "Your character says each of your chat lines in their own words. The lines take a moment longer to appear."

## 3. Rewrite

`server/chat/player_voice.py` holds the rewrite, so that `chat` in `server/chat/routes.py` only calls it.

- The rewrite runs after the check of a failure (`server/chat/routes.py:468`) and before the check of `!end` (`server/chat/routes.py:472`).
- A line that the game refuses keeps the raw line: a line while an offer waits (`server/chat/routes.py:440`), a blocked line (`server/chat/routes.py:454`), and a failure, also of the classify call. The game tells the player that the line failed, so the bubble shows what the player typed, and the classify call read the same words.
- A line that the world hears gets the rewrite, also when no chat call follows: `!end` with text after the mark, DISMISS of a hired follower (`server/chat/routes.py:484`), and a yell that no one can answer (`server/chat/routes.py:520`). So with the setting on, DISMISS makes one call.
- The rewrite reads the profile of the speaker with `get_character_data` (`server/chat/characters.py:118`), because `chat` reads the profiles only after DISMISS and the yell checks (`server/chat/routes.py:538`).
- The rewrite takes the `rephrase` task (see [section 4](#4-llm-route-and-time-budget)).
- These lines go to the NPC without a call:
  - A line that starts with `/`.
  - A line with no words outside `*actions*`.
  - A line of an animal speaker.
- These lines get the rewrite: talk, whisper, and yell lines, a talk to itself, `!b` lines and the lines of the Barter window (also "How about this deal?"), and the reply to a declined offer, which goes to `/chat` as the next line.
- A call that gets no reply, and a rewrite that leaves out a number of the raw line, give the raw line instead. The check compares each number of digits, without thousands separators, because a lost "200 cats" breaks a trade, and code checks it more reliably than the model.
- The server cleans the rewrite as a chat reply (`reply_text.spoken`), which removes the quotes and a label with the name of the speaker.
- Each rewrite writes a log line with the raw line and the rewrite, for example `CHAT: Beep says "Can I have some water?" as "Oi. Spare some water?"`.

### Prompt

`server/data/prompts/prompt_player_voice.txt` holds the request, filled by `fill_prompt`. The Prompts page lists it in the Conversations group (`server/dashboard/web/prompts.js`).

| Part | Source |
|---|---|
| The speaker | The name, the race, and `describe_persona` of its profile (`server/chat/prompts.py:109`): the personality, the backstory, and the speech quirks |
| The listener | The name of the NPC, or "everyone" for a yell at everyone, and the mode, so that a whisper reads quietly and a yell loudly |
| The context | The last line of the chat thread, so that a short answer, such as "yes", keeps its meaning |
| The language | `language_instruction()` (`server/chat/prompts.py:117`) |
| The line | The raw line, without its mark |

- The request tells the model to keep each name, number, item, and place, to keep each `*action*` as it is, and to write only the line.
- The prompt holds no scene and no lore, because a model with more context adds facts that the player did not say.

### Raw line and rewrite

| Reads the raw line | Reads the rewrite |
|---|---|
| The classify call (`server/chat/routes.py:460`) | The chat call and the action call |
| The names of a yell (`radiant.named`, `server/chat/routes.py:523`) | The stored line of the speaker and each overheard copy |
| The lore search, `names_record`, and the directions (`server/chat/routes.py:616` to `server/chat/routes.py:622`) | The later lines of a yell (`spoken` of `yell_talk`) |
| The price guide (`said`, `server/chat/routes.py:634`) | The memory of the chat thread |
| The towns that the plugin names (`NamedTowns`) | The speech bubble of the speaker |

- The code that matches words reads the raw line, because the rewrite adds words of the speaker's manner, such as "by the Holy Flame", that would find lore that the player did not ask for, and it can change an item word, such as "water" to "drink".

## 4. LLM route and time budget

- `TASKS` (`server/chat/llm_config.py:14`) gets `rephrase`, with `max_tokens` 512, `temperature` 0.7, and a deadline of 15 s. `default_route` (`server/chat/llm_config.py:52`) keeps a deadline that `TASKS` gives, and else uses `DEFAULT_DEADLINE`.
- A configuration of an earlier version gets the default route for the new task (`server/chat/llm.py:79`), so the file needs no upgrade.
- The Models page shows the task as "Player lines", with the hint "Your character's own words for each chat line that you send, when Characterised player dialogue is on." (`TASK_LABELS` and `TASK_HINTS` in `server/dashboard/web/llm.js`).
- `run_route` (`server/chat/llm_router.py:21`) gets an `until` parameter, and its deadline is the earlier of `until` and the start plus the deadline of the route. `call_llm` passes `until` on.
- `chat` passes `until` as `started` plus `DEFAULT_DEADLINE` to the classify call, the rewrite, and the chat or action call. The plugin stops waiting for `/chat` after 60 s (`plugin/core/Comm.cpp:94`), and two or three calls with their own deadlines can each take most of 55 s.

## 5. Speech bubbles

With the setting on, the bubbles of a line come in this order:

1. When the player sends the line, the plugin shows "..." over the speaker instead of the line (`PLAYER_SAY` in `SendChatLine`, `plugin/ui/ChatWindow.cpp:361`). A line that starts with `/` and a line of only a mark still show no bubble.
2. The server runs the rewrite.
3. The server sends `PLAYER_SAY: Name: <line>` with the rewrite, or with the raw line when the line gets no call or the call fails. The bubble of the speaker changes from "..." to the line.
4. The server sends the "{name} is thinking..." status and `NPC_SAY: npc|key: ...`. A yell already sends them just before its chat call (`server/chat/routes.py:650`), and with the setting on, every mode sends them there, so the "..." shows over the NPC that answers.
5. The reply plays as it does today.

- With the setting on, the plugin does not show the "..." of the NPC and the status when it sends the line (`ChatResponseThread`, `plugin/ui/ChatWindow.cpp:171`). `SendChatLine` notes this in `ChatTask` (`plugin/ui/ChatWindow.cpp:37`), because `ChatResponseThread` runs off the game thread.
- The "..." of the speaker still sends the name of the speaker, so `TakePlayerSpeaker` sets the squad member that the actions of the reply fall back to (`plugin/main.cpp:289`).
- The "..." and the line of the speaker share one bubble, so with the "..." of the NPC no third bubble ends one of them (`KeepTwoBubbles`, `plugin/game/GameActions.cpp:186`).
- A line that stops before step 3 (a line while an offer waits, a blocked line, or a failure) gets the raw line, without its mark, as the bubble of the speaker from `reply` in `chat`. Without it, the "..." would stay for the whole bubble life. A line that the plugin refuses, for example because the NPC is too far away, stops before step 1.
- `!end`, DISMISS, and a yell that no one can answer stop after step 3 and before step 4, so no "..." shows over an NPC that does not answer with a chat call.
- With the setting off, the bubbles do not change.

## 6. Documentation

- `docs/info/architecture.md` gets a section, `## Characterised dialogue`, before `## Line pacing`, with the rules of sections 3 to 5.
- [LLM routing](../info/architecture.md#llm-routing) adds `rephrase` to the list of tasks.

## 7. Tests

| Test file | Checks |
|---|---|
| A new `server/tests/test_player_voice.py` | Each line of [section 3](#3-rewrite) that gets no call gets no call. A call with no reply gives the raw line. A rewrite without a number of the raw line gives the raw line, and "2,000" matches "2000". The server removes quotes and the label of the speaker. `bubble` gives the words of the bubble of the plugin. |
| `server/tests/test_llm_router.py` | An `until` before the deadline of the route ends the chain at `until`. |
| `server/tests/test_llm_config.py` | The default route of `rephrase` has a deadline of 15 s, and the other tasks keep 55 s. |

- The plugin gets a syntax check with `g++ -fsyntax-only` in the dev container. The build and a test of the bubble order in the game need Windows.

## 8. Rejected

| Alternative | Reason |
|---|---|
| The raw bubble, and only the NPC hears the rewrite | The bubble then shows words that the character did not say, and the stored line differs from the bubble. |
| The raw bubble first, which the rewrite then replaces | The player sees the raw words for the time of the call. |
| The `chat` route for the rewrite | One route for both calls cannot give the rewrite a small, fast model. |
