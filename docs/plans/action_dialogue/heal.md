# Proposal: HEAL

## 1. Summary

In a HEAL action dialogue, the player asks the NPC to treat the speaker's wounds. The player opens it with `!h` or `!heal`. [framework.md](framework.md) holds the rules that all categories share.

HEAL treats only the speaker. A knocked-out squad member cannot speak ([Blocked](framework.md#blocked)), so HEAL cannot treat it.

## 2. Deal

HEAL needs all of these ([Blocked](framework.md#blocked)):

- The speaker has a wound: a body part below its full health (`limbs` of `medical` in the speaker's context, `plugin/game/Context.cpp`). A slight wound counts too, although `health` (`GetHealthStatus` in `plugin/game/Context.cpp:118`) says `Injured` only below 70% of a part.
- The NPC carries a first aid item (`has_first_aid` in the NPC's context, from `hasItemFunction` with `ITEM_FIRSTAID` in `deps/KenshiLib/Include/kenshi/Inventory.h:195`).
- The NPC is not `imprisoned` (`plugin/game/Context.cpp:675`), because a fellow prisoner cannot help.

Treatment needs no medical skill, because any NPC can treat a wound.

The treatment gives the NPC the game's `FIRST_AID_ORDER` task (`deps/KenshiLib/Include/kenshi/Enums.h:304`) as an order, with the speaker as its target, as the release gives `RELEASE_PRISONER` (`plugin/game/GameActions.cpp:793`). `JOB_MEDIC` (`plugin/main.cpp:793`) gives the NPC a job with no target, so it cannot aim the treatment at the speaker. An in-game test showed that the order makes an NPC outside the squad treat the speaker ([kenshi_internals.md](../../info/kenshi_internals.md#orders-and-contracts)).

The player pays the fee when it accepts the offer, before the treatment starts. The popup ([Offer](framework.md#offer)) is, for example, "Doctor offers treatment for 300 cats.". When the NPC offers to treat the speaker for free, the treatment starts at once, with no popup.

The action dialogue ends when the treatment starts.

## 3. Hard limits

The player has the cats of the fee. Treatment has no `price`, so code sets no bound on the fee.

## 4. Lean

The lean ([Outcome](framework.md#outcome)) is how likely the NPC is to treat the speaker. It counts the relation, on the scale of [Outcome](framework.md#outcome), and the wound of the speaker, because a worse wound raises the demand for treatment:

| The speaker's `health` | Bonus |
|---|---|
| `Injured` | +1 |
| `Crippled` | +2 |
