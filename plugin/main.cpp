// Sentient Sands - Kenshi AI Mod
// Copyright (C) 2026 Sentient Sands Team
//
// This program is free software: you can redistribute it and/or modify
// it under the terms of the GNU General Public License as published by
// the Free Software Foundation, either version 3 of the License, or
// (at your option) any later version.
//
// This program is distributed in the hope that it will be useful,
// but WITHOUT ANY WARRANTY; without even the implied warranty of
// MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
// GNU General Public License for more details.
//
// You should have received a copy of the GNU General Public License
// along with this program.  If not, see <https://www.gnu.org/licenses/>.

#ifdef _WIN64
// Linker aliases to cover all common entry point names for Kenshi mod loaders.
// ?startPlugin@@YAXXZ is the C++ mangled name for void startPlugin(void)
#pragma comment(linker, "/export:?startPlugin@@YAXXZ=startPlugin")
#pragma comment(linker, "/export:Init=startPlugin")
#pragma comment(linker, "/export:DllInstall=startPlugin")
#endif

#include <cctype>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>
#include <windows.h>

#include "core/Comm.h"
#include "game/Context.h"
#include <core/Functions.h>
#include "game/GameActions.h"
#include "game/Probes.h"
#include "core/Globals.h"
#include "core/Utils.h"

#include <kenshi/Character.h>
#include <kenshi/Dialogue.h>
#include <kenshi/Faction.h>
#include <kenshi/GameData.h>
#include <kenshi/GameWorld.h>
#include <kenshi/Platoon.h>
#include <kenshi/PlayerInterface.h>
#include <kenshi/util/hand.h>

#include <kenshi/RootObject.h>

// A generic NPC whose template is a canon character carries the npc_id of that
// character, not the one that GetNpcId gives it
static bool HasNpcId(Character *c, const std::string &npcId) {
  if (npcId.compare(0, 2, "u:") == 0)
    return c->data && "u:" + c->data->stringID == npcId;
  return GetNpcId(c) == npcId;
}

// The game puts a name in place of the token of a template, such as Barman
// /GENNAME/, so a rename keeps the title and the text around the token
static std::string ShownName(Character *c, const std::string &name) {
  if (c->isUnique() || !c->data)
    return name;
  const std::string &tmpl = c->data->name;
  for (size_t open = tmpl.find('/'); open != std::string::npos;
       open = tmpl.find('/', open + 1)) {
    size_t close = open + 1;
    while (close < tmpl.size() && tmpl[close] >= 'A' && tmpl[close] <= 'Z')
      ++close;
    if (close > open + 1 && close < tmpl.size() && tmpl[close] == '/')
      return tmpl.substr(0, open) + name + tmpl.substr(close + 1);
  }
  return name;
}

void (*playerUpdate_orig)(PlayerInterface *) = nullptr;
void (*attackingYou_orig)(Character *, Character *, bool, bool) = nullptr;
void (*declareDead_orig)(Character *) = nullptr;
void (*setPrisonMode_orig)(Character *, bool, UseableStuff *) = nullptr;
void (*setProneState_orig)(Character *, ProneState) = nullptr;
void (*setName_orig)(Character *, const std::string &) = nullptr;
bool (*addActiveObject_orig)(ActivePlatoon *, RootObject *) = nullptr;
void (*addCharacterAt_orig)(ActivePlatoon *, RootObject *, int) = nullptr;
static std::vector<hand> g_renamedSquad;
static hand g_lastSelectionHand;
static hand g_lastChattingPlayerHand;
static HMODULE g_hModule = nullptr;
static DWORD g_lastRadiantTick = 0;
static bool g_welcomeShown = false;

#include <mygui/MyGUI_EditBox.h>
#include <mygui/MyGUI_Gui.h>
#include <mygui/MyGUI_InputManager.h>

#include "ui/ChatUI.h"

// The bubble strips every other tag, but the reply tag of an action dialogue
// stays, so the player sees which category the NPC answers in
static std::string LeadingCategoryTag(const std::string &text) {
  static const char *TAGS[] = {"[THREATEN]", "[BARTER]",  "[HEAL]",
                               "[LIBERATE]", "[RECRUIT]", "[FOLLOW]",
                               "[DISMISS]"};
  for (size_t i = 0; i < sizeof(TAGS) / sizeof(TAGS[0]); ++i) {
    std::string tag = TAGS[i];
    if (text.compare(0, tag.size(), tag) == 0)
      return tag;
  }
  return "";
}

