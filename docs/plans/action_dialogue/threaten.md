# Proposal: THREATEN

## 1. Summary

In a THREATEN action dialogue, the player threatens the NPC, demands its cats or items, or challenges it to a fight. The player opens it with `!t` or `!threaten`. [framework.md](framework.md) holds the rules that all categories share.

## 2. Gate

The speaker is not `imprisoned` (`plugin/game/Context.cpp:675`), because a prisoner cannot threaten or fight anyone ([Blocked](framework.md#blocked)).

## 3. Answers

The NPC answers a threat, a demand, or a challenge to a fight in one of three ways:

| Answer | Result |
|---|---|
| It gives in | It makes an offer of the handover ([Offer](framework.md#offer)), for example "Bandit offers 200 cats and a Katana.". When the player declines the offer, the player can demand more in the reply. |
| It fights | `ATTACK` runs at once. The NPC attacks the speaker ([Speaker](framework.md#5-speaker)), and the fight then spreads to the squad. |
| It refuses | It neither gives in nor fights, and the action dialogue goes on. |

The action dialogue closes when the player accepts an offer, or when the NPC attacks the speaker.

## 4. Hard limits

The NPC hands over only the cats that it has and the items that it carries.

## 5. Lean

The lean ([Outcome](framework.md#outcome)) is how likely the NPC is to give in:

| Fact | Bonus |
|---|---|
| The melee attack plus the melee defence of the speaker (`stats` in `plugin/game/Context.cpp:885`) is above the NPC's | +1 |
| The same sum is below the NPC's | -1 |
| The squad members near the NPC (`nearby` in `plugin/game/Context.cpp:800`) outnumber the members of the NPC's faction near it | +1 |
| The squad members near the NPC are fewer | -1 |
| The NPC's `health` is `Injured` or `Crippled` | +1 |
| The speaker's `health` is `Injured` or `Crippled` | -1 |
| The NPC is the leader of its faction (`is_leader`) or unique (`unique`) | -1 |

`nearby` leaves out the first squad character (`plugin/game/Context.cpp:806`), so the count must add that character when it is near.
