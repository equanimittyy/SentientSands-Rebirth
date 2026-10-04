# Proposal: Dialogue Threads

Status: The threads (phase 1) and the memories (phase 2) are built ([architecture.md](../info/architecture.md#chat-threads)). The memories in the chat prompt (phase 3) are a draft for review.

## 1. Summary

One exchange of dialogue is stored as a copy in the history of each NPC that took part in it ([section 3](#3-current-state)). Phase 1 gave each chat a thread that records its speakers and its overhearers, and the chat prompt reads the threads to tell the squad members apart ([architecture.md](../info/architecture.md#chat-threads)).

Today the chat prompt gives an NPC its stored dialogue as raw lines, in a window of 20 to 39 lines ([architecture.md](../info/architecture.md#prompts)). A long conversation fills the prompt with exact wording that the NPC does not need. The trim then removes the oldest lines, and nothing of them stays.

Phase 2 therefore distills each chat thread into a short memory when the chat is quiet for the Conversation timeout ([architecture.md](../info/architecture.md#conversation-memories)). In phase 3, each member of the thread, a speaker or an overhearer, reads the memory in its chat prompt instead of the lines of the thread. The memories are a new part of the chat prompt. When every chat thread of an NPC has a memory, the chat prompt of that NPC has no history.

Non-goals:

- A thread ID in the line text or in a prompt.
- A relation for each squad member. An NPC keeps one relation, and the prompt presents it as a feeling towards the player's faction.
- A memory for each member of a thread ([architecture.md](../info/architecture.md#conversation-memories)).
- Memories of banter ([section 6](#6-memories-in-the-prompt)).
- Memories in the bio prompt or in the banter prompt. Both keep the stored lines.
- A memory of older memories, for an NPC that has more memories than the prompt shows.
- The delete of the stored lines. The Dialogue Library and the bio prompt still read them, and the trim still removes them.

## 2. Why

Threads support these uses:

| Use | What threads add | Status |
|---|---|---|
| A conversation view | The view shows one conversation with its speakers and its overhearers | Built as the Dialogue & Memories subtab of the Editor ([architecture.md](../info/architecture.md#web-app)) |
| A delete or an edit of a bad reply | One action changes every copy of a line, not only the copy that the player sees | Not planned. The web app has no dialogue edit. A match on the text would also find the copies, because the copies of a line differ only by the `(Overheard)` tag and the name of the one that the line was said to |
| A summary of old dialogue before the trim | A thread is the unit of a summary, so the summary of a conversation is written once and not once for each copy | Built ([architecture.md](../info/architecture.md#conversation-memories)). The chat prompt reads it in [section 6](#6-memories-in-the-prompt) |
| Recall of an earlier conversation in a prompt | The prompt gets a whole earlier conversation when the player refers to it | Not planned. Retrieval in [proposal_lore_retrieval.md](proposal_lore_retrieval.md#1-summary) searches only the lore |
| A group chat in which several NPCs reply | One exchange holds the replies of several speakers | Not planned. A chat has one target today |

Not a reason: the de-duplication of banter. The prompt of a banter collects the recent lines of the NPCs nearby and drops repeated lines by their text (`ambient_event` in `server/scripts/kenshi_llm_server.py`). The copies of a banter line have the same text, so this already works.

## 3. Current state

| Part | Today |
|---|---|
| Chat | The player's line and the reply go into the history of the target, of the squad member who speaks, and of each NPC in the talk or yell radius, with the `(Overheard)` tag for the listeners. The listeners include the squad members near the player, except the squad member who speaks. A whisper has no listeners. |
| Banter | Each line goes into the history of every NPC of the banter request. |
| Speaker | Each dialogue row stores the `npc_id` of its speaker ([architecture.md](../info/architecture.md#characters)). |
| Relation | Each NPC keeps one `Relation`. The judgment of each reply changes it, whichever squad member speaks. The scene gives it as a feeling towards the player's faction. |
| Threads | Each chat row stores its thread, and each thread stores its speakers and its overhearers. The scene names the squad members that the NPC spoke with, and the history notes who of the player's faction overheard each conversation of the NPC ([architecture.md](../info/architecture.md#chat-threads)). |
| Memories | Each chat thread gets a memory when the chat is quiet for the Conversation timeout. A thread with a memory stays after the trim removes its lines. No prompt reads the memories ([architecture.md](../info/architecture.md#conversation-memories)). |
| Trim | Each character keeps its newest 240 to 260 lines, so the copies of one exchange are trimmed at different times. |
| Cull | **Cull Future Data** deletes the rows dated after the current game time in every history. |
| Views | The in-game Dialogue Library shows the history of each character as plain text from `/history`. The Dialogue & Memories subtab of the web app shows each chat thread with its memory. |

## 4. Threads

Phase 1 built the threads: the storage, the thread lifetime, and the prompt ([architecture.md](../info/architecture.md#chat-threads)).

## 5. Distillation and memory storage

Phase 2 built the distillation, the storage of the memories, and the Memorised Summary box of the Dialogue & Memories subtab ([architecture.md](../info/architecture.md#conversation-memories)).

## 6. Memories in the prompt

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

- The header of a speaker names the overhearers that were in the player's faction when they joined, as the overheard note does ([architecture.md](../info/architecture.md#chat-threads)). That note stays only after the lines of a thread with no memory.
- The header and the text name each member by its current name ([architecture.md](../info/architecture.md#conversation-memories)).

### History

- The history holds only the lines of the chat threads that have no memory: the current thread and the pending threads.
- Banter lines leave the chat history. Banter has no threads, so its lines would never get a memory, and an NPC that took part in banter would always have a history. The banter prompt still reads them.
- Rejected: threads and memories for banter. Each banter would cost a distillation call, and the memories of banter would push the memories of chats out of the newest 10.
- When no line is left, the request has no history turns: the system message comes before the last user message.
- The first meeting and the companions of the scene ([architecture.md](../info/architecture.md#chat-threads)) also count a memory of a thread in which the NPC and the squad member were speakers. A conversation that the trim removed therefore still counts.

Example: Jorge spoke with Stick on day 3 and overheard Izumi on day 4. Every line of the two threads has a memory, so the chat with Jorge has no history, and the system message of Jorge ends:

```
Memories of your earlier conversations, oldest first:
[Day 3, 14:05] You spoke with Stick. Izumi heard it.
Stick asked Jorge for work. Jorge offered a job as a guard at the bar for 200 cats a day and told Stick to come back in the morning. Stick agreed. Jorge stayed friendly but doubted that Stick could fight.
[Day 4, 08:12] You overheard Izumi and the barman.
Izumi asked the barman where to sell skeleton parts. The barman named no buyer and told Izumi to speak more quietly.
```

## 7. Verification

Phase 3 builds the prompt of [section 6](#6-memories-in-the-prompt). The chat prompt of the NPC, the squad member, and an overhearer holds the memory and no line of the thread. An NPC whose threads all have memories gets no history turns. A memory written during a conversation reaches the next turn. After a rename, the next prompt has the new name in the header and the text of each memory.

1. `server/tests/test_chat_prompt.py` covers the history without the lines of a thread with a memory and without banter, the header for a speaker and for an overhearer, the limit of 10 and the order, and a request with no history turns.
2. The full server test suite passes.

## 8. Open questions

1. The quiet period counts real time. Should a long pause in game time also start a new chat thread, for example when the player speeds up the game and comes back to the same NPC within the Conversation timeout?
2. Should the in-game Dialogue Library show a header line for each thread, for example "Day 3, Squin: with Dust Bandit Josh, Ruka"? MyGUI shows only text, so the header could not open the copy of another participant.
3. What does the relation sentence say for an NPC in the player's faction? "You feel friendly towards Nameless, the group Izumi travels with" reads oddly next to "You travel in Izumi's squad".
4. Should the player be able to edit or delete a bad memory?