static void ApplyConfig(const std::string &data) {
  size_t colon = data.find(':');
  if (colon == std::string::npos)
    return;
  std::string var = Trim(data.substr(0, colon));
  std::string val = Trim(data.substr(colon + 1));
  if (var == "g_enableRadiant") {
    g_enableRadiant = (val == "1");
    g_lastRadiantTick = GetTickCount();
  } else if (var == "g_radiantIntervalSeconds") {
    g_radiantIntervalSeconds = atoi(val.c_str());
    g_lastRadiantTick = GetTickCount();
  } else if (var == "g_whisperRadius") {
    g_whisperRadius = (float)atof(val.c_str());
  } else if (var == "g_proximityRadius") {
    g_proximityRadius = (float)atof(val.c_str());
  } else if (var == "g_yellRadius") {
    g_yellRadius = (float)atof(val.c_str());
  } else if (var == "g_speechBubbleLife") {
    g_speechBubbleLife = (float)atof(val.c_str());
  } else if (var == "g_chatHotkey") {
    SetHotkeyFromString(val);
    RefreshWelcomeUI();
    RefreshHelpUI();
  } else if (var == "g_enableWelcome") {
    g_enableWelcome = (val == "1");
  } else if (var == "g_logLevel") {
    g_logLevel = ParseLogLevel(val);
  }
}

// Restarts the interval on the reply, so a slow server does not shorten the
// gap between conversations
static void FinishRadiant(const std::string &data) {
  std::string tag, reply;
  if (!SplitTaggedReply(data, tag, reply))
    return;
  if (reply.empty()) {
    Log(LOG_WARN, "RADIANT: Empty response or timeout from server.");
    return;
  }
  g_lastRadiantTick = GetTickCount();
  Log(LOG_INFO,
      "RADIANT: Server answered " + GetJsonValue(reply, "status") + ".");
}

// "<command>: <data>". The data stays untrimmed, because a multi-line block in
// it must arrive as sent
static void HandleCommand(const std::string &message) {
  size_t colon = message.find(':');
  if (colon == std::string::npos)
    return;
  std::string command = Trim(message.substr(0, colon));
  std::string data = message.substr(colon + 1);
  if (command == "APPLY_TRANSLATION") {
    LoadUITranslation(data);
    RefreshLauncherUI();
    RefreshWelcomeUI();
    RefreshHelpUI();
  } else if (command == "POPULATE_LIBRARY") {
    PopulateLibraryUI(data);
  } else if (command == "SET_LIBRARY_PROFILE") {
    SetLibraryProfile(data);
  } else if (command == "SET_EVENTS_TEXT") {
    SetEventContent(data);
  } else if (command == "SET_CONFIG") {
    ApplyConfig(data);
  } else if (command == "REFRESH_LIBRARY") {
    RefreshLibraryUI();
  } else if (command == "REPORT") {
    AsyncPostToPython(L"/report", GameReport());
  } else if (command == "BIO_WRITTEN") {
    OpenBioEditor(data, "Write failed: ");
  } else if (command == "BIO_READ") {
    OpenBioEditor(data, "Load failed: ");
  } else if (command == "BIO_KEPT") {
    FinishKeptBio(data);
  } else if (command == "POPULATE_EVENTS") {
    PopulateEventsUI(data);
  } else if (command == "RUMOR_WRITTEN") {
    OpenRumorEditor(data, "Write failed: ");
  } else if (command == "RUMOR_READ") {
    OpenRumorEditor(data, "Load failed: ");
  } else if (command == "RUMOR_KEPT") {
    FinishEventChange(data, "Keep failed: ");
  } else if (command == "EVENT_ADDED") {
    FinishEventChange(data, "Add failed: ");
  } else if (command == "EVENT_DELETED") {
    FinishEventChange(data, "Delete failed: ");
  } else if (command == "POPULATE_JOURNAL") {
    PopulateJournalUI(data);
  } else if (command == "JOURNAL_ENTRY") {
    SetJournalEntry(data);
  } else if (command == "JOURNAL_ADDED") {
    FinishJournalAdd(data);
  } else if (command == "JOURNAL_SAVED") {
    FinishJournalSave(data);
  } else if (command == "JOURNAL_DELETED") {
    FinishJournalDelete(data);
  } else if (command == "OFFER") {
    ShowOfferUI(data);
  } else if (command == "OFFER_GONE") {
    DropOfferUI();
  } else if (command == "HIRE_TERMS") {
    SetHireTerms(data);
  } else if (command == "CHAT_HISTORY") {
    SetChatHistory(data);
  } else if (command == "BARTER_TURN") {
    SetBarterTurn(data);
  } else if (command == "CHEAT_RELATION") {
    SetCheatRelation(data);
  } else if (command == "CULLED") {
    FinishCull(data);
  } else if (command == "RADIANT_DONE") {
    FinishRadiant(data);
  }
}

