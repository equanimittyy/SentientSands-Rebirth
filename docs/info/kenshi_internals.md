# Kenshi internals

The plugin reads the game objects of Kenshi through KenshiLib. This page records how those objects behave in the game. The probe lines of in-game tests showed each fact ([development.md](development.md#probes)).

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

- No other loaded character had the `serial` of the target NPC, in seven chats with about 100 loaded characters. A `serial` is 32 bits and looks random, so a clash in a long campaign is possible but unlikely.
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
- `AI/AIPackage.h` and `AI/Blackboard.h` of KenshiLib define the same enum, so one source file cannot include both (error C2011). The plugin reads the package by name through `Blackboard::getCurrentAIPackageName`.
