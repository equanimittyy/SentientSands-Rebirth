# Proposal: Campaign Log

Status: Draft for review

## 1. Summary

The Campaign Log subtab of the Editor and its Dialogue & Memories and Events subtabs are built ([architecture.md](../info/architecture.md#web-app)). This proposal holds the work that is left: the Memorised Summary box of Dialogue & Memories. It needs the distillation of the threads plan ([proposal_dialogue_threads.md](proposal_dialogue_threads.md#5-distillation)).

Non-goals:

- Raw SQL editing or a generic table editor in the web app.
- Banter in Dialogue & Memories. Banter has no threads ([architecture.md](../info/architecture.md#chat-threads)).
- Favorites in the web app. A favorite marks a character, and Dialogue & Memories lists threads.

## 2. Memorised Summary

- Below the dialogue of the selected thread, a Memorised Summary box shows the memory of the thread when it has one. A pending thread shows no box.
- The search also matches the text of a memory.
- A thread whose lines the trim removed stays in the list, because its memory keeps it ([proposal_dialogue_threads.md](proposal_dialogue_threads.md#6-memory-storage)). Its right pane shows only the memory.
- The box is read-only. An edit or a delete of a memory is an open question of the threads plan ([proposal_dialogue_threads.md](proposal_dialogue_threads.md#10-open-questions)).

## 3. Verification

- The right pane shows the memory of a thread that has one, and no Memorised Summary box for a pending thread.
- A search for a word of a memory finds the thread.
- A thread whose lines the trim removed shows only its memory.

## 4. Open questions

1. Should the name pool (`names.json`) be customizable? The options are a player override, as for the system prompts, or a part of each world template, so that a modded template can add its own names.
2. Should an existing campaign be able to take a newer version of its template, and how does that merge with `origin = 'campaign'` changes?
