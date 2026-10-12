// The renewal popup of a hire that a FOLLOW deal made. The server keeps the
// terms of each such hire, and the plugin finds the hires by a scan, because a
// save holds the contracts and the plugin keeps nothing across a save load.
// The game ends a contract at its expiry, so the popup opens just before it and
// pauses the game until the player answers.
#include "RenewWindow.h"
#include "../core/Comm.h"
#include "../core/Globals.h"
#include "../core/Utils.h"
#include "../game/Context.h"
#include "OfferWindow.h"

#include <kenshi/AI/Blackboard.h>
#include <kenshi/Character.h>
#include <kenshi/GameWorld.h>
#include <kenshi/PlayerInterface.h>

#include <mygui/MyGUI_Button.h>
#include <mygui/MyGUI_Delegate.h>
#include <mygui/MyGUI_EditBox.h>
#include <mygui/MyGUI_Gui.h>
#include <mygui/MyGUI_Window.h>

#include <sstream>
#include <vector>

namespace SentientSands {
namespace UI {

static const DWORD HIRE_SCAN_MS = 2000;
static const double HIRE_MARGIN_HOURS = 0.1;

struct Hire {
  unsigned int key;
  // A save load gives the same handles to new objects
  Character *npc;
  // A renewal or a new hire gives a new expiry, so its terms are asked again
  double expiry;
  unsigned int ask;
  // 0 for a hire of the game's own dialogues, which expires as in the game
  int hours;
  int fee;
  std::string text;
  bool due;
};
static std::vector<Hire> g_hires;
static unsigned int g_lastAsk = 0;

static MyGUI::Window *g_renewWindow = nullptr;
static Hire g_renewal;
static bool g_renewPaused = false;

struct HireAsk {
  unsigned int ask;
  std::string json;
};

static DWORD WINAPI HireTermsThread(LPVOID lpParam) {
  HireAsk *t = (HireAsk *)lpParam;
  std::string response = PostToPythonWithResponse(L"/hire_terms", t->json);
  if (GetJsonValue(response, "status") == "ok") {
    EnterCriticalSection(&g_msgMutex);
    g_messageQueue.push_back("CMD: HIRE_TERMS: " + ToString(t->ask) + " " +
                             GetJsonValue(response, "hours") + " " +
                             GetJsonValue(response, "fee") + "\n" +
                             GetJsonValue(response, "text"));
    LeaveCriticalSection(&g_msgMutex);
  }
  delete t;
  return 0;
}

static bool Hired(Character *c, double &expiry) {
  Blackboard *board = c->getBlackboard();
  if (!board || (uintptr_t)board < 0x1000 || !board->hasContractJob())
    return false;
  expiry = board->getContractExpiryTime().getTotalHours();
  return true;
}

static void AskTerms(Character *c, double expiry) {
  Hire hire;
  hire.key = HandleKey(c);
  hire.npc = c;
  hire.expiry = expiry;
  hire.ask = ++g_lastAsk;
  hire.hours = 0;
  hire.fee = 0;
  hire.due = false;
  for (size_t i = 0; i < g_hires.size(); ++i)
    if (g_hires[i].key == hire.key) {
      g_hires.erase(g_hires.begin() + i);
      break;
    }
  g_hires.push_back(hire);
  HireAsk *t = new HireAsk();
  t->ask = hire.ask;
  t->json = "{\"npc_id\": \"" + EscapeJSON(GetNpcId(c)) + "\", \"npc\": \"" +
            EscapeJSON(c->getName()) + "\"}";
  StartThread(HireTermsThread, t);
}

static void ScanHires(GameWorld *world) {
  const auto &chars = world->getCharacterUpdateList();
  for (auto it = chars.begin(); it != chars.end(); ++it) {
    Character *c = *it;
    double expiry;
    if (!c || (uintptr_t)c < 0x1000 || !Hired(c, expiry))
      continue;
    unsigned int key = HandleKey(c);
    bool known = false;
    for (size_t i = 0; i < g_hires.size() && !known; ++i)
      known = g_hires[i].key == key && g_hires[i].npc == c &&
              g_hires[i].expiry == expiry;
    if (!known)
      AskTerms(c, expiry);
  }
}

// The hire may still wait for its terms, so the popup opens when they arrive
void ExpireHire(Character *npc) {
  double expiry;
  if (!Hired(npc, expiry))
    return;
  unsigned int key = HandleKey(npc);
  for (size_t i = 0; i < g_hires.size(); ++i)
    if (g_hires[i].key == key && g_hires[i].npc == npc &&
        g_hires[i].expiry == expiry) {
      g_hires[i].due = true;
      return;
    }
  AskTerms(npc, expiry);
  g_hires.back().due = true;
}

// The data holds the ask, the hours, and the fee on its first line, and the
// text of the popup on its second
void SetHireTerms(const std::string &data) {
  std::istringstream in(data);
  unsigned int ask = 0;
  Hire terms;
  in >> ask >> terms.hours >> terms.fee;
  in.ignore(1);
  std::getline(in, terms.text);
  for (size_t i = 0; i < g_hires.size(); ++i)
    if (g_hires[i].ask == ask) {
      g_hires[i].hours = terms.hours;
      g_hires[i].fee = terms.fee;
      g_hires[i].text = terms.text;
    }
}

static Character *NearestMember(GameWorld *world, Character *npc) {
  Character *nearest = nullptr;
  float best = 0.0f;
  lektor<Character *> &members = world->player->playerCharacters;
  for (uint32_t i = 0; i < members.size(); ++i) {
    Character *c = members.stuff[i];
    if (!c || c->isDead())
      continue;
    float dist = npc->getPosition().distance(c->getPosition());
    if (!nearest || dist < best) {
      nearest = c;
      best = dist;
    }
  }
  return nearest;
}

static void QueueAction(ActionType type, Character *npc, Character *target,
                        int value) {
  QueuedAction act;
  act.type = type;
  act.actor = npc->getHandle();
  if (target)
    act.target = target->getHandle();
  act.taskValue = value;
  EnterCriticalSection(&g_uiMutex);
  g_uiActionQueue.push_back(act);
  LeaveCriticalSection(&g_uiMutex);
}

static void CloseRenewUI() {
  if (g_renewWindow && MyGUI::Gui::getInstancePtr())
    MyGUI::Gui::getInstancePtr()->destroyWidget(g_renewWindow);
  g_renewWindow = nullptr;
  GameWorld *world = *ppWorld;
  if (g_renewPaused && world)
    world->userPause(false);
  g_renewPaused = false;
}

static void EndHire(Character *npc) {
  QueueAction(ACT_END_HIRE, npc, nullptr, 0);
  AsyncPostToPython(L"/hire_end", "{\"npc_id\": \"" +
                                      EscapeJSON(GetNpcId(npc)) +
                                      "\", \"npc\": \"" +
                                      EscapeJSON(npc->getName()) + "\"}");
}

static void OnRenewAccept(MyGUI::Widget *sender) {
  GameWorld *world = *ppWorld;
  Character *npc = KeyedCharacter(g_renewal.key);
  CloseRenewUI();
  if (!world || !world->player || !npc || npc != g_renewal.npc)
    return;
  Character *payer = world->player->playerCharacters.size() > 0
                         ? world->player->playerCharacters[0]
                         : nullptr;
  if (!payer || MoneyOf(payer) < g_renewal.fee) {
    NotifyText(Fill(T("You no longer have {what}."), "{what}",
                    ToString(g_renewal.fee) + " cats"));
    EndHire(npc);
    return;
  }
  if (g_renewal.fee > 0)
    QueueAction(ACT_TAKE_CATS, npc, nullptr, g_renewal.fee);
  QueueAction(ACT_HIRE, npc, NearestMember(world, npc), g_renewal.hours);
}

static void OnRenewDecline(MyGUI::Widget *sender) {
  Character *npc = KeyedCharacter(g_renewal.key);
  CloseRenewUI();
  if (npc && npc == g_renewal.npc)
    EndHire(npc);
}

static void OnRenewWindowButtonPressed(MyGUI::Window *sender,
                                       const std::string &name) {
  if (name == "close")
    OnRenewDecline(sender);
}

static MyGUI::Button *AddRenewButton(MyGUI::Widget *client, const char *key,
                                     float left,
                                     void (*onClick)(MyGUI::Widget *)) {
  MyGUI::Button *button = client->createWidgetReal<MyGUI::Button>(
      "Kenshi_Button1", left, 0.72f, 0.25f, 0.2f,
      MyGUI::Align::Bottom | MyGUI::Align::Left,
      std::string("SentientSands_Renew") + key);
  button->setCaption(Utf8ToWide(T(key)).c_str());
  button->eventMouseButtonClick += MyGUI::newDelegate(onClick);
  return button;
}

static void ShowRenewUI(GameWorld *world, const Hire &hire) {
  MyGUI::Gui *gui = MyGUI::Gui::getInstancePtr();
  if (!gui)
    return;
  g_renewal = hire;
  g_renewPaused = !world->isPaused();
  if (g_renewPaused)
    world->userPause(true);

  g_renewWindow = gui->createWidgetReal<MyGUI::Window>(
      "Kenshi_WindowCX", 0.3f, 0.36f, 0.4f, 0.24f, MyGUI::Align::Center,
      "Popup", "SentientSands_RenewWindow");
  g_renewWindow->setCaption(
      Utf8ToWide(Fill(T("Offer from {name}"), "{name}", hire.npc->getName()))
          .c_str());
  g_renewWindow->eventWindowButtonPressed +=
      MyGUI::newDelegate(OnRenewWindowButtonPressed);
  MyGUI::Widget *client = g_renewWindow->getClientWidget();

  MyGUI::EditBox *text = client->createWidgetReal<MyGUI::EditBox>(
      "Kenshi_WordWrap", 0.05f, 0.05f, 0.9f, 0.5f,
      MyGUI::Align::Top | MyGUI::Align::HStretch, "SentientSands_RenewText");
  text->setEditMultiLine(true);
  text->setEditWordWrap(true);
  text->setEditReadOnly(true);
  text->setTextAlign(MyGUI::Align::Left | MyGUI::Align::Top);
  text->setFontHeight(18);
  text->setCaption(Utf8ToWide(hire.text).c_str());

  AddRenewButton(client, "Accept", 0.18f, OnRenewAccept);
  AddRenewButton(client, "Decline", 0.57f, OnRenewDecline);
}

void WatchHires(GameWorld *world) {
  if (g_renewWindow)
    return;
  static DWORD lastScan = 0;
  if (GetTickCount() - lastScan >= HIRE_SCAN_MS) {
    lastScan = GetTickCount();
    ScanHires(world);
  }
  double now = world->getTimeStamp_inGameHours().getTotalHours();
  for (size_t i = 0; i < g_hires.size();) {
    Character *c = KeyedCharacter(g_hires[i].key);
    double expiry;
    if (!c || c != g_hires[i].npc || !Hired(c, expiry) ||
        expiry != g_hires[i].expiry) {
      g_hires.erase(g_hires.begin() + i);
      continue;
    }
    if (g_hires[i].hours > 0 &&
        (g_hires[i].due || now >= expiry - HIRE_MARGIN_HOURS)) {
      Hire hire = g_hires[i];
      g_hires.erase(g_hires.begin() + i);
      ShowRenewUI(world, hire);
      return;
    }
    ++i;
  }
}

} // namespace UI
} // namespace SentientSands
