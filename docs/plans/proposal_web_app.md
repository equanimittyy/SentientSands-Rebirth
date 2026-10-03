# Proposal: Web App Data Editor

Status: Draft for review

## 1. Summary

The web app ([architecture.md](../info/architecture.md#web-app)) holds the gameplay settings, the LLM routing, and the prompts. This proposal adds domain editors for the campaign database ([architecture.md](../info/architecture.md#campaign-storage)) and the world templates from [proposal_data_layers.md](proposal_data_layers.md).

Two tabs hold the editors. The Campaigns tab edits the active campaign, and the Editor tab edits the world templates. The built parts are in [architecture.md](../info/architecture.md#web-app): the campaign list and the creation of a campaign from a template, the overview, factions, rumors, and events of the active campaign, and the search, edit, duplicate, and delete of templates and their records. The rest depends on later phases of the data layers proposal: the characters on phase 2, the import and export on phase 3, and the campaign's world lore on phase 5.

## 2. Scope

The editor works on the user world templates and the active campaign database. Only the Campaigns tab switches campaigns. The web app shows the name of the active campaign and reloads its data when the campaign changes.

| Tab | Still to build |
|---|---|
| Editor | Import and export of templates, with the authors and credits shown before an import. A form for the access rules, when the Kayak converter sets their schema. |
| Campaigns | The profile, dialogue history, and favorite of each character of the active campaign, NPCs and player characters alike, with the bio of each player character ([data layers proposal, section 6.1](proposal_data_layers.md#61-player-characters)). The world lore of the campaign. |

Non-goals:

- Raw SQL editing or a generic table editor.
- Editing a campaign other than the active one.

## 3. Consistency

- The API writes only through the functions of `campaign_db` and `world_template`, never through SQL or file paths built in a route. The `link` table and the `entity_fts` index derive from fields and aliases ([data layers proposal, section 5](proposal_data_layers.md#5-data-model)), and only those modules keep them in step.
- An edit to a user template writes its JSON file after the template validator accepts it ([data layers proposal, section 4](proposal_data_layers.md#4-templates-on-disk)). The vanilla template is read-only, because an update replaces it, so the page offers to duplicate it first. An edit to a campaign writes the campaign database directly.
- The game changes the same records during play, for example "Regen Bio" in the Dialogue Library. Each editable record carries `updated_at`, and a save with an older value is rejected so that the web app reloads the record.
- Each operation opens its own connection with a 5 s busy timeout ([architecture.md](../info/architecture.md#campaign-storage)). A web save then waits for a game write in progress instead of failing.
- The new routes follow the web app's rules in [architecture.md](../info/architecture.md#web-app): a GET route does not change state.

## 4. Acceptance criteria

| Depends on | Criteria |
|---|---|
| Data layers phase 2 | A character profile edit appears in the next chat prompt for that character. |
| Data layers phase 3 | A template exported from the page imports on another install with the same content. |
| Data layers phase 5 | An entity edit in a campaign appears in the next prompt that retrieves it. A search finds a renamed entity. |

## 5. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| A web edit and a game write hit the same record | One change is lost without notice | `updated_at` check; `busy_timeout` |