// "<npc_id>|<name>"
static void RenameNpc(GameWorld *world, const std::string &payload) {
  size_t sep = payload.find('|');
  if (sep == std::string::npos || sep + 1 >= payload.size())
    return;
  std::string npcId = payload.substr(0, sep);
  std::string name = payload.substr(sep + 1);
  const ogre_unordered_set<Character *>::type &chars =
      world->getCharacterUpdateList();
  for (auto it = chars.begin(); it != chars.end(); ++it) {
    Character *c = *it;
    if (!c || (uintptr_t)c <= 0x1000 || !HasNpcId(c, npcId))
      continue;
    std::string newName = ShownName(c, name);
    std::string oldName = c->getName();
    if (newName != oldName) {
      c->setName(newName);
      Log(LOG_DEBUG, "NAME: Renamed '" + oldName + "' -> '" + newName +
                         "' (" + npcId + ")");
    }
    return;
  }
}

static bool TakePrefix(const std::string &text, const char *prefix,
                       std::string &rest) {
  size_t length = strlen(prefix);
  if (text.compare(0, length, prefix) != 0)
    return false;
  rest = text.substr(length);
  return true;
}

// A colon past this ends no name, because it is part of the line
static const size_t SPEAKER_NAME_MAX = 64;

// "<name>: <text>" names the squad member that speaks, else the first one
// speaks
static hand TakePlayerSpeaker(GameWorld *world, std::string &text) {
  Character *first = FirstPlayerCharacter();
  if (!first)
    return hand();
  hand speaker = first->getHandle();
  size_t nameEnd = text.find(':');
  if (nameEnd != std::string::npos && nameEnd < SPEAKER_NAME_MAX) {
    std::string name = Trim(text.substr(0, nameEnd));
    lektor<Character *> &members = world->player->playerCharacters;
    for (uint32_t i = 0; i < members.size(); ++i) {
      if (members[i] && members[i]->getName() == name) {
        speaker = members[i]->getHandle();
        text = text.substr(nameEnd + 1);
        text.erase(0, text.find_first_not_of(" \t\r\n"));
        break;
      }
    }
  }
  g_lastChattingPlayerHand = speaker;
  return speaker;
}

static int NameScore(Character *c, const std::string &name,
                     const std::string &lowName) {
  std::string cName = c->getName();
  if (cName == name)
    return 500;
  std::string cLow = Lower(cName);
  if (cLow == lowName)
    return 400;
  size_t at = cLow.find(lowName);
  return at == 0 ? 200 : at != std::string::npos ? 100 : 0;
}

static Character *BestNameMatch(Character *best, int &bestScore,
                                Character *c, const std::string &name,
                                const std::string &lowName) {
  if (!c || (uintptr_t)c < 0x1000)
    return best;
  int score = NameScore(c, name, lowName);
  if (score <= bestScore)
    return best;
  bestScore = score;
  return c;
}

// The key finds the character, and the name only when the key finds none:
// first among the characters that the game updates, then near the squad
static Character *FindSpeaker(GameWorld *world, const std::string &name,
                              unsigned int key) {
  Character *best = KeyedCharacter(key);
  if (best)
    return best;
  std::string lowName = Lower(name);
  int bestScore = 0;
  const ogre_unordered_set<Character *>::type &chars =
      world->getCharacterUpdateList();
  for (auto it = chars.begin(); it != chars.end(); ++it)
    best = BestNameMatch(best, bestScore, *it, name, lowName);
  Character *first = FirstPlayerCharacter();
  if (best || !first)
    return best;
  lektor<RootObject *> results;
  world->getCharactersWithinSphere(results, first->getPosition(), 2500.0f,
                                   0.0f, 0.0f, 0x10, 0, first);
  for (uint32_t i = 0; i < results.size(); ++i)
    best = BestNameMatch(best, bestScore, (Character *)results.stuff[i], name,
                         lowName);
  if (best)
    Log(LOG_INFO, "SPEAKER: Only the 2500-unit search found " +
                      best->getName() + " for the name '" + name + "'");
  return best;
}

// Strips the "<name>|<key>><speaker key>:" header of a reply line and points
// target at its character. A line whose speaker no search finds stays on the
// chat target
static std::string TakeSpeaker(GameWorld *world, const std::string &line,
                               hand &target, hand &actionSpeaker) {
  size_t colon = line.find(':');
  if (colon == std::string::npos || colon >= SPEAKER_NAME_MAX ||
      line[0] == '[')
    return line;
  std::string header = line.substr(0, colon);
  size_t bar = header.find('|');
  std::string name = header.substr(0, bar);
  unsigned int key = 0;
  if (bar != std::string::npos) {
    char *rest = NULL;
    key = (unsigned int)strtoul(header.c_str() + bar + 1, &rest, 10);
    Character *spoke =
        rest && *rest == '>'
            ? KeyedCharacter((unsigned int)strtoul(rest + 1, NULL, 10))
            : nullptr;
    if (spoke)
      actionSpeaker = spoke->getHandle();
  }
  Character *speaker = FindSpeaker(world, name, key);
  if (speaker) {
    target = speaker->getHandle();
  } else if (!target.isValid()) {
    Log(LOG_WARN, "QUEUE: Speaker not found: " + name);
    return line;
  }
  std::string text = line.substr(colon + 1);
  return text.compare(0, 1, " ") == 0 ? text.substr(1) : text;
}

