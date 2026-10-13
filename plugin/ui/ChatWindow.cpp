#include "ChatWindow.h"
#include "BarterWindow.h"
#include "CheatWindow.h"
#include "HelpWindow.h"
#include "OfferWindow.h"
#include "../core/Comm.h"
#include "../game/Context.h"
#include "../game/Probes.h"
#include "../core/Globals.h"
#include "../core/Utils.h"

#include <kenshi/Character.h>
#include <kenshi/Dialogue.h>
#include <kenshi/Faction.h>
#include <kenshi/GameData.h>
#include <kenshi/GameWorld.h>
#include <kenshi/Kenshi.h>
#include <kenshi/PlayerInterface.h>
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

struct ChatTask {
  std::string json;
  std::string npcName;
  unsigned int npcKey;
  bool action;
  bool yell;
  bool barter;
  // The decline goes to /offer before the reply line, or the server would
  // still hold the offer and drop the line
  std::string offerAnswer;
};

static const struct {
  const char *mode;
  const char *label;
} CHAT_MODES[] = {{"whisper", "Whisper"}, {"talk", "Talk"}, {"yell", "Yell"}};

static void OnChatSendClick(MyGUI::Widget *sender);
static void OnModeButtonClick(MyGUI::Widget *sender);
static void UpdateModeButtons();

MyGUI::Window *g_chatWindow = nullptr;
static MyGUI::EditBox *g_chatInput = nullptr;
static MyGUI::Button *g_chatModeBtns[3] = {nullptr, nullptr, nullptr};
static MyGUI::Button *g_chatSpeakerBtn = nullptr;
static std::vector<hand> g_chatSpeakers;
static size_t g_chatSpeakerIndex = 0;
// In memory only, so a new game session starts on the first squad member
static unsigned int g_lastSpeakerKey = 0;
static MyGUI::Button *g_chatTargetBtn = nullptr;
static std::vector<hand> g_chatTargets;
static size_t g_chatTargetIndex = 0;
static hand g_chosenChatTarget;
// Ending a vanilla dialogue also clears the AI goals of the NPC, so an NPC
// selected while the window is open keeps it until a line goes to the NPC
static hand g_switchedNpc;
static unsigned int g_chatTargetKey = 0;
static std::string g_chatTargetNameStr;
static size_t g_lastChatModeIndex = 1;
static bool g_chatJustOpened = false;
// Guarded by g_msgMutex, because the reply thread of a chat line sets them
static std::string g_actionPendingName;
static unsigned int g_actionNpcKey = 0;
static std::string g_offerPendingName;
static MyGUI::TextBox *g_chatThreadHeader = nullptr;
static MyGUI::EditBox *g_chatHistoryText = nullptr;
static MyGUI::Button *g_chatBarterBtn = nullptr;
static std::string g_chatBarterThread;
static int g_chatHistoryRequest = 0;
static const float CHAT_INPUT_HEIGHT = 0.18f;
static const float CHAT_HEADER_HEIGHT = 0.035f;
static const float CHAT_HISTORY_HEIGHT = 0.15f;

static void CloseChatUI() {
  if (!g_chatWindow)
    return;
  DestroyWindow(g_chatWindow);
  g_chatInput = nullptr;
  for (int i = 0; i < 3; i++)
    g_chatModeBtns[i] = nullptr;
  g_chatSpeakerBtn = nullptr;
  g_chatTargetBtn = nullptr;
  g_chatThreadHeader = nullptr;
  g_chatHistoryText = nullptr;
  g_chatBarterBtn = nullptr;
}

static CloseAction g_chatClose = {CloseChatUI};

static void NotifyChatStatus(const std::string &key,
                             const std::string &npcName) {
  NotifyText(Fill(T(key), "{name}", npcName));
}

// A refused line still answers its offer, or the server would hold the offer
// and refuse each later line
static bool RefuseLine(const std::string &key, const std::string &name,
                       const std::string &offerAnswer) {
  NotifyChatStatus(key, name);
  if (!offerAnswer.empty())
    AsyncPostToPython(L"/offer", offerAnswer);
  return false;
}

