# Proposal: Names of Generic NPCs

Status: Draft for review

## 1. Summary

Today the plugin names each generic NPC as soon as it sees it, and the new name replaces the name that the game gives it, such as Holy Sentinel ([section 2](#2-current-state)). This proposal names a generic NPC only when the player speaks to it, and it keeps the game name as a title in front of the new name. A recruit drops the title. A name changes in game only for an NPC with no name of its own, and only as often as it must. The player sees each change at the moment that it happens:

| Moment | Name in game |
|---|---|
| Before the player speaks to the NPC | Starving Bandit |
| The first chat with the NPC ([section 4](#4-naming-at-the-first-chat)) | Starving Bandit Josh |
| The NPC joins the player's faction ([section 5](#5-recruits)) | Josh |

The provisional profiles ([architecture.md](../info/architecture.md#provisional-profiles)) do not depend on this plan, and this plan does not depend on them.

Non-goals:

- A unique NPC. It keeps the name that the game gives it.
- A name that the player gives with the `/name` command of the chat window. The server never changes it.

## 2. Current state

| Part | Today |
|---|---|
| Scan | Every 2 s, the plugin checks each character that the game updates and each character within 5000 units of a player character. It queues each one whose name `IsGenericName` (`plugin/main.cpp:162`) finds generic. |
| Names | `NameAssignThread` (`plugin/main.cpp:1503`) posts the queue to `/get_batch_identities` (`server/scripts/kenshi_llm_server.py:1133`). The server rolls a name from `names.json` for the sex of the NPC (`generate_unique_lore_name`). |
| Rename | The game thread renames the NPC when it reads `NPC_RENAME: <serial>\|<name>` from the message queue (`ProcessMessageQueue`, `plugin/main.cpp`). The pipe listener puts each pipe message on the same queue, so the server can also send this message. |
| `/name` | The chat window renames its NPC and posts `/rename`, which stores the new `Name`. |
| Keys | Within one chat or banter request, the server keys the NPCs by name (`npc_ids`, `char_datas`, and `memories` in `kenshi_llm_server.py`). |

`IsGenericName` matches a name that equals the name of the character's template in the game data, which works in each game language. It also matches a name that contains a generic name or keyword from `generic_names.json`.

## 3. Name format

- The name is the title and a given name, for example Holy Sentinel Joe. The title is the name that the game shows for the NPC when the player first speaks to it. The given name comes from `names.json` for the sex of the NPC, as today.
- The title tells the player what the NPC is, as the game name did before.
- A new profile key, `GivenName`, holds the given name. `Name` holds the whole name, as today.
- `generate_unique_lore_name` checks the given names of the campaign, so two recruits never share a name. Today it checks each `Name`, and a name with a title never equals a given name.
- A name with a title still contains the generic name, so `IsGenericName` matches it. The server therefore checks `GivenName` first: it never names an NPC with a `GivenName` again.

## 4. Naming at the first chat

At a chat turn that the player sends to a generic NPC:

1. The plugin adds `generic_name` to the context of the NPC (`GetDetailedContext`, `plugin/game/Context.cpp:327`). The value comes from `IsGenericName`. Only the plugin can make this check in each game language, because only the plugin sees the game data.
2. If the profile has no `GivenName` and `generic_name` is true, the server rolls a given name. It stores `GivenName`, and it stores the game name and the given name as `Name`. An NPC that is already in the player's faction gets the given name with no title ([section 5](#5-recruits)), so its name changes once, not twice.
3. If the profile has a `GivenName`, `generic_name` is true, and the game name is not the stored `Name`, the game lost the name, for example after the load of an earlier save. The server takes the stored `Name` and rolls no new name.
4. In steps 2 and 3, the server sends `NPC_RENAME: <serial>|<name>` through the pipe before the LLM call. The name therefore changes in game while the player waits for the reply.
5. The prompt and the dialogue history use the new name. The reply names the NPC as `<name>|<serial>`, as banter does. The plugin then finds the NPC by its serial and not by the old name of the request (`ChatResponseThread`, `plugin/ui/ChatWindow.cpp`).

- Banter and an ambient greeting name no NPC, because the player does not speak to the NPC.
- Until the first chat, the NPC shows its game name in banter, as a listener, in the Dialogue Library, and on Campaign Canon. Several characters can show one game name there, and each keeps its own row by `npc_id`.

## 5. Recruits

A generic NPC that joins the player's faction drops its title, so Starving Bandit Josh becomes Josh.

1. The plugin posts the context of the selected character every 1.5 s (`plugin/main.cpp:1246`). After a recruit, the player selects the new squad member, so the server sees the new faction at once.
2. `/context` checks an NPC context when the `npc_id` starts with `h:` and the faction of the NPC is the player's faction, by name or by `factionID`, as `npc_scene` does.
3. If the profile has a `GivenName`, and the game name is the stored `Name`, the server sets `Name` to `GivenName` and sends `NPC_RENAME`. A game name that differs from the stored `Name` is a name that the player gave, so the server keeps it.
4. If the profile has no `GivenName`, the server changes nothing. The recruit keeps its game name until the player speaks to it, and its first chat gives it the given name with no title.

- The server checks each NPC only once in each server session (a set of `npc_id` in memory). A selected squad member therefore costs one database read, not one read every 1.5 s.
- A context post writes a profile only for this rename, once for each recruit.
- An NPC that leaves the player's faction keeps its name with no title.
- Rejected: the rename at the next chat. The squad would show the title until the player speaks to the recruit.

## 6. Keys by `npc_id`

Within one chat or banter request, the server keys each NPC by `npc_id`, not by name. Today the keys by name work only because each NPC near the player has a unique name. With this plan, two NPCs that the player did not speak to, for example two Dust Bandits, would share one key, and one of them would lose its overheard lines and its banter.

- Rejected: a number in a duplicate name within a request, such as Dust Bandit (2). The number would reach the LLM and the dialogue history.

## 7. Removed

- The scan, `NameAssignThread`, `g_nameCheckQueue`, `g_renamedSerials`, and `NameCheckItem` in the plugin.
- `/get_batch_identities` on the server.

`IsGenericName` and the `POPULATE_GENERIC` message stay, because `generic_name` uses them. The release ships the plugin and the server together, so neither side needs the old behavior of the other.

## 8. Phases and verification

| Phase | Deliverable | Acceptance criteria |
|---|---|---|
| 1. Keys | [Section 6](#6-keys-by-npc_id) in chat and banter, with tests | A chat with two listeners of one name stores the overheard lines of each. A banter with two speakers of one name stores the banter of each. |
| 2. Names | `generic_name` in the plugin context, [section 4](#4-naming-at-the-first-chat), [section 5](#5-recruits), and [section 7](#7-removed). The plugin part needs a Windows build. | In game, a generic NPC near the player keeps its game name until the player speaks to it. At the first chat, its name changes to the title and a given name before the reply appears, and the reply bubble appears over that NPC. A recruit loses its title when the player selects it. A recruit that the player never spoke to keeps its game name, and its first chat gives it a given name with no title. A name from `/name` does not change. After the load of an earlier save, the next chat gives back the stored name. |

Phase 1 runs in the dev container. Phase 2 needs the game.
