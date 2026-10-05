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

#include <string>
#include <vector>
#include <windows.h>

#include "core/Comm.h"
#include "game/Context.h"
#include <core/Functions.h>
#include "game/GameActions.h"
#include "core/Globals.h"
#include "core/Utils.h"

#include <kenshi/CharStats.h>
#include <kenshi/Character.h>
#include <kenshi/Dialogue.h>
#include <kenshi/Faction.h>
#include <kenshi/GameData.h>
#include <kenshi/GameWorld.h>
#include <kenshi/Kenshi.h>
#include <kenshi/Platoon.h>
#include <kenshi/PlayerInterface.h>
#include <kenshi/util/hand.h>

#include <kenshi/RaceData.h>
#include <kenshi/RootObject.h>
#include <kenshi/RootObjectBase.h>
#include <kenshi/WorldEventStateQuery.h>

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
static std::vector<hand> g_renamedSquad;

#include <mygui/MyGUI_Button.h>
#include <mygui/MyGUI_Delegate.h>
#include <mygui/MyGUI_EditBox.h>
#include <mygui/MyGUI_Gui.h>
#include <mygui/MyGUI_InputManager.h>
#include <mygui/MyGUI_TextBox.h>
#include <mygui/MyGUI_Window.h>

#include "ui/ChatUI.h"