// A line without a key goes by the name alone
static std::string KeyText(unsigned int key) {
  return key ? ToString(key) : std::string();
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
  bool open = JsonTrue(response, "action_dialogue");
  bool offered = JsonTrue(response, "offer");
  EnterCriticalSection(&g_msgMutex);
  if (t->action)
    g_actionPendingName.clear();
  // Set before the popup opens, because the popup waits for the reply lines
  if (offered)
    g_offerPendingName = t->npcName;
  g_actionNpcKey =
      open ? t->npcKey : 0;
  LeaveCriticalSection(&g_msgMutex);
}

static DWORD WINAPI ChatResponseThread(LPVOID lpParam) {
  ChatTask *t = (ChatTask *)lpParam;
  if (!t->offerAnswer.empty())
    PostToPythonWithResponse(L"/offer", t->offerAnswer);
  Log(LOG_INFO, "CHAT: Sending chat request for " + t->npcName);
  // The server picks the NPC that answers a yell, so it shows these for that
  // NPC
  if (!t->yell) {
    NotifyChatStatus("{name} is thinking...", t->npcName);
    QueueMessage("NPC_SAY: " + t->npcName + "|" + KeyText(t->npcKey) + ": ...");
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
    if (t->barter)
      QueueMessage("CMD: BARTER_TURN: error");
    delete t;
    return 0;
  }
  // The server sends the reply and its actions through the pipe, and paces the lines
  Log(LOG_INFO, "CHAT: Got response for " + t->npcName);

  delete t;
  return 0;
}

static void OnChatInputChange(MyGUI::EditBox *sender) {
  std::string text = sender->getOnlyText().asUTF8();
  bool first = g_chatJustOpened && !text.empty();
  if (first)
    g_chatJustOpened = false;
  // The press of the chat key that opened the window types its key
  bool hotkey = first && text.size() == 1 && g_chatHotkeyStr.size() == 1 &&
                toupper((unsigned char)text[0]) ==
                    toupper((unsigned char)g_chatHotkeyStr[0]);
  if (hotkey || text == "\\" || text == "\n" || text == "\r") {
    sender->setCaption("");
    return;
  }

  if (!text.empty() && (text.back() == '\n' || text.back() == '\r')) {
    while (!text.empty() && (text.back() == '\n' || text.back() == '\r'))
      text.pop_back();

    sender->setOnlyText(Utf8ToWide(text).c_str());
    OnChatSendClick(sender);
  }
}

static void OnChatInputAccept(MyGUI::EditBox *sender) {
  OnChatSendClick(sender);
}

void SetOfferPending(const std::string &npcName) {
  EnterCriticalSection(&g_msgMutex);
  g_offerPendingName = npcName;
  LeaveCriticalSection(&g_msgMutex);
}

std::string CurrentChatMode() {
  return g_lastChatModeIndex < 3 ? CHAT_MODES[g_lastChatModeIndex].mode
                                 : "talk";
}

// Vanilla dialogue would run alongside the AI chat ("double dialogue")
static void EndVanillaDialogue(Character *npc) {
  if (npc && npc->dialogue && (uintptr_t)npc->dialogue > 0x1000) {
    npc->dialogue->endDialogue(true);
    npc->dialogue->setInDialog(false);
  }
}

static void OnChatSendClick(MyGUI::Widget *sender) {
  if (!g_chatInput)
    return;
  std::string text = g_chatInput->getOnlyText().asUTF8();
  if (text.empty()) {
    CloseChatUI();
    return;
  }

  std::string mode = CurrentChatMode();
  GameWorld *world = *ppWorld;
  Character *target = KeyedCharacter(g_chatTargetKey);
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

  if (SendChatLine(g_chatTargetNameStr, g_chatTargetKey, speaker, text, mode,
                   "") &&
      target && target->getHandle() == g_switchedNpc)
    EndVanillaDialogue(target);
}

