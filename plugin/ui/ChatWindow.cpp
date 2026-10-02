#include "ChatWindow.h"
#include "../core/Comm.h"
#include "../game/Context.h"
#include "../core/Globals.h"
#include "../core/Utils.h"

#include <kenshi/Character.h>
#include <kenshi/Faction.h>
#include <kenshi/GameData.h>
#include <kenshi/GameWorld.h>
#include <kenshi/Kenshi.h>
#include <kenshi/PlayerInterface.h>
#include <kenshi/RaceData.h>
#include <kenshi/RootObject.h>
#include <kenshi/RootObjectBase.h>
#include <kenshi/util/hand.h>

#include <mygui/MyGUI_Button.h>
#include <mygui/MyGUI_ComboBox.h>
#include <mygui/MyGUI_Delegate.h>
#include <mygui/MyGUI_EditBox.h>
#include <mygui/MyGUI_Gui.h>
#include <mygui/MyGUI_InputManager.h>
#include <mygui/MyGUI_TextBox.h>
#include <mygui/MyGUI_Window.h>

#include <sstream>

namespace SentientSands {
namespace UI {

MyGUI::Window *g_chatWindow = nullptr;
MyGUI::EditBox *g_chatInput = nullptr;
MyGUI::Button *g_chatModeBtns[3] = {nullptr, nullptr, nullptr};
MyGUI::TextBox *g_chatLabel = nullptr;
std::string g_chatTargetHandleStr = "";
std::string g_chatTargetNameStr = "";
std::string g_chatPlayerNameStr = "";
size_t g_lastChatModeIndex = 1;
bool g_chatJustOpened = false;

void CloseChatUI() {
  if (g_chatWindow) {
    if (MyGUI::Gui::getInstancePtr())
      MyGUI::Gui::getInstancePtr()->destroyWidget(g_chatWindow);
    g_chatWindow = nullptr;
    g_chatInput = nullptr;
    for (int i = 0; i < 3; i++)
      g_chatModeBtns[i] = nullptr;
    g_chatLabel = nullptr;
  }
}

DWORD WINAPI ChatResponseThread(LPVOID lpParam) {
  ChatTask *t = (ChatTask *)lpParam;
  Log(LOG_INFO, "CHAT: Sending chat request for " + t->npcName);

  std::string response = PostToPythonWithResponse(L"/chat", t->json);

  if (response.empty()) {
    Log(LOG_WARN, "CHAT: Empty response from server for " + t->npcName);
    delete t;
    return 0;
  }

  Log(LOG_INFO, "CHAT: Got response for " + t->npcName + " (" +
                    ToString((int)response.length()) + " bytes)");
  Log(LOG_DEBUG, "CHAT: Response: " + response);

  std::string npcText = GetJsonValue(response, "text");
  std::vector<std::string> actions;
  std::string actionsJson = GetJsonValue(response, "actions");
  if (!actionsJson.empty() && actionsJson[0] == '[') {
    size_t s = 0;
    while ((s = actionsJson.find("\"", s)) != std::string::npos) {
      s++;
      size_t e = s;
      while (e < actionsJson.size()) {
        if (actionsJson[e] == '\\' && e + 1 < actionsJson.size()) {
          e += 2;
        } else if (actionsJson[e] == '\"') {
          break;
        } else {
          e++;
        }
      }
      if (e < actionsJson.size()) {
        actions.push_back(UnescapeJSON(actionsJson.substr(s, e - s)));
        s = e + 1;
      } else {
        break;
      }
    }
  }

  // Queue actions before speech so an AI state change cannot clear an already-queued bubble.
  for (size_t i = 0; i < actions.size(); i++) {
    std::string actLine;
    // Action may already name its speaker, e.g. "Name: [ACTION: X]"
    if (actions[i].find(':') != std::string::npos &&
        actions[i].find('[') != std::string::npos &&
        actions[i].find(':') < actions[i].find('[')) {
      actLine = "NPC_ACTION: " + actions[i];
    } else {
      actLine =
          "NPC_ACTION: " + t->npcName + "|" + t->handleStr + ": " + actions[i];
    }

    EnterCriticalSection(&g_msgMutex);
    g_messageQueue.push_back(actLine);
    LeaveCriticalSection(&g_msgMutex);
    Sleep(50);
  }

  if (!npcText.empty()) {
    std::stringstream ss(npcText);
    std::string line;
    bool first = true;
    while (std::getline(ss, line)) {
      if (line.empty())
        continue;

      std::string pipeLine;
      size_t colonPos = line.find(':');
      if (colonPos != std::string::npos && colonPos < 64 && colonPos > 0) {
        std::string speakerName = line.substr(0, colonPos);
        speakerName.erase(0, speakerName.find_first_not_of(" "));
        speakerName.erase(speakerName.find_last_not_of(" ") + 1);

        std::string speech = line.substr(colonPos + 1);
        speech.erase(0, speech.find_first_not_of(" "));

        if (speakerName.find('|') != std::string::npos) {
          pipeLine = "NPC_SAY: " + speakerName + ": " + speech;
        } else if (speakerName == t->npcName) {
          pipeLine =
              "NPC_SAY: " + speakerName + "|" + t->handleStr + ": " + speech;
        } else {
          pipeLine = "NPC_SAY: " + speakerName + ": " + speech;
        }
      } else {
        pipeLine = "NPC_SAY: " + t->npcName + "|" + t->handleStr + ": " + line;
      }

      if (!first)
        SleepIfPaused(g_dialogueSpeedSeconds * 1000);

      EnterCriticalSection(&g_msgMutex);
      g_messageQueue.push_back(pipeLine);
      g_lastDialogueTick = GetTickCount();
      LeaveCriticalSection(&g_msgMutex);
      first = false;
    }
  }

  delete t;
  return 0;
}

void OnChatInputChange(MyGUI::EditBox *sender) {
  std::string text = sender->getCaption().asUTF8();

  if (g_chatJustOpened) {
    if (text.length() > 0) {
      std::string textUpper = text;
      textUpper[0] = toupper(textUpper[0]);
      std::string hkUpper = g_chatHotkeyStr;
      if (!hkUpper.empty())
        hkUpper[0] = toupper(hkUpper[0]);

      if (text == "\\" || text == "\n" || text == "\r" ||
          (text.length() == 1 && textUpper == hkUpper)) {
        sender->setCaption("");
        g_chatJustOpened = false;
        return;
      }
      g_chatJustOpened = false;
    }
  }

  if (text == "\\" || text == "\n" || text == "\r") {
    sender->setCaption("");
    return;
  }

  if (!text.empty() && (text.back() == '\n' || text.back() == '\r')) {
    while (!text.empty() && (text.back() == '\n' || text.back() == '\r'))
      text.pop_back();

    sender->setCaption(text);
    OnChatSendClick(sender);
  }
}

void OnChatInputAccept(MyGUI::EditBox *sender) { OnChatSendClick(sender); }

void OnChatSendClick(MyGUI::Widget *sender) {
  if (!g_chatInput)
    return;
  std::string text = g_chatInput->getCaption().asUTF8();
  if (text.empty()) {
    CloseChatUI();
    return;
  }

  std::string mode = "talk";
  size_t selIndex = g_lastChatModeIndex;

  if (selIndex == 0)
    mode = "whisper";
  else if (selIndex == 1)
    mode = "talk";
  else if (selIndex == 2)
    mode = "yell";

  std::string npcName = g_chatTargetNameStr;
  std::string playerName = g_chatPlayerNameStr;
  std::string handleStr = g_chatTargetHandleStr;

  if (text.substr(0, 6) == "/name " && text.length() > 6) {
    std::string newName = text.substr(6);
    newName.erase(0, newName.find_first_not_of(" \t\r\n"));
    newName.erase(newName.find_last_not_of(" \t\r\n") + 1);

    if (!newName.empty()) {
      GameWorld *world = *ppWorld;
      if (world) {
        Character *target = nullptr;
        const auto &chars = world->getCharacterUpdateList();
        for (auto it = chars.begin(); it != chars.end(); ++it) {
          if (*it && (uintptr_t)(*it) > 0x1000) {
            unsigned int serial = std::stoul(handleStr);
            if ((*it)->getHandle().serial == serial) {
              target = *it;
              break;
            }
          }
        }

        if (target) {
          target->setName(newName);
          Log(LOG_INFO, "NAME: " + npcName + " is now " + newName);
          g_chatTargetNameStr = newName;

          std::string renJson =
              "{\"old_name\": \"" + EscapeJSON(npcName) + "\", ";
          renJson += "\"new_name\": \"" + EscapeJSON(newName) + "\", ";
          renJson += "\"context\": " + GetDetailedContext(target) + "}";
          AsyncPostToPython(L"/rename", renJson);

          if (g_chatWindow)
            g_chatWindow->setCaption("Talking to: " + newName);
          if (g_chatLabel)
            g_chatLabel->setCaption("Name updated to: " + newName);

          g_chatInput->setCaption("");
          return;
        }
      }
    }
  }

  CloseChatUI();

  EnterCriticalSection(&g_msgMutex);
  g_messageQueue.push_back("PLAYER_SAY: " + text);
  LeaveCriticalSection(&g_msgMutex);

  std::string primaryId = npcName + "|" + handleStr;
  std::string npcsJson = "\"" + EscapeJSON(primaryId) + "\"";
  std::string nearbyFullJson = "";

  float searchRadius = g_proximityRadius;
  if (mode == "whisper")
    searchRadius = g_visionRange; // NPCs can see you even if you whisper
  else if (mode == "yell")
    searchRadius = g_yellRadius;

  GameWorld *world = *ppWorld;
  if (world && world->player && world->player->playerCharacters.size() > 0) {
    try {
      Character *player = world->player->playerCharacters[0];
      const auto &chars = world->getCharacterUpdateList();
      for (auto it = chars.begin(); it != chars.end(); ++it) {
        Character *other = *it;
        if (other && (uintptr_t)other > 0x1000 && other != player &&
            other->getName() != npcName) {
          float dist = player->getPosition().distance(other->getPosition());
          if (dist < searchRadius) {
            std::string o_name = other->getName();
            unsigned int o_serial = other->getHandle().serial;
            npcsJson +=
                ", \"" + EscapeJSON(o_name) + "|" + ToString(o_serial) + "\"";

            RaceData *race =
                other->getRace() ? other->getRace() : other->myRace;
            std::string raceName = "Unknown";
            if (race && (uintptr_t)race > 0x1000) {
              if (race->data && !race->data->name.empty())
                raceName = race->data->name;
              else if (race->data && !race->data->stringID.empty())
                raceName = race->data->stringID;
            }

            Faction *faction =
                other->getFaction() ? other->getFaction() : other->owner;
            std::string factionName = "Neutral";
            if (faction && (uintptr_t)faction > 0x1000) {
              std::string fn = faction->getName();
              if (!fn.empty() && fn != "Unknown")
                factionName = fn;
              else if (faction->data && !faction->data->name.empty())
                factionName = faction->data->name;
              else if (faction->data && !faction->data->stringID.empty())
                factionName = faction->data->stringID;
            }

            std::string o_sid_fact = factionName;
            if (g_originFactions.count(o_serial)) {
              o_sid_fact = g_originFactions[o_serial];
            } else if (faction && !faction->isThePlayer()) {
              g_originFactions[o_serial] = factionName;
              o_sid_fact = factionName;
            }
            std::string o_sid =
                GetStorageIDFor(other, other->getName(), o_sid_fact);

            std::string o_gender = other->isFemale() ? "female" : "male";

            if (!nearbyFullJson.empty())
              nearbyFullJson += ",";
            nearbyFullJson += "{\"name\":\"" + EscapeJSON(other->getName()) +
                              "\", \"id\":\"" +
                              ToString((int)other->getHandle().serial) +
                              "\", \"storage_id\":\"" + EscapeJSON(o_sid) +
                              "\", \"race\":\"" + EscapeJSON(raceName) +
                              "\", \"faction\":\"" + EscapeJSON(factionName) +
                              "\", \"gender\":\"" + EscapeJSON(o_gender) +
                              "\", \"dist\":" + ToString((int)dist) + "}";
          }
        }
      }
    } catch (...) {
      Log(LOG_WARN, "CHAT: Exception during proximity check.");
    }
  }

  Character *targetNpc = nullptr;
  if (world) {
    try {
      // By serial, because name assignment can give two loaded NPCs one name
      unsigned int targetSerial = std::stoul(handleStr);
      const auto &chars = world->getCharacterUpdateList();
      for (auto it = chars.begin(); it != chars.end(); ++it) {
        if ((*it) && (uintptr_t)(*it) > 0x1000 &&
            (*it)->getHandle().serial == targetSerial) {
          targetNpc = *it;
          break;
        }
      }
    } catch (...) {
    }
  }

  std::string detailedContext = "{}";
  if (targetNpc) {
    detailedContext = GetDetailedContext(targetNpc);
    LogNpcIdentity(targetNpc);
  }

  std::string json =
      "{\"npc\": \"" + EscapeJSON(npcName) + "\", \"npcs\": [" + npcsJson +
      "], \"nearby\": [" + nearbyFullJson + "], \"message\": \"" +
      EscapeJSON(text) + "\", \"player\": \"" + EscapeJSON(playerName) +
      "\", \"mode\": \"" + mode + "\", \"context\": " + detailedContext + "}";

  ChatTask *task = new ChatTask();
  task->json = json;
  task->npcName = npcName;
  task->handleStr = handleStr;
  CreateThread(NULL, 0, ChatResponseThread, task, 0, NULL);
}

void OnChatCancelClick(MyGUI::Widget *sender) { CloseChatUI(); }
void OnRadiantClick(MyGUI::Widget *sender) {
  g_triggerAmbient = true;
  CloseChatUI();
}

void OnChatWindowButtonPressed(MyGUI::Window *sender, const std::string &name) {
  if (name == "close")
    CloseChatUI();
}

void CreateChatUI(const std::string &npcName, const std::string &playerName,
                  const std::string &handleStr) {
  MyGUI::Gui *gui = MyGUI::Gui::getInstancePtr();
  if (!gui)
    return;
  if (g_chatWindow)
    CloseChatUI();

  g_chatTargetNameStr = npcName;
  g_chatPlayerNameStr = playerName;
  g_chatTargetHandleStr = handleStr;
  g_chatJustOpened = true;

  std::string actualNpcName = npcName;
  // Auto-renaming runs on NameAssignThread so CreateChatUI never blocks on HTTP.
  g_chatWindow = gui->createWidgetReal<MyGUI::Window>(
      "Kenshi_WindowCX", 0.1875f, 0.4f, 0.625f, 0.18f, MyGUI::Align::Center,
      "Popup", "SentientSands_ChatWindow");
  g_chatWindow->setCaption(
      Utf8ToWide(T("Talking to: ") + actualNpcName).c_str());
  g_chatWindow->eventWindowButtonPressed +=
      MyGUI::newDelegate(OnChatWindowButtonPressed);
  MyGUI::Widget *client = g_chatWindow->getClientWidget();
  g_chatLabel = client->createWidgetReal<MyGUI::TextBox>(
      "Kenshi_TextboxStandardText", 0.05f, 0.05f, 0.9f, 0.2f,
      MyGUI::Align::Top | MyGUI::Align::HStretch, "SentientSands_ChatLabel");
  g_chatLabel->setCaption(Utf8ToWide(T("Message for ") + actualNpcName +
                                     T(" (from ") + playerName + T("):"))
                              .c_str());
  g_chatInput = client->createWidgetReal<MyGUI::EditBox>(
      "Kenshi_EditBox", 0.05f, 0.35f, 0.9f, 0.25f,
      MyGUI::Align::Top | MyGUI::Align::HStretch, "SentientSands_ChatInput");

  g_chatInput->setEditMultiLine(false);
  g_chatInput->setEditWordWrap(false);
  g_chatInput->setVisibleVScroll(false);
  g_chatInput->setTextAlign(MyGUI::Align::Default);
  g_chatInput->setFontHeight(18);

  g_chatInput->eventEditTextChange += MyGUI::newDelegate(OnChatInputChange);
  g_chatInput->eventEditSelectAccept += MyGUI::newDelegate(OnChatInputAccept);
  MyGUI::InputManager::getInstance().setKeyFocusWidget(g_chatInput);

  const char *btnLabelKeys[] = {"Whisper", "Talk", "Yell"};
  float btnX = 0.05f;
  for (int i = 0; i < 3; i++) {
    g_chatModeBtns[i] = client->createWidgetReal<MyGUI::Button>(
        "Kenshi_Button1", btnX, 0.75f, 0.12f, 0.2f,
        MyGUI::Align::Bottom | MyGUI::Align::Left,
        "SentientSands_ChatMode_" + ToString(i));
    g_chatModeBtns[i]->setCaption(Utf8ToWide(T(btnLabelKeys[i])).c_str());
    g_chatModeBtns[i]->eventMouseButtonClick +=
        MyGUI::newDelegate(OnModeButtonClick);
    btnX += 0.13f;
  }
  UpdateModeButtons();

  MyGUI::Button *sendBtn = client->createWidgetReal<MyGUI::Button>(
      "Kenshi_Button1", 0.44f, 0.75f, 0.17f, 0.2f,
      MyGUI::Align::Bottom | MyGUI::Align::Right, "SentientSands_ChatSendBtn");
  sendBtn->setCaption(Utf8ToWide(T("Send")).c_str());
  sendBtn->eventMouseButtonClick += MyGUI::newDelegate(OnChatSendClick);

  MyGUI::Button *cancelBtn = client->createWidgetReal<MyGUI::Button>(
      "Kenshi_Button1", 0.62f, 0.75f, 0.17f, 0.2f,
      MyGUI::Align::Bottom | MyGUI::Align::Right,
      "SentientSands_ChatCancelBtn");
  cancelBtn->setCaption(Utf8ToWide(T("Cancel")).c_str());
  cancelBtn->eventMouseButtonClick += MyGUI::newDelegate(OnChatCancelClick);

  MyGUI::Button *radiantBtn = client->createWidgetReal<MyGUI::Button>(
      "Kenshi_Button1", 0.80f, 0.75f, 0.17f, 0.2f,
      MyGUI::Align::Bottom | MyGUI::Align::Right,
      "SentientSands_ChatRadiantBtn");
  radiantBtn->setCaption(Utf8ToWide(T("Trigger Radiant")).c_str());
  radiantBtn->eventMouseButtonClick += MyGUI::newDelegate(OnRadiantClick);
}

void OnModeButtonClick(MyGUI::Widget *sender) {
  for (int i = 0; i < 3; i++) {
    if (sender == g_chatModeBtns[i]) {
      g_lastChatModeIndex = i;
      break;
    }
  }
  UpdateModeButtons();
}

void UpdateModeButtons() {
  const char *btnLabelKeys[] = {"Whisper", "Talk", "Yell"};
  for (int i = 0; i < 3; i++) {
    if (!g_chatModeBtns[i])
      continue;
    if (i == g_lastChatModeIndex) {
      g_chatModeBtns[i]->setCaption(
          (std::string("> ") + T(btnLabelKeys[i]) + " <").c_str());
    } else {
      g_chatModeBtns[i]->setCaption(Utf8ToWide(T(btnLabelKeys[i])).c_str());
    }
  }
}

} // namespace UI
} // namespace SentientSands
