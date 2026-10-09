# Proposal: FOLLOW

## 1. Summary

In a FOLLOW action dialogue, the player asks the NPC to follow the squad for a time. Unlike RECRUIT, the hire is temporary. The player opens it with `!f` or `!follow`. [framework.md](framework.md) holds the rules that all categories share.

FOLLOW reuses the game's mercenary hire: the NPC follows the squad under a hire contract, as a hired mercenary does. The plugin already reads such a contract as `temporary_follower` (`plugin/game/Context.cpp:362`).

## 2. Gate, hard limits, and lean

FOLLOW uses the [gate](recruit.md#2-gate), the [hard limits](recruit.md#4-hard-limits), and the [lean](recruit.md#5-lean) of RECRUIT. Its lean is how likely the NPC is to follow.

## 3. Open questions

1. How does the plugin start a hire contract? The plugin only reads one now, and no in-game test covers a contract yet ([development.md](../../info/development.md#probes)).
2. When does the action dialogue close?
