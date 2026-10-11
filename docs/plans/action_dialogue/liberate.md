# Proposal: LIBERATE

## 1. Summary

In a LIBERATE action dialogue, the player asks the NPC to free the speaker from a prison cage or from slavery. The player opens it with `!l` or `!liberate`. [framework.md](framework.md) holds the rules that all categories share.

## 2. Deal

LIBERATE needs all of these ([Blocked](framework.md#blocked)):

- The speaker is a prisoner or a slave: its `character_state` (`plugin/game/Context.cpp:675`) is `imprisoned` or `enslaved`.
- The NPC is not `imprisoned`, because a fellow prisoner cannot free anyone.

A guard ([Outcome](framework.md#outcome)) releases the speaker, and any other NPC breaks the speaker out:

| NPC | Task | Popup ([Offer](framework.md#offer)) |
|---|---|---|
| A guard | `RELEASE_PRISONER` | Guard offers your release for 500 cats. |
| Any other NPC | `BREAKOUT_PRISONER` | Drifter offers to break you out for 500 cats. |

Both tasks run through the release handler (`ACT_RELEASE` in `plugin/game/GameActions.cpp`). It frees the speaker at once when the NPC stands within 4 m of the cage or the shackles, and it gives the NPC the task otherwise. When the speaker is still locked up after 30 seconds of unpaused game, `WatchReleases` frees it, because the package of a jailer can keep it at its desk: the captain of a bounty desk never left the desk for the task.

A slave in a cage reads as `imprisoned`, because the plugin checks the cage before the slave state (`plugin/game/Context.cpp:659`). The plugin must therefore send the slave state apart from `character_state` (`isSlave` in `plugin/game/Context.cpp:663`), so that the lean of a guard also counts a slave in a cage ([section 4](#4-lean)).

The action dialogue ends when the player accepts an offer.

## 3. Hard limits

The player has the cats of the fee. A release has no `price`, so code sets no other bound on the fee. The prompt does not give the cats of the player's squad, because an NPC that saw them asked for all of them.

## 4. Lean

The lean ([Outcome](framework.md#outcome)) is how likely the NPC is to free the speaker. It counts the relation, on the scale of [Outcome](framework.md#outcome), and these facts:

| Fact | Bonus |
|---|---|
| The speaker's `health` is `Crippled` | +1 |
| The NPC is a guard, and the speaker is a slave (`slave`) | -2 |

A crippled prisoner cannot escape, so the NPC takes its cats at no risk. The wound adds at most +1, so the relation weighs more. A guard alone is inclined to refuse to free a slave, so only a high relation or a big fee wins it over.
