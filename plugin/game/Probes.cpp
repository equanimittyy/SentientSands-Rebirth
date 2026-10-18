#include "Probes.h"
#include "../core/Globals.h"
#include "../core/Utils.h"
#include "Context.h"
#include "GameActions.h"
#include <core/Functions.h>
#include <kenshi/AI/AITaskSystem.h>
#include <kenshi/AI/Blackboard.h>
#include <kenshi/Building/Building.h>
#include <kenshi/Character.h>
#include <kenshi/Dialogue.h>
#include <kenshi/Faction.h>
#include <kenshi/GameData.h>
#include <kenshi/GameWorld.h>
#include <kenshi/Inventory.h>
#include <kenshi/Item.h>
#include <kenshi/MedicalSystem.h>
#include <kenshi/Platoon.h>
#include <kenshi/RaceData.h>
#include <kenshi/ShopTraderInventory.h>
#include <kenshi/StateBroadcastData.h>
#include <kenshi/Tasker.h>
#include <kenshi/util/hand.h>
#include <mygui/MyGUI_EditBox.h>
#include <cstdlib>
#include <map>
#include <vector>

// Probe: every faction's string ID, for the vanilla template's faction files
void LogFactionList() {
  static bool logged = false;
  GameWorld *world = ppWorld ? *ppWorld : NULL;
  if (logged || !LogEnabled(LOG_DEBUG) || !world || !world->factionMgr)
    return;
  const lektor<Faction *> *all = world->factionMgr->getAllFactions();
  if (!all)
    return;
  logged = true;

  for (uint32_t i = 0; i < all->count; ++i) {
    Faction *faction = all->stuff[i];
    if (!faction || !faction->data)
      continue;
    Log(LOG_DEBUG, "FACTION_PROBE: id=" + faction->data->stringID +
                       " name=" + faction->getName() +
                       " data_name=" + faction->data->name +
                       (faction->isThePlayer() ? " player" : "") +
                       (faction->isNotARealFaction() ? " not_real" : ""));
  }
}

static std::string DataLabel(GameData *data) {
  if (!data || (uintptr_t)data < 0x1000)
    return "-";
  return data->stringID + " '" + data->name + "'";
}

template <class Tasks> static std::string TaskKeys(const Tasks &list) {
  std::string keys;
  for (auto it = list.begin(); it != list.end(); ++it) {
    Tasker *task = *it;
    if (!task || (uintptr_t)task < 0x1000 || !task->taskData)
      continue;
    if (!keys.empty())
      keys += ",";
    keys += ToString((int)task->key());
  }
  return keys.empty() ? "-" : keys;
}

std::string OrdersLine(Character *npc) {
  OrdersReceiver *orders = npc->getOrdersReciever();
  if (!orders || (uintptr_t)orders < 0x1000)
    return "";
  const TaskMatch &goal = orders->getCurrentGoal();
  std::string line =
      " goal=" + (goal.taskData ? ToString((int)goal.key()) : std::string("-"));
  line += " orders=" + TaskKeys(orders->orders.list);
  line += " jobs=" + TaskKeys(orders->jobs);
  line += " permajobs=" + TaskKeys(orders->permajobs);
  line += " squad_jobs=";
  for (int p = 0; p < 5; ++p)
    line += (p ? "|" : "") + TaskKeys(orders->squadAIPackage[p]);
  line += " goals=";
  for (int p = 0; p < 5; ++p)
    line += (p ? "|" : "") + TaskKeys(orders->goals[p]);
  return line;
}

