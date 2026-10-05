# Proposal: Radiant Conversations

Status: Draft for review

## 1. Summary

A radiant conversation is a talk between the player's characters that the plugin asks for on a timer. It replaces banter, the talk between any NPCs near the player ([section 2](#2-current-system)), which has the problems of [section 3](#3-problems).

1. Only the player's characters take part: 3 to 5 of them, within the talk radius of the selected character ([section 4](#4-participants)).
2. The timer stays the only trigger, and no conversation starts within 3 game hours after a fight of a participant ([section 5](#5-trigger)).
3. The server picks the topic: a memory that the participants share, the surroundings, or a rumor. With no topic, no conversation starts ([section 6](#6-topic)).
4. One LLM call writes the whole conversation, and each participant speaks in it ([section 7](#7-prompt-and-reply)).
5. The server sends the lines of a radiant conversation and of a chat to the game one at a time, with the dialogue delay between them ([section 8](#8-presentation)).
6. Each radiant conversation is a thread, so it gets a memory as a chat does ([section 9](#9-thread-and-memory)).
7. The feature has one name, radiant, in the code, the settings, the logs, and the docs ([section 10](#10-names-and-settings)).

Non-goals:

- Characters outside the player's faction. They do not talk, and they do not overhear.
- Triggers from game events, such as a fight or the arrival in a town.

## 2. Current system

1. The plugin starts a banter when `RadiantDelay` (240 s by default) passes at normal game speed, or when the player clicks Trigger Radiant in the chat window (`OnRadiantClick` in `plugin/ui/ChatWindow.cpp`). Paused time does not count (`plugin/main.cpp:1069`).
2. It finds up to 16 characters within `RadiantRange` (100 by default) of `playerCharacters[0]`, and skips the dead and the unconscious. It sends the first 5 to `/ambient`, with the player's context and the game events.
3. The server drops the animals, and stops when fewer than 2 NPCs remain (`server/chat/routes.py:36`).
4. It loads or creates the profile of each NPC, and collects the newest 15 stored lines of each NPC, up to 40 lines with no duplicates.
5. It builds one system message: the system prompt, the place, the rumors, the player, a one-line entry for each NPC (`Name|ID`, sex, race, identity faction, health, gear, personality, speech quirks), the collected lines, and 10 instructions (`server/chat/routes.py:95`).
6. It sends one call on the `ambient` route (2048 tokens, temperature 0.8), and parses the reply as `Name|ID: line` lines.
7. It stores every line in the history of every NPC of the request, with no thread.
8. The plugin shows the lines as speech bubbles, one line each `g_dialogueSpeedSeconds` (`AmbientPollThread` in `plugin/core/Comm.cpp`), and restarts the interval when the reply arrives.

One feature has three names:

| Name | Where |
|---|---|
| Ambient | `/ambient`, the `ambient` route, `g_enableAmbient`, `EnableAmbientConversations` |
| Radiant | `RadiantDelay`, `RadiantRange`, the Trigger Radiant button, the web app, the prompt heading |
| Banter | The logs, the docs, the code comments |

## 3. Problems

### Who talks

- The plugin counts the animals in its limit of 5, and the server drops them after. Three animals nearby therefore leave 2 NPCs, and an NPC after the first 5 never talks.
- Nothing checks that the NPCs are together. Two NPCs at opposite sides of the 100-unit sphere can talk, and nothing checks for a fight or for hostile factions.
- The sphere is around `playerCharacters[0]`. When the squad is split, the banter can take place far from the squad member that the player watches.
- The model picks 2 or 3 speakers. The other NPCs of the request only hear the banter.

### What they say

- The prompt sets one tone for every NPC ("cynical, weary, or suspicious") and one list of topics, so most banter sounds the same.
- An NPC gets only its personality and speech quirks. It gets no backstory, job, relation to the other NPCs, or memories, which the chat prompt gives through `describe_npc`.
- The collected lines include the chats of each NPC with the player. The prompt uses them only as a list of topics not to repeat, so an NPC cannot continue an earlier talk.
- Each banter has 4 to 6 lines, whatever the scene.
- The instructions are in the code, not in a prompt file, so the Prompts page of the web app cannot edit them.

### What the campaign stores

- An NPC that did not speak stores the lines as its own talk, with no `(Overheard)` tag. The first meeting check (`chat_prompt.spoken_with`) therefore counts a squad member who spoke in a banter as known to every NPC of the request.
- Each banter stores every NPC of the request in the campaign, also the NPCs that did not speak.
- Banter lines have no thread, so they never get a memory, and nothing trims them. They stay in the Dialogue Library and in the bio prompt for good.

### Code

- The parse keeps a line with no colon and more than 5 characters, so the plugin gets a line with no speaker.
- `npcs_data[:12]` never limits, because the plugin sends at most 5 NPCs. The server never reads the `day` and `hour` fields of the request, and the branch for an NPC that is a string never runs, because the plugin sends each NPC as an object.

## 4. Participants

When the timer fires, the plugin picks the participants on the game thread:

1. The center is the selected character, when it is one of the player's characters and can talk. Otherwise, the center is the first character of the current squad that can talk (`GetCurrentSquad` in `plugin/game/Context.cpp`). A character can talk when it is not dead, not unconscious, and not an animal, such as a pack beast of the squad.
2. The participants are the center and the player's characters nearest to it within `TalkRadius` that can talk, up to 5 in all.
3. With fewer than 3 participants, the plugin sends no request, so a lone character or a pair costs no call.

- The player's characters are `world->player->playerCharacters`, the same characters as the `squad` list of the player's context.
- The center is a character that the player watches, so the speech bubbles show on the screen. Rejected: the largest group of the player's characters. An outpost with many characters would always win over the squad that travels with the player.
- `TalkRadius` replaces `RadiantRange`, because a radiant conversation is a talk.
- The request carries each participant with the fields of a banter NPC now, and the game events. The context of the center goes in `player_context`, so the server keeps the context of the character that the player watches (`take_report`).

## 5. Trigger

The plugin starts a radiant conversation only when `RadiantDelay` passes, as banter does now ([section 2](#2-current-system)). Paused time does not count, and the interval restarts when the reply arrives.

- The default of `RadiantDelay` becomes 600 s (10 minutes of real time), from 240 s. A squad that stays together therefore has at most 6 radiant conversations each hour. Each one costs 2 calls, the conversation and its memory, and its memory takes a place in the newest 10 memories that a chat gives each participant (`chat_prompt.memories_block`).
- The Trigger Radiant button of the chat window stays. It skips only the wait for the timer, so every other rule of this plan applies.
- No radiant conversation starts within 3 game hours after a fight of a participant, so the participants do not talk about other things right after a battle. The 3 hours are a constant in the code, not a setting.
- A fight of a participant is an attack by the participant, or a knockout of the participant. The server finds them in the game events that it keeps for the deeds (`server/core/deeds.py`), and it answers the request with no LLM call. Those events are in memory, so a restart of the server forgets the fights before it.
- The plugin sends no event for an attack on a character of the player's faction (`attackingYou_hook` in `plugin/main.cpp`). A participant that took hits but did not hit back and did not go down therefore had no fight.

## 6. Topic

The server picks one kind of topic, at random with equal chances, from the kinds that have material. When no kind has material, the server answers the request with no LLM call.

| Kind | Material | Has material when |
|---|---|---|
| Shared memory | One memory, at random, of a thread in which at least 2 participants were members, with the names of its members | Such a memory exists |
| Surroundings | The place of the center: the town, the biome, and the weather (`scene_text.location_text`) | The context of the center names a town or a biome |
| Rumor | One rumor, at random, of the 5 newest (`PROMPT_RUMORS`) | The campaign has a rumor |

- The server picks the topic, not the LLM, so each conversation is about one specific thing.
- The prompt names one topic. It holds no list of earlier lines not to repeat.
- [Lore retrieval](proposal_lore_retrieval.md) is to add the lore entry of the place to Surroundings. Until then, Surroundings has only the place.

## 7. Prompt and reply

- The system message starts with `prompt_system.txt` (`build_system_prompt`), as in a chat, so the cache serves that part. A new prompt file, `prompt_radiant.txt`, follows with the participants, the place, the topic, and the instructions. The Prompts page of the web app lists it.
- Each participant gets the description of the NPC of a chat (`npc_chat_template.txt`, `describe_npc`), with its `Name|serial`, its health, and its gear.
- Each participant speaks at least once and at most 3 times. The topic and the flow of the conversation decide the number, not a fixed count.
- The tone comes from the profiles of the participants. The prompt sets no tone.
- One call on the `radiant` route writes all lines.
- The reply keeps the form `Name|serial: line`, because the plugin finds the speaker by the serial. The server keeps only a line whose serial names a participant, and it strips bracketed text as now.

## 8. Presentation

The server paces the lines of every conversation, radiant and chat, so one place paces them, and the plugin only shows them:

1. The server answers the request of the plugin when it stores the lines. The reply holds no text. A chat reply still holds its actions, which the plugin queues at once (`ChatResponseThread` in `plugin/ui/ChatWindow.cpp`).
2. A server thread sends each line through the pipe as `NPC_SAY: Name|serial: line` (`send_to_pipe`), with the dialogue delay (`DialogueSpeed`, 5 s by default) between two lines.
3. The plugin shows each line as a speech bubble when it arrives. It no longer paces lines (`AmbientPollThread`, `ChatResponseThread`).

- Each line names its speaker as `Name|serial`, also for a unique NPC. The server takes the serial of a chat target from the chat request, which names the target as `Name|serial`.
- The server does not know when the game pauses, so a pause does not stop the delay. The pacing of the plugin stops it now (`SleepIfPaused` in `plugin/core/Utils.cpp`).

## 9. Thread and memory

- Each radiant conversation is a new thread (`campaign_db.join_thread`). Each participant is a member with the role of a speaker in the player's faction. The thread has no overhearers, because no other character takes part.
- Each participant stores every line with the thread ID and the `npc_id` of its speaker (`campaign_db.append_dialogue`).
- A radiant conversation does not change `state.CURRENT_THREAD` or `state.QUIET_SINCE`, so it never joins a chat thread, and it does not delay the memories of chat threads.
- The distillation of the next quiet period writes the memory, as for a chat thread (`memory.distill_threads`). The distillation runs once in each quiet period, and only a chat starts a new quiet period, so a radiant thread waits until the player chats again and the chat goes quiet.
- The memory replaces the lines, as for a chat thread. Until then, the lines are in the history of each participant (`chat_prompt.chat_lines`).

## 10. Names and settings

| Now | After |
|---|---|
| `/ambient`, `ambient_event` | `/radiant`, `radiant_event` |
| The `ambient` route | The `radiant` route |
| `EnableAmbientConversations`, `g_enableAmbient`, `enable_ambient` | `EnableRadiantConversations`, `g_enableRadiant`, `enable_radiant` |
| `g_ambientIntervalSeconds`, `ambient_timer` | `g_radiantIntervalSeconds`, `radiant_delay` |
| `RadiantRange`, `g_radiantRange`, the `radiant` radius, the Radiant range field of the web app | Removed. `TalkRadius` replaces them |
| `AmbientPollThread`, `g_lastAmbientTick`, `g_triggerAmbient` | `RadiantPollThread`, `g_lastRadiantTick`, `g_triggerRadiant` |
| `AMBIENT:` in the logs, banter in the docs and the comments | `RADIANT:`, radiant conversation |

`RadiantDelay` keeps its name. The server does not upgrade the old settings keys or the banter lines of a campaign.
