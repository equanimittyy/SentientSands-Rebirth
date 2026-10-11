# Proposal: LIBERATE

## 1. Summary

In a LIBERATE action dialogue, the player asks a guard to release the speaker from a prison cage, for a bribe. The player opens it with `!l` or `!liberate`. [framework.md](framework.md) holds the rules that all categories share.

An NPC that is not a guard cannot break the speaker out. An apothecary of the Holy Nation Outlaws that got `BREAKOUT_PRISONER` for a cage of its own faction never walked to the cage ([kenshi_internals.md](../../info/kenshi_internals.md#orders-and-contracts)).

## 2. Deal

LIBERATE needs all of these, and a line that fails one goes to plain chat with the reason ([Plain chat](framework.md#plain-chat)):

- The speaker is not a slave, because no one releases a slave.
- The speaker is a prisoner: its `character_state` (`plugin/game/Context.cpp:675`) is `imprisoned`.
- The NPC is not `imprisoned`, because a fellow prisoner cannot free anyone.
- The NPC is a guard ([Outcome](framework.md#outcome)).

The guard releases the speaker with the `RELEASE_PRISONER` task. The popup ([Offer](framework.md#offer)) reads, for example, "Guard offers your release for 800 cats.".

The task runs through the release handler (`ACT_RELEASE` in `plugin/game/GameActions.cpp`). It frees the speaker at once when the NPC stands within 4 m of the cage or the shackles, and it gives the NPC the task otherwise. When the speaker is still locked up after 30 seconds of unpaused game, `WatchReleases` frees it, because the package of a jailer can keep it at its desk: the captain of a bounty desk never left the desk for the task.

A slave in a cage reads as `imprisoned`, because the plugin checks the cage before the slave state (`plugin/game/Context.cpp:659`). The plugin must therefore send the slave state apart from `character_state` (`isSlave` in `plugin/game/Context.cpp:663`), so that a slave in a cage also goes to plain chat.

The action dialogue ends when the player accepts an offer.

## 3. Hard limits

The guard releases the speaker only for a bribe of at least 500 cats plus the bounty of the speaker (`offers.release_fee`). The bounty is the total of `BountyManager::getTotalBounty`, which the plugin sends as `bounty` in each context. The turn message names the least bribe, and the bounty when the speaker has one. The server drops an offer with a smaller fee, and an offer of a fee that the player does not have. The prompt does not give the cats of the player's squad, because an NPC that saw them asked for all of them.

## 4. Lean

The lean ([Outcome](framework.md#outcome)) is how likely the NPC is to free the speaker. It counts the relation, on the scale of [Outcome](framework.md#outcome), and this fact:

| Fact | Bonus |
|---|---|
| The speaker's `health` is `Crippled` | +1 |

A crippled prisoner cannot escape, so the NPC takes its cats at no risk. The wound adds at most +1, so the relation weighs more.
