# Proposal: DISMISS

## 1. Summary

In a DISMISS action dialogue, the player ends the hire of an NPC that follows the squad through FOLLOW ([follow.md](follow.md)). The player opens it with `!d` or `!dismiss`. [framework.md](framework.md) holds the rules that all categories share.

Dismissing a squad member stays outside the action dialogue and goes through the normal routes.

## 2. Gate

The NPC is a temporary follower (`temporary_follower` in `plugin/game/Context.cpp:362`) ([Blocked](framework.md#blocked)).

## 3. Answer

The NPC never refuses, so DISMISS has no lean and no offer. `LEAVE` runs at once, and the action dialogue ends when the NPC leaves. The player gets no part of the fee back.

## 4. Open questions

1. Which call ends a hire contract? The game ends the contract of a mercenary when its time runs out, so a way exists. The `/hire end` probe tries `endContractJob` of the blackboard (`deps/KenshiLib/Include/kenshi/AI/Blackboard.h:76`) ([framework.md](framework.md#7-probe)). It does not try `signalEnd` of `Contract_Timed`, because `AI/Contract.h` includes `AIPackage.h`, which clashes with `Blackboard.h` ([kenshi_gotchas.md](../../info/kenshi_gotchas.md#kenshilib-headers)). `LEAVE` now runs `PerformLeaveSquad` (`plugin/game/GameActions.cpp:25`), which takes a member out of the squad instead.
