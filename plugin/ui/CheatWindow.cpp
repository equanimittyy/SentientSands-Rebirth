#include "CheatWindow.h"
#include "JournalWindow.h"
#include "../core/Comm.h"
#include "../core/Globals.h"
#include "../core/Utils.h"
#include "../game/Context.h"

#include <kenshi/CharStats.h>
#include <kenshi/Character.h>
#include <kenshi/GameData.h>
#include <kenshi/GameWorld.h>
#include <kenshi/Platoon.h>
#include <kenshi/PlayerInterface.h>
#include <kenshi/util/hand.h>

#include <mygui/MyGUI_Button.h>
#include <mygui/MyGUI_Delegate.h>
#include <mygui/MyGUI_EditBox.h>
#include <mygui/MyGUI_Gui.h>
#include <mygui/MyGUI_ListBox.h>
#include <mygui/MyGUI_TextBox.h>
#include <mygui/MyGUI_Window.h>

#include <algorithm>
#include <cstdlib>
#include <set>
#include <vector>

namespace SentientSands {
namespace UI {

static MyGUI::Window *g_cheatWindow = nullptr;
static MyGUI::Button *g_cheatCharacterBtn = nullptr;
static MyGUI::EditBox *g_cheatName = nullptr;
static MyGUI::TextBox *g_cheatCats = nullptr;
static MyGUI::EditBox *g_cheatAmount = nullptr;
static MyGUI::ListBox *g_cheatStatList = nullptr;
static MyGUI::EditBox *g_cheatLevel = nullptr;
static MyGUI::ListBox *g_cheatItemList = nullptr;
static MyGUI::EditBox *g_cheatCount = nullptr;
static std::vector<hand> g_cheatCharacters;
static size_t g_cheatCharacterIndex = 0;
static std::vector<StatsEnumerated> g_cheatStats;
static std::vector<std::string> g_cheatItemNames;

static void CloseCheatUI() {
  if (g_cheatWindow && MyGUI::Gui::getInstancePtr())
    MyGUI::Gui::getInstancePtr()->destroyWidget(g_cheatWindow);
  g_cheatWindow = nullptr;
}

static std::string Lower(std::string text) {
  std::transform(text.begin(), text.end(), text.begin(), ::tolower);
  return text;
}

static std::string Trimmed(MyGUI::EditBox *box) {
  std::string text = box->getCaption().asUTF8();
  text.erase(0, text.find_first_not_of(" \t\r\n"));
  text.erase(text.find_last_not_of(" \t\r\n") + 1);
  return text;
}

static Character *CheatCharacter() {
  return g_cheatCharacters.empty()
             ? NULL
             : g_cheatCharacters[g_cheatCharacterIndex].getCharacter();
}

// The cats belong to the whole player faction, as TAKE_CATS reads them
static Character *Payer() {
  GameWorld *world = ppWorld ? *ppWorld : NULL;
  return world && world->player && world->player->playerCharacters.size() > 0
             ? world->player->playerCharacters[0]
             : NULL;
}

static int MoneyOf(Character *c) {
  int money = c->getMoney();
  if (money <= 0 && c->getOwnerships())
    money = c->getOwnerships()->getMoney();
  return money;
}

static void ShowCats() {
  Character *payer = Payer();
  g_cheatCats->setCaption(
      "Player cats: " + (payer ? ToString(MoneyOf(payer)) : std::string("?")));
}

static void FillStatList() {
  Character *c = CheatCharacter();
  CharStats *stats = c ? c->getStats() : NULL;
  g_cheatStatList->removeAllItems();
  for (size_t i = 0; stats && i < g_cheatStats.size(); ++i)
    g_cheatStatList->addItem(
        Utf8ToWide(CharStats::getStatName(g_cheatStats[i]) + ": " +
                   ToString((int)stats->getStatRef(g_cheatStats[i])))
            .c_str());
}

static void ShowCheatCharacter() {
  Character *c = CheatCharacter();
  std::string name = c ? c->getName() : "?";
  g_cheatCharacterBtn->setCaption(Utf8ToWide(name).c_str());
  g_cheatName->setCaption(Utf8ToWide(c ? name : "").c_str());
  FillStatList();
}

static void OnCheatCharacterClick(MyGUI::Widget *sender) {
  if (g_cheatCharacters.empty())
    return;
  g_cheatCharacterIndex =
      (g_cheatCharacterIndex + 1) % g_cheatCharacters.size();
  ShowCheatCharacter();
}

static void OnCheatRenameClick(MyGUI::Widget *sender) {
  Character *c = CheatCharacter();
  std::string newName = Trimmed(g_cheatName);
  if (!c || newName.empty())
    return;
  std::string oldName = c->getName();
  c->setName(newName);
  Log(LOG_INFO, "NAME: " + oldName + " is now " + newName);
  AsyncPostToPython(L"/rename", "{\"old_name\": \"" + EscapeJSON(oldName) +
                                    "\", \"new_name\": \"" +
                                    EscapeJSON(newName) + "\", \"context\": " +
                                    GetDetailedContext(c) + "}");
  ShowCheatCharacter();
}

static void ChangeCats(int sign) {
  Character *payer = Payer();
  int amount = atoi(Trimmed(g_cheatAmount).c_str());
  if (!payer || amount < 1)
    return;
  int money = MoneyOf(payer);
  if (sign < 0 && amount > money)
    amount = money;
  payer->takeMoney(-sign * amount);
  Log(LOG_INFO, "CHEAT: Changed the player's cats by " +
                    ToString(sign * amount));
  ShowCats();
}

static void OnCheatAddCatsClick(MyGUI::Widget *sender) { ChangeCats(1); }
static void OnCheatTakeCatsClick(MyGUI::Widget *sender) { ChangeCats(-1); }

static void OnCheatStatSelect(MyGUI::ListBox *sender, size_t index) {
  Character *c = CheatCharacter();
  CharStats *stats = c ? c->getStats() : NULL;
  if (index != MyGUI::ITEM_NONE && stats)
    g_cheatLevel->setCaption(
        ToString((int)stats->getStatRef(g_cheatStats[index])));
}

static void OnCheatSetStatClick(MyGUI::Widget *sender) {
  size_t index = g_cheatStatList->getIndexSelected();
  Character *c = CheatCharacter();
  CharStats *stats = c ? c->getStats() : NULL;
  std::string text = Trimmed(g_cheatLevel);
  char *end = NULL;
  long level = strtol(text.c_str(), &end, 10);
  if (index == MyGUI::ITEM_NONE || !stats || text.empty() || *end != '\0')
    return;
  level = level > 100 ? 100 : level < 0 ? 0 : level;
  stats->getStatRef(g_cheatStats[index]) = (float)level;
  Log(LOG_INFO, "CHEAT: " + c->getName() + "'s " +
                    CharStats::getStatName(g_cheatStats[index]) + " is now " +
                    ToString((int)level));
  FillStatList();
  g_cheatStatList->setIndexSelected(index);
}

// The types that SPAWN_ITEM finds by name, so each listed name spawns
static bool IsItem(itemType type) {
  return type == ITEM || type == WEAPON || type == ARMOUR ||
         type == CROSSBOW || type == BLUEPRINT || type == LIMB_REPLACEMENT ||
         type == MAP_ITEM;
}

static void AddItemNames(GameDataManager &data, std::set<std::string> &names) {
  boost::unordered::unordered_map<std::string, GameData *>::iterator it;
  for (it = data.gamedataSID.begin(); it != data.gamedataSID.end(); ++it) {
    GameData *record = it->second;
    if (record && !record->name.empty() && IsItem(record->type))
      names.insert(record->name);
  }
}

static void OnCheatSearchChange(MyGUI::EditBox *sender) {
  std::string wanted = Lower(sender->getCaption().asUTF8());
  g_cheatItemList->removeAllItems();
  for (size_t i = 0; i < g_cheatItemNames.size(); ++i)
    if (Lower(g_cheatItemNames[i]).find(wanted) != std::string::npos)
      g_cheatItemList->addItem(Utf8ToWide(g_cheatItemNames[i]).c_str());
}

static void OnCheatSpawnClick(MyGUI::Widget *sender) {
  size_t index = g_cheatItemList->getIndexSelected();
  Character *c = CheatCharacter();
  if (index == MyGUI::ITEM_NONE || !c)
    return;
  QueuedAction act;
  act.type = ACT_SPAWN_ITEM;
  act.actor = c->getHandle();
  act.target = c->getHandle();
  act.message = g_cheatItemList->getItemNameAt(index).asUTF8();
  act.taskValue = atoi(Trimmed(g_cheatCount).c_str());
  if (act.taskValue < 1)
    act.taskValue = 1;
  EnterCriticalSection(&g_uiMutex);
  g_uiActionQueue.push_back(act);
  LeaveCriticalSection(&g_uiMutex);
  Log(LOG_INFO, "CHEAT: Spawning " + ToString(act.taskValue) + " " +
                    act.message + " for " + c->getName());
}

static void OnCheatWindowButtonPressed(MyGUI::Window *sender,
                                       const std::string &name) {
  if (name == "close")
    CloseCheatUI();
}

static MyGUI::ListBox *AddCheatList(MyGUI::Widget *client, float left,
                                    const std::string &name) {
  return client->createWidgetReal<MyGUI::ListBox>(
      "Kenshi_ListBox", left, 0.10f, 0.32f, 0.66f,
      MyGUI::Align::Left | MyGUI::Align::VStretch, name);
}

static void FindCheatCharacters(Character *chatTarget) {
  std::vector<Character *> characters;
  if (chatTarget)
    characters.push_back(chatTarget);
  GetCurrentSquad(characters);
  g_cheatCharacters.clear();
  g_cheatCharacterIndex = 0;
  std::set<unsigned int> keys;
  for (size_t i = 0; i < characters.size(); ++i)
    if (keys.insert(HandleKey(characters[i])).second)
      g_cheatCharacters.push_back(characters[i]->getHandle());
}

void ShowCheatUI(Character *chatTarget) {
  GameWorld *world = ppWorld ? *ppWorld : NULL;
  MyGUI::Gui *gui = MyGUI::Gui::getInstancePtr();
  CloseCheatUI();
  if (!world || !gui)
    return;
  FindCheatCharacters(chatTarget);
  std::set<std::string> names;
  AddItemNames(world->leveldata, names);
  AddItemNames(world->gamedata, names);
  g_cheatItemNames.assign(names.begin(), names.end());
  g_cheatStats.clear();
  for (int i = STAT_NONE + 1; i < STAT_END; ++i)
    if (!CharStats::getStatName((StatsEnumerated)i).empty())
      g_cheatStats.push_back((StatsEnumerated)i);

  g_cheatWindow = gui->createWidgetReal<MyGUI::Window>(
      "Kenshi_WindowCX", 0.1f, 0.1f, 0.8f, 0.8f, MyGUI::Align::Center, "Popup",
      "SentientSands_CheatWindow");
  g_cheatWindow->setCaption("Cheats");
  g_cheatWindow->eventWindowButtonPressed +=
      MyGUI::newDelegate(OnCheatWindowButtonPressed);
  MyGUI::Widget *client = g_cheatWindow->getClientWidget();

  g_cheatCharacterBtn =
      AddJournalButton(client, "", 0.02f, 0.02f, 0.28f, OnCheatCharacterClick,
                       "SentientSands_CheatCharacterBtn");
  AddJournalLine(client, 0.02f, 0.12f, 0.07f, "SentientSands_CheatNameLabel")
      ->setCaption("Name");
  g_cheatName =
      AddJournalLineBox(client, 0.09f, 0.12f, 0.21f, "SentientSands_CheatName");
  AddJournalButton(client, "Rename", 0.02f, 0.20f, 0.135f, OnCheatRenameClick,
                   "SentientSands_CheatRenameBtn");
  g_cheatCats =
      AddJournalLine(client, 0.02f, 0.34f, 0.28f, "SentientSands_CheatCats");
  AddJournalLine(client, 0.02f, 0.42f, 0.07f, "SentientSands_CheatAmountLabel")
      ->setCaption("Amount");
  g_cheatAmount = AddJournalLineBox(client, 0.09f, 0.42f, 0.21f,
                                    "SentientSands_CheatAmount");
  AddJournalButton(client, "Add Cats", 0.02f, 0.50f, 0.135f,
                   OnCheatAddCatsClick, "SentientSands_CheatAddCatsBtn");
  AddJournalButton(client, "Take Cats", 0.165f, 0.50f, 0.135f,
                   OnCheatTakeCatsClick, "SentientSands_CheatTakeCatsBtn");

  AddJournalLine(client, 0.32f, 0.02f, 0.32f, "SentientSands_CheatStatsLabel")
      ->setCaption("Stats");
  g_cheatStatList = AddCheatList(client, 0.32f, "SentientSands_CheatStatList");
  g_cheatStatList->eventListChangePosition +=
      MyGUI::newDelegate(OnCheatStatSelect);
  AddJournalLine(client, 0.32f, 0.79f, 0.07f, "SentientSands_CheatLevelLabel")
      ->setCaption("Level");
  g_cheatLevel = AddJournalLineBox(client, 0.39f, 0.79f, 0.25f,
                                   "SentientSands_CheatLevel");
  AddJournalButton(client, "Set Stat", 0.32f, 0.88f, 0.135f,
                   OnCheatSetStatClick, "SentientSands_CheatSetStatBtn");

  AddJournalLine(client, 0.66f, 0.02f, 0.07f, "SentientSands_CheatSearchLabel")
      ->setCaption("Search");
  MyGUI::EditBox *search = AddJournalLineBox(client, 0.73f, 0.02f, 0.25f,
                                             "SentientSands_CheatSearch");
  search->eventEditTextChange += MyGUI::newDelegate(OnCheatSearchChange);
  g_cheatItemList = AddCheatList(client, 0.66f, "SentientSands_CheatItemList");
  AddJournalLine(client, 0.66f, 0.79f, 0.07f, "SentientSands_CheatCountLabel")
      ->setCaption("Count");
  g_cheatCount = AddJournalLineBox(client, 0.73f, 0.79f, 0.25f,
                                   "SentientSands_CheatCount");
  g_cheatCount->setCaption("1");
  AddJournalButton(client, "Spawn", 0.66f, 0.88f, 0.135f, OnCheatSpawnClick,
                   "SentientSands_CheatSpawnBtn");

  ShowCheatCharacter();
  ShowCats();
  OnCheatSearchChange(search);
}

} // namespace UI
} // namespace SentientSands
