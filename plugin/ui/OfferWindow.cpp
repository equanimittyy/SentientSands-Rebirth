#include "OfferWindow.h"
#include "../core/Comm.h"
#include "../core/Globals.h"
#include "../core/Utils.h"
#include "../game/Context.h"
#include "BarterWindow.h"
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
#include <mygui/MyGUI_ListBox.h>
#include <mygui/MyGUI_TextBox.h>
#include <mygui/MyGUI_Window.h>

#include <cstdlib>
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
static MyGUI::Button *g_offerBackBtn = nullptr;
static std::vector<MyGUI::Widget *> g_offerBoxes;

struct Offer {
  std::string id;
  std::string npcName;
  std::string text;
  unsigned int npcKey;
  unsigned int speakerKey;
  // A save load gives the same handles to new objects, so a new object behind
  // a key means the world that the offer rests on is gone
  Character *npc;
  Character *speaker;
  std::vector<std::string> checks;
  std::vector<std::string> deal;
};
// The barter window can hold the offer instead of the popup, so the ID marks a
// held offer
static Offer g_offer;

static void CloseOfferUI() {
  DestroyWindow(g_offerWindow);
  g_offerText = nullptr;
  g_offerReply = nullptr;
  g_offerAcceptBtn = nullptr;
  g_offerDeclineBtn = nullptr;
  g_offerSendBtn = nullptr;
  g_offerBackBtn = nullptr;
  g_offerBoxes.clear();
}

static std::string AnswerJson(const std::string &answer) {
  return "{\"id\": \"" + EscapeJSON(g_offer.id) + "\", \"answer\": \"" +
         answer + "\", \"npc\": \"" + EscapeJSON(g_offer.npcName) + "\"}";
}

static void ForgetOffer() {
  CloseOfferUI();
  SetOfferPending("");
  g_offer.id.clear();
  BarterOfferGone();
}

static void EndOffer(const std::string &answer) {
  AsyncPostToPython(L"/offer", AnswerJson(answer));
  ForgetOffer();
}

// The NPC also sells the stock in the furniture of its shop
static int CountItems(Character *c, const std::string &name, bool withShop) {
  std::vector<Item *> items;
  GetAllCharacterItems(c, items);
  if (withShop)
    GetShopItems(c, items);
  std::string wanted = Lower(name);
  int count = 0;
  for (size_t i = 0; i < items.size(); ++i)
    if (items[i] && Lower(ItemLabel(items[i])) == wanted)
      count += items[i]->quantity;
  return count;
}

static GameData *ItemData(Character *c, const std::string &name) {
  std::vector<Item *> items;
  GetAllCharacterItems(c, items);
  std::string wanted = Lower(name);
  for (size_t i = 0; i < items.size(); ++i)
    if (items[i] && Lower(ItemLabel(items[i])) == wanted)
      return items[i]->data;
  return nullptr;
}

// The game does not pause while an offer waits, so a side can have spent or
// lost its part of the deal by the time the player accepts. An item of a squad
// mate names the key of its holder instead of player
DealLine ParseDealLine(const std::string &text) {
  DealLine line;
  line.count = 0;
  std::istringstream in(text);
  in >> line.kind >> line.holder >> line.count;
  std::getline(in, line.name);
  line.name.erase(0, line.name.find_first_not_of(' '));
  return line;
}

static std::string Shortfall(Character *npc, Character *speaker) {
  Character *payer = FirstPlayerCharacter();
  if (!payer)
    payer = speaker;
  for (size_t i = 0; i < g_offer.checks.size(); ++i) {
    DealLine check = ParseDealLine(g_offer.checks[i]);
    bool player = check.holder != "npc";
    Character *holder =
        check.holder == "player" ? speaker
        : !player               ? npc
                                : KeyedCharacter((unsigned int)strtoul(
                                      check.holder.c_str(), NULL, 10));
    // A ROOM line names the giver of an item that the NPC must carry
    if (check.kind == "ROOM") {
      GameData *data = holder ? ItemData(holder, check.name) : nullptr;
      if (data && !HasRoomFor(npc, data, check.count))
        return Fill(T("{name} can't carry all that."), "{name}",
                    g_offer.npcName);
      continue;
    }
    int have = check.kind == "CATS" ? MoneyOf(player ? payer : npc)
               : holder ? CountItems(holder, check.name, !player)
                        : 0;
    if (have >= check.count)
      continue;
    std::string what = ToString(check.count) +
                       (check.kind == "CATS" ? " cats" : " " + check.name);
    return player ? Fill(T("You no longer have {what}."), "{what}", what)
                  : Fill(Fill(T("{name} no longer has {what}."), "{name}",
                              g_offer.npcName),
                         "{what}", what);
  }
  return "";
}

