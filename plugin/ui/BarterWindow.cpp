// The player lays the deal from real items, so the model never writes a deal
// that the game must run. The held offer stays in OfferWindow.cpp, so Accept,
// its checks, and the knockout watch work as for the popup.
#include "BarterWindow.h"
#include "../core/Comm.h"
#include "../core/Globals.h"
#include "../core/Utils.h"
#include "../game/Context.h"
#include "ChatWindow.h"
#include "OfferWindow.h"

#include <kenshi/Character.h>
#include <kenshi/GameWorld.h>
#include <kenshi/Item.h>
#include <kenshi/PlayerInterface.h>
#include <kenshi/util/hand.h>

#include <mygui/MyGUI_Button.h>
#include <mygui/MyGUI_Delegate.h>
#include <mygui/MyGUI_EditBox.h>
#include <mygui/MyGUI_Gui.h>
#include <mygui/MyGUI_InputManager.h>
#include <mygui/MyGUI_ListBox.h>
#include <mygui/MyGUI_TextBox.h>
#include <mygui/MyGUI_Window.h>

#include <algorithm>
#include <cstdlib>
#include <map>
#include <vector>

namespace SentientSands {
namespace UI {

MyGUI::Window *g_barterWindow = nullptr;
static MyGUI::EditBox *g_barterHistory = nullptr;
static MyGUI::EditBox *g_barterInput = nullptr;
static MyGUI::EditBox *g_barterCats[2] = {nullptr, nullptr};
static MyGUI::ListBox *g_barterLists[4] = {nullptr, nullptr, nullptr, nullptr};
static MyGUI::Button *g_barterPickBtn = nullptr;
static MyGUI::Button *g_barterSendBtn = nullptr;
static MyGUI::Button *g_barterAcceptBtn = nullptr;
static MyGUI::TextBox *g_barterPurses[2] = {nullptr, nullptr};
static MyGUI::TextBox *g_barterStatus = nullptr;
static MyGUI::TextBox *g_barterEstimate = nullptr;

enum { INVENTORY, MINE, THEIRS, STOCK };
enum { PLAYER_SIDE, NPC_SIDE };

// The NPC holds its side with the key 0, which no character gets
struct Lot {
  unsigned int holder;
  std::string label;
  int count;
};

struct Deal {
  int cats[2];
  std::vector<Lot> lots[2];
};

static Deal g_deal;
static Deal g_agreed;
static std::vector<Lot> g_lost;
static bool g_offerHeld = false;
static std::vector<Lot> g_shown[4];
static std::string g_barterNpcName;
static std::string g_barterMode;
static unsigned int g_barterNpcKey = 0;
static unsigned int g_barterSpeakerKey = 0;
static bool g_barterStock = false;
static std::vector<hand> g_barterSquad;
static size_t g_barterPick = 0;
static bool g_barterWaiting = false;
// The NPC's goods set the price of an item that both sides hold, at its
// highest (offers.price_of)
static std::map<std::string, int> g_npcPrices;
static std::map<std::string, int> g_squadPrices;

static void SetCaption(MyGUI::TextBox *widget, const std::string &text) {
  widget->setCaption(PlainText(text));
}

static void SetStatus(const std::string &key) {
  SetCaption(g_barterStatus, Fill(T(key), "{name}", g_barterNpcName));
}

static int LotCount(const std::vector<Lot> &lots, unsigned int holder,
                    const std::string &label) {
  for (size_t i = 0; i < lots.size(); ++i)
    if (lots[i].holder == holder && lots[i].label == label)
      return lots[i].count;
  return 0;
}

static void AddLot(std::vector<Lot> &lots, unsigned int holder,
                   const std::string &label, int count) {
  for (size_t i = 0; i < lots.size(); ++i) {
    if (lots[i].holder == holder && lots[i].label == label) {
      lots[i].count += count;
      return;
    }
  }
  Lot lot = {holder, label, count};
  lots.push_back(lot);
}

static void TakeLot(std::vector<Lot> &lots, unsigned int holder,
                    const std::string &label, int count) {
  for (size_t i = 0; i < lots.size(); ++i) {
    if (lots[i].holder == holder && lots[i].label == label) {
      lots[i].count -= count;
      if (lots[i].count <= 0)
        lots.erase(lots.begin() + i);
      return;
    }
  }
}

static bool LotBefore(const Lot &a, const Lot &b) {
  return a.holder != b.holder ? a.holder < b.holder : a.label < b.label;
}

// A trader in a shop trades only the stock of its shop (offers.sells_stock)
static void GoodsOf(Character *c, bool stock, std::vector<Item *> &items) {
  if (stock)
    GetShopItems(c, items);
  else
    GetAllCharacterItems(c, items);
}

static std::vector<Lot> Holdings(Character *c, unsigned int holder,
                                 bool stock) {
  std::vector<Lot> lots;
  if (!c)
    return lots;
  std::vector<Item *> items;
  GoodsOf(c, stock, items);
  for (size_t i = 0; i < items.size(); ++i)
    if (items[i] && items[i]->itemFunction != ITEM_MONEY)
      AddLot(lots, holder, ItemLabel(items[i]), items[i]->quantity);
  std::sort(lots.begin(), lots.end(), LotBefore);
  return lots;
}

static void NotePrices(Character *c, bool stock,
                       std::map<std::string, int> &prices) {
  if (!c)
    return;
  std::vector<Item *> items;
  GoodsOf(c, stock, items);
  for (size_t i = 0; i < items.size(); ++i) {
    if (!items[i] || items[i]->itemFunction == ITEM_MONEY)
      continue;
    int &best = prices[ItemLabel(items[i])];
    best = std::max(best, items[i]->getValueSingle(false));
  }
}

static std::vector<Lot> Left(const std::vector<Lot> &held,
                             const std::vector<Lot> &offered) {
  std::vector<Lot> left;
  for (size_t i = 0; i < held.size(); ++i) {
    Lot lot = held[i];
    lot.count -= LotCount(offered, lot.holder, lot.label);
    if (lot.count > 0)
      left.push_back(lot);
  }
  return left;
}

static int CatsIn(MyGUI::EditBox *box) {
  return std::max(0, atoi(box->getOnlyText().asUTF8().c_str()));
}

static Deal TableDeal() {
  Deal deal = g_deal;
  deal.cats[PLAYER_SIDE] = CatsIn(g_barterCats[PLAYER_SIDE]);
  deal.cats[NPC_SIDE] = CatsIn(g_barterCats[NPC_SIDE]);
  return deal;
}

static bool SameDeal(Deal a, Deal b) {
  for (int side = 0; side < 2; ++side) {
    std::sort(a.lots[side].begin(), a.lots[side].end(), LotBefore);
    std::sort(b.lots[side].begin(), b.lots[side].end(), LotBefore);
    if (a.cats[side] != b.cats[side] ||
        a.lots[side].size() != b.lots[side].size())
      return false;
    for (size_t i = 0; i < a.lots[side].size(); ++i)
      if (a.lots[side][i].holder != b.lots[side][i].holder ||
          a.lots[side][i].label != b.lots[side][i].label ||
          a.lots[side][i].count != b.lots[side][i].count)
        return false;
  }
  return true;
}

static int PriceOf(const std::string &label) {
  std::map<std::string, int>::const_iterator price = g_npcPrices.find(label);
  if (price != g_npcPrices.end())
    return price->second;
  price = g_squadPrices.find(label);
  return price != g_squadPrices.end() ? price->second : 0;
}

static int Worth(const std::vector<Lot> &lots) {
  int total = 0;
  for (size_t i = 0; i < lots.size(); ++i)
    total += lots[i].count * PriceOf(lots[i].label);
  return total;
}

// At the full price, so the player sees how much the NPC fleeces them. The NPC
// weighs the deal at its shares instead (offers.worth)
static void UpdateEstimate() {
  Deal deal = TableDeal();
  int profit = deal.cats[PLAYER_SIDE] + Worth(deal.lots[PLAYER_SIDE]) -
               deal.cats[NPC_SIDE] - Worth(deal.lots[NPC_SIDE]);
  std::string text = T(profit >= 0 ? "{name}'s estimated profit: {count} cats"
                                   : "{name}'s estimated loss: {count} cats");
  SetCaption(g_barterEstimate,
             Fill(Fill(text, "{name}", g_barterNpcName), "{count}",
                  ToString(profit >= 0 ? profit : -profit)));
}

// The NPC agreed only to the deal that it saw, so an edit takes Accept away
static void UpdateAccept() {
  g_barterAcceptBtn->setEnabled(g_offerHeld && !g_barterWaiting &&
                                SameDeal(TableDeal(), g_agreed));
  UpdateEstimate();
}

static Character *Picked() {
  return g_barterPick < g_barterSquad.size()
             ? g_barterSquad[g_barterPick].getCharacter()
             : nullptr;
}

static std::string HolderName(unsigned int holder) {
  Character *c = KeyedCharacter(holder);
  return c ? c->getName() : "?";
}

static void FillList(int list, const std::vector<Lot> &lots, bool named) {
  MyGUI::ListBox *box = g_barterLists[list];
  box->removeAllItems();
  for (size_t i = 0; i < lots.size(); ++i) {
    std::string row = ToString(lots[i].count) + " " + lots[i].label;
    if (named)
      row = HolderName(lots[i].holder) + ": " + row;
    box->addItem(PlainText(row));
  }
  g_shown[list] = lots;
}

// The game does not pause, so a side can lose an item that lies on the table
static bool TrimDeal() {
  bool trimmed = false;
  for (int side = 0; side < 2; ++side) {
    std::vector<Lot> &lots = g_deal.lots[side];
    for (size_t i = lots.size(); i-- > 0;) {
      Lot lot = lots[i];
      bool npc = side == NPC_SIDE;
      Character *holder = KeyedCharacter(npc ? g_barterNpcKey : lot.holder);
      int have =
          LotCount(Holdings(holder, lot.holder, npc && g_barterStock),
                   lot.holder, lot.label);
      if (have >= lot.count)
        continue;
      std::string text =
          Fill(Fill(T("{name} no longer has {what}."), "{name}",
                    npc ? g_barterNpcName : HolderName(lot.holder)),
               "{what}", ToString(lot.count) + " " + lot.label);
      if (npc) {
        text += " " + T("Someone bought or ate it.");
        AddLot(g_lost, lot.holder, lot.label, lot.count - have);
      }
      NotifyText(text);
      if (!trimmed)
        SetCaption(g_barterStatus, text);
      trimmed = true;
      TakeLot(lots, lot.holder, lot.label, lot.count - have);
    }
  }
  return trimmed;
}

static void RefreshBarterLists() {
  TrimDeal();
  Character *npc = KeyedCharacter(g_barterNpcKey);
  Character *mate = Picked();
  g_npcPrices.clear();
  g_squadPrices.clear();
  NotePrices(npc, g_barterStock, g_npcPrices);
  for (size_t i = 0; i < g_barterSquad.size(); ++i)
    NotePrices(g_barterSquad[i].getCharacter(), false, g_squadPrices);
  unsigned int mateKey = mate ? HandleKey(mate) : 0;
  FillList(INVENTORY,
           Left(Holdings(mate, mateKey, false), g_deal.lots[PLAYER_SIDE]),
           false);
  FillList(MINE, g_deal.lots[PLAYER_SIDE], true);
  FillList(THEIRS, g_deal.lots[NPC_SIDE], false);
  FillList(STOCK,
           Left(Holdings(npc, 0, g_barterStock), g_deal.lots[NPC_SIDE]),
           false);
  Character *payer = FirstPlayerCharacter();
  SetCaption(g_barterPurses[PLAYER_SIDE],
             Fill(T("Purse: {count} cats"), "{count}",
                  ToString(payer ? MoneyOf(payer) : 0)));
  SetCaption(g_barterPurses[NPC_SIDE],
             Fill(T("Purse: {count} cats"), "{count}",
                  ToString(npc ? MoneyOf(npc) : 0)));
  if (mate)
    SetCaption(g_barterPickBtn, mate->getName());
  UpdateAccept();
}

static void MoveLot(int list, size_t index) {
  if (index >= g_shown[list].size())
    return;
  Lot lot = g_shown[list][index];
  int count =
      MyGUI::InputManager::getInstance().isShiftPressed() ? lot.count : 1;
  int side = list == INVENTORY || list == MINE ? PLAYER_SIDE : NPC_SIDE;
  if (list == INVENTORY || list == STOCK)
    AddLot(g_deal.lots[side], lot.holder, lot.label, count);
  else
    TakeLot(g_deal.lots[side], lot.holder, lot.label, count);
  RefreshBarterLists();
  // A refill scrolls to the top, and a long stock would lose its place
  size_t rows = g_barterLists[list]->getItemCount();
  if (rows > 0)
    g_barterLists[list]->beginToItemAt(std::min(index, rows - 1));
}

static void OnBarterListAccept(MyGUI::ListBox *sender, size_t index) {
  for (int i = 0; i < 4; ++i)
    if (sender == g_barterLists[i])
      MoveLot(i, index);
}

// The NPC side has no cap, because charity creates its cats
static void CapPlayerCats() {
  Character *payer = FirstPlayerCharacter();
  int purse = payer ? MoneyOf(payer) : 0;
  if (CatsIn(g_barterCats[PLAYER_SIDE]) > purse)
    SetCaption(g_barterCats[PLAYER_SIDE], ToString(purse));
}

static void OnBarterCatsChange(MyGUI::EditBox *sender) {
  if (sender == g_barterCats[PLAYER_SIDE])
    CapPlayerCats();
  UpdateAccept();
}

static void OnBarterPickClick(MyGUI::Widget *sender) {
  if (g_barterSquad.empty())
    return;
  g_barterPick = (g_barterPick + 1) % g_barterSquad.size();
  RefreshBarterLists();
}

static void SetBarterHistory(const std::string &lines) {
  g_barterHistory->setOnlyText(Utf8ToWide(lines).c_str());
  g_barterHistory->setTextCursor(g_barterHistory->getTextLength());
}

static void CloseBarterUI() {
  DestroyWindow(g_barterWindow);
  g_barterHistory = nullptr;
  g_barterInput = nullptr;
  g_barterPickBtn = nullptr;
  g_barterSendBtn = nullptr;
  g_barterAcceptBtn = nullptr;
  g_barterStatus = nullptr;
  g_barterEstimate = nullptr;
  for (int i = 0; i < 4; ++i)
    g_barterLists[i] = nullptr;
  for (int i = 0; i < 2; ++i) {
    g_barterCats[i] = nullptr;
    g_barterPurses[i] = nullptr;
  }
}

static std::string LotsJson(const std::vector<Lot> &lots) {
  std::string json = "[";
  for (size_t i = 0; i < lots.size(); ++i)
    json += std::string(i ? "," : "") + "{\"holder\": \"" +
            ToString(lots[i].holder) + "\", \"name\": \"" +
            EscapeJSON(lots[i].label) +
            "\", \"count\": " + ToString(lots[i].count) + "}";
  return json + "]";
}

// The server checks each item against the inventory of its holder, and the
// price guide covers the items of all the squad mates
static std::string BarterJson() {
  Deal deal = TableDeal();
  std::string squad = "[";
  for (size_t i = 0; i < g_barterSquad.size(); ++i) {
    Character *mate = g_barterSquad[i].getCharacter();
    if (!mate)
      continue;
    std::vector<Item *> items;
    GetAllCharacterItems(mate, items);
    squad += std::string(squad.size() > 1 ? "," : "") + "{\"key\": \"" +
             ToString(HandleKey(mate)) + "\", \"name\": \"" +
             EscapeJSON(mate->getName()) +
             "\", \"inventory\": " + ItemsJson(items) + "}";
  }
  return "{\"deal\": {\"take_cats\": " + ToString(deal.cats[PLAYER_SIDE]) +
         ", \"give_cats\": " + ToString(deal.cats[NPC_SIDE]) +
         ", \"take\": " + LotsJson(deal.lots[PLAYER_SIDE]) +
         ", \"give\": " + LotsJson(deal.lots[NPC_SIDE]) +
         ", \"lost\": " + LotsJson(g_lost) + "}, \"squad\": " + squad + "]}";
}

static void SendBarterLine() {
  if (g_barterWaiting)
    return;
  // The player wrote the line for the table before the trim
  if (TrimDeal()) {
    RefreshBarterLists();
    return;
  }
  std::string text = Trim(g_barterInput->getOnlyText().asUTF8());
  if (text.empty())
    text = T("How about this deal?");
  CapPlayerCats();
  std::string json = BarterJson();
  // The server keeps the offer until the answer, and drops a line that comes
  // before it. An offer in the popup came from the model, and a send of the
  // table declines it as well
  std::string answer =
      OfferHeldFor(g_barterNpcKey) ? DeclineOffer() : std::string();
  // The mark keeps the line in the BARTER dialogue even after the dialogue
  // ended, as a new !b line would
  if (!SendChatLine(g_barterNpcName, g_barterNpcKey,
                    KeyedCharacter(g_barterSpeakerKey), "!b " + text,
                    g_barterMode, answer, json))
    return;
  g_lost.clear();
  g_barterInput->setCaption("");
  g_barterWaiting = true;
  g_barterSendBtn->setEnabled(false);
  SetStatus("{name} is thinking...");
  UpdateAccept();
}

static void OnBarterSend(MyGUI::Widget *sender) { SendBarterLine(); }
static void OnBarterInputAccept(MyGUI::EditBox *sender) { SendBarterLine(); }

static void OnBarterAccept(MyGUI::Widget *sender) {
  if (!g_offerHeld)
    return;
  AcceptOffer();
  CloseBarterUI();
}

// The NPC hears that the player walked away from a deal that it agreed to
static void CloseBarterTable() {
  if (g_offerHeld)
    AsyncPostToPython(L"/offer", DeclineOffer());
  CloseBarterUI();
}

static void OnBarterClose(MyGUI::Widget *sender) { CloseBarterTable(); }

static CloseAction g_barterClose = {CloseBarterTable};

static MyGUI::TextBox *AddBarterText(MyGUI::Widget *client, float left,
                                     float top, float width, float height,
                                     const std::string &text,
                                     const std::string &name) {
  return AddLabel(client, text, left, top, width, height,
                  MyGUI::Align::Top | MyGUI::Align::Left, name,
                  MyGUI::Align::Default);
}

static MyGUI::Button *AddBarterButton(MyGUI::Widget *client, float left,
                                      float top, float width,
                                      const std::string &key,
                                      const std::string &name,
                                      ClickHandler onClick) {
  return AddButton(client, T(key), left, top, width, 0.06f,
                   MyGUI::Align::Top | MyGUI::Align::Left, name, onClick);
}

static MyGUI::EditBox *AddBarterEdit(MyGUI::Widget *client, float left,
                                     float top, float width,
                                     const std::string &name) {
  return AddLineBox(client, left, top, width, 0.05f,
                    MyGUI::Align::Top | MyGUI::Align::Left, name);
}

static void BuildBarterWindow() {
  MyGUI::Widget *client = OpenWindow(
      g_barterWindow, 0.15f, 0.08f, 0.7f, 0.84f, MyGUI::Align::Center, "Window",
      "SentientSands_BarterWindow",
      Fill(T("Barter with {name}"), "{name}", g_barterNpcName), g_barterClose);
  g_barterHistory = AddTextView(client, 0.03f, 0.02f, 0.94f, 0.22f,
                                MyGUI::Align::Top | MyGUI::Align::HStretch,
                                "SentientSands_BarterHistory");

  // A button goes to the next squad mate, because a drop-down list opens
  // under the window (kenshi_gotchas.md)
  g_barterPickBtn = AddBarterButton(client, 0.03f, 0.26f, 0.21f, "?",
                                    "SentientSands_BarterPick",
                                    OnBarterPickClick);
  g_barterPurses[PLAYER_SIDE] = AddBarterText(
      client, 0.26f, 0.27f, 0.21f, 0.04f, "", "SentientSands_BarterPurse");
  g_barterPurses[NPC_SIDE] = AddBarterText(
      client, 0.53f, 0.27f, 0.44f, 0.04f, "", "SentientSands_BarterNpcPurse");

  const char *headers[] = {"Inventory", "You offer", "They offer", "Stock"};
  const float lefts[] = {0.03f, 0.26f, 0.53f, 0.76f};
  for (int i = 0; i < 4; ++i) {
    float left = lefts[i];
    AddBarterText(client, left, 0.33f, 0.21f, 0.04f, T(headers[i]),
                  "SentientSands_BarterHeader" + ToString(i));
    g_barterLists[i] = client->createWidgetReal<MyGUI::ListBox>(
        "Kenshi_ListBox", left, 0.37f, 0.21f, 0.25f,
        MyGUI::Align::Top | MyGUI::Align::Left,
        "SentientSands_BarterList" + ToString(i));
    g_barterLists[i]->eventListSelectAccept +=
        MyGUI::newDelegate(OnBarterListAccept);
  }

  AddBarterText(client, 0.03f, 0.635f, 0.21f, 0.04f, T("Cats:"),
                "SentientSands_BarterCatsLabel");
  AddBarterText(client, 0.76f, 0.635f, 0.21f, 0.04f, T("Cats:"),
                "SentientSands_BarterNpcCatsLabel");
  g_barterCats[PLAYER_SIDE] =
      AddBarterEdit(client, 0.26f, 0.63f, 0.21f, "SentientSands_BarterCats");
  g_barterCats[NPC_SIDE] = AddBarterEdit(client, 0.53f, 0.63f, 0.21f,
                                         "SentientSands_BarterNpcCats");
  for (int i = 0; i < 2; ++i) {
    g_barterCats[i]->setCaption("0");
    g_barterCats[i]->eventEditTextChange +=
        MyGUI::newDelegate(OnBarterCatsChange);
  }
  g_barterEstimate = AddBarterText(client, 0.03f, 0.69f, 0.94f, 0.04f, "",
                                   "SentientSands_BarterEstimate");
  AddBarterText(client, 0.03f, 0.73f, 0.94f, 0.04f,
                T("Double-click moves one item. Shift and double-click moves "
                  "the stack."),
                "SentientSands_BarterHint");

  AddBarterText(client, 0.03f, 0.785f, 0.2f, 0.04f,
                T("Message for ") + g_barterNpcName + ":",
                "SentientSands_BarterInputLabel");
  g_barterInput =
      AddBarterEdit(client, 0.24f, 0.78f, 0.55f, "SentientSands_BarterInput");
  g_barterInput->eventEditSelectAccept +=
      MyGUI::newDelegate(OnBarterInputAccept);
  g_barterSendBtn = AddBarterButton(client, 0.8f, 0.775f, 0.17f, "Send",
                                    "SentientSands_BarterSend", OnBarterSend);
  g_barterStatus = AddBarterText(client, 0.03f, 0.845f, 0.94f, 0.04f, "",
                                 "SentientSands_BarterStatus");
  g_barterStatus->setTextColour(MyGUI::Colour(1.0f, 0.9f, 0.5f));

  AddBarterButton(client, 0.03f, 0.9f, 0.2f, "Close",
                  "SentientSands_BarterClose", OnBarterClose);
  g_barterAcceptBtn =
      AddBarterButton(client, 0.77f, 0.9f, 0.2f, "Accept",
                      "SentientSands_BarterAccept", OnBarterAccept);
  MyGUI::InputManager::getInstance().setKeyFocusWidget(g_barterInput);
}

static Character *PlayerCharacter(const std::string &npcId) {
  GameWorld *world = *ppWorld;
  if (!world || !world->player)
    return nullptr;
  lektor<Character *> &characters = world->player->playerCharacters;
  for (uint32_t i = 0; i < characters.size(); ++i)
    if (characters[i] && GetNpcId(characters[i]) == npcId)
      return characters[i];
  return nullptr;
}

// thread is the reply of /chat_thread: the window speaks as the speaker of
// the action dialogue, in its mode, or its line would start a new thread
void ShowBarterUI(const std::string &npcName, unsigned int npcKey,
                  const std::string &thread) {
  if (!MyGUI::Gui::getInstancePtr())
    return;
  CloseBarterUI();
  g_barterNpcName = npcName;
  g_barterNpcKey = npcKey;
  g_barterMode = GetJsonValue(thread, "mode");
  g_barterStock = JsonTrue(thread, "stock");
  g_deal = Deal();
  g_deal.cats[PLAYER_SIDE] = g_deal.cats[NPC_SIDE] = 0;
  g_lost.clear();
  g_offerHeld = false;
  g_barterWaiting = false;

  Character *speaker = PlayerCharacter(GetJsonValue(thread, "speaker"));
  Character *npc = KeyedCharacter(g_barterNpcKey);
  std::vector<Character *> squad;
  GetCurrentSquad(squad);
  g_barterSquad.clear();
  g_barterPick = 0;
  if (speaker)
    g_barterSquad.push_back(speaker->getHandle());
  // Only a squad mate in talk range of the NPC can hand it an item
  for (size_t i = 0; i < squad.size(); ++i)
    if (npc && squad[i] != speaker && squad[i] != npc &&
        npc->getPosition().distance(squad[i]->getPosition()) <
            g_proximityRadius)
      g_barterSquad.push_back(squad[i]->getHandle());
  Character *first = Picked();
  g_barterSpeakerKey = first ? HandleKey(first) : 0;

  BuildBarterWindow();
  SetBarterHistory(GetJsonValue(thread, "lines"));
  RefreshBarterLists();
}

bool ShowBarterOffer(unsigned int npcKey, unsigned int speakerKey,
                     const std::vector<std::string> &deal) {
  if (!g_barterWindow || npcKey != g_barterNpcKey || deal.empty())
    return false;
  Deal loaded;
  loaded.cats[PLAYER_SIDE] = loaded.cats[NPC_SIDE] = 0;
  for (size_t i = 0; i < deal.size(); ++i) {
    DealLine line = ParseDealLine(deal[i]);
    if (line.kind == "CATS")
      loaded.cats[line.holder == "npc" ? NPC_SIDE : PLAYER_SIDE] = line.count;
    else if (line.holder == "npc")
      AddLot(loaded.lots[NPC_SIDE], 0, line.name, line.count);
    else
      AddLot(loaded.lots[PLAYER_SIDE],
             line.holder == "player"
                 ? speakerKey
                 : (unsigned int)strtoul(line.holder.c_str(), NULL, 10),
             line.name, line.count);
  }
  g_deal = loaded;
  g_agreed = loaded;
  g_offerHeld = true;
  for (int side = 0; side < 2; ++side)
    SetCaption(g_barterCats[side], ToString(loaded.cats[side]));
  SetStatus("{name} agrees to this deal.");
  RefreshBarterLists();
  return true;
}

void BarterOfferGone() {
  g_offerHeld = false;
  if (g_barterWindow)
    UpdateAccept();
}

// The first line is 1 while the action dialogue stays open, 0 after it ended,
// or error when the server gave no reply. The thread lines follow it
void SetBarterTurn(const std::string &data) {
  if (!g_barterWindow)
    return;
  size_t eol = data.find('\n');
  std::string flag = data.substr(0, eol);
  flag.erase(0, flag.find_first_not_of(" \t\r"));
  flag.erase(flag.find_last_not_of(" \t\r") + 1);
  std::string lines =
      eol == std::string::npos ? std::string() : data.substr(eol + 1);
  if (!lines.empty())
    SetBarterHistory(lines);
  g_barterWaiting = false;
  g_barterSendBtn->setEnabled(true);
  if (g_offerHeld)
    SetStatus("{name} agrees to this deal.");
  else if (flag == "1")
    SetStatus("");
  else if (flag == "0")
    SetStatus("{name} ended the trade.");
  else
    SetStatus(
        "{name} could not respond. (Something went wrong, is SSR configured?)");
  RefreshBarterLists();
}

} // namespace UI
} // namespace SentientSands
