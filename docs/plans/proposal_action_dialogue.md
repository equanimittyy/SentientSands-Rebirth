# Proposal: Action Dialogue

Status: Draft for review

## 1. Summary

Chat sends no game actions since the action tags were turned off. The plugin still runs the actions (`ExecuteQueuedActions` in `plugin/game/GameActions.cpp:245`). Only the debug commands of the chat send them, through the pipe before the reply line (`server/chat/routes.py:250`).

In this plan, the player marks a chat thread as an action dialogue. An action dialogue uses its own system prompt instead of the chat system prompt (`server/data/prompts/prompt_system.txt`). A chat thread without the mark stays plain chat, with no game actions.

[Sections 2 to 4](#2-entry) hold the decided design, and [section 6](#6-open-questions) holds what is open.

## 2. Entry

A player line that starts with `!` marks its chat thread as an action dialogue. The mark holds for the rest of the chat thread, until the action dialogue [ends](#end). A chat thread is one NPC in one mode, and the squad members that speak to that NPC share the thread (`server/chat/routes.py:278`). The chat thread ends after `conversation_timeout_minutes` without a chat (`server/chat/memory.py:13`).

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

The debug commands of the chat keep the `/` mark (`server/chat/routes.py:198`), so the two marks do not collide.

### No category

A line with no category costs two LLM calls: a classify call, and then the action dialogue call. A line that names its category skips the classify call.

The classify call is as lean as possible. Its prompt holds only the player's line and a numbered list of the categories, and it tells the model to output only the number of one choice. The list follows the map of [section 3](#3-categories):

1. A threat or demand
2. A request to trade for items, services or help, or a gift
3. A request to join the squad
4. A request to follow the squad for a time
5. An order to leave
6. None of these

The last choice is an escape hatch: it lets the model reject a line that fits no category, instead of forcing the line into one.

The classify call fails when the call gives an error, or when its output is not the number of a category. The escape hatch is therefore a [failure](#failure) too.

### Failure

A failure sends no action dialogue call. The server replies with the line "X didn't understand what you meant.", where X is the name of the NPC. The chat thread then ends, and the server keeps neither the player's line nor the reply, so a failed line leaves no junk thread.

## 3. Categories

| Letter | Word | Category | The player's request |
|---|---|---|---|
| `t` | `threaten` | THREATEN | Threatens the NPC, demands its cats or items, or challenges it to a fight. |
| `b` | `barter` | BARTER | Makes a deal with the NPC: buys or sells an item, gives an item or cats for nothing, or asks for a service, such as a release from prison or the treatment of wounds. The player can haggle over the price. A gift is a trade at no price, and the NPC is glad to take it. |
| `r` | `recruit` | RECRUIT | Asks the NPC to join the squad. |
| `f` | `follow` | FOLLOW | Asks the NPC to follow the squad for a time. Unlike RECRUIT, the hire is temporary. |
| `d` | `dismiss` | DISMISS | Tells the NPC to leave: a squad member leaves the squad, and an NPC outside the squad goes away. The NPC never refuses. |

FOLLOW reuses the game's mercenary hire: the NPC follows the squad under a hire contract, as a hired mercenary does. The plugin already reads such a contract as `temporary_follower` (`plugin/game/Context.cpp:362`).

BARTER offers a deal only when its gate holds. The gates read only the speaker's `character_state` and `health`, and the NPC's Current Job.

| Deal | Gate |
|---|---|
| A release from prison | The speaker's `character_state` (`plugin/game/Context.cpp:675`) is `imprisoned`. |
| Treatment | The speaker's `health` (`plugin/game/Context.cpp:676`) is `Injured` or `Crippled` (`GetHealthStatus` in `plugin/game/Context.cpp:115`). |
| A trade of items, or a gift | The NPC's Current Job (`current_job` in `server/chat/current_job.py:41`) is `Trading`, `Running a shop`, or `Travelling as a trader`. |

## 4. Action dialogue

### Reply

The model under the action prompt starts each reply with the tag of the category that it reads in the player's request:

- `[BARTER] So what can I do for you?`
- `[THREATEN] Don't hurt me! I'll give you what you want, just spare me!`

The player's mark names the category for the model. A later line of the chat thread can name another category, for example `!t` after `!b`. A later line without a mark stays in the action dialogue, and the tag of the reply shows how the model reads it.

The chat window shows system messages about the action dialogue, in the shape of the chat status messages such as "{name} is thinking..." (`NotifyChatStatus` in `plugin/ui/ChatWindow.cpp:59`). They show that the chat thread is an action dialogue, and the category of each reply.

### Outcome

Code sets the hard limits of an action dialogue, and the model decides inside them. Before each call, code reads a lean from the game state and puts it in the prompt as one of three bands: likely to agree, could go either way, or likely to refuse. The lean is a band, not a percentage, because a small model follows a plain band better.

The words of the player can move a close call, but they cannot break a hard limit, because the server checks each offer against the hard limits ([Offer](#offer)). The facts of the lean and the hard limits of each category are open ([section 6](#6-open-questions)).

### Offer

An NPC that agrees to a deal makes an offer. The model ends its reply with an offer tag, which holds the actions of the deal under the names that the plugin already runs, for example `[OFFER: GIVE_CATS: 200]` or `[OFFER: TAKE_CATS: 3000; GIVE_ITEM: Katana]`. Each action that moves cats, items, or characters needs an offer: the handover of THREATEN, each deal of BARTER, RECRUIT, and FOLLOW. Only `ATTACK` and `LEAVE` run at once.

The server checks the offer against the hard limits, and it drops and logs an offer that breaks one. It holds a valid offer and sends it to the plugin after the lines of the reply. The offer goes to the squad member that spoke the line that the offer answers ([section 5](#5-speaker)).

The plugin shows the offer in a popup with the buttons Accept and Decline. The server writes the text of the popup from the checked offer, never from the words of the model, so the popup always shows the real deal. The text is "X offers A for B": X is the NPC, A is what the NPC gives, and B is what the player gives. When the player gives nothing, the text has no "for B".

| Deal | Popup |
|---|---|
| THREATEN, the handover | Bandit offers 200 cats and a Katana. |
| BARTER, the NPC sells | Trader offers a Katana for 3,000 cats. |
| BARTER, the NPC buys | Trader offers 1,200 cats for your Katana. |
| BARTER, a release | Guard offers your release for 500 cats. |
| BARTER, a treatment | Doctor offers treatment for 300 cats. |
| BARTER, a gift | Trader offers thanks for your Katana. |
| RECRUIT | Drifter offers to join your squad for 1,500 cats. |
| RECRUIT, with no fee | Drifter offers to join your squad. |

| Answer | Result |
|---|---|
| Accept | The plugin sends the answer to the server, and the server sends the actions of the offer through the pipe, as for any action. The take actions go before the give actions, because the plugin skips a give after a failed take in the same batch (`transactionFailed` in `plugin/game/GameActions.cpp:253`). The action dialogue and the chat thread then end. |
| Decline | The popup asks the player for a reply, and a blank reply is "No.". The reply goes to the NPC as the next line of the action dialogue, and the action dialogue goes on. |

While an offer waits, the chat waits for the answer. The chat window takes no new line to any NPC, and it shows the status "Answer X's offer first.". No other chat thread or radiant conversation starts, and the chat thread does not time out. The game does not pause.

A save load removes the popup and the offer, and it ends the action dialogue, because the load can undo the world that the offer rests on.

### End

The action dialogue ends at the first of these events:

- The model sends a close signal in its reply.
- The player accepts an offer, or a save loads while an offer waits ([Offer](#offer)).
- The player sends `!e` or `!end`, for example `!end Thanks`.
- The chat thread ends: `conversation_timeout_minutes` pass without a chat, or the player starts another chat thread, for example with another NPC.

A close signal, `!end`, or an accepted offer also ends the chat thread.

The category sets when the action dialogue closes:

| Category | The action dialogue closes |
|---|---|
| BARTER | When the player accepts an offer |
| THREATEN | When the player accepts an offer, or when the NPC attacks the player |
| RECRUIT | When the NPC refuses and makes no offer, or when the player accepts an offer |
| DISMISS | When the NPC leaves |

## 5. Speaker

The chat window names the speaker in the player's line (`plugin/ui/ChatWindow.cpp:214`), and the plugin keeps that squad member as `g_lastChattingPlayerHand` (`plugin/main.cpp:251`). Only `SPAWN_ITEM` acts on that squad member (`plugin/game/GameActions.cpp:1018`). The other actions act on the first character of the squad:

| Actions | Why they act on the first character |
|---|---|
| `GIVE_ITEM`, `TAKE_ITEM`, `GIVE_CATS`, `TAKE_CATS` | The plugin queues each action for the speaker (`plugin/main.cpp:522`, `:557`, `:587`, and `:577`), but its handler ignores the speaker (`plugin/game/GameActions.cpp:630`, `:518`, `:724`, and `:739`). |
| `ATTACK`, `FOLLOW_PLAYER`, and the release | The plugin queues each action for the first character (`plugin/main.cpp:489`, `:673`, `:704`, and `:715`). |

The squad members that take turns share one chat thread ([section 2](#2-entry)), so another squad member can speak before the reply to a line arrives. `g_lastChattingPlayerHand` then names the wrong squad member. Each design of the actions must therefore send the speaker with the action, so that the action acts on the squad member that spoke.

## 6. Open questions

1. What is the close signal of the model?
2. Which facts make the lean of each category, and which hard limits does code set for each category?
3. What does the action system prompt hold, and how do an offer, `ATTACK`, and `LEAVE` reach the plugin?
4. How does the plugin start a hire contract? The plugin only reads one now, and no in-game test covers a contract yet ([development.md](../info/development.md#probes)).
5. When does the action dialogue close for FOLLOW?
