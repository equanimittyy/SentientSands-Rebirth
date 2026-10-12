# Proposal: HEAL

## 1. Summary

In a HEAL action dialogue, the player asks the NPC to treat the speaker's wounds. The player opens it with `!h` or `!heal`. [framework.md](framework.md) holds the rules that all categories share.

HEAL treats only the speaker. A knocked-out squad member cannot speak ([Blocked](framework.md#blocked)), so HEAL cannot treat it.

## 2. Deal

HEAL needs all of these, and a line that fails one goes to plain chat with the reason ([Plain chat](framework.md#plain-chat)):

- The speaker has a wound: a body part whose flesh and bandage are below its full health (`needs_first_aid` and `needs_repair` in the speaker's context, `TreatmentNeeds` in `plugin/game/Context.cpp`). A slight wound counts too, although `health` (`GetHealthStatus` in `plugin/game/Context.cpp:118`) says `Injured` only below 70% of a part. A bandaged wound does not count, because the game counts the bandage as healed when it picks a patient for first aid.
- The NPC carries a kit that fits a wound: a first aid item for flesh (`has_first_aid`, `ITEM_FIRSTAID`), or a repair kit for a robot body or a robotic limb (`has_repair_kit`, `ITEM_ROBOTREPAIR`), from `hasItemFunction` in `deps/KenshiLib/Include/kenshi/Inventory.h:195`. A character with robotic limbs can need both kits, and one fitting kit is enough. The block names the missing kits, for example "You have no first aid kit or repair kit."
- The NPC is not `imprisoned` (`plugin/game/Context.cpp:675`), because a fellow prisoner cannot help.

Treatment needs no medical skill, because any NPC can treat a wound.

The treatment gives the NPC the game's `FIRST_AID_ORDER` task (`deps/KenshiLib/Include/kenshi/Enums.h:304`) for the flesh wounds and `FIRST_AID_ROBOT` for the robotic damage, each only when the NPC carries the kit, as orders with the speaker as their target (`StartTreatment` in `plugin/game/GameActions.cpp`). The repair queues behind the first aid. A speaker who needs a repair gets a fact in the turn message that says whether the NPC can repair it (`offers.facts`). The release gives `RELEASE_PRISONER` as an order in the same way (`plugin/game/GameActions.cpp:793`). A `JOB_MEDIC` job has no target, so it cannot aim the treatment at the speaker. An in-game test showed that the first aid order makes an NPC outside the squad treat the speaker ([kenshi_internals.md](../../info/kenshi_internals.md#orders-and-contracts)).

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