bool SendChatLine(const std::string &npcName, unsigned int targetKey,
                  Character *speaker, const std::string &text,
                  const std::string &mode, const std::string &offerAnswer,
                  const std::string &barterJson) {
  GameWorld *world = *ppWorld;
  std::string playerName = speaker ? speaker->getName() : "Drifter";
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
    return RefuseLine("{name} is unconscious.", downName, offerAnswer);
  }
  bool marked = IsActionMark(text);
  float dist = speaker && targetNpc
                   ? speaker->getPosition().distance(targetNpc->getPosition())
                   : 0.0f;
  float range = mode == "whisper" ? g_whisperRadius : g_proximityRadius;
  bool beyondRange = said && dist >= range;
  EnterCriticalSection(&g_msgMutex);
  std::string pendingName = g_actionPendingName;
  std::string offerName = g_offerPendingName;
  bool actionLine =
      marked || (g_actionNpcKey != 0 && targetKey == g_actionNpcKey);
  // A plain yell goes to each NPC in Yell range, not only to its target
  bool tooFar = beyondRange && (mode != "yell" || actionLine);
  // A second line could bring a second offer, so an action dialogue line
  // holds every chat until its reply arrives
  if (!tooFar && pendingName.empty() && offerName.empty() && actionLine)
    g_actionPendingName = npcName;
  LeaveCriticalSection(&g_msgMutex);
  CloseChatUI();
  if (!offerName.empty()) {
    // The pipe drops a message when it finds no instance in time, so the
    // server sends the popup again, or says that it holds no offer
    if (!g_offerWindow)
      AsyncPostToPython(L"/offer", "{\"answer\": \"show\"}");
    return RefuseLine("Answer {name}'s offer first.", offerName, offerAnswer);
  }
  if (!pendingName.empty())
    return RefuseLine("{name} is still thinking.", pendingName, offerAnswer);
  if (tooFar) {
    Log(LOG_INFO, "CHAT: " + npcName + " is " + ToString((int)dist) +
                      " from " + playerName + ", beyond the range of " +
                      ToString((int)range));
    return RefuseLine("{name} is too far away.", npcName, offerAnswer);
  }
  // The server reads a yell at the speaker as a yell at everyone in range, so
  // a target beyond Yell range does not answer
  bool unheard = mode == "yell" && said && dist >= g_yellRadius;
  if (unheard) {
    Log(LOG_INFO, "CHAT: " + npcName + " is " + ToString((int)dist) +
                      " from " + playerName + ", beyond the Yell range of " +
                      ToString((int)g_yellRadius));
    NotifyChatStatus("{name} is too far away.", npcName);
  }
  Character *addressee = unheard ? speaker : targetNpc;
  std::string addresseeName = unheard ? playerName : npcName;
  unsigned int addresseeKey = unheard ? HandleKey(speaker) : targetKey;

  // Names the speaker, so its bubble and the NPC's actions go to that squad
  // member. A line of only a mark, such as !end, shows no bubble but still
  // names the speaker
  QueueMessage("PLAYER_SAY: " + (speaker ? playerName + ": " : std::string()) +
               (marked ? WithoutActionMark(text) : text));

  std::string primaryId = addresseeName + "|" + KeyText(addresseeKey);
  std::string npcsJson = "\"" + EscapeJSON(primaryId) + "\"";
  std::string nearbyFullJson = "";

  float searchRadius = g_proximityRadius;
  if (mode == "whisper")
    searchRadius = VISION_RANGE; // NPCs can see you even if you whisper
  else if (mode == "yell")
    searchRadius = g_yellRadius;

  if (world && speaker) {
    const auto &chars = world->getCharacterUpdateList();
    for (auto it = chars.begin(); it != chars.end(); ++it) {
      Character *other = *it;
      if (!other || (uintptr_t)other < 0x1000 || other == speaker ||
          other == addressee)
        continue;
      float dist = speaker->getPosition().distance(other->getPosition());
      if (dist >= searchRadius)
        continue;
      LogNpcRole(other);
      npcsJson += ", \"" + EscapeJSON(other->getName()) + "|" +
                  ToString(HandleKey(other)) + "\"";
      nearbyFullJson += (nearbyFullJson.empty() ? "{" : ", {") +
                        PartyFields(other) + ", \"faction\": \"" +
                        EscapeJSON(FactionName(CharacterFaction(other))) +
                        "\", \"dist\": " + ToString((int)dist) + "}";
    }
  }

  std::string detailedContext = "{}";
  if (addressee) {
    detailedContext = GetDetailedContext(addressee);
    LogFactionList();
    LogNpcRole(addressee);
  }
  std::string speakerContext =
      speaker ? GetDetailedContext(speaker, "player") : "{}";

  std::string json =
      "{\"npc\": \"" + EscapeJSON(addresseeName) + "\", \"npcs\": [" +
      npcsJson + "], \"nearby\": [" + nearbyFullJson + "], \"message\": \"" +
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
  task->npcKey = targetKey;
  task->action = actionLine;
  task->yell = mode == "yell";
  task->barter = !barterJson.empty();
  task->offerAnswer = offerAnswer;
  StartThread(ChatResponseThread, task);
  return true;
}

