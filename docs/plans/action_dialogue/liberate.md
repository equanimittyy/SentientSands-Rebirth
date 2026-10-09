# Proposal: LIBERATE

## 1. Summary

In a LIBERATE action dialogue, the player asks the NPC to free the speaker from prison. The player opens it with `!l` or `!liberate`. [framework.md](framework.md) holds the rules that all categories share.

## 2. Deal

The NPC offers a release only when the speaker's `character_state` (`plugin/game/Context.cpp:675`) is `imprisoned`.

The popup ([Offer](framework.md#offer)) is, for example, "Guard offers your release for 500 cats.".

The action dialogue closes when the player accepts an offer.

## 3. Hard limits

The player has the cats of the fee. A release has no `price`, so code sets no bound on the fee.

## 4. Lean

The lean ([Outcome](framework.md#outcome)) is how likely the NPC is to free the speaker. It counts the relation, on the scale of [Outcome](framework.md#outcome), and a crippled speaker:

| The speaker's `health` | Bonus |
|---|---|
| `Crippled` | +1 |

A crippled prisoner cannot escape, so the NPC takes its cats at no risk. The wound adds at most +1, so the relation weighs more.