// The ']' that closes the '[' at open, or npos
static size_t ClosingBracket(const std::string &text, size_t open) {
  int depth = 0;
  for (size_t i = open; i < text.length(); ++i) {
    if (text[i] == '[')
      depth++;
    else if (text[i] == ']' && --depth == 0)
      return i;
  }
  return std::string::npos;
}

static std::string TagPayload(const std::string &tag, const char *prefix) {
  size_t at = tag.find(prefix);
  if (at == std::string::npos)
    return "";
  std::string payload = Trim(tag.substr(at + strlen(prefix)));
  if (!payload.empty() && payload[payload.size() - 1] == ']')
    payload.erase(payload.size() - 1);
  return Trim(payload);
}

// "<name>: <count>", where only the last colon outside brackets ends the name
static int TakeCount(std::string &payload) {
  int depth = 0;
  for (int i = (int)payload.length() - 1; i >= 0; --i) {
    if (payload[i] == ']') {
      depth++;
    } else if (payload[i] == '[') {
      depth--;
    } else if (payload[i] == ':' && depth == 0) {
      std::string count = Trim(payload.substr(i + 1), " ");
      if (count.empty() || !isdigit((unsigned char)count[0]))
        return 1;
      payload = Trim(payload.substr(0, i), " ");
      return atoi(count.c_str());
    }
  }
  return 1;
}

static bool Has(const std::string &tag, const char *name) {
  return tag.find(name) != std::string::npos;
}

// The tags match by substring, so EXPIRE_HIRE and END_HIRE come before HIRE
static void QueueTagAction(const std::string &tag, const hand &npc,
                           const hand &actionSpeaker) {
  Character *first = FirstPlayerCharacter();
  hand itemHolder =
      actionSpeaker.isValid() ? actionSpeaker : g_lastChattingPlayerHand;
  hand actionTarget = actionSpeaker.isValid() ? actionSpeaker
                      : first                 ? first->getHandle()
                                              : hand();
  if (Has(tag, "PROBE:")) {
    QueueAction(ACT_PROBE, npc, g_lastChattingPlayerHand,
                TagPayload(tag, "PROBE:"));
  } else if (Has(tag, "JOIN_PARTY")) {
    QueueAction(ACT_JOIN_PARTY, npc, hand(), "",
                atoi(TagPayload(tag, "JOIN_PARTY:").c_str()));
  } else if (Has(tag, "EXPIRE_HIRE")) {
    Character *c = npc.getCharacter();
    if (c)
      ExpireHire(c);
  } else if (Has(tag, "END_HIRE")) {
    QueueAction(ACT_END_HIRE, npc);
  } else if (Has(tag, "HIRE:")) {
    QueueAction(ACT_HIRE, npc, actionTarget, "",
                atoi(TagPayload(tag, "HIRE:").c_str()));
  } else if (Has(tag, "FIRST_AID")) {
    QueueAction(ACT_FIRST_AID, npc, actionTarget);
  } else if (Has(tag, "ATTACK")) {
    QueueAction(ACT_ATTACK, npc, actionTarget);
  } else if (Has(tag, "GIVE_ITEM:") || Has(tag, "SELL_ITEM:")) {
    bool sell = Has(tag, "SELL_ITEM:");
    std::string payload = TagPayload(tag, sell ? "SELL_ITEM:" : "GIVE_ITEM:");
    int count = TakeCount(payload);
    QueueAction(sell ? ACT_SELL_ITEM : ACT_GIVE_ITEM, npc, itemHolder, payload,
                count);
  } else if (Has(tag, "TAKE_ITEM:")) {
    std::string payload = TagPayload(tag, "TAKE_ITEM:");
    int count = TakeCount(payload);
    QueueAction(ACT_TAKE_ITEM, npc, itemHolder, payload, count);
  } else if (Has(tag, "ADD_CATS:")) {
    QueueAction(ACT_ADD_CATS, npc, hand(), "",
                atoi(TagPayload(tag, "ADD_CATS:").c_str()));
  } else if (Has(tag, "TAKE_CATS:")) {
    QueueAction(ACT_TAKE_CATS, npc, hand(), "",
                atoi(TagPayload(tag, "TAKE_CATS:").c_str()));
  } else if (Has(tag, "GIVE_CATS:")) {
    QueueAction(ACT_GIVE_CATS, npc, hand(), "",
                atoi(TagPayload(tag, "GIVE_CATS:").c_str()));
  } else if (Has(tag, "SPAWN_ITEM:")) {
    std::string payload = TagPayload(tag, "SPAWN_ITEM:");
    size_t bar = payload.find('|');
    std::string name = payload.substr(0, bar);
    int count = TakeCount(name);
    QueueAction(ACT_SPAWN_ITEM, npc, itemHolder,
                bar == std::string::npos ? name : name + payload.substr(bar),
                count);
  } else if (Has(tag, "RELEASE_PRISONER") || Has(tag, "FREE_PLAYER")) {
    QueueAction(ACT_RELEASE, npc, actionTarget);
  } else if (Has(tag, "RAID_TOWN")) {
    QueueAction(ACT_SET_TASK, npc, hand(), TagPayload(tag, "RAID_TOWN:"),
                RAID_TOWN);
  } else if (Has(tag, "TRAVEL_TO_TARGET_TOWN")) {
    QueueAction(ACT_SET_TASK, npc, hand(),
                TagPayload(tag, "TRAVEL_TO_TARGET_TOWN:"),
                TRAVEL_TO_TARGET_TOWN);
  }
}

