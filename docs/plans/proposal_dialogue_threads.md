# Proposal: Dialogue Threads

Status: Planned. The chat prompt is the first reader ([section 2](#2-why)).

## 1. Summary

One exchange of dialogue is stored as a copy in the history of each NPC that took part in it ([section 3](#3-current-state)). Nothing links the copies, so a history cannot show who else was there. This proposal gives each chat a thread that records its speakers and, separately, the characters that overheard it. Each copy of a chat line stores the thread ID.

The chat prompt reads the threads to tell an NPC which squad members overheard its conversations. Two smaller changes to the scene complete the fix. The NPC then knows whether it spoke before with the squad member in front of it, or only with a companion of that squad member.

Non-goals:

- One stored row for each line instead of one copy for each NPC ([section 4](#4-design)).
- A thread ID in the line text or in a prompt.
- A relation for each squad member. An NPC keeps one relation, and the prompt presents it as a feeling towards the player's faction.
- Threads for banter, until a reader needs them.

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
| A conversation view, for example in the Campaign Dialogue subtab | The view lists who else took part in a conversation and opens the copy of each participant | The subtab is planned ([proposal_campaign_data.md](proposal_campaign_data.md#5-campaign-dialogue)), but it shows one history for each character and does not need threads |
| A delete or an edit of a bad reply | One action changes every copy of a line, not only the copy that the player sees | Not planned. The web app has no dialogue edit. A match on the text would also find the copies, because the copies of a line differ only by the `(Overheard)` tag |
| A summary of old dialogue before the trim | A thread is the unit of a summary, so the summary of a conversation is written once and not once for each copy | Not planned. Today the oldest lines go in blocks of 20 with no summary |
| Recall of an earlier conversation in a prompt | The prompt gets a whole earlier conversation when the player refers to it | Not planned. Retrieval in [proposal_campaign_data.md](proposal_campaign_data.md#3-retrieval) searches only the lore |
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

## 4. Design

### Storage

- A `thread` table holds the ID. A `thread_id` column of `dialogue` links each chat row to its thread. Banter rows have no thread. The kind, the game time, and the place of a thread come with the first view that shows them.
- A `thread_member` table holds the thread ID, the `npc_id` of a character, its role (`speaker` or `overheard`), the game time when it joined, and whether it was in the player's faction then. The speakers of a chat thread are the squad member and the NPC. The overhearers are the listeners of each exchange (`chat_prompt.overhearers`).
- The player's faction of a member is recorded when it joins, not read when the prompt is built. The history text therefore stays the same from turn to turn, so the cache serves it, and a later recruit or dismissal does not change what an NPC remembers.
- A thread that no row uses any more, after a trim or a cull, is deleted in the same transaction, with its members. A cull also deletes the members that joined after the cut.
- The schema version changes. A campaign of an earlier version does not open, as for every schema change.
- Rejected: members derived from the rows that hold the thread. A squad member overhears every chat near the player, so its copies are trimmed first, and the overheard note would then disappear from the history of the NPC.
- Rejected: one stored row for each line, with a table of the characters that heard it. Each copy has its own `(Overheard)` tag, its own trim, and its own relabel after a rename, so the history of a character would have to rebuild all three from a join.

### Chat thread lifetime

- A chat thread lasts while the player chats with the same NPC as the same squad member. A chat with another NPC, a chat as another squad member, a campaign switch, or a server restart starts a new thread. The server keeps the current thread in memory, as it keeps the scene of a conversation ([architecture.md](../info/architecture.md#prompts)). The thread does not follow the scene: a new name or the first exchange starts a new scene but not a new thread.
- The lines that an NPC overhears join the thread of the chat that it overheard.
- Rejected: one thread for each player message. A conversation of ten messages would be ten threads.

### Prompt

- **First meeting.** The NPC spoke before with the squad member who speaks when the history of the NPC holds a line of that squad member without the `(Overheard)` tag. The check reads the speaker of each row, not the name. A line that the NPC only overheard does not count, and a conversation that the trim removed does not count.
- **Companions.** The scene names the other squad members that the NPC spoke with, by the same check: "Earlier you spoke with Stick, who travels with Izumi." A squad member counts when it is in the player's faction now. The scene stays fixed for a conversation, so this current state cannot change the cached text during a conversation.
- **Relation.** The relation sentence names the player's faction and not the squad member: "You feel friendly towards Nameless, the group Izumi travels with." The grades of the scale do not change. The sentence says only how the NPC feels, so its effect on the reply stays soft. The faction stance sentence still gives the stance of the NPC's faction.
- **Overheard notes.** After the last line of each thread in which the NPC is a speaker, the history adds one user line. The line names the overhearers that were in the player's faction: "Stick and Mikse heard your conversation with Izumi." Other overhearers are not named. A thread that the NPC only overheard gets no note.
- The note of the current thread is at the end of the history, and it moves after each new exchange. The cache therefore loses the tokens of one exchange on each turn. A note at the start of a thread would break the cache from the start of the thread each time a new squad member walks up.
- In the history of an overhearer, its overheard lines keep their `(Overheard)` tag.

Example: Izumi asks Jorge "Hey, have we met?" after Stick's chat with Jorge. If Izumi stood near during that chat, the note after it reads "Izumi heard your conversation with Stick." The scene of Jorge then starts:

```
You have never spoken with Izumi before. Earlier you spoke with Stick, who travels with Izumi. You feel friendly towards Nameless, the group Izumi travels with.
```

## 5. Open questions

1. Should a long pause in game time start a new chat thread, for example when the player comes back to the same NPC on the next day without a chat with another NPC between?
2. Should the in-game Dialogue Library show a header line for each thread, for example "Day 3, Squin: with Dust Bandit Josh, Ruka"? MyGUI shows only text, so the header could not open the copy of another participant.
3. What does the relation sentence say for an NPC in the player's faction? "You feel friendly towards Nameless, the group Izumi travels with" reads oddly next to "You travel in Izumi's squad".
