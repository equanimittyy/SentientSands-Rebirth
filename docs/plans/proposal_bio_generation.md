# Proposal: Bio Generation on Request

Status: Draft for review

## 1. Summary

The editor of the web app gets a robot button on each character entry. The button opens a dialog where the player picks what the LLM writes and gives it instructions:

| Choice | The LLM writes |
|---|---|
| Full bio | `Personality`, `Backstory`, and `SpeechQuirks` |
| Personality | `Personality` only |
| Backstory | `Backstory` only |
| SpeechQuirks | `SpeechQuirks` only |

The LLM text fills the form as unsaved changes. The player reads it, then saves or discards it.

One prompt serves every bio path: the robot, the automatic bio after the chat threshold, and Regenerate in the Dialogue Library. The prompt gets the player's instructions, the name, the sex, the race, the faction, the job, the race lore, the current texts of the profile, and the stored dialogue. The current texts carry the rolled traits of a provisional profile, so the LLM builds on them.

## 2. Current state

| Path | Today |
|---|---|
| Generate bio on Campaign Canon | Shows only on a provisional character. `POST /api/campaign/characters/bio` writes the full bio into the campaign at once. It refuses while the entry has unsaved changes. |
| Chat threshold | `generate_bio` (`server/scripts/kenshi_llm_server.py`) writes the full bio in a background thread with `prompt_profile_generation.txt`. |
| Regenerate, provisional profile | `/regenerate_profile` calls `generate_bio`. |
| Regenerate, full profile | `/regenerate_profile` has its own prompt in the code, which "evolves" the profile from the dialogue. It refuses when the NPC has no dialogue. |

The bio prompt gets the origin faction and the provisional texts. It has no instructions, and it always asks for all three parts.

## 3. The robot button

Each character entry, in a template and in a campaign, shows a robot icon button (Lucide `bot`, added as `server/web/images/lucide/bot.svg`) to the left of Delete. A gap of 1.5rem separates the two buttons, so a click meant for one does not hit the other. The button is disabled when the entry is read-only, as Delete is.

```
Holy Sentinel Joe  [Character] [Provisional]               [bot]      [Delete]
```

The button replaces the Generate bio button in Other Details. The Chats field stays.

## 4. The dialog

A new `<dialog id="bio">` in `server/web/index.html`, opened by the robot button:

```
+- Write with the LLM -------------------------------+
| Holy Sentinel Joe                                  |
|                                                    |
| What to write                                      |
| (o) Full bio                                       |
| ( ) Personality                                    |
| ( ) Backstory                                      |
| ( ) SpeechQuirks                                   |
|                                                    |
| Instructions (optional)                            |
| +------------------------------------------------+ |
| | For example: a former slave who distrusts      | |
| | every noble.                                   | |
| +------------------------------------------------+ |
| The LLM also reads the name, sex, race, faction,   |
| job, the race lore, the current texts, and the     |
| chats with this character.                         |
|                                  [Cancel] [Write]  |
+----------------------------------------------------+
```

1. The player picks a choice and writes instructions, then presses Write.
2. A progress dialog shows one step: "Asking the LLM".
3. The web app puts each returned part into its form field and marks the entry as changed. The message line says: "The LLM wrote the personality of Holy Sentinel Joe. Save to keep it."
4. Save goes through the usual record save. On a provisional character, a save that changes a text ends the provisional state, as a hand edit does today. A later automatic bio would otherwise overwrite the text that the player asked for.

The dialog works on unsaved changes. The prompt reads the facts and the texts from the form, so an unsaved race or faction counts.

## 5. The prompt

`prompt_profile_generation.txt` is rewritten:

