# Proposal: LIBERATE

## 1. Summary

In a LIBERATE action dialogue, the player asks the NPC to free the speaker from a prison cage or from slavery. The player opens it with `!l` or `!liberate`. [framework.md](framework.md) holds the rules that all categories share.

## 2. Deal

LIBERATE needs all of these ([Blocked](framework.md#blocked)):

- The speaker is a prisoner or a slave: its `character_state` (`plugin/game/Context.cpp:675`) is `imprisoned` or `enslaved`.
- The NPC is not `imprisoned`, because a fellow prisoner cannot free anyone.
- The NPC is not a guard when the speaker is a slave, because a guard never releases a slave.

A guard ([Outcome](framework.md#outcome)) releases the speaker, and any other NPC breaks the speaker out:

| NPC | Task | Popup ([Offer](framework.md#offer)) |
|---|---|---|
| A guard | `RELEASE_PRISONER` | Guard offers your release for 500 cats. |
| Any other NPC | `BREAKOUT_PRISONER` | Drifter offers to break you out for 500 cats. |

Both tasks run through the release handler (`ACT_RELEASE` in `plugin/game/GameActions.cpp:793`). It frees the speaker at once when the NPC stands within 4 m of the cage or the shackles, and it gives the NPC the task otherwise.

A slave in a cage reads as `imprisoned`, because the plugin checks the cage before the slave state (`plugin/game/Context.cpp:659`). The plugin must therefore send the slave state apart from `character_state` (`isSlave` in `plugin/game/Context.cpp:663`), so that the guard rule also holds in a cage.

The action dialogue closes when the player accepts an offer.

## 3. Hard limits

The player has the cats of the fee. A release has no `price`, so code sets no bound on the fee.

## 4. Lean

The lean ([Outcome](framework.md#outcome)) is how likely the NPC is to free the speaker. It counts the relation, on the scale of [Outcome](framework.md#outcome), and a crippled speaker:

| The speaker's `health` | Bonus |
|---|---|
| `Crippled` | +1 |

A crippled prisoner cannot escape, so the NPC takes its cats at no risk. The wound adds at most +1, so the relation weighs more.
