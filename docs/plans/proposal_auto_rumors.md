# Proposal: Automatic Rumors

Status: Accepted, not built

## 1. Summary

The server writes a rumor only for a deed: a kill or a capture of a known figure, or a custom deed that the player writes ([architecture.md](../info/architecture.md#rumors)). The talk of the wasteland makes no news, also when several conversations come back to the same event.

This plan adds a third kind of deed, `auto`. At most once in each hour of real time, a pass reads the conversation memories that no rumor used, and the LLM spins at most one rumor from them. The player edits and deletes an auto deed as a custom deed.

The plan also shortens the Deed text of a custom deed ([section 2](#2-deed-text)) and the hints of the Deeds list ([section 3](#3-deeds-hints)).

Campaigns move to schema 14 for a new column of the `thread` table, so a campaign of schema 13 does not open.

## 2. Deed text

The Deed column of a custom deed shows "Custom deed - add any rumours you would like characters to possibly comment on" (`server/dashboard/web/editor.js:1110`). The deed text of the in-game Deeds window shows the same words (`server/core/routes.py:78`). The Kind badge already says "Custom", so the Deed text tells only where the rumor comes from:

| Kind | Time | Deed | Rumor |
|---|---|---|---|
| Custom | - | Written by you | They say Beep freed the slaves of Rebirth. |
| Auto | Day 12, 14:05 | From 3 conversations | Word in Squin is that the Hounds pay double for Shek heads. |

`notable_line` (`server/core/deeds.py:180`) gives these texts, so the web app and the in-game window drop their own text for a custom deed and show the line of the deed. "From 1 conversation" takes the singular.

## 3. Deeds hints

The two hints above the Deeds list (`server/dashboard/web/editor.js:1071-1074`) become one sentence that tells only what the list is:

> Kills and captures of known figures, such as Tinfist, and rumors that you write or that SSR makes from your conversations, for NPCs to gossip about.

## 4. Auto deeds

### Storage

| Place | Holds |
|---|---|
| `notable` row | The game time, and as JSON `{"deed": "auto", "threads": [12, 15, 19]}`, the chat threads whose memories the rumor cites. |
| `rumor` row | The text, with the game time of its notable event. |
| `thread.rumor_passes` | `INTEGER NOT NULL DEFAULT 0`. The count of the passes that read the memory of the thread and did not cite it. At 6, the memory leaves the pool. |

- The game time of an auto deed is the newest game time of its cited threads. The cull therefore deletes an auto deed with its memories, and its rumor sorts among the other rumors by game time.
- `campaign_db.add_auto_deed` stores the deed and its rumor, and sets `rumor_passes` of each cited thread to 6, in one transaction, as `add_custom_deed` (`server/store/campaign_db.py:507`) stores a custom deed with its rumor. It writes nothing when a cited thread is gone or already at 6, because a delete or a cull changed the pool during the call.
- The delete of an auto deed keeps its threads at 6.

### Pool

The pool holds each memory whose thread has a `rumor_passes` less than 6. A pass reads the newest 40 of them by thread ID, oldest first, which is about 3,000 tokens. After a pass with a valid reply ([Reply](#reply)), the counts change:

| Memory | `rumor_passes` |
|---|---|
| Cited by the rumor | 6 |
| Read and not cited | +1 |
| In the pool, and older than the newest 40 | 6 |

- The count drops a memory that the LLM passed over 6 times. Without it, the same dull memories go into each prompt, and they invite the LLM to make a theme from unrelated talk.
- A pass runs at most once an hour, and only for a new memory, so a memory stays in the pool for about 6 hours of play. A theme whose memories are further apart makes no rumor.
- The cap of 40 bounds the prompt. The memories older than the newest 40 leave for good, so a cited memory does not let an old memory back into the 40.
- Only the cited memories leave for a rumor. The other memories stay, so a theme can build over several passes.
- The pool decides only which memories can feed an auto rumor. Each memory stays in the campaign, and the chat, the Dialogue Library, and the bio prompt still read it.

### Pass

`memory_loop` (`server/chat/memory.py:96`) checks on each tick of 10 s whether a pass is due, after the memories and the rumors of the deeds. The pass runs in the same thread, so its LLM call never runs at the same time as a call of the memories or the deed rumors, because a local model serves one request at a time. A pass runs when these conditions are all true:

1. 60 minutes of real time passed since the server start or the last pass.
2. The chat is quiet (`chat_is_quiet`).
3. No chat thread waits for its memory, and no deed waits for its rumor.
4. The pool holds a memory whose `rumor_passes` is 0, which no pass has read. A pool without a new memory therefore costs no LLM call.

The hour counts from each pass, also from a failed one, so a provider that keeps failing costs one call in each hour.

### Prompt

The new file `server/data/prompts/prompt_auto_rumor.txt` goes to the LLM with the `synthesis` task. The player can edit it on the Prompts tab, as the other prompts. A sketch:

```
You are a teller of tales in the bars of Kenshi.
Task: Pick the one story from the memories below that the wasteland would retell from bar to bar, and write it as a rumor.

PLAYER FACTION: Nameless.

MEMORIES:
[1] Day 12, 14:05, Squin. Beep and Ruka spoke...
[2] Day 12, 18:40, Squin. ...

RUMORS ALREADY TOLD:
- They say Beep freed the slaves of Rebirth.

RULES:
1. IMPACT: Pick a theme that comes back in several memories, or one conversation whose outcome changes the world, such as a deal, a betrayal, a threat of war, or a new power. One person who insults a few others is not news.
2. NO REPEATS: Never tell again a story that a rumor already tells, also in other words.
3. NONE: When no story meets this bar, give an empty rumor. Most passes find nothing.
4. FACTS: Use only what the memories say.
5. OUTPUT: Only JSON: {"rumor": "...", "memories": [1, 2]}. "memories" lists the label of each memory that the rumor tells.
```

- The memories carry the labels 1 to N, and the server maps each label to its thread ID. A short label is harder for the LLM to get wrong than a thread ID.
- Each memory carries the current names (`chat_prompt.named`), and the game time and the place of its thread.
- The rumors already told are the newest 30 rumors of each kind.
- The player's faction comes with its description, as in the facts of a deed rumor (`rumors.facts`).
- A language other than English adds the LANGUAGE line, as for a deed rumor (`rumors.prompt`).

### Reply

`robust_json_parse` (`server/chat/llm.py:35`) reads the reply, and `rumors.clean` cleans the text of the rumor. A valid reply is JSON with an empty rumor, or with a rumor that cites at least one valid label. The server drops each label that names no memory of the pass.

- Only a valid reply changes the counts. A reply that is not JSON, or a rumor without a valid label, changes nothing, because the LLM judged no memory.
- An empty rumor is the usual reply. It adds 1 to each memory that the pass read.
- The server writes nothing, also no count, when the active campaign changed during the call, because the same thread ID can name another thread in the other campaign.

### Edit and delete

An auto deed works as a custom deed:

- Save and the robot edit its rumor. The robot sends the facts of a custom deed, "The one that the rumor so far tells" (`rumors.deed_sentence`), so the LLM rewrites the rumor with no new facts.
- Delete removes the deed with its rumor, after a confirmation.

Each place that treats a custom deed apart treats an auto deed the same way:

| Place | Change |
|---|---|
| `server/core/deeds.py:164` (`character_deeds`) | It skips an auto deed. |
| `server/core/deeds.py:175` (`character_ids`) | An auto deed names no characters. |
| `server/core/deeds.py:182` (`notable_line`) | The texts of [section 2](#2-deed-text). |
| `server/chat/rumors.py:41,49` | No faction line, and the deed is the rumor so far. |
| `server/core/routes.py:59-62` (`/events`) | The list title of an auto deed is "Auto:" and its rumor. |
| `campaign_db.delete_custom_deed` | It also deletes an auto deed. |
| `server/dashboard/web/editor.js` | `NOTABLE_KINDS` gets "Auto". An auto deed gets the delete of the whole deed, and the confirmation names its kind. The Deeds hints change as [section 3](#3-deeds-hints) tells. |
| `server/dashboard/web/llm.js:14`, `server/dashboard/web/prompts.js:22` | The blurb of the `synthesis` task names the auto rumors, and the Prompts tab lists the new prompt. |
| `plugin/ui/EventsWindow.cpp:15,405,416,505` | `DEED_KINDS` gets `auto`, and Delete removes an auto deed as a custom deed. Without this, Delete in the game removes only the rumor and leaves an empty deed. |

The plugin change needs a build on Windows.

### Rumors in the chat

The chat scene still gives the 5 newest rumors of each kind (`PROMPT_RUMORS` in `server/chat/prompts.py:11`). An auto rumor has a game time, so it comes with its age.

## 5. Rejected alternatives

| Alternative | Reason |
|---|---|
| An hour of game time | A game hour passes much faster than an hour of real time, and each pass is an LLM call, which costs real time and money. |
| Several rumors in each pass | One rumor in each pass keeps the volume low, so the auto rumors do not push the deed rumors out of the 5 newest. |
| No game time for an auto deed, as for a custom deed | A rumor without a game time counts as the newest, so the auto rumors would hold the 5 newest places for good, and the cull would keep them. |
| A mark on each memory that a pass read | A theme whose memories come in two passes never shows together. |
| Only a window of the newest 40 memories | The same dull memories go into each prompt, a cited memory lets an old memory back into the window, and the unused memories wait forever. |
| A cull of the pool by game days | The game time jumps with sleep, fast-forward, and the load of a save. |
| The LLM lists the memories to drop | A weak model drops the wrong memories, and each reply carries a second judgment. |
| Free the memories when the player deletes an auto deed | The next pass would probably spin the same rumor again. |

## 6. Verification

Unit tests, which run with the standard library only (`server/tests/`):

- `campaign_db`: `add_auto_deed` stores the deed and its rumor and sets the cited threads to 6. It writes nothing when a cited thread is gone or at 6. The pool skips a memory at 6. A delete keeps the counts. The cull deletes an auto deed with its memories.
- The counts after a pass: a cited memory goes to 6, a read memory gets 1 more, and a memory older than the newest 40 goes to 6. A failed reply and a campaign switch during the call change nothing.
- The parse of the reply: the labels map to thread IDs, a wrong label drops, and an empty rumor and a reply that is not JSON give no rumor.
- The due check: each of the four conditions of the [Pass](#pass).
- `deeds.notable_events` and `deeds.character_deeds` with an auto deed.

In the game and the web app:

1. In one town, tell three NPCs in separate chats that the Holy Nation marches on the town.
2. Wait for the memories and for the pass. Campaign Log > Deeds shows an auto deed with a rumor about the march.
3. Edit the rumor and save it. Rewrite it with the robot. Delete it. The next pass does not spin the same rumor again.
4. In the in-game Deeds window, the kind button shows Auto, and Delete removes the auto deed.
5. Cull at a game time before the memories. The auto deed goes with them.
