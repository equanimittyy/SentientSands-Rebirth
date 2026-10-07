# Proposal: Action Dialogue

Status: Draft for review

## 1. Summary

Chat sends no game actions since the action tags were turned off. The plugin still runs the actions (`ExecuteQueuedActions` in `plugin/game/GameActions.cpp:224`). Only the debug commands of the chat send them, through the pipe before the reply line (`server/chat/routes.py:228`).

In this plan, the player marks a chat thread as an action dialogue. An action dialogue uses its own system prompt instead of the chat system prompt (`server/data/prompts/prompt_system.txt`). A chat thread without the mark stays plain chat, with no game actions.

[Section 2](#2-entry) gives the entry shape, which is decided. The rest of the design is open ([section 5](#5-open-questions)).

## 2. Entry

A player line that starts with `!` marks its chat thread as an action dialogue. The mark holds for the whole chat thread, not only for that line. A chat thread is one speaker with one NPC in one mode, and it ends after `conversation_timeout_minutes` without a chat (`server/chat/routes.py:255`).

The characters right after the `!` decide the result. A word after the `!` runs up to the first character that is not a letter.

| After the `!` | Result |
|---|---|
| A space | An action dialogue with no category ([No category](#no-category)) |
| One letter or the full word of a category ([section 3](#3-categories)) | An action dialogue in that category |
| Any other letter or word | A [failure](#failure), with no LLM call |
| Any other character, such as `!` or `?` | Plain chat, with no mark |

| Line | Result |
|---|---|
| `! Hand me over all your money!` | No category |
| `!t Hand me over your cats!` | THREATEN |
| `!b I'd like to trade` | BARTER |
| `!barter` | BARTER |
| `!o` | Failure |
| `!I see the light` | Failure |
| `!light the way` | Failure |
| `!!!` | Plain chat |
| `!?!?!` | Plain chat |

The text after the mark can be empty, as in `!barter`.

The debug commands of the chat keep the `/` mark (`server/chat/routes.py:176`), so the two marks do not collide.

### No category

A line with no category costs two LLM calls: a classify call, and then the action dialogue call. A line that names its category skips the classify call.

The classify call is as lean as possible. Its prompt holds only the player's line and a numbered list of the categories, and it tells the model to output only the number of one choice. The list follows the draft map of [section 3](#3-categories):

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

This map is a draft. Only `t` for THREATEN, `b` for BARTER, and the scope of BARTER are decided.

| Letter | Word | Category | The player's request |
|---|---|---|---|
| `t` | `threaten` | THREATEN | Threatens the NPC, demands its cats or items, or challenges it to a fight. |
| `b` | `barter` | BARTER | Makes a deal with the NPC: buys or sells an item, or asks for a service, such as a release from prison or the treatment of wounds. The player can haggle over the price. |
| `r` | `recruit` | RECRUIT | Asks the NPC to join the squad. |
| `d` | `dismiss` | DISMISS | Tells the NPC to leave: a squad member leaves the squad, and an NPC outside the squad goes away. |
| `g` | `gift` | GIFT | Gives the NPC an item or cats, and asks for nothing back. |

BARTER gates its deals on three fields of the game context only: the speaker's `character_state` and `health`, and the NPC's `job`. For example, an imprisoned speaker can ask for a release, and a hurt speaker can ask for treatment.

## 4. Speaker

The plugin gives most actions to the first character of the squad, not to the squad member that spoke: `ATTACK` (`plugin/main.cpp:489`), the release (`plugin/main.cpp:704` and `:715`), and the item and cat handlers (`plugin/game/GameActions.cpp:496`, `:608`, `:702`, `:717`, and `:996`). The chat window knows the speaker (`plugin/ui/ChatWindow.cpp:160`), but the action line does not carry it. Each design of the actions must therefore send the speaker with the action, so that the action acts on the squad member that spoke.

## 5. Open questions

1. What ends the action dialogue: the end of the chat thread, a line with its own mark, or a done action?
2. Can a later line of the chat thread name another category, for example `!t` after `!b`?
3. Are the letters and the words case-insensitive? Is a line of only `!` plain chat?
4. Who decides whether an action happens, and at what price: code with fixed rules from the game state, or the model under the action prompt?
5. What does the action system prompt hold, and how does a reply send its actions to the plugin?
6. Which values of `character_state` (`plugin/game/Context.cpp:650`), `health` (`:651`), and `job` (`:722`) open each deal of BARTER?
7. Does the chat window show that a chat thread is an action dialogue?
8. Is the draft map of [section 3](#3-categories) right?
