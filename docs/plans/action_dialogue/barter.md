# Proposal: BARTER

## 1. Summary

In a BARTER action dialogue, the player trades items with the NPC: the player buys or sells an item, swaps items, gives an item or cats for nothing, or asks the NPC for charity. The player can haggle over the price. A gift is a trade at no price, and the NPC is glad to take it. The player opens it with `!b` or `!barter`. [framework.md](framework.md) holds the rules that all categories share.

A trade is between the speaker and the NPC only. The cats of the player belong to the whole player faction, so a deal can spend all of them. The items belong to each player character, so only the items that the speaker carries can trade, and the items of the other squad members stay out.

## 2. Deals

Any NPC can trade, but a trader gives better prices ([section 3](#3-hard-limits)).

A prisoner can trade too, for example to ask a guard for bread. When the speaker is `imprisoned` (`plugin/game/Context.cpp:675`), the prompt says so, and it gives the NPC's Current Job, for example "Guarding the town", and whether the NPC is `imprisoned` too.

The action dialogue closes when the player accepts an offer.

### Barter window

An offer of BARTER shows in a barter window instead of the popup line of [Offer](framework.md#offer). The window has two boxes side by side, "You are offering:" and "They are offering:", and the buttons Accept and Decline at the bottom. The buttons work as in [Offer](framework.md#offer).

| You are offering: | They are offering: |
|---|---|
| 500 cats | 1 Katana |
| 1 Dirty Loincloth | |

Each box lists the cats first, and then each item with its count. A box with nothing in it, as in a gift or in charity, shows "Nothing". The server fills the boxes from the checked offer, as it writes the popup line. The boxes reuse the list boxes of the existing windows, for example the event list of the Events window (`MyGUI::ListBox` in `plugin/ui/EventsWindow.cpp:22`).

## 3. Hard limits

Each side gives only the cats that it has and the items that it carries, except in charity ([section 4](#4-charity)). For the player, these are the cats of the player faction and the items of the speaker.

Each deal except charity holds this rule: what the NPC receives is worth at least what it gives. The worth of each part of the deal:

| Part | Worth |
|---|---|
| Cats, from either side | Their count |
| An item of the player | Its `price` (`plugin/game/Context.cpp:966`) times the buy share of the NPC, times its count |
| An item of the NPC | Its `price` times the sell share of the NPC, times its count |

A non-trader wants a bigger profit margin, so it fleeces the player more:

| NPC | Sell share | Buy share |
|---|---|---|
| A trader: its Current Job (`current_job` in `server/chat/current_job.py:41`) is `Trading`, `Running a shop`, or `Travelling as a trader` | 80% | 60% |
| Any other NPC | 100% | 40% |

For example, a trader sells a Katana with a `price` of 3,000 for at least 2,400 cats, and it buys the Katana for at most 1,800 cats.

## 4. Charity

In charity, the NPC gives without receiving anything. Charity costs the NPC nothing, so that the player can beg on the streets: the plugin creates the cats or the food for the speaker, and the NPC's own cats and items stay.

Charity has tight limits:

- The NPC gives at most 50 cats, or 1 food item (`ITEM_FOOD` in `deps/KenshiLib/Include/kenshi/Enums.h:224`) with a `price` of 100 or less.
- Each NPC gives charity at most once in each game day.

`GIVE_CATS` takes the cats from the NPC (`plugin/game/GameActions.cpp:730`), so charity needs an action that only adds the cats to the player. `SPAWN_ITEM` already creates an item for the speaker (`plugin/game/GameActions.cpp:1018`).

## 5. Gifts

A gift raises the NPC's profile `Relation` (`change_relation` in `server/store/campaign_db.py:267`) by 1 for each 500 cats of the worth that the NPC receives ([section 3](#3-hard-limits)), at most by 10 for each gift. A gift worth less than 500 thus gives nothing, so small gifts cannot farm relation. The game shows the gain as a message, as it shows "Gained 200 cats." (`showPlayerAMessage_withLog` in `plugin/game/GameActions.cpp:732`).

## 6. Price guide

The prompt opens with a stocktake of the NPC: the name and the count of each item, with no prices. Each turn, code finds the items that the player's line and the NPC's last reply name, in the inventories of the NPC and the speaker, and it adds each item with its `price` to the turn message. The model thus gets the real price of each item that the deal is about, and it does not invent one.

The stocktake, the price guide, and the offer name each weapon and each armour with its quality from the game, so two items with one name and different prices stay apart. The item holds the candidate data (`manufacturerData`, `quality`, and `getLevel` in `deps/KenshiLib/Include/kenshi/Item.h:63` to `:74`), but the plugin does not send it yet.

## 7. Lean

The lean ([Outcome](framework.md#outcome)) is how likely the NPC is to take the deal. It counts only the relation, on the scale of [Outcome](framework.md#outcome). The value of the trade reaches the model through the price guide ([section 6](#6-price-guide)) instead.

## 8. Open questions

1. Where does a shopkeeper keep its stock? `inventory` reads only the items of the character and its backpack (`GetAllCharacterItems` in `plugin/game/GameActions.cpp`). An in-game probe decides it ([development.md](../../info/development.md#probes)).
2. Which data of an item holds the quality that the game shows for a weapon or an armour?
3. How does code find the template and the `price` of a charity food that the NPC does not carry?
