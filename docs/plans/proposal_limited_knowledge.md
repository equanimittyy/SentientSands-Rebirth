# Proposal: Limited Knowledge

Status: Draft for review

## 1. Summary

Today each NPC gets the same lore entries for the same line. Any NPC can therefore speak of any entry, even of a secret of the history, such as Kenshi is a Moon ([architecture.md](../info/architecture.md#lore-retrieval)).

This plan gives each lore record a knowledge tier. The search of a chat line finds only the records that the NPC can know:

| Tier | The NPC finds the record when |
|---|---|
| Global | Always |
| Limited | The NPC links to the record through the seeded data ([section 5](#5-limited-access)) |
| Secret | The `known_by` list of the record names the NPC, its faction, or its race ([section 7](#7-secret-access)) |

The plan also adds the canon characters to the lore records, with the Backstory as the text ([section 4](#4-character-records)). A character is Limited unless its author sets another tier. An NPC therefore finds the past of a character only through a faction: a faction that the two share, a faction of the NPC that names the character, for example as its leader, or a faction that holds the place of the NPC. An NPC in the Hub therefore knows the Dust King, because the Dust King leads the Dust Bandits, whose `territory` is the Border Zone.

A new `neighbours` fact names the regions next to each region. An NPC counts the regions next to its own as a part of its place, so it knows what it would know in each of them, and they join the place order of the lore ([section 6](#6-adjacent-regions)).

The plan reverses three decisions of architecture.md:

- "No filter by what the NPC knows" ([Lore retrieval](../info/architecture.md#lore-retrieval)).
- "No character records" ([Lore retrieval](../info/architecture.md#lore-retrieval)). A Backstory still mixes what the wasteland knows with a private past, so a character defaults to Limited.
- "An entry holds no access rules, because what an NPC knows belongs to the character, not to the entry" ([World templates](../info/architecture.md#world-templates)). The links of the NPC still decide Limited access. Only a Secret entry lists the characters, factions, and races that know it ([section 11](#11-rejected-alternatives)).

Non-goals:

- What the model knows from its training. An NPC without an entry can still talk of Tinfist from that knowledge, as it can today of any name that the lore does not hold.
- Knowledge that an NPC gains in play, for example from a chat or a rumor. The memories already give an NPC what it lived through. Access reads only the seeded data and the current place of the NPC.
- The overview. It goes into every prompt, so it stays Global.
- Generic NPCs as records. A rolled backstory is invented, and only its Faction links it to the seeded data.
- Radiant conversations and animals. They get no search ([architecture.md](../info/architecture.md#block)). A radiant conversation about a town reads the entry of the town where its participants stand.

## 2. Tiers

Each record has one tier. A record without a tier takes the default of its kind:

| Kind | Default |
|---|---|
| Race, location, region, faction, history entry | Global |
| Character | Limited |

- The lore keeps its current reach until an author marks it. A template without tiers therefore works as today, except for the new character records.
- An author can set a character that the whole wasteland knows, such as Tinfist, to Global.
- A Secret record reaches only the NPCs that its `known_by` list names. A link never opens it. A Secret record with an empty `known_by` reaches no NPC.
- The tier decides only whether an NPC finds the record. A found record goes into the block of the turn as now, and the closing note of the block stays ([architecture.md](../info/architecture.md#block)).

### SSR Vanilla

Each tier of SSR Vanilla that differs from the default has a source in the dialogue of the game or in the wiki, as each fact of the template does ([architecture.md](../info/architecture.md#ssr-vanilla)). The other records keep the default of their kind.

SSR Vanilla sets each faction that is not `major` to Limited, and keeps its 14 major factions Global. A member of the United Cities in Heft therefore does not know Narko's Disciples, while a member of the Holy Nation knows them anywhere, because the `enemies` of Narko's Disciples name the Holy Nation. A new faction takes the default of its kind, Global.

These records are Secret:

| Record | `known_by` | Source |
|---|---|---|
| Obedience (history) | Skeleton | At Obedience, only a Skeleton in the squad recalls why the Behemoths walked into the quarry, and the other races say "What the...". |
| The Chaos Age (history) | Skeleton | Quin of the Skeleton junkyard breaks off in front of a human or a Hiver: "back in the cha- uh... back some time ago". |
| Kenshi is a Moon (history) | None | No line of the game says it. NPCs call the world "this planet", and "the moons" are the moons in its sky. |
| Elder (character) | None | His Backstory says that he does not care that the Stobe story is false. He admits the sham only to a Skeleton, while his followers fight "in memory of Great Stobe". |

These history entries are Limited:

| Entry | Source |
|---|---|
| The War of Behemoths | The lines of the Skeleton at Obedience. Of the records that can be own records, its text links only the race Skeleton and the faction Skeletons, so Limited reaches the Skeletons only. |
| Stobe | The Skeleton Bandits and the Elder. |
| The Second Empire | The Skeletons of Black Desert City, Quin, and the Armour King. Bar patrons know only the legend of "Old King Cat-Lon". |
| The Hydraulic Knights | The cannibals greet Jang with "The Inedible One returns!". |
| The Shek Extinction Crisis | Shek warriors: "it weakens our numbers. The queen knows this". |
| The Fleshless Doctrine | The Skin Bandits. The record of their faction, which is Limited, holds the same belief. |

These canon characters are Global, because speakers far from their factions name them, mostly the bar patrons of the Swamp, World's End, and the United Cities, who talk of their fates: Tinfist, Holy Lord Phoenix, Emperor Tengu, Esata the Stone Golem, Bugmaster, Eyegore, Longen, High Inquisitor Seta, Boss Simion, and Luquin.

- Mad Cat-Lon stays Limited. The bar patrons know his legend, but the Skeletons of Black Desert City do not know where he went ("While Cat-Lon disappears into thin air..."), and his Backstory names his throne.
- Lady Kana and Lord Inaba stay Limited. Only the bars of the United Cities name them, and Limited already gives them to the members of their factions and to the NPCs in the places that those factions hold.

## 3. Records

### Template format

Each faction, character, race, location, region, and history entry can hold two new keys:

| Key | Value |
|---|---|
| `knowledge` | `global`, `limited`, or `secret`. A missing key takes the default of the kind. |
| `known_by` | A list of names of characters, factions, and races of the template |

A character holds the keys beside its `profile`, not in it. The validator takes only text and numbers as profile values, and the chat prompt reads the profile:

```json
{
  "game_id": "59030-Dialogue.mod",
  "knowledge": "global",
  "profile": {
    "Name": "Tinfist",
    ...
  }
}
```

- A name of `known_by` matches a character by its `Name`, a faction by its name or an alias, and a race by its name, as a field value matches a record ([Links](#links)). A name can match more than one record, and then names each of them. "Skeleton" therefore names both the race Skeleton and the faction Skeletons. In SSR Vanilla this changes nothing, because the game gives the Skeletons faction only Skeletons and P4 Units, a Skeleton race with no record of its own.
- The validator rejects an unknown tier. It warns about a `known_by` on a record that is not Secret, and about a name of `known_by` that names no character, faction, or race of the template, as it warns about a child that names no record ([architecture.md](../info/architecture.md#world-templates)).
- An import accepts the two keys. `format_version` stays 1, because a file without the keys reads as the defaults.

### Campaign storage

| Record | Where the keys go |
|---|---|
| Race, location, region | The JSON of the `entity` row, which holds the whole template record |
| History entry | The history JSON in `meta` |
| Faction | New columns `knowledge` and `known_by` of the `faction` table |
| Character | New columns `knowledge` and `known_by` of the `character` table |

- `SCHEMA_VERSION` goes from 12 to 13 (`server/store/campaign_db.py:18`). `open_campaign` refuses a campaign of an earlier schema, as for each schema change.
- An empty `knowledge` column means the default of the kind, as a missing key does.

## 4. Character records

Each canon character becomes a lore record: each character whose `origin` is `seed` or `campaign`. A character that the server added in play (`game`) stays out.

| Part | Value |
|---|---|
| Key | `("characters", npc_id)` |
| Kind | `character` |
| Name | `Name`, with no aliases |
| Fields | `race` and `faction`, from `Race` and `Faction` of the profile. A value of `Unknown` is left out. |
| Text | `Backstory` |

- The block shows a character as it shows the other records (`describe_record` with the kind first), and `clipped` cuts the text at 700 characters: `Tinfist (character; race: Skeleton; faction: Anti-Slavers): Leader of the Anti-Slavers. ...`.
- The Personality and the Speech stay out. They describe the character for an LLM that speaks as that character, as the scene of the squad member who speaks leaves them out ([architecture.md](../info/architecture.md#characters)).
- The search skips the record of the NPC itself, because `describe_npc` already puts its Backstory in the system message (`in_system_message` in `server/chat/background.py`).
- The records of SSR Vanilla grow from 363 to 574, with its 211 canon characters. Each canon character of SSR Vanilla has a Backstory.

A character name matches as any other name: lowercase, and as whole words. About 25 of the one-word names of SSR Vanilla are English words, such as Knife, Red, Fish, and Ghost, so "I need a knife" names Knife. A name match passes the cooldown. The Limited default limits the cost to the NPCs that link to the character, and the closing note of the block tells the NPC that an entry can be unrelated to the line.

## 5. Limited access

### Links

A link joins two records when one names the other:

- A field value links to each record whose name or alias has the same words, except a value of the `neighbours` fact ([section 6](#6-adjacent-regions)), as the name matching of the lore search compares them (`retrieval.name_words`): case ignored, a leading "the" dropped, and a final "s" dropped from each word of 4 or more letters. In SSR Vanilla, this links 4 field values that an exact match misses, such as "Great Desert" in the `territory` of the United Cities, which names the region The Great Desert.
- A child of a region links to the record that it names.
- The `Faction` and the `OriginFaction` of a character link to their factions.
- The text of a history entry links to each record that it names, by the name matching of the lore search (`retrieval.name_matches`). A history entry has no fields, so without its text no link could reach a Limited history entry.

A link works in both directions. A member of the Anti-Slavers therefore knows Tinfist through the `leader` field of the faction, and Bo through the `Faction` of Bo.

- The `Race` of a character is no link. Otherwise every canon Greenlander would know the past of every other canon Greenlander.
- A field value that names no record links nothing. In SSR Vanilla, 8 names in the `leader`, `founder`, and `nobles` fields name no character. Some name a figure with no record, such as Cat-Lon, and some join two names in one value, such as `Dimak and Buzan`.
- In SSR Vanilla, the texts of the 17 history entries hold 64 links to 38 records, with the links between history entries. Two of these links are wrong: "Cat-Lon" names the character Cat, and "the Old Empire" in The First Empire names the United Cities through its alias The Empire. A character is an own record only of itself ([Own records](#own-records)), so a wrong link to a character gives the history entry only to that character. The First Empire is Global, so its wrong link changes nothing.
- A longer name wins, so "the First Empire" names the history entry and not the United Cities. The texts of The Second Empire and The Hydraulic Knights therefore say "the Second Empire", not "an empire" or "the empire". The texts also avoid "brink" and "pit", which name the location Brink and the region The Pits.

### Own records

The own records of an NPC are the start of its links:

| Own record | Source |
|---|---|
| The current faction | The `factionID` of the NPC's context (`find_faction`) |
| The origin faction | The `OriginFaction` of the profile |
| The race | The `Race` of the profile |
| The current location | The `town_name` of the context, as for the place order ([architecture.md](../info/architecture.md#order-of-the-lore)) |
| The current region | The `zone_name`, or the `zone` of the current location, as for the place order |
| The neighbouring regions | The regions next to the current region ([section 6](#6-adjacent-regions)) |
| The character record | The record of the NPC itself, for a canon character |
| The holding factions | Each faction whose `territory`, `bases`, or `capital` names the current location, the current region, or a neighbouring region, and each `owner` of the current location |

An NPC knows a Limited record when the record is one of its own records, or has a link to one of them. Links go one hop from the own records. In SSR Vanilla, one hop from a faction reaches a median of 1 and at most 28 of the 211 canon characters.

The holding factions and the neighbouring regions come from the place of the NPC. From the place, the records of a holding faction are a second hop: the Border Zone, the Dust Bandits, then the Dust King. The step to a neighbouring region costs no hop, so the same path runs from each neighbouring region: the Stenn Desert, the Border Zone next to it, the Dust Bandits, then the Dust King. No other path takes a second hop. A member of the Holy Nation therefore does not reach Tinfist through the `enemies` field of its faction.

- A character links only to factions, so an NPC knows a Limited character through its current faction, its origin faction, or a holding faction, never through its race.
- The holding factions take a place to its characters. The Hub and the Border Zone alone have 6 holding factions in SSR Vanilla, such as the Holy Nation Outlaws, the `owner` of the Hub, and the Dust Bandits, whose `territory` is the Border Zone. Through them, an NPC in the Hub knows 10 canon characters, the Dust King among them.
- The neighbouring regions add their holding factions. In a prototype with the neighbours of the wiki as a stand-in, an NPC in the Hub has 24 holding factions, such as the gangs of the Swamp, the Shek Kingdom, and the Holy Nation, and knows 43 canon characters through them. From its region and the neighbouring regions, an NPC knows a median of 17 and at most 42 canon characters through the holding factions, against a median of 1 and at most 19 from its region alone.
- The links do not depend on the tier of a record. A Secret record still links the records around it, but the NPC does not find the Secret record itself unless its `known_by` reaches the NPC ([section 7](#7-secret-access)).
- The current location and the current region come from the context of each chat line, as for the place order. A squad member that walks into Admag therefore knows a Limited Admag while it stands there.

## 6. Adjacent regions

A region gets a new fact, `neighbours`: the regions that share a border with it.

- The regions next to the current region are own records of the NPC ([Own records](#own-records)), so the step to a neighbouring region costs no hop. The NPC knows what each neighbouring region links to, such as its towns, and the characters of the factions that hold it, as for its current region.
- Only one step counts. The `neighbours` fact is no link, so a region two regions away is not an own record, and the NPC knows it only through another link. With the neighbours of the wiki, an NPC has a median of 5 and at most 11 regions in its place. A second step would give a median of 13 and at most 28 of the 66 regions in those lists.
- A region is next to the current region when either of the two names the other in `neighbours`, so a pair needs to be listed on one region only.
- The validator warns about a neighbour that names no region of the template, as it warns about a child.
- The fact stays out of the fields column of the search. In a prototype with the neighbours of the wiki, "Is the Border Zone dangerous?" asked in Vain found Vain second. The `neighbours` of Vain hold the Border Zone, and the place order puts the current region first.

### Place order

The neighbouring regions join the place order of the lore ([architecture.md](../info/architecture.md#order-of-the-lore)), after the locations of the current region (`place_order` in `server/chat/retrieval.py`):

1. The current location
2. The current region
3. The locations of the current region
4. The neighbouring regions of the current region
5. The other hits

Today "Any bonedogs around?", asked outside a region with bonedogs, gives the same three regions in every place: High Bonefields, Spine Canyon, and The Eye. In the prototype, asked in the Deadlands, it gave Skinner's Roam first, a neighbour with bonedogs. As now, the order adds no entry.

### Source

The game data holds no list of neighbours. Each zone record (type 95) has an `index` that is an RGB colour, for example `0xFF0000` for the Border Zone. The colours suggest a zone map in the game files, an image that paints each part of the world with the colour of its zone.

| Probe question | Needed for |
|---|---|
| Which file of the game is the zone map, and do its colours match the `index` of each zone? | The neighbours of SSR Vanilla |
| Two pairs of zones share a colour: Akakus and Skimsands (`0x006432`), and Rim Sands and Shem (`0x7D6450`). SSR Vanilla has no record of Akakus or Rim Sands. Does the map paint these colours only where Skimsands and Shem are? | The neighbours of Skimsands and Shem |

A one-off script then lists each pair of zones whose colours touch on the map, and writes the `neighbours` of the regions of SSR Vanilla, on both regions of each pair, so the editor shows each pair on both regions. Without a zone map in the game files, the neighbours are read by hand from a map of the zones.

## 7. Secret access

An NPC knows a Secret record when its `known_by` names one of these:

- The NPC itself, for a canon character
- Its current faction
- Its origin faction
- Its race, the `Race` of its profile

A holding faction does not count. An NPC in the Hub is not a member of the Dust Bandits.

A race counts because the game gates its own dialogue by race more often than by faction or by character: in the game data, the conditions `my race`, `my faction`, and `is character` gate 350, 258, and 206 dialogue lines. At Obedience, for example, only a Skeleton in the squad recalls why the Behemoths walked into the quarry, and the other races say "What the...". A Limited record about a place cannot reach only the Skeletons, because its links also give it to the NPCs in and next to that place.

The server matches each name of `known_by` to the canon characters, the factions, and the races of the campaign, and then compares the `npc_id`, the faction ID, and the race record, not the name. A generic NPC can carry the name of a canon character, because the game gives most generic NPCs a name of its own ([architecture.md](../info/architecture.md#names)).

## 8. Search

`server/chat/knowledge.py` holds the rules of [section 5](#5-limited-access) and [section 7](#7-secret-access), with the neighbouring regions ([section 6](#6-adjacent-regions)). It takes the lore records with their tiers and the own records of the NPC as plain values, uses the standard library only, and returns the keys of the records that the NPC can know. Its tests therefore run without a campaign, like the tests of `retrieval.py`.

- `background.campaign_lore` also reads the canon characters (`server/chat/background.py:10`).
- `background.search` drops the records that the NPC cannot know before `find_lore` builds its index. The vocabulary, the common share, and the score cut therefore count only the records that the NPC can know.
- A lore search alone, with no NPC, searches every record, so a template author can test each record.
- The memory search takes the lore names of the lore hits as now, so a lore name that the NPC cannot know finds no memory through its name.
- `in_system_message` also returns the key of the NPC's own character record.
- The server builds the records, the links, and the index for each chat line, as now, so an edit on Campaign Canon reaches the next line.
- `place_order` reads the `neighbours` of the current region from the records ([Place order](#place-order)), and `find_lore` leaves the fact out of the fields column.
- The block shows `neighbours` as any other fact of an entry, so an NPC can tell which regions lie next to a region that the line finds.
- The slots, the cooldown, and the block stay as they are. A character record takes a lore slot.

## 9. Editor and test search

Campaign Canon and Templates get a **Knowledge** fieldset after the facts of each faction, character, race, location, and region form. The History form has no form for each entry, so each history card gets the two fields, with the select beside the title.

- **Knowledge Level**: a select of Global, Limited, and Secret, with the default of the kind marked "(default)". The default saves no `knowledge` key, so a template does not fill with keys that change nothing, and a record that the player did not touch stays unchanged.
- **Known by**: hidden unless Knowledge Level is Secret. It holds one row for each name, with a search box, and an **Add knower** button, as the Relations editor does (`relationsEditor` in `server/dashboard/web/editor.js`), because a list of names separated by commas cannot offer suggestions. The suggestions are the characters, the factions, and the races of the campaign or the template, each with its kind, such as "Skeleton (race)", and a row saves the plain name. A name that names nothing gets a warning on its row and still saves, because the validator only warns about it.
- A record that is not Secret saves no `known_by`, so no list stays behind the hidden field.
- Campaign Canon shows the fieldset only for a canon character, because no other character becomes a record.

The help texts tell the player who can know the entry:

- **Knowledge Level**: "Who can know this entry. Global: every NPC. Limited: only the NPCs tied to it through a faction, a race, or a place that it names or that names it. Secret: only the characters, factions, and races in Known by."
- **Known by**: "The characters, factions, and races that know this entry. A member of a faction knows it, and so does a character that comes from the faction. Type to search, then choose from the list."

A region form gets `neighbours` as a list fact, as the other list facts. Its help text says that it holds the regions that share a border with this region on the world map of the game.

The test search ([architecture.md](../info/architecture.md#test-search)) changes:

- Each hit shows its tier.
- With a character to talk to, the box filters as a chat does. The links take the place of the character from its `CurrentLocation` (`background.place_of`), as the place order does.
- With a character to talk to, the box also lists each name match that the filter dropped, with its tier, so a template author sees why a name finds nothing.

## 10. Build order

1. The keys, the validator, the import, the campaign schema, and the editor fields.
2. `knowledge.py` with the holding factions, the filter in `background.search`, and the test search.
3. The character records.
4. The adjacent regions: the probe, the `neighbours` fact, the place order, and the neighbours of SSR Vanilla.
5. The tiers of SSR Vanilla ([SSR Vanilla](#ssr-vanilla)).

Each step updates architecture.md in the same change.

## 11. Rejected alternatives

| Alternative | Reason |
|---|---|
| The whitelist of a secret on the character | It reaches only canon characters, so no generic NPC could know a secret, and the knowers of one secret would spread over many files. |
| A second hop through every link | A member of the Holy Nation would know the past of Tinfist, Bo, Grey, and Jaegar through the `enemies` field of its faction. Two hops take a member of the United Cities from 15 to 67 of the 211 canon characters of SSR Vanilla. |
| Direct links only | A member of the Anti-Slavers would not know Tinfist, its leader. |
| Links through the text of every record | The other records link through their fields. A match in a text finds wrong names, such as the character Cat in "Cat-Lon". |
| The race of a character as a link | Every canon Greenlander would know the past of every other canon Greenlander. |
| The `factions` of a region as holding factions | They list each faction that roams a region, also a faction that only passes through. From its region and the neighbouring regions, an NPC would know a median of 47 and at most 107 canon characters, against 17 and 42 through the holding factions, with the neighbours of the wiki. |
| A second step of neighbours | A second step would give an NPC a median of 13 and at most 28 regions in its place, against 5 and 11, with the neighbours of the wiki. |
| The `neighboring_zones` of the wiki as the source of the neighbours | The lists disagree: at least 40 pairs appear on one side only, such as the Border Zone, which lists Spider Plains, while Spider Plains does not list the Border Zone. |
| The characters that the NPC spoke with as links | The memories already give an NPC what it lived through, and access then depends on play data, not on the seeded data. |
| A filter after the search | A record that the NPC cannot know could set the best score and cut the hits that it can know below `SCORE_RATIO`, and its words would count towards `COMMON_SHARE`. |
| Every character with a profile as a record | A rolled backstory is invented, and only its Faction links it. |
| Limited as the default of all lore | The common history and the races would reach only linked NPCs until an author marks them Global. |
| Character records with the Personality and the Speech | They describe how the character acts and talks, for the LLM that speaks as it. |
| Two tiers, Global and Limited, without Secret | SSR Vanilla has only 4 Secret records, but only Secret can hide a record. Without it, the Skeleton Bandits would read in the Elder's Backstory that his Stobe story is false, and a player could not keep a plot secret of Campaign Canon from the other NPCs. A `known_by` that adds knowers to a Limited record cannot hide one either. |

## 12. Verification

Unit tests, which run without Flask and requests (`server/tests/`):

1. `test_knowledge.py`: the default of each kind; an empty `knowledge` column as the default; each own record; a link in each direction; a link through a field, a child, a `Faction`, an `OriginFaction`, and the text of a history entry; no link through the text of another record; no link through the `Race` of a character; no second hop; a field value that names no record; a field value that differs from a name only in case, a leading "the", or a final "s"; a holding faction through `territory`, `bases`, `capital`, and `owner`; a character of a holding faction; no holding faction through the `factions` of a region; a neighbouring region that either region names; a town and a holding faction of a neighbouring region; no region two steps away; no link through `neighbours`; Secret by the NPC, by its current faction, by its origin faction, and by its race; a name of `known_by` that names both a race and a faction; no Secret through a link or a holding faction; a generic NPC with the name of a character in `known_by`; an empty `known_by`.
2. `test_retrieval.py`: the neighbouring regions in the place order, after the locations of the current region; no content hit through `neighbours`.
3. `test_background.py`: a record that the NPC cannot know and that has the best score does not cut a hit that it can know; the NPC's own character record is skipped; a character that the server added in play is no record; a field of `Unknown` is left out; a lore search alone searches every record.
4. `test_world_template.py`: an unknown tier; a `known_by` on a record that is not Secret; a name of `known_by` that names a race; a name of `known_by` that names nothing; a neighbour that names no region; an import with the two keys; the keys of a character beside its `profile`.
5. `test_campaign_db.py`: the two columns of a faction and of a character keep their values through a save and a read.

On a new SSR Vanilla campaign, after step 3 of the build order, these lines give these first entries. A prototype of the rules gave the same entries:

| NPC | Line | First entries |
|---|---|---|
| A member of the Anti-Slavers in Spring | Where is Tinfist? | Tinfist (character) |
| A member of the Holy Nation in Blister Hill | Where is Tinfist? | Anti-Slavers, by its `leader` field, and no Tinfist |
| A member of the Traders Guild in the Hub | Ever met Longen? | Longen (character) |
| A Drifter in the Hub | Ever met Longen? | Traders Guild, by its `leader` field, and no Longen |
| A member of the Holy Nation Outlaws in the Hub | Ever heard of the Dust King? | Dust King (character) |
| A member of the Shek Kingdom in Squin | Ever heard of the Dust King? | Dust King (character) |
| A member of the Shek Kingdom in Admag | Ever heard of the Dust King? | Dust King Tower and Dust Bandits, and no Dust King |

After step 4:

1. The probe answers its questions, and the neighbours that the script writes for the Border Zone agree with the map of the zones.
2. "Any bonedogs around?", asked in a region without bonedogs, gives a neighbouring region with bonedogs before the other regions.

After step 5, with the tiers of SSR Vanilla, these lines give these first entries. The prototype gave the same entries, with the neighbours of the wiki as a stand-in:

| NPC | Line | First entries |
|---|---|---|
| A member of the United Cities in Heft | Ever heard of Narko's Disciples? | The Order of Chitrin, whose text names Narko's Disciples, and no Narko's Disciples |
| A member of the Holy Nation in Blister Hill | Ever heard of Narko's Disciples? | Narko's Disciples |
| A member of the Shek Kingdom in Admag | Ever heard of the Dust King? | Dust King (character), through the Border Zone next to the Stenn Desert |
| A member of the United Cities in Heft | Ever heard of the Dust King? | Dust King Tower, and no Dust King |
| A member of the Holy Nation Outlaws in the Hub | Ever heard of the Dust King? | Dust King (character), Dust King Tower, Dust Bandits |
| A Drifter in the Hub | Ever met Longen? | Longen (character) |
| A Skeleton of the Anti-Slavers in Spring | What happened at Obedience? | Obedience (region), Obedience (history) |
| A Greenlander of the Drifters in the Floodlands | What happened at Obedience? | Obedience (region), and no Obedience history entry |
| A member of the Skeletons in Black Desert City | Tell me about the Chaos Age. | The Chaos Age |
| A member of the United Cities in Heft | Tell me about the Chaos Age. | No entry |
| A member of the United Cities in Heft | Is Kenshi a moon? | No entry |
| A member of the Skeleton Bandits in Stobe's Gamble | Who is the Elder? | Skeleton Bandits, by its `leader` field, and no Elder |

On a test campaign:

1. Set Admag to Limited. A Drifter in Squin finds it through the Shek Kingdom, the `owner` of Squin, and a member of the Holy Nation in Blister Hill does not.
2. Set a region to Limited. An NPC in a neighbouring region finds it, and an NPC two regions away does not.
3. Put a faction in the `known_by` of Kenshi is a Moon. "Is it true that Kenshi is a moon?" gives the entry to a member of that faction, and no entry to any other NPC.
4. Set Kral and the Shek Wars to Limited. "Tell me about the war with the Shek." gives it to a member of the Shek Kingdom, through the Shek in its text, and not to a Greenlander of the Traders Guild in Heft. The prototype gave the same result, with the neighbours of the wiki as a stand-in.
5. On Templates, Known by shows only while Knowledge Level is Secret. Set a Secret record to Limited and save: the record keeps no `known_by`.
6. The test search of Campaign Canon, with a member of the United Cities in Heft to talk to, lists the Dust King as a name match that the filter dropped, with the tier Limited.
7. Measure the time of a search of SSR Vanilla with the character records. In the prototype, `find_lore` took 17 ms for the 574 records and 10 ms for the 363 lore records in the dev container.

The full server test suite passes.