void AcceptOffer() {
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

std::string DeclineOffer() {
  std::string answer = AnswerJson("decline");
  ForgetOffer();
  return answer;
}

static void OnOfferAccept(MyGUI::Widget *sender) { AcceptOffer(); }

// The offer and the reply share one window, so Back can bring the offer back
static void ShowReplyBox(bool shown) {
  bool barter = !g_offerBoxes.empty();
  for (size_t i = 0; i < g_offerBoxes.size(); ++i)
    g_offerBoxes[i]->setVisible(!shown);
  g_offerText->setVisible(shown || !barter);
  g_offerText->setOnlyText(
      Utf8ToWide(shown ? T("Your reply:") : g_offer.text).c_str());
  g_offerAcceptBtn->setVisible(!shown);
  g_offerDeclineBtn->setVisible(!shown);
  g_offerReply->setVisible(shown);
  g_offerSendBtn->setVisible(shown);
  g_offerBackBtn->setVisible(shown);
  if (shown)
    MyGUI::InputManager::getInstance().setKeyFocusWidget(g_offerReply);
}

static void SendReply() {
  std::string reply = Trim(g_offerReply->getOnlyText().asUTF8());
  if (reply.empty())
    reply = T("No.");
  std::string answer = AnswerJson("decline");
  std::string npcName = g_offer.npcName;
  Character *speaker = KeyedCharacter(g_offer.speakerKey);
  ForgetOffer();
  SendChatLine(npcName, g_offer.npcKey, speaker, reply, CurrentChatMode(),
               answer);
}

static void OnOfferDecline(MyGUI::Widget *sender) { ShowReplyBox(true); }
static void OnOfferBack(MyGUI::Widget *sender) { ShowReplyBox(false); }
static void OnOfferSend(MyGUI::Widget *sender) { SendReply(); }
static void OnOfferReplyAccept(MyGUI::EditBox *sender) { SendReply(); }

// Close is a decline, which asks for a reply first
static void OnOfferClose() {
  if (g_offerAcceptBtn->getVisible())
    ShowReplyBox(true);
  else
    SendReply();
}

static CloseAction g_offerClose = {OnOfferClose};

MyGUI::Widget *OpenPopup(MyGUI::Window *&window, float top, float height,
                         const std::string &name, const std::string &npcName,
                         CloseAction &onClose) {
  return OpenWindow(window, 0.3f, top, 0.4f, height, MyGUI::Align::Center,
                    "Popup", name,
                    Fill(T("Offer from {name}"), "{name}", npcName), onClose);
}

MyGUI::Button *AddPopupButton(MyGUI::Widget *client, const std::string &key,
                              float left, const std::string &name,
                              ClickHandler onClick) {
  return AddButton(client, T(key), left, 0.72f, 0.25f, 0.2f,
                   MyGUI::Align::Bottom | MyGUI::Align::Left, name + key,
                   onClick);
}

static void AddOfferBox(MyGUI::Widget *client, const char *labelKey,
                        float left, const std::vector<std::string> &entries,
                        const std::string &name) {
  MyGUI::TextBox *label =
      AddLabel(client, T(labelKey), left, 0.03f, 0.43f, 0.1f,
               MyGUI::Align::Top | MyGUI::Align::Left, name + "Label",
               MyGUI::Align::Default);
  MyGUI::ListBox *box = client->createWidgetReal<MyGUI::ListBox>(
      "Kenshi_ListBox", left, 0.14f, 0.43f, 0.52f,
      MyGUI::Align::Top | MyGUI::Align::Left, name);
  if (entries.empty())
    box->addItem(Utf8ToWide(T("Nothing")).c_str());
  for (size_t i = 0; i < entries.size(); ++i)
    box->addItem(PlainText(entries[i]));
  g_offerBoxes.push_back(label);
  g_offerBoxes.push_back(box);
}

// The data holds, one to a line, the offer ID, the keys of the NPC and the
// speaker, the name of the NPC, the text of the popup, the CHECK lines, and the
// BOX lines of a barter offer, which shows in two boxes instead of the text.
// An agreement in the barter window adds DEAL lines, and the window shows it
static bool ParseOffer(const std::string &data, Offer &offer,
                       std::vector<std::string> &mine,
                       std::vector<std::string> &theirs) {
  std::vector<std::string> lines;
  std::istringstream in(data);
  std::string line;
  while (std::getline(in, line))
    lines.push_back(Trim(line, " \t\r"));
  if (lines.size() < 4)
    return false;
  offer.id = lines[0];
  std::istringstream keys(lines[1]);
  offer.npcKey = 0;
  offer.speakerKey = 0;
  keys >> offer.npcKey >> offer.speakerKey;
  offer.npcName = lines[2];
  offer.text = lines[3];
  for (size_t i = 4; i < lines.size(); ++i) {
    if (lines[i].compare(0, 7, "CHECK: ") == 0)
      offer.checks.push_back(lines[i].substr(7));
    else if (lines[i].compare(0, 12, "BOX: player ") == 0)
      mine.push_back(lines[i].substr(12));
    else if (lines[i].compare(0, 9, "BOX: npc ") == 0)
      theirs.push_back(lines[i].substr(9));
    else if (lines[i].compare(0, 6, "DEAL: ") == 0)
      offer.deal.push_back(lines[i].substr(6));
  }
  return true;
}

void ShowOfferUI(const std::string &data) {
  Offer offer;
  std::vector<std::string> mine, theirs;
  if (!MyGUI::Gui::getInstancePtr() || !ParseOffer(data, offer, mine, theirs) ||
      (!g_offer.id.empty() && g_offer.id == offer.id))
    return;
  CloseOfferUI();
  bool barter = !mine.empty() || !theirs.empty();
  offer.npc = KeyedCharacter(offer.npcKey);
  offer.speaker = KeyedCharacter(offer.speakerKey);
  g_offer = offer;
  SetOfferPending(offer.npcName);
  if (!offer.npc || !offer.speaker) {
    EndOffer("cancel");
    return;
  }
  if (ShowBarterOffer(offer.npcKey, offer.speakerKey, offer.deal))
    return;

  MyGUI::Widget *client =
      OpenPopup(g_offerWindow, barter ? 0.3f : 0.36f, barter ? 0.36f : 0.24f,
                "SentientSands_OfferWindow", offer.npcName, g_offerClose);
  g_offerText = AddTextView(client, 0.05f, 0.05f, 0.9f, 0.5f,
                            MyGUI::Align::Top | MyGUI::Align::HStretch,
                            "SentientSands_OfferText");
  g_offerText->setOnlyText(Utf8ToWide(offer.text).c_str());
  if (barter) {
    g_offerText->setVisible(false);
    AddOfferBox(client, "You are offering:", 0.05f, mine,
                "SentientSands_OfferMine");
    AddOfferBox(client, "They are offering:", 0.52f, theirs,
                "SentientSands_OfferTheirs");
  }

  g_offerReply = AddLineBox(client, 0.05f, 0.35f, 0.9f, 0.22f,
                            MyGUI::Align::Top | MyGUI::Align::HStretch,
                            "SentientSands_OfferReply");
  g_offerReply->eventEditSelectAccept +=
      MyGUI::newDelegate(OnOfferReplyAccept);
  g_offerReply->setVisible(false);

  const std::string name = "SentientSands_Offer";
  g_offerAcceptBtn = AddPopupButton(client, "Accept", 0.18f, name, OnOfferAccept);
  g_offerDeclineBtn =
      AddPopupButton(client, "Decline", 0.57f, name, OnOfferDecline);
  g_offerSendBtn = AddPopupButton(client, "Send", 0.18f, name, OnOfferSend);
  g_offerSendBtn->setVisible(false);
  g_offerBackBtn = AddPopupButton(client, "Back", 0.57f, name, OnOfferBack);
  g_offerBackBtn->setVisible(false);
}

void DropOfferUI() { ForgetOffer(); }

bool OfferHeldFor(unsigned int npcKey) {
  return !g_offer.id.empty() && g_offer.npcKey == npcKey;
}

// A knocked-out or dead character cannot make or take a deal
void WatchOffer() {
  if (g_offer.id.empty())
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
