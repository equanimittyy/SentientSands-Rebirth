# Proposal: Lore and Memory Retrieval

Status: Draft for review

## 1. Summary

The chat prompt gets the lore entries and the memories of the NPC that the player's message is about. The lore entries are races, locations, regions, factions, and history entries. Today no prompt reads the history, the locations, or the regions. The retrieval works only from the words of the player's message.

Retrieval has two steps:

1. Name matching ([section 3](#3-name-matching)) finds the entries that the message names, such as "Admag" or "the Shek Kingdom".
2. Content search ([section 4](#4-content-search)) finds the entries whose text holds the lore words of the message, such as "mercenary" or "Phoenix".

The memories use the same two steps ([section 6](#6-memories)). The system message keeps the newest memories of the conversations in which the NPC was a speaker. The search finds the older memories and the memories of the conversations that the NPC overheard.

Two limits keep a wrong hit cheap and the context small. A turn has a number of slots that the player sets, 3 by default. The memories that the message finds take the first slots, newest first, up to a cap that the player sets, and lore entries fill the slots that are left ([section 6](#order-and-limit)). A hit that only content search finds does not come back for a number of turns that the player sets, 1 by default. The hits go only into the last user message, so they never pile up in the history ([section 7](#7-prompt)).

Non-goals:

- Vector search or embeddings.
- A filter by what the speaking NPC knows. That needs a knowledge bank for each character, which does not exist, so each NPC gets the same entries for the same message. Any NPC can therefore speak of any entry, even of a secret of the history such as Kenshi is a Moon. This is a known trade-off, which a later NPC knowledge system is to fix. The memories need no such filter, because an NPC finds only the memories of the conversations in which it was a member.
- The entries that a hit links to, such as the region of a town. The default of 3 slots leaves no room for them.

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

`server/chat/retrieval.py` holds both steps, for the lore and for the memories. It uses the standard library only and has its own unit tests, like `chat_prompt.py`. It takes the message and the records as plain values, so it never touches the campaign.

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

The weights, the ratio, and the tenth are starting values, which the fixed list of [section 9](#9-verification) and the test search of [section 8](#8-test-search) tune.

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
- The records fill the slots of the turn that the memories leave ([section 6](#order-and-limit)).
- The text of an entry ends at the last sentence end before 700 characters, or at 700 characters when no sentence ends before. The longest text of SSR Vanilla has 614 characters, but a user template has no limit.

## 6. Memories

### Starting memories

The system message gives the NPC the newest 5 memories of the chat threads in which it was a speaker, oldest first. Today it gives the newest 10, also of the threads that the NPC only overheard ([architecture.md](../info/architecture.md#conversation-memories)).

- The search finds the older memories, so the system message needs fewer of them, and each memory there costs its tokens on every turn.
- An NPC that stands near many chats, such as a barman, overhears more conversations than it has. Its overheard memories would push its own conversations out of the newest 5.
- An overheard memory reaches the prompt only when the player's message finds it.
- The system message changes only when the server writes a memory of a thread in which the NPC spoke, so the memory of a chat that the NPC overheard no longer costs a miss of the prompt cache.
- The Dialogue Library and the bio prompt still read every memory of the character, also the overheard ones.

Rejected: the newest memories of the threads in which the squad member who speaks was the other speaker. The scene names the other squad members that the NPC spoke with ("Earlier you spoke with Stick, who travels with Izumi."), so the NPC would know that it spoke with Stick but not what they said.

### Records

Each memory of a thread in which the NPC is a member, as a speaker or as an overhearer, is a record, except the memories that the system message holds.

- The text is the memory with the current names (`chat_prompt.named`), so a search finds a renamed character by its new name.
- The names are the current names of the members, except the NPC. The NPC is a member of each of its memories, so its own name would match all of them: "Jorge, did you hear about Admag?"
- A pending thread has no memory, and its lines are already in the history.
- The server reads the memories for each chat message and builds their index, as for the lore. Memories are not trimmed, so an NPC near many chats can have hundreds. A memory is about as long as a lore text, and the prototype built 363 lore records in 3.7 ms.

### Name matching

The rules of [section 3](#3-name-matching) apply.

1. A memory matches when the message names one of its members.
2. A memory also matches when its text holds a lore name that the message names, with the words in the same order. "Are the Dust Bandits around?" finds the memory in which Jorge named the Dust Bandits. The name counts even when [section 5](#5-order-and-limit) skips its entry, because the system message holds that entry but not the memory.

### Content search

An FTS5 table holds one row for each memory, with its text, and the tokenizer of [section 4](#4-content-search).

1. A word of the message searches when it is not an English stop word and not a word of the NPC's name.
2. A memory is a hit only when it holds at least 2 different words that search.
3. A hit whose BM25 score is below 60% of the best score of the search is dropped.

The memories have no vocabulary as in section 4. A memory tells a conversation, so the words that it is about, such as "debt" or "secret", are chat words, which a vocabulary of lore words drops. One shared chat word is weak evidence, because "today" or "need" can be in any memory. The limit of a tenth of section 4 does not help here: for an NPC with 5 memories, each word that a memory holds is in more than a tenth of them.

The 2 words and the ratio are starting values. No campaign holds enough memories for a prototype yet, so the test search of [section 8](#8-test-search) tunes them on a played campaign.

### Order and limit

- A hit that only content search finds is held back when it was a hit in one of the last N turns of the conversation, where N is the Retrieval cooldown of the Settings page (`retrieval_cooldown_turns`, default 1). A name match always passes. A held-back hit leaves its slot to the next hit.
- A content hit comes from shared words, not from the topic that the player asked about, so the same words in the next lines would bring it back on each turn, and a model tends to talk about the text that it gets. A name match passes because the player asked about it, and the hits of a turn are not in the next request ([section 7](#7-prompt)).
- The server keeps the hits of the last N turns for the pair of the speaker and the NPC. A message from another pair, or a campaign switch, drops them. A Retrieval cooldown of 0 turns the guard off.
- The memories that the two steps find come first, newest first, up to the Memory slots of the Settings page (`memory_slots`, default 3). A memory that both steps find counts once.
- The lore entries of [section 5](#5-order-and-limit) follow, in their own order, until the turn holds as many hits as the Retrieval slots of the Settings page (`retrieval_slots`, default 3). With the defaults, a message that finds 3 memories therefore gets no lore.
- A memory is what this NPC lived through, and every NPC gets the same lore entries for the same message, so a memory goes first. A newer memory goes before an older one, because it is closer to how things stand now.
- A slot costs up to about 175 tokens on each turn, so a player with a small local model can lower the Retrieval slots. A lower Memory slots value keeps slots for the lore when a message finds many memories.
- 0 Retrieval slots turns the search off, and 0 Memory slots gives every slot to the lore. Memory slots above Retrieval slots count as Retrieval slots, so the page does not check one value against the other.
- The server keeps the three values in the INI with the other settings and does not send them to the plugin, which does not use them.
- The text of a memory ends as in [section 5](#5-order-and-limit), because the player can edit a memory to any length.
- Each memory gets the header from the view of the NPC that the system message gives it, such as `[Day 3, 14:05] You overheard Stick and Jorge.` (`chat_prompt.memories_block`).

## 7. Prompt

- The entries and the memories go into the last user message (`prompt_chat_turn.txt`), before the player's line. They change on each turn, and the cache can serve only an identical start of a request, so they stay out of the system message and the history ([architecture.md](../info/architecture.md#prompts)).
- The stored dialogue holds only the lines, so the entries and the memories of a turn are gone from the next request. The lore and the memories of a conversation therefore cost the same on each turn and do not grow.
- An animal gets no search, because it replies only in actions. It keeps its starting memories. Banter gets no search, because it has no message from the player.
- Each memory gives its header and its text, and each entry gives its name, its kind, and its text. The memories come before the entries, in the order of [section 6](#order-and-limit). The block and the heading of each list stay in the code, as for the rumors, so an empty list leaves no heading, and two empty lists leave no block.
- The block is in parentheses and starts with "Background, not said aloud", as the final instruction of the turn is in parentheses. The block is part of the user message, so without this mark a model can take the lore or a memory for words of the player. Some chat templates accept a system message only at the start of a chat, so the block cannot be a system message of its own.
- The note at the end of the block tells the NPC that the lore and the memories can be unrelated to the line, that the NPC may know less than the lore says, and that a reply must not recite them or turn the talk towards them. The note names only the lists that the block holds. A search finds words, not meaning, so some hits are wrong, and a model tends to use all the text that it gets. The note sits directly before the player's line, where the model reads it last.

Rejected:

- A guard that also holds back a name match. The entries of a turn are not in the next request, so a held-back entry would be missing: a second question about Admag would get no lore about Admag.
- A carry of the hits of the message before to a message that finds nothing, such as "Tell me more about it". It would repeat the hits that the guard holds back. The NPC answers a vague follow-up from its own last reply.
- Entries that stay in the history, so that the guard could hold back every repeat. The context would grow with each new entry, and the stored dialogue, which the Dialogue Library and the bio prompt read, would hold lore.

Example: Izumi speaks to Jorge, whose memories are all in the system message.

```
(Background, not said aloud. Lore that Izumi's words may touch on:
- Admag (location): Admag is the Shek Kingdom's capital, a hilltop town in the Stenn Desert with one entrance, home to most of the kingdom's Shek. Esata the Stone Golem rules here with Bayan and Seto, guarded by the Five Invincibles, while Hundred Guardians defend the town. It has two bars, armour and weapon shops, and a thieves' guild.
- Bad Teeth (location): Bad Teeth is a Holy Nation town in Okran's Pride that watches over a mountain pass leading from the fertile valley out to the wild Skinner's Roam. It has a temple, three bars, a bakery, barracks, and shops for weapons and armour, and its gate guards often kill river raptors that roam close.
This lore may have nothing to do with what Izumi means, and you may know less than it says. Use it only where it fits your reply, and never recite it or turn the talk towards it.)

[Day 12, 14:05] Izumi: I came from Admag through the Bad Teeth.

(Reply as Jorge. End with [JUDGMENT: n].)
```

Example: Izumi speaks to Paladin Abel, who overheard Stick ask Jorge for work. The system message holds no memory of Paladin Abel, because Paladin Abel spoke in no thread. "trouble" and "night" find the memory.

```
(Background, not said aloud. Memories that Izumi's words may touch on:
[Day 3, 14:05] You overheard Stick and Jorge.
Stick asked Jorge for work. Jorge doubted that Stick could fight, but offered 200 cats to guard the door of the bar for the night and stop anyone who started trouble. Stick agreed. Jorge named the Dust Bandits as the usual trouble, because they drink and leave without paying.
These memories may have nothing to do with what Izumi means. Use them only where they fit your reply, and never recite them or turn the talk towards them.)

[Day 12, 14:05] Izumi: Who keeps the trouble out of here at night?

(Reply as Paladin Abel. End with [JUDGMENT: n].)
```

## 8. Test search

A Test Search panel on the Campaign Canon and Templates subtabs of the Editor shows what a line of the player finds. A template author sees why a line finds nothing, and the starting values of [section 4](#4-content-search) and [section 6](#content-search) get tuned on real lines.

- The player types a line, and the panel lists the entries in their prompt order, with the slots of the Settings page. Each entry shows its kind and how it was found: by its name, or by the words that found it.
- The panel also lists each word of the line that did not search the lore, with the reason: a common English word, not a word of the lore, or a word in too many entries.
- On Campaign Canon, the player can also pick a member of a chat thread with a memory, from the threads that `GET /api/campaign` already returns. The panel then lists the hits of a chat with that character in their prompt order: first the memories, each with how it was found, by a name or by the words that found it, then the entries in the slots that are left. It skips the memories that the system message of the character holds, as a chat does. A template has no memories.
- Campaign Canon searches the active campaign, and Templates searches the open template. The search reads the saved records, so an unsaved edit counts only after Save.
- The panel skips no entry that the system message of a chat would hold, and it has no earlier turns, so the guard holds back no hit.
- The routes are `GET /api/campaign/search?message=...&npc=...`, where `npc` is optional, and `GET /api/templates/<name>/search?message=...`. A search changes nothing, and a POST under `/api/` counts as a write, which makes every open page refresh (`count_write_requests` in `server/main.py`).

## 9. Verification

1. `server/tests/test_retrieval.py` covers each rule of [section 3](#3-name-matching), [section 4](#4-content-search), and [section 5](#5-order-and-limit): case, punctuation, and the possessive; the final "s"; the leading "the"; the order of the words; a longer match over a shorter one; two records with one name; a word outside the vocabulary; a word in more than a tenth of the records; the score cut; a record that both steps find; an empty text; the records that the system message holds; the limit and the order; the cut of a long text; a history title.
2. `server/tests/test_retrieval.py` covers each rule of [section 6](#6-memories): a member's name; the NPC's own name; a lore name in the text; a lore name whose entry the system message holds; a renamed member; one shared word against two; a word of the NPC's name; the score cut; a memory that both steps find; an overheard memory; a memory that the system message holds; the newest memory first; the lore in the slots that the memories leave; the Memory slots cap; as many memories as Retrieval slots, and no lore; 0 Retrieval slots; 0 Memory slots; Memory slots above Retrieval slots; a content hit of the last N turns; a name match of the last N turns; a hit older than N turns; a Retrieval cooldown of 0; the cut of a long text.
3. On an SSR Vanilla campaign with the memories of the examples of [section 7](#7-prompt), these messages, each the first message of a conversation, give these first hits:

   | NPC | Message | First hits |
   |---|---|---|
   | Paladin Abel | Who keeps the trouble out of here at night? | Stick asks Jorge for work |
   | Paladin Abel | Are the Dust Bandits around? | Stick asks Jorge for work, Dust Bandits (faction) |
   | Paladin Abel | Have you seen Stick? | Stick asks Jorge for work |
   | Paladin Abel | Do you need a guard? | No memory, because only "guard" is in the memory |
   | Paladin Abel | How are you doing today? | None |
   | Jorge | Did Stick ever find work? | No memory, because the system message holds it |

4. In the server, the system message of an NPC that spoke in one thread and overheard another holds only the memory of the thread in which it spoke. The Dialogue Library of the NPC lists both memories. An NPC with 6 memories of threads in which it spoke gets the newest 5 in its system message.
5. On SSR Vanilla, these messages give no entry: "Where can I buy food?", "How are you doing today?", "I need a doctor.", "My feet are killing me", "Nice weather.", "Want to join my squad?", "Who rules this town?".
6. On SSR Vanilla, these messages give these first entries:

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

7. In the server, with the defaults, a message that finds an entry by content only gives a turn that holds it. The next message, which finds the same entry by content only, gives a turn without it, and the message after that gives it again. A message that names the entry gives it on each turn. The system message of these turns is the same. An entry that Campaign Canon edits shows the edit in the next message, and a renamed entry matches by its new name.
8. The Settings page saves Retrieval slots, Memory slots, and Retrieval cooldown to the INI, and Reset to defaults fills 3, 3, and 1. The next chat message uses the saved values.
9. On the test search of a new SSR Vanilla campaign, "Any work for a mercenary?" lists Mercenary Guild as found by "mercenary", "work" as not a word of the lore, and "any", "for", and "a" as common English words. The Templates subtab gives the same result for SSR Vanilla. On a campaign with the memories of the examples, "Who keeps the trouble out of here at night?" with Paladin Abel lists the memory of Stick and Jorge as found by "trouble" and "night".
10. The full server test suite passes.

These messages still give wrong or arbitrary entries in the prototype, and the limit and the note of the block bound their cost: "my teeth hurt" finds Bad Teeth, "Where can I get a prosthetic arm?" finds Arm of Okran, and "Any bonedogs around?" finds 3 of the many regions with bonedogs.

## 10. Open questions

1. Should retrieval also find characters, such as Beep or Tinfist? Today "Tinfist" finds the Anti-Slavers, whose `leader` field names Tinfist, but not the profile of Tinfist.
2. Should a content hit in the NPC's current region or location rank first? "Any bonedogs around?" would then find the region that the NPC stands in.
3. Should a memory in which the squad member who speaks is a member rank first? A name that many memories hold, such as the name of a squad member, would then find the conversations that the NPC had with the speaker before the other ones.