static void QueueTagActions(const std::string &text, const hand &npc,
                            const hand &actionSpeaker) {
  for (size_t open = text.find('['); open != std::string::npos;
       open = text.find('[', open)) {
    size_t close = ClosingBracket(text, open);
    if (close == std::string::npos)
      break;
    QueueTagAction(text.substr(open, close - open + 1), npc, actionSpeaker);
    open = close + 1;
  }
}

static std::string StripTags(std::string text) {
  for (size_t open = text.find('['); open != std::string::npos;
       open = text.find('[', open)) {
    size_t close = ClosingBracket(text, open);
    text.erase(open, close == std::string::npos ? std::string::npos
                                                : close - open + 1);
  }
  return Trim(text);
}

static std::string NpcBubble(const std::string &text, bool said) {
  if (said && text.compare(0, 7, "[DEBUG]") == 0)
    return "";
  std::string categoryTag = said ? LeadingCategoryTag(text) : "";
  std::string bubble = StripTags(text.substr(categoryTag.size()));
  return categoryTag.empty() || bubble.empty() ? bubble
                                               : categoryTag + " " + bubble;
}

static void ProcessMessage(GameWorld *world, const std::string &msg) {
  if (LogEnabled(LOG_DEBUG))
    Log(LOG_DEBUG, "QUEUE: Processing: " + msg);
  std::string text;
  if (TakePrefix(msg, "CMD:", text)) {
    HandleCommand(text);
    return;
  }
  if (TakePrefix(msg, "NPC_RENAME: ", text)) {
    RenameNpc(world, text);
    return;
  }
  if (TakePrefix(msg, "NOTIFY:", text)) {
    QueueAction(ACT_NOTIFY, hand(), hand(), text);
    return;
  }
  bool playerSay = TakePrefix(msg, "PLAYER_SAY: ", text);
  bool npcSay = !playerSay && TakePrefix(msg, "NPC_SAY: ", text);
  if (!playerSay && !npcSay && !TakePrefix(msg, "NPC_ACTION: ", text))
    return;
  g_lastRadiantTick = GetTickCount();

  hand anchor;
  std::string bubble;
  if (playerSay) {
    anchor = TakePlayerSpeaker(world, text);
    bubble = text.compare(0, 1, "/") == 0 ? "" : text;
  } else {
    anchor = g_talkTargetHand.isValid() ? g_talkTargetHand : g_lastSelectionHand;
    hand actionSpeaker;
    text = TakeSpeaker(world, text, anchor, actionSpeaker);
    QueueTagActions(text, anchor, actionSpeaker);
    // A line that runs an action still shows its bubble
    bubble = NpcBubble(text, npcSay);
  }
  if (bubble.empty() || !anchor.isValid())
    return;
  Character *c = anchor.getCharacter();
  Log(LOG_DEBUG, "QUEUE: Queuing SAY for " + (c ? c->getName() : "Unknown") +
                     ": " + bubble);
  QueueAction(ACT_SAY, anchor, hand(), bubble);
}

// Kenshi engine writes must happen on the main thread, inside hooks.
static void ProcessMessageQueue(GameWorld *thisptr) {
  std::deque<std::string> messages;
  if (!TryEnterCriticalSection(&g_msgMutex))
    return;
  // Swapped out, so the pipe thread can queue the next message while the game
  // thread runs these
  messages.swap(g_messageQueue);
  LeaveCriticalSection(&g_msgMutex);
  for (size_t i = 0; i < messages.size(); ++i)
    ProcessMessage(thisptr, messages[i]);
}

