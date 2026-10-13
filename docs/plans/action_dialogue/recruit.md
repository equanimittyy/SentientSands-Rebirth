# Proposal: RECRUIT

## 1. Summary

In a RECRUIT action dialogue, the player asks the NPC to join the squad. The player opens it with `!r` or `!recruit`. [framework.md](framework.md) holds the rules that all categories share.

## 2. Gate

RECRUIT needs all of these, and a line that fails one goes to plain chat with the reason ([Plain chat](framework.md#plain-chat)):

- Neither the speaker nor the NPC is `imprisoned` or `enslaved` (`character_state` in `plugin/game/Context.cpp:1104`), because a caged or shackled speaker cannot recruit, and the player must free a caged or shackled NPC first. Fellow captives are the exception ([Fellow captives](#fellow-captives)).
- The NPC is not the leader of its faction (`is_leader`), because the faction would lose its leader in the world.

A marked line to an NPC that is already in the player faction goes to plain chat ([Plain chat](framework.md#plain-chat)). A temporary follower can join, and its hire then becomes a permanent join.

### Fellow captives

A captive can recruit a fellow captive of the same faction, so that they can escape together. The speaker and the NPC pass the first gate when the captor of each is the same faction (`action_dialogue.fellow_captives`). Each one can be in a cage or in shackles, because a slave camp also puts its slaves into cages.

The plugin sends the captor as `captor`, the faction ID of the owner of the cage or of the slave owner of a shackled slave (`CaptorID` in `plugin/game/Context.cpp:329`). A captive keeps its own faction, so its `faction` does not name the captor. A character that is not in a cage and not in shackles has an empty `captor`, and so does a captive whose captor the plugin cannot read.

The leader gate still holds for a fellow captive.

## 3. Answers

| Answer | Result |
|---|---|
| It agrees | It makes an offer ([Offer](framework.md#offer)): "Drifter offers to join your squad for 1,500 cats.", or with no fee, "Drifter offers to join your squad.". |
| It bargains | It makes no offer yet, and the action dialogue goes on. |
| It refuses | It makes no offer and ends its reply with `[REFUSE]` ([Refusal](#refusal)). |

On accept, `JOIN_PARTY` carries the fee (`QueueTagAction` in `plugin/main.cpp`). The plugin takes the fee and recruits the NPC, or does neither when the player has fewer cats than the fee (`DoJoinParty` in `plugin/game/GameActions.cpp`).

The action dialogue ends when the NPC refuses, or when the player accepts an offer.

### Refusal

Only RECRUIT and FOLLOW have a refusal tag, because only they end on a refusal. Without the tag, code cannot tell a refusal from a reply that still bargains. The chat window shows the tag as a system message ([Reply](framework.md#reply)), where X is the name of the NPC and Y is the name of the player faction:

| Category | Message |
|---|---|
| RECRUIT | X has refused your invitation to join Y. |
| FOLLOW | X refused to follow you. |

## 4. Hard limits

The player has the cats of the fee.

## 5. Lean

The lean ([Outcome](framework.md#outcome)) is how likely the NPC is to join. It counts the relation, on the scale of [Outcome](framework.md#outcome), and these facts:

| Fact | Bonus |
|---|---|
| The NPC's `character_state` is `escaped-slave` | +1 |
| The speaker and the NPC are [fellow captives](#fellow-captives) | +1 |
| The speaker and the NPC are fellow captives, and the line is a talk or a yell, not a whisper, so the captors can hear it | -3 |
| The NPC is unique (`unique`) | -1 |
| The NPC is a guard ([Outcome](framework.md#outcome)) | -2 |
| The NPC's Current Job is `Trading`, `Running a shop`, or `Travelling as a trader` | -2 |
