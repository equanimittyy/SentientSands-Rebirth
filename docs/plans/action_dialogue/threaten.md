# Proposal: THREATEN

## 1. Summary

In a THREATEN action dialogue, the player threatens the NPC, demands its cats or items, or challenges it to a fight. The player opens it with `!t` or `!threaten`. [framework.md](framework.md) holds the rules that all categories share.

## 2. Gate

A threat of an `imprisoned` speaker (`plugin/game/Context.cpp:744`) goes to plain chat ([Plain chat](framework.md#plain-chat)), because no one takes a threat from a cage seriously. The NPC's thought gives that reason. THREATEN has no other gate.

A chained slave (`enslaved`) can threaten: the NPC, for example a guard, can laugh it off or beat the slave for it.

## 3. Answers

The NPC answers a threat, a demand, or a challenge to a fight in one of three ways:

| Answer | Result |
|---|---|
| It gives in | It makes an offer of the handover ([Offer](framework.md#offer)), for example "Bandit offers 200 cats and a Katana.". When the player declines the offer, the player can demand more in the reply. |
| It fights | The reply ends with `[ATTACK]`, and `ATTACK` runs at once. The NPC attacks the speaker ([Speaker](framework.md#5-speaker)), and its squad fights the squad of the speaker. |
| It refuses | It neither gives in nor fights, and the action dialogue goes on. |

The action dialogue ends when the player accepts an offer, or when the NPC attacks the speaker.

An attack marks the NPC's squad and the speaker's squad as temporary enemies of each other, because the game marks only the hitter of a character as its enemy. The fight ends when one squad is all knocked out or dead, or when neither squad attacks the other for 30 s of unpaused game time, for example after the player runs away. The plugin then clears the marks and the AI goals of the NPC's squad, so that the NPC does not attack the speaker again when the speaker gets up (`WatchFights` in `plugin/game/GameActions.cpp`).

## 4. Hard limits

The NPC hands over only the cats that it has and the items that it carries.

## 5. Lean

The lean ([Outcome](framework.md#outcome)) is how likely the NPC is to give in:

| Fact | Bonus |
|---|---|
| The melee attack plus the melee defence of the speaker (`stats` in `plugin/game/Context.cpp:915`) is above the NPC's | +1 |
| The same sum is below the NPC's | -1 |
| The squad members near the NPC (`nearby` in `plugin/game/Context.cpp:822`) outnumber the members of the NPC's faction near it | +1 |
| The squad members near the NPC are fewer | -1 |
| The NPC's `health` is `Injured` or `Crippled` | +1 |
| The speaker's `health` is `Injured` or `Crippled` | -1 |
| The NPC is the leader of its faction (`is_leader`) or unique (`unique`) | -1 |

`nearby` leaves out the first squad character (`plugin/game/Context.cpp:830`), so the count must add that character when it is near.