// Kenshi engine writes must happen on the main thread, inside hooks.
void ProcessMessageQueue(GameWorld *thisptr) {
  if (TryEnterCriticalSection(&g_msgMutex)) {
    while (!g_messageQueue.empty()) {
      std::string msg = g_messageQueue.front();
      g_messageQueue.pop_front();
      if (LogEnabled(LOG_DEBUG))
        Log(LOG_DEBUG, "QUEUE: Processing: " + msg);

      bool isNPCAction = (msg.find("NPC_ACTION: ") == 0);
      bool isPlayerSay = (msg.find("PLAYER_SAY: ") == 0);
      bool isNPCSay = (msg.find("NPC_SAY: ") == 0);
      bool isNotify = (msg.find("NOTIFY:") == 0);
      bool isCmd = (msg.find("CMD:") == 0);
      bool isRename = (msg.find("NPC_RENAME: ") == 0);

      hand targetHand = g_talkTargetHand;
      hand speakerHand = hand();

      if (isCmd) {
        size_t firstColon = msg.find(":", 4); // skip "CMD:"
        if (firstColon != std::string::npos) {
          std::string command = msg.substr(4, firstColon - 4);
          std::string data = msg.substr(firstColon + 1);

          auto trim = [](std::string &s) {
            s.erase(0, s.find_first_not_of(" \t\r\n"));
            s.erase(s.find_last_not_of(" \t\r\n") + 1);
          };
          trim(command);
          // Leave data untrimmed: multiline blocks in it must arrive exactly as sent.

          if (command == "APPLY_TRANSLATION") {
            LoadUITranslation(data);
            RefreshLauncherUI();
            RefreshWelcomeUI();
          } else if (command == "POPULATE_LIBRARY") {
            PopulateLibraryUI(data);
          } else if (command == "SET_LIBRARY_TEXT") {
            SetLibraryText(data);
          } else if (command == "SET_EVENTS_TEXT") {
            SetEventsText(data);
          } else if (command == "SET_CONFIG") {
            size_t colon = data.find(":");
            if (colon != std::string::npos) {
              std::string var = data.substr(0, colon);
              std::string val = data.substr(colon + 1);

              auto trimInternal = [](std::string &s) {
                s.erase(0, s.find_first_not_of(" \t\r\n"));
                s.erase(s.find_last_not_of(" \t\r\n") + 1);
              };
              trimInternal(var);
              trimInternal(val);

              if (var == "g_enableAmbient") {
                g_enableAmbient = (val == "1");
                g_lastAmbientTick = GetTickCount();
              } else if (var == "g_ambientIntervalSeconds") {
                g_ambientIntervalSeconds = atoi(val.c_str());
                g_lastAmbientTick =
                    GetTickCount();
              } else if (var == "g_proximityRadius")
                g_proximityRadius = (float)atof(val.c_str());
              else if (var == "g_radiantRange")
                g_radiantRange = (float)atof(val.c_str());
              else if (var == "g_yellRadius")
                g_yellRadius = (float)atof(val.c_str());
              else if (var == "g_dialogueSpeedSeconds") {
                g_dialogueSpeedSeconds = atoi(val.c_str());
                g_lastDialogueTick =
                    GetTickCount();
              } else if (var == "g_speechBubbleLife") {
                g_speechBubbleLife = (float)atof(val.c_str());
              } else if (var == "g_chatHotkey") {
                SetHotkeyFromString(val);
                RefreshWelcomeUI();
              } else if (var == "g_enableWelcome") {
                g_enableWelcome = (val == "1");
              } else if (var == "g_logLevel") {
                g_logLevel = ParseLogLevel(val);
              }
            }
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
          }
        }
      } else if (isRename) {
        // Format: "NPC_RENAME: <npc_id>|<name>"
        std::string payload = msg.substr(12); // skip "NPC_RENAME: "
        size_t sep = payload.find('|');
        if (sep != std::string::npos && sep + 1 < payload.size() && thisptr) {
          std::string npcId = payload.substr(0, sep);
          std::string name = payload.substr(sep + 1);
          const ogre_unordered_set<Character *>::type &chars =
              thisptr->getCharacterUpdateList();
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
            break;
          }
        }
      } else if (isNotify) {
        std::string text = msg.substr(7);
        EnterCriticalSection(&g_uiMutex);
        QueuedAction act;
        act.type = ACT_NOTIFY;
        act.actor = hand();
        act.target = hand();
        act.message = text;
        act.taskValue = 0;
        g_uiActionQueue.push_back(act);
        LeaveCriticalSection(&g_uiMutex);
      } else if (isPlayerSay || isNPCAction || isNPCSay) {
        g_lastAmbientTick = GetTickCount();

        if (isPlayerSay) {
          if (thisptr->player && thisptr->player->playerCharacters.size() > 0) {

            speakerHand = thisptr->player->playerCharacters[0]->getHandle();
            g_lastChattingPlayerHand = speakerHand;

            size_t nameStart = 12; // length of "PLAYER_SAY: "
            size_t nameEnd = msg.find(":", nameStart);
            if (nameEnd != std::string::npos && nameEnd < 64) {
              std::string pName = msg.substr(nameStart, nameEnd - nameStart);
              pName.erase(0, pName.find_first_not_of(" \t\r\n"));
              pName.erase(pName.find_last_not_of(" \t\r\n") + 1);

              bool nameMatched = false;
              for (size_t ci = 0; ci < thisptr->player->playerCharacters.size();
                   ++ci) {
                Character *c = thisptr->player->playerCharacters[ci];
                if (c && c->getName() == pName) {
                  speakerHand = c->getHandle();
                  g_lastChattingPlayerHand = speakerHand;
                  nameMatched = true;
                  break;
                }
              }

              if (nameMatched) {
                std::string textOnly = msg.substr(nameEnd + 1);
                textOnly.erase(0, textOnly.find_first_not_of(" \t\r\n"));
                msg = "PLAYER_SAY: " + textOnly;
              }
            }
          }
        }

        if (!targetHand.isValid()) {
          targetHand = g_lastSelectionHand;
        }

        bool found = false;
        bool header_processed = false;

        if (isNPCSay || isNPCAction) {
          hand fallbackHand = targetHand;
          // Do not reset targetHand here: that kills bubbles for single-target talk.

          size_t startPos = isNPCSay ? 9 : 12;
          std::string remainder = msg.substr(startPos);
          size_t colon = remainder.find(':');

          std::string name = "";
          unsigned int tSerial = 0;

          if (colon != std::string::npos && colon < 64 && remainder[0] != '[') {
            header_processed = true;
            std::string header = remainder.substr(0, colon);
            name = header;
            size_t piper = header.find("|");
            if (piper != std::string::npos) {
              name = header.substr(0, piper);
              std::string sStr = header.substr(piper + 1);
              size_t endS = sStr.find_first_not_of("0123456789");
              if (endS != std::string::npos)
                sStr = sStr.substr(0, endS);
              tSerial = (unsigned int)strtoul(sStr.c_str(), NULL, 10);
            }

            std::string nLow = name;
            std::transform(nLow.begin(), nLow.end(), nLow.begin(), ::tolower);

            Character *bestMatch = nullptr;
            int bestScore = 0;

            const ogre_unordered_set<Character *>::type &chars =
                thisptr->getCharacterUpdateList();
            for (auto it = chars.begin(); it != chars.end(); ++it) {
              Character *c = *it;
              if (!c || (uintptr_t)c < 0x1000)
                continue;

              int score = 0;
              if (tSerial > 0 && c->getHandle().serial == tSerial)
                score = 1000;
              else {
                std::string cName = c->getName();
                if (cName == name)
                  score = 500;
                else {
                  std::string cLow = cName;
                  std::transform(cLow.begin(), cLow.end(), cLow.begin(),
                                 ::tolower);
                  if (cLow == nLow)
                    score = 400;
                  else if (cLow.find(nLow) == 0)
                    score =
                        200;
                  else if (cLow.find(nLow) != std::string::npos)
                    score = 100;
                }
              }

              if (score > bestScore) {
                bestScore = score;
                bestMatch = c;
                if (score == 1000)
                  break;
              }
            }

            if (bestMatch && bestScore > 0) {
              targetHand = bestMatch->getHandle();
              found = true;
            }

            if (!found && thisptr->player &&
                thisptr->player->playerCharacters.size() > 0) {
              Character *p = thisptr->player->playerCharacters[0];
              lektor<RootObject *> results;
              thisptr->getCharactersWithinSphere(
                  results, p->getPosition(), 2500.0f, 0.0f, 0.0f, 0x10, 0, p);
              for (uint32_t i = 0; i < results.size(); ++i) {
                Character *c = (Character *)results.stuff[i];
                if (!c || (uintptr_t)c < 0x1000)
                  continue;

                int score = 0;
                if (tSerial > 0 && c->getHandle().serial == tSerial)
                  score = 1000;
                else {
                  std::string cName = c->getName();
                  if (cName == name)
                    score = 500;
                  else {
                    std::string cLow = cName;
                    std::transform(cLow.begin(), cLow.end(), cLow.begin(),
                                   ::tolower);
                    if (cLow == nLow)
                      score = 400;
                    else if (cLow.find(nLow) == 0)
                      score = 200;
                    else if (cLow.find(nLow) != std::string::npos)
                      score = 100;
                  }
                }

                if (score > bestScore) {
                  bestScore = score;
                  bestMatch = c;
                  if (score == 1000)
                    break;
                }
              }
              if (bestMatch && bestScore > 0) {
                targetHand = bestMatch->getHandle();
                found = true;
              }
            }

            if (!found && fallbackHand.isValid()) {
              Character *fc = fallbackHand.getCharacter();
              if (fc && (uintptr_t)fc > 0x1000) {
                std::string fcName = fc->getName();
                std::transform(fcName.begin(), fcName.end(), fcName.begin(),
                               ::tolower);
                std::string nLow = name;
                std::transform(nLow.begin(), nLow.end(), nLow.begin(),
                               ::tolower);

                if (name.empty() || fcName == nLow ||
                    fcName.find(nLow) != std::string::npos) {
                  targetHand = fallbackHand;
                  found = true;
                }
              }
            }
          }

          if (found || (header_processed && !found && fallbackHand.isValid())) {
            msg = (isNPCSay ? "NPC_SAY: " : "NPC_ACTION: ") +
                  remainder.substr(colon + 1);
            if (msg.length() > startPos && msg[startPos] == ' ')
              msg.erase(startPos, 1);

            if (!found && fallbackHand.isValid()) {
              targetHand = fallbackHand;
            }
          } else {
            Log(LOG_WARN, "QUEUE: Speaker not found: " + name);
          }
        }
      }

      if (isNPCAction || isNPCSay) {
        size_t searchPos = 0;
        while (true) {
          size_t startBracket = msg.find("[", searchPos);
          if (startBracket == std::string::npos)
            break;

          size_t endBracket = std::string::npos;
          int depth = 0;
          for (size_t i = startBracket; i < msg.length(); ++i) {
            if (msg[i] == '[')
              depth++;
            else if (msg[i] == ']') {
              depth--;
              if (depth == 0) {
                endBracket = i;
                break;
              }
            }
          }

          if (endBracket == std::string::npos)
            break;

          std::string fullTag =
              msg.substr(startBracket, endBracket - startBracket + 1);
          searchPos = endBracket + 1;

          std::string actStr = fullTag;

          auto getPayload = [](const std::string &str,
                               const std::string &prefix) -> std::string {
            size_t p = str.find(prefix);
            if (p == std::string::npos)
              return "";
            std::string res = str.substr(p + prefix.length());
            size_t lnot = res.find_last_not_of(" \t\n\r");
            if (lnot != std::string::npos) {
              res.erase(lnot + 1);
              if (!res.empty() && res.back() == ']')
                res.pop_back();
            }
            size_t f = res.find_first_not_of(" \t\n\r");
            if (f != std::string::npos)
              res.erase(0, f);
            lnot = res.find_last_not_of(" \t\n\r");
            if (lnot != std::string::npos)
              res.erase(lnot + 1);
            return res;
          };

          if (actStr.find("JOIN_PARTY") != std::string::npos) {
            EnterCriticalSection(&g_uiMutex);
            QueuedAction act;
            act.type = ACT_JOIN_PARTY;
            act.actor = targetHand;
            g_uiActionQueue.push_back(act);
            LeaveCriticalSection(&g_uiMutex);
          } else if (actStr.find("ATTACK") != std::string::npos &&
                     actStr.find("TOWN") == std::string::npos) {
            EnterCriticalSection(&g_uiMutex);
            QueuedAction act;
            act.type = ACT_ATTACK;
            act.actor = targetHand;
            if (thisptr->player && thisptr->player->playerCharacters.size() > 0)
              act.target = thisptr->player->playerCharacters[0]->getHandle();
            g_uiActionQueue.push_back(act);
            LeaveCriticalSection(&g_uiMutex);
          } else if (actStr.find("GIVE_ITEM:") != std::string::npos) {
            std::string payload = getPayload(actStr, "GIVE_ITEM:");
            int count = 1;
            size_t colon = std::string::npos;
            int depth = 0;
            for (int i = (int)payload.length() - 1; i >= 0; --i) {
              if (payload[i] == ']')
                depth++;
              else if (payload[i] == '[')
                depth--;
              else if (payload[i] == ':' && depth == 0) {
                colon = i;
                break;
              }
            }

            if (colon != std::string::npos) {
              std::string cStr = payload.substr(colon + 1);
              cStr.erase(0, cStr.find_first_not_of(" "));
              cStr.erase(cStr.find_last_not_of(" ") + 1);
              if (!cStr.empty() && isdigit(cStr[0])) {
                count = atoi(cStr.c_str());
                payload = payload.substr(0, colon);
                payload.erase(payload.find_last_not_of(" ") + 1);
              }
            }
            EnterCriticalSection(&g_uiMutex);
            QueuedAction act;
            act.type = ACT_GIVE_ITEM;
            act.actor = targetHand;
            act.target = g_lastChattingPlayerHand;
            act.message = payload;
            act.taskValue = count;
            g_uiActionQueue.push_back(act);
            LeaveCriticalSection(&g_uiMutex);
          } else if (actStr.find("TAKE_ITEM:") != std::string::npos) {
            std::string payload = getPayload(actStr, "TAKE_ITEM:");
            int count = 1;
            size_t colon = std::string::npos;
            int depth = 0;
            for (int i = (int)payload.length() - 1; i >= 0; --i) {
              if (payload[i] == ']')
                depth++;
              else if (payload[i] == '[')
                depth--;
              else if (payload[i] == ':' && depth == 0) {
                colon = i;
                break;
              }
            }

            if (colon != std::string::npos) {
              std::string cStr = payload.substr(colon + 1);
              cStr.erase(0, cStr.find_first_not_of(" "));
              cStr.erase(cStr.find_last_not_of(" ") + 1);
              if (!cStr.empty() && isdigit(cStr[0])) {
                count = atoi(cStr.c_str());
                payload = payload.substr(0, colon);
                payload.erase(payload.find_last_not_of(" ") + 1);
              }
            }
            EnterCriticalSection(&g_uiMutex);
            QueuedAction act;
            act.type = ACT_TAKE_ITEM;
            act.actor = targetHand;
            act.target = g_lastChattingPlayerHand;
            act.message = payload;
            act.taskValue = count;
            g_uiActionQueue.push_back(act);
            LeaveCriticalSection(&g_uiMutex);
          } else if (actStr.find("DROP_ITEM:") != std::string::npos) {
            std::string iName = getPayload(actStr, "DROP_ITEM:");
            EnterCriticalSection(&g_uiMutex);
            QueuedAction act;
            act.type = ACT_DROP_ITEM;
            act.actor = targetHand;
            act.message = iName;
            g_uiActionQueue.push_back(act);
            LeaveCriticalSection(&g_uiMutex);
          } else if (actStr.find("TAKE_CATS:") != std::string::npos) {
            std::string amtStr = getPayload(actStr, "TAKE_CATS:");
            EnterCriticalSection(&g_uiMutex);
            QueuedAction act;
            act.type = ACT_TAKE_CATS;
            act.actor = targetHand;
            act.target = g_lastChattingPlayerHand;
            act.taskValue = atoi(amtStr.c_str());
            g_uiActionQueue.push_back(act);
            LeaveCriticalSection(&g_uiMutex);
          } else if (actStr.find("GIVE_CATS:") != std::string::npos) {
            std::string amtStr = getPayload(actStr, "GIVE_CATS:");
            EnterCriticalSection(&g_uiMutex);
            QueuedAction act;
            act.type = ACT_GIVE_CATS;
            act.actor = targetHand;
            act.target = g_lastChattingPlayerHand;
            act.taskValue = atoi(amtStr.c_str());
            g_uiActionQueue.push_back(act);
            LeaveCriticalSection(&g_uiMutex);
          } else if (actStr.find("LEAVE") != std::string::npos) {
            EnterCriticalSection(&g_uiMutex);
            QueuedAction act;
            act.type = ACT_LEAVE;
            act.actor = targetHand;
            act.message = getPayload(actStr, "LEAVE:");
            g_uiActionQueue.push_back(act);
            LeaveCriticalSection(&g_uiMutex);
          } else if (actStr.find("FACTION_RELATIONS:") != std::string::npos) {
            std::string payload = getPayload(actStr, "FACTION_RELATIONS:");
            size_t colon = payload.find(':');
            if (colon != std::string::npos) {
              std::string fName = payload.substr(0, colon);
              size_t f = fName.find_first_not_of(" ");
              if (f != std::string::npos)
                fName.erase(0, f);
              size_t l = fName.find_last_not_of(" ");
              if (l != std::string::npos)
                fName.erase(l + 1);

              int amount = atoi(payload.substr(colon + 1).c_str());
              EnterCriticalSection(&g_uiMutex);
              QueuedAction act;
              act.type = ACT_FACTION_RELATIONS;
              act.actor = targetHand;
              act.message = fName;
              act.taskValue = amount;
              g_uiActionQueue.push_back(act);
              LeaveCriticalSection(&g_uiMutex);
            }
          } else if (actStr.find("SPAWN_ITEM:") != std::string::npos) {
            std::string payload = getPayload(actStr, "SPAWN_ITEM:");
            int count = 1;
            size_t pipePos = payload.find('|');
            std::string templateSegment = (pipePos != std::string::npos)
                                              ? payload.substr(0, pipePos)
                                              : payload;

            size_t colon = std::string::npos;
            int depth = 0;
            for (int i = (int)templateSegment.length() - 1; i >= 0; --i) {
              if (templateSegment[i] == ']')
                depth++;
              else if (templateSegment[i] == '[')
                depth--;
              else if (templateSegment[i] == ':' && depth == 0) {
                colon = i;
                break;
              }
            }

            if (colon != std::string::npos) {
              std::string cStr = templateSegment.substr(colon + 1);
              cStr.erase(0, cStr.find_first_not_of(" "));
              cStr.erase(cStr.find_last_not_of(" ") + 1);
              if (!cStr.empty() && isdigit(cStr[0])) {
                count = atoi(cStr.c_str());
                std::string baseTemplate = templateSegment.substr(0, colon);
                baseTemplate.erase(baseTemplate.find_last_not_of(" ") + 1);
                if (pipePos != std::string::npos) {
                  payload = baseTemplate + payload.substr(pipePos);
                } else {
                  payload = baseTemplate;
                }
              }
            }

            EnterCriticalSection(&g_uiMutex);
            QueuedAction act;
            act.type = ACT_SPAWN_ITEM;
            act.actor = targetHand;
            act.target = g_lastChattingPlayerHand;
            act.message = payload;
            act.taskValue = count;
            g_uiActionQueue.push_back(act);
            LeaveCriticalSection(&g_uiMutex);
          } else if (actStr.find("FOLLOW_PLAYER") != std::string::npos) {
            EnterCriticalSection(&g_uiMutex);
            QueuedAction act;
            act.type = ACT_SET_TASK;
            act.actor = targetHand;
            if (thisptr->player && thisptr->player->playerCharacters.size() > 0)
              act.target = thisptr->player->playerCharacters[0]->getHandle();
            act.taskValue = 44; // FOLLOW_PLAYER_ORDER
            g_uiActionQueue.push_back(act);
            LeaveCriticalSection(&g_uiMutex);
          } else if (actStr.find("IDLE") != std::string::npos &&
                     actStr.find("TASK:") == std::string::npos) {
            EnterCriticalSection(&g_uiMutex);
            QueuedAction act;
            act.type = ACT_SET_TASK;
            act.actor = targetHand;
            act.taskValue = 14; // IDLE
            g_uiActionQueue.push_back(act);
            LeaveCriticalSection(&g_uiMutex);
          } else if (actStr.find("PATROL_TOWN") != std::string::npos &&
                     actStr.find("TASK:") == std::string::npos) {
            EnterCriticalSection(&g_uiMutex);
            QueuedAction act;
            act.type = ACT_SET_TASK;
            act.actor = targetHand;
            act.taskValue = 36; // PATROL_TOWN
            g_uiActionQueue.push_back(act);
            LeaveCriticalSection(&g_uiMutex);
          } else if (actStr.find("RELEASE_PLAYER") != std::string::npos ||
                     actStr.find("RELEASE_PRISONER") != std::string::npos ||
                     actStr.find("FREE_PLAYER") != std::string::npos) {
            EnterCriticalSection(&g_uiMutex);
            QueuedAction act;
            act.type = ACT_RELEASE;
            act.actor = targetHand;
            act.taskValue = 110; // RELEASE_PRISONER
            if (thisptr->player && thisptr->player->playerCharacters.size() > 0)
              act.target = thisptr->player->playerCharacters[0]->getHandle();
            g_uiActionQueue.push_back(act);
            LeaveCriticalSection(&g_uiMutex);
          } else if (actStr.find("BREAKOUT_PRISONER") != std::string::npos ||
                     actStr.find("BREAKOUT_PLAYER") != std::string::npos) {
            EnterCriticalSection(&g_uiMutex);
            QueuedAction act;
            act.type = ACT_RELEASE;
            act.actor = targetHand;
            act.taskValue = 111; // BREAKOUT_PRISONER
            if (thisptr->player && thisptr->player->playerCharacters.size() > 0)
              act.target = thisptr->player->playerCharacters[0]->getHandle();
            g_uiActionQueue.push_back(act);
            LeaveCriticalSection(&g_uiMutex);
          } else if (actStr.find("MOVE_ON_FREE_WILL_FAST") !=
                     std::string::npos) {
            EnterCriticalSection(&g_uiMutex);
            QueuedAction act;
            act.type = ACT_SET_TASK;
            act.actor = targetHand;
            act.taskValue = 67; // MOVE_ON_FREE_WILL_FAST
            g_uiActionQueue.push_back(act);
            LeaveCriticalSection(&g_uiMutex);
          } else if (actStr.find("MOVE_ON_FREE_WILL") != std::string::npos) {
            EnterCriticalSection(&g_uiMutex);
            QueuedAction act;
            act.type = ACT_SET_TASK;
            act.actor = targetHand;
            act.taskValue = 1; // MOVE_ON_FREE_WILL
            g_uiActionQueue.push_back(act);
            LeaveCriticalSection(&g_uiMutex);
          } else if (actStr.find("GO_HOMEBUILDING") != std::string::npos) {
            EnterCriticalSection(&g_uiMutex);
            QueuedAction act;
            act.type = ACT_SET_TASK;
            act.actor = targetHand;
            act.taskValue = 19; // GO_HOMEBUILDING
            g_uiActionQueue.push_back(act);
            LeaveCriticalSection(&g_uiMutex);
          } else if (actStr.find("STAND_AT_SHOPKEEPER_NODE") !=
                     std::string::npos) {
            EnterCriticalSection(&g_uiMutex);
            QueuedAction act;
            act.type = ACT_SET_TASK;
            act.actor = targetHand;
            act.taskValue = 20; // STAND_AT_SHOPKEEPER_NODE
            g_uiActionQueue.push_back(act);
            LeaveCriticalSection(&g_uiMutex);
          } else if (actStr.find("ATTACK_TOWN") != std::string::npos) {
            std::string tName = getPayload(actStr, "ATTACK_TOWN:");
            EnterCriticalSection(&g_uiMutex);
            QueuedAction act;
            act.type = ACT_SET_TASK;
            act.actor = targetHand;
            act.taskValue = 23; // ATTACK_TOWN
            act.message = tName;
            g_uiActionQueue.push_back(act);
            LeaveCriticalSection(&g_uiMutex);
          } else if (actStr.find("RAID_TOWN") != std::string::npos) {
            std::string tName = getPayload(actStr, "RAID_TOWN:");
            EnterCriticalSection(&g_uiMutex);
            QueuedAction act;
            act.type = ACT_SET_TASK;
            act.actor = targetHand;
            act.taskValue = 18; // RAID_TOWN
            act.message = tName;
            g_uiActionQueue.push_back(act);
            LeaveCriticalSection(&g_uiMutex);
          } else if (actStr.find("TRAVEL_TO_TARGET_TOWN") !=
                     std::string::npos) {
            std::string tName = getPayload(actStr, "TRAVEL_TO_TARGET_TOWN:");
            EnterCriticalSection(&g_uiMutex);
            QueuedAction act;
            act.type = ACT_SET_TASK;
            act.actor = targetHand;
            act.message = tName;
            act.taskValue = 53; // TRAVEL_TO_TARGET_TOWN
            g_uiActionQueue.push_back(act);
            LeaveCriticalSection(&g_uiMutex);
          } else if (actStr.find("JOB_MEDIC") != std::string::npos) {
            EnterCriticalSection(&g_uiMutex);
            QueuedAction act;
            act.type = ACT_SET_TASK;
            act.actor = targetHand;
            act.taskValue = 58; // JOB_MEDIC
            g_uiActionQueue.push_back(act);
            LeaveCriticalSection(&g_uiMutex);
          } else if (actStr.find("FIND_AND_RESCUE") != std::string::npos) {
            EnterCriticalSection(&g_uiMutex);
            QueuedAction act;
            act.type = ACT_SET_TASK;
            act.actor = targetHand;
            act.taskValue = 105; // FIND_AND_RESCUE
            g_uiActionQueue.push_back(act);
            LeaveCriticalSection(&g_uiMutex);
          } else if (actStr.find("JOB_REPAIR_ROBOT") != std::string::npos) {
            EnterCriticalSection(&g_uiMutex);
            QueuedAction act;
            act.type = ACT_SET_TASK;
            act.actor = targetHand;
            act.taskValue = 57; // JOB_REPAIR_ROBOT
            g_uiActionQueue.push_back(act);
            LeaveCriticalSection(&g_uiMutex);
          } else if (actStr.find("TASK:") != std::string::npos) {
            std::string tName = getPayload(actStr, "TASK:");
            EnterCriticalSection(&g_uiMutex);
            QueuedAction act;
            act.type = ACT_SET_TASK;
            act.actor = targetHand;

            if (thisptr->player && thisptr->player->playerCharacters.size() > 0)
              act.target = thisptr->player->playerCharacters[0]->getHandle();

            act.taskValue = 24; // WANDERER
            if (tName == "IDLE")
              act.taskValue = 14;
            else if (tName == "PATROL_TOWN")
              act.taskValue = 36;
            else if (tName == "RUN_AWAY")
              act.taskValue = 35;
            else if (tName == "FOLLOW_PLAYER_ORDER")
              act.taskValue = 44;
            else if (tName == "CHASE")
              act.taskValue = 46;
            else if (tName == "MOVE_ON_FREE_WILL")
              act.taskValue = 1;
            else if (tName == "MELEE_ATTACK") {
              act.taskValue = 4;
            } else if (tName == "RELEASE_PRISONER") {
              act.taskValue = 110;
            } else if (tName == "BREAKOUT_PRISONER") {
              act.taskValue = 111;
            } else if (tName == "MOVE_ON_FREE_WILL_FAST") {
              act.taskValue = 67;
            } else if (tName == "GO_HOMEBUILDING") {
              act.taskValue = 19;
            } else if (tName == "STAND_AT_SHOPKEEPER_NODE") {
              act.taskValue = 20;
            } else if (tName == "ATTACK_TOWN") {
              act.taskValue = 23;
            } else if (tName == "RAID_TOWN") {
              act.taskValue = 18;
            } else if (tName == "TRAVEL_TO_TARGET_TOWN") {
              act.taskValue = 53;
            } else if (tName == "JOB_MEDIC") {
              act.taskValue = 58;
            } else if (tName == "FIND_AND_RESCUE") {
              act.taskValue = 105;
            } else if (tName == "JOB_REPAIR_ROBOT") {
              act.taskValue = 57;
            }

            g_uiActionQueue.push_back(act);
            LeaveCriticalSection(&g_uiMutex);
          }
        }
      }

      // Not an else-if: a message that triggers an action must still show its bubble.
      if (isPlayerSay || isNPCSay || isNPCAction) {
        std::string bubbleContent =
            isPlayerSay ? msg.substr(12)
                        : (isNPCSay ? msg.substr(9)
                                    : (isNPCAction ? msg.substr(12) : ""));

        if (!bubbleContent.empty()) {
          if (isPlayerSay && bubbleContent[0] == '/')
            bubbleContent = "";
          else if (isNPCSay && bubbleContent.find("[DEBUG]") == 0)
            bubbleContent = "";
        }

        if (!bubbleContent.empty() && (isNPCSay || isNPCAction)) {
          size_t searchPos = 0;
          while (true) {
            size_t aPos = bubbleContent.find("[", searchPos);
            if (aPos == std::string::npos)
              break;

            size_t aEnd = std::string::npos;
            int depth = 0;
            for (size_t i = aPos; i < bubbleContent.length(); ++i) {
              if (bubbleContent[i] == '[')
                depth++;
              else if (bubbleContent[i] == ']') {
                depth--;
                if (depth == 0) {
                  aEnd = i;
                  break;
                }
              }
            }

            if (aEnd != std::string::npos) {
              bubbleContent.erase(aPos, aEnd - aPos + 1);
            } else {
              bubbleContent.erase(aPos);
              break;
            }
          }
          size_t f = bubbleContent.find_first_not_of(" \t\r\n");
          if (f != std::string::npos)
            bubbleContent.erase(0, f);
          else
            bubbleContent = "";

          size_t l = bubbleContent.find_last_not_of(" \t\r\n");
          if (l != std::string::npos)
            bubbleContent.erase(l + 1);
        }

        hand bubbleAnchor = isPlayerSay ? speakerHand : targetHand;

        if (!bubbleContent.empty() && bubbleAnchor.isValid()) {
          Character *tc = bubbleAnchor.getCharacter();
          Log(LOG_DEBUG, "QUEUE: Queuing SAY for " +
                             (tc ? tc->getName() : "Unknown") + ": " +
                             bubbleContent);
          EnterCriticalSection(&g_uiMutex);
          QueuedAction act;
          act.type = ACT_SAY;
          act.actor = bubbleAnchor;
          act.target = targetHand;
          act.message = bubbleContent;
          g_uiActionQueue.push_back(act);
          LeaveCriticalSection(&g_uiMutex);
        }
      }
    }
    LeaveCriticalSection(&g_msgMutex);
  }
}

