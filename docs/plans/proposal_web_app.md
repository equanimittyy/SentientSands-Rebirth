# Proposal: Web App Data Editor

Status: Draft for review

## 1. Summary

The web app ([architecture.md](../info/architecture.md#web-app)) holds the gameplay settings, the LLM routing, the prompts, and the player profile. This proposal adds domain editors for the campaign database ([architecture.md](../info/architecture.md#campaign-storage)) and the world templates from [proposal_data_layers.md](proposal_data_layers.md).

The World events page needs only the campaign database, which exists. The Factions page depends on phase 1 of the data layers proposal, the Characters page on phase 2, the Templates page on phase 3, and the Entities page on phase 5. The Player profile page goes away: the Factions page edits the player's faction ([data layers proposal, section 6.2](proposal_data_layers.md#62-factions)), and the Characters page edits the bio of each player character ([section 6.1](proposal_data_layers.md#61-player-characters)).

## 2. Scope

The editor works on the user world templates and the active campaign database. Campaign switching stays in the in-game Campaign Manager. The web app shows the name of the active campaign and reloads its data when the campaign changes.

| Page | Edits |
|---|---|
| Templates | List, import, export, duplicate, and delete world templates. Create a campaign from a template. Show the authors and credits before an import. |
| Entities | Search and filter the world lore by category. Fields, prose, aliases, children with weights, and access rules. |
| Factions | The factions of the active campaign, the player's faction included: name, aliases, major flag, fields, and description. A faction that came from the template is marked. |
| Characters | Profile, dialogue history, and favorite of each character of the active campaign, NPCs and player characters alike. |
| World events | The event history and the rumors of the active campaign. |

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
| Campaign storage | An edited rumor appears in the next chat prompt. A stale save is rejected. |
| Data layers phase 1 | A faction description edit appears in the next prompt of an NPC of that faction. |
| Data layers phase 2 | A character profile edit appears in the next chat prompt for that character. |
| Data layers phase 3 | A template exported from the page imports on another install with the same content. |
| Data layers phase 5 | An entity edit in a campaign appears in the next prompt that retrieves it. A search finds a renamed entity. |

## 5. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| A web edit and a game write hit the same record | One change is lost without notice | `updated_at` check; `busy_timeout` |
