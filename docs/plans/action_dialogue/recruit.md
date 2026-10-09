# Proposal: RECRUIT

## 1. Summary

In a RECRUIT action dialogue, the player asks the NPC to join the squad. The player opens it with `!r` or `!recruit`. [framework.md](framework.md) holds the rules that all categories share.

## 2. Gate

Neither the speaker nor the NPC is `imprisoned` (`plugin/game/Context.cpp:675`), because a caged speaker cannot recruit, and the player must free a caged NPC first ([Blocked](framework.md#blocked)).

## 3. Answers

| Answer | Result |
|---|---|
| It agrees | It makes an offer ([Offer](framework.md#offer)): "Drifter offers to join your squad for 1,500 cats.", or with no fee, "Drifter offers to join your squad.". |
| It bargains | It makes no offer yet, and the action dialogue goes on. |
| It refuses | It makes no offer and ends its reply with `[REFUSE]` ([Refusal](#refusal)). |

The action dialogue closes when the NPC refuses, or when the player accepts an offer.

### Refusal

Only RECRUIT has a refusal tag, because only RECRUIT closes on a refusal. Without the tag, code cannot tell a refusal from a reply that still bargains. The chat window shows the tag as a system message ([Reply](framework.md#reply)): "X has refused your Y.", where X is the name of the NPC.

## 4. Hard limits

The player has the cats of the fee.

## 5. Lean

The lean ([Outcome](framework.md#outcome)) is how likely the NPC is to join:

| Fact | Bonus |
|---|---|
| The NPC's profile `Relation` is 60 or more | +2 |
| The NPC's profile `Relation` is 25 to 59 | +1 |
| The NPC's profile `Relation` is -25 or less | -1 |
| The NPC's `character_state` is `escaped-slave` | +1 |
| The NPC is the leader of its faction (`is_leader`) or unique (`unique`) | -1 |
| The NPC's Current Job is `Trading`, `Running a shop`, or `Travelling as a trader` | -1 |

## 6. Open questions

1. Which word is Y in the refusal message?
