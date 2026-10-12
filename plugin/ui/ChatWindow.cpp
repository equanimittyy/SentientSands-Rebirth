#include "ChatWindow.h"
#include "BarterWindow.h"
#include "CheatWindow.h"
#include "HelpWindow.h"
#include "OfferWindow.h"
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
#include <mygui/MyGUI_Delegate.h>
#include <mygui/MyGUI_EditBox.h>
#include <mygui/MyGUI_Gui.h>
#include <mygui/MyGUI_InputManager.h>
#include <mygui/MyGUI_TextBox.h>
#include <mygui/MyGUI_TextIterator.h>
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
MyGUI::Button *g_chatTargetBtn = nullptr;
std::vector<hand> g_chatTargets;
size_t g_chatTargetIndex = 0;
static hand g_chosenChatTarget;
std::string g_chatTargetHandleStr = "";
std::string g_chatTargetNameStr = "";
size_t g_lastChatModeIndex = 1;
bool g_chatJustOpened = false;
// Guarded by g_msgMutex, because the reply thread of a chat line sets them
std::string g_actionPendingName;
unsigned int g_actionNpcKey = 0;
std::string g_offerPendingName;
MyGUI::TextBox *g_chatThreadHeader = nullptr;
MyGUI::EditBox *g_chatHistoryText = nullptr;
MyGUI::Button *g_chatBarterBtn = nullptr;
std::string g_chatBarterThread;
int g_chatHistoryRequest = 0;
const float CHAT_INPUT_HEIGHT = 0.18f;
const float CHAT_HEADER_HEIGHT = 0.035f;
const float CHAT_HISTORY_HEIGHT = 0.15f;

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
    g_chatTargetBtn = nullptr;
    g_chatThreadHeader = nullptr;
    g_chatHistoryText = nullptr;
    g_chatBarterBtn = nullptr;
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

static void SettleActionDialogue(ChatTask *t, const std::string &response) {
  bool open = GetJsonValue(response, "action_dialogue").find("true") == 0;
  bool offered = GetJsonValue(response, "offer").find("true") == 0;
  EnterCriticalSection(&g_msgMutex);
  if (t->action)
    g_actionPendingName.clear();
  // Set before the popup opens, because the popup waits for the reply lines
  if (offered)
    g_offerPendingName = t->npcName;
  g_actionNpcKey =
      open ? (unsigned int)strtoul(t->handleStr.c_str(), NULL, 10) : 0;
  LeaveCriticalSection(&g_msgMutex);
}

