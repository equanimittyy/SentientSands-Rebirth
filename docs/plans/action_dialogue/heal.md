# Proposal: HEAL

## 1. Summary

In a HEAL action dialogue, the player asks the NPC to treat the speaker's wounds. The player opens it with `!h` or `!heal`. [framework.md](framework.md) holds the rules that all categories share.

## 2. Deal

HEAL needs all of these ([Blocked](framework.md#blocked)):

- The speaker's `health` (`plugin/game/Context.cpp:676`) is `Injured` or `Crippled` (`GetHealthStatus` in `plugin/game/Context.cpp:115`).
- The NPC carries a first aid item (`hasItemFunction` with `ITEM_FIRSTAID` in `deps/KenshiLib/Include/kenshi/Inventory.h:195`). The plugin does not send this yet.
- The NPC is not `imprisoned` (`plugin/game/Context.cpp:675`), because a fellow prisoner cannot help.

Treatment needs no medical skill, because any NPC can treat a wound.

The popup ([Offer](framework.md#offer)) is, for example, "Doctor offers treatment for 300 cats.".

The action dialogue closes when the player accepts an offer.

## 3. Hard limits

The player has the cats of the fee. Treatment has no `price`, so code sets no bound on the fee.

## 4. Lean

The lean ([Outcome](framework.md#outcome)) is how likely the NPC is to treat the speaker. It counts the relation, on the scale of [Outcome](framework.md#outcome), and the wound of the speaker, because a worse wound raises the demand for treatment:

| The speaker's `health` | Bonus |
|---|---|
| `Injured` | +1 |
| `Crippled` | +2 |