static void OnChatCancelClick(MyGUI::Widget *sender) { CloseChatUI(); }

static void OnChatBarterClick(MyGUI::Widget *sender) {
  std::string npcName = g_chatTargetNameStr;
  std::string thread = g_chatBarterThread;
  CloseChatUI();
  ShowBarterUI(npcName, g_chatTargetKey, thread);
}
static void OnRadiantClick(MyGUI::Widget *sender) {
  g_triggerRadiant = true;
  CloseChatUI();
}

static void SetChatThreadHeader(const std::string &text) {
  g_chatThreadHeader->setCaption(PlainText(text));
}

static void RequestChatHistory() {
  SetChatThreadHeader(T("Loading the conversation..."));
  Character *target = KeyedCharacter(g_chatTargetKey);
  PostForGameThread(L"/chat_thread",
                    "{\"npc_id\":\"" +
                        EscapeJSON(target ? GetNpcId(target) : std::string()) +
                        "\"}",
                    "CHAT_HISTORY", ToString(++g_chatHistoryRequest));
}

void SetChatHistory(const std::string &data) {
  std::string reply;
  if (!g_chatThreadHeader ||
      !TakeTaggedReply(data, g_chatHistoryRequest, reply))
    return;
  if (GetJsonValue(reply, "status") != "ok") {
    SetChatThreadHeader(T("Could not load the conversation."));
    return;
  }
  if (!JsonTrue(reply, "open")) {
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
  g_chatSpeakerBtn->setCaption(PlainText(member ? member->getName() : "?"));
}

static void OnChatSpeakerClick(MyGUI::Widget *sender) {
  g_chatSpeakerIndex = (g_chatSpeakerIndex + 1) % g_chatSpeakers.size();
  ShowChatSpeaker();
}

void SelectChatSpeaker(const hand &member) {
  g_lastSpeakerKey = HandleKey(member.getCharacter());
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
  g_chatTargetKey = target ? HandleKey(target) : 0;
  g_chatWindow->setCaption(PlainText(T("Talking to: ") + g_chatTargetNameStr));
  g_chatTargetBtn->setCaption(PlainText(g_chatTargetNameStr));

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

static void BuildChatWindow() {
  float panel = CHAT_HEADER_HEIGHT + CHAT_HISTORY_HEIGHT;
  MyGUI::Widget *client = OpenWindow(
      g_chatWindow, 0.1875f, 0.4f - panel, 0.625f, CHAT_INPUT_HEIGHT + panel,
      MyGUI::Align::Center, "Window", "SentientSands_ChatWindow", "",
      g_chatClose);
  // unit turns a share of the screen into a share of the client, so the panel
  // gets its screen height and the input rows keep their pixel height
  float unit = (float)g_chatWindow->getHeight() /
               (CHAT_INPUT_HEIGHT + panel) / client->getHeight();
  float header = CHAT_HEADER_HEIGHT * unit;
  float top = panel * unit;
  float rows = 1.0f - top;
  MyGUI::Align topLeft = MyGUI::Align::Top | MyGUI::Align::Left;
  MyGUI::Align topWide = MyGUI::Align::Top | MyGUI::Align::HStretch;
  MyGUI::Align bottomLeft = MyGUI::Align::Bottom | MyGUI::Align::Left;
  MyGUI::Align bottomRight = MyGUI::Align::Bottom | MyGUI::Align::Right;

  g_chatThreadHeader = AddLabel(client, "", 0.05f, 0.0f, 0.9f, header, topWide,
                                "SentientSands_ChatThreadHeader");
  g_chatThreadHeader->setTextColour(MyGUI::Colour(1.0f, 0.9f, 0.5f));
  g_chatHistoryText = AddTextView(client, 0.05f, header, 0.9f, top - header,
                                  topWide, "SentientSands_ChatHistory");

  AddLabel(client, T("Message for "), 0.40f, top + 0.05f * rows, 0.37f,
           0.2f * rows, topWide, "SentientSands_ChatLabel",
           MyGUI::Align::Right | MyGUI::Align::VCenter);
  g_chatSpeakerBtn =
      AddButton(client, "", 0.05f, top + 0.05f * rows, 0.165f, 0.22f * rows,
                topLeft, "SentientSands_ChatSpeakerBtn", OnChatSpeakerClick);
  g_chatTargetBtn = AddButton(client, "", 0.785f, top + 0.05f * rows, 0.165f,
                              0.22f * rows, MyGUI::Align::Top | MyGUI::Align::Right,
                              "SentientSands_ChatTargetBtn", OnChatTargetClick);
  g_chatBarterBtn =
      AddButton(client, T("Barter"), 0.23f, top + 0.05f * rows, 0.15f,
                0.22f * rows, topLeft, "SentientSands_ChatBarterBtn",
                OnChatBarterClick);
  g_chatBarterBtn->setVisible(false);

  g_chatInput = AddLineBox(client, 0.05f, top + 0.35f * rows, 0.9f,
                           0.25f * rows, topWide, "SentientSands_ChatInput");
  g_chatInput->eventEditTextChange += MyGUI::newDelegate(OnChatInputChange);
  g_chatInput->eventEditSelectAccept += MyGUI::newDelegate(OnChatInputAccept);
  MyGUI::InputManager::getInstance().setKeyFocusWidget(g_chatInput);

  for (int i = 0; i < 3; i++)
    g_chatModeBtns[i] =
        AddButton(client, "", 0.05f + i * 0.13f, top + 0.75f * rows, 0.12f,
                  0.2f * rows, bottomLeft,
                  "SentientSands_ChatMode_" + ToString(i), OnModeButtonClick);
  UpdateModeButtons();

  AddButton(client, T("Send"), 0.44f, top + 0.75f * rows, 0.17f, 0.2f * rows,
            bottomRight, "SentientSands_ChatSendBtn", OnChatSendClick);
  AddButton(client, T("Cancel"), 0.62f, top + 0.75f * rows, 0.17f, 0.2f * rows,
            bottomRight, "SentientSands_ChatCancelBtn", OnChatCancelClick);
  AddButton(client, T("Trigger Radiant"), 0.80f, top + 0.75f * rows, 0.17f,
            0.2f * rows, bottomRight, "SentientSands_ChatRadiantBtn",
            OnRadiantClick);
}

static void FillChatTargets(GameWorld *world, Character *npc) {
  std::vector<Character *> squad;
  GetCurrentSquad(squad);
  g_chatTargets.clear();
  if (npc)
    g_chatTargets.push_back(npc->getHandle());
  lektor<Character *> &characters = world->player->playerCharacters;
  // A lone character would talk to itself
  for (uint32_t i = 0; characters.size() > 1 && i < characters.size(); ++i) {
    Character *c = characters[i];
    for (size_t j = 0; c && j < squad.size(); ++j) {
      if (c->getPosition().distance(squad[j]->getPosition()) <
          g_proximityRadius) {
        g_chatTargets.push_back(c->getHandle());
        break;
      }
    }
  }
}

void SelectChatTarget(Character *npc) {
  g_chosenChatTarget = hand();
  if (!g_chatWindow)
    return;
  g_switchedNpc = npc->getHandle();
  FillChatTargets(*ppWorld, npc);
  g_chatTargetIndex = 0;
  ShowChatTarget();
}

void CreateChatUI(Character *npc) {
  GameWorld *world = *ppWorld;
  if (!MyGUI::Gui::getInstancePtr() || !world || !world->player)
    return;
  CloseChatUI();

  EndVanillaDialogue(npc);
  g_switchedNpc = hand();
  FillChatTargets(world, npc);
  if (g_chatTargets.empty())
    return;

  g_chatTargetIndex = 0;
  for (size_t i = 0; i < g_chatTargets.size(); ++i) {
    if (g_chatTargets[i] == g_chosenChatTarget)
      g_chatTargetIndex = i;
  }
  g_chatSpeakers.clear();
  g_chatJustOpened = true;
  BuildChatWindow();
  ShowChatTarget();
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

static void OnModeButtonClick(MyGUI::Widget *sender) {
  for (int i = 0; i < 3; i++) {
    if (sender == g_chatModeBtns[i]) {
      g_lastChatModeIndex = i;
      break;
    }
  }
  UpdateModeButtons();
}

static void UpdateModeButtons() {
  for (int i = 0; i < 3; i++) {
    if (!g_chatModeBtns[i])
      continue;
    std::string label = T(CHAT_MODES[i].label);
    g_chatModeBtns[i]->setCaption(
        PlainText(i == g_lastChatModeIndex ? "> " + label + " <" : label));
  }
}

} // namespace UI
} // namespace SentientSands