void attackingYou_hook(Character *npc, Character *attacker, bool so,
                       bool doAwarenessCheck) {
  // The hook runs many times a second for each attacker, so the faction check
  // comes first, and an attack that already waits is not built again
  Faction *faction = attacker && npc ? attacker->getFaction() : nullptr;
  if (faction && (uintptr_t)faction > 0x1000 && faction->isThePlayer()) {
    std::string target = GetNpcId(npc);
    std::string pair = GetNpcId(attacker) + ">" + target;
    if (!AttackWaits(pair))
      QueueGameEvent("attack", pair,
                     "\"attacker\": " + EventParty(attacker) +
                         ", \"target\": \"" + EscapeJSON(target) + "\"");
  }
  if (attackingYou_orig)
    attackingYou_orig(npc, attacker, so, doAwarenessCheck);
}

void declareDead_hook(Character *npc) {
  if (npc)
    QueueGameEvent("death", "", "\"party\": " + EventParty(npc));
  if (declareDead_orig)
    declareDead_orig(npc);
}

void setPrisonMode_hook(Character *npc, bool on, UseableStuff *h) {
  if (npc && on)
    QueueGameEvent("imprisonment", "", "\"party\": " + EventParty(npc));
  if (setPrisonMode_orig)
    setPrisonMode_orig(npc, on, h);
}