```
You are a Kenshi Lore Historian.
Task: Write the {parts} of "{name}".
RACE: {race}
SEX: {sex}
FACTION: {faction}
JOB: {job}

RACE LORE:
{race_lore}

CURRENT PROFILE:
{current}

DIALOGUE SO FAR:
{history}

PLAYER INSTRUCTIONS:
{instructions}

RULES:
- INSTRUCTIONS: Follow the player instructions. They win over every other rule.
- CURRENT PROFILE: Keep the traits of the current personality, the events of the current backstory, and the current speech quirk, in your own words, and expand them. A part that you do not write stays as it is, so your text must fit it.
- DIALOGUE: Everything that "{name}" said in the dialogue stays true. You can build on what they revealed.
- SPEECH: A speech quirk is a verbal habit only, with no gestures or sounds.
- BIOLOGY: The character lives with the physical reality of their race, as the race lore describes it.
- CANON: If "{name}" is a unique character of Kenshi, follow their exact established lore.

PARTS:
- Personality: 1-2 sentences on their internal drive.
- Backstory: What they survived before this moment.
- SpeechQuirks: Their verbal habits.

JSON OUTPUT ONLY: an object with exactly these keys: {parts}.
```

| Placeholder | Value |
|---|---|
| `{parts}` | The requested keys, for example "Personality, Backstory, and SpeechQuirks" or "Personality" |
| `{current}` | The three current texts, one per line, with "None." for an empty text |
| `{history}` | The stored dialogue of the character, or "None yet." |
| `{instructions}` | The player's instructions, or "None." |
| `{faction}` | `describe_faction`: the name, the facts, and the description of the faction entry |
| `{race_lore}` | `describe_race`: the race entry |

- The origin faction goes, because the facts that the prompt gets are the name, the sex, the race, the faction, and the job.
- The server keeps the language line, and names only the requested keys in it.
- The reply must hold each requested key as non-empty text. The server ignores any other key, so a reply cannot change a part that the player did not ask for.

## 6. Server

`write_bio(profile, parts, instructions, history, race_lore, faction)` fills the prompt, calls the `profile` LLM task, and returns the requested parts, or None. It stores nothing. Its callers:

| Caller | Facts and texts | Lore | Dialogue | Stores |
|---|---|---|---|---|
| `POST /api/campaign/characters/bio` | The form, from the request | The active campaign | The stored profile, by `id` | Nothing; returns the parts |
| `POST /api/templates/<name>/characters/bio` (new) | The form, from the request | The template (`world_template.load`) | None | Nothing; returns the parts |
| `generate_bio(npc_id)`: chat threshold and Regenerate | The stored profile | The active campaign | The stored profile | Yes |

- The two web routes take `parts` (a list of the three keys) and `instructions`. A route refuses an empty `parts` list or an unknown key.
- The campaign route keeps its `campaign_write` check, because it reads the dialogue of the active campaign by `id`.
- `generate_bio` asks for all three parts, with no instructions, except for an animal: it asks for the `Personality` only, so an animal keeps no backstory and no speech quirk.
- `generate_bio` stores a provisional profile through `promote_profile`, as today. It stores a full profile through `upsert_profile`. It keeps the `PROFILES_IN_PROGRESS` guard and the drop on a campaign change for both.
- `/regenerate_profile` calls `generate_bio` for each profile. A full profile no longer needs dialogue.

## 7. Removed

- The Generate bio button and `writeBio` (`server/web/editor.js`).
- The inline prompt of `/regenerate_profile` for a full profile.

## 8. Docs and labels

- `docs/info/architecture.md`: the editor paragraph, the trigger table of [Provisional profiles](../info/architecture.md#provisional-profiles), and the route table.
- `server/web/prompts.js`: the blurb of the bio prompt.
- `server/web/llm.js`: the hint of the `profile` task.

## 9. Verification

1. The server test suite passes.
2. A scratch render check, with a temp campaign seeded from SSR Vanilla and a fake LLM:
   - The prompt for each choice names the right keys, and the server returns only those keys.
   - A provisional profile shows its rolled texts in `{current}`.
   - A template entry gets its lore from the template, and "None yet." as dialogue.
   - The chat threshold still promotes a provisional profile, and Regenerate rewrites a full profile.
   - An animal gets the `Personality` only from `generate_bio`.
3. In the web app: the robot button sits left of Delete with the gap. Each choice fills only its fields, and Discard restores them. A save of a provisional character ends the provisional state.
