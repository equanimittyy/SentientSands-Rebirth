# Proposal: Dialogue Threads

Status: The threads (phase 1) are planned. The distillation (phases 2 to 4) is a draft for review.

## 1. Summary

One exchange of dialogue is stored as a copy in the history of each NPC that took part in it ([section 3](#3-current-state)). Nothing links the copies, so a history cannot show who else was there. This proposal gives each chat a thread that records its speakers and, separately, the characters that overheard it. Each copy of a chat line stores the thread ID.

The chat prompt reads the threads to tell an NPC which squad members overheard its conversations. Two smaller changes to the scene complete the fix. The NPC then knows whether it spoke before with the squad member in front of it, or only with a companion of that squad member.

Today the chat prompt gives an NPC its stored dialogue as raw lines, in a window of 20 to 39 lines ([architecture.md](../info/architecture.md#prompts)). A long conversation fills the prompt with exact wording that the NPC does not need. The trim then removes the oldest lines, and nothing of them stays.

The later phases therefore distill each chat thread into a short memory when the chat is quiet for 3 minutes. Each member of the thread, a speaker or an overhearer, reads the memory in its chat prompt instead of the lines of the thread. The memories are a new part of the chat prompt. When every chat thread of an NPC has a memory, the chat prompt of that NPC has no history.

Non-goals:

- One stored row for each line instead of one copy for each NPC ([section 4](#4-threads)).
- A thread ID in the line text or in a prompt.
- A relation for each squad member. An NPC keeps one relation, and the prompt presents it as a feeling towards the player's faction.
- Threads for banter, until a reader needs them.
- A memory for each member of a thread ([section 5](#5-distillation)).
- Memories of banter ([section 7](#7-memories-in-the-prompt)).
- Memories in the bio prompt or in the banter prompt. Both keep the stored lines.
- A memory of older memories, for an NPC that has more memories than the prompt shows.
- The delete of the stored lines. The Dialogue Library and the bio prompt still read them, and the trim still removes them.

## 2. Why

A squad member who never spoke with an NPC asked "Hey, have we met?", and the NPC answered "I believe we spoke before". A minute earlier, another squad member had a long chat with that NPC, outside the talk radius of the first squad member. Three parts of the prompt told the model that the two squad members were one person:

| Part | Fault |
|---|---|
| Scene: first meeting | `met` is true when the NPC spoke with any squad member (`chat_prompt.has_spoken`), so the scene drops "You have never spoken with Izumi before." |
| Scene: relation | The NPC keeps one relation, which the chats of every squad member change, but the sentence names the squad member who speaks: "You are friendly towards Izumi." |
| History | The lines of every squad member are user turns. Each line has the name of its speaker, but nothing in the prompt says that two names are two people, or that they travel together. |

The fix must know who overheard each conversation of the NPC. The copies of a line in the histories of the overhearers cannot give this. Each history is trimmed on its own schedule, and a squad member overhears every chat near the player, so its copies are trimmed first.

Threads also support these later uses:

| Use | What threads add | Status |
|---|---|---|
| A conversation view, for example in the Campaign Dialogue subtab | The view lists who else took part in a conversation and opens the copy of each participant | The subtab is planned ([proposal_campaign_dialogue.md](proposal_campaign_dialogue.md#2-campaign-dialogue)), but it shows one history for each character and does not need threads |
| A delete or an edit of a bad reply | One action changes every copy of a line, not only the copy that the player sees | Not planned. The web app has no dialogue edit. A match on the text would also find the copies, because the copies of a line differ only by the `(Overheard)` tag and the name of the one that the line was said to |
| A summary of old dialogue before the trim | A thread is the unit of a summary, so the summary of a conversation is written once and not once for each copy | Planned in [section 5](#5-distillation) |
| Recall of an earlier conversation in a prompt | The prompt gets a whole earlier conversation when the player refers to it | Not planned. Retrieval in [proposal_lore_retrieval.md](proposal_lore_retrieval.md#1-summary) searches only the lore |
| A group chat in which several NPCs reply | One exchange holds the replies of several speakers | Not planned. A chat has one target today |

Not a reason: the de-duplication of banter. The prompt of a banter collects the recent lines of the NPCs nearby and drops repeated lines by their text (`ambient_event` in `server/scripts/kenshi_llm_server.py`). The copies of a banter line have the same text, so this already works.

## 3. Current state

| Part | Today |
|---|---|
| Chat | The player's line and the reply go into the history of the target, of the squad member who speaks, and of each NPC in the talk or yell radius, with the `(Overheard)` tag for the listeners. The listeners include the squad members near the player, except the squad member who speaks. A whisper has no listeners. |
| Banter | Each line goes into the history of every NPC of the banter request. |
| Speaker | Each dialogue row stores the `npc_id` of its speaker ([architecture.md](../info/architecture.md#characters)). |
| Relation | Each NPC keeps one `Relation`. The judgment of each reply changes it, whichever squad member speaks. |
| First meeting | The scene says "You have never spoken with {name} before." until the NPC has a line that it did not only overhear, from any squad member. |
| Trim | Each character keeps its newest 240 to 260 lines, so the copies of one exchange are trimmed at different times. |
| Cull | **Cull Future Data** deletes the rows dated after the current game time in every history. |
| Views | Only the in-game Dialogue Library shows dialogue, as plain text from `/history`. The web app has no dialogue view. |

## 4. Threads

### Storage

- A `thread` table holds the ID. A `thread_id` column of `dialogue` links each chat row to its thread. Banter rows have no thread. The kind, the game time, and the place of a thread come with the first view that shows them.
- A `thread_member` table holds the thread ID, the `npc_id` of a character, its role (`speaker` or `overheard`), the game time when it joined, and whether it was in the player's faction then. The speakers of a chat thread are the squad member and the NPC. The overhearers are the listeners of each exchange (`chat_prompt.overhearers`).
- The player's faction of a member is recorded when it joins, not read when the prompt is built. The history text therefore stays the same from turn to turn, so the cache serves it, and a later recruit or dismissal does not change what an NPC remembers.
- A thread that no row uses any more, after a trim or a cull, is deleted in the same transaction, with its members, unless it has a memory ([section 6](#6-memory-storage)). A cull also deletes the members that joined after the cut.
- The schema version changes. A campaign of an earlier version does not open, as for every schema change.
- Rejected: members derived from the rows that hold the thread. A squad member overhears every chat near the player, so its copies are trimmed first, and the overheard note would then disappear from the history of the NPC.
- Rejected: one stored row for each line, with a table of the characters that heard it. Each copy has its own `(Overheard)` tag, its own trim, and its own relabel after a rename, so the history of a character would have to rebuild all three from a join.

### Thread lifetime

- A chat thread lasts while the player chats with the same NPC as the same squad member. A chat with another NPC, a chat as another squad member, a campaign switch, a server restart, or a quiet chat starts a new thread. The server keeps the current thread in memory, as it keeps the scene of a conversation ([architecture.md](../info/architecture.md#prompts)). The thread does not follow the scene: a new name or the first exchange starts a new scene but not a new thread.
- The chat is quiet when no chat reply went out in the last 3 minutes and no chat is in progress. The 3 minutes are a constant in the code. The server measures real time, because it sees the game time only in the requests that it gets.
- When the chat becomes quiet, the current chat thread ends. The close of the chat window does not end it. The next exchange, also with the same NPC and the same squad member, starts a new thread.
- The lines that an NPC overhears join the thread of the chat that it overheard.
- Rejected: one thread for each player message. A conversation of ten messages would be ten threads.

### Prompt

- **First meeting.** The NPC spoke before with the squad member who speaks when the history of the NPC holds a line of that squad member without the `(Overheard)` tag. The check reads the speaker of each row, not the name. A line that the NPC only overheard does not count, and a conversation that the trim removed counts only through its memory ([section 7](#history)).
- **Companions.** The scene names the other squad members that the NPC spoke with, by the same check: "Earlier you spoke with Stick, who travels with Izumi." A squad member counts when it is in the player's faction now. The scene stays fixed for a conversation, so this current state cannot change the cached text during a conversation.
- **Relation.** The relation sentence names the player's faction and not the squad member: "You feel friendly towards Nameless, the group Izumi travels with." The grades of the scale do not change. The sentence says only how the NPC feels, so its effect on the reply stays soft. The faction stance sentence still gives the stance of the NPC's faction.
- **Overheard notes.** After the last line of each thread in which the NPC is a speaker, the history adds one user line. The line names the overhearers that were in the player's faction: "Stick and Mikse heard your conversation with Izumi." Other overhearers are not named. A thread that the NPC only overheard gets no note.
- The note of the current thread is at the end of the history, and it moves after each new exchange. The cache therefore loses the tokens of one exchange on each turn. A note at the start of a thread would break the cache from the start of the thread each time a new squad member walks up.
- In the history of an overhearer, its overheard lines keep their `(Overheard)` tag.

Example: Izumi asks Jorge "Hey, have we met?" after Stick's chat with Jorge. If Izumi stood near during that chat, the note after it reads "Izumi heard your conversation with Stick." The scene of Jorge then starts:

```
You have never spoken with Izumi before. Earlier you spoke with Stick, who travels with Izumi. You feel friendly towards Nameless, the group Izumi travels with.
```

## 5. Distillation

### When to distill

- A thread is pending when it ended and has no memory.
- When the chat becomes quiet ([section 4](#thread-lifetime)), the server distills the pending threads of the active campaign in the background, one at a time, the oldest first. Before each call, it checks that the chat is still quiet. A chat that starts during a distillation therefore waits for one call at most.
- The quiet clock starts with the server, so the threads that a restart left without a memory get one 3 minutes after the start.
- The quiet period is the same for all threads. A distillation call uses the same provider as a chat, and a local model serves one request at a time, so a distillation during a chat delays the reply.
- Rejected: a quiet period for each thread. A chat with a second NPC would then wait for the distillation of the chat with the first NPC.
- The thread ends before its call starts, so a chat during the call starts a new thread. A memory therefore covers a whole thread.
- Rejected: a memory for the first part of a thread, and raw lines for the rest. Each copy of a line has its own row in the history of each member, so each copy would need its own mark for where the memory stops.
- A pause of 3 minutes also ends a thread in the middle of a conversation. The NPC then reads the start of the conversation as a memory.
- While the player keeps chatting, with any NPC, no thread is distilled. The pending threads keep their lines in the history until the next quiet period.

### The call

- A new task, `memory`, has its own route ([architecture.md](../info/architecture.md#llm-routing)), so the player can send the distillation to a cheaper model. The Models page shows the route as Conversation memories.
- A new prompt, `prompt_thread_memory.txt`, is in the Conversations group of the Prompts page. It gets the lines of the thread from the history of one of its speakers, because those lines have no `(Overheard)` tag.
- The memory is plain text in the third person and the past tense, at most 80 words. It keeps what each speaker asked, told, offered, promised, or threatened, the names, places, and numbers that they gave, what stayed open, and how each speaker treated the other. It drops greetings and the exact wording. It adds nothing that the lines do not say.
- The memory names each speaker and never says "you", because every member reads the same text.
- An overhearer reads the whole memory, also when it came near after the start of the thread.
- Rejected: a memory for each member, written from the view of that member. Each member would cost one call, and a crowd near a chat would multiply the calls.
- After a failed call, the thread stays pending and its lines stay in the history. The server moves on to the next thread, and the next quiet period tries the failed thread again.
- A campaign switch during a call drops the memory, as it drops a bio, because the same thread ID can name another thread in the new campaign.

## 6. Memory storage

- The `thread` table gets two columns: `memory`, which is empty until the distillation, and `game_time`, the game time of the newest line of the thread.
- A memory is stored once, on its thread. Each member reads it through `thread_member`.
- Rejected: a copy of the memory for each member, as for the lines. Each copy would need its own trim and its own delete, and every copy would hold the same text.
- The stored text of a memory marks each name of a member with the `npc_id` of that member. The server builds the names from the IDs each time that it reads a memory, so a rename changes the names in every memory.
- After the call, the server replaces each name of a member in the text with its mark. It matches whole words only, the longest name first, so "Dust Bandit" does not match inside "Dust Bandit Josh".
- A name that two members share stays as plain text, because its mark could name the wrong member. A name that the memory writes in another form, such as a short form, also stays as plain text.
- Rejected: marks in the lines that the call reads and in the text that it writes. The model writes a better memory from names, and a mark that it drops or changes would leave a broken name.
- A thread with a memory stays, with its members, when the trim removes its last line. The memory is then the only record of the conversation in the prompt.
- Memories are not trimmed. A memory is about 500 bytes, so 10,000 conversations add about 5 MB to a campaign. The prompt reads only the newest 10 of a character ([section 7](#7-memories-in-the-prompt)).
- **Cull Future Data** deletes the memory of each thread whose `game_time` is after the cut. The lines of the thread from before the cut make it pending again, so the next quiet period distills them. A thread that has no line left is deleted.
- The schema version changes, as for the threads.

## 7. Memories in the prompt

The chat request gets a new part, the memories:

| Part | Content | Changes |
|---|---|---|
| System message | As today, then the memories of the NPC | When a new conversation starts, and when a memory of the NPC is written |
| History | The lines of the chat threads of the NPC that have no memory yet | One exchange more each turn |
| Last user message | As today | Every turn |

### Memories

- `prompt_chat_template.txt` gets a `{memories}` placeholder after `{scene}`. The memories are older than every line of the history, so they come before it. The heading stays in the code, as for the rumors, so an NPC with no memory gets no heading.
- The server reads the memories on each turn, not with the scene. A memory that a pause writes during a conversation therefore reaches the next turn. That turn misses the prompt cache once, as after a bio.
- The prompt shows the newest 10 memories of the threads in which the NPC is a member, the oldest first. The limit is a constant in the code. The 10 memories cost about 1,200 tokens, which is in the range of the window of 20 to 39 lines today, but they cover 10 conversations.
- The server builds a header for each memory from the members of the thread, so that one text serves every member:

  | Reader | Header |
  |---|---|
  | A speaker | `[Day 3, 14:05] You spoke with Stick. Izumi heard it.` |
  | An overhearer | `[Day 3, 14:05] You overheard Stick and Jorge.` |

- The header of a speaker names the overhearers that were in the player's faction when they joined, as the overheard note does ([section 4](#prompt)). That note stays only after the lines of a thread with no memory.
- The header and the text name each member by its current name ([section 6](#6-memory-storage)).

### History

- The history holds only the lines of the chat threads that have no memory: the current thread and the pending threads.
- Banter lines leave the chat history. Banter has no threads, so its lines would never get a memory, and an NPC that took part in banter would always have a history. The banter prompt still reads them.
- Rejected: threads and memories for banter. Each banter would cost a distillation call, and the memories of banter would push the memories of chats out of the newest 10.
- When no line is left, the request has no history turns: the system message comes before the last user message.
- The first meeting and the companions of the scene ([section 4](#prompt)) also count a memory of a thread in which the NPC and the squad member were speakers. A conversation that the trim removed therefore still counts.

Example: Jorge spoke with Stick on day 3 and overheard Izumi on day 4. Every line of the two threads has a memory, so the chat with Jorge has no history, and the system message of Jorge ends:

```
Memories of your earlier conversations, oldest first:
[Day 3, 14:05] You spoke with Stick. Izumi heard it.
Stick asked Jorge for work. Jorge offered a job as a guard at the bar for 200 cats a day and told Stick to come back in the morning. Stick agreed. Jorge stayed friendly but doubted that Stick could fight.
[Day 4, 08:12] You overheard Izumi and the barman.
Izumi asked the barman where to sell skeleton parts. The barman named no buyer and told Izumi to speak more quietly.
```

## 8. Memory viewer

A Campaign Memories subtab of the Editor lists the memories of the active campaign. The Dialogue Library and the Campaign Dialogue subtab do not show memories.

- The subtab follows the event log of Campaign Events: a search field above a table of 50 rows on each page, the newest first.
- Each row shows the game time, the speakers, the overhearers, and the text of a memory. The names are the current names, built from the IDs, as in the prompt.
- The search matches the text of a memory and the names of its members, with case ignored. The player can therefore find a memory by what was said or by who has it.
- The subtab shows every memory, not only the newest 10 of each character that the prompt reads.

## 9. Phases and verification

| Phase | Deliverable | Acceptance criteria |
|---|---|---|
| 1. Threads | The storage, the thread lifetime, and the prompt of [section 4](#4-threads) | In the example of [section 4](#prompt), the scene of Jorge says that Jorge never spoke with Izumi, names Stick as a companion, and names the player's faction in the relation sentence. The history of Jorge has the overheard note after the thread with Stick. A chat with another NPC, a chat as another squad member, or 3 minutes without a reply starts a new thread. A trim or a cull that removes the last row of a thread deletes the thread and its members. |
| 2. Distillation | The distillation of [section 5](#5-distillation) and the storage of [section 6](#6-memory-storage) | 3 minutes after the last reply, each thread of the chat has a memory, and the next exchange with the same NPC starts a new thread. A chat during a distillation gets its reply after one call at most. A failed call leaves its thread pending. A cull deletes the memories after the cut. |
| 3. Memories in the chat prompt | The prompt of [section 7](#7-memories-in-the-prompt) | The chat prompt of the NPC, the squad member, and an overhearer holds the memory and no line of the thread. An NPC whose threads all have memories gets no history turns. A memory written during a conversation reaches the next turn. After a rename, the next prompt has the new name in the header and the text of each memory. |
| 4. Memory viewer | The Campaign Memories subtab of [section 8](#8-memory-viewer) | The subtab lists every memory with its speakers, its overhearers, and the current names. A search for a word of a memory, or for the name of a member, finds the memory. |

Phases 2 and 3 each need the phase before them. Phase 4 needs phase 2.

1. `server/tests/test_scene_text.py` covers the first meeting by the speaker of each row, the companions, and the relation sentence.
2. `server/tests/test_chat_prompt.py` covers the overheard note, the history without the lines of a thread with a memory and without banter, the header for a speaker and for an overhearer, the limit of 10 and the order, and a request with no history turns. It also covers the name marks: whole words, the longest name first, a name that two members share, and a rename.
3. `server/tests/test_campaign_db.py` covers the members of a thread, the delete of a thread after a trim or a cull, a memory that stays after the trim of its last line, the order of the pending threads, and a cull that deletes a memory after the cut and makes its thread pending.
4. The full server test suite passes.

## 10. Open questions

1. The quiet period counts real time. Should a long pause in game time also start a new chat thread, for example when the player speeds up the game and comes back to the same NPC within 3 minutes?
2. Should the in-game Dialogue Library show a header line for each thread, for example "Day 3, Squin: with Dust Bandit Josh, Ruka"? MyGUI shows only text, so the header could not open the copy of another participant.
3. What does the relation sentence say for an NPC in the player's faction? "You feel friendly towards Nameless, the group Izumi travels with" reads oddly next to "You travel in Izumi's squad".
4. Should the player be able to edit or delete a bad memory?