// Probe: the role and task data of a character, logged again when it changes.
// Enum values stay numbers for Enums.h. Game thread only: the map has no lock.
void LogNpcRole(Character *npc) {
  static std::map<unsigned int, std::string> logged;
  if (!LogEnabled(LOG_DEBUG) || !npc || (uintptr_t)npc < 0x1000)
    return;
  std::string line;
  line += "template=" + DataLabel(npc->data);
  if (npc->data) {
    auto npcClass = npc->data->idata.find("NPC class");
    if (npcClass != npc->data->idata.end())
      line += " class=" + ToString(npcClass->second);
  }
  StateBroadcastData *state = npc->getStateBroadcast();
  if (state && (uintptr_t)state > 0x1000)
    line += " live_type=" + ToString((int)state->NPCType);
  Faction *faction = npc->getFaction();
  if (faction && (uintptr_t)faction > 0x1000)
    line += " faction='" + faction->getName() + "'";
  ActivePlatoon *active = npc->getPlatoon();
  Platoon *platoon =
      active && (uintptr_t)active > 0x1000 ? active->me : NULL;
  if (platoon && (uintptr_t)platoon > 0x1000)
    line += " squad=" + DataLabel(platoon->squadTemplate) +
            " squad_type=" + ToString((int)platoon->squadType) +
            " leader=" + (active->squadleader == npc ? "1" : "0");
  // Name only: AIPackage.h, which packageData needs, redefines the
  // BlackboardSignalFunctions enum from Blackboard.h (C2011).
  Blackboard *board = BoardOf(npc);
  if (board)
    line += " package='" + board->getCurrentAIPackageName() + "'" +
            " contract=" + (board->hasContractJob() ? "1" : "0");
  line += OrdersLine(npc);
  std::string names;
  for (int i = 0; i < npc->getPermajobCount(); ++i)
    names += (i ? "," : "") + npc->getPermajobName(i);
  line += " permajob_names='" + names + "'";
  unsigned int serial = npc->getHandle().serial;
  if (logged[serial] == line)
    return;
  logged[serial] = line;
  Log(LOG_DEBUG, "ROLE_PROBE: name='" + npc->getName() + "' npc_id=" +
                     GetNpcId(npc) + " " + line);
}

static std::string InventoryLine(Inventory *inv) {
  if (!inv || (uintptr_t)inv < 0x1000)
    return "none";
  // A C-style cast checks nothing (kenshi_gotchas.md), so the override of
  // dropItem in vtable slot 0x38 tells a ShopTraderInventory apart
  void **vtable = *(void ***)inv;
  bool shop = vtable[0x38 / sizeof(void *)] ==
              (void *)KenshiLib::GetRealAddress(
                  &ShopTraderInventory::_NV_dropItem);
  RootObject *owner = inv->getOwner();
  std::string line =
      "owner='" +
      (owner ? ((RootObjectBase *)owner)->getName() : std::string("-")) +
      "' shop=" + (shop ? "1" : "0") +
      " all_items=" + ToString(inv->getAllItems().size()) + " sections=";
  for (auto it = inv->sections.begin(); it != inv->sections.end(); ++it)
    if (it->second)
      line += it->first + ":" +
              ToString((int)it->second->getItems().size()) + ",";
  if (shop) {
    ShopTraderInventory *stock = (ShopTraderInventory *)inv;
    line += " sources=";
    for (auto it = stock->inventories.begin(); it != stock->inventories.end();
         ++it)
      if (it->second)
        line += it->first.toString() + "/" + it->second->name + ":" +
                ToString((int)it->second->getItems().size()) + ",";
  }
  return line;
}

static void LogItems(const std::string &who,
                     const std::vector<Item *> &items) {
  for (uint32_t i = 0; i < items.size(); ++i) {
    Item *item = items[i];
    if (!item || (uintptr_t)item < 0x1000)
      continue;
    Log(LOG_DEBUG,
        "STOCK_PROBE: item who=" + who + " name='" + item->getName() +
            "' data=" + DataLabel(item->data) +
            " type=" + ToString((int)item->objectType) +
            " count=" + ToString(item->quantity) +
            " price=" + ToString(item->getValueSingle(false)) +
            " quality=" + ToString(item->quality) +
            " level=" + ToString(item->getLevel()) +
            " manufacturer=" + DataLabel(item->manufacturerData) +
            " material=" + DataLabel(item->materialData) + " section='" +
            item->inventorySection + "'");
  }
}

static void LogFurniture(const std::string &list,
                         const lektor<Building *> &furniture,
                         std::map<std::string, int> &totals) {
  Log(LOG_DEBUG, "STOCK_PROBE: " + list + "=" + ToString(furniture.size()));
  for (uint32_t i = 0; i < furniture.size(); ++i) {
    Building *piece = furniture[i];
    if (!piece || (uintptr_t)piece < 0x1000)
      continue;
    std::string name = ((RootObjectBase *)piece)->getName();
    Log(LOG_DEBUG, "STOCK_PROBE: " + list + "='" + name + "' handle=" +
                       piece->getHandle().toString() + " function=" +
                       ToString((int)piece->getSpecialFunction()) + " " +
                       InventoryLine(piece->getInventory()));
    std::vector<Item *> stock;
    SectionItems(piece->getInventory(), stock);
    LogItems(list + ":" + name, stock);
    for (size_t s = 0; s < stock.size(); ++s)
      totals[stock[s]->getName()] += stock[s]->quantity;
  }
}

