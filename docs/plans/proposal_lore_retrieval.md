# Proposal: Lore Retrieval

Status: Draft for review

## 1. Summary

The chat prompt gets the lore entries that the player's message is about: races, locations, regions, factions, and history entries. Today no prompt reads the history, the locations, or the regions. The retrieval works only from the words of the player's message.

Retrieval has two steps:

1. Name matching ([section 3](#3-name-matching)) finds the entries that the message names, such as "Admag" or "the Shek Kingdom".
2. Content search ([section 4](#4-content-search)) finds the entries whose text holds the lore words of the message, such as "mercenary" or "Phoenix".

Two limits keep a wrong hit cheap and the context small. At most 3 entries go into a turn, and they go only into the last user message, so they never pile up in the history ([section 6](#6-prompt)).

Non-goals:

- Vector search or embeddings.
- A filter by what the speaking NPC knows. That needs a knowledge bank for each character, which does not exist, so each NPC gets the same entries for the same message. Any NPC can therefore speak of any entry, even of a secret of the history such as Kenshi is a Moon. This is a known trade-off, which a later NPC knowledge system is to fix.
- The entries that a hit links to, such as the region of a town. The limit of 3 entries leaves no room for them.

## 2. Records

| Record | Name | Fields | Text | Source |
|---|---|---|---|---|
| Race, location, region | `name`, `aliases` | the values of `fields` | `description` | `campaign_db.list_records("entity")` |
| Faction | `name`, `aliases` | the values of `fields` | `description` | `campaign_db.list_factions()` |
| History entry | `title` | none | `text` | `campaign_db.history()` |

- A record with an empty text is skipped, as for a faction that the game reported (`note_faction`).
- The server reads the records for each chat message and builds the index of [section 4](#4-content-search) in memory. On SSR Vanilla, the build of 363 records took 3.7 ms in a prototype. An edit on Campaign Canon therefore reaches the next message, and the schema of the campaign database does not change.
- A history entry has no aliases, so only its whole title matches as a name.
- Only 3 of the 240 races, locations, and regions of SSR Vanilla have aliases. A name with no entry and no alias is found only by content search.
- SSR Vanilla is in English. A message in another language finds names, but it holds few lore words for content search.

## 3. Name matching

`server/scripts/lore_retrieval.py` holds both steps. It uses the standard library only and has its own unit tests, like `chat_prompt.py`. It takes the message and the records as plain values, so it never touches the campaign.

1. The message and each name become words: lowercase, split at each character that is not a letter or a digit. A word of 4 or more letters loses a final "s", on both sides, so "skeletons" finds Skeleton. The split at an apostrophe lets "Admag's" find Admag.
2. A name loses a leading "the", so "Hub" finds The Hub.
3. A name matches when its words appear in the message in the same order, with no word between them.
4. A match that lies inside a longer match is dropped, so "Shek Kingdom" finds the faction and not also the race Shek. Records with the same name all match: "Bast" finds the location and the region.

## 4. Content search

An SQLite FTS5 table holds one row for each record, with the columns name, aliases, fields, and text, and the `porter unicode61` tokenizer. The embedded Windows runtime ships SQLite 3.49.1, which has FTS5 ([development.md](../info/development.md#probes) has the check for a later runtime).

1. The vocabulary is each word of the names, the aliases, and the field values of the records, stemmed by the tokenizer of the index. SSR Vanilla has 538 such words.
2. A word of the message searches only when it is in the vocabulary, is not an English stop word, and appears in no more than a tenth of the records.
3. The search is an OR of these words, ranked by BM25 with the weights 10 for the name, 10 for the aliases, 3 for the fields, and 1 for the text.
4. A hit whose score is below 60% of the best score of the search is dropped.

The weights, the ratio, and the tenth are starting values, which the fixed list of [section 8](#8-verification) and the test search of [section 7](#7-test-search) tune.

The vocabulary keeps chat words out of the search. Chat words are rare in the lore, so BM25 ranks them high, and lore words are common. In a prototype with every word of the message, "How are you doing today?" found Fish Isle, The Shek Extinction Crisis, and Hive Village, and "I need a doctor." found Twinblades. "doing", "need", and "doctor" each appear in 1 to 5 records, but "shek" appears in 32 and "holy" in 68.

The limit of a tenth keeps a common word of names from pulling arbitrary records: "Who rules this town?" would find three towns that have "Town" in their names. A name such as The Holy Nation, whose words are in more records, still matches by name.

Rejected:

- A search with every word of the message. The examples above show the result.
- A search without the words that appear in many records, and without the vocabulary. It keeps "doing" and "need" and drops "shek" and "iron", which is the opposite of what the search needs.
- A content search without the name and alias columns, so that only name matching finds a record by its name. In the prototype, "Any work for a mercenary?" lost Mercenary Guild and "Any bounties around here?" lost Bounty Hunters, while "my teeth hurt" still found Bad Teeth through its own text, and through Okran's Pride when the index also left each record's own name out of its text.

## 5. Order and limit

- The name matches come first, in the order of their first word in the message. The content hits follow, in the order of their score.
- A record that both steps find counts once.
- A record is skipped when the system message already holds it: the NPC's current faction and origin faction, the player's race, and the player's faction.
- The first 3 records go into the prompt. The limit is a constant in the code.
- The text of an entry ends at the last sentence end before 700 characters, or at 700 characters when no sentence ends before. The longest text of SSR Vanilla has 614 characters, but a user template has no limit. A turn therefore gets at most about 500 tokens of lore.

## 6. Prompt

- The entries go into the last user message (`prompt_chat_turn.txt`), before the player's line. They change on each turn, and the cache can serve only an identical start of a request, so they stay out of the system message and the history ([architecture.md](../info/architecture.md#prompts)).
- The stored dialogue holds only the lines, so the entries of a turn are gone from the next request. The lore of a conversation therefore costs the same on each turn and does not grow.
- When a message gives no entry, the turn repeats the entries of the message before it, so "Tell me more about it" keeps the lore of the topic. The entries carry for one message only, so small talk after a topic does not keep the lore in front of the NPC. The server keeps the entries of the last message in memory for the pair of the speaker and the NPC. A message from another pair, or a campaign switch, drops them.
- An animal gets no entries, because it replies only in actions. Banter gets no entries, because it has no message from the player.
- Each entry gives its name, its kind, and its text. The block around the entries stays in the code, as for the rumors, so an empty list leaves no block.
- The block is in parentheses and starts with "Background, not said aloud", as the final instruction of the turn is in parentheses. The block is part of the user message, so without this mark a model can take the lore for words of the player. Some chat templates accept a system message only at the start of a chat, so the block cannot be a system message of its own.
- The note at the end of the block tells the NPC that the lore can be unrelated to the line, that the NPC may know less than it says, and that a reply must not recite it or turn the talk towards it. A search finds words, not meaning, so some hits are wrong, and a model tends to use all the text that it gets. The note sits directly before the player's line, where the model reads it last.

Rejected:

- A cache that skips the entries that the conversation already sent. The entries of a turn are not in the next request, so a skipped entry would be missing: a second question about Admag would get no lore about Admag.
- Entries that stay in the history, so that the cache above could work. The context would grow with each new entry, and the stored dialogue, which the Dialogue Library and the bio prompt read, would hold lore.

Example: Izumi speaks to Jorge.

```
(Background, not said aloud. Lore that Izumi's words may touch on:
- Admag (location): Admag is the Shek Kingdom's capital, a hilltop town in the Stenn Desert with one entrance, home to most of the kingdom's Shek. Esata the Stone Golem rules here with Bayan and Seto, guarded by the Five Invincibles, while Hundred Guardians defend the town. It has two bars, armour and weapon shops, and a thieves' guild.
- Bad Teeth (location): Bad Teeth is a Holy Nation town in Okran's Pride that watches over a mountain pass leading from the fertile valley out to the wild Skinner's Roam. It has a temple, three bars, a bakery, barracks, and shops for weapons and armour, and its gate guards often kill river raptors that roam close.
This lore may have nothing to do with what Izumi means, and you may know less than it says. Use it only where it fits your reply, and never recite it or turn the talk towards it.)

[Day 12, 14:05] Izumi: I came from Admag through the Bad Teeth.

(Reply as Jorge. End with [JUDGMENT: n].)
```

## 7. Test search

A Test Lore Search panel on the Campaign Canon and Templates subtabs of the Editor shows what a line of the player finds. A template author sees why a line finds nothing, and the starting values of [section 4](#4-content-search) get tuned on real lines.

- The player types a line, and the panel lists the entries in their prompt order. Each entry shows its kind and how it was found: by its name, or by the words that found it.
- The panel also lists each word of the line that did not search, with the reason: a common English word, not a word of the lore, or a word in too many entries.
- Campaign Canon searches the active campaign, and Templates searches the open template. The search reads the saved records, so an unsaved edit counts only after Save.
- The panel has no NPC, so it skips no entry that the system message of a chat would hold, and it does not repeat the entries of the message before.
- The routes are `GET /api/campaign/lore?message=...` and `GET /api/templates/<name>/lore?message=...`. A search changes nothing, and a POST under `/api/` counts as a write, which makes every open page refresh (`count_write_requests` in `server/scripts/kenshi_llm_server.py`).

## 8. Verification

1. `server/tests/test_lore_retrieval.py` covers each rule of [section 3](#3-name-matching), [section 4](#4-content-search), and [section 5](#5-order-and-limit): case, punctuation, and the possessive; the final "s"; the leading "the"; the order of the words; a longer match over a shorter one; two records with one name; a word outside the vocabulary; a word in more than a tenth of the records; the score cut; a record that both steps find; an empty text; the records that the system message holds; the limit and the order; the cut of a long text; a history title.
2. On SSR Vanilla, these messages give no entry: "Where can I buy food?", "How are you doing today?", "I need a doctor.", "My feet are killing me", "Nice weather.", "Want to join my squad?", "Who rules this town?".
3. On SSR Vanilla, these messages give these first entries:

   | Message | First entries |
   |---|---|
   | I came from Admag through the Bad Teeth | Admag, Bad Teeth |
   | What do you think of the Shek Kingdom? | Shek Kingdom (faction) |
   | Is Bast safe? | Bast (location), Bast (region) |
   | I hate the Holy Nation. | The Holy Nation |
   | Tell me about the war with the Shek. | Shek (race), Kral and the Shek Wars |
   | Any work for a mercenary? | Mercenary Guild |
   | Where do the cannibals live? | Cannibals (faction) |
   | Where can I find ancient technology? | Ancient Technology |
   | Have you heard of the Phoenix? | The Holy Nation |
   | Where can I find Tinfist? | Anti-Slavers |
   | Ever met Longen? | Traders Guild |

4. In the server, a message that finds an entry gives a turn that holds it. The next message, which finds nothing, gives the same entries, and the message after that gives none. The system message of these turns is the same. An entry that Campaign Canon edits shows the edit in the next message, and a renamed entry matches by its new name.
5. On the test search of a new SSR Vanilla campaign, "Any work for a mercenary?" lists Mercenary Guild as found by "mercenary", "work" as not a word of the lore, and "any", "for", and "a" as common English words. The Templates subtab gives the same result for SSR Vanilla.
6. The full server test suite passes.

These messages still give wrong or arbitrary entries in the prototype, and the limit and the note of the block bound their cost: "my teeth hurt" finds Bad Teeth, "Where can I get a prosthetic arm?" finds Arm of Okran, and "Any bonedogs around?" finds 3 of the many regions with bonedogs.

## 9. Open questions

1. Should retrieval also find characters, such as Beep or Tinfist? Today "Tinfist" finds the Anti-Slavers, whose `leader` field names Tinfist, but not the profile of Tinfist.
2. Should a content hit in the NPC's current region or location rank first? "Any bonedogs around?" would then find the region that the NPC stands in.