DWORD WINAPI ChatResponseThread(LPVOID lpParam) {
  ChatTask *t = (ChatTask *)lpParam;
  if (!t->offerAnswer.empty())
    PostToPythonWithResponse(L"/offer", t->offerAnswer);
  Log(LOG_INFO, "CHAT: Sending chat request for " + t->npcName);
  // The server picks the NPC that answers a yell, so it shows these for that
  // NPC
  if (!t->yell) {
    NotifyChatStatus("{name} is thinking...", t->npcName);
    EnterCriticalSection(&g_msgMutex);
    g_messageQueue.push_back("NPC_SAY: " + t->npcName + "|" + t->handleStr +
                             ": ...");
    LeaveCriticalSection(&g_msgMutex);
  }

  std::string response = PostToPythonWithResponse(L"/chat", t->json);
  SettleActionDialogue(t, response);

  std::string error = GetJsonValue(response, "error");
  if (response.empty() || !error.empty()) {
    Log(LOG_WARN, "CHAT: No reply from server for " + t->npcName +
                      (error.empty() ? "" : ": " + error));
    NotifyChatStatus(
        "{name} could not respond. (Something went wrong, is SSR configured?)",
        t->npcName);
    // The barter window waits for its turn, which the server sends only with
    // a reply
    if (t->barter) {
      EnterCriticalSection(&g_msgMutex);
      g_messageQueue.push_back("CMD: BARTER_TURN: error");
      LeaveCriticalSection(&g_msgMutex);
    }
    delete t;
    return 0;
  }
  // The server sends the reply and its actions through the pipe, and paces the lines
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

void SetOfferPending(const std::string &npcName) {
  EnterCriticalSection(&g_msgMutex);
  g_offerPendingName = npcName;
  LeaveCriticalSection(&g_msgMutex);
}

std::string CurrentChatMode() {
  const char *modes[] = {"whisper", "talk", "yell"};
  return g_lastChatModeIndex < 3 ? modes[g_lastChatModeIndex] : "talk";
}

void OnChatSendClick(MyGUI::Widget *sender) {
  if (!g_chatInput)
    return;
  std::string text = g_chatInput->getCaption().asUTF8();
  if (text.empty()) {
    CloseChatUI();
    return;
  }

  std::string mode = CurrentChatMode();
  std::string npcName = g_chatTargetNameStr;
  std::string handleStr = g_chatTargetHandleStr;
  GameWorld *world = *ppWorld;

  Character *target =
      KeyedCharacter((unsigned int)strtoul(handleStr.c_str(), NULL, 10));
  Character *speaker = nullptr;
  if (g_chatSpeakerIndex < g_chatSpeakers.size())
    speaker = g_chatSpeakers[g_chatSpeakerIndex].getCharacter();
  if (!speaker && world && world->player) {
    lektor<Character *> &characters = world->player->playerCharacters;
    for (uint32_t i = 0; !speaker && i < characters.size(); ++i)
      if (characters[i] != target)
        speaker = characters[i];
  }
  if (speaker)
    g_lastSpeakerKey = HandleKey(speaker);

  if (text == "/cheat" || text == "/cheats") {
    CloseChatUI();
    ShowCheatUI(target);
    return;
  }

  if (text == "/help") {
    CloseChatUI();
    CreateHelpUI();
    return;
  }

  SendChatLine(npcName, handleStr, speaker, text, mode, "");
}

bool SendChatLine(const std::string &npcName, const std::string &handleStr,
                  Character *speaker, const std::string &text,
                  const std::string &mode, const std::string &offerAnswer,
                  const std::string &barterJson) {
  GameWorld *world = *ppWorld;
  std::string playerName = speaker ? speaker->getName() : "Drifter";
  unsigned int targetKey = (unsigned int)strtoul(handleStr.c_str(), NULL, 10);
  Character *targetNpc = KeyedCharacter(targetKey);
  std::string downName;
  if (speaker && speaker->isUnconcious())
    downName = playerName;
  else if (targetNpc && targetNpc->isUnconcious())
    downName = npcName;
  // A test command is never said, so it still reaches the server
  bool said = text.compare(0, 1, "/") != 0;
  if (!downName.empty() && said) {
    CloseChatUI();
    NotifyChatStatus("{name} is unconscious.", downName);
    return false;
  }
  bool marked = IsActionMark(text);
  bool beyondTalkRange =
      said && speaker && targetNpc &&
      speaker->getPosition().distance(targetNpc->getPosition()) >=
          g_proximityRadius;
  EnterCriticalSection(&g_msgMutex);
  std::string pendingName = g_actionPendingName;
  std::string offerName = g_offerPendingName;
  bool actionLine =
      marked || (g_actionNpcKey != 0 && targetKey == g_actionNpcKey);
  // A plain yell goes to each NPC in Yell range, not only to its target
  bool tooFar = beyondTalkRange && (mode != "yell" || actionLine);
  // A second line could bring a second offer, so an action dialogue line
  // holds every chat until its reply arrives
  if (!tooFar && pendingName.empty() && offerName.empty() && actionLine)
    g_actionPendingName = npcName;
  LeaveCriticalSection(&g_msgMutex);
  CloseChatUI();
  if (!offerName.empty()) {
    NotifyChatStatus("Answer {name}'s offer first.", offerName);
    // The pipe drops a message when it finds no instance in time, so the
    // server sends the popup again, or says that it holds no offer
    if (!g_offerWindow)
      AsyncPostToPython(L"/offer", "{\"answer\": \"show\"}");
    return false;
  }
  if (!pendingName.empty()) {
    NotifyChatStatus("{name} is still thinking.", pendingName);
    return false;
  }
  if (tooFar) {
    NotifyChatStatus("{name} is too far away.", npcName);
    return false;
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
                              "\", \"animal\":" +
                              (other->isAnimal() ? "true" : "false") +
                              ", \"faction\":\"" + EscapeJSON(factionName) +
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
      ", \"speaker\": " + speakerContext + ", \"speaker_key\": \"" +
      (speaker ? ToString(HandleKey(speaker)) : std::string()) + "\"" +
      ", \"events\": " + TakeGameEvents() +
      ", \"changed_towns\": " + ChangedTowns() +
      (barterJson.empty() ? "" : ", \"barter\": " + barterJson) + "}";

  ChatTask *task = new ChatTask();
  task->json = json;
  task->npcName = npcName;
  task->handleStr = handleStr;
  task->action = actionLine;
  task->yell = mode == "yell";
  task->barter = !barterJson.empty();
  task->offerAnswer = offerAnswer;
  CreateThread(NULL, 0, ChatResponseThread, task, 0, NULL);
  return true;
}

void OnChatCancelClick(MyGUI::Widget *sender) { CloseChatUI(); }

static void OnChatBarterClick(MyGUI::Widget *sender) {
  std::string npcName = g_chatTargetNameStr;
  std::string handleStr = g_chatTargetHandleStr;
  std::string thread = g_chatBarterThread;
  CloseChatUI();
  ShowBarterUI(npcName, handleStr, thread);
}
void OnRadiantClick(MyGUI::Widget *sender) {
  g_triggerRadiant = true;
  CloseChatUI();
}

void OnChatWindowButtonPressed(MyGUI::Window *sender, const std::string &name) {
  if (name == "close")
    CloseChatUI();
}

struct ChatHistoryTask {
  std::string json;
  int request;
};

DWORD WINAPI ChatHistoryThread(LPVOID lpParam) {
  ChatHistoryTask *t = (ChatHistoryTask *)lpParam;
  std::string response = PostToPythonWithResponse(L"/chat_thread", t->json);
  EnterCriticalSection(&g_msgMutex);
  g_messageQueue.push_back("CMD: CHAT_HISTORY: " + ToString(t->request) + "|" +
                           response);
  LeaveCriticalSection(&g_msgMutex);
  delete t;
  return 0;
}

static void SetChatThreadHeader(const std::string &text) {
  g_chatThreadHeader->setCaption(
      MyGUI::TextIterator::toTagsString(Utf8ToWide(text)));
}

static void RequestChatHistory() {
  SetChatThreadHeader(T("Loading the conversation..."));
  Character *target = KeyedCharacter(
      (unsigned int)strtoul(g_chatTargetHandleStr.c_str(), NULL, 10));
  ChatHistoryTask *t = new ChatHistoryTask();
  t->json = "{\"npc_id\":\"" +
            EscapeJSON(target ? GetNpcId(target) : std::string()) + "\"}";
  t->request = ++g_chatHistoryRequest;
  CreateThread(NULL, 0, ChatHistoryThread, t, 0, NULL);
}

void SetChatHistory(const std::string &data) {
  size_t sep = data.find('|');
  if (!g_chatThreadHeader || sep == std::string::npos ||
      atoi(data.c_str()) != g_chatHistoryRequest)
    return;
  std::string reply = data.substr(sep + 1);
  if (GetJsonValue(reply, "status") != "ok") {
    SetChatThreadHeader(T("Could not load the conversation."));
    return;
  }
  if (GetJsonValue(reply, "open").find("true") != 0) {
    SetChatThreadHeader(T("No open conversation."));
    return;
  }
  SetChatThreadHeader(GetJsonValue(reply, "type") + ": " +
                      GetJsonValue(reply, "title"));
  if (GetJsonValue(reply, "type") == "Barter") {
    g_chatBarterThread = reply;
    g_chatBarterBtn->setVisible(true);
  }
  g_chatHistoryText->setOnlyText(
      Utf8ToWide(GetJsonValue(reply, "lines")).c_str());
  // The view follows the cursor, so the newest line shows
  g_chatHistoryText->setTextCursor(g_chatHistoryText->getTextLength());
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

void SelectChatSpeaker(const hand &member) {
  if (!g_chatWindow || member == g_chatTargets[g_chatTargetIndex])
    return;
  for (size_t i = 0; i < g_chatSpeakers.size(); ++i) {
    if (g_chatSpeakers[i] == member) {
      g_chatSpeakerIndex = i;
      ShowChatSpeaker();
      return;
    }
  }
}

static void FillChatSpeakers(unsigned int preferredKey) {
  std::vector<Character *> squad;
  GetCurrentSquad(squad);
  g_chatSpeakers.clear();
  g_chatSpeakerIndex = 0;
  for (size_t i = 0; i < squad.size(); ++i) {
    if (HandleKey(squad[i]) == preferredKey)
      g_chatSpeakerIndex = g_chatSpeakers.size();
    g_chatSpeakers.push_back(squad[i]->getHandle());
  }
}

static void ShowChatTarget() {
  Character *target = g_chatTargets[g_chatTargetIndex].getCharacter();
  g_talkTargetHand = g_chatTargets[g_chatTargetIndex];
  g_chatTargetNameStr = target ? target->getName() : "?";
  g_chatTargetHandleStr = target ? ToString(HandleKey(target)) : "";
  g_chatWindow->setCaption(
      Utf8ToWide(T("Talking to: ") + g_chatTargetNameStr).c_str());
  g_chatTargetBtn->setCaption(Utf8ToWide(g_chatTargetNameStr).c_str());

  Character *speaker = g_chatSpeakerIndex < g_chatSpeakers.size()
                           ? g_chatSpeakers[g_chatSpeakerIndex].getCharacter()
                           : nullptr;
  FillChatSpeakers(speaker ? HandleKey(speaker) : g_lastSpeakerKey);
  g_chatSpeakerBtn->setVisible(!g_chatSpeakers.empty());
  if (!g_chatSpeakers.empty())
    ShowChatSpeaker();

  g_chatBarterBtn->setVisible(false);
  g_chatHistoryText->setOnlyText("");
  RequestChatHistory();
}

static void OnChatTargetClick(MyGUI::Widget *sender) {
  g_chatTargetIndex = (g_chatTargetIndex + 1) % g_chatTargets.size();
  g_chosenChatTarget = g_chatTargets[g_chatTargetIndex];
  ShowChatTarget();
}

void ForgetChatTarget() { g_chosenChatTarget = hand(); }

static void AddChatHistory(MyGUI::Widget *client, float top, float height) {
  g_chatHistoryText = client->createWidgetReal<MyGUI::EditBox>(
      "Kenshi_WordWrap", 0.05f, top, 0.9f, height,
      MyGUI::Align::Top | MyGUI::Align::HStretch, "SentientSands_ChatHistory");
  g_chatHistoryText->setEditMultiLine(true);
  g_chatHistoryText->setEditWordWrap(true);
  g_chatHistoryText->setEditReadOnly(true);
  g_chatHistoryText->setVisibleVScroll(true);
  // The default cap of 2048 characters would cut the newest lines
  g_chatHistoryText->setMaxTextLength(262144);
  g_chatHistoryText->setTextAlign(MyGUI::Align::Left | MyGUI::Align::Top);
  g_chatHistoryText->setFontHeight(18);
}

static void BuildChatWindow(MyGUI::Gui *gui) {
  float panel = CHAT_HEADER_HEIGHT + CHAT_HISTORY_HEIGHT;
  g_chatWindow = gui->createWidgetReal<MyGUI::Window>(
      "Kenshi_WindowCX", 0.1875f, 0.4f - panel, 0.625f,
      CHAT_INPUT_HEIGHT + panel, MyGUI::Align::Center, "Window",
      "SentientSands_ChatWindow");
  g_chatWindow->eventWindowButtonPressed +=
      MyGUI::newDelegate(OnChatWindowButtonPressed);
  MyGUI::Widget *client = g_chatWindow->getClientWidget();
  // unit turns a share of the screen into a share of the client, so the panel
  // gets its screen height and the input rows keep their pixel height
  float unit = (float)g_chatWindow->getHeight() /
               (CHAT_INPUT_HEIGHT + panel) / client->getHeight();
  float header = CHAT_HEADER_HEIGHT * unit;
  float top = panel * unit;
  float rows = 1.0f - top;

  g_chatThreadHeader = client->createWidgetReal<MyGUI::TextBox>(
      "Kenshi_TextboxStandardText", 0.05f, 0.0f, 0.9f, header,
      MyGUI::Align::Top | MyGUI::Align::HStretch,
      "SentientSands_ChatThreadHeader");
  g_chatThreadHeader->setTextAlign(MyGUI::Align::Left | MyGUI::Align::VCenter);
  g_chatThreadHeader->setTextColour(MyGUI::Colour(1.0f, 0.9f, 0.5f));
  AddChatHistory(client, header, top - header);

  g_chatLabel = client->createWidgetReal<MyGUI::TextBox>(
      "Kenshi_TextboxStandardText", 0.40f, top + 0.05f * rows, 0.37f,
      0.2f * rows, MyGUI::Align::Top | MyGUI::Align::HStretch,
      "SentientSands_ChatLabel");
  g_chatLabel->setTextAlign(MyGUI::Align::Right | MyGUI::Align::VCenter);
  g_chatLabel->setCaption(Utf8ToWide(T("Message for ")).c_str());

  g_chatSpeakerBtn = client->createWidgetReal<MyGUI::Button>(
      "Kenshi_Button1", 0.05f, top + 0.05f * rows, 0.165f, 0.22f * rows,
      MyGUI::Align::Top | MyGUI::Align::Left, "SentientSands_ChatSpeakerBtn");
  g_chatSpeakerBtn->eventMouseButtonClick +=
      MyGUI::newDelegate(OnChatSpeakerClick);

  g_chatTargetBtn = client->createWidgetReal<MyGUI::Button>(
      "Kenshi_Button1", 0.785f, top + 0.05f * rows, 0.165f, 0.22f * rows,
      MyGUI::Align::Top | MyGUI::Align::Right, "SentientSands_ChatTargetBtn");
  g_chatTargetBtn->eventMouseButtonClick +=
      MyGUI::newDelegate(OnChatTargetClick);

  g_chatBarterBtn = client->createWidgetReal<MyGUI::Button>(
      "Kenshi_Button1", 0.23f, top + 0.05f * rows, 0.15f, 0.22f * rows,
      MyGUI::Align::Top | MyGUI::Align::Left, "SentientSands_ChatBarterBtn");
  g_chatBarterBtn->setCaption(Utf8ToWide(T("Barter")).c_str());
  g_chatBarterBtn->eventMouseButtonClick +=
      MyGUI::newDelegate(OnChatBarterClick);
  g_chatBarterBtn->setVisible(false);

  g_chatInput = client->createWidgetReal<MyGUI::EditBox>(
      "Kenshi_EditBox", 0.05f, top + 0.35f * rows, 0.9f, 0.25f * rows,
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
        "Kenshi_Button1", btnX, top + 0.75f * rows, 0.12f, 0.2f * rows,
        MyGUI::Align::Bottom | MyGUI::Align::Left,
        "SentientSands_ChatMode_" + ToString(i));
    g_chatModeBtns[i]->setCaption(Utf8ToWide(T(btnLabelKeys[i])).c_str());
    g_chatModeBtns[i]->eventMouseButtonClick +=
        MyGUI::newDelegate(OnModeButtonClick);
    btnX += 0.13f;
  }
  UpdateModeButtons();

  MyGUI::Button *sendBtn = client->createWidgetReal<MyGUI::Button>(
      "Kenshi_Button1", 0.44f, top + 0.75f * rows, 0.17f, 0.2f * rows,
      MyGUI::Align::Bottom | MyGUI::Align::Right, "SentientSands_ChatSendBtn");
  sendBtn->setCaption(Utf8ToWide(T("Send")).c_str());
  sendBtn->eventMouseButtonClick += MyGUI::newDelegate(OnChatSendClick);

  MyGUI::Button *cancelBtn = client->createWidgetReal<MyGUI::Button>(
      "Kenshi_Button1", 0.62f, top + 0.75f * rows, 0.17f, 0.2f * rows,
      MyGUI::Align::Bottom | MyGUI::Align::Right,
      "SentientSands_ChatCancelBtn");
  cancelBtn->setCaption(Utf8ToWide(T("Cancel")).c_str());
  cancelBtn->eventMouseButtonClick += MyGUI::newDelegate(OnChatCancelClick);

  MyGUI::Button *radiantBtn = client->createWidgetReal<MyGUI::Button>(
      "Kenshi_Button1", 0.80f, top + 0.75f * rows, 0.17f, 0.2f * rows,
      MyGUI::Align::Bottom | MyGUI::Align::Right,
      "SentientSands_ChatRadiantBtn");
  radiantBtn->setCaption(Utf8ToWide(T("Trigger Radiant")).c_str());
  radiantBtn->eventMouseButtonClick += MyGUI::newDelegate(OnRadiantClick);
}

void CreateChatUI(Character *npc) {
  MyGUI::Gui *gui = MyGUI::Gui::getInstancePtr();
  GameWorld *world = *ppWorld;
  if (!gui || !world || !world->player)
    return;
  if (g_chatWindow)
    CloseChatUI();

  std::vector<Character *> squad;
  GetCurrentSquad(squad);
  g_chatTargets.clear();
  if (npc)
    g_chatTargets.push_back(npc->getHandle());
  lektor<Character *> &characters = world->player->playerCharacters;
  // A lone character would talk to itself
  for (uint32_t i = 0; characters.size() > 1 && i < characters.size(); ++i) {
    Character *c = characters[i];
    if (!c)
      continue;
    for (size_t j = 0; j < squad.size(); ++j) {
      if (c->getPosition().distance(squad[j]->getPosition()) <
          g_proximityRadius) {
        g_chatTargets.push_back(c->getHandle());
        break;
      }
    }
  }
  if (g_chatTargets.empty())
    return;

  g_chatTargetIndex = 0;
  for (size_t i = 0; i < g_chatTargets.size(); ++i) {
    if (g_chatTargets[i] == g_chosenChatTarget)
      g_chatTargetIndex = i;
  }
  g_chatSpeakers.clear();
  g_chatJustOpened = true;
  BuildChatWindow(gui);
  ShowChatTarget();
  SelectChatSpeaker(world->player->selectedCharacter);
  // Only a button press may make a character talk to itself
  if (!g_chatSpeakers.empty() &&
      g_chatSpeakers[g_chatSpeakerIndex] == g_chatTargets[g_chatTargetIndex]) {
    if (g_chatSpeakers.size() > 1) {
      OnChatSpeakerClick(NULL);
    } else {
      // The send then picks another player character
      g_chatSpeakers.clear();
      g_chatSpeakerBtn->setVisible(false);
    }
  }
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
