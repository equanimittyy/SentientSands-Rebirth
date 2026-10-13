# Proposal: BARTER

## 1. Summary

In a BARTER action dialogue, the player trades items with the NPC: the player buys or sells an item, swaps items, gives an item or cats for nothing, or asks the NPC for charity. The player can haggle over the price. A gift is a trade at no price, and the NPC is glad to take it. The player opens it with `!b` or `!barter`. [framework.md](framework.md) holds the rules that all categories share.

A trade is between the speaker and the NPC only. The cats of the player belong to the whole player faction, so a deal can spend all of them. The items belong to each player character, so only the items that the speaker carries can trade, and the items of the other squad members stay out. The Barter window is the exception: its deal can hold the items of each squad member ([architecture.md](../../info/architecture.md#barter-window)).

## 2. Deals

Any NPC can trade, but a trader gives better prices ([section 3](#3-hard-limits)).

A prisoner can trade too, for example to ask a guard for bread. When the speaker is `imprisoned` (`plugin/game/Context.cpp:744`), the prompt says so, and it gives the NPC's Current Job, for example "Guarding the town", and whether the NPC is `imprisoned` too.

The action dialogue ends when the player accepts an offer.

### Offer boxes

An offer of BARTER shows in two boxes of the popup instead of the popup line of [Offer](framework.md#offer). The boxes stand side by side, "You are offering:" and "They are offering:", and the buttons Accept and Decline are at the bottom. The buttons work as in [Offer](framework.md#offer).

| You are offering: | They are offering: |
|---|---|
| 500 cats | 1 Katana |
| 1 Dirty Loincloth | |

Each box lists the cats first, and then each item with its count, the biggest count first and items of one count by name. A box with nothing in it, as in a gift or in charity, shows "Nothing". The server fills the boxes from the checked offer, as it writes the popup line. The boxes reuse the list boxes of the existing windows, for example the event list of the Events window (`MyGUI::ListBox` in `plugin/ui/EventsWindow.cpp:20`).

## 3. Hard limits

Each side gives only the cats that it has and the items that it carries, except in charity ([section 4](#4-charity)). A trader in a shop gives only the items of its stock ([section 6](#6-price-guide)). For the player, these are the cats of the player faction and the items of the speaker.

The worth of a deal is no hard limit. The turn message gives what each side is worth to the NPC, and the model weighs it, so the NPC can agree to a deal at a loss. The worth of each part of the deal:

| Part | Worth |
|---|---|
| Cats, from either side | Their count |
| An item of the player | Its `price` (`plugin/game/Context.cpp:605`) times the buy share of the NPC, times its count |
| An item of the NPC | Its `price` times the sell share of the NPC, times its count |

Each NPC sells at the full `price`, which is the price in the trade window of the game, so a deal never undercuts the trade window. A non-trader wants a bigger profit margin, so it pays less for the items of the player:

| NPC | Sell share | Buy share |
|---|---|---|
| A trader: its Current Job (`current_job` in `server/chat/current_job.py:41`) is `Trading`, `Running a shop`, or `Travelling as a trader` | 100% | 80% |
| Any other NPC | 100% | 60% |

For example, a trader sells a Katana with a `price` of 3,000 for at least 3,000 cats, and it buys the Katana for at most 2,400 cats.

An NPC can take a loss on a deal when its character would, for example a friend who gives a discount. A neutral NPC instead wants a profit, and an NPC that dislikes the player wants a bigger one. The turn message gives a guide to the loss that the NPC usually takes at most, or the profit that it usually wants, as a share of the worth that it gives, by its relation to the player (`offers.LOSS_SHARES`). No check enforces the guide, so the model decides each deal by the character.

| Relation of the NPC | Guide |
|---|---|
| -60 or lower | A profit of at least 30% |
| -59 to -25 | A profit of at least 20% |
| -24 to 24 | A profit of at least 10% |
| 25 to 59 | A loss of at most 10% |
| 60 or higher | A loss of at most 20% |

For example, the guide has a neutral trader sell the Katana for at least 3,300 cats, and it lets a liked trader sell the Katana for 2,700 cats.

## 4. Charity

In charity, the NPC gives without receiving anything. Charity costs the NPC nothing, so that the player can beg on the streets: the plugin creates the cats or the food for the speaker, and the NPC's own cats and items stay.

Charity has tight limits:

- The NPC gives at most 50 cats, or 1 Dried Gristle Flaps, the cheapest food in the game data (base value 40, `50568-rebirth.mod`).
- After an NPC gives charity, a plea for more charity takes -2 on its lean for the rest of the game day ([section 7](#7-lean)). A second plea is thus likely refused, but not blocked. A trade with the NPC keeps its lean. The server keeps the day of the last charity of each NPC in memory, so a restart of the server forgets it.

The model often offers more cats than the cap, for example 500 cats from an NPC that holds 3,000 cats. The server then cuts the offer to 50 cats, and it does not drop the offer, so the player still gets the charity. The popup shows 50 cats, although the reply of the NPC can name more. Each turn message of a trade also states the cap next to the cats of the NPC (`offers.facts`).

For food, the model writes `GIVE_FOOD`, and code picks the food. The prompt names no food, because the model offered a food that the charity rule listed, Dried Meat, as its own stock in a trade.

`GIVE_CATS` takes the cats from the NPC (`plugin/game/GameActions.cpp:572`), so charity needs an action that only adds the cats to the player. `SPAWN_ITEM` already creates an item for the speaker (`plugin/game/GameActions.cpp:680`).

## 5. Gifts

A gift raises the NPC's profile `Relation` (`change_relation` in `server/store/campaign_db.py:282`) by 1 for each 500 cats of the worth that the NPC receives ([section 3](#3-hard-limits)), at most by 10 for each gift. A gift worth less than 500 thus gives nothing, so small gifts cannot farm relation. The game shows "X appreciates the gift." as a message, as it shows "Gained 200 cats." (`showPlayerAMessage_withLog` in `plugin/game/GameActions.cpp:573`).

## 6. Price guide

The prompt opens with a stocktake of the NPC: the name and the count of each item, with no prices. For a trader in a shop, the stocktake holds only the items in all the furniture of its building, because the trade window of the game shows them as its stock, and the trader keeps what it carries ([kenshi_internals.md](../../info/kenshi_internals.md#inventories)). The furniture of the building can hold items that are not stock, for example the personal chest of a guard. The NPC can then sell those items too, and the plan accepts that cost. Each turn, code finds the items that the player's line and the NPC's last reply ask for, in the inventories of the NPC and the speaker, and it adds each item with its count and its `price` to the turn message, at most 10 items for each side. A line asks for an item by a word of its name, for example "water" for Water Jug, or by a word for its kind, for example "food", or "drink" for alcohol, which the game data files under narcotics. The model thus gets the real price of each item that the deal is about, and it does not invent one.

One item can have a different `price` on different holders, for example a Standard First Aid Kit was 102 on a barman and 132 in the furniture of the bar ([kenshi_internals.md](../../info/kenshi_internals.md#inventories)). The deal therefore takes the `price` of an item from the stock of the NPC, because that is the price that the NPC sells at. When the stock holds the item at different prices, the deal takes the highest. When the stock does not hold the item, the deal takes the highest `price` of the item in the inventory of the speaker.

The stocktake, the price guide, and the offer name each weapon and each armour with its quality from the game, so two items with one name and different prices stay apart. A weapon keeps its grade in `materialData` and its maker in `manufacturerData`, and an armour keeps its grade in `getLevel` (`deps/KenshiLib/Include/kenshi/Item.h:63` to `:66`) ([kenshi_internals.md](../../info/kenshi_internals.md#inventories)). The plugin writes them into the name of the item, for example `Katana (Ancient, Refitted Blade)` or `Chain Shirt (High)` (`ItemLabel` in `plugin/game/Context.cpp`). The armour grades follow the level in steps of 20, from Prototype at 0 to Masterwork at 100. A name without the grade finds the item when the holder holds only one grade of it.

## 7. Lean

The lean ([Outcome](framework.md#outcome)) is how likely the NPC is to take the deal. It counts the relation, on the scale of [Outcome](framework.md#outcome).

After the NPC gives charity in a game day ([section 4](#4-charity)), the thought gets one more line: the band of a plea for charity, which is the lean -2, for example "If Zaps begs for charity: You are inclined to refuse. You already gave charity today." (`offers.facts`). The turn message comes before the reply, so the server does not know if the player begs or trades, and the -2 thus stays out of the lean of a trade.

In the Barter window, code knows the deal on the table, so the lean also counts the worth of the deal to the NPC ([section 3](#3-hard-limits)) by its profit share: the profit divided by the worth that the NPC gives (`offers.profit_lean`). The model refused deals at a profit when the lean counted only the relation. A deal that keeps the NPC's price and the profit that it wants therefore lifts a neutral NPC to agree, and a bigger profit outweighs a worse relation. A gift costs the NPC nothing, so it counts as a big profit.

| Deal on the table | Lean | Reason in the thought |
|---|---|---|
| At the NPC's price and the profit that it wants, with a profit under 25% | +2 | "The deal on the table earns you 300 cats.", or "The deal on the table keeps your price." with no profit |
| A profit of 25% up to 50% | +3 | "The deal on the table earns you 750 cats, a good profit." |
| A profit of 50% or more, or a gift | +4 | "The deal on the table earns you 1,500 cats, a big profit." |
| Below the price, inside the loss that the NPC usually takes | 0 | None |
| At the price, with less than the profit that the NPC wants | 0 | None |
| Below the price by more than that loss | -2 | "The deal on the table loses you 120 cats, more than you usually take." |

In a chat trade, the deal is only in the words of the player, so code cannot know its worth. The value of the trade reaches the model through the price guide ([section 6](#6-price-guide)) instead. Each turn message of a trade also states that a trade that gets the NPC more than it gives is a profit, and that the NPC takes a bigger profit more gladly (`offers.facts`).
