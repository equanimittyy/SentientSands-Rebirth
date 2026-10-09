# Proposal: DISMISS

## 1. Summary

In a DISMISS action dialogue, the player ends the hire of an NPC that follows the squad through FOLLOW ([follow.md](follow.md)). The player opens it with `!d` or `!dismiss`. [framework.md](framework.md) holds the rules that all categories share.

Dismissing a squad member stays outside the action dialogue and goes through the normal routes.

## 2. Gate

The NPC is a temporary follower (`temporary_follower` in `plugin/game/Context.cpp:362`) ([Blocked](framework.md#blocked)).

## 3. Answer

The NPC never refuses, so DISMISS has no lean and no offer. `LEAVE` runs at once, and the action dialogue closes when the NPC leaves. The player gets no part of the fee back.

## 4. Open questions

1. Which call ends a hire contract? The game ends the contract of a mercenary when its time runs out, so a way exists. A candidate is `signalEnd` of `Contract_Timed` (`deps/KenshiLib/Include/kenshi/AI/Contract.h:11`), which `Contract_HiredAlly` inherits. `LEAVE` now runs `PerformLeaveSquad` (`plugin/game/GameActions.cpp:25`), which takes a member out of the squad instead.