static void attackingYou_hook(Character *npc, Character *attacker, bool so,
                       bool doAwarenessCheck) {
  // The hook runs many times a second for each attacker, so the faction check
  // comes first, and the handle serials find an attack that already waits
  // without building a string
  Faction *faction = attacker && npc ? attacker->getFaction() : nullptr;
  if (faction && (uintptr_t)faction > 0x1000 && faction->isThePlayer()) {
    unsigned long long attack =
        (unsigned long long)attacker->getHandle().serial << 32 |
        npc->getHandle().serial;
    if (!AttackWaits(attack))
      QueueGameEvent("attack",
                     "\"attacker\": " + EventParty(attacker) +
                         ", \"target\": \"" + EscapeJSON(GetNpcId(npc)) +
                         "\"",
                     attack);
  }
  if (attackingYou_orig)
    attackingYou_orig(npc, attacker, so, doAwarenessCheck);
}

static void declareDead_hook(Character *npc) {
  if (npc)
    QueueGameEvent("death", "\"party\": " + EventParty(npc));
  if (declareDead_orig)
    declareDead_orig(npc);
}

static void setPrisonMode_hook(Character *npc, bool on, UseableStuff *h) {
  if (npc && on)
    QueueGameEvent("imprisonment", "\"party\": " + EventParty(npc));
  if (setPrisonMode_orig)
    setPrisonMode_orig(npc, on, h);
}

static void setProneState_hook(Character *npc, ProneState p) {
  // The hook runs about 10 times a second while a character lies knocked out,
  // so only a change of the knockout makes an event
  bool down = npc && npc->getProneState() == PS_KO;
  if (npc && (p == PS_KO) != down) {
    std::string id = "\"id\": \"" + EscapeJSON(GetNpcId(npc)) + "\"";
    if (down)
      QueueGameEvent("up", id + ", \"carried\": " +
                               (npc->isBeingCarried() ? "true" : "false"));
    else
      QueueGameEvent("knockout", id);
  }
  if (setProneState_orig)
    setProneState_orig(npc, p);
}

// The frame hook sends the context, because a rename can come in the middle of
// a game update
static void setName_hook(Character *c, const std::string &name) {
  std::string old = c ? c->getName() : std::string();
  if (setName_orig)
    setName_orig(c, name);
  if (!c || old == name)
    return;
  Faction *faction = c->getFaction();
  if (faction && faction->isThePlayer()) {
    Log(LOG_INFO, "NAME: '" + old + "' is now '" + name + "' in game");
    EnterCriticalSection(&g_stateMutex);
    g_renamedSquad.push_back(c->getHandle());
    LeaveCriticalSection(&g_stateMutex);
  }
}

// A C-style cast checks nothing, so the data type tells a character apart
static Character *AsCharacter(RootObject *o) {
  return o && o->getDataType() == CHARACTER ? (Character *)o : nullptr;
}

// A recruit and a leave add the character with addActiveObject, and a move
// between the player's squads with addCharacterAt
static bool addActiveObject_hook(ActivePlatoon *p, RootObject *o) {
  Character *c = AsCharacter(o);
  hand before = c ? c->getHandle() : hand();
  bool added = addActiveObject_orig ? addActiveObject_orig(p, o) : false;
  RekeyCharacter(c, before);
  return added;
}

static void addCharacterAt_hook(ActivePlatoon *p, RootObject *o, int index) {
  Character *c = AsCharacter(o);
  hand before = c ? c->getHandle() : hand();
  if (addCharacterAt_orig)
    addCharacterAt_orig(p, o, index);
  RekeyCharacter(c, before);
}

static std::string RadiantJson(const std::vector<Character *> &characters) {
  std::string json = "[";
  for (size_t i = 0; i < characters.size(); ++i) {
    Character *other = characters[i];
    LogNpcRole(other);
    ActivePlatoon *active = other->getPlatoon();
    json += std::string(i ? "," : "") + "{" + PartyFields(other) +
            ", \"squad\": \"" +
            EscapeJSON(active && active->me ? active->me->getHandle().toString()
                                            : std::string()) +
            "\", \"equipment\": \"" + EscapeJSON(GetVisibleEquipment(other)) +
            "\", \"faction\": \"" + EscapeJSON(GetIdentityFaction(other)) +
            "\"}";
  }
  return json + "]";
}