static void ProbeStock(Character *npc, Character *speaker) {
  Building *building = BuildingOf(npc);
  std::string place = "none";
  if (building)
    place = "'" + ((RootObjectBase *)building)->getName() + "' " +
            InventoryLine(building->getInventory());
  Log(LOG_DEBUG, "STOCK_PROBE: name='" + npc->getName() + "' npc " +
                     InventoryLine(npc->getInventory()) + " building=" + place);
  std::vector<Item *> items;
  GetAllCharacterItems(npc, items);
  LogItems("npc", items);

  std::map<std::string, int> counterTotals, furnitureTotals;
  Ownerships *owned = npc->getOwnerships();
  if (owned && (uintptr_t)owned > 0x1000) {
    lektor<Building *> counters;
    owned->getHomeFurnitureOfType(counters, BF_SHOP);
    LogFurniture("counter", counters, counterTotals);
  }
  if (building) {
    lektor<Building *> furniture;
    building->findAllFurnitureWithFunction(furniture, BF_ANY);
    LogFurniture("furniture", furniture, furnitureTotals);
  }
  std::string line;
  for (auto it = furnitureTotals.begin(); it != furnitureTotals.end(); ++it)
    line += " '" + it->first + "'=" + ToString(it->second) + "/" +
            ToString(counterTotals[it->first]);
  Log(LOG_DEBUG, "STOCK_PROBE: totals furniture/counter" + line);

  if (speaker) {
    items.clear();
    GetAllCharacterItems(speaker, items);
    LogItems("speaker", items);
  }
}

static void ProbeFirstAid(Character *npc, Character *speaker,
                          const std::string &arg) {
  Inventory *inv = npc->getInventory();
  std::string line =
      "name='" + npc->getName() + "' first_aid_item=" +
      (inv && inv->hasItemFunction(ITEM_FIRSTAID) ? "1" : "0") +
      " repair_kit=" +
      (inv && inv->hasItemFunction(ITEM_ROBOTREPAIR) ? "1" : "0");
  if (speaker) {
    bool needsFirstAid, needsRepair, firstAid, repair;
    TreatmentNeeds(speaker, needsFirstAid, needsRepair);
    RaceData *race = speaker->getRace() ? speaker->getRace() : speaker->myRace;
    std::string parts;
    MedicalSystem *med = speaker->getMedical();
    for (uint32_t i = 0; med && i < med->anatomy.size(); ++i) {
      MedicalSystem::HealthPartStatus *part = med->anatomy[i];
      if (part)
        parts += std::string(parts.empty() ? "" : ",") +
                 (part->robotLimb ? "R" : "F") + ToString((int)part->flesh) +
                 "+" + ToString((int)part->bandaging) + "/" +
                 ToString((int)part->maxHealth());
    }
    GameWorld *world = ppWorld ? *ppWorld : NULL;
    TaskType robotOrder = arg == "job"   ? JOB_REPAIR_ROBOT
                          : arg == "aid" ? FIRST_AID_ORDER
                                         : FIRST_AID_ROBOT;
    std::string message =
        StartTreatment(npc, speaker, firstAid, repair, robotOrder);
    if (world)
      world->showPlayerAMessage(message, false);
    line += " speaker='" + speaker->getName() +
            "' health=" + GetHealthStatus(speaker) +
            " robot_race=" + (race && race->robot ? "1" : "0") + " parts=" +
            parts + " needs_first_aid=" + (needsFirstAid ? "1" : "0") +
            " needs_repair=" + (needsRepair ? "1" : "0") +
            " first_aid_order=" + (firstAid ? "1" : "0") +
            " repair_order=" + (repair ? "1" : "0") + " dist=" +
            ToString(npc->getPosition().distance(speaker->getPosition()));
  }
  line += OrdersLine(npc);
  Log(LOG_DEBUG, "FIRSTAID_PROBE: " + line);
}

