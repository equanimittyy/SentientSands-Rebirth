# Proposal: Web App Usability

Status: Draft for review

## 1. Summary

The web app ([architecture.md](../info/architecture.md#web-app)) works, but each page is a plain form. The Models page (the LLM tab) is the hardest to use: it shows every provider and profile as an open card in data order, it cannot test a profile before a save, and it removes items with no warning. This proposal makes the Models page easier to use first, then adds shared save behavior, small fixes to the Settings and Player profile pages, and a theme.

The data editor of [proposal_web_app.md](proposal_web_app.md) adds new pages. Those pages use the shared patterns of [section 3](#3-shared-patterns).

Non-goals:

- A build step, a framework, or an npm package. The web app stays plain HTML, CSS, and JavaScript modules.
- Drag-and-drop ordering. The task chain keeps buttons.

## 2. Current state

| Area | Today |
|---|---|
| Layout | One page with three fieldsets in data order: Providers, Profiles, Tasks (`render` in `server/web/llm.js`). Every card is open. The default configuration has 13 profiles (`server/config/default_models.json`). |
| Save | Each page has one Save button at its end. The Models page shows "Unsaved changes." next to it. Nothing warns the player when the tab closes with unsaved changes. |
| Test | The Test button tests only the saved profile, and it refuses while the page has unsaved changes (`testProfile`). The next render deletes the result. |
| Remove | Remove deletes the item at once. A profile that names a removed provider, or a task that names a removed profile, shows the missing name as a normal choice (`selectInput`). The save then fails with "does not exist" (`llm_config.validate`). |
| Rename | Not possible, because the name is the key. |
| API key | The key state shows only as placeholder text. The defaults store placeholder keys such as `YOUR_OPENROUTER_KEY` (`server/config/default_providers.json`), so a new install shows "Stored key ends in _KEY". |
| New provider | It gets the type `openai` and the base URL `https://`. The only provider types are `openai` and `player2` (`llm_config.PROVIDER_TYPES`). |
| Model ID | Free text with no suggestions. |
| Extra parameters | A one-line JSON input that is checked only on save (`buildPayload`). |
| Errors | The server returns each error as one line of text, for example "Profile kimi: the model ID is empty." The web app joins the lines into one message next to the Save button (`readJson` in `server/web/api.js`). |

## 3. Shared patterns

Each page uses these patterns.

- **Save bar.** The `.actions` row sticks to the bottom of the viewport. It holds Save, Discard, and the state message. Discard loads the saved data from the server again.
- **Unsaved marker.** Each page tracks its unsaved changes. The nav tab of a page with unsaved changes shows a marker. A `beforeunload` handler asks the player before the tab closes while any page has unsaved changes.
- **Field errors.** An invalid field gets a red border and a message below it. The web app checks what the browser can check (required, minimum, maximum, JSON syntax) as the player types. The server stays the final check, and each of its errors marks the field that it names ([section 5](#5-server-changes)).
- **Focus.** The Models page renders again after each structural change, so the focus and the open cards are lost. The page keeps the names of the open cards in its module state, and it gives the focus to the new or changed control after the render.

## 4. Models page

### 4.1 Layout

- The nav tab label changes from "LLM" to "Models". The section ID and the `#llm` hash stay, so a saved link still works.
- The fieldsets go in the order Tasks, Profiles, Providers. The player starts from what the game does, and goes to a provider only to add a key.
- A profile card and a provider card are closed by default. A closed profile card shows its name, provider, model ID, and last test result. A closed provider card shows its name, type, base URL host, and key state. A click opens the card to edit it.
- The five task cards stay open, because the player uses them most.

### 4.2 Test

- The Test button tests the profile and the provider as they are in the form. The player does not save first.
- The result stays on the card as a badge until the next test or the next load: "OK" with the reply time, or "Failed" with the reason. The page keeps the results in its module state by profile name. The results are not saved.
- A "Test all" button on the Profiles fieldset tests each profile, one at a time, so a provider does not get a burst of requests.

### 4.3 Remove and rename

- Remove does not save, so Discard brings back a removed item. Remove asks first only when other items use the item: "Chat and World events use this profile. Remove it from them too?" A yes removes the item and each reference to it.
- A select whose value names a missing item shows "<name> (missing)" as a field error.
- A Rename button lets the player edit the card name. The rename changes each reference in the form. A renamed provider sends its old name as `previous_name`, so that the server keeps its stored key ([section 5](#5-server-changes)).

### 4.4 Providers

- Each provider card shows its key state: "Key set (…a3F9)" or "No key". An empty key and a key that starts with `YOUR_` count as no key.
- The Add form has a preset select: OpenRouter, NanoGPT, Player2, Ollama, and Custom. A preset fills the name, the type, and the base URL from `server/config/default_providers.json`. Custom gives the type `openai` and an empty base URL with the placeholder `https://example.com/v1`.
- The type select shows "OpenAI-compatible" for `openai` and "Player2" for `player2`.
- A Show button next to the API key field shows the typed key.

### 4.5 Profiles

- A "List models" button next to the Model ID field gets the model IDs of the profile's provider. The IDs fill a `<datalist>` on the field. If the call fails, the page shows the reason, and the field stays free text. The page keeps the list of each provider until the next load.
- The extra parameters field becomes a three-row monospace textarea. The page checks that the text is a JSON object as the player types.
- The timeout field gets the hint "The task deadline can stop a profile before its timeout." The router uses the smaller of the two (`llm_router`).

### 4.6 Tasks

- Each chain entry shows the provider, the model ID, and the last test result of its profile.
- "Add a profile" becomes a select with the placeholder "Add a fallback…". A choice adds that profile to the end of the chain.
- The Up, Down, and Remove buttons get an `aria-label` that names the profile, for example "Move kimi-k2.5 up".
- The deadline field shows a warning at 60 s or more, because the plugin stops waiting after 60 s (`plugin/core/Comm.cpp:100`). The temperature field gets `max="2"`, and the max tokens field gets `min="1"`, to match `llm_config.validate`.

## 5. Server changes

| Part | Change |
|---|---|
| `llm_config.validate` | Splits into one check for a provider and one for a profile, which the test route also uses. Each error carries the path of its field, for example `{"field": ["profiles", "kimi", "model"], "message": "The model ID is empty."}`. Only the web app reads `/api/llm`, so the plugin does not change. |
| `llm_config.masked` | Adds `api_key_set`, which is false for an empty key or a key that starts with `YOUR_`. |
| `llm_config.with_stored_keys` | Takes the stored key from `previous_name` when the provider has one. Without this, a renamed provider loses its stored key, because the function finds the key by the new name. |
| `GET /api/llm` | Adds `presets`: the name, type, and base URL of each provider in `default_providers.json`, with no keys. |
| `POST /api/llm/test` | Takes the profile, the provider, and the provider name from the form. An empty key field uses the stored key of that provider name, but only when the base URL is the saved one. |
| `POST /api/llm/models` | New. Takes the same provider fields as the test, calls `GET <base_url>/models`, and returns the model IDs. It uses POST because the provider in the form is not saved. |
| `GET /settings/defaults` | New. Returns the defaults in the shape of the Settings page. The defaults move out of `load_settings` into `SETTINGS_DEFAULTS`. The `/settings` reply does not carry them, because the plugin reads that reply by searching for the first match of each key. |

Each `llm_config` change gets unit tests in `server/tests/test_llm_config.py`. The routes import Flask, so they cannot be tested in the dev container ([development.md](../info/development.md#tests)).

## 6. Settings and Player profile pages

- Each Settings field gets a one-line hint that says what it changes.
- A "Reset to defaults" button fills the form with the defaults from `GET /settings/defaults`. It does not save.
- Each Player profile textarea shows its length in characters.

## 7. Theme

- The fonts stay: Lacquer for titles and Walter Turncoat for UI text. Form fields and card names keep the system font, because Walter Turncoat has no lowercase letters and draws `0` like `O`. A model ID, a URL, or a name in it loses its case.
- The colors become tokens on `:root`, with a sand and rust palette for the light scheme and a dark palette under `prefers-color-scheme: dark`. The current `--accent` (`#b5762a`) stays as the rust color.
- The header shows a banner from `media/images/rebirth.png`. That file is 1920×1080 and 4.5 MB, so `server/web/` gets a copy that is 1200 px wide and less than 200 KB. The full image stays in `media/`.

## 8. Phases

| Phase | Content | Parts |
|---|---|---|
| 1 | Shared patterns: save bar, Discard, unsaved marker, `beforeunload` | Web app |
| 2 | Models layout, closed cards, remove with references, task chain controls, checks as the player types | Web app |
| 3 | Field paths in errors, key state, presets, rename, test before a save | Server and web app |
| 4 | Model list | Server and web app |
| 5 | Settings hints and defaults, Player profile lengths | Server and web app |
| 6 | Theme | Web app |

Each phase is one change that works alone. Phase 4 needs phase 3, because it uses the same provider fields as the test.

## 9. Acceptance criteria

| Phase | Criteria |
|---|---|
| 1 | A tab close with unsaved changes asks the player first. Discard brings back the saved values, a removed profile included. |
| 2 | A removal of a profile that Chat uses asks first, and a yes also removes it from the Chat chain. Invalid JSON in the extra parameters shows a field error before a save. |
| 3 | A test of an unsaved profile works, and `server/user/llm_config.json` does not change. A renamed provider keeps its stored key. A new install shows "No key" for OpenRouter and NanoGPT. A server error marks the field that it names. A test with a changed base URL and an empty key field does not send the stored key. |
| 4 | "List models" fills the suggestions for OpenRouter. With a wrong base URL, the page shows the reason and the field stays usable. |
| 5 | "Reset to defaults" fills the values of `SETTINGS_DEFAULTS` and does not save. |
| 6 | Both color schemes keep text contrast at WCAG AA or better. |

`python -m unittest discover -s server/tests` passes after each phase.

## 10. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| A test sends the stored key to an unsaved base URL | The key goes to a host with a typing error | The test uses the stored key only with the saved base URL. |
| The model list route calls any URL that the form holds | The server makes a request for the caller | The request guard accepts only the web app ([architecture.md](../info/architecture.md#runtime-flow)), and the route returns only model IDs. |
| A render drops the open cards and the focus | The player loses their place | The page keeps the open cards in its module state and gives the focus back. |
| The banner makes the release bigger | A bigger download | A scaled copy under 200 KB. |

## 11. Open questions

- The range settings are game world units from `getPosition().distance` (`plugin/game/Context.cpp:532`). The size of one unit in meters is not known, so the hints cannot give a unit yet.
- It is not known whether the local Player2 API answers `GET /v1/models`. If it does not, its profiles keep a free-text Model ID field.