static void playerUpdate_hook(PlayerInterface *thisptr) {
  if (playerUpdate_orig)
    playerUpdate_orig(thisptr);

  // The main menu runs this hook too, but with no player characters
  if (!g_welcomeShown && MyGUI::Gui::getInstancePtr() &&
      thisptr->getAllPlayerCharacters().size() > 0) {
    if (g_enableWelcome) {
      CreateWelcomeUI();
      CreateLauncherUI();
    }
    StartThread(WelcomeResponseThread, NULL);
    g_welcomeShown = true;
  }

  Character *sel = thisptr->selectedObject.getCharacter();
  if (!sel)
    sel = thisptr->selectedCharacter.getCharacter();

  g_lastSelectionHand =
      sel && (uintptr_t)sel > 0x1000 ? sel->getHandle() : hand();
  std::vector<hand> renamed;
  EnterCriticalSection(&g_stateMutex);
  renamed.swap(g_renamedSquad);
  LeaveCriticalSection(&g_stateMutex);

  // Driven from playerUpdate because it keeps ticking while the game is paused.
  GameWorld *world = *ppWorld;
  if (world) {
    ProcessMessageQueue(world);
    ExecuteQueuedActions(world);
    WatchOffer();
    WatchHires(world);
    WatchActions(world);

    for (size_t i = 0; i < renamed.size(); ++i) {
      Character *c = renamed[i].getCharacter();
      if (c)
        AsyncPostToPython(L"/squad_rename", GetDetailedContext(c));
    }

    if (ReportDue())
      AsyncPostToPython(L"/report", GameReport());

    DWORD now = GetTickCount();

    static DWORD lastFrameTickForRadiant = GetTickCount();
    DWORD deltaTick = now >= lastFrameTickForRadiant ? (now - lastFrameTickForRadiant) : 0;
    lastFrameTickForRadiant = now;

    if (g_enableRadiant) {
      float currentSpeed = world->getFrameSpeedMultiplier();
      
      // Shift the timer so paused time does not count toward the radiant interval.
      if (currentSpeed <= 0.1f || world->isPaused()) {
          g_lastRadiantTick += deltaTick;
      } else {
        if (g_triggerRadiant || (now - g_lastRadiantTick >
                                 (DWORD)(g_radiantIntervalSeconds * 1000))) {
          g_triggerRadiant = false;
          g_lastRadiantTick = now;

          std::vector<Character *> squad, npcs;
          GetRadiantParticipants(sel, squad);
          Character *center = squad.empty() ? nullptr : squad[0];
          GetRadiantNpcs(center, npcs);
          if (squad.size() < 3)
            squad.clear();
          if (!squad.empty() || !npcs.empty()) {
            Log(LOG_DEBUG, "RADIANT: Sending request to server...");
            PostForGameThread(
                L"/radiant",
                "{\"participants\": " + RadiantJson(squad) +
                    ", \"npcs\": " + RadiantJson(npcs) +
                    ", \"player_context\": " +
                    GetDetailedContext(center, "player") +
                    ", \"events\": " + TakeGameEvents() +
                    ", \"changed_towns\": " + ChangedTowns() + "}",
                "RADIANT_DONE", "");
          }
        }
      }
    }
  }

  // The hotkey is polled from the keyboard, so it would fire while the player
  // types its key into a text box
  MyGUI::InputManager *input = MyGUI::InputManager::getInstancePtr();
  MyGUI::Widget *keyFocus = input ? input->getKeyFocusWidget() : nullptr;
  bool typing = keyFocus && keyFocus->isType<MyGUI::EditBox>();

  static hand lastNpc;
  static hand lastPick;
  hand pick = sel && (uintptr_t)sel > 0x1000 ? sel->getHandle() : hand();
  if (sel && (uintptr_t)sel > 0x1000 && !InPlayerFaction(sel)) {
    // Each frame sees the NPC that stays selected, which would undo the button
    if (pick != lastPick)
      ForgetChatTarget();
    lastNpc = pick;
  }
  lastPick = pick;

  // Only a change moves the speaker, so the speaker button still cycles
  static hand lastSelected;
  if (thisptr->selectedCharacter != lastSelected) {
    lastSelected = thisptr->selectedCharacter;
    SelectChatSpeaker(lastSelected);
  }

  if (!typing && (GetAsyncKeyState(g_chatHotkey) & 0x8000) && !g_chatWindow &&
      !g_libraryWindow && !g_barterWindow) {
    static DWORD lastTalkTick = 0;
    if (GetTickCount() - lastTalkTick > 500) {
      lastTalkTick = GetTickCount();
      Character *npc = lastNpc.getCharacter();
      if (npc && InPlayerFaction(npc))
        npc = nullptr;
      // End vanilla dialogue, or it runs alongside the AI chat ("double dialogue").
      if (npc && npc->dialogue && (uintptr_t)npc->dialogue > 0x1000) {
        npc->dialogue->endDialogue(true);
        npc->dialogue->setInDialog(false);
      }
      CreateChatUI(npc);
    }
  }

  if ((GetAsyncKeyState(VK_F8) & 0x8000)) {
    static DWORD lastLaunchTick = 0;
    if (GetTickCount() - lastLaunchTick > 500) {
      lastLaunchTick = GetTickCount();
      CreateLauncherUI();
    }
  }
}

