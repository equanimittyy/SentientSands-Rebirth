# Proposal: Web App Data Editor

Status: Draft for review

## 1. Summary

The web app ([architecture.md](../info/architecture.md#web-app)) holds the gameplay settings, the LLM routing, and the player profile. This proposal adds domain editors for the SQLite knowledge store from [proposal_sqlite_knowledge_store.md](proposal_sqlite_knowledge_store.md).

The editor depends on phases 1 and 2 of the SQLite proposal. Until then, the web app edits the player profile over the per-campaign text files.

## 2. Scope

The editor works on the template database and the active campaign database. Campaign switching stays in the in-game Campaign Manager. The web app shows the name of the active campaign and reloads its data when the campaign changes.

| Page | Edits |
|---|---|
| Entities | Search and filter by category. Fields, aliases, children with weights, and access rules. |
| NPCs | Profile, dialogue history, and stats of the active campaign. |
| World events | The event history of the active campaign. |
| Player profile | Player backstory and faction description. |

Non-goals:

- Raw SQL editing or a generic table editor.
- Editing a campaign other than the active one.

## 3. Consistency

- The API writes only through `sentient_db` functions, never through SQL built in a route. The `link` table and the `entity_fts` index derive from fields and aliases ([SQLite proposal, section 6](proposal_sqlite_knowledge_store.md#6-data-model)), and only `sentient_db` keeps them in step.
- An edit to the template becomes a patch ([SQLite proposal, section 7.2](proposal_sqlite_knowledge_store.md#72-step-2-local-patch-layer)), so a re-import of upstream data keeps it. An edit to a campaign writes the campaign database directly.
- The game changes the same records during play, for example "Regen Bio" in the Dialogue Library. Each editable record carries `updated_at`, and a save with an older value is rejected so that the web app reloads the record. The `entity` table needs this column added.
- Each request thread opens its own SQLite connection, with WAL mode and a `busy_timeout`. A web save then waits for a game write in progress instead of failing.
- The new routes follow the web app's rules in [architecture.md](../info/architecture.md#web-app): a GET route does not change state.

## 4. Acceptance criteria

| Depends on | Criteria |
|---|---|
| SQLite phase 2 | An entity edit appears in the next prompt that retrieves it. A stale save is rejected. A search finds a renamed entity. |

## 5. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| A web edit and a game write hit the same record | One change is lost without notice | `updated_at` check; `busy_timeout` |
