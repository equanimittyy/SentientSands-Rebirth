# Proposal: Action Dialogue Framework

## 1. Summary

Chat sends no game actions since the action tags were turned off. The plugin still runs the actions (`ExecuteQueuedActions` in `plugin/game/GameActions.cpp:245`). Only the debug commands of the chat send them, through the pipe before the reply line (`server/chat/routes.py:250`).

In this plan, the player marks a chat thread as an action dialogue. An action dialogue uses its own system prompt instead of the chat system prompt (`server/data/prompts/prompt_system.txt`), and a new LLM route (`TASKS` in `server/chat/llm_config.py:14`) that its classify call ([No category](#no-category)) shares. A chat thread without the mark stays plain chat, with no game actions.

This doc holds the framework that all categories share. Each category has its own doc for its own constraints ([section 3](#3-categories)). [Sections 2 to 5](#2-entry) hold the decided design, [section 6](#6-open-questions) holds what is open, and [section 7](#7-probe) holds the in-game checks of the probe.

## 2. Entry

A player line that starts with `!` marks its chat thread as an action dialogue. The mark holds for the rest of the chat thread. A chat thread is one NPC in one mode, and the squad members that speak to that NPC share the thread (`server/chat/routes.py:278`). An action dialogue belongs to one speaker instead: a line of another squad member to the NPC starts a new chat thread, and the action dialogue [ends](#end). The chat thread ends after `conversation_timeout_minutes` without a chat (`server/chat/memory.py:13`).

The characters right after the `!` decide the result. A word after the `!` runs up to the first character that is not a letter. Letters and words are case-insensitive, so `!B` names BARTER.

| After the `!` | Result |
|---|---|
| A space | An action dialogue with no category ([No category](#no-category)) |
| One letter or the full word of a category ([section 3](#3-categories)) | An action dialogue in that category, or a [block](#blocked) when a gate of the category fails |
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

The text after the mark can be empty, as in `!barter`. Such a line opens the action dialogue and sends no LLM call.

An action dialogue works in each chat mode. The mode sets who overhears its lines, as in plain chat (`server/chat/routes.py:286`).

The debug commands of the chat keep the `/` mark (`server/chat/routes.py:198`), so the two marks do not collide.

### No category

A line with no category costs two LLM calls: a classify call, and then the action dialogue call. A line that names its category skips the classify call.

The classify call is as lean as possible. Its prompt holds only the player's line and a numbered list of the categories, and it tells the model to output only the number of one choice.

The list leaves out each category that the game state already rules out, because a shorter list confuses a small model less. Code numbers the remaining choices from 1 in the order of this table, and it maps the number of the answer back to its category.

| Choice | Category | Left out when |
|---|---|---|
| A threat or demand | THREATEN | The speaker is `imprisoned` ([threaten.md](threaten.md#2-gate)). |
| A request to trade items, a gift, or a plea for charity | BARTER | Never |
| A request to treat wounds | HEAL | The speaker is not `Injured` or `Crippled`, the NPC carries no first aid item, or the NPC is `imprisoned` ([heal.md](heal.md#2-deal)). |
| A request to be freed from prison or slavery | LIBERATE | The speaker is neither `imprisoned` nor `enslaved`, the NPC is `imprisoned`, or the speaker is a slave and the NPC is a guard ([liberate.md](liberate.md#2-deal)). |
| A request to join the squad | RECRUIT | The speaker or the NPC is `imprisoned` or `enslaved`, or the NPC leads its faction ([recruit.md](recruit.md#2-gate)). |
| A request to follow the squad for a time | FOLLOW | The speaker or the NPC is `imprisoned` or `enslaved`, or the NPC leads its faction ([recruit.md](recruit.md#2-gate)). |
| An order for a hired follower to leave | DISMISS | The NPC is not a temporary follower ([dismiss.md](dismiss.md#2-gate)). |

The fee of a deal never leaves out a choice, because code does not know the fee before the call.

The last choice is always "None of these". It is an escape hatch: it lets the model reject a line that fits no category, instead of forcing the line into one. A line that asks for a left-out category fits no choice, so it ends in the escape hatch.

The classify call fails when the call gives an error, or when its output is not the number of a category. The escape hatch is therefore a [failure](#failure) too.

### Failure

A failure sends no action dialogue call. The server replies with the line "X didn't understand what you meant.", where X is the name of the NPC. The chat thread then ends, and the server keeps neither the player's line nor the reply, so a failed line leaves no junk thread.

### Blocked

A line that names a category whose gate fails is blocked, so a named mark cannot open a category that the classify call would leave out. A blocked line sends no LLM call. The chat window shows a system message ([Reply](#reply)) that names the failed gate, for example "You can't threaten anyone while imprisoned.". The server keeps neither the player's line nor the message, so the chat thread stays as it was. The doc of each category holds its gates.

A knockout blocks every category, because a knocked-out character cannot talk. While the speaker or the NPC is knocked out (`character_state` is `unconscious`, `plugin/game/Context.cpp:658`), each line that starts with `!` and each line of an action dialogue is blocked, before any classify call. The message names who is knocked out, for example "Bandit is unconscious.". The block holds for plain chat too: a line from a knocked-out speaker or to a knocked-out NPC sends no LLM call, and the chat window shows the same message. Radiant conversations already leave out knocked-out characters (`CanTalk` in `plugin/game/Context.cpp:495`).

An animal makes no deals, so each line that starts with `!` to an animal (`animal` in `plugin/game/Context.cpp:705`) is blocked too, before any classify call. Plain chat with an animal stays.

No action works on a member of the player faction, so each line that starts with `!` to an NPC in the player faction (`in_squad` in `server/chat/routes.py:290`) is blocked too, before any classify call. The message is, for example, "Hobbs is a member of your faction.". A temporary follower keeps its own faction, so DISMISS still reaches it.

## 3. Categories

| Letter | Word | Category | The player's request | Doc |
|---|---|---|---|---|
| `t` | `threaten` | THREATEN | Threatens the NPC, demands its cats or items, or challenges it to a fight. | [threaten.md](threaten.md) |
| `b` | `barter` | BARTER | Trades items with the NPC, gives it a gift, or begs it for charity. | [barter.md](barter.md) |
| `h` | `heal` | HEAL | Asks the NPC to treat the speaker's wounds. | [heal.md](heal.md) |
| `l` | `liberate` | LIBERATE | Asks the NPC to free the speaker from prison or slavery. | [liberate.md](liberate.md) |
| `r` | `recruit` | RECRUIT | Asks the NPC to join the squad. | [recruit.md](recruit.md) |
| `f` | `follow` | FOLLOW | Asks the NPC to follow the squad for a time. | [follow.md](follow.md) |
| `d` | `dismiss` | DISMISS | Ends the hire of an NPC that follows the squad through FOLLOW. | [dismiss.md](dismiss.md) |

The doc of a category holds its gates, its hard limits, its lean, the popups of its offers, and the end events of its action dialogue.

## 4. Action dialogue

### Reply

The model under the action prompt starts each reply with the tag of the category that it reads in the player's request:

- `[BARTER] So what can I do for you?`
- `[THREATEN] Don't hurt me! I'll give you what you want, just spare me!`

The player's mark names the category for the model. A later line of the chat thread can name another category, for example `!t` after `!b`. A later line without a mark keeps the category of the action dialogue and runs no classify call, so code always knows which lean and which parts of the prompt the call needs. A reply tag that names another category changes nothing.

The chat window shows system messages about the action dialogue, in the shape of the chat status messages such as "{name} is thinking..." (`NotifyChatStatus` in `plugin/ui/ChatWindow.cpp:59`). They show that the chat thread is an action dialogue, and the category of each reply.

### Outcome

Code sets the hard limits of an action dialogue, and the model decides inside them. Before each call, code adds up the + and - bonuses of facts in the game state into a lean. The prompt states the lean as a thought of the NPC, in one of three bands: likely to agree, could go either way, or likely to refuse. The lean is a band, not a percentage, because a small model follows a plain band better.

| Lean | Band |
|---|---|
| +2 or more | Likely to agree |
| -1 to +1 | Could go either way |
| -2 or less | Likely to refuse |

The words of the player can move a close call, but they cannot break a hard limit, because the server checks each offer against the hard limits ([Offer](#offer)). The doc of each category holds the facts of its lean and its hard limits.

BARTER, HEAL, LIBERATE, RECRUIT, and FOLLOW count the NPC's profile `Relation` on one scale:

| Relation | Bonus |
|---|---|
| 60 or more | +2 |
| 25 to 59 | +1 |
| -59 to -25 | -1 |
| -60 or less | -2 |

The action prompt keeps the judgment of plain chat (`judgment` in `server/chat/routes.py:313`): each reply ends with `[JUDGMENT: n]`, and the NPC's `Relation` changes by n. A threat thus costs relation.

A guard is an NPC whose Current Job (`current_job` in `server/chat/current_job.py:41`) is `Guarding the town`, `Guarding a building`, `Patrolling the town`, `Keeping the peace`, or `Working as a slaver`. LIBERATE and RECRUIT read it.

### Offer

An NPC that agrees to a deal makes an offer. The model ends its reply with an offer tag, which holds the actions of the deal under the names that the plugin already runs, for example `[OFFER: GIVE_CATS: 200]` or `[OFFER: TAKE_CATS: 3000; GIVE_ITEM: Katana]`. Each action that moves cats, items, or characters needs an offer: the handover of THREATEN, each deal of BARTER, HEAL, LIBERATE, RECRUIT, and FOLLOW. Only `ATTACK`, `LEAVE`, and a free treatment of HEAL ([heal.md](heal.md#2-deal)) run at once.

The server checks the offer against the hard limits, and it drops and logs an offer that breaks one. The reply already reads as a deal, so the chat window then shows the system message "X made an offer it can't keep.", and the action dialogue goes on. It holds a valid offer and sends it to the plugin after the lines of the reply. The offer goes to the squad member that spoke the line that the offer answers ([section 5](#5-speaker)).

The plugin shows the offer in a popup with the buttons Accept and Decline. The server writes the text of the popup from the checked offer, never from the words of the model, so the popup always shows the real deal. The text is "X offers A for B": X is the NPC, A is what the NPC gives, and B is what the player gives. When the player gives nothing, the text has no "for B". For example, "Bandit offers 200 cats and a Katana.".

BARTER shows its offers in a barter window instead ([barter.md](barter.md#barter-window)), because a trade can list many cats and items on both sides. The other categories need no full transaction window, so they keep the one line.

| Answer | Result |
|---|---|
| Accept | The plugin sends the answer to the server, and the server sends the actions of the offer through the pipe, as for any action. The action dialogue and the chat thread then end. |
| Decline | The popup asks the player for a reply, and a blank reply is "No.". The reply goes to the NPC as the next line of the action dialogue, and the action dialogue goes on. |

While an offer waits, the chat waits for the answer. The chat window takes no new line to any NPC, and it shows the status "Answer X's offer first.". No other chat thread or radiant conversation starts, and the chat thread does not time out. The game does not pause.

While the reply to a line of an action dialogue is pending, the chat window also takes no new line to any NPC, and it shows the status "X is still thinking.". The chat window does not wait for a reply before it sends the next line (`ChatResponseThread` in `plugin/ui/ChatWindow.cpp:70`), so without the block a second line could bring a second offer.

Before it runs an accepted offer, the plugin checks that each side still has the cats and the items of the offer. The game does not pause while the offer waits, and `TAKE_CATS` takes all the cats of the player when they are fewer than its count (`plugin/game/GameActions.cpp:747`). When a check fails, the plugin runs no action of the offer, and the chat window shows a system message that names why, for example "You no longer have 500 cats.". The server does the same when an answer arrives for an offer that it no longer holds, for example after a restart of the server. In both cases the action dialogue ends.

The tags of the model never reach the plugin as they are. The server builds each action from the data of the plugin, and it sends the plugin a game-altering payload, such as an order to an NPC. `ATTACK` and `LEAVE` reach the plugin the same way.

A save load removes the popup and the offer, and it ends the action dialogue, because the load can undo the world that the offer rests on.

A knockout or a death of the speaker or the NPC while an offer waits also removes the popup and the offer, and it ends the action dialogue, because a knocked-out or dead character cannot make or take a deal. The plugin sees each knockout in `setProneState_hook` (`plugin/main.cpp:982`), and each death in `declareDead_hook` (`plugin/main.cpp:968`).

### Memory

The server writes a line into the chat thread for each action that runs and for each answer to an offer. It writes the line from the checked offer, for example "(Drifter accepted: Bandit gives 200 cats.)" or "(Drifter declined: Bandit offered 200 cats.)". The model thus sees on the next turn which offer the player declined.

The line counts as an exchange, so a chat thread that ends in a deal is not deleted as a chat thread of one exchange (`server/chat/memory.py:89`).

A chat thread that holds an action dialogue gets its memory from its own memory prompt instead of `prompt_thread_memory.txt` (`write_memory` in `server/chat/memory.py:22`), so that the memory keeps each action and each deal.

### End

The action dialogue ends at the first of these events:

- The model ends its reply with the ending tag `[END]`, as a refusal ends a reply with `[REFUSE]` ([recruit.md](recruit.md#refusal)).
- An end event of the category occurs, for example the NPC attacks in THREATEN. The doc of each category sets its end events.
- The player accepts an offer, or a save loads while an offer waits ([Offer](#offer)).
- The speaker or the NPC is knocked out or dies while an offer waits ([Offer](#offer)).
- The player sends `!e` or `!end`, for example `!end Thanks`. The line sends no LLM call, and the server does not keep it.
- The action dialogue call gives an error. The chat window shows the error status of plain chat, "X could not respond." (`plugin/ui/ChatWindow.cpp:85`).
- The chat thread ends: `conversation_timeout_minutes` pass without a chat, or the player starts another chat thread, for example with another NPC or from another squad member ([section 2](#2-entry)).

Each end also ends the chat thread.

At the end, the NPC says a line from a preset list of its category and its end, picked at random, because the end comes after the last call and a preset line costs no call. A knockout, a death, a save load, an error, a timeout of the chat thread, and the start of another chat thread get no line, because the NPC cannot talk or the player is gone.

| End | Example line |
|---|---|
| BARTER: the player accepts an offer | "Pleasure doing business." |
| HEAL: the treatment starts | "I'll patch you right up." |
| THREATEN: the NPC attacks the speaker | "Think you can take me? C'mon then!" |

## 5. Speaker

The chat window names the speaker in the player's line (`plugin/ui/ChatWindow.cpp:214`), and the plugin keeps that squad member as `g_lastChattingPlayerHand` (`plugin/main.cpp:251`). Only `SPAWN_ITEM` acts on that squad member (`plugin/game/GameActions.cpp:1018`). The other actions act on the first character of the squad:

| Actions | Why they act on the first character |
|---|---|
| `GIVE_ITEM`, `TAKE_ITEM`, `GIVE_CATS`, `TAKE_CATS` | The plugin queues each action for the speaker (`plugin/main.cpp:522`, `:557`, `:587`, and `:577`), but its handler ignores the speaker (`plugin/game/GameActions.cpp:630`, `:518`, `:724`, and `:739`). |
| `ATTACK`, `FOLLOW_PLAYER`, and the release | The plugin queues each action for the first character (`plugin/main.cpp:489`, `:673`, `:704`, and `:715`). |

An action dialogue belongs to one speaker ([section 2](#2-entry)), but another squad member can still chat, with this NPC or another, before the reply to a line arrives. `g_lastChattingPlayerHand` then names the wrong squad member. Each design of the actions must therefore send the speaker with the action, so that the action acts on the squad member that spoke.

## 6. Open questions

1. What does the action system prompt hold?
2. What are the lines of each preset list of the end?

## 7. Probe

Three test commands of the chat answer the open questions of the category docs that need the game ([development.md](../../info/development.md#probes)). Before the checks, set **Log level** on the Settings page to `DEBUG`. The speaker is the squad member that the chat window names.

`/stock` answers where a trader keeps its stock and which data of an item holds its grade ([barter.md](barter.md#8-open-questions)):

1. Chat with a trader in its shop, for example a weapon smith, and send `/stock`.
2. Open the trade window of the trader. Find the stock of the window in the `STOCK_PROBE` lines: in `all_items` and the `item who=npc` lines, in `sections`, in `sources`, or in the inventory of the `building`.
3. For each weapon and each armour of the trader and of the speaker, compare the grade in the tooltip of the game, for example "Edge Type 1" or "Specialist", with `quality`, `level`, `manufacturer`, and `material`.

`/firstaid` answers whether `FIRST_AID_ORDER` makes an NPC outside the squad treat the speaker ([heal.md](heal.md#5-open-questions)):

1. Get the speaker `Injured`, for example in a fight.
2. Chat with an NPC outside the squad that carries a first aid kit, and send `/firstaid`. The line shows `first_aid_item=1`.
3. Check that the NPC walks to the speaker and treats its wounds.
4. Send `/firstaid` to an NPC without a first aid kit, and check that the line shows `first_aid_item=0`.

`/hire` answers which call starts a hire contract with an expiry time and which call ends it ([follow.md](follow.md#4-open-questions), [dismiss.md](dismiss.md#4-open-questions)):

1. Chat with an NPC outside the squad, and send `/hire 6`.
2. Check that the `HIRE_PROBE` line shows `contract=1`, and that `expiry` is 6 more than `now`.
3. Check that the NPC follows the squad, and that its next `ROLE_PROBE` line shows `contract=1`.
4. Wait 6 game hours, and check that the NPC stops following.
5. Send `/hire 6` again, and then `/hire end`. Check that the line shows `contract=0`, and that the NPC stops following.
6. When `/hire 6` starts no contract, send `/hire 5078-gamedata.base`, which runs the 24-hour hire line of the game's bodyguard dialogue, and repeat the checks with 24 hours.
