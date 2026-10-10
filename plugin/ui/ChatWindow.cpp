#include "ChatWindow.h"
#include "../core/Comm.h"
#include "../game/Context.h"
#include "../core/Globals.h"
#include "../core/Utils.h"

#include <kenshi/CharStats.h>
#include <kenshi/Character.h>
#include <kenshi/Faction.h>
#include <kenshi/GameData.h>
#include <kenshi/GameWorld.h>
#include <kenshi/Kenshi.h>
#include <kenshi/Platoon.h>
#include <kenshi/PlayerInterface.h>
#include <kenshi/RaceData.h>
#include <kenshi/RootObject.h>
#include <kenshi/RootObjectBase.h>
#include <kenshi/util/hand.h>

#include <mygui/MyGUI_Button.h>
#include <mygui/MyGUI_Delegate.h>
#include <mygui/MyGUI_EditBox.h>
#include <mygui/MyGUI_Gui.h>
#include <mygui/MyGUI_InputManager.h>
#include <mygui/MyGUI_TextBox.h>
#include <mygui/MyGUI_Window.h>

#include <cstdlib>
#include <vector>

namespace SentientSands {
namespace UI {

MyGUI::Window *g_chatWindow = nullptr;
MyGUI::EditBox *g_chatInput = nullptr;
MyGUI::Button *g_chatModeBtns[3] = {nullptr, nullptr, nullptr};
MyGUI::TextBox *g_chatLabel = nullptr;
MyGUI::Button *g_chatSpeakerBtn = nullptr;
std::vector<hand> g_chatSpeakers;
size_t g_chatSpeakerIndex = 0;
// In memory only, so a new game session starts on the first squad member
unsigned int g_lastSpeakerKey = 0;
std::string g_chatTargetHandleStr = "";
std::string g_chatTargetNameStr = "";
size_t g_lastChatModeIndex = 1;
bool g_chatJustOpened = false;
// Both guarded by g_msgMutex, because the reply thread of a chat line sets them
std::string g_actionPendingName;
unsigned int g_actionNpcKey = 0;

void CloseChatUI() {
  if (g_chatWindow) {
    if (MyGUI::Gui::getInstancePtr())
      MyGUI::Gui::getInstancePtr()->destroyWidget(g_chatWindow);
    g_chatWindow = nullptr;
    g_chatInput = nullptr;
    for (int i = 0; i < 3; i++)
      g_chatModeBtns[i] = nullptr;
    g_chatLabel = nullptr;
    g_chatSpeakerBtn = nullptr;
  }
}

static void NotifyChatStatus(const std::string &key,
                             const std::string &npcName) {
  std::string text = T(key);
  size_t nameSlot = text.find("{name}");
  if (nameSlot != std::string::npos)
    text.replace(nameSlot, 6, npcName);
  EnterCriticalSection(&g_msgMutex);
  g_messageQueue.push_back("NOTIFY: " + text);
  LeaveCriticalSection(&g_msgMutex);
}

static bool IsAsciiLetter(char c) {
  return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z');
}

// The server parses the mark, so the window does not check the category name
static bool IsActionMark(const std::string &text) {
  if (text.size() < 2 || text[0] != '!')
    return false;
  if (IsAsciiLetter(text[1]))
    return true;
  return text[1] == ' ' && text.find_first_not_of(' ', 1) != std::string::npos;
}

static std::string WithoutActionMark(const std::string &text) {
  size_t end = 1;
  while (end < text.size() && IsAsciiLetter(text[end]))
    end++;
  size_t start = text.find_first_not_of(' ', end);
  return start == std::string::npos ? std::string() : text.substr(start);
}

static std::string Squashed(const std::string &text) {
  std::string out;
  for (size_t i = 0; i < text.size(); ++i)
    if (text[i] != ' ')
      out += (char)tolower((unsigned char)text[i]);
  return out;
}

static std::string SetStat(Character *target, const std::string &args) {
  const std::string usage =
      "Type /stat, a stat, and a level, for example /stat strength 80.";
  size_t space = args.find_last_of(' ');
  CharStats *stats = target ? target->getStats() : NULL;
  if (space == std::string::npos || !stats)
    return usage;
  char *end = NULL;
  long level = strtol(args.c_str() + space + 1, &end, 10);
  if (*end != '\0')
    return usage;
  level = level > 100 ? 100 : level < 0 ? 0 : level;
  std::string typed = args.substr(0, space);
  std::string wanted = Squashed(typed);
  std::string known;
  for (int i = STAT_NONE + 1; i < STAT_END; ++i) {
    std::string name = CharStats::getStatName((StatsEnumerated)i);
    if (Squashed(name) == wanted) {
      stats->getStatRef((StatsEnumerated)i) = (float)level;
      std::string result = target->getName() + "'s " + name + " is now " +
                           ToString((int)level) + ".";
      Log(LOG_INFO, "CHEAT: " + result);
      return result;
    }
    known += (known.empty() ? "" : ", ") + name;
  }
  Log(LOG_INFO, "CHEAT: No stat named '" + typed + "'. The stats are " + known);
  return "No stat named '" + typed + "'.";
}

static std::string ChangeCats(Character *player, const std::string &args) {
  char *end = NULL;
  long amount = strtol(args.c_str(), &end, 10);
  if (!player || args.empty() || *end != '\0')
    return "Type /cats and an amount, for example /cats 500 or /cats -500.";
  int money = player->getMoney();
  if (money <= 0 && player->getOwnerships())
    money = player->getOwnerships()->getMoney();
  if (amount < -money)
    amount = -money;
  player->takeMoney((int)-amount);
  std::string result = amount < 0 ? "Took " + ToString((int)-amount) + " cats."
                                  : "Added " + ToString((int)amount) + " cats.";
  Log(LOG_INFO, "CHEAT: " + result);
  return result;
}

static void SettleActionDialogue(ChatTask *t, const std::string &response) {
  bool open = GetJsonValue(response, "action_dialogue").find("true") == 0;
  EnterCriticalSection(&g_msgMutex);
  if (t->action)
    g_actionPendingName.clear();
  g_actionNpcKey =
      open ? (unsigned int)strtoul(t->handleStr.c_str(), NULL, 10) : 0;
  LeaveCriticalSection(&g_msgMutex);
}

DWORD WINAPI ChatResponseThread(LPVOID lpParam) {
  ChatTask *t = (ChatTask *)lpParam;
  Log(LOG_INFO, "CHAT: Sending chat request for " + t->npcName);
  NotifyChatStatus("{name} is thinking...", t->npcName);
  EnterCriticalSection(&g_msgMutex);
  g_messageQueue.push_back("NPC_SAY: " + t->npcName + "|" + t->handleStr +
                           ": ...");
  LeaveCriticalSection(&g_msgMutex);

  std::string response = PostToPythonWithResponse(L"/chat", t->json);
  SettleActionDialogue(t, response);

  std::string error = GetJsonValue(response, "error");
  if (response.empty() || !error.empty()) {
    Log(LOG_WARN, "CHAT: No reply from server for " + t->npcName +
                      (error.empty() ? "" : ": " + error));
    NotifyChatStatus("{name} could not respond.", t->npcName);
    delete t;
    return 0;
  }
  // The server sends the reply and its actions through the pipe, and paces the lines
  NotifyChatStatus("{name} has responded.", t->npcName);
  Log(LOG_INFO, "CHAT: Got response for " + t->npcName);

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
  std::string handleStr = g_chatTargetHandleStr;
  GameWorld *world = *ppWorld;

  Character *speaker = nullptr;
  if (g_chatSpeakerIndex < g_chatSpeakers.size())
    speaker = g_chatSpeakers[g_chatSpeakerIndex].getCharacter();
  if (!speaker && world && world->player &&
      world->player->playerCharacters.size() > 0)
    speaker = world->player->playerCharacters[0];
  if (speaker)
    g_lastSpeakerKey = HandleKey(speaker);
  std::string playerName = speaker ? speaker->getName() : "Drifter";

  if (text.substr(0, 6) == "/name " && text.length() > 6) {
    std::string newName = text.substr(6);
    newName.erase(0, newName.find_first_not_of(" \t\r\n"));
    newName.erase(newName.find_last_not_of(" \t\r\n") + 1);

    if (!newName.empty()) {
      GameWorld *world = *ppWorld;
      if (world) {
        Character *target =
            KeyedCharacter((unsigned int)strtoul(handleStr.c_str(), NULL, 10));

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

  std::string command = text.substr(0, text.find(' '));
  if (command == "/stat" || command == "/cats") {
    std::string args = text.substr(command.size());
    args.erase(0, args.find_first_not_of(" \t\r\n"));
    args.erase(args.find_last_not_of(" \t\r\n") + 1);
    std::string result =
        command == "/stat"
            ? SetStat(KeyedCharacter(
                          (unsigned int)strtoul(handleStr.c_str(), NULL, 10)),
                      args)
            : ChangeCats(speaker, args);
    if (g_chatLabel)
      g_chatLabel->setCaption(result);
    g_chatInput->setCaption("");
    return;
  }

  bool marked = IsActionMark(text);
  unsigned int targetKey = (unsigned int)strtoul(handleStr.c_str(), NULL, 10);
  EnterCriticalSection(&g_msgMutex);
  std::string pendingName = g_actionPendingName;
  bool actionLine =
      marked || (g_actionNpcKey != 0 && targetKey == g_actionNpcKey);
  // A second line could bring a second offer, so an action dialogue line
  // holds every chat until its reply arrives
  if (pendingName.empty() && actionLine)
    g_actionPendingName = npcName;
  LeaveCriticalSection(&g_msgMutex);
  CloseChatUI();
  if (!pendingName.empty()) {
    NotifyChatStatus("{name} is still thinking.", pendingName);
    return;
  }

  EnterCriticalSection(&g_msgMutex);
  // Names the speaker, so its bubble and the NPC's actions go to that squad
  // member. A line of only a mark, such as !end, shows no bubble but still
  // names the speaker
  g_messageQueue.push_back(
      "PLAYER_SAY: " + (speaker ? playerName + ": " : std::string()) +
      (marked ? WithoutActionMark(text) : text));
  LeaveCriticalSection(&g_msgMutex);

  std::string primaryId = npcName + "|" + handleStr;
  std::string npcsJson = "\"" + EscapeJSON(primaryId) + "\"";
  std::string nearbyFullJson = "";

  float searchRadius = g_proximityRadius;
  if (mode == "whisper")
    searchRadius = g_visionRange; // NPCs can see you even if you whisper
  else if (mode == "yell")
    searchRadius = g_yellRadius;

  Character *targetNpc = KeyedCharacter(targetKey);
  if (world && speaker) {
    try {
      Character *player = speaker;
      const auto &chars = world->getCharacterUpdateList();
      for (auto it = chars.begin(); it != chars.end(); ++it) {
        Character *other = *it;
        if (other && (uintptr_t)other > 0x1000 && other != player &&
            other != targetNpc) {
          float dist = player->getPosition().distance(other->getPosition());
          if (dist < searchRadius) {
            LogNpcRole(other);
            std::string o_name = other->getName();
            unsigned int o_key = HandleKey(other);
            std::string o_npcId = GetNpcId(other);
            npcsJson +=
                ", \"" + EscapeJSON(o_name) + "|" + ToString(o_key) + "\"";

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

            if (!g_originFactions.count(o_npcId) && faction &&
                !faction->isThePlayer())
              g_originFactions[o_npcId] = factionName;

            std::string o_gender = other->isFemale() ? "female" : "male";

            if (!nearbyFullJson.empty())
              nearbyFullJson += ",";
            nearbyFullJson += "{\"name\":\"" + EscapeJSON(other->getName()) +
                              "\", \"id\":\"" + ToString(o_key) +
                              "\", \"npc_id\":\"" + EscapeJSON(o_npcId) +
                              "\", \"race\":\"" + EscapeJSON(raceName) +
                              "\", \"faction\":\"" + EscapeJSON(factionName) +
                              "\", \"gender\":\"" + EscapeJSON(o_gender) +
                              "\", \"template\":\"" +
                              EscapeJSON(other->data ? other->data->name
                                                     : std::string()) +
                              "\", \"template_id\":\"" +
                              EscapeJSON(other->data ? other->data->stringID
                                                     : std::string()) +
                              "\", \"unique\":" +
                              (other->isUnique() ? "true" : "false") +
                              ", \"in_player_faction\":" +
                              (faction && faction->isThePlayer() ? "true"
                                                                 : "false") +
                              ", " + RoleJson(other) + ", " +
                              ProfileJson(other) +
                              ", \"dist\":" + ToString((int)dist) + "}";
          }
        }
      }
    } catch (...) {
      Log(LOG_WARN, "CHAT: Exception during proximity check.");
    }
  }

  std::string detailedContext = "{}";
  if (targetNpc) {
    detailedContext = GetDetailedContext(targetNpc);
    LogFactionList();
    LogNpcRole(targetNpc);
  }
  std::string speakerContext =
      speaker ? GetDetailedContext(speaker, "player") : "{}";

  std::string json =
      "{\"npc\": \"" + EscapeJSON(npcName) + "\", \"npcs\": [" + npcsJson +
      "], \"nearby\": [" + nearbyFullJson + "], \"message\": \"" +
      EscapeJSON(text) + "\", \"player\": \"" + EscapeJSON(playerName) +
      "\", \"mode\": \"" + mode + "\", \"context\": " + detailedContext +
      ", \"speaker\": " + speakerContext +
      ", \"events\": " + TakeGameEvents() +
      ", \"changed_towns\": " + ChangedTowns() + "}";

  ChatTask *task = new ChatTask();
  task->json = json;
  task->npcName = npcName;
  task->handleStr = handleStr;
  task->action = actionLine;
  CreateThread(NULL, 0, ChatResponseThread, task, 0, NULL);
}

void OnChatCancelClick(MyGUI::Widget *sender) { CloseChatUI(); }
void OnRadiantClick(MyGUI::Widget *sender) {
  g_triggerRadiant = true;
  CloseChatUI();
}

void OnChatWindowButtonPressed(MyGUI::Window *sender, const std::string &name) {
  if (name == "close")
    CloseChatUI();
}

static void ShowChatSpeaker() {
  Character *member = g_chatSpeakers[g_chatSpeakerIndex].getCharacter();
  g_chatSpeakerBtn->setCaption(
      Utf8ToWide(member ? member->getName() : "?").c_str());
}

void OnChatSpeakerClick(MyGUI::Widget *sender) {
  g_chatSpeakerIndex = (g_chatSpeakerIndex + 1) % g_chatSpeakers.size();
  ShowChatSpeaker();
}

void CreateChatUI(const std::string &npcName, const std::string &handleStr) {
  MyGUI::Gui *gui = MyGUI::Gui::getInstancePtr();
  if (!gui)
    return;
  if (g_chatWindow)
    CloseChatUI();

  g_chatTargetNameStr = npcName;
  g_chatTargetHandleStr = handleStr;
  g_chatJustOpened = true;

  unsigned int targetKey = (unsigned int)strtoul(handleStr.c_str(), NULL, 10);
  std::vector<Character *> squad;
  GetCurrentSquad(squad);
  g_chatSpeakers.clear();
  g_chatSpeakerIndex = 0;
  for (size_t i = 0; i < squad.size(); ++i) {
    unsigned int key = HandleKey(squad[i]);
    if (key == targetKey)
      continue;
    if (key == g_lastSpeakerKey)
      g_chatSpeakerIndex = g_chatSpeakers.size();
    g_chatSpeakers.push_back(squad[i]->getHandle());
  }

  std::string actualNpcName = npcName;
  g_chatWindow = gui->createWidgetReal<MyGUI::Window>(
      "Kenshi_WindowCX", 0.1875f, 0.4f, 0.625f, 0.18f, MyGUI::Align::Center,
      "Window", "SentientSands_ChatWindow");
  g_chatWindow->setCaption(
      Utf8ToWide(T("Talking to: ") + actualNpcName).c_str());
  g_chatWindow->eventWindowButtonPressed +=
      MyGUI::newDelegate(OnChatWindowButtonPressed);
  MyGUI::Widget *client = g_chatWindow->getClientWidget();
  g_chatLabel = client->createWidgetReal<MyGUI::TextBox>(
      "Kenshi_TextboxStandardText", 0.40f, 0.05f, 0.55f, 0.2f,
      MyGUI::Align::Top | MyGUI::Align::HStretch, "SentientSands_ChatLabel");
  g_chatLabel->setCaption(
      Utf8ToWide(T("Message for ") + actualNpcName + ":").c_str());

  if (!g_chatSpeakers.empty()) {
    g_chatSpeakerBtn = client->createWidgetReal<MyGUI::Button>(
        "Kenshi_Button1", 0.05f, 0.05f, 0.165f, 0.22f,
        MyGUI::Align::Top | MyGUI::Align::Left, "SentientSands_ChatSpeakerBtn");
    g_chatSpeakerBtn->eventMouseButtonClick +=
        MyGUI::newDelegate(OnChatSpeakerClick);
    ShowChatSpeaker();
  }
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