// StartPythonServer can block on system(), so it runs off the game thread
static DWORD WINAPI ServerThread(LPVOID lpParam) {
  StartPythonServer(g_openWebPanelOnStart);
  return 0;
}

// A missing export leaves the events of its hook silent, so it logs
static void Hook(HMODULE lib, const char *symbol, void *detour,
                 void **original) {
  void *thunk = (void *)GetProcAddress(lib, symbol);
  if (!thunk) {
    Log(LOG_WARN, std::string("SYSTEM: KenshiLib exports no ") + symbol);
    return;
  }
  KenshiLib::AddHook((void *)KenshiLib::GetRealAddress(thunk), detour,
                     original);
}

static bool g_pluginStarted = false;

extern "C" __declspec(dllexport) void startPlugin() {
  if (g_pluginStarted)
    return;
  g_pluginStarted = true;
  // Initialize mutexes first — Log() requires g_LogMutex to be ready.
  InitializeCriticalSection(&g_LogMutex);
  InitializeCriticalSection(&g_msgMutex);
  InitializeCriticalSection(&g_uiMutex);
  InitializeCriticalSection(&g_stateMutex);
  InitializeCriticalSection(&g_eventMutex);
  g_mainThreadId = GetCurrentThreadId();

  // Derive the mod root from the DLL path so Steam Workshop numeric-ID folders work too.
  if (g_modRoot.empty()) {
    char dllPath[MAX_PATH] = {};
    GetModuleFileNameA(g_hModule, dllPath, MAX_PATH);
    std::string p = dllPath;
    size_t slash = p.find_last_of("\\/");
    g_modRoot = (slash != std::string::npos) ? p.substr(0, slash) : p;
  }
  Log(LOG_INFO, "SYSTEM: Mod root resolved to: " + g_modRoot);

  // Before the hooks, so that no hook runs without the world or the settings
  HMODULE hLib = GetModuleHandleA("KenshiLib.dll");
  ppWorld = (GameWorld **)GetProcAddress(hLib, "?ou@@3PEAVGameWorld@@EA");
  ppSharedKing =
      (SharedKing **)GetProcAddress(hLib, "?shou@@3PEAVSharedKing@@EA");
  if (!ppWorld) {
    Log(LOG_ERROR, "SYSTEM: KenshiLib exports no game world, so SSR stays off");
    return;
  }
  LoadPluginConfig();

  Hook(hLib, "?update@PlayerInterface@@QEAAXXZ", (void *)playerUpdate_hook,
       (void **)&playerUpdate_orig);
  Hook(hLib, "?attackingYou@Character@@QEAAXPEAV1@_N1@Z",
       (void *)attackingYou_hook, (void **)&attackingYou_orig);
  Hook(hLib, "?declareDead@Character@@QEAAXXZ", (void *)declareDead_hook,
       (void **)&declareDead_orig);
  Hook(hLib, "?setPrisonMode@Character@@QEAAX_NPEAVUseableStuff@@@Z",
       (void *)setPrisonMode_hook, (void **)&setPrisonMode_orig);
  Hook(hLib, "?setProneState@Character@@UEAAXW4ProneState@@@Z",
       (void *)setProneState_hook, (void **)&setProneState_orig);
  Hook(hLib,
       "?_NV_setName@Character@@QEAAXAEBV?$basic_string@DU?$char_traits@D@"
       "std@@V?$allocator@D@2@@std@@@Z",
       (void *)setName_hook, (void **)&setName_orig);
  Hook(hLib, "?_NV_addActiveObject@ActivePlatoon@@QEAA_NPEAVRootObject@@@Z",
       (void *)addActiveObject_hook, (void **)&addActiveObject_orig);
  Hook(hLib, "?addCharacterAt@ActivePlatoon@@QEAAXPEAVRootObject@@H@Z",
       (void *)addCharacterAt_hook, (void **)&addCharacterAt_orig);

  StartThread(PipeThread, NULL);
  StartThread(ServerThread, NULL);
}

BOOL APIENTRY DllMain(HMODULE hModule, DWORD ul_reason_for_call,
                      LPVOID lpReserved) {
  if (ul_reason_for_call == DLL_PROCESS_ATTACH)
    g_hModule = hModule;
  return TRUE;
}
