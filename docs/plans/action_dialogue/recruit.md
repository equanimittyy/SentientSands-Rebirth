# Proposal: RECRUIT

## 1. Summary

In a RECRUIT action dialogue, the player asks the NPC to join the squad. The player opens it with `!r` or `!recruit`. [framework.md](framework.md) holds the rules that all categories share.

## 2. Gate

RECRUIT needs all of these ([Blocked](framework.md#blocked)):

- Neither the speaker nor the NPC is `imprisoned` or `enslaved` (`character_state` in `plugin/game/Context.cpp:675`), because a caged or shackled speaker cannot recruit, and the player must free a caged or shackled NPC first.
- The NPC is not the leader of its faction (`is_leader`), because the faction would lose its leader in the world.

No action reaches an NPC that is already in the player faction ([Blocked](framework.md#blocked)). A temporary follower can join, and its hire then becomes a permanent join.

## 3. Answers

| Answer | Result |
|---|---|
| It agrees | It makes an offer ([Offer](framework.md#offer)): "Drifter offers to join your squad for 1,500 cats.", or with no fee, "Drifter offers to join your squad.". |
| It bargains | It makes no offer yet, and the action dialogue goes on. |
| It refuses | It makes no offer and ends its reply with `[REFUSE]` ([Refusal](#refusal)). |

On accept, `JOIN_PARTY` (`plugin/main.cpp:485`) recruits the NPC (`plugin/game/GameActions.cpp:322`).

The action dialogue ends when the NPC refuses, or when the player accepts an offer.

### Refusal

Only RECRUIT and FOLLOW have a refusal tag, because only they end on a refusal. Without the tag, code cannot tell a refusal from a reply that still bargains. The chat window shows the tag as a system message ([Reply](framework.md#reply)), where X is the name of the NPC and Y is the name of the player faction:

| Category | Message |
|---|---|
| RECRUIT | X has refused your invitation to join Y. |
| FOLLOW | X has refused your offer of hire. |

## 4. Hard limits

The player has the cats of the fee.

## 5. Lean

The lean ([Outcome](framework.md#outcome)) is how likely the NPC is to join. It counts the relation, on the scale of [Outcome](framework.md#outcome), and these facts:

| Fact | Bonus |
|---|---|
| The NPC's `character_state` is `escaped-slave` | +1 |
| The NPC is unique (`unique`) | -1 |
| The NPC is a guard ([Outcome](framework.md#outcome)) | -1 |
| The NPC's Current Job is `Trading`, `Running a shop`, or `Travelling as a trader` | -1 |
