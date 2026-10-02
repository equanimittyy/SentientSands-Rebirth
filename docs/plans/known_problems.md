# Known problems

The problems below are known and not fixed. Each section gives the failure, the cause, and a fix. Line numbers refer to `server/scripts/kenshi_llm_server.py` unless a section names another file.

| Problem | Effect | Fix size |
|---|---|---|
| A relation change is lost when two chats overlap | One judgment is lost | About 10 lines and a test |
| `/chat` fails when the context has no ID | The chat returns 500 and no reply | 1 line |
| Stand-in profiles are stored with `_transient` | `/rename` does not rename the NPC | A few lines and a cleanup of stored rows |
| The "SKIP SAVE" branch in `/chat` is dead | None | 3 lines |
| A player cannot edit an NPC profile by hand | A bad profile cannot be fixed in a text editor | None to medium, by option |

## A relation change is lost when two chats overlap

`/chat` computes the new Relation from the profile that it read before the LLM call, and it writes that value after the call. If two chats with the same NPC overlap, the second write replaces the first. For example, two judgments of +3 on a Relation of 10 store 13, not 16.

The dialogue and the other profile keys do not have this problem, because `campaign_db` merges only the keys that a caller passes ([architecture.md](../info/architecture.md#campaign-storage)).

Fix: add `campaign_db.change_relation(storage_id, delta)`. It reads the value, adds the delta, clamps the result to -100..100, and writes it in one `BEGIN IMMEDIATE` transaction. The judges loop in `chat()` then passes the judgment as the delta. A test with two threads must show that both changes stay.

## `/chat` fails when the context has no ID

Line 2009 reads `live_ctx`, which `chat()` does not define. A chat whose `context` has neither `storage_id` nor `id` raises `NameError`, so the player gets a 500 and no reply.

Fix: read `LIVE_CONTEXTS.get(primary_npc, {})` at that line. It is not known whether the plugin always sends an ID. If it does, the failure does not occur in play, and the branch can be deleted instead.

## Stand-in profiles are stored with `_transient`

For an NPC with no stored profile, `get_character_data(..., skip_generate=True)` returns a stand-in profile with the key `"_transient": true`. `/ambient` (line 1791) passes this profile to `append_dialogue`, which stores it with the key.

`/rename` then reads the stored profile, finds the key, and answers "No profile to rename". The NPC keeps its old name in the database.

Fix: drop the keys that start with `_` before `campaign_db` stores a profile. Remove the key from the rows that already have it, for example with one `json_remove` update when a campaign opens.

## The "SKIP SAVE" branch in `/chat` is dead

The branch at line 2495 runs only for a stand-in profile with no history. The route appends the new lines just before the check, so the history is never empty and the branch never runs.

Fix: delete the branch and its `has_history` variable. The behavior does not change.

## A player cannot edit an NPC profile by hand

The NPC profiles are JSON strings in `campaign.db`, so a player cannot fix a bad profile in a text editor.

The NPCs page of the web app ([proposal_web_app.md](proposal_web_app.md)) is the planned editor. Until it exists, these options are available:

| Option | Work | Limit |
|---|---|---|
| Wait for the NPCs page | None | No hand edits until the page exists |
| JSON export and import routes | Two routes, validation, and a button | The NPCs page replaces this work |
| A SQLite browser on `campaign.db` | None | An edit to the JSON string in the `profile` column can break the profile |
