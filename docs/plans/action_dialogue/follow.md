# Proposal: FOLLOW

## 1. Summary

In a FOLLOW action dialogue, the player asks the NPC to follow the squad for a time. Unlike RECRUIT, the hire is temporary. The player opens it with `!f` or `!follow`. [framework.md](framework.md) holds the rules that all categories share.

FOLLOW reuses the game's mercenary hire: the NPC follows the squad under a hire contract, as a hired mercenary does. The game's hire dialogues give the NPC the `Bodyguard` contract (`5090-gamedata.base`) with a length in hours, and the game runs it as a hired ally (`Contract_HiredAlly` in `deps/KenshiLib/Include/kenshi/AI/Contract.h:63`). The contract expires at the end of its length. The plugin starts the hire with `_setContractJob` of the blackboard, with the `Bodyguard` package and the hours of the hire (`deps/KenshiLib/Include/kenshi/AI/Blackboard.h:65`), which an in-game test showed to work ([kenshi_internals.md](../../info/kenshi_internals.md#orders-and-contracts)). The plugin already reads such a contract as `temporary_follower` (`plugin/game/Context.cpp:362`). The player ends the hire early with DISMISS ([dismiss.md](dismiss.md)).

## 2. Gate, hard limits, and lean

FOLLOW uses the [gate](recruit.md#2-gate), the [hard limits](recruit.md#4-hard-limits), and the [lean](recruit.md#5-lean) of RECRUIT. Its lean is how likely the NPC is to follow.

An offer of FOLLOW holds the length of the hire, for example "Drifter offers to follow you for 2 days for 4,000 cats.".

The action dialogue ends when the NPC refuses ([Refusal](recruit.md#refusal)), or when the player accepts an offer.

## 3. Mercenaries

Code picks the request by the faction of the NPC. A mercenary gets `prompt_action_follow_mercenary.txt`, a hire as a guard for a fee, and any other NPC gets `prompt_action_follow.txt`, a request to follow as a follower. One request that called each follow the work of a hired guard made NPCs that are not mercenaries refuse "hired guard work", and its fee example made them write `TAKE_CATS: 0`.

An NPC that is not a mercenary never asks for a fee, but it can take the cats that the player offers, and an offer of cats makes it more willing to follow. It is wary of following the player for no reason, so its lean takes -1 on top of the lean of RECRUIT.

A mercenary never follows for free: its fee is at least the daily rate of its faction times the days of the hire. Code tells a mercenary by the faction that it belongs to (`faction` and `factionID` in `plugin/game/Context.cpp:726`). The rates come from the `Bodyguard` contracts of the game's hire dialogues:

| Faction | Daily rate | Hire dialogue in the game data |
|---|---|---|
| Mercenary Guild | 2,000 cats | `mercenary shop` (`5464-gamedata.base`): 1 day for 2,000, 2 days for 4,000 |
| Tech Hunters | 2,000 cats | The drifter squads use `mercenary shop`, and the solo drifters use `bodyguard for hire` (`5070-gamedata.base`): 6 hours for 500 up to 2 days for 4,000 |
| Vagrants | 2,000 cats | The bar thugs use `Thug2` (`44780-Dialogue.mod`): 1 day for 2,000, 2 days for 4,000 |
| Black Dog | 2,500 cats | `Black dog random extortion` (`47469-Dialogue.mod`): 1 day for 2,500 |

The Cannibal Hunters sell only the `contract Mercenary outpost guard`, in which the hired squad guards an outpost and does not follow, so they are not mercenaries of FOLLOW.