void setProneState_hook(Character *npc, ProneState p) {
  // The hook runs about 10 times a second while a character lies knocked out,
  // so only a change of the knockout makes an event
  bool down = npc && npc->getProneState() == PS_KO;
  if (npc && (p == PS_KO) != down) {
    std::string id = "\"id\": \"" + EscapeJSON(GetNpcId(npc)) + "\"";
    if (down)
      QueueGameEvent("up", "",
                     id + ", \"carried\": " +
                         (npc->isBeingCarried() ? "true" : "false"));
    else
      QueueGameEvent("knockout", "", id);
  }
  if (setProneState_orig)
    setProneState_orig(npc, p);
}

// The frame hook sends the context, because a rename can come in the middle of
// a game update
void setName_hook(Character *c, const std::string &name) {
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

void playerUpdate_hook(PlayerInterface *thisptr) {
  if (playerUpdate_orig)
    playerUpdate_orig(thisptr);

  if (!g_welcomeShown && MyGUI::Gui::getInstancePtr()) {
    if (g_enableWelcome) {
      CreateWelcomeUI();
      CreateLauncherUI();
    }
    CreateThread(NULL, 0, WelcomeResponseThread, NULL, 0, NULL);
    g_welcomeShown = true;
  }

  Character *sel = nullptr;
  try {
    sel = thisptr->selectedObject.getCharacter();
    if (!sel)
      sel = thisptr->selectedCharacter.getCharacter();
  } catch (...) {
  }

  std::vector<hand> renamed;
  EnterCriticalSection(&g_stateMutex);
  g_lastSelectionHand =
      sel && (uintptr_t)sel > 0x1000 ? sel->getHandle() : hand();
  renamed.swap(g_renamedSquad);
  LeaveCriticalSection(&g_stateMutex);

  // Driven from playerUpdate because it keeps ticking while the game is paused.
  GameWorld *world = *ppWorld;
  if (world) {
    ProcessMessageQueue(world);
    static int invTimer = 0;
    ExecuteQueuedActions(world, invTimer);

    for (size_t i = 0; i < renamed.size(); ++i) {
      Character *c = renamed[i].getCharacter();
      if (c)
        AsyncPostToPython(L"/squad_rename", GetDetailedContext(c));
    }

    // The buffer drops its oldest past 100, and the events that wait are lost
    // when the game closes
    EnterCriticalSection(&g_eventMutex);
    bool reportDue =
        g_gameEvents.size() >= 50 ||
        (!g_gameEvents.empty() &&
         GetTickCount() - g_gameEvents.front().queuedAt >= 60000);
    LeaveCriticalSection(&g_eventMutex);
    if (reportDue)
      AsyncPostToPython(L"/report", GameReport());

    DWORD now = GetTickCount();

    static DWORD lastFrameTickForAmbient = GetTickCount();
    DWORD deltaTick = now >= lastFrameTickForAmbient ? (now - lastFrameTickForAmbient) : 0;
    lastFrameTickForAmbient = now;

    if (g_enableAmbient) {
      float currentSpeed = world->getFrameSpeedMultiplier();
      
      // Shift the timer so paused time does not count toward the banter interval.
      if (currentSpeed <= 0.1f || world->isPaused()) {
          g_lastAmbientTick += deltaTick;
      } else {
        if (g_triggerAmbient || (now - g_lastAmbientTick >
                                 (DWORD)(g_ambientIntervalSeconds * 1000))) {
          g_triggerAmbient = false;
          g_lastAmbientTick = now;

          if (world->player && world->player->playerCharacters.size() > 0) {
            Character *player = world->player->playerCharacters[0];
            lektor<RootObject *> results;
            world->getCharactersWithinSphere(results, player->getPosition(),
                                             g_radiantRange, 0.0f, 0.0f, 16, 0,
                                             player);

            if (results.size() >= 2) {
              std::string npcData = "[";
              bool first = true;
              int count = 0;
              for (uint32_t i = 0; i < results.size() && count < 5; ++i) {
                Character *other = (Character *)results.stuff[i];
                if (other && (uintptr_t)other > 0x1000 && other != player) {
                  // Dead or unconscious NPCs cannot show speech bubbles.
                  try {
                    if (other->isDead() || other->isUnconcious())
                      continue;
                  } catch (...) {
                  }
                  if (!first)
                    npcData += ",";

                  RaceData *o_race =
                      other->getRace() ? other->getRace() : other->myRace;
                  std::string o_rn = "Unknown";
                  if (o_race && (uintptr_t)o_race > 0x1000) {
                    if (o_race->data && !o_race->data->name.empty())
                      o_rn = o_race->data->name;
                    else if (o_race->data && !o_race->data->stringID.empty())
                      o_rn = o_race->data->stringID;
                  }

                  LogNpcRole(other);
                  std::string identityFaction = GetIdentityFaction(other);
                  npcData +=
                      "{\"name\":\"" + EscapeJSON(other->getName()) + "\",";
                  npcData +=
                      "\"id\":" + ToString(other->getHandle().serial) +
                      ",";
                  npcData +=
                      "\"npc_id\":\"" + EscapeJSON(GetNpcId(other)) + "\",";
                  npcData += "\"race\":\"" + EscapeJSON(o_rn) + "\",";
                  npcData +=
                      "\"animal\":" +
                      std::string(other->isAnimal() ? "true" : "false") + ",";
                  npcData +=
                      "\"gender\":\"" +
                      std::string(other->isFemale() ? "female" : "male") +
                      "\",";
                  npcData += "\"template\":\"" +
                             EscapeJSON(other->data ? other->data->name
                                                    : std::string()) +
                             "\",";
                  npcData += "\"template_id\":\"" +
                             EscapeJSON(other->data ? other->data->stringID
                                                    : std::string()) +
                             "\",";
                  npcData += "\"unique\":" +
                             std::string(other->isUnique() ? "true" : "false") +
                             ",";
                  Faction *o_faction =
                      other->getFaction() ? other->getFaction() : other->owner;
                  npcData += "\"in_player_faction\":" +
                             std::string(o_faction && o_faction->isThePlayer()
                                             ? "true"
                                             : "false") +
                             ",";
                  npcData += RoleJson(other) + ",";
                  npcData +=
                      "\"faction\":\"" + EscapeJSON(identityFaction) + "\"}";
                  first = false;
                  count++;
                }
              }
              npcData += "]";

              int day = 0;
              int hour = 0;
              if (ppWorld && *ppWorld) {
                TimeOfDay tod = (*ppWorld)->getTimeStamp_inGameHours();
                day = (int)tod.getTotalDays();
                hour = (int)tod.getHoursPassed();
              }

              if (count >= 2) {
                std::string *pJson = new std::string(
                    "{\"npcs\": " + npcData + ", \"player\": \"" +
                    EscapeJSON(player->getName()) + "\", \"day\": " +
                    ToString(day) + ", \"hour\": " + ToString(hour) +
                    ", \"player_context\": " +
                    GetDetailedContext(player, "player") +
                    ", \"events\": " + TakeGameEvents() + "}");
                CreateThread(NULL, 0, AmbientPollThread, pJson, 0, NULL);
              }
            }
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

  if (!typing && (GetAsyncKeyState(g_chatHotkey) & 0x8000) && !g_chatWindow &&
      !g_libraryWindow) {
    static DWORD lastTalkTick = 0;
    if (GetTickCount() - lastTalkTick > 500) {
      lastTalkTick = GetTickCount();
      if (sel && (uintptr_t)sel > 0x1000) {
        // Only the slot-1 leader is excluded; squadmates are valid talk targets.
        bool isMainPlayer = false;
        const lektor<Character *> &pc = thisptr->getAllPlayerCharacters();
        if (pc.size() > 0 && pc[0] == sel) {
          isMainPlayer = true;
        }

        if (!isMainPlayer) {
          g_talkTargetHand = sel->getHandle();

          // End vanilla dialogue, or it runs alongside the AI chat ("double dialogue").
          if (sel->dialogue && (uintptr_t)sel->dialogue > 0x1000) {
            try {
              sel->dialogue->endDialogue(true);
              sel->dialogue->setInDialog(false);
            } catch (...) {
            }
          }

          CreateChatUI(sel->getName(), ToString(sel->getHandle().serial));
        }
      }
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

DWORD WINAPI MainThread(LPVOID lpParam) {
  HMODULE hLib = GetModuleHandleA("KenshiLib.dll");
  while (!hLib) {
    Sleep(500);
    hLib = GetModuleHandleA("KenshiLib.dll");
  }
  ppWorld = (GameWorld **)GetProcAddress(hLib, "?ou@@3PEAVGameWorld@@EA");
  if (!ppWorld)
    return 1;
  CreateThread(NULL, 0, PipeThread, NULL, 0, NULL);
  LoadPluginConfig();
  StartPythonServer(g_openWebPanelOnStart);
  return 0;
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

  HMODULE hLib = GetModuleHandleA("KenshiLib.dll");
  void *thunkPlayer =
      (void *)GetProcAddress(hLib, "?update@PlayerInterface@@QEAAXXZ");
  if (thunkPlayer)
    KenshiLib::AddHook((void *)KenshiLib::GetRealAddress(thunkPlayer),
                       (void *)playerUpdate_hook, (void **)&playerUpdate_orig);

  void *thunkAttack =
      (void *)GetProcAddress(hLib, "?attackingYou@Character@@QEAAXPEAV1@_N1@Z");
  if (thunkAttack)
    KenshiLib::AddHook((void *)KenshiLib::GetRealAddress(thunkAttack),
                       (void *)attackingYou_hook, (void **)&attackingYou_orig);

  void *thunkDeath =
      (void *)GetProcAddress(hLib, "?declareDead@Character@@QEAAXXZ");
  if (thunkDeath)
    KenshiLib::AddHook((void *)KenshiLib::GetRealAddress(thunkDeath),
                       (void *)declareDead_hook, (void **)&declareDead_orig);

  void *thunkPrison = (void *)GetProcAddress(
      hLib, "?setPrisonMode@Character@@QEAAX_NPEAVUseableStuff@@@Z");
  if (thunkPrison)
    KenshiLib::AddHook((void *)KenshiLib::GetRealAddress(thunkPrison),
                       (void *)setPrisonMode_hook,
                       (void **)&setPrisonMode_orig);

  void *thunkKO = (void *)GetProcAddress(
      hLib, "?setProneState@Character@@UEAAXW4ProneState@@@Z");
  if (thunkKO)
    KenshiLib::AddHook((void *)KenshiLib::GetRealAddress(thunkKO),
                       (void *)setProneState_hook,
                       (void **)&setProneState_orig);

  void *thunkName = (void *)GetProcAddress(
      hLib, "?_NV_setName@Character@@QEAAXAEBV?$basic_string@DU?$char_traits@D@"
            "std@@V?$allocator@D@2@@std@@@Z");
  if (thunkName)
    KenshiLib::AddHook((void *)KenshiLib::GetRealAddress(thunkName),
                       (void *)setName_hook, (void **)&setName_orig);

  CreateThread(NULL, 0, MainThread, NULL, 0, NULL);
}

BOOL APIENTRY DllMain(HMODULE hModule, DWORD ul_reason_for_call,
                      LPVOID lpReserved) {
  if (ul_reason_for_call == DLL_PROCESS_ATTACH)
    g_hModule = hModule;
  return TRUE;
}
