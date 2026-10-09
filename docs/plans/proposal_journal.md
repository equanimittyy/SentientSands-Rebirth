# Proposal: Journal

Status: Draft for review

## 1. Summary

The journal is a notebook for the player in the game. The player creates, edits, and deletes journal entries in a Journal window, which the SSR HUB opens. An entry has a title and free text.

The server keeps the entries in the database of the active campaign, so each campaign has its own journal. The plugin only reads and writes the entries through the routes of [section 3](#3-routes), as the Events window does for the events (`server/core/routes.py:50`). No prompt reads the journal, so the journal changes nothing that an NPC says.

[Sections 2 to 5](#2-storage) hold the decided design, and [section 6](#6-open-questions) holds what is open.

## 2. Storage

```sql
CREATE TABLE journal (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  game_time INTEGER,
  title     TEXT NOT NULL DEFAULT '',
  text      TEXT NOT NULL DEFAULT ''
);
```

- The plugin keeps the ID of the selected entry. Without `AUTOINCREMENT`, SQLite can give the ID of a deleted entry to a new entry, and a late save of the deleted entry then overwrites the new entry. The `thread` table uses `AUTOINCREMENT` for the same reason (`server/store/campaign_db.py:41`).
- `game_time` holds the game time at which the player created the entry, in the minutes from day 0 that `campaign_db.game_time` gives (`server/store/campaign_db.py:892`).
- `SCHEMA_VERSION` goes from 16 to 17 (`server/store/campaign_db.py:18`). `open_campaign` refuses a campaign of an earlier version (`server/store/campaign_db.py:128`), so the player must start a new campaign. SSR has no users yet, so the change has no migration.
- The cull does not delete entries, because an entry is the text of the player, as a custom event is ([architecture.md](../info/architecture.md#events)).
- `campaign_db` gets `journal_page`, `journal_entry`, `add_journal_entry`, `save_journal_entry`, and `delete_journal_entry`. Each write is one `BEGIN IMMEDIATE` transaction, as every other write is (`_connect` in `server/store/campaign_db.py:831`).

`journal_page(query, page)` gives one page of the entries:

| Rule | Behavior |
|---|---|
| Order | The newest entry first, by ID. An edit does not move an entry, because a move takes the entry to another page while the player reads it. |
| Search | The page keeps each entry whose title or text holds the query, case-insensitive (`str.casefold`). The search runs in Python, because the SQLite `lower()` folds only ASCII letters. It runs on the server, because the plugin holds only one page. |
| Size | 20 entries for each page (`JOURNAL_PAGE`). |
| Clamp | The server moves a page number outside 1 to the page count into that range, so the delete of the last entry of the last page shows the page before it. An empty journal has 1 page. |
| Label | The day and the title, cut at 40 characters with `...`, for example `Day 12  Trip to the Hub`. A blank title gives its place to the first line of the text that is not blank. An entry with no game time shows no day, and an entry with a blank title and a blank text shows `Empty entry`. |

## 3. Routes

The routes are POST routes in `server/core/routes.py`, beside `/events`.

| Route | Body | Reply |
|---|---|---|
| `/journal` | `page`, `query` | `campaign`, `entries` (each with `id` and `label`), `page`, `pages` |
| `/journal/read` | `id` | `title`, `text`, `time` |
| `/journal/add` | `campaign`, `day`, `hour`, `minute` | `id` |
| `/journal/save` | `campaign`, `id`, `title`, `text` | `status` |
| `/journal/delete` | `campaign`, `id` | `status` |

- Each write sends back the campaign that `/journal` gave. `campaign_write` (`server/core/routes.py:368`) refuses the write with status 409 after a campaign switch, because the same ID can name another entry in another campaign.
- The keys of each listed entry sort after `"id"`, because the plugin splits the list at each `"id":` and Flask sorts the keys (`PopulateEventsUI` in `plugin/ui/EventsWindow.cpp:157`).
- `/journal/add` stores an empty entry at once. An empty entry stays until the player deletes it.
- `/journal/add` carries the game time from the plugin, which reads it as `GetDetailedContext` does (`plugin/game/Context.cpp:638`). The server does not use `PLAYER_CONTEXT`, because it comes from the latest request and can be old ([architecture.md](../info/architecture.md#game-state)).
- `/journal/read` and `/journal/save` answer status 404 with "The entry is gone." for an ID that no entry has.

## 4. Journal window

```
+- Journal ------------------------------------------------- x -+
| Search [___________]       | Day 12, 14:05                    |
| +------------------------+ | Title [Trip to the Hub_________] |
| | Day 14  Shek patrol    | | +------------------------------+ |
| | Day 12  Trip to the Hub| | | Went to the Hub. Bought      | |
| | Day 9   Lost Ruka ne...| | | rations, sold the stolen...  | |
| +------------------------+ | +------------------------------+ |
| [<]    Page 1 / 3     [>]  | Saved.                  [Save]   |
| [New Entry]   [Delete]     |                                  |
+---------------------------------------------------------------+
```

The window takes the size and the left column of the Events window (`CreateEventsUI` in `plugin/ui/EventsWindow.cpp:526`). The left column is the navigator, and the right column is the editor.

### Navigator

- Each keystroke in Search asks `/journal` for page 1. The replies can arrive out of order, so each request takes a number, and the plugin drops each reply that is not the newest, as the Dialogue Library does (`SetLibraryProfile` in `plugin/ui/LibraryWindow.cpp:568`). The read of an entry has its own number.
- `<` and `>` ask for the page before and the page after. Each is disabled on the first or the last page.
- The plugin escapes each label with `MyGUI::TextIterator::toTagsString`, because a list item reads `#` as a colour tag (`server/core/routes.py:63`).
- New Entry sends `/journal/add`. The plugin then clears Search, shows page 1, and selects the new entry, as `FinishEventChange` does after Add Event (`plugin/ui/EventsWindow.cpp:456`).
- Delete opens a popup that asks the player to confirm, with the warning that the delete is irreversible, as `CreateEventDeleteUI` does (`plugin/ui/EventsWindow.cpp:421`).

### Editor

- The line at the top shows the game time of the entry.
- The title box is a one-line `Kenshi_EditBox`, as the Search box of the Events window is (`plugin/ui/EventsWindow.cpp:549`).
- The text box is the multi-line box of `AddBioEditBox` (`plugin/ui/LibraryWindow.cpp:273`): the `Kenshi_WordWrap` skin with `setEditStatic(false)`, word wrap, a scroll bar, and a cap of 16384 characters. `AddBioEditBox` places the box at a fixed left and width, so a new function takes the left and the width, and `AddBioEditBox` calls it with its current values.
- Both boxes load with `setOnlyText` and read with `getOnlyText`. `setCaption` applies colour tags (`MyGUI_EditBox.h`), so a `#` in a stored entry would change the colour of the text after it.
- Save sends `/journal/save`. The status line under the text box shows "Saved." or the error.
- When the title or the text differs from the loaded entry, the plugin saves the entry before the player leaves it: at the select of another entry, a page change, New Entry, and the close of the window. The save at the close has no window to show its reply, so the plugin only logs a failure.

### Plugin code

- The window goes into `plugin/ui/JournalWindow.cpp` and `plugin/ui/JournalWindow.h`, which `plugin/SentientSands.vcxproj` lists.
- The request threads only push their replies onto `g_messageQueue`, and the game thread changes the widgets ([architecture.md](../info/architecture.md#threading)). `ProcessMessageQueue` (`plugin/main.cpp:131`) gets the commands `POPULATE_JOURNAL`, `JOURNAL_ENTRY`, `JOURNAL_ADDED`, `JOURNAL_SAVED`, and `JOURNAL_DELETED`.

### SSR HUB

The Journal button goes below the Events button. `CreateLauncherUI` (`plugin/ui/LauncherWindow.cpp:154`) spaces six buttons by 0.16 at a height of 0.14, which fills the window. For seven buttons, the spacing becomes 0.137 and the height becomes 0.12. `RefreshLauncherUI` (`plugin/ui/LauncherWindow.cpp:219`) gets the caption of the button.

## 5. Tests and docs

- `server/tests/test_campaign_db.py` tests add, save, and delete; that a new entry does not take the ID of the deleted newest entry; and the order, the clamp, the search of the title and the text, the label from the title and from the first line, and the empty journal of `journal_page`.
- [architecture.md](../info/architecture.md) gets a Journal window section beside [Events window](../info/architecture.md#events-window), and the `journal` table in [Campaign storage](../info/architecture.md#campaign-storage).
- The plugin builds only on Windows ([development.md](../info/development.md#plugin)), so the window needs a build and a test in the game there.

## 6. Open questions

1. Does the web app show the journal? This draft gives it no view.
