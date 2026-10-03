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

## Factions

`FactionManager::getAllFactions` lists each faction of the game, and `faction->data->stringID` gives its string ID. The `game_id` of each faction file of SSR Vanilla comes from the `FACTION_PROBE` lines of one mod list.

## Zones

- `ZoneManager::getBiome` gives only the ground type, such as Canyonland FlatTop, so it cannot name the zone.
- The zone object (`AreaBiomeGroup`) holds the zone record, for example Stenn Desert, at slot `0x10`. `WeatherSystem::ActiveRegion` and `TownBase::getBiome` both give a zone object.
- Slot `0x120` also holds a zone record, but not the zone that the map shows.

## Squads

`PlayerInterface::getCurrentPlatoon` gives the squad that the player selected. A squad member is in that squad when its `Character::getPlatoon` is the `getActivePlatoon` of that squad.
