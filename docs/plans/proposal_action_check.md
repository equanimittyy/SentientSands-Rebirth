# Proposal: Action Check

Status: Draft for review

## 1. Summary

Chat sends no game actions since the action tags were turned off. In the old system, the chat model wrote `[ACTION: X]` tags into its reply. The model decided the words and the effect in the game together, nothing checked the game state, and the examples broke the two-step rule of trades. The plugin still runs the actions (`ExecuteQueuedActions` in `plugin/game/GameActions.cpp`), and only the debug commands of the chat send them (`server/chat/routes.py:234`).

This plan splits the work into two parts:

1. An action check, which is a small LLM call on each player line, tells which category of request the line holds. The LLM only reads the language, and it writes one number ([section 4](#4-action-check)).
2. Code decides the result from the game state with fixed rules ([section 5](#5-rules)). A request that costs cats becomes an offer at a price from the rules, and the player accepts it in a later line. The chat call gets the result, so the reply of the NPC agrees with what happens in the game ([section 6](#6-reply-and-game-action)).

The LLM never decides whether an action happens, or at what price. A missing or unreadable answer counts as no request, so a failed check gives a normal chat turn without an action.

Each action acts on the squad member that spoke, not on the first character of the squad ([section 6](#speaker)).

Non-goals:

- Banter, radiant talk, and chats with animals.
- The judgment of a reply. The chat reply keeps its `[JUDGMENT: n]` tag (`server/chat/routes.py:389`).
- The stock of a shop. The trade screen of the game sells it. A chat trade moves only the items that the NPC itself carries.

## 2. Flow

For each player line in a 1:1 chat (talk, whisper, or yell) to an NPC that is not an animal, the chat route (`server/chat/routes.py:177`) does these steps:

1. It sends the action check and gets a category.
2. It applies the rules of the category to the game context of the request. The result is no action, an offer, a decline with a reason, or a done action.
3. It keeps the offer of a result with a price ([section 5](#offers)).
4. It adds the outcome sentence to the final instruction of the chat turn (`server/chat/routes.py:351`), and sends the chat call.
5. It returns the actions of a done result in `actions`, which now always holds an empty list (`server/chat/routes.py:487`).

The check runs before the chat call, because the reply must state the outcome. A check of the reply after the chat call would let the words of the NPC decide the outcome again.

The debug commands of the chat skip the check and the rules, so they still test the handlers of the plugin directly.

## 3. Categories

A category names the request of the player, not the action of the NPC.

| Number | Category | The player's line |
|---|---|---|
| 0 | NONE | Everything else, including talk about a topic that asks for nothing, such as "Did you ever join a squad?" |
| 1 | THREATEN | Threatens the NPC, or challenges it to a fight. |
| 2 | DEMAND | Demands the NPC's cats or items, with or without a threat. |
| 3 | RECRUIT | Asks the NPC to join the squad. |
| 4 | DISMISS | Tells a squad member to leave the squad. |
| 5 | BUY | Asks for an item that the NPC carries, to buy it or as a favour. |
| 6 | SELL | Offers the NPC an item for cats. |
| 7 | GIFT | Gives the NPC an item or cats, and asks for nothing back. |
| 8 | ACCEPT | Agrees to the open offer. |
| 9 | HAGGLE | Names another price for the open offer. |
| 10 | FREE | Asks the NPC to let the speaker out of prison. |
| 11 | HEAL | Asks the NPC to treat the speaker's wounds, or to repair a skeleton speaker. |
| 12 | SEND_AWAY | Tells an NPC outside the squad to go away. |

A later category gets the next number, so the numbers of the earlier categories do not change.

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

### Prompt

`server/data/prompts/prompt_action_check.txt` holds the fixed instructions and a `{categories}` placeholder. Code fills the placeholder from the category table, so the numbers in the prompt and in the parse come from one place. The system message is the same on each call, so a provider with a prompt cache can serve it from the cache.

The user message holds these lines, with the names of the speakers:

- The last line of the NPC in the current chat thread, if there is one. It lets the check read a short answer: after "Want me along?", the line "Yes." is a RECRUIT.
- The open offer, if there is one, such as "Open offer: Beep asks 3000 cats to join the squad." It lets the check tell ACCEPT and HAGGLE from GIFT and SELL.
- The player's line.

The message holds no profile, no scene, and no history.

The instructions end with `Reply with JSON only: {"action": n}`.

### Prefill

The messages end with a partial reply of the assistant: `{"role": "assistant", "content": "{\"action\":"}`. A model that continues this reply writes only the number and the closing brace.

Prefill support depends on the provider and the model, and the player picks both:

| Provider | Prefill |
|---|---|
| OpenRouter | Documented, if the upstream provider of the model supports it |
| llama.cpp | Documented |
| vLLM | Only with `continue_final_message` |
| DeepSeek | Only on its beta endpoint, with `prefix: true` on the message |
| OpenAI | Not supported: the model reads the partial reply as an earlier turn |
| Ollama, NanoGPT, Player2 | Untested |

The prefill is therefore only an aid. The parse reads the answer with or without it.

### Parse

The parse joins the prefill and the reply, and finds the first `"action": n` in that text. A provider that continues the prefill gives `{"action": 5}`. A provider that ignores it gives `{"action":{"action": 5}`, and the parse finds the same number.

The result is NONE when:

- The route gives no reply.
- The reply is longer than 40 characters. `extract_completion` returns the `reasoning_content` of a reply that has no `content` (`server/chat/llm.py:107`), and the length limit keeps the digits of a reasoning text from picking an action.
- The text holds no `"action": n`, or n is not in the category table.

### Route

`action` becomes a task of `llm_config.TASKS` (`server/chat/llm_config.py:14`), with `max_tokens` 10 and `temperature` 0. The Models page of the web app shows its route with the other tasks, and `server/dashboard/web/llm.js` gets its label and help text.

The check and the chat call run one after the other, and the plugin stops waiting after 60 s. The default deadline of the `action` route is therefore 5 s, and the default deadline of the `chat` route goes from 55 s to 50 s (`server/chat/llm_config.py:23`).

A reasoning model can spend `max_tokens` on its reasoning and return no text. The `action` route therefore needs a profile without reasoning, or a profile whose request parameters turn reasoning off.

A provider that refuses a request that ends with an assistant message returns an error, and the route moves to its next profile. When every profile fails, the result is NONE.

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

The rules take a value from the player's line with code, by a match against a closed list. The LLM never names a value.

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

A done RECRUIT or DISMISS changes the faction of the NPC, so the next turn gets a new scene, because the faction is part of the scene key (`server/chat/routes.py:361`).

### Speaker

The plugin now gives most actions to the first character of the squad, not to the squad member that spoke: `ATTACK` (`plugin/main.cpp:485`), the release (`plugin/main.cpp:700` and `:711`), and the item and cat handlers (`plugin/game/GameActions.cpp:496`, `:608`, `:702`, `:717`, and `:996`).

The change:

1. The chat task keeps the handle of the speaker that the chat window picked (`plugin/ui/ChatWindow.cpp:249`).
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

1. The check, DISMISS, GIFT, and the speaker change of the plugin.
2. RECRUIT, BUY, SELL, ACCEPT, and HAGGLE, after the design of offers.
3. THREATEN and DEMAND, after the design of threats.
4. FREE, HEAL, and SEND_AWAY, after the design of offers and the probe.

## 9. Rejected alternatives

| Alternative | Reason |
|---|---|
| Action tags in the chat reply (the old system) | The chat model decided the words and the effect together, and nothing checked the game state. |
| A check of the NPC's reply after the chat call | The words of the NPC would decide the outcome again, and the reply could promise what the rules decline. |
| Keyword rules on the player's line | They miss other words for the same request, negation ("I won't ask you to join"), questions about a topic, and players who write in other languages. Rules that handle these cases are language processing work. |
| Embedding similarity | It needs an embeddings endpoint, which not every provider has, and thresholds that need tuning. |
| A relation threshold for RECRUIT | Relation sets the price instead, so any NPC can join at some price. |

## 10. Verification

Unit tests, which run without Flask and requests (`server/tests/`):

- The parse: a reply after a continued prefill, a reply that ignores the prefill, a reply in a code fence, a long reasoning text that holds digits, an unknown number, and no reply.
- The rules: each row of the rules table.
- The prices: each formula, and that the lowest ask stays above the pay.
- The values: the longest name wins, equipped items do not count, and the count caps at the count held.

A labelled set of player lines, a few for each category, runs through a profile and prints the accuracy of each category. Thirteen categories are many for a small model, so this set shows which profiles can serve the `action` route.

A prefill probe sends one check to each configured profile and logs whether the provider continued the prefill. Its results fill the untested rows of the table in [section 4](#prefill).

In the game:

1. Pick a second squad member as the speaker, and give an NPC an item that only that squad member carries. The item leaves the inventory of that squad member.
2. Ask a stranger with little fight skill to join. The NPC asks about 3000 cats, and nothing happens.
3. Say "Deal" with the cats. The cats go, and the NPC joins the squad.
4. Tell the recruit to leave. It leaves the squad.
5. Ask "Did you ever join a squad?". `llm.log` shows category 0, and no action happens.

## 11. Open questions

1. Are the proposed values of the constants right?
2. Threats: how do the rules read what the NPC wants? Candidates are the signs of the personal and the faction relation, and a temper that the server rolls for each NPC, like the speech quirks. DEMAND uses the same design.
3. Offers:
   - How long does an offer last, and what closes it: another category, the end of the chat thread, or a restart of the server?
   - Does ACCEPT check the cats and the items again with the context of the ACCEPT request?
   - How far can a haggle move a price? The limit must keep the lowest ask above the pay.
4. The player must name an item as the inventory names it. Is that strict enough, or too strict?
