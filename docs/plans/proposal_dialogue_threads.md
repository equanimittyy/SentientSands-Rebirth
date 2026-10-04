# Proposal: Dialogue Threads

Status: Idea. Not scheduled until a feature needs it ([section 2](#2-why))

## 1. Summary

One exchange of dialogue is stored as a copy in the history of each NPC that took part in it ([section 3](#3-current-state)). Nothing links the copies, so a history cannot show who else was there. This proposal gives each conversation a thread ID that every copy of its lines stores. A view of one conversation can then list its participants and open the copy of each one.

Non-goals:

- One stored row for each line instead of one copy for each NPC ([section 4](#4-design)).
- A thread ID in the line text or in a prompt.

## 2. Why

The need is not established yet. Each use below would justify threads, but no plan asks for one of them today. Threads are built only together with the first feature that reads them. Without a reader, the column is data that nothing checks, so its bugs stay hidden.

| Use | What threads add | Status |
|---|---|---|
| A conversation view, for example in the Campaign Dialogue subtab | The view lists who else took part in a conversation and opens the copy of each participant | The subtab is planned ([proposal_campaign_data.md](proposal_campaign_data.md#5-campaign-dialogue)), but it shows one history for each character and does not need threads |
| A delete or an edit of a bad reply | One action changes every copy of a line, not only the copy that the player sees | Not planned. The web app has no dialogue edit. A match on the text would also find the copies, because the copies of a line differ only by the `(Overheard)` tag |
| A summary of old dialogue before the trim | A thread is the unit of a summary, so the summary of a conversation is written once and not once for each copy | Not planned. Today the oldest lines go in blocks of 20 with no summary |
| Recall of an earlier conversation in a prompt | The prompt gets a whole earlier conversation when the player refers to it | Not planned. Retrieval in [proposal_campaign_data.md](proposal_campaign_data.md#3-retrieval) searches only the lore |
| A group chat in which several NPCs reply | One exchange holds the replies of several speakers | Not planned. A chat has one target today |

Not a reason: the de-duplication of banter. The prompt of a banter collects the recent lines of the NPCs nearby and drops repeated lines by their text (`ambient_event` in `server/scripts/kenshi_llm_server.py`). The copies of a banter line have the same text, so this already works.

## 3. Current state

| Part | Today |
|---|---|
| Chat | The player's line and the reply go into the history of the target and of each NPC in the talk or yell radius, with the `(Overheard)` tag for the listeners. A whisper has no listeners. |
| Banter | Each line goes into the history of every NPC of the banter request. |
| Speaker | Each dialogue row stores the `npc_id` of its speaker ([architecture.md](../info/architecture.md#characters)). |
| Trim | Each character keeps its newest 240 to 260 lines, so the copies of one exchange are trimmed at different times. |
| Cull | **Cull Future Data** deletes the rows dated after the current game time in every history. |
| Views | Only the in-game Dialogue Library shows dialogue, as plain text from `/history`. The web app has no dialogue view. |

## 4. Design

- A `thread` table holds the ID, the kind (`chat` or `banter`), the game time of the first line, and the place. A `thread_id` column of `dialogue` links each row to its thread.
- The participants of a thread are the characters whose history holds a row of it. The speakers are the `speaker` values of those rows. Neither needs a table of its own.
- A banter thread is one banter request.
- A chat thread lasts while the player chats with the same NPC as the same squad member. A chat with another NPC, a chat as another squad member, a campaign switch, or a server restart starts a new thread. The server keeps the current thread in memory, as it keeps the scene of a conversation ([architecture.md](../info/architecture.md#prompts)). The thread does not follow the scene: a new name or the first exchange starts a new scene but not a new thread.
- The lines that an NPC overhears join the thread of the chat that it overheard.
- A view shows the copy of the selected character and lists the other participants. The copies are not merged, because each copy has the tags of its own character.
- A thread that no row uses any more, after a trim or a cull, is deleted in the same transaction.
- The schema version changes. A campaign of an earlier version does not open, as for every schema change.
- Rejected: one stored row for each line, with a table of the characters that heard it. Each copy has its own `(Overheard)` tag, its own trim, and its own relabel after a rename, so the history of a character would have to rebuild all three from a join.
- Rejected: one thread for each player message. A conversation of ten messages would be ten threads.

## 5. Open questions

1. Which use of [section 2](#2-why) comes first, and does it need threads at all?
2. Should a long pause in game time start a new chat thread, for example when the player comes back to the same NPC on the next day without a chat with another NPC between?
3. Should the in-game Dialogue Library show a header line for each thread, for example "Day 3, Squin: with Dust Bandit Josh, Ruka"? MyGUI shows only text, so the header could not open the copy of another participant.
