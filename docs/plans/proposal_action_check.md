# Proposal: Action Check

Status: Draft for review

## 1. Summary

Chat sends no game actions since the action tags were turned off. In the old system, the chat model wrote `[ACTION: X]` tags into its reply. The model decided the words and the effect in the game together, nothing checked the game state, and the examples broke the two-step rule of trades. The plugin still runs the actions (`ExecuteQueuedActions` in `plugin/game/GameActions.cpp`), and only the debug commands of the chat send them, through the pipe before the reply line (`server/chat/routes.py:226`).

This plan splits the work into two parts:

1. An action check on each player line tells which category of request the line holds. Von, a local classifier model, reads the line and picks one category ([section 4](#4-action-check)). The check makes no LLM call.
2. Code decides the result from the game state with fixed rules ([section 5](#5-rules)). A request that costs cats becomes an offer at a price from the rules, and the player accepts it in a later line. The chat call gets the result, so the reply of the NPC agrees with what happens in the game ([section 6](#6-reply-and-game-action)).

No model decides whether an action happens, or at what price. A missing answer counts as no request, so a failed check gives a normal chat turn without an action.

Each action acts on the squad member that spoke, not on the first character of the squad ([section 6](#speaker)).

Non-goals:

- Radiant conversations and chats with animals.
- The judgment of a reply. The chat reply keeps its `[JUDGMENT: n]` tag (`server/chat/routes.py:288`).
- The stock of a shop. The trade screen of the game sells it. A chat trade moves only the items that the NPC itself carries.

## 2. Flow

For each player line in a 1:1 chat (talk, whisper, or yell) to an NPC that is not an animal, the chat route (`server/chat/routes.py:135`) does these steps:

1. It sends the action check to Von, and gets a category with a confidence. Below the threshold of the category, the category is NONE.
2. It applies the rules of the category to the game context of the request. The result is no action, an offer, a decline with a reason, or a done action.
3. It keeps the offer of a result with a price ([section 5](#offers)).
4. It adds the outcome sentence to the final instruction of the chat turn (`server/chat/routes.py:294`), and sends the chat call.
5. It sends the actions of a done result through the pipe before the reply line, as the debug commands do (`play_lines` in `server/chat/routes.py:110`).

The check runs before the chat call, because the reply must state the outcome. A check of the reply after the chat call would let the words of the NPC decide the outcome again.

The debug commands of the chat skip the check and the rules, so they still test the handlers of the plugin directly.

## 3. Categories

A category names the request of the player, not the action of the NPC. Von gets each category by its name and a one-line description.

| Category | The player's line |
|---|---|
| NONE | Everything else, including talk about a topic that asks for nothing, such as "Did you ever join a squad?" |
| THREATEN | Threatens the NPC, or challenges it to a fight. |
| DEMAND | Demands the NPC's cats or items, with or without a threat. |
| RECRUIT | Asks the NPC to join the squad. |
| DISMISS | Tells a squad member to leave the squad. |
| BUY | Asks for an item that the NPC carries, to buy it or as a favour. |
| SELL | Offers the NPC an item for cats. |
| GIFT | Gives the NPC an item or cats, and asks for nothing back. |
| ACCEPT | Agrees to the open offer. |
| HAGGLE | Names another price for the open offer. |
| FREE | Asks the NPC to let the speaker out of prison. |
| HEAL | Asks the NPC to treat the speaker's wounds, or to repair a skeleton speaker. |
| SEND_AWAY | Tells an NPC outside the squad to go away. |

Some actions of the old tag list have no category:

| Old action | Reason |
|---|---|
| `FOLLOW_PLAYER`, `IDLE` | RECRUIT brings an NPC along, and the player gives orders to squad members in the game. |
| `PATROL_TOWN`, `STAND_AT_SHOPKEEPER_NODE`, `GO_HOMEBUILDING` | They are the NPC's own jobs, which the game runs. |
| `TRAVEL_TO_TARGET_TOWN` | The server has no list of towns to match a town name against. |
| `FIND_AND_RESCUE`, `RAID_TOWN`, `ATTACK_TOWN`, `MOVE_ON_FREE_WILL_FAST` | No player request leads to them. |
| `DROP_ITEM` | DEMAND gives the item to the speaker. |
| `SPAWN_ITEM` | It makes items from nothing, so it stays a debug command. |
| `FACTION_RELATIONS` | A chat line changes only the personal relation. |
| `NOTIFY` | The plugin shows its own message for each action. |

## 4. Action check

### Classifier

[Von](https://github.com/wfzyx/von) reads the check. It is a ModernBERT encoder with 395M parameters. It answers a choice question over labels with descriptions in one forward pass, so it needs no training for the categories. It samples nothing, so the same line gets the same answer, and it returns a calibrated confidence with its choice.

The check makes no LLM call. It therefore does not depend on the provider that the player picked, it leaves the prompt cache of the provider alone, and it adds no LLM round trip to a chat turn.

The server sends the check to `von serve` on the player's PC, at `http://127.0.0.1:8000/v1/systemone`, with a timeout of 10 s. When Von gives no answer, the category is NONE, so chat without Von works as now, without actions.

### Question

| Part | Content |
|---|---|
| State | JSON with `npc_said`, the newest line of the NPC in the current chat thread; `open_offer`, the open offer, if there is one; and `player_said`, the player's line |
| Instructions | Pick the request that the player makes of the NPC in `player_said`, and pick NONE unless the player clearly makes one of the other requests now. |
| Choices | The categories that can apply now, each with its description |

`npc_said` lets the check read a short answer: after "Want me along?", the line "Yes." is a RECRUIT. `open_offer` lets it tell ACCEPT and HAGGLE from GIFT and SELL.

Code leaves out each category that the facts rule out, so Von cannot pick it:

- For a squad member, the choices are only NONE and DISMISS.
- FREE needs an imprisoned speaker.
- ACCEPT and HAGGLE need an open offer.

### Confidence

A category acts only when the confidence of Von reaches the threshold of the category. Below the threshold, the category is NONE. A wrong DISMISS costs more than a missed one, so each category gets its own threshold from the eval ([section 10](#10-verification)). `von calibrate` can refit the confidence of Von on the labelled lines.

### Install

Von is not part of the release, because it needs `torch` and `transformers`, and its weights are about 3 GB. A player who wants actions installs `von-sdk`, which needs Python 3.12 or later, and runs `von serve`. A player without Von gets chat without actions.

### Limits

| Limit | Effect |
|---|---|
| English only | The README says that "other languages get token matching with confidence it has not earned". |
| Runs on the player's PC | 395M parameters in 32-bit floats take about 1.6 GB of RAM. The latency next to the game is unknown. The README gives a p50 of 0.096 s on a 4-vCPU server Xeon with OpenVINO. |
| Windows | The README does not name Windows. `von serve` has a `dml` device for DirectML. |

## 5. Rules

### Facts

The rules read the game context of the chat request, the speaker's context, and the profile of the NPC. The rules of an ACCEPT read the context of the ACCEPT request, so they see the cats and items of that moment.

| Fact | Source |
|---|---|
| In the squad | `in_player_faction`, or `is_player_faction` of the faction (`server/core/game.py:27`) |
| Personal relation (R) | `Relation` of the profile, from -100 to 100 (`server/store/campaign_db.py:264`). The rules use the value before the judgment of the current line. |
| Faction relation (F) | `relation`: the relation of the player's faction with the NPC's faction, from -100 to 100 (`plugin/game/Context.cpp:683`) |
| Fight skill | The higher of `melee_attack` and `melee_defence` (`_fight_skill` in `server/chat/scene_text.py:201`) |
| Strength gap | The speaker's fight skill minus the NPC's, on the scale of `STRENGTH_GAP` (`server/chat/scene_text.py:40`) |
| Cats | `money` of the speaker's context and of the NPC's context |
| Items | `inventory` of each context: name, count, `price` (the value of one item), and `equipped` |
| Unique, leader, in shop | `unique`, `is_leader`, `in_shop` of the NPC's context |
| Imprisoned | `character_state` of the speaker's context is `imprisoned` |
| Hurt | The speaker's `blood` is below its `max_blood`, or a part of `limbs` is below its maximum |
| Skeleton | `is_skeleton` of the speaker's race (`server/chat/characters.py:13`) |

### Prices

Relation sets prices, not permission. Each price is in whole cats.

| Price | Formula |
|---|---|
| Ask (the NPC sells) | value × count × (1 − R/200) |
| Pay (the NPC buys) | value × count × `PAY_SHARE`, and at most the NPC's cats |
| Recruit | (3000 + 150 × the NPC's fight skill) × (1 − R/200) × (1 − F/200), × `UNIQUE` for a unique NPC, × `LEADER` for a leader |
| Free | `FREE_BASE` × (1 − R/200) × (1 − F/200) |
| Heal | `HEAL_PRICE` × (1 − R/200) |

| Constant | Proposed value |
|---|---|
| `PAY_SHARE` | 0.3 |
| `UNIQUE` | 2 |
| `LEADER` | 5 |
| `FREE_BASE` | 2000 |
| `HEAL_PRICE` | 200 |
| `GIFT_VALUE` | 100 cats for each point of relation |

With R and F at 0, an NPC with almost no fight skill asks about 3000 cats to join, and an NPC with a fight skill of 20 asks about 6000 cats.

The lowest ask (0.5 of the value) stays above the pay (0.3 of the value). A player therefore cannot buy an item and sell it back at a profit.

### Values

The rules take a value from the player's line with code, by a match against a closed list. No model names a value.

| Value | Match |
|---|---|
| An item | The longest item name of the inventory that the line holds, without regard to case. Only items that are not equipped count. BUY and DEMAND look in the NPC's inventory, and SELL and GIFT look in the speaker's inventory. |
| A count | The first number in the line, or 1. The rules cap it at the count of the item. |
| Cats | The first number in the line, for GIFT and DEMAND when the line names no item, and for HAGGLE. |

### Offers

A result with a price becomes an offer for the speaker and the NPC, with the category, the item, the count, and the price. ACCEPT carries out the offer, and HAGGLE changes its price. How the server keeps, checks, changes, and closes an offer is open ([section 11](#11-open-questions)).

### Rules of each category

| Category | No action when | Result | Actions |
|---|---|---|---|
| THREATEN | The NPC is in the squad. | See [Threats](#threats). | `ATTACK` when the NPC attacks |
| DEMAND | The NPC is in the squad. | See [Threats](#threats). The NPC yields, or reacts as to a threat. | `GIVE_ITEM`, or `GIVE_CATS` with the demanded cats or all its cats, when the NPC yields. `ATTACK` when the NPC attacks. |
| RECRUIT | The NPC is in the squad. | Offer at the recruit price | `TAKE_CATS`, then `JOIN_PARTY`, at ACCEPT |
| DISMISS | The NPC is not in the squad. | Done | `LEAVE` |
| BUY | The NPC is in the squad, or the line names no item of the NPC. | Offer at the ask | `TAKE_CATS`, then `GIVE_ITEM`, at ACCEPT |
| SELL | The NPC is in the squad, or the line names no item of the speaker. | Offer at the pay. Declined when the NPC has no cats. | `TAKE_ITEM`, then `GIVE_CATS`, at ACCEPT |
| GIFT | The NPC is in the squad, or the line names no item and no cats. | Done. R rises by 1 for each `GIFT_VALUE` cats of value, by at most 10. | `TAKE_ITEM` or `TAKE_CATS` |
| ACCEPT | No offer is open. | See [Offers](#offers). | The actions of the offer |
| HAGGLE | No offer is open, or the line holds no number. | See [Offers](#offers). | None |
| FREE | The speaker is not imprisoned. | Offer at the free price | `TAKE_CATS`, then a release, at ACCEPT |
| HEAL | The NPC is in the squad, or the speaker is not hurt. | Offer at the heal price | `TAKE_CATS`, then `JOB_MEDIC`, or `JOB_REPAIR_ROBOT` for a skeleton, at ACCEPT |
| SEND_AWAY | The NPC is in the squad, or the NPC is in its shop. | Done | `MOVE_ON_FREE_WILL` |

The cats move before the service or the item. After a failed take of cats or items, the plugin skips `GIVE_ITEM` and `GIVE_CATS` of the same reply (`plugin/game/GameActions.cpp:583` and `:694`). The plugin change of [section 6](#speaker) extends this skip to `JOIN_PARTY`, the release, and the jobs, because the speaker's cats can change between the request and the action.

### Threats

The result of a threat or a demand depends on the strength gap and on what the NPC wants. For example, an NPC that is much stronger than the speaker can laugh off a threat. How the rules read what the NPC wants is open ([section 11](#11-open-questions)).

The chat reply gives the words. A result such as "laughs it off" sets what happens, and the profile of the NPC sets how it sounds.

## 6. Reply and game action

### Outcome

The outcome sentence goes after the final instruction of the chat turn (`server/data/prompts/prompt_chat_turn.txt`). It states the result and every number, for example:

- "Beep asks 3000 cats to join Kara's squad. Say the price."
- "Beep takes 3000 cats and joins Kara's squad."
- "Beep does not carry that item."

The sentence is part of the turn only. The stored dialogue keeps the player's line and the reply, as now. The offer holds the price, so the deal uses the price of the rules even when the reply states another number.

A done RECRUIT or DISMISS changes the faction of the NPC, so the next turn gets a new scene, because the faction is part of the scene key (`server/chat/routes.py:304`).

### Speaker

The plugin now gives most actions to the first character of the squad, not to the squad member that spoke: `ATTACK` (`plugin/main.cpp:485`), the release (`plugin/main.cpp:700` and `:711`), and the item and cat handlers (`plugin/game/GameActions.cpp:496`, `:608`, `:702`, `:717`, and `:996`).

The change:

1. The chat task keeps the handle of the speaker that the chat window picked (`plugin/ui/ChatWindow.cpp:160`).
2. The action line carries the speaker's serial next to the NPC's serial.
3. Each handler uses the speaker as its target. When the speaker no longer exists, the plugin drops the action.
4. A failed take of cats or items also skips `JOIN_PARTY`, the release, and the jobs of the same reply.

The debug commands go through the same path, so they also act on the speaker.

## 7. Probe

Some rules depend on facts of the game that no test has shown. A probe answers them before the categories that need them are built ([development.md](../info/development.md#probes)).

| Question | Needed by |
|---|---|
| Is the `money` of the speaker's context the cats of the player's faction? | Every price |
| Does `JOB_MEDIC` on an NPC outside the squad treat the speaker? Does `JOB_REPAIR_ROBOT` repair a skeleton speaker? | HEAL |
| How can the server tell whether the NPC belongs to the faction that holds the speaker? A guard of that faction gives `RELEASE_PRISONER`, and any other NPC gives `BREAKOUT_PRISONER`. | FREE |
| Does a release free a speaker that is not the first character of the squad? | FREE |
| What does `MOVE_ON_FREE_WILL` make a town resident do? | SEND_AWAY |

## 8. Build order

1. The check in shadow mode: the chat route sends the check on each player line and only logs the answer of Von. The eval and the logs show whether Von reads well enough, and set the thresholds.
2. DISMISS, GIFT, and the speaker change of the plugin.
3. RECRUIT, BUY, SELL, ACCEPT, and HAGGLE, after the design of offers.
4. THREATEN and DEMAND, after the design of threats.
5. FREE, HEAL, and SEND_AWAY, after the design of offers and the probe.

## 9. Rejected alternatives

| Alternative | Reason |
|---|---|
| Action tags in the chat reply (the old system) | The chat model decided the words and the effect together, and nothing checked the game state. |
| A check of the NPC's reply after the chat call | The words of the NPC would decide the outcome again, and the reply could promise what the rules decline. |
| Keyword rules on the player's line | They miss other words for the same request, negation ("I won't ask you to join"), questions about a topic, and players who write in other languages. Rules that handle these cases are language processing work. |
| An LLM check with its own short prompt | On a local server with one slot, it replaces the cached chat prompt on each line. A second model or a pinned slot is a setup that a player should not need. |
| An LLM check on the chat prompt | It adds an LLM round trip to each line. A prefill fails on some providers (a 400 error on Claude 4.6 and later, and OpenAI ignores it), a reasoning model needs a different switch on each provider, and logprobs are too rare and too poorly calibrated to gate an action. |
| Tool calling in the chat call | Models call a tool when none applies, and the reply and the action come from the same call again. |
| Embedding similarity | It needs example phrases for each category, and Von reads one description for each. |
| A relation threshold for RECRUIT | Relation sets the price instead, so any NPC can join at some price. |

## 10. Verification

Unit tests, which run without Flask and requests (`server/tests/`):

- The check: the choices that the facts allow, the request body, and the parse of the answer of Von, with a stub in place of the HTTP call.
- The rules: each row of the rules table.
- The prices: each formula, and that the lowest ask stays above the pay.
- The values: the longest name wins, equipped items do not count, and the count caps at the count held.

The eval (`scripts/action_check_eval.py`) sends the labelled lines of `scripts/action_lines.jsonl` to Von as the chat route sends them. The set holds lines for each category, hard negatives such as "Get out of here! You're joking.", lines with an open offer, and lines in other languages. Run it on a Windows PC with the game open, so the latency is what a player gets. It prints the accuracy of each category, the confusions, the false actions at each threshold, and the latency. The set holds far more requests than play does, so its accuracy is not the share of right answers in a game.

In shadow mode, play a session and read the answers of Von in `server.log`.

In the game, after the build of the first actions:

1. Pick a second squad member as the speaker, and give an NPC an item that only that squad member carries. The item leaves the inventory of that squad member.
2. Ask a stranger with little fight skill to join. The NPC asks about 3000 cats, and nothing happens.
3. Say "Deal" with the cats. The cats go, and the NPC joins the squad.
4. Tell the recruit to leave. It leaves the squad.
5. Ask "Did you ever join a squad?". `server.log` shows that Von read it as NONE, and no action happens.

## 11. Open questions

1. Are the proposed values of the constants right?
2. Threats: how do the rules read what the NPC wants? Candidates are the signs of the personal and the faction relation, and a temper that the server rolls for each NPC, like the speech quirks. DEMAND uses the same design.
3. Offers:
   - How long does an offer last, and what closes it: another category, the end of the chat thread, or a restart of the server?
   - Does ACCEPT check the cats and the items again with the context of the ACCEPT request?
   - How far can a haggle move a price? The limit must keep the lowest ask above the pay.
4. The player must name an item as the inventory names it. Is that strict enough, or too strict?
5. Should Von ship in the release once the eval passes, and how big may the release get?
6. What do players who write in other languages get: chat without actions, or a multilingual encoder that is fine-tuned as Von's `docs/finetune.md` describes?
