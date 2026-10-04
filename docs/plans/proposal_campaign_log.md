# Proposal: Campaign Log

Status: Draft for review

## 1. Summary

The Campaign Events subtab of the Editor becomes Campaign Log, with two subtabs of its own: Dialogue & Memories and Events. Dialogue & Memories shows the dialogue of the active campaign one chat thread at a time, with the memory of each thread ([proposal_dialogue_threads.md](proposal_dialogue_threads.md)). Events keeps the rumors and the event log of Campaign Events.

The in-game Dialogue Library stays, so the player can read the dialogue of one character in the game, or one conversation in the browser.

Non-goals:

- Raw SQL editing or a generic table editor in the web app.
- Banter in Dialogue & Memories. Banter has no threads ([proposal_dialogue_threads.md](proposal_dialogue_threads.md#1-summary)).
- Favorites in the web app. A favorite marks a character, and Dialogue & Memories lists threads.

## 2. Campaign Log

- The subtabs of the Editor are Campaign Canon, Campaign Log, and Templates.
- Campaign Log has two subtabs: Dialogue & Memories and Events.
- Events shows the rumors and the event log, as Campaign Events does today.

## 3. Dialogue & Memories

Dialogue & Memories uses the layout of Campaign Canon: a search field and a list of threads on the left, and the selected thread on the right. It needs phases 1 and 2 of the threads plan ([proposal_dialogue_threads.md](proposal_dialogue_threads.md#9-phases-and-verification)).

- The list holds every chat thread of the active campaign, the newest first. Each row shows the game time and the speakers of the thread.
- The search matches the names of the members of a thread, the text of its lines, and the text of its memory, with case ignored.
- The right pane names the speakers and the overhearers of the thread. Below them, a log box shows the lines of the thread, and a Memorised Summary box shows its memory when the thread has one.
- The log box shows the copy of the lines in the history of the NPC that the squad member spoke with, so no line has the `(Overheard)` tag. The NPC's copy is used because the history of a squad member fills and trims first. A thread whose lines the trim removed shows only its memory.
- The names are the current names, built from the IDs, as in the prompt.
- Dialogue & Memories is read-only. An edit or a delete of a memory is an open question of the threads plan ([proposal_dialogue_threads.md](proposal_dialogue_threads.md#10-open-questions)).

## 4. Verification

- The Editor shows Campaign Canon, Campaign Log, and Templates. Events shows and saves the rumors, and lists the events, as Campaign Events does today.
- Dialogue & Memories lists every chat thread of the active campaign, the newest first. A search for the name of a member, a word of a line, or a word of a memory finds the thread.
- The right pane shows the members, the lines, and the memory of the selected thread. A pending thread shows no Memorised Summary box. A thread whose lines the trim removed shows only its memory.

## 5. Open questions

1. Should the page load every thread with its lines at once, as Campaign Canon loads every record, or load the lines of a thread when the player selects it? The search of the line text needs either the lines of every thread in the page, or a search on the server.
2. Should the name pool (`names.json`) be customizable? The options are a player override, as for the system prompts, or a part of each world template, so that a modded template can add its own names.
3. Should an existing campaign be able to take a newer version of its template, and how does that merge with `origin = 'campaign'` changes?