static void ProbeHire(Character *npc, Character *speaker,
                      const std::string &arg) {
  GameWorld *world = ppWorld ? *ppWorld : NULL;
  Blackboard *board = BoardOf(npc);
  if (!world || !board)
    return;
  std::string action = "log";
  if (arg == "end") {
    board->endContractJob();
    action = "end";
  } else if (arg.find('-') != std::string::npos && speaker) {
    GameData *line = world->gamedata.getData(arg);
    if (line)
      board->setContractJob(line, speaker->getHandle());
    action = line ? "line " + DataLabel(line) : "no_line";
  } else if (!arg.empty() && speaker) {
    GameData *bodyguard = BodyguardPackage();
    if (bodyguard)
      board->_setContractJob(bodyguard, atoi(arg.c_str()),
                             speaker->getHandle());
    action = bodyguard ? "hours " + arg : "no_package";
  }
  Log(LOG_DEBUG,
      "HIRE_PROBE: name='" + npc->getName() + "' action=" + action +
          " contract=" + (board->hasContractJob() ? "1" : "0") + " package='" +
          board->getCurrentAIPackageName() + "' now=" +
          ToString((float)world->getTimeStamp_inGameHours().getTotalHours()) +
          " expiry=" +
          ToString((float)board->getContractExpiryTime().getTotalHours()));
}

void RunProbe(Character *npc, Character *speaker, const std::string &payload) {
  size_t colon = payload.find(':');
  std::string name = payload.substr(0, colon);
  std::string arg;
  if (colon != std::string::npos) {
    arg = payload.substr(colon + 1);
    arg.erase(0, arg.find_first_not_of(' '));
  }
  if (name == "stock")
    ProbeStock(npc, speaker);
  else if (name == "firstaid")
    ProbeFirstAid(npc, speaker, arg);
  else if (name == "hire")
    ProbeHire(npc, speaker, arg);
}

// Probe: what the game changes in the frame that ends the line of a player
// character, which ends on the first unpaused update while an NPC line stays
static hand g_bubbleSpeaker;
static DWORD g_bubbleStart;
static std::string g_bubbleState;
static const DWORD BUBBLE_WATCH_MS = 30000;

void WatchPlayerBubble(Character *speaker) {
  if (!LogEnabled(LOG_DEBUG))
    return;
  g_bubbleSpeaker = speaker->getHandle();
  g_bubbleStart = GetTickCount();
  g_bubbleState.clear();
}

static std::string HandName(const hand &h) {
  Character *c = h.isValid() ? h.getCharacter() : NULL;
  return c ? c->getName() : "";
}

void LogPlayerBubble(GameWorld *world) {
  if (!g_bubbleSpeaker.isValid())
    return;
  Character *speaker = g_bubbleSpeaker.getCharacter();
  Dialogue *d = speaker ? speaker->dialogue : NULL;
  if (!d || (uintptr_t)d <= 0x1000) {
    g_bubbleSpeaker = hand();
    return;
  }
  DialogueSpeechBubble *panel =
      (uintptr_t)d->speechBubblePanel > 0x1000 ? d->speechBubblePanel : NULL;
  MyGUI::EditBox *box =
      panel && (uintptr_t)panel->textBox > 0x1000 ? panel->textBox : NULL;
  float alpha = panel ? panel->getAlpha() : 0.0f;
  std::string state =
      std::string(" paused=") + (world->isPaused() ? "1" : "0") +
      " panel=" + (panel ? "1" : "0") +
      " alpha=" + (alpha <= 0.01f ? "0" : alpha >= 0.99f ? "1" : "fading") +
      " visible=" + (box && box->getVisible() ? "1" : "0") + " text='" +
      (box ? box->getCaption().asUTF8() : "") + "' ended=" +
      (d->_hasEnded ? "1" : "0") + " stays=" +
      (d->staysOnScreen ? "1" : "0") + " conversation=" +
      (d->currentConversation ? "1" : "0") + " target='" +
      HandName(d->conversationTarget) + "' master='" +
      HandName(d->conversationMaster) + "' waiting='" +
      HandName(d->waitingForReplyFrom) + "'";
  // Not on a missing panel: the game may make it in a later frame
  bool gone = d->speechTextTimer <= 0.0f ||
              GetTickCount() - g_bubbleStart > BUBBLE_WATCH_MS;
  if (state != g_bubbleState || gone)
    Log(LOG_DEBUG, "BUBBLE_PROBE: name='" + speaker->getName() + "' after=" +
                       ToString((unsigned int)(GetTickCount() - g_bubbleStart)) +
                       "ms timer=" + ToString(d->speechTextTimer) +
                       " forced=" + ToString(d->speechTextTimer_forced) +
                       state);
  g_bubbleState = state;
  if (gone)
    g_bubbleSpeaker = hand();
}
