# Proposal: Campaign Dialogue

Status: Draft for review

## 1. Summary

The campaign database, the world templates, the character store keyed by game IDs, the speaker picker, and the web editors are built ([architecture.md](../info/architecture.md#campaign-storage)). This proposal adds a Campaign Dialogue subtab to the Editor of the web app. The subtab shows the dialogue history and the favorite of each character.

Non-goals:

- Raw SQL editing or a generic table editor in the web app.

## 2. Campaign Dialogue

A Campaign Dialogue subtab of the Editor shows the dialogue of the active campaign, as the Dialogue Library does in game. Both views stay, so the player can read the dialogue in the game or in the browser. Campaign Canon already edits the profile of each character.

- The subtab lists the same characters as the Dialogue Library ([architecture.md](../info/architecture.md#characters)), NPCs and player characters alike. The player searches the list by name.
- The subtab shows the dialogue history of the selected character and sets its favorite.

## 3. Verification

- The subtab lists the same characters and shows the same history as the Dialogue Library.
- A favorite that the player sets in one view shows in the other.

## 4. Open questions

1. Should the subtab read the routes of the Dialogue Library (`/characters`, `/history`, `/favorite`), or new JSON routes under `/api/campaign/`? The Library routes return the list as one comma-joined string, and the history as text that is formatted for the window in game and holds only the last 250 lines.
2. Should the name pool (`names.json`) be customizable? The options are a player override, as for the system prompts, or a part of each world template, so that a modded template can add its own names.
3. Should an existing campaign be able to take a newer version of its template, and how does that merge with `origin = 'campaign'` changes?
