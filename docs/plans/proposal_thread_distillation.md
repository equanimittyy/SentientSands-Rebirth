# Proposal: Thread Distillation

Status: Draft for review. It needs the threads of [proposal_dialogue_threads.md](proposal_dialogue_threads.md).

## 1. Summary

Today the chat prompt gives an NPC its stored dialogue as raw lines, in a window of 20 to 39 lines ([architecture.md](../info/architecture.md#prompts)). A long conversation fills the prompt with exact wording that the NPC does not need. The trim then removes the oldest lines, and nothing of them stays.

This proposal distills each chat thread into a short memory when the chat is quiet for 3 minutes. Each member of the thread, a speaker or an overhearer, reads the memory in its chat prompt instead of the lines of the thread. The memories are a new part of the chat prompt. When every chat thread of an NPC has a memory, the chat prompt of that NPC has no history.

Non-goals:

- A memory for each member of a thread ([section 2](#2-distillation)).
- Memories of banter ([section 4](#4-prompt)).
- Memories in the bio prompt or in the banter prompt. Both keep the stored lines.
- A memory of older memories, for an NPC that has more memories than the prompt shows.
- The delete of the stored lines. The Dialogue Library and the bio prompt still read them, and the trim still removes them.

## 2. Distillation

### Quiet period

- The chat is quiet when no chat reply went out in the last 3 minutes and no chat is in progress. The 3 minutes are a constant in the code.
- The server measures real time, because it sees the game time only in the requests that it gets. The clock starts with the server, so the threads that a restart left without a memory get one 3 minutes after the start.
- The quiet period is the same for all threads. A distillation call uses the same provider as a chat, and a local model serves one request at a time, so a distillation during a chat delays the reply.
- Rejected: a quiet period for each thread. A chat with a second NPC would then wait for the distillation of the chat with the first NPC.

### Thread lifetime

- When the chat becomes quiet, the current chat thread ends. The close of the chat window does not end it. The next exchange, also with the same NPC and the same squad member, starts a new thread.
- A thread is pending when it ended and has no memory.
- The server then distills the pending threads of the active campaign in the background, one at a time, the oldest first. Before each call, it checks that the chat is still quiet. A chat that starts during a distillation therefore waits for one call at most.
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

## 3. Storage

- The `thread` table gets two columns: `memory`, which is empty until the distillation, and `game_time`, the game time of the newest line of the thread.
- A memory is stored once, on its thread. Each member reads it through `thread_member`.
- Rejected: a copy of the memory for each member, as for the lines. Each copy would need its own trim and its own delete, and every copy would hold the same text.
- The stored text of a memory marks each name of a member with the `npc_id` of that member. The server builds the names from the IDs each time that it reads a memory, so a rename changes the names in every memory.
- After the call, the server replaces each name of a member in the text with its mark. It matches whole words only, the longest name first, so "Dust Bandit" does not match inside "Dust Bandit Josh".
- A name that two members share stays as plain text, because its mark could name the wrong member. A name that the memory writes in another form, such as a short form, also stays as plain text.
- Rejected: marks in the lines that the call reads and in the text that it writes. The model writes a better memory from names, and a mark that it drops or changes would leave a broken name.
- A thread with a memory stays, with its members, when the trim removes its last line. The memory is then the only record of the conversation in the prompt.
- Memories are not trimmed. A memory is about 500 bytes, so 10,000 conversations add about 5 MB to a campaign. The prompt reads only the newest 10 of a character ([section 4](#4-prompt)).
- **Cull Future Data** deletes the memory of each thread whose `game_time` is after the cut. The lines of the thread from before the cut make it pending again, so the next quiet period distills them. A thread that has no line left is deleted.
- The schema version changes, as for the threads.

## 4. Prompt

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

- The header of a speaker names the overhearers that were in the player's faction when they joined, as the overheard note of the threads does ([proposal_dialogue_threads.md](proposal_dialogue_threads.md#prompt)). That note stays only after the lines of a thread with no memory.
- The header and the text name each member by its current name ([section 3](#3-storage)).

### History

- The history holds only the lines of the chat threads that have no memory: the current thread and the pending threads.
- Banter lines leave the chat history. Banter has no threads, so its lines would never get a memory, and an NPC that took part in banter would always have a history. The banter prompt still reads them.
- Rejected: threads and memories for banter. Each banter would cost a distillation call, and the memories of banter would push the memories of chats out of the newest 10.
- When no line is left, the request has no history turns: the system message comes before the last user message.
- The first meeting and the companions of the scene ([proposal_dialogue_threads.md](proposal_dialogue_threads.md#prompt)) also count a memory of a thread in which the NPC and the squad member were speakers. A conversation that the trim removed therefore still counts.

Example: Jorge spoke with Stick on day 3 and overheard Izumi on day 4. Every line of the two threads has a memory, so the chat with Jorge has no history, and the system message of Jorge ends:

```
Memories of your earlier conversations, oldest first:
[Day 3, 14:05] You spoke with Stick. Izumi heard it.
Stick asked Jorge for work. Jorge offered a job as a guard at the bar for 200 cats a day and told Stick to come back in the morning. Stick agreed. Jorge stayed friendly but doubted that Stick could fight.
[Day 4, 08:12] You overheard Izumi and the barman.
Izumi asked the barman where to sell skeleton parts. The barman named no buyer and told Izumi to speak more quietly.
```

## 5. Memory viewer

A Campaign Memories subtab of the Editor lists the memories of the active campaign. The Dialogue Library and the Campaign Dialogue subtab do not show memories.

- The subtab follows the event log of Campaign Events: a search field above a table of 50 rows on each page, the newest first.
- Each row shows the game time, the speakers, the overhearers, and the text of a memory. The names are the current names, built from the IDs, as in the prompt.
- The search matches the text of a memory and the names of its members, with case ignored. The player can therefore find a memory by what was said or by who has it.
- The subtab shows every memory, not only the newest 10 of each character that the prompt reads.

## 6. Phases and verification

| Phase | Deliverable | Acceptance criteria |
|---|---|---|
| 1. Threads | [proposal_dialogue_threads.md](proposal_dialogue_threads.md) | As in that proposal |
| 2. Distillation | The quiet period, the `memory` task and prompt, and the storage of [section 2](#2-distillation) and [section 3](#3-storage) | 3 minutes after the last reply, each thread of the chat has a memory, and the next exchange with the same NPC starts a new thread. A chat during a distillation gets its reply after one call at most. A failed call leaves its thread pending. A cull deletes the memories after the cut. |
| 3. Memories in the chat prompt | The prompt of [section 4](#4-prompt) | The chat prompt of the NPC, the squad member, and an overhearer holds the memory and no line of the thread. An NPC whose threads all have memories gets no history turns. A memory written during a conversation reaches the next turn. After a rename, the next prompt has the new name in the header and the text of each memory. |
| 4. Memory viewer | The Campaign Memories subtab of [section 5](#5-memory-viewer) | The subtab lists every memory with its speakers, its overhearers, and the current names. A search for a word of a memory, or for the name of a member, finds the memory. |

Phases 2 and 3 each need the phase before them. Phase 4 needs phase 2.

1. `server/tests/test_chat_prompt.py` covers the history without the lines of a thread with a memory and without banter, the header for a speaker and for an overhearer, the limit of 10 and the order, and a request with no history turns. It also covers the name marks: whole words, the longest name first, a name that two members share, and a rename.
2. `server/tests/test_campaign_db.py` covers a memory that stays after the trim of its last line, the order of the pending threads, and a cull that deletes a memory after the cut and makes its thread pending.
3. The full server test suite passes.

## 7. Open questions

1. Should the player be able to edit or delete a bad memory?
