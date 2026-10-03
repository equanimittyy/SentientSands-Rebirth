# Proposal: Provisional NPC Profiles

Status: Draft for review

## 1. Summary

Today each NPC that the player meets gets a full profile: the canon profile of the world template, or a bio that the LLM writes ([section 2](#2-current-state)). Most NPCs are generic guards, bandits, and traders that the player never talks to again, but each one costs a share of an LLM call. This proposal gives two kinds of profile:

| Kind | Source | Who gets it |
|---|---|---|
| Full | The canon profile of the world template, or a bio that the LLM writes | A canon character, a unique NPC without a canon profile, and a provisional NPC after promotion |
| Provisional | Code only, with no LLM: three rolled personality traits, a backstory, and a speech quirk | Each generic NPC at its first meeting |

A provisional profile becomes full when the player's chats with the NPC reach a threshold, or when the player asks for a bio ([section 5](#5-promotion-to-a-full-profile)).

The names of generic NPCs change in a separate plan, [proposal_npc_names.md](proposal_npc_names.md). The two plans do not depend on each other.

The traits follow the CK3 mod [More Personality Depth](https://steamcommunity.com/sharedfiles/filedetails/?id=3717989134): the personality traits of CK3, each in three tiers. SSR uses the trait concepts and the tier names only. It writes its own text for Kenshi, and it copies no text from the mod.

Non-goals:

- Traits for a full profile. A full profile keeps the shape that it has today.
- Traits that change over time, such as the event shifts of the mod.

## 2. Current state

| Path | Today |
|---|---|
| Chat, an NPC without a stored profile | `generate_character_profile` (`server/scripts/kenshi_llm_server.py:817`) makes one LLM call with `prompt_profile_generation.txt`. |
| Chat listeners and banter | `generate_batch_profiles` (`kenshi_llm_server.py:904`) makes one LLM call for all new NPCs with `prompt_batch_profile_generation.txt`. |
| No `npc_id`, a generation in progress, or a failed generation | `get_character_data` (`kenshi_llm_server.py:989`) returns a stand-in profile with `_transient`, which is not stored. |
| Regenerate in the Dialogue Library | `/regenerate_profile` (`kenshi_llm_server.py:2508`) rewrites `Personality`, `Backstory`, and `SpeechQuirks` from the dialogue history. It refuses an NPC without dialogue. |

## 3. Profile kinds

The kind of a new profile comes from the `npc_id` ([architecture.md](../info/architecture.md#characters)):

| Character | `npc_id` | Profile |
|---|---|---|
| A canon character of the world template | `u:` with a canon row | Full, from the template |
| A unique NPC without a canon row | `u:` | Full, from the LLM, as today |
| A generic NPC, a recruit included | `h:` | Provisional |

A provisional profile has the keys of a full profile, and two more:

| Key | Value |
|---|---|
| `Provisional` | `true` until a bio replaces the provisional text |
| `Interactions` | The number of chat turns in which the NPC replied to the player. An overheard turn and banter do not count. |

- The server counts `Interactions` only while the profile is provisional.
- Rejected: a count from the dialogue history. A banter line has no tag, so it looks like a reply to the player, and the history keeps only the newest 260 lines.
- An edit of `Personality`, `Backstory`, or `SpeechQuirks` on Campaign Canon clears `Provisional`, because a later bio would overwrite the player's text.

## 4. Provisional roll

### 4.1 Traits

Each NPC gets three traits. No two of them are opposites, and each trait has a tier from 1 to 3:

| Tier | Chance | Why |
|---|---|---|
| 1 | 60% | Most people show a trait mildly. |
| 2 | 30% | |
| 3 | 10% | An extreme trait stands out because it is rare. |

The traits and their tiers come from the mod:

| Trait (tier 1 / 2 / 3) | Opposite (tier 1 / 2 / 3) |
|---|---|
| Lustful (Flirtatious / Lustful / Lecher) | Chaste (Reserved / Chaste / Ascetic) |
| Gluttonous (Hearty Eater / Gluttonous / Insatiable) | Temperate (Moderate / Temperate / Abstemious) |
| Greedy (Thrifty / Greedy / Avaricious) | Generous (Charitable / Generous / Munificent) |
| Lazy (Laid-Back / Lazy / Indolent) | Diligent (Conscientious / Diligent / Industrious) |
| Wrathful (Quick-Tempered / Wrathful / Furious) | Calm (Composed / Calm / Serene) |
| Impatient (Restless / Impatient / Hasty) | Patient (Tolerant / Patient / Stoic) |
| Arrogant (Proud / Arrogant / Haughty) | Humble (Modest / Humble / Self-Effacing) |
| Deceitful (Cunning / Deceitful / Treacherous) | Honest (Forthright / Honest / Candid) |
| Craven (Cautious / Craven / Cowardly) | Brave (Daring / Brave / Fearless) |
| Shy (Bashful / Shy / Withdrawn) | Gregarious (Sociable / Gregarious / Effusive) |
| Ambitious (Aspiring / Ambitious / Driven) | Content (Satisfied / Content / Complacent) |
| Arbitrary (Whimsical / Arbitrary / Despotic) | Just (Fair / Just / Righteous) |
| Cynical (Skeptical / Cynical / Nihilistic) | Zealous (Devout / Zealous / Fanatical) |
| Paranoid (Wary / Paranoid / Conspiratorial) | Trusting (Open / Trusting / Naive) |
| Callous (Detached / Callous / Cold-Hearted) | Compassionate (Kind / Compassionate / Saintly) |
| Sadistic (Cruel / Sadistic / Sociopathic) | Compassionate |
| Stubborn (Resolute / Stubborn / Obstinate) | Fickle (Indecisive / Fickle / Erratic) |
| Vengeful (Resentful / Vengeful / Vindictive) | Forgiving (Lenient / Forgiving / Magnanimous) |
| Eccentric (Quirky / Eccentric / Bizarre) | None |

Each trait names the kinds of character that it fits. The server finds the kind from the race:

| Kind | Race | Traits |
|---|---|---|
| Animal | A race that matches `ANIMAL_RACES` | Only Brave, Craven, Wrathful, Calm, Shy, Gregarious, Paranoid, Trusting, Lazy, Diligent, Gluttonous, Patient, Impatient, and Stubborn |
| Skeleton | `is_skeleton` | Each trait except Lustful, Chaste, Gluttonous, and Temperate, because a skeleton does not eat and has no sex |
| Person | Every other race | Each trait |

### 4.2 Trait text

Each tier of a trait has one sentence. `Personality` holds the three sentences, the highest tier first.

- The subject is "They", with the plural verb, as in the chat scene. The text therefore needs no gendered pronoun and no name, so a rename cannot make it wrong.
- The sentence describes behavior, not a label. Tier 1 is mild, and tier 3 is extreme.
- The text fits Kenshi: cats, squads, and the wasteland, not courts and councils. It names no place, faction, race, or person.
- The text of a trait that fits animals describes only behavior that an animal can show, with no speech, money, or beliefs. One sentence then fits an animal and a person.

| Trait | Tier 1 | Tier 2 | Tier 3 |
|---|---|---|---|
| Greedy | They count every cat and spend few of them. | They weigh every favor by what it pays, and they haggle over everything. | They would sell a friend for the right price, and no amount of money is ever enough. |
| Brave | They take risks that make others hesitate. | They stand their ground when others run. | Nothing frightens them, not even certain death. |
| Paranoid | They keep strangers at a distance until those strangers prove themselves. | They suspect a threat in every stranger. | They trust no one, and they treat every approach as an attack. |
| Zealous | Their beliefs guide their days. | They hold their beliefs above comfort, and they judge others by them. | They would kill or die for their beliefs, and they treat doubt as betrayal. |

### 4.3 Backstories and speech quirks

Each person and each skeleton gets one backstory and one speech quirk, rolled from a list of 100 each. An animal gets neither, so its `Backstory` and `SpeechQuirks` are empty.

Backstory rules:

- One or two sentences about past events, with "They" as the subject.
- It names no place, faction, race, person, or historical event, so it fits each faction and invents no lore.
- It mentions no childhood, family, food, or age, so it also fits a skeleton and a Hiver.
- It says nothing about the current faction or job, because the game reports those.
- It describes events, not temperament, so it cannot contradict a trait.

Speech quirk rules:

- It describes the form of speech: word choice, sentence shape, or a verbal habit. It never describes temperament, so it cannot contradict a trait.
- It holds no gesture or sound, because the reply rules allow spoken words only.

| Backstory | Speech quirk |
|---|---|
| They once lost everything they carried to raiders on an empty road, and they have kept a weapon close ever since. | Answers a question with a question before giving a real answer. |
| They owe a debt to someone they would rather not name. | Calls people by their trade instead of their name. |
| They spent a long season alone in the wilds and came back with little to say about it. | Repeats the last words of the other speaker before answering. |

### 4.4 Roll and data

- A new module, `server/scripts/provisional_profile.py`, rolls the profile. It uses the standard library only and has its own unit tests, as `scene_text.py` does.
- The lists are data files next to `names.json`: `server/config/personality_traits.json`, `server/config/backstories.json`, and `server/config/speech_quirks.json`. A trait record holds its ID, its opposites, its kinds, and the name and the sentence of each tier.
- The roll uses `random.Random(npc_id)`. Banter and a chat can meet a new NPC at the same time, and each request writes the profile. The same seed gives the same roll, so the second write changes nothing.
- The text is in English. The system prompt sets the reply language, so replies still follow the language setting. A bio is written in the language of the setting, as today.
- Rejected: the lists as a part of the world template. Each template today describes Kenshi, and a template part needs the validator, the editor, the import, and the export.

## 5. Promotion to a full profile

A bio replaces the provisional text in one of three ways:

| Trigger | Behavior |
|---|---|
| Threshold | After each chat reply, the server adds 1 to `Interactions` of the NPC that replied. When the count reaches the threshold, the server starts the bio in a background thread. |
| Regenerate in the Dialogue Library | `/regenerate_profile` promotes a provisional profile. It does not need dialogue history for a provisional profile, so the plugin does not change. |
| Generate bio on Campaign Canon | A new route of the web app promotes the character that the page shows ([section 6](#6-web-app)). |

The threshold is a new setting, `bio_interactions`, with a default of 5. A value of 0 gives a bio only when the player asks for one. Only the server reads the setting, so the server does not send it to the plugin.

Bio generation:

- A new prompt, `prompt_bio_generation.txt`, takes the values of `prompt_profile_generation.txt` and two more: `{provisional}`, the provisional `Personality`, `Backstory`, and `SpeechQuirks`, and `{history}`, the dialogue lines of the NPC.
- The prompt tells the LLM to keep the traits, to expand the backstory so that it fits the race, the faction, and the job, and to keep true everything that the NPC said in the dialogue. The reply has the JSON keys of a profile today.
- The write holds only `Personality`, `Backstory`, and `SpeechQuirks`, and it clears `Provisional` and `Interactions`. A route that waits for the LLM must write only the keys that it changed ([architecture.md](../info/architecture.md#campaign-storage)).
- `PROFILES_IN_PROGRESS` stops a threshold bio and a requested bio for the same NPC from running together.
- After a failed call, the profile stays provisional. The count stays at or above the threshold, so the next chat turn tries again.
- A background thread keeps the reply from waiting for a second LLM call. The plugin stops waiting after 60 s.
- The bio takes effect at the next chat turn. The NPC block is in the system message, so that turn misses the prompt cache once.

## 6. Web app

- Campaign Canon marks each provisional character as Provisional in the list and on its record.
- Other Details shows `Interactions` and the threshold, read-only, for example "3 of 5 chats".
- A provisional record has a Generate bio button. The route carries the campaign that the page loaded, as each edit does.
- A save that changes `Personality`, `Backstory`, or `SpeechQuirks` clears the mark ([section 3](#3-profile-kinds)).
- The Settings page gets a field for `bio_interactions`. Its help: "How many times you talk to a generic NPC before the LLM writes its full bio. 0 writes a bio only when you ask for one."
- The Prompts page describes `prompt_bio_generation.txt`.

## 7. Example

A Holy Sentinel of a Holy Nation patrol rolls Paranoid (tier 3), Zealous (tier 2), and Brave (tier 1) at its first meeting. When the player speaks to it, it becomes Holy Sentinel Aldo in game ([proposal_npc_names.md](proposal_npc_names.md)), and the NPC block of the chat reads:

```
CHARACTER: Holy Sentinel Aldo
RACE: Greenlander
SEX: Male
JOB: Patrol
CURRENT FACTION: The Holy Nation: …
ORIGIN FACTION: Same as the current faction.
PERSONALITY: They trust no one, and they treat every approach as an attack. They hold their beliefs above comfort, and they judge others by them. They take risks that make others hesitate.
BACKSTORY: They once lost everything they carried to raiders on an empty road, and they have kept a weapon close ever since.
SPEECH QUIRKS: Answers a question with a question before giving a real answer.
```

## 8. Phases and verification

| Phase | Deliverable | Acceptance criteria |
|---|---|---|
| 1. Roll | The three data files, `provisional_profile.py`, and tests | The tests show 100 unique backstories and 100 unique quirks, three tiers with text for each trait, opposites that name each other, no gendered pronoun, and no name of an SSR Vanilla faction, race, location, or region in any text. A roll gives three traits with no opposites, only traits of its kind, and the same result for the same `npc_id`. The player reviews each text before the merge. |
| 2. Provisional profiles | The wiring in `get_character_data`, chat listeners, and banter | A first chat with a generic NPC stores a provisional profile and makes no profile LLM call. A banter with new generic NPCs makes no profile LLM call. A unique NPC without a canon profile still gets an LLM bio. |
| 3. Promotion | `Interactions`, the setting, the prompt, the background bio, and the Regenerate change | The fifth chat turn starts a bio, and the next turn holds it. A failed call keeps the profile provisional and tries again at the next turn. Regenerate promotes an NPC without dialogue. |
| 4. Web app and docs | [Section 6](#6-web-app), and the Characters, Prompts, and Settings sections of `architecture.md` | A provisional character shows its mark and count. Generate bio promotes it. A save of its personality clears the mark. |

The checks run against a temporary campaign that is seeded from SSR Vanilla, never against the live campaign of the server.

## 9. Open questions

1. With provisional profiles, batch generation serves only unique NPCs without a canon profile, which are rare. Should `generate_batch_profiles` and `prompt_batch_profile_generation.txt` go, so that such an NPC goes through the single generation?
2. Should the faction or the race of an NPC weight the roll, for example Zealous more often in The Holy Nation? The faction entry in the prompt already tells the LLM what the faction values.
3. Should animals get a provisional profile with animal traits only, as [section 4.1](#41-traits) says, or keep the LLM bio of today?
4. Is 5 chats the right default for the threshold?
