# Proposal: DISMISS

## 1. Summary

In a DISMISS action dialogue, the player ends the hire of an NPC that follows the squad through FOLLOW ([follow.md](follow.md)). The player opens it with `!d` or `!dismiss`. [framework.md](framework.md) holds the rules that all categories share.

Dismissing a squad member stays outside the action dialogue and goes through the normal routes.

## 2. Gate

The NPC is a temporary follower (`temporary_follower` in `plugin/game/Context.cpp:362`) ([Blocked](framework.md#blocked)).

## 3. Answer

The NPC never refuses, so DISMISS has no lean, no offer, and no LLM call. The hire ends at once, the NPC says a line of `dismiss_end`, and the action dialogue ends with it. The player gets no part of the fee back.

The plugin ends the hire with `endContractJob` of the blackboard (`deps/KenshiLib/Include/kenshi/AI/Blackboard.h:76`), which an in-game test showed to work ([kenshi_internals.md](../../info/kenshi_internals.md#orders-and-contracts)). `LEAVE` does not fit, because it runs `PerformLeaveSquad` (`plugin/game/GameActions.cpp:25`), which takes a member out of the squad.
