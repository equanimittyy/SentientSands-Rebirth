[img]images/title.png[/img]
[b][i]A RE_Kenshi AI dialogue mod for Kenshi[/i][/b]

[b]Sentient Sands Rebirth[/b]
lets you talk to NPCs, create memories, and drive your own dynamic story in the world of Kenshi. Powered by LLMs.

Rebirth rebuilds version 0.2 of [url=https://steamcommunity.com/sharedfiles/filedetails/?id=3675880187]Sentient Sands[/url] by Harvicus. What's new:
[list]
[*] [b]NPCs who remember:[/b] new chats, rumours, and radiant conversations. NPCs remember what you said, what they overheard, and what the world talks about
[*] [b]Easy setup:[/b] a modern, simple web app
[*] [b]Overhauled action system:[/b] trade, hire, recruit, heal, or buy a release from prison in the chat, and build your trades from real items in the new Barter window
[*] [b]NPCs who know Kenshi:[/b] real Kenshi lore of its factions, history, races, places, and regions. NPCs know who leads each faction, where it holds ground, and who its enemies are, and they bring up the lore that your words touch
[/list]

[b]Requires RE_Kenshi v0.3.5 or later, and an AI model![/b]

[img]images/features.png[/img]
[list]
[*] Talk to any NPC in your own words. Whisper, talk and yell
[*] Make deals in chat: trades, gifts, charity, healing and repair, liberation, recruit, and hire
[*] Build a trade from real items and cats in the Barter window, which shows the profit or the loss of the NPC
[*] Radiant conversations: your squad members who stand together talk to each other, and NPCs who relax at a bar talk about rumors
[*] NPC profiles: each NPC that you meet gets a personality, a backstory, and a way of speaking - also augmented with AI bio generation when needed
[*] Memories: NPCs remember your conversations and what they overheard, and recall an older conversation when your line touches it
[*] World events and rumors: kill or capture a unique character, and the world talks about it. Stories that keep coming up in your conversations become rumors too
[*] The SSR HUB (F8) holds the Dialogue Library, the Events, and your Journal, so you never have to leave Kenshi
[*] The web app holds your campaigns, an editor for what NPCs know, world templates that you can share, the prompts, and the settings
[*] Works with any OpenAI-compatible service, such as OpenRouter or Player2, or a local model through Ollama, llama.cpp, or LM Studio
[*] The in-game windows and the NPC replies come in English, Spanish, French, Japanese, or Russian
[/list]

[b]Compatible with:[/b]
[list]
[*] Vanilla Kenshi: [b]Yes[/b]
[*] Universal Wasteland Expansion: [b]Yes[/b]
[/list]

[img]images/install_setup.png[/img]
[olist]
[*] Install [url=https://github.com/BFrizzleFoShizzle/RE_Kenshi/releases]RE_Kenshi[/url] v0.3.5 or later
[*] Subscribe to this mod
[*] In the Kenshi launcher, check [b]Sentient Sands Rebirth[/b], and uncheck the original Sentient Sands (if you have it)
[*] Start Kenshi. Your browser opens the SSR web app
[*] On the [b]Models[/b] tab of the web app, connect a model, and press [b]Test[/b]. The [b]Tutorial[/b] tab shows how to configure everything
[*] Select an NPC in the game, and press [b]\[/b] (default) to talk to it
[/olist]

[img]images/chat_commands.png[/img]
[b]Keys:[/b]
[list]
[*] [b]\[/b] - Talk to the selected NPC. You can change the chat key on the Settings tab of the web app
[*] [b]F8[/b] - Open the SSR HUB: the Dialogue Library, Events, Journal, Cull Future Data, Open Web App, Restart Server, and Help
[*] [b]Enter[/b] on an empty line - Close the chat window
[/list]

[b]Deals:[/b]
Start a line with ! to ask the NPC for something that the game can carry out, for example: [i]!b I want to buy your water[/i]
[list]
[*] [b]![/b] and a space - SSR picks the kind of deal from your line (Not recommended)
[*] [b]!t[/b] - Threaten the NPC, or make a demand
[*] [b]!b[/b] - Buy, sell, or swap items, give a gift, or ask for charity
[*] [b]!h[/b] - Ask for the treatment of your wounds, or the repair of your robotic parts
[*] [b]!l[/b] - Ask for a release from prison or slavery
[*] [b]!r[/b] - Ask the NPC to join your squad for good
[*] [b]!f[/b] - Ask the NPC to come along, or hire it for a while
[*] [b]!d[/b] - Tell a hired follower to leave
[*] [b]!end[/b] - End the deal
[/list]
You can type the full word instead of the letter, for example [i]!barter[/i]. Your next lines without ! stay in the same deal.

[b]Other commands:[/b]
[list]
[*] [b]/help[/b] - Open the in-game guide, which also lists the test commands
[*] [b]/cheats[/b] - Open the Cheats window
[/list]

[img]images/faq.png[/img]
[b]Q: Does it cost money?[/b]
A: The mod is free. An online service, such as OpenRouter, needs an API key and sets its own prices. A local model through Ollama or llama.cpp needs no API key, and can be free

[b]Q: Can I run a local model?[/b]
A: Yes. Connect Ollama, llama.cpp, or LM Studio on the Models tab of the web app. Local models can be slower, so lower [b]Retrieval slots[/b] on the Settings tab if you need. Each slot adds about 250 tokens to every line, and the game waits at most 60 seconds for a reply

[b]Q: The NPC says that it could not respond![/b]
A: On the Models tab of the web app, press [b]Test[/b] on your default profile. If the test fails, check the API key and the Model ID

[b]Q: The chat key does nothing![/b]
A: Select an NPC first, and close the Dialogue Library and the Barter window

[b]Q: Can I use it with the original Sentient Sands?[/b]
A: No. Both mods use the same server port, so only one can run. Disable the original Sentient Sands in the Kenshi launcher

[b]Q: Does it work with Universal Wasteland Expansion?[/b]
A: Yes. The SSR Vanilla world template also describes the factions and the unique characters of [url=https://steamcommunity.com/sharedfiles/filedetails/?id=2142406806]Universal Wasteland Expansion[/url] by TreadLightly77. They apply only when that mod is installed

[b]Q: I loaded an older save, and NPCs remember things that did not happen yet![/b]
A: Press [b]Cull Future Data[/b] in the SSR HUB (F8). NPCs then forget what happened after your save. You cannot undo it. A campaign is not linked to a save, so choose the right campaign on the Campaigns tab before you load another playthrough

[b]Q: I want to modify SSR, how can I do this?[/b]
A: The source code for SSR can be found [url=https://github.com/equanimittyy/SentientSands-Rebirth]here[/url].

[b]Q: I found a bug. What do I do?[/b]
A: Please post in the Discussions tab with a description of the issue. Logs can be found in the [i]logs[/i] folder of the mod: [i]SentientSands_SDK.log[/i] and [i]server.log[/i]

[hr][/hr]

[i]If you enjoy this mod, please rate it up - it helps others find it![/i]
