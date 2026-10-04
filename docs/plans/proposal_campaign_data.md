# Proposal: Campaign Data: Faction Check and Campaign Dialogue

Status: Draft for review

## 1. Summary

The campaign database, the world templates, the character store keyed by game IDs, the speaker picker, and the web editors are built ([architecture.md](../info/architecture.md#campaign-storage)). This proposal holds the work that is left:

- Faction check ([section 2](#2-faction-of-an-npc)): the prompt follows an NPC that changes faction in game.
- Campaign Dialogue ([section 3](#3-campaign-dialogue)): the Editor of the web app shows the dialogue history and the favorite of each character.

Lore retrieval has its own proposal ([proposal_lore_retrieval.md](proposal_lore_retrieval.md)).

Non-goals:

- Raw SQL editing or a generic table editor in the web app.

## 2. Faction of an NPC

The profile `Faction` is the faction that SSR tells the LLM. Today the server writes the faction that the game reports into it only while it is `Unknown` (`get_character_data`). An NPC that changes faction in game, for example a recruit, therefore keeps its old faction in the prompts.

- The server checks the faction of an NPC only when a chat or ambient banter uses the NPC. It compares the profile `Faction` with the faction in the context of that request, and it writes the profile only when the two are different.

## 3. Campaign Dialogue

A Campaign Dialogue subtab of the Editor shows the dialogue of the active campaign, as the Dialogue Library does in game. Both views stay, so the player can read the dialogue in the game or in the browser. Campaign Canon already edits the profile of each character.

- The subtab lists the same characters as the Dialogue Library ([architecture.md](../info/architecture.md#characters)), NPCs and player characters alike. The player searches the list by name.
- The subtab shows the dialogue history of the selected character and sets its favorite.
- The subtab also shows the memories of the selected character ([proposal_thread_distillation.md](proposal_thread_distillation.md#5-views)).

## 4. Phases and verification

| Phase | Deliverable | Acceptance criteria |
|---|---|---|
| 1. Faction check | The check of [section 2](#2-faction-of-an-npc); tests | A recruit's next chat prompt names its new faction; a context post alone writes no profile |
| 2. Campaign Dialogue | The subtab of [section 3](#3-campaign-dialogue) | The subtab lists the same characters and shows the same history as the Dialogue Library; a favorite set in one shows in the other |

The phases do not depend on each other.

## 5. Open questions

1. Should the name pool (`names.json`) be customizable? The options are a player override, as for the system prompts, or a part of each world template, so that a modded template can add its own names.
2. Should an existing campaign be able to take a newer version of its template, and how does that merge with `origin = 'campaign'` changes?
3. Should the player's edit of an NPC's `Faction` on Campaign Canon survive the faction check of [section 2](#2-faction-of-an-npc)? The check replaces the edit the next time that a chat uses the NPC.
