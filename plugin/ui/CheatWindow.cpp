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
#include <map>
#include <set>
#include <vector>

namespace SentientSands {
namespace UI {

static MyGUI::Window *g_cheatWindow = nullptr;
static MyGUI::Button *g_cheatCharacterBtn = nullptr;
static MyGUI::EditBox *g_cheatName = nullptr;
static MyGUI::TextBox *g_cheatCats = nullptr;
static MyGUI::EditBox *g_cheatAmount = nullptr;
static MyGUI::TextBox *g_cheatRelation = nullptr;
static MyGUI::EditBox *g_cheatPoints = nullptr;
static int g_cheatRelationRequest = 0;
static MyGUI::ListBox *g_cheatStatList = nullptr;
static MyGUI::EditBox *g_cheatLevel = nullptr;
static MyGUI::ListBox *g_cheatItemList = nullptr;
static MyGUI::EditBox *g_cheatCount = nullptr;
static std::vector<hand> g_cheatCharacters;
static size_t g_cheatCharacterIndex = 0;
static std::vector<StatsEnumerated> g_cheatStats;

struct CheatItem {
  std::string label;
  GameData *data;
  GameData *model;
  GameData *maker;
  int level;
};
static std::vector<CheatItem> g_cheatItems;
static std::vector<size_t> g_cheatShown;

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

// The relation lives in the server's profile; an empty one only reads it
static void RequestCheatRelation(const std::string &relation) {
  Character *c = CheatCharacter();
  g_cheatRelation->setCaption("Relation: ...");
  if (!c)
    return;
  StartJournalRequest(
      L"/relation",
      "{\"context\": " + GetDetailedContext(c) +
          (relation.empty() ? "" : ", \"relation\": " + relation) + "}",
      "CHEAT_RELATION", ToString(++g_cheatRelationRequest));
}

void SetCheatRelation(const std::string &data) {
  std::string tag, reply;
  if (!g_cheatWindow || !SplitJournalReply(data, tag, reply) ||
      atoi(tag.c_str()) != g_cheatRelationRequest)
    return;
  std::string relation = GetJsonValue(reply, "relation");
  g_cheatRelation->setCaption(
      Utf8ToWide("Relation: " + (relation.empty() ? "?" : relation)).c_str());
}

static void ShowCheatCharacter() {
  Character *c = CheatCharacter();
  std::string name = c ? c->getName() : "?";
  g_cheatCharacterBtn->setCaption(Utf8ToWide(name).c_str());
  g_cheatName->setCaption(Utf8ToWide(c ? name : "").c_str());
  FillStatList();
  RequestCheatRelation("");
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

// Wear lowers the max health of a part, so each part gets the values of an
// unworn part before the heal
static void OnCheatHealClick(MyGUI::Widget *sender) {
  Character *c = CheatCharacter();
  if (!c)
    return;
  MedicalSystem *medical = c->getMedical();
  for (auto it = medical->status.begin(); it != medical->status.end(); ++it) {
    it->second.hitChanceMult = 1.0f;
    it->second.wearDamage = 0.0f;
    it->second.juryRigging = 0.0f;
  }
  c->healCompletely();
  Log(LOG_INFO, "CHEAT: Healed " + c->getName());
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

static void OnCheatSetRelationClick(MyGUI::Widget *sender) {
  Character *c = CheatCharacter();
  std::string text = Trimmed(g_cheatPoints);
  char *end = NULL;
  long points = strtol(text.c_str(), &end, 10);
  if (!c || text.empty() || *end != '\0')
    return;
  points = points > 100 ? 100 : points < -100 ? -100 : points;
  Log(LOG_INFO, "CHEAT: Setting " + c->getName() + "'s relation to " +
                    ToString((int)points));
  RequestCheatRelation(ToString((int)points));
}

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

struct WeaponGrade {
  int level;
  GameData *model;
  GameData *maker;
};

// The levels of the armour grades on the wiki, which crossbows share; the game
// showed 40 as Standard and 60 as High on armour
static const struct {
  const char *name;
  int level;
} GEAR_GRADES[] = {{"Prototype", 5}, {"Shoddy", 20},     {"Standard", 40},
                     {"High", 60},     {"Specialist", 80}, {"Masterwork", 95}};

static bool ByLevel(const WeaponGrade &a, const WeaponGrade &b) {
  return a.level < b.level;
}

static void AddItemRecords(GameDataManager &data,
                           std::map<std::string, GameData *> &records) {
  boost::unordered::unordered_map<std::string, GameData *>::iterator it;
  for (it = data.gamedataSID.begin(); it != data.gamedataSID.end(); ++it) {
    GameData *record = it->second;
    if (record && !record->name.empty() && IsItem(record->type))
      records.insert(std::make_pair(record->name, record));
  }
}

// A manufacturer lists the weapons that it makes and its grades, each grade
// with its level. The player's own manufacturer marks a weapon as homemade, so
// the manufacturer of a trader wins.
static void AddWeaponGrades(
    GameDataManager &data,
    std::map<std::string, std::map<std::string, WeaponGrade> > &grades) {
  boost::unordered::unordered_map<std::string, GameData *>::iterator it;
  for (it = data.gamedataSID.begin(); it != data.gamedataSID.end(); ++it) {
    GameData *maker = it->second;
    if (!maker || maker->type != WEAPON_MANUFACTURER)
      continue;
    const Ogre::vector<GameDataReference>::type *weapons =
        maker->getReferenceListIfExists("weapon types");
    const Ogre::vector<GameDataReference>::type *models =
        maker->getReferenceListIfExists("weapon models");
    for (size_t m = 0; weapons && models && m < models->size(); ++m) {
      GameData *model = data.getData(models->at(m).sid);
      int level = models->at(m).values.value[0];
      if (!model || level < 1)
        continue;
      for (size_t w = 0; w < weapons->size(); ++w) {
        WeaponGrade &grade = grades[weapons->at(w).sid][model->name];
        if (grade.model && grade.maker->stringID != "PLAYER_WEAPONS")
          continue;
        grade.level = level;
        grade.model = model;
        grade.maker = maker;
      }
    }
  }
}

static void AddCheatItem(const std::string &label, GameData *data,
                         GameData *model, GameData *maker, int level) {
  CheatItem item;
  item.label = label;
  item.data = data;
  item.model = model;
  item.maker = maker;
  item.level = level;
  g_cheatItems.push_back(item);
}

static void FindCheatItems(GameWorld *world) {
  std::map<std::string, GameData *> records;
  AddItemRecords(world->leveldata, records);
  AddItemRecords(world->gamedata, records);
  std::map<std::string, std::map<std::string, WeaponGrade> > weaponGrades;
  AddWeaponGrades(world->gamedata, weaponGrades);
  g_cheatItems.clear();
  std::map<std::string, GameData *>::iterator it;
  for (it = records.begin(); it != records.end(); ++it) {
    GameData *data = it->second;
    std::vector<WeaponGrade> grades;
    std::map<std::string, std::map<std::string, WeaponGrade> >::iterator found =
        weaponGrades.find(data->stringID);
    if (data->type == WEAPON && found != weaponGrades.end())
      for (std::map<std::string, WeaponGrade>::iterator g =
               found->second.begin();
           g != found->second.end(); ++g)
        grades.push_back(g->second);
    std::stable_sort(grades.begin(), grades.end(), ByLevel);
    for (size_t g = 0; g < grades.size(); ++g)
      AddCheatItem(it->first + " (" + grades[g].model->name + ")", data,
                   grades[g].model, grades[g].maker, grades[g].level);
    if (data->type == ARMOUR || data->type == CROSSBOW)
      for (size_t g = 0; g < sizeof(GEAR_GRADES) / sizeof(GEAR_GRADES[0]); ++g)
        AddCheatItem(it->first + " (" + GEAR_GRADES[g].name + ")", data, NULL,
                     NULL, GEAR_GRADES[g].level);
    else if (grades.empty())
      AddCheatItem(it->first, data, NULL, NULL, 0);
  }
}

static void OnCheatSearchChange(MyGUI::EditBox *sender) {
  std::string wanted = Lower(sender->getCaption().asUTF8());
  g_cheatItemList->removeAllItems();
  g_cheatShown.clear();
  for (size_t i = 0; i < g_cheatItems.size(); ++i) {
    if (Lower(g_cheatItems[i].label).find(wanted) == std::string::npos)
      continue;
    g_cheatShown.push_back(i);
    g_cheatItemList->addItem(Utf8ToWide(g_cheatItems[i].label).c_str());
  }
}

static void OnCheatSpawnClick(MyGUI::Widget *sender) {
  size_t index = g_cheatItemList->getIndexSelected();
  Character *c = CheatCharacter();
  if (index == MyGUI::ITEM_NONE || !c)
    return;
  const CheatItem &item = g_cheatItems[g_cheatShown[index]];
  QueuedAction act;
  act.type = ACT_SPAWN_ITEM;
  act.actor = c->getHandle();
  act.target = c->getHandle();
  act.message = item.data->name + "|" + item.label;
  act.itemData = item.data;
  act.itemModel = item.model;
  act.itemMaker = item.maker;
  act.itemLevel = item.level;
  act.taskValue = atoi(Trimmed(g_cheatCount).c_str());
  if (act.taskValue < 1)
    act.taskValue = 1;
  EnterCriticalSection(&g_uiMutex);
  g_uiActionQueue.push_back(act);
  LeaveCriticalSection(&g_uiMutex);
  Log(LOG_INFO, "CHEAT: Spawning " + ToString(act.taskValue) + " " +
                    item.label + " for " + c->getName());
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
  FindCheatItems(world);
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
  AddJournalButton(client, "Heal", 0.165f, 0.20f, 0.135f, OnCheatHealClick,
                   "SentientSands_CheatHealBtn");
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
  g_cheatRelation =
      AddJournalLine(client, 0.02f, 0.64f, 0.28f, "SentientSands_CheatRelation");
  AddJournalLine(client, 0.02f, 0.72f, 0.07f, "SentientSands_CheatPointsLabel")
      ->setCaption("Points");
  g_cheatPoints = AddJournalLineBox(client, 0.09f, 0.72f, 0.21f,
                                    "SentientSands_CheatPoints");
  AddJournalButton(client, "Set Relation", 0.02f, 0.80f, 0.135f,
                   OnCheatSetRelationClick, "SentientSands_CheatSetRelationBtn");

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
