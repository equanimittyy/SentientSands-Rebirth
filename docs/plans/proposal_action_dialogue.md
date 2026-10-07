# Proposal: Action Dialogue

Status: Draft for review

## 1. Summary

Chat sends no game actions since the action tags were turned off. The plugin still runs the actions (`ExecuteQueuedActions` in `plugin/game/GameActions.cpp:224`). Only the debug commands of the chat send them, through the pipe before the reply line (`server/chat/routes.py:228`).

In this plan, the player marks a chat thread as an action dialogue. An action dialogue uses its own system prompt instead of the chat system prompt (`server/data/prompts/prompt_system.txt`). A chat thread without the mark stays plain chat, with no game actions.

[Sections 2 to 4](#2-entry) hold the decided design, and [section 6](#6-open-questions) holds what is open.

## 2. Entry

A player line that starts with `!` marks its chat thread as an action dialogue. The mark holds for the rest of the chat thread, until the action dialogue [ends](#end). A chat thread is one speaker with one NPC in one mode, and it ends after `conversation_timeout_minutes` without a chat (`server/chat/routes.py:255`).

The characters right after the `!` decide the result. A word after the `!` runs up to the first character that is not a letter. Letters and words are case-insensitive, so `!B` names BARTER.

| After the `!` | Result |
|---|---|
| A space | An action dialogue with no category ([No category](#no-category)) |
| One letter or the full word of a category ([section 3](#3-categories)) | An action dialogue in that category |
| `e` or `end` | The [end](#end) of the action dialogue |
| Any other letter or word | A [failure](#failure), with no LLM call |
| Any other character, such as `!` or `?`, or nothing | Plain chat, with no mark |

| Line | Result |
|---|---|
| `! Hand me over all your money!` | No category |
| `!t Hand me over your cats!` | THREATEN |
| `!b I'd like to trade` | BARTER |
| `!barter` | BARTER |
| `!end Thanks` | End |
| `!o` | Failure |
| `!I see the light` | Failure |
| `!light the way` | Failure |
| `!!!` | Plain chat |
| `!?!?!` | Plain chat |
| `!` | Plain chat |

The text after the mark can be empty, as in `!barter`.

The debug commands of the chat keep the `/` mark (`server/chat/routes.py:176`), so the two marks do not collide.

### No category

A line with no category costs two LLM calls: a classify call, and then the action dialogue call. A line that names its category skips the classify call.

The classify call is as lean as possible. Its prompt holds only the player's line and a numbered list of the categories, and it tells the model to output only the number of one choice. The list follows the map of [section 3](#3-categories):

1. A threat or demand
2. A request to trade for items, services or help
3. A request to join the squad
4. An order to leave
5. A gift that asks for nothing back
6. None of these

The last choice is an escape hatch: it lets the model reject a line that fits no category, instead of forcing the line into one.

The classify call fails when the call gives an error, or when its output is not the number of a category. The escape hatch is therefore a [failure](#failure) too.

### Failure

A failure sends no action dialogue call. The server replies with the line "X didn't understand what you meant.", where X is the name of the NPC. The chat thread then ends, and the server keeps neither the player's line nor the reply, so a failed line leaves no junk thread.

## 3. Categories

| Letter | Word | Category | The player's request |
|---|---|---|---|
| `t` | `threaten` | THREATEN | Threatens the NPC, demands its cats or items, or challenges it to a fight. |
| `b` | `barter` | BARTER | Makes a deal with the NPC: buys or sells an item, or asks for a service, such as a release from prison or the treatment of wounds. The player can haggle over the price. |
| `r` | `recruit` | RECRUIT | Asks the NPC to join the squad. |
| `d` | `dismiss` | DISMISS | Tells the NPC to leave: a squad member leaves the squad, and an NPC outside the squad goes away. |
| `g` | `gift` | GIFT | Gives the NPC an item or cats, and asks for nothing back. |

BARTER offers a deal only when its gate holds. The gates read three fields of the game context only.

| Deal | Gate |
|---|---|
| A release from prison | The speaker's `character_state` (`plugin/game/Context.cpp:650`) is `imprisoned`. |
| Treatment | The speaker's `health` (`plugin/game/Context.cpp:651`) is `Injured` or `Crippled` (`GetHealthStatus` in `plugin/game/Context.cpp:114`). |
| A trade of items | The NPC's `job` (`plugin/game/Context.cpp:722`) is a trade job. |

## 4. Action dialogue

### Reply

The model under the action prompt starts each reply with the tag of the category that it reads in the player's request:

- `[BARTER] So what can I do for you?`
- `[THREATEN] Don't hurt me! I'll give you what you want, just spare me!`

The player's mark names the category for the model. A later line of the chat thread can name another category, for example `!t` after `!b`. A later line without a mark stays in the action dialogue, and the tag of the reply shows how the model reads it.

The chat window shows system messages about the action dialogue, in the shape of the chat status messages such as "{name} is thinking..." (`NotifyChatStatus` in `plugin/ui/ChatWindow.cpp:62`). They show that the chat thread is an action dialogue, and the category of each reply.

### Outcome

Code steers the outcome of an action dialogue with deterministic nudges from the game state. The nudges are open ([section 6](#6-open-questions)).

### End

The action dialogue ends at the first of these events:

- The model sends a close signal in its reply.
- The player sends `!e` or `!end`, for example `!end Thanks`.
- The chat thread ends: `conversation_timeout_minutes` pass without a chat, or the player starts another chat thread, for example with another NPC.

The category sets when the model sends the close signal:

| Category | The model closes |
|---|---|
| BARTER, for a release or a treatment | When the release or the treatment is done |
| BARTER, for a trade of items | When the player confirms the trade |
| THREATEN | When the NPC complies, or when it attacks the player |

## 5. Speaker

The plugin gives most actions to the first character of the squad, not to the squad member that spoke: `ATTACK` (`plugin/main.cpp:489`), the release (`plugin/main.cpp:704` and `:715`), and the item and cat handlers (`plugin/game/GameActions.cpp:496`, `:608`, `:702`, `:717`, and `:996`). The chat window knows the speaker (`plugin/ui/ChatWindow.cpp:160`), but the action line does not carry it. Each design of the actions must therefore send the speaker with the action, so that the action acts on the squad member that spoke.

## 6. Open questions

1. What is the close signal of the model? When does the model close RECRUIT, DISMISS, and GIFT?
2. After a close signal or `!end`, does the chat thread go on as plain chat, or does it end?
3. Which deterministic nudges does code give the model, and from which facts?
4. What does the action system prompt hold, and how does a reply send its actions to the plugin?
5. Which values of `job` count as a trade job?
6. Does GIFT fold into BARTER?
