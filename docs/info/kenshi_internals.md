# Kenshi internals

The plugin reads the game objects of Kenshi through KenshiLib. This page records how those objects behave in the game and the methods that work in the game. The probe lines of in-game tests showed each fact ([development.md](development.md#probes)). Its sister page, [kenshi_gotchas.md](kenshi_gotchas.md), records the calls and the patterns that broke the plugin. Read both before you change plugin code that calls the game.

## String IDs

Each record of the game data, for example a faction, a character template, or a zone, has a string ID. The string ID is `<number>-<mod file>`, and the mod file is the file that adds the record, for example `44420-Dialogue.mod` or `204-gamedata.base`.

A change of the mod list is not tested, by decision. Because a string ID names the mod file that adds the record, only the removal of that mod is expected to change it.

## Character identity

`hand::toString()` gives the handle of a character as `index-serial-container-containerSerial-type`. `container` and `containerSerial` name the squad of the character, and `index` is its place in that squad.

| Event | What stays the same |
|---|---|
| A save and a load | The whole handle |
| A town reload: the player leaves the town until it unloads, and comes back | The whole handle of a generic trader |
| A recruit into the player's squad | Only `serial`. The recruit changes `index`, `container`, and `containerSerial`. |

- Characters of other squads can have the same `serial`. In one session, 2 of the 5 characters of the start squad had the `serial` of a loaded character of another squad: Zip had the `serial` of a Shinobi Thieves guard, and Izumi had the `serial` of a Bonedog.
- The instance ID (`getInstanceID()->uid`) and the layout instance ID (`getLayoutInstanceID`) are empty for unique and generic NPCs.
- `npc->data->stringID` is the string ID of the template of the character. Many generic NPCs share one template.
- `Character::isUnique` gives `1` for a unique NPC, such as Ruka, Harenga the Loud, or Jewel, whose template is its own. It gives `0` for a generic NPC, whose template has a generated name, such as `Barman /GENNAME/`.
- The flag of a template depends on the mod list. The game data files show that Yamdu is generic without UWE and unique with it, and that the Yabuta Chief is unique without UWE and becomes the generic `Chief /GENNAME/` with it.

## Names

- A template name can hold one name token, a word in capitals between slashes, for example `Barman /GENNAME/`. The game shows the NPC with a name in place of the token, for example Barman Arleen, and `npc->data->name` keeps the token.
- The vanilla game data has no name token. UWE gives one to 661 of its 1184 generic templates, with the tokens `/GENNAME/`, `/HNNAME/`, `/UCNAME/`, `/SKNAME/`, `/CANNAME/`, `/VIK/`, `/HIVNAME/`, and `/FISNAME/`. No template has two tokens. These counts come from the game data files of vanilla Kenshi and of UWE, not from a probe.

## Factions

`FactionManager::getAllFactions` lists each faction of the game, and `faction->data->stringID` gives its string ID. The `game_id` of each faction file of SSR Vanilla comes from the `FACTION_PROBE` lines of one mod list.

## Zones

- `ZoneManager::getBiome` gives only the ground type, such as Canyonland FlatTop, so it cannot name the zone.
- The zone object (`AreaBiomeGroup`) holds the zone record, for example Stenn Desert, at slot `0x10`. `WeatherSystem::ActiveRegion` and `TownBase::getBiome` both give a zone object.
- Slot `0x120` also holds a zone record, but not the zone that the map shows.

## Deaths and captures

A probe of these hooks in several played sessions showed these facts. The plugin sends the game events from the same hooks (see [architecture.md](architecture.md#game-events)).

| Hook or call | Behavior |
|---|---|
| `declareDead` | Runs for each death of a person or an animal, in a fight and when a knocked-out character bleeds out. A character that bleeds out is still knocked out (`PS_KO`) when it runs. It does not run again when a save with dead bodies loads. |
| `setProneState` with `PS_KO` | Runs about 10 times a second while a character lies knocked out, also after the last attack of the fight. A character that wakes up and goes down again gets it anew. |
| `setProneState` with another state | Runs when a knocked-out character wakes up, and also each time someone picks up a knocked-out character. |
| `setPrisonMode` with `on` | Runs when a character goes into a prisoner cage, also with no knockout and no attack before it. A captor put a knocked-out Scavenger into a cage 158 game minutes after the last attack on it. |
| `setPrisonMode` with `on` false | Runs when a character leaves a cage, but also after the knockouts and the deaths of characters that nobody carried, so it tells nothing. |
| `Character::isBeingCarried` | True at a pickup, but also at `setPrisonMode` with `on` false for knocked-out Bonedogs that nobody carried. |
| `Character::getAllAttackers` | Gave an attacker for 1 of 56 knockouts, and for none of 17 deaths and 16 prison changes, also when an attack came in the same second. |
| `attackingYou` | Runs many times a second for each attacker, for example 2,182 times in 15 s for one attacker and one target. |

- The knockout, death, and prison hooks run off the game thread. The game thread is the thread that started the plugin (`g_mainThreadId`), because the chat context reads the inventory only on that thread.
- When a save loads, the knockout hook runs again for each character that lies knocked out, and `setPrisonMode` with `on` runs again for each prisoner in a cage, a few seconds after the load.
- When the captor puts the character into a cage, the game shows neither the knockout nor the carry: the bandit that the player carried into a cage was not `PS_KO` and not carried at `setPrisonMode`.
- 5 Bonedogs bled out more than 3 game hours after the last attack on them.
- `Character::isAnimal` marks Bonedogs, Blood Spiders, and Bog Dogs. A Gurgler, of the race Fishman, is not an animal.
- `getCurrentTownLocation` also gives animal dens, such as `Bog Dog Den 9`.
- A mod can split one animal into several races: `Wolf_Headgear.mod` gives Bonedogs the races `Bonedog (white)`, `Bonedog (yellow)`, and `Bonedog (darkbrown)` besides `Bonedog`. The name of each of these Bonedogs stays `Bonedog`.

## Squads

`PlayerInterface::getCurrentPlatoon` gives the squad that the player selected. A squad member is in that squad when its `Character::getPlatoon` is the `getActivePlatoon` of that squad.

## Roles

The role probe logged 26 characters in one town of a UWE game.

- The squad template of a character (`Character::getPlatoon()->me->squadTemplate`) and its AI package decide the role. The jobs of the package reach the character as `TaskType` values in `OrdersReceiver::squadAIPackage`, one list for each priority. A shop guard held `STAND_AT_GUARD_NODE_HOMEBUILDING_IN_OUT`, the barman who led the same squad held `SIT_ON_THRONE`, and the mercenaries in a bar held `RELAX_IN_TOWN_PACKAGE`.
- The `is trader` flag belongs to the squad template, not to the character. A shop squad has the trader as its leader and Shop Guards as its members, so `Character::isATrader` is true for the shop guards too. The plugin takes only the squad leader as the trader (`RoleJson` in `plugin/game/Context.cpp`).
- The current goal (`OrdersReceiver::getCurrentGoal`) changes within seconds, for example from `PATROL_TOWN` to none.
- The names of AI packages and squads come from the mods, for example `(LB) Shop-24hr` and `Merchant (Mod)`.
- The live NPC type (`StateBroadcastData::NPCType`) equalled the `NPC class` of the template of each character.
- One character had a permajob: `JOB_REPAIR_ROBOT`, which `getPermajobName` names Robotics, as the Jobs menu does.
- The player's squad has no AI package and no squad jobs.
- An AI goal record of the game data holds its task type as the int `enum`, for example 20, `STAND_AT_SHOPKEEPER_NODE`, for the goal Shopkeeper.
- `Blackboard::getCurrentAIPackageName` gives the name of the AI package of a character. The plugin reads only the name, because the package data needs a header that clashes with `AI/Blackboard.h` (see [kenshi_gotchas.md](kenshi_gotchas.md#kenshilib-headers)).

## Inventories

The `STOCK_PROBE` and `FIRSTAID_PROBE` lines of a bar and of a shop in a Shinobi Tower showed these facts.

- `Inventory::getAllItems` leaves out the equipped items. The sections of a barman held 5 items, 2 of them in `legs` and `armour`, but `getAllItems` gave 3. `GetAllCharacterItems` (`plugin/game/Context.cpp`) reads the sections, so it gets all 5.
- The barman carried only his own items, and his inventory was not a `ShopTraderInventory`. The bar (`Character::isIndoors().getBuilding()`) had no inventory: `getInventory` gave null.
- The trade window of the bar showed the items in all the furniture of the bar. For Water, Vodka, Water Jug, and Bread, the counts in the window were the sums over `Building::findAllFurnitureWithFunction` with `BF_ANY`, for example 14 Water Jugs. The shop counters (`Ownerships::getHomeFurnitureOfType` with `BF_SHOP`) held only 4 of the 14 Water Jugs. Each piece of furniture keeps its items in the `backpack_content` section, and its inventory is not a `ShopTraderInventory`.
- `Item::getValueSingle(false)` gave one item a different price on different holders: a Standard First Aid Kit was 102 on the barman and 132 in the furniture.
- The data of a weapon holds its grade: `materialData` names the grade, for example "09 - Refitted Blade", and `manufacturerData` names the maker, for example "Ancient". `Item::getLevel` rises with the grade.
- `Item::getLevel` gives the grade of an armour: 40 is Standard and 60 is High. The game showed no grade for Shinobi Clothpants (alt) at level 60, whose game data covers no body part (no `part coverage`).
- `Inventory::hasItemFunction` with `ITEM_FIRSTAID` was true for the barman, who carried a Standard First Aid Kit.

## Orders and contracts

- `Character::addOrder` with `FIRST_AID_ORDER` and an injured player character as the target made a shop guard outside the squad walk 50 m to the character and treat it.
- `Blackboard::_setContractJob` with the `Bodyguard` AI package (`5090-gamedata.base`) and 6 hours started a hire contract on a vagrant outside the squad. `hasContractJob` became true, `getContractExpiryTime` was 6 game hours after the call, the AI package became `Bodyguard`, and the NPC took the task `FOLLOW_PLAYER_ORDER` (44). The UI of the game showed the NPC as a hired mercenary. The KenshiLib header marks the function private in a comment, but declares it public, and `KenshiLib.lib` exports it.
- `Blackboard::endContractJob` ended that hire contract early on two NPCs. `hasContractJob` became false, the AI package became empty, and the NPC stopped following.

## Crash dumps

When the game crashes, Kenshi writes a zip, for example `crashDump1.0.65_x64.zip`, with a minidump (`.dmp`) and the logs of the game. The minidump holds the exception, the registers of the thread that crashed, the loaded modules, and the stack memory. These steps find the plugin call that crashed the game:

1. Compare the time stamp and the size of `SentientSands.dll` in the module list of the minidump with the build in `plugin/x64/Release`. Only a match lets `SentientSands.pdb` name the plugin frames.
2. Read the exception code, the address that the failed instruction read, and the instruction address (`Rip`). A crash in game code shows as an offset in `kenshi_x64.exe`.
3. Scan the stack from `Rsp` for addresses in `SentientSands.dll`, and name each with the procedure records of the PDB. The scan also finds old return addresses of earlier calls, so disassemble the plugin code before each return address to find the real call (`objdump -d`, image base `0x180000000`).
4. Name the game frames with the `RVA = 0x...` comments of the KenshiLib headers. The function with the nearest lower RVA is the best match, because the headers do not list every function.

The dev container has `objdump` with PE support, but no minidump or PDB reader. A short Python script with `struct` reads both formats.
