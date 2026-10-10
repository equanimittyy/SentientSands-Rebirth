#include "OfferWindow.h"
#include "../core/Comm.h"
#include "../core/Globals.h"
#include "../core/Utils.h"
#include "../game/Context.h"
#include "ChatWindow.h"

#include <kenshi/Character.h>
#include <kenshi/GameWorld.h>
#include <kenshi/Item.h>
#include <kenshi/Platoon.h>
#include <kenshi/PlayerInterface.h>

#include <mygui/MyGUI_Button.h>
#include <mygui/MyGUI_Delegate.h>
#include <mygui/MyGUI_EditBox.h>
#include <mygui/MyGUI_Gui.h>
#include <mygui/MyGUI_InputManager.h>
#include <mygui/MyGUI_Window.h>

#include <algorithm>
#include <sstream>
#include <vector>

namespace SentientSands {
namespace UI {

MyGUI::Window *g_offerWindow = nullptr;
static MyGUI::EditBox *g_offerText = nullptr;
static MyGUI::EditBox *g_offerReply = nullptr;
static MyGUI::Button *g_offerAcceptBtn = nullptr;
static MyGUI::Button *g_offerDeclineBtn = nullptr;
static MyGUI::Button *g_offerSendBtn = nullptr;

struct Offer {
  std::string id;
  std::string npcName;
  unsigned int npcKey;
  unsigned int speakerKey;
  // A save load gives the same handles to new objects, so a new object behind
  // a key means the world that the offer rests on is gone
  Character *npc;
  Character *speaker;
  std::vector<std::string> checks;
};
static Offer g_offer;

static void CloseOfferUI() {
  if (g_offerWindow && MyGUI::Gui::getInstancePtr())
    MyGUI::Gui::getInstancePtr()->destroyWidget(g_offerWindow);
  g_offerWindow = nullptr;
  g_offerText = nullptr;
  g_offerReply = nullptr;
  g_offerAcceptBtn = nullptr;
  g_offerDeclineBtn = nullptr;
  g_offerSendBtn = nullptr;
}

static void NotifyText(const std::string &text) {
  EnterCriticalSection(&g_msgMutex);
  g_messageQueue.push_back("NOTIFY: " + text);
  LeaveCriticalSection(&g_msgMutex);
}

static std::string Fill(std::string text, const std::string &slot,
                        const std::string &value) {
  size_t at = text.find(slot);
  if (at != std::string::npos)
    text.replace(at, slot.size(), value);
  return text;
}

static std::string Lower(std::string text) {
  std::transform(text.begin(), text.end(), text.begin(), ::tolower);
  return text;
}

static std::string AnswerJson(const std::string &answer) {
  return "{\"id\": \"" + EscapeJSON(g_offer.id) + "\", \"answer\": \"" +
         answer + "\", \"npc\": \"" + EscapeJSON(g_offer.npcName) + "\"}";
}

static void EndOffer(const std::string &answer) {
  AsyncPostToPython(L"/offer", AnswerJson(answer));
  CloseOfferUI();
  SetOfferPending("");
}

static int MoneyOf(Character *c) {
  int money = c->getMoney();
  if (money <= 0 && c->getOwnerships())
    money = c->getOwnerships()->getMoney();
  return money;
}

static int CountItems(Character *c, const std::string &name) {
  std::vector<Item *> items;
  GetAllCharacterItems(c, items);
  std::string wanted = Lower(name);
  int count = 0;
  for (size_t i = 0; i < items.size(); ++i)
    if (items[i] && Lower(items[i]->getName()) == wanted)
      count += items[i]->quantity;
  return count;
}

// The game does not pause while an offer waits, so a side can have spent or
// lost its part of the deal by the time the player accepts
static std::string Shortfall(Character *npc, Character *speaker) {
  GameWorld *world = *ppWorld;
  // The cats belong to the whole player faction, as TAKE_CATS reads them
  Character *payer = world && world->player &&
                             world->player->playerCharacters.size() > 0
                         ? world->player->playerCharacters[0]
                         : speaker;
  for (size_t i = 0; i < g_offer.checks.size(); ++i) {
    std::istringstream in(g_offer.checks[i]);
    std::string kind, side, name;
    int count = 0;
    in >> kind >> side >> count;
    std::getline(in, name);
    name.erase(0, name.find_first_not_of(' '));
    bool player = side == "player";
    int have = kind == "CATS" ? MoneyOf(player ? payer : npc)
                              : CountItems(player ? speaker : npc, name);
    if (have >= count)
      continue;
    std::string what = ToString(count) + (kind == "CATS" ? " cats" : " " + name);
    return player ? Fill(T("You no longer have {what}."), "{what}", what)
                  : Fill(Fill(T("{name} no longer has {what}."), "{name}",
                              g_offer.npcName),
                         "{what}", what);
  }
  return "";
}

static void OnOfferAccept(MyGUI::Widget *sender) {
  Character *npc = KeyedCharacter(g_offer.npcKey);
  Character *speaker = KeyedCharacter(g_offer.speakerKey);
  std::string reason = npc && speaker ? Shortfall(npc, speaker) : "";
  if (!reason.empty()) {
    NotifyText(reason);
    EndOffer("failed");
    return;
  }
  EndOffer("accept");
}

static void ShowReplyBox() {
  g_offerText->setCaption(Utf8ToWide(T("Your reply:")).c_str());
  g_offerAcceptBtn->setVisible(false);
  g_offerDeclineBtn->setVisible(false);
  g_offerReply->setVisible(true);
  g_offerSendBtn->setVisible(true);
  MyGUI::InputManager::getInstance().setKeyFocusWidget(g_offerReply);
}

static void SendReply() {
  std::string reply = g_offerReply->getCaption().asUTF8();
  reply.erase(0, reply.find_first_not_of(" \t\r\n"));
  reply.erase(reply.find_last_not_of(" \t\r\n") + 1);
  if (reply.empty())
    reply = T("No.");
  std::string answer = AnswerJson("decline");
  std::string npcName = g_offer.npcName;
  std::string handleStr = ToString(g_offer.npcKey);
  Character *speaker = KeyedCharacter(g_offer.speakerKey);
  CloseOfferUI();
  SetOfferPending("");
  SendChatLine(npcName, handleStr, speaker, reply, CurrentChatMode(), answer);
}

static void OnOfferDecline(MyGUI::Widget *sender) { ShowReplyBox(); }
static void OnOfferSend(MyGUI::Widget *sender) { SendReply(); }
static void OnOfferReplyAccept(MyGUI::EditBox *sender) { SendReply(); }

static void OnOfferWindowButtonPressed(MyGUI::Window *sender,
                                       const std::string &name) {
  if (name != "close")
    return;
  if (g_offerAcceptBtn->getVisible())
    ShowReplyBox();
  else
    SendReply();
}

static MyGUI::Button *AddOfferButton(MyGUI::Widget *client, const char *key,
                                     float left, float top,
                                     void (*onClick)(MyGUI::Widget *)) {
  MyGUI::Button *button = client->createWidgetReal<MyGUI::Button>(
      "Kenshi_Button1", left, top, 0.25f, 0.2f,
      MyGUI::Align::Bottom | MyGUI::Align::Left,
      std::string("SentientSands_Offer") + key);
  button->setCaption(Utf8ToWide(T(key)).c_str());
  button->eventMouseButtonClick += MyGUI::newDelegate(onClick);
  return button;
}

// The data holds, one to a line, the offer ID, the keys of the NPC and the
// speaker, the name of the NPC, the text of the popup, and the CHECK lines
void ShowOfferUI(const std::string &data) {
  std::vector<std::string> lines;
  std::istringstream in(data);
  std::string line;
  while (std::getline(in, line)) {
    line.erase(0, line.find_first_not_of(" \t\r"));
    line.erase(line.find_last_not_of(" \t\r") + 1);
    lines.push_back(line);
  }
  MyGUI::Gui *gui = MyGUI::Gui::getInstancePtr();
  if (lines.size() < 4 || !gui || (g_offerWindow && g_offer.id == lines[0]))
    return;
  CloseOfferUI();

  Offer offer;
  offer.id = lines[0];
  std::istringstream keys(lines[1]);
  offer.npcKey = 0;
  offer.speakerKey = 0;
  keys >> offer.npcKey >> offer.speakerKey;
  offer.npcName = lines[2];
  for (size_t i = 4; i < lines.size(); ++i)
    if (lines[i].compare(0, 7, "CHECK: ") == 0)
      offer.checks.push_back(lines[i].substr(7));
  offer.npc = KeyedCharacter(offer.npcKey);
  offer.speaker = KeyedCharacter(offer.speakerKey);
  g_offer = offer;
  SetOfferPending(offer.npcName);
  if (!offer.npc || !offer.speaker) {
    EndOffer("cancel");
    return;
  }

  g_offerWindow = gui->createWidgetReal<MyGUI::Window>(
      "Kenshi_WindowCX", 0.3f, 0.36f, 0.4f, 0.24f, MyGUI::Align::Center,
      "Popup", "SentientSands_OfferWindow");
  g_offerWindow->setCaption(
      Utf8ToWide(Fill(T("Offer from {name}"), "{name}", offer.npcName))
          .c_str());
  g_offerWindow->eventWindowButtonPressed +=
      MyGUI::newDelegate(OnOfferWindowButtonPressed);
  MyGUI::Widget *client = g_offerWindow->getClientWidget();

  g_offerText = client->createWidgetReal<MyGUI::EditBox>(
      "Kenshi_WordWrap", 0.05f, 0.05f, 0.9f, 0.5f,
      MyGUI::Align::Top | MyGUI::Align::HStretch, "SentientSands_OfferText");
  g_offerText->setEditMultiLine(true);
  g_offerText->setEditWordWrap(true);
  g_offerText->setEditReadOnly(true);
  g_offerText->setTextAlign(MyGUI::Align::Left | MyGUI::Align::Top);
  g_offerText->setFontHeight(18);
  g_offerText->setCaption(Utf8ToWide(lines[3]).c_str());

  g_offerReply = client->createWidgetReal<MyGUI::EditBox>(
      "Kenshi_EditBox", 0.05f, 0.35f, 0.9f, 0.22f,
      MyGUI::Align::Top | MyGUI::Align::HStretch, "SentientSands_OfferReply");
  g_offerReply->setEditMultiLine(false);
  g_offerReply->setFontHeight(18);
  g_offerReply->eventEditSelectAccept +=
      MyGUI::newDelegate(OnOfferReplyAccept);
  g_offerReply->setVisible(false);

  g_offerAcceptBtn = AddOfferButton(client, "Accept", 0.18f, 0.72f, OnOfferAccept);
  g_offerDeclineBtn =
      AddOfferButton(client, "Decline", 0.57f, 0.72f, OnOfferDecline);
  g_offerSendBtn = AddOfferButton(client, "Send", 0.375f, 0.72f, OnOfferSend);
  g_offerSendBtn->setVisible(false);
}

void DropOfferUI() {
  CloseOfferUI();
  SetOfferPending("");
}

// A knocked-out or dead character cannot make or take a deal
void WatchOffer() {
  if (!g_offerWindow)
    return;
  Character *npc = KeyedCharacter(g_offer.npcKey);
  Character *speaker = KeyedCharacter(g_offer.speakerKey);
  bool gone = !npc || !speaker || npc != g_offer.npc || speaker != g_offer.speaker;
  if (!gone && !npc->isDead() && !speaker->isDead() && !npc->isUnconcious() &&
      !speaker->isUnconcious())
    return;
  NotifyText(Fill(T("{name}'s offer is gone."), "{name}", g_offer.npcName));
  EndOffer("cancel");
}

} // namespace UI
} // namespace SentientSands
