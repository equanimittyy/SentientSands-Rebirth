# Proposal: BARTER

## 1. Summary

In a BARTER action dialogue, the player trades items with the NPC: the player buys or sells an item, or gives an item or cats for nothing. The player can haggle over the price. A gift is a trade at no price, and the NPC is glad to take it. The player opens it with `!b` or `!barter`. [framework.md](framework.md) holds the rules that all categories share.

## 2. Deals

Any NPC can trade, but a trader gives better prices ([section 3](#3-hard-limits)).

A prisoner can trade too, for example to ask a guard for bread. When the speaker is `imprisoned` (`plugin/game/Context.cpp:675`), the prompt says so, and it gives the NPC's Current Job, for example "Guarding the town", and whether the NPC is `imprisoned` too.

The popup of each deal ([Offer](framework.md#offer)):

| Deal | Popup |
|---|---|
| The NPC sells | Trader offers a Katana for 3,000 cats. |
| The NPC buys | Trader offers 1,200 cats for your Katana. |
| A gift | Trader offers thanks for your Katana. |

The action dialogue closes when the player accepts an offer.

## 3. Hard limits

- Each side gives only the cats that it has and the items that it carries.
- The NPC sells an item for at least a share of its `price` (`plugin/game/Context.cpp:966`), and it buys an item for at most a share of its `price`. A non-trader wants a bigger profit margin, so it fleeces the player more.

| NPC | Sells for at least | Buys for at most |
|---|---|---|
| A trader: its Current Job (`current_job` in `server/chat/current_job.py:41`) is `Trading`, `Running a shop`, or `Travelling as a trader` | 80% of the `price` | 60% of the `price` |
| Any other NPC | 100% of the `price` | 40% of the `price` |

## 4. Price guide

The prompt opens with a stocktake of the NPC: the name and the count of each item, with no prices. Each turn, code finds the items that the player's line names in the inventories of the NPC and the speaker, and it adds each item with its `price` to the turn message. The model thus gets the real price of each item that the deal is about, and it does not invent one.

## 5. Lean

The lean ([Outcome](framework.md#outcome)) is how likely the NPC is to take the deal. It counts only the relation, on the scale of [Outcome](framework.md#outcome). The value of the trade reaches the model through the price guide ([section 4](#4-price-guide)) instead.
