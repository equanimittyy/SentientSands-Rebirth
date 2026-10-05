#include "Context.h"
#include "../core/Globals.h"
#include "../core/Utils.h"
#include <kenshi/Building/Building.h>
#include <kenshi/CharStats.h>
#include <kenshi/Character.h>
#include <kenshi/Faction.h>
#include <kenshi/FactionRelations.h>
#include <kenshi/GameData.h>
#include <kenshi/GameWorld.h>
#include <kenshi/InstanceID.h>
#include <kenshi/Inventory.h>
#include <kenshi/Item.h>
#include <kenshi/MedicalSystem.h>
#include <kenshi/Platoon.h>
#include <kenshi/PlayerInterface.h>
#include <kenshi/AI/AITaskSystem.h>
#include <kenshi/AI/Blackboard.h>
#include <kenshi/RaceData.h>
#include <kenshi/StateBroadcastData.h>
#include <kenshi/Tasker.h>
#include <kenshi/Town.h>
// Weather.h redefines WeatherRegion from PhysicsCollection.h; rename its copy
#define WeatherRegion WeatherRegion_WeatherH
#include <kenshi/Weather.h>
#undef WeatherRegion
#include <kenshi/util/hand.h>
#include <map>
#include <set>
#include <vector>

std::string SlotToString(AttachSlot slot) {
  switch (slot) {
  case ATTACH_WEAPON:
    return "weapon";
  case ATTACH_BACK:
    return "back";
  case ATTACH_HAIR:
    return "hair";
  case ATTACH_HAT:
    return "hat";
  case ATTACH_EYES:
    return "eyes";
  case ATTACH_BODY:
    return "body";
  case ATTACH_LEGS:
    return "legs";
  case ATTACH_SHIRT:
    return "shirt";
  case ATTACH_BOOTS:
    return "boots";
  case ATTACH_GLOVES:
    return "gloves";
  case ATTACH_NECK:
    return "neck";
  case ATTACH_BACKPACK:
    return "backpack";
  case ATTACH_BEARD:
    return "beard";
  case ATTACH_BELT:
    return "belt";
  case ATTACH_LEFT_ARM:
    return "left_arm";
  case ATTACH_RIGHT_ARM:
    return "right_arm";
  case ATTACH_LEFT_LEG:
    return "left_leg";
  case ATTACH_RIGHT_LEG:
    return "right_leg";
  default:
    return "none";
  }
}

void GetAllCharacterItems(Character *npc, std::vector<Item *> &outItems) {
  if (!npc)
    return;
  Inventory *inv = npc->getInventory();
  if (!inv)
    return;

  lektor<InventorySection *> &sections = inv->sectionsInSearchOrder;
  for (uint32_t s = 0; s < sections.size(); ++s) {
    InventorySection *sect = sections[s];
    if (sect) {
      const Ogre::vector<InventorySection::SectionItem>::type &items =
          sect->getItems();
      for (uint32_t i = 0; i < items.size(); ++i) {
        if (items[i].item)
          outItems.push_back(items[i].item);
      }
    }
  }

  ContainerItem *backpack = npc->hasABackpackOn();
  if (backpack && backpack->inventory) {
    lektor<InventorySection *> &bpSections =
        backpack->inventory->sectionsInSearchOrder;
    for (uint32_t s = 0; s < bpSections.size(); ++s) {
      InventorySection *sect = bpSections[s];
      if (sect) {
        const Ogre::vector<InventorySection::SectionItem>::type &items =
            sect->getItems();
        for (uint32_t i = 0; i < items.size(); ++i) {
          if (items[i].item)
            outItems.push_back(items[i].item);
        }
      }
    }
  }
}

static std::string GetHealthStatus(Character *npc) {
  if (!npc || (uintptr_t)npc < 0x1000)
    return "Unknown";
  MedicalSystem *med = npc->getMedical();
  if (!med || (uintptr_t)med < 0x1000)
    return "Unknown";

  if (med->dead)
    return "Dead";
  if (med->unconcious)
    return "Unconscious";
  if (npc->_currentProneState == PS_PLAYING_DEAD)
    return "Playing Dead";

  bool crippled = false;
  if (med->leftLeg && med->leftLeg->flesh < 0)
    crippled = true;
  if (med->rightLeg && med->rightLeg->flesh < 0)
    crippled = true;

  bool injured = false;
  MedicalSystem::HealthPartStatus *parts[6] = {med->getPart(0), med->getPart(1),
                                               med->leftArm,    med->rightArm,
                                               med->leftLeg,    med->rightLeg};
  for (int i = 0; i < 6; ++i) {
    MedicalSystem::HealthPartStatus *p = parts[i];
    if (p && p->flesh < p->maxHealth() * 0.70f)
      injured = true;
  }

  if (crippled)
    return "Crippled";
  if (injured)
    return "Injured";
  return "Healthy";
}

static std::string GetVisibleEquipment(Character *npc) {
  if (!npc || (uintptr_t)npc < 0x1000)
    return "";
  Inventory *inv = npc->getInventory();
  if (!inv || (uintptr_t)inv < 0x1000)
    return "";

  std::string eq = "";
  lektor<Item *> armor;
  inv->getEquippedArmour(armor);
  for (uint32_t i = 0; i < armor.size(); ++i) {
    if (armor.stuff[i] && (uintptr_t)armor.stuff[i] > 0x1000) {
      if (!eq.empty())
        eq += ", ";
      eq += armor.stuff[i]->getName();
    }
  }

  lektor<Item *> weapons;
  inv->getEquippedWeapons(weapons);
  for (uint32_t i = 0; i < weapons.size(); ++i) {
    if (weapons.stuff[i] && (uintptr_t)weapons.stuff[i] > 0x1000) {
      if (!eq.empty())
        eq += ", ";
      eq += weapons.stuff[i]->getName();
    }
  }
  return eq;
}

// The serial is the only member of a handle that survives a recruit
std::string GetNpcId(Character *npc) {
  if (npc->isUnique() && npc->data)
    return "u:" + npc->data->stringID;
  return "h:" + ToString(npc->getHandle().serial);
}

// The zone around the camera, for example Vain: the game gives no zone for each
// character, and a chat happens near the camera. KenshiLib does not map slot
// 0x10 of the zone object, so only a pointer that is a zone record is followed.
static std::string ZoneName() {
  static std::set<GameData *> zones;
  GameWorld *world = ppWorld ? *ppWorld : NULL;
  WeatherSystem *weather = WeatherSystem::getInstance();
  if (!world || !weather || !weather->ActiveRegion)
    return "";

  if (zones.empty()) {
    lektor<GameData *> list;
    world->gamedata.getDataOfType(list, BIOME_GROUP);
    for (uint32_t i = 0; i < list.size(); ++i) {
      if (list[i])
        zones.insert(list[i]);
    }
  }
  GameData *zone = *(GameData **)((char *)weather->ActiveRegion + 0x10);
  return zones.count(zone) ? zone->name : "";
}

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

static std::string TaskKeys(const lektor<Tasker *> &list) {
  std::string keys;
  for (uint32_t i = 0; i < list.count; ++i) {
    Tasker *task = list.stuff[i];
    if (!task || (uintptr_t)task < 0x1000 || !task->taskData)
      continue;
    if (!keys.empty())
      keys += ",";
    keys += ToString((int)task->key());
  }
  return keys.empty() ? "-" : keys;
}

#define ROLE_TASK(task) {task, #task}
// The squad jobs that tell what an NPC does, by their TaskType names.
// server/chat/current_job.py maps them to phrases, and its tests read this list.
static const struct {
  TaskType type;
  const char *name;
} ROLE_TASKS[] = {
    ROLE_TASK(STAND_AT_SHOPKEEPER_NODE),
    ROLE_TASK(WANDERING_TRADER),
    ROLE_TASK(SIT_ON_THRONE),
    ROLE_TASK(MAN_THE_GATE),
    ROLE_TASK(STAND_AT_GUARD_NODE_HOMETOWN_OUTSIDE),
    ROLE_TASK(STAND_AT_BUILDING_DEFENSIVE_NODE),
    ROLE_TASK(STAND_AT_BUILDING_GUARD_NODE),
    ROLE_TASK(STAND_AT_GUARD_NODE_HOMEBUILDING_INDOORS_ONLY),
    ROLE_TASK(STAND_AT_GUARD_NODE_HOMEBUILDING_IN_OUT),
    ROLE_TASK(CAPTURE_ESCAPING_SLAVES),
    ROLE_TASK(CAPTURE_NEW_SLAVES),
    ROLE_TASK(NEW_SLAVE_PROCESSING),
    ROLE_TASK(PROCESS_AND_STRIP_NEW_SLAVE),
    ROLE_TASK(WORK_THE_SLAVES),
    ROLE_TASK(FIND_CAGE_AND_PUT_IN_IF_BOUNTY),
    ROLE_TASK(HUNT_BOUNTIES),
    ROLE_TASK(POLICE_FREE_PRISONERS_WHEN_DONE),
    ROLE_TASK(AUTO_LABOURING_MINES),
    ROLE_TASK(AUTO_LABOURING_MINES_PRETEND),
    ROLE_TASK(OPERATE_AUTOMATIC_MACHINERY),
    ROLE_TASK(OPERATE_MACHINERY),
    ROLE_TASK(PRETEND_TO_OPERATE_MACHINERY),
    ROLE_TASK(ASSAULT_FORTIFICATIONS_PREFER_GATES),
    ROLE_TASK(ATTACK_TOWN),
    ROLE_TASK(RAID_TOWN),
    ROLE_TASK(BODYGUARD),
    ROLE_TASK(GO_TO_THE_BAR_AND_DRINK),
    ROLE_TASK(RELAX_IN_TOWN_PACKAGE),
    ROLE_TASK(PATROL_TOWN),
    ROLE_TASK(PATROL),
    ROLE_TASK(MAN_A_TURRET),
    ROLE_TASK(MAN_A_TURRET_ON_BUILDING),
    ROLE_TASK(USE_TURRET),
    ROLE_TASK(TRAVEL_TO_TARGET_PACKAGE),
    ROLE_TASK(TRAVEL_TO_TARGET_TOWN),
    ROLE_TASK(TRAVEL_TO_TARGET_TOWN_FAST),
    ROLE_TASK(WANDERER),
    ROLE_TASK(SHOPPING),
    ROLE_TASK(WANDER_TOWN),
    ROLE_TASK(FOLLOW_SLAVEMASTER),
    ROLE_TASK(SIT_AROUND),
    ROLE_TASK(STAY_IN_HOME),
    ROLE_TASK(FOLLOW_SQUADLEADER),
};
#undef ROLE_TASK

std::string RoleJson(Character *npc) {
  bool trader = false;
  bool follower = false;
  std::string jobs;
  try {
    trader = npc->isATrader();
    // A hire or escort contract makes an NPC follow the player without a recruit
    Blackboard *board = npc->getBlackboard();
    follower = board && (uintptr_t)board > 0x1000 && board->hasContractJob();
    OrdersReceiver *orders = npc->getOrdersReciever();
    if (orders && (uintptr_t)orders > 0x1000) {
      for (int p = 0; p < 5; ++p) {
        const lektor<Tasker *> &list = orders->squadAIPackage[p];
        for (uint32_t i = 0; i < list.count; ++i) {
          Tasker *task = list.stuff[i];
          if (!task || (uintptr_t)task < 0x1000 || !task->taskData)
            continue;
          TaskType type = task->key();
          for (size_t r = 0; r < sizeof(ROLE_TASKS) / sizeof(ROLE_TASKS[0]);
               ++r) {
            if (ROLE_TASKS[r].type == type) {
              jobs += std::string(jobs.empty() ? "" : ",") + "\"" +
                      ROLE_TASKS[r].name + "\"";
              break;
            }
          }
        }
      }
    }
  } catch (...) {
  }
  return std::string("\"is_trader\":") + (trader ? "true" : "false") +
         ",\"temporary_follower\":" + (follower ? "true" : "false") +
         ",\"squad_jobs\":[" + jobs + "]";
}

// Probe: the role and task data of a character, logged again when it changes.
// Enum values stay numbers for Enums.h. Game thread only: the map has no lock.
void LogNpcRole(Character *npc) {
  static std::map<unsigned int, std::string> logged;
  if (!LogEnabled(LOG_DEBUG) || !npc || (uintptr_t)npc < 0x1000)
    return;
  std::string line;
  try {
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
  } catch (...) {
    line += " [identity failed]";
  }
  try {
    ActivePlatoon *active = npc->getPlatoon();
    Platoon *platoon =
        active && (uintptr_t)active > 0x1000 ? active->me : NULL;
    if (platoon && (uintptr_t)platoon > 0x1000)
      line += " squad=" + DataLabel(platoon->squadTemplate) +
              " squad_type=" + ToString((int)platoon->squadType) +
              " leader=" + (active->squadleader == npc ? "1" : "0");
    // Name only: AIPackage.h, which packageData needs, redefines the
    // BlackboardSignalFunctions enum from Blackboard.h (C2011).
    Blackboard *board = npc->getBlackboard();
    if (board && (uintptr_t)board > 0x1000)
      line += " package='" + board->getCurrentAIPackageName() + "'" +
              " contract=" + (board->hasContractJob() ? "1" : "0");
  } catch (...) {
    line += " [squad failed]";
  }
  try {
    OrdersReceiver *orders = npc->getOrdersReciever();
    if (orders && (uintptr_t)orders > 0x1000) {
      const TaskMatch &goal = orders->getCurrentGoal();
      line += " goal=" +
              (goal.taskData ? ToString((int)goal.key()) : std::string("-"));
      line += " permajobs=" + TaskKeys(orders->permajobs);
      line += " squad_jobs=";
      for (int p = 0; p < 5; ++p)
        line += (p ? "|" : "") + TaskKeys(orders->squadAIPackage[p]);
      line += " goals=";
      for (int p = 0; p < 5; ++p)
        line += (p ? "|" : "") + TaskKeys(orders->goals[p]);
    }
    std::string names;
    for (int i = 0; i < npc->getPermajobCount(); ++i)
      names += (i ? "," : "") + npc->getPermajobName(i);
    line += " permajob_names='" + names + "'";
  } catch (...) {
    line += " [tasks failed]";
  }
  unsigned int serial = npc->getHandle().serial;
  if (logged[serial] == line)
    return;
  logged[serial] = line;
  Log(LOG_DEBUG, "ROLE_PROBE: name='" + npc->getName() + "' npc_id=" +
                     GetNpcId(npc) + " " + line);
}

static std::string ProbeParty(Character *npc) {
  std::string party = "'" + npc->getName() + "' npc_id=" + GetNpcId(npc);
  Faction *faction = npc->getFaction();
  if (faction && (uintptr_t)faction > 0x1000)
    party += " faction='" + faction->getName() + "' player=" +
             (faction->isThePlayer() ? "1" : "0");
  return party;
}

// Probe: knockouts, deaths, and prison changes with their attackers, for the
// squad deeds. A death or a capture links to its knockout by npc_id.
void LogDeathProbe(const std::string &kind, Character *npc) {
  if (!LogEnabled(LOG_DEBUG) || !npc || (uintptr_t)npc < 0x1000)
    return;
  std::string line = "kind=" + kind;
  try {
    line += " name=" + ProbeParty(npc);
    RaceData *race = npc->getRace() ? npc->getRace() : npc->myRace;
    line += " race=" +
            DataLabel(race && (uintptr_t)race > 0x1000 ? race->data : NULL);
    line += std::string(" animal=") + (npc->isAnimal() ? "1" : "0");
    TownBase *town = npc->getCurrentTownLocation();
    line += " town='" +
            (town ? ((RootObjectBase *)town)->getName() : std::string()) + "'";
  } catch (...) {
    line += " [identity failed]";
  }
  std::string attackers;
  try {
    lektor<hand> list;
    npc->getAllAttackers(list);
    for (uint32_t i = 0; i < list.size(); ++i) {
      Character *attacker = list[i].getCharacter();
      if (attacker && (uintptr_t)attacker > 0x1000)
        attackers += (attackers.empty() ? "" : "|") + ProbeParty(attacker);
    }
  } catch (...) {
    attackers += "[attackers failed]";
  }
  Log(LOG_DEBUG, "DEATH_PROBE: " + line + " attackers=[" + attackers + "]");
}

void GetCurrentSquad(std::vector<Character *> &members) {
  GameWorld *world = ppWorld ? *ppWorld : NULL;
  if (!world || !world->player)
    return;

  Platoon *platoon = world->player->getCurrentPlatoon();
  ActivePlatoon *active = platoon ? platoon->getActivePlatoon() : NULL;
  if (!active)
    return;
  lektor<Character *> &characters = world->player->playerCharacters;
  for (uint32_t i = 0; i < characters.size(); ++i) {
    if (characters[i] && characters[i]->getPlatoon() == active)
      members.push_back(characters[i]);
  }
}

std::string GetIdentityFaction(Character *npc) {
  if (!npc || (uintptr_t)npc < 0x1000)
    return "Neutral";

  Faction *faction = nullptr;
  try {
    faction = npc->getFaction() ? npc->getFaction() : npc->owner;
  } catch (...) {
  }

  std::string factionName = "Neutral";
  if (faction && (uintptr_t)faction > 0x1000) {
    factionName = faction->getName();
    if (factionName.empty() || factionName == "Unknown") {
      if (faction->data && !faction->data->name.empty())
        factionName = faction->data->name;
    }
  }

  std::string identityFaction = factionName;
  unsigned int serial = npc->getHandle().serial;

  std::string cached = "";
  EnterCriticalSection(&g_stateMutex);
  if (g_originFactions.count(serial)) {
    cached = g_originFactions[serial];
  }
  LeaveCriticalSection(&g_stateMutex);

  if (!cached.empty()) {
    return cached;
  }

  if (faction && faction->isThePlayer()) {
    GameData *characterData = npc->getGameData();
    if (characterData && ppWorld && *ppWorld && (*ppWorld)->factionMgr) {
      const Ogre::vector<GameDataReference>::type *refs =
          characterData->getReferenceListIfExists("faction");
      if (refs && !refs->empty()) {
        Faction *refFaction =
            (*ppWorld)->factionMgr->getFactionByStringID(refs->at(0).sid);
        if (refFaction && !refFaction->isThePlayer()) {
          identityFaction = refFaction->getName();
          g_originFactions[serial] = identityFaction;
          return identityFaction;
        }
      }
    }
    // Player faction names change when the squad is renamed, so use a stable label
    if (identityFaction == factionName || identityFaction == "Nameless") {
      identityFaction = "Drifters";
    }
  } else {
    if (!factionName.empty() && factionName != "Unknown" &&
        factionName != "Neutral") {
      EnterCriticalSection(&g_stateMutex);
      g_originFactions[serial] = factionName;
      LeaveCriticalSection(&g_stateMutex);
    }
  }
  return identityFaction;
}

std::string GetDetailedContext(Character *npc, const std::string &type) {
  if (!npc || (uintptr_t)npc < 0x1000 || !ppWorld || !(*ppWorld))
    return "{}";

  std::string json = "{";
  json += "\"type\": \"" + type + "\",";
  if (ppWorld && *ppWorld) {
    TimeOfDay tod = (*ppWorld)->getTimeStamp_inGameHours();
    int day = (int)tod.getTotalDays();
    int hour = (int)fmod(tod.getTotalHours(), 24.0);
    int minute = (int)fmod(tod.getTotalMinutes(), 60.0);

    json += "\"day\": " + ToString(day) + ",";
    json += "\"hour\": " + ToString(hour) + ",";
    json += "\"minute\": " + ToString(minute) + ",";
    json +=
        "\"gamespeed\": " + ToString((*ppWorld)->getFrameSpeedMultiplier()) +
        ",";
    json += "\"is_paused\": " +
            std::string((*ppWorld)->isPaused() ? "true" : "false") + ",";

    DWORD now = GetTickCount();
    DWORD elapsed = now - g_lastAmbientTick;
    json += "\"radiant_timer_ms\": " + ToString((int)elapsed) + ",";
    json += "\"radiant_interval_ms\": " +
            ToString((int)(g_ambientIntervalSeconds * 1000)) + ",";

    DWORD speech_elapsed = now - g_lastDialogueTick;
    json += "\"speech_delay_ms\": " + ToString((int)speech_elapsed) + ",";
    json += "\"speech_interval_ms\": " +
            ToString((int)(g_dialogueSpeedSeconds * 1000)) + ",";
  }

  std::string charState = "normal";
  bool isDead = false;
  bool isUnconcious = false;
  try {
    isDead = npc->isDead();
    if (isDead) {
      charState = "dead";
    } else {
      isUnconcious = npc->isUnconcious();
      if (isUnconcious) {
        charState = "unconscious";
      } else if (npc->inSomething == IN_PRISON) {
        charState = "imprisoned";
      } else {
        try {
          SlaveStateEnum slaveState = npc->isSlave();
          bool chained = npc->isChainedMode();
          if (slaveState != 0) { // 0 == not a slave
            // Slave status but unchained means escaped
            charState = chained ? "enslaved" : "escaped-slave";
          }
        } catch (...) {
        }
      }
    }
  } catch (...) {
  }
  json += "\"character_state\": \"" + charState + "\",";
  json += "\"is_incapacitated\": " +
          std::string((isDead || isUnconcious) ? "true" : "false") + ",";

  std::string name = "Unknown";
  try {
    name = npc->getName();
    if (name.empty() || name == "Unknown Entity" || name == "Unknown") {
      if (!npc->displayName.empty())
        name = npc->displayName;
      else if (npc->data && !npc->data->name.empty())
        name = npc->data->name;
    }
  } catch (...) {
  }
  json += "\"name\": \"" + EscapeJSON(name) + "\",";
  json += "\"template\": \"" +
          EscapeJSON(npc->data ? npc->data->name : std::string()) + "\",";
  json += "\"template_id\": \"" +
          EscapeJSON(npc->data ? npc->data->stringID : std::string()) + "\",";
  json += "\"unique\": " + std::string(npc->isUnique() ? "true" : "false") +
          ",";

  InstanceID *iid = npc->getInstanceID();
  if (iid && !iid->uid.empty()) {
    json += "\"id\": \"" + EscapeJSON(iid->uid) + "\",";
  } else {
    json += "\"id\": \"hand_" + ToString(npc->getHandle().serial) + "\",";
  }

  RaceData *race = nullptr;
  try {
    race = npc->getRace() ? npc->getRace() : npc->myRace;
  } catch (...) {
  }

  std::string raceName = "Unknown";
  if (race && (uintptr_t)race > 0x1000) {
    if (race->data && !race->data->name.empty())
      raceName = race->data->name;
    else if (race->data && !race->data->stringID.empty())
      raceName = race->data->stringID;
  }
  json += "\"race\": \"" + EscapeJSON(raceName) + "\",";

  std::string gender = "male";
  try {
    gender = npc->isFemale() ? "female" : "male";
  } catch (...) {
  }
  if (npc->sex == "female" || npc->sex == "male")
    gender = npc->sex;
  json += "\"gender\": \"" + gender + "\",";

  Faction *faction = nullptr;
  try {
    faction = npc->getFaction() ? npc->getFaction() : npc->owner;
  } catch (...) {
  }

  std::string factionName = "Neutral";
  std::string factionID = "Neutral";
  if (faction && (uintptr_t)faction > 0x1000) {
    std::string fn = faction->getName();
    if (!fn.empty() && fn != "Unknown")
      factionName = fn;
    else if (faction->data && !faction->data->name.empty())
      factionName = faction->data->name;

    if (faction->data && !faction->data->stringID.empty())
      factionID = faction->data->stringID;
    else
      factionID = factionName;
  }
  json += "\"faction\": \"" + EscapeJSON(factionName) + "\",";
  json += "\"factionID\": \"" + EscapeJSON(factionID) + "\",";

  std::string job = "None";
  try {
    int jobCount = npc->getPermajobCount();
    if (jobCount > 0) {
      job = "";
      for (int i = 0; i < jobCount; ++i) {
        std::string jName = npc->getPermajobName(i);
        if (!jName.empty()) {
          if (!job.empty())
            job += ", ";
          job += jName;
        }
      }
      if (job.empty())
        job = "None";
    }
  } catch (...) {
  }
  json += "\"job\": \"" + EscapeJSON(job) + "\",";

  std::string identityFaction = GetIdentityFaction(npc);
  json += "\"origin_faction\": \"" + EscapeJSON(identityFaction) + "\",";

  json += "\"npc_id\": \"" + EscapeJSON(GetNpcId(npc)) + "\",";

  if (ppWorld && *ppWorld && (*ppWorld)->player &&
      (*ppWorld)->player->getFaction() && faction) {
    Faction *playerFaction = (*ppWorld)->player->getFaction();
    if (playerFaction->relations) {
      float rel = playerFaction->relations->getFactionRelation(faction);
      json += "\"relation\": " + ToString((int)rel) + ",";
    }
  }

  json += RoleJson(npc) + ",";

  bool isLeader = false;
  if (faction && (uintptr_t)faction > 0x1000 && faction->data &&
      (uintptr_t)faction->data > 0x1000) {
    hand lHand;
    if (faction->data->getHandle(lHand, "leader") && lHand.isValid()) {
      if (lHand == npc->getHandle())
        isLeader = true;
    }
  }
  json += "\"is_leader\": " + std::string(isLeader ? "true" : "false") + ",";

  bool indoors = false;
  std::string buildingName = "Unknown";
  bool inAShop = false;
  const hand &buildingHandle = npc->isIndoors();
  if (buildingHandle.isValid()) {
    indoors = true;
    Building *b = buildingHandle.getBuilding();
    if (b) {
      buildingName = b->getName();
      if (b->isAShop() || b->designation == BD_SHOP ||
          b->designation == BD_BAR) {
        inAShop = true;
      }
    }
  }

  json += "\"indoors\": " + std::string(indoors ? "true" : "false") + ",";
  json += "\"in_shop\": " + std::string(inAShop ? "true" : "false") + ",";
  json += "\"building_name\": \"" + EscapeJSON(buildingName) + "\",";

  if (ppWorld && *ppWorld) {
    lektor<RootObject *> results;
    (*ppWorld)->getCharactersWithinSphere(
        results, npc->getPosition(), g_visionRange, 0.0f, 0.0f, 16, 0, npc);
    json += "\"nearby\": [";
    for (uint32_t i = 0; i < results.size(); ++i) {
      Character *other = (Character *)results.stuff[i];
      if (other && (uintptr_t)other > 0x1000) {
        if ((*ppWorld)->player &&
            (*ppWorld)->player->playerCharacters.size() > 0) {
          if (other == (*ppWorld)->player->playerCharacters[0])
            continue;
        }

        if (json.back() == '}')
          json += ",";

        std::string o_name = other->getName();

        RaceData *o_race = other->getRace() ? other->getRace() : other->myRace;
        std::string o_rn = "Unknown";
        if (o_race && (uintptr_t)o_race > 0x1000) {
          if (o_race->data && !o_race->data->name.empty())
            o_rn = o_race->data->name;
          else if (o_race->data && !o_race->data->stringID.empty())
            o_rn = o_race->data->stringID;
        }

        Faction *o_fact =
            other->getFaction() ? other->getFaction() : other->owner;
        std::string o_fn = "Neutral";
        if (o_fact && (uintptr_t)o_fact > 0x1000) {
          std::string fn = o_fact->getName();
          if (!fn.empty() && fn != "Unknown")
            o_fn = fn;
          else if (o_fact->data && !o_fact->data->name.empty())
            o_fn = o_fact->data->name;
          else if (o_fact->data && !o_fact->data->stringID.empty())
            o_fn = o_fact->data->stringID;
        }

        std::string o_gender = other->isFemale() ? "female" : "male";
        float dist = npc->getPosition().distance(other->getPosition());

        unsigned int o_serial = other->getHandle().serial;

        EnterCriticalSection(&g_stateMutex);
        if (!g_originFactions.count(o_serial) && o_fact &&
            !o_fact->isThePlayer())
          g_originFactions[o_serial] = o_fn;
        LeaveCriticalSection(&g_stateMutex);

        std::string o_health = GetHealthStatus(other);
        std::string o_equip = GetVisibleEquipment(other);

        json += "{\"name\":\"" + EscapeJSON(o_name) + "\",";
        json += "\"race\":\"" + EscapeJSON(o_rn) + "\",";
        json += "\"faction\":\"" + EscapeJSON(o_fn) + "\",";
        json += "\"gender\":\"" + EscapeJSON(o_gender) + "\",";
        json += "\"health\":\"" + EscapeJSON(o_health) + "\",";
        json += "\"equipment\":\"" + EscapeJSON(o_equip) + "\",";
        json += "\"npc_id\":\"" + EscapeJSON(GetNpcId(other)) + "\",";
        json += "\"dist\":" + ToString(dist) + "}";
      }
    }
    json += "],";
  }

  int money = npc->getMoney();
  if (money <= 0 && npc->getOwnerships())
    money = npc->getOwnerships()->getMoney();
  json += "\"money\": " + ToString(money) + ",";

  if (type == "player" && ppWorld && *ppWorld && (*ppWorld)->player) {
    json += "\"squad\": [";
    for (uint32_t i = 0; i < (*ppWorld)->player->playerCharacters.size(); ++i) {
      if (i > 0)
        json += ",";
      json += "\"" +
              EscapeJSON((*ppWorld)->player->playerCharacters[i]->getName()) +
              "\"";
    }
    json += "],";
  }

  CharStats *stats = npc->getStats();
  if (stats) {
    json += "\"stats\": {";
    json += "\"strength\": " + ToString((int)stats->_strength) + ",";
    json += "\"dexterity\": " + ToString((int)stats->_dexterity) + ",";
    json += "\"toughness\": " + ToString((int)stats->_toughness) + ",";
    json += "\"perception\": " + ToString((int)stats->perception) + ",";
    json += "\"melee_attack\": " +
            ToString((int)stats->getStat(STAT_MELEE_ATTACK, false)) + ",";
    json += "\"melee_defence\": " +
            ToString((int)stats->getStat(STAT_MELEE_DEFENCE, false)) + ",";
    json += "\"athletics\": " +
            ToString((int)stats->getStat(STAT_ATHLETICS, false));
    json += "},";
  }

  MedicalSystem *med = npc->getMedical();
  if (med) {
    json += "\"medical\": {";
    json += "\"blood\": " + ToString((int)med->blood) + ",";
    json += "\"max_blood\": " + ToString((int)med->getMaxBlood()) + ",";
    json += "\"blood_rate\": " + ToString(med->currentBleedRate) + ",";
    // hunger is a deficit (0 full, 300 starving); fed is food still being digested
    float hungerVal = (300.0f - med->hunger) + med->fed;
    if (hungerVal < 0)
      hungerVal = 0;
    json += "\"hunger\": " + ToString((int)hungerVal) + ",";
    json += "\"is_unconscious\": " +
            std::string(med->unconcious ? "true" : "false") + ",";
    json += "\"limbs\": {";
    auto addPart = [&](const std::string &name,
                       MedicalSystem::HealthPartStatus *p) {
      json += "\"" + name + "\": " + ToString(p ? (int)p->flesh : 100) + ",";
      json += "\"" + name +
              "_max\": " + ToString(p ? (int)p->maxHealth() : 100) + ",";
    };
    addPart("head", med->getPart(0));
    addPart("stomach", med->getPart(1));
    addPart("left_arm", med->leftArm);
    addPart("right_arm", med->rightArm);
    addPart("left_leg", med->leftLeg);
    addPart("right_leg", med->rightLeg);
    if (json.back() == ',')
      json.pop_back();
    json += "}";
    json += "},";
  }

  json += "\"environment\": {";
  json += "\"indoors\": " +
          std::string(npc->isIndoors().isValid() ? "true" : "false") + ",";
  json += "\"in_town\": " +
          std::string(npc->amInsideTownWalls() ? "true" : "false") + ",";
  TownBase *town = npc->getCurrentTownLocation();
  if (town)
    json += "\"town_name\": \"" +
            EscapeJSON(((RootObjectBase *)town)->getName()) + "\",";
  std::string zone = ZoneName();
  if (!zone.empty())
    json += "\"zone_name\": \"" + EscapeJSON(zone) + "\",";
  json += "\"weather\": " + ToString((int)npc->getCurrentWeatherAffectStatus());
  json += "},";

  json += "\"inventory\": ";
  if (GetCurrentThreadId() == g_mainThreadId) {
    json += "[";
    std::vector<Item *> allItems;
    GetAllCharacterItems(npc, allItems);
    for (uint32_t i = 0; i < allItems.size(); ++i) {
      if (allItems[i]) {
        if (i > 0)
          json += ",";
        
        int price = 0;
        try {
            price = allItems[i]->getValueSingle(false);
        } catch (...) {
            price = 0;
        }

        json +=
            "{\"name\": \"" + EscapeJSON(allItems[i]->getName()) +
            "\", \"count\": " + ToString((int)allItems[i]->quantity) +
            ", \"price\": " + ToString(price) +
            ", \"equipped\": " + (allItems[i]->isEquipped ? "true" : "false") +
            ", \"slot\": \"" + SlotToString(allItems[i]->slotType) + "\"}";
      }
    }
    json += "],";
  } else {
    json += "[],";
  }

  if (ppWorld && *ppWorld && (*ppWorld)->player &&
      (*ppWorld)->player->playerCharacters.size() > 0) {
    Character *player = (*ppWorld)->player->playerCharacters[0];
    json += "\"memories\": { \"short_term\": [";
    bool first = true;
    for (int i = 1; i < 8; ++i) {
      if (npc->getCharacterMemoryTag(player,
                                     (CharacterPerceptionTags_ShortTerm)i)) {
        if (!first)
          json += ",";
        json += ToString(i);
        first = false;
      }
    }
    json += "], \"long_term\": [";
    first = true;
    for (int i = 1; i < 17; ++i) {
      if (npc->getCharacterMemoryTag(player,
                                     (CharacterPerceptionTags_LongTerm)i)) {
        if (!first)
          json += ",";
        json += ToString(i);
        first = false;
      }
    }
    json += "] }";
  } else {
    json += "\"memories\": {}";
  }

  json += "}";
  return json;
}

// Empties the buffer, because the server records each event that it gets
std::string TakeGameEvents() {
  std::deque<GameEvent> events;
  EnterCriticalSection(&g_eventMutex);
  events.swap(g_gameEvents);
  LeaveCriticalSection(&g_eventMutex);

  std::string json = "[";
  for (size_t i = 0; i < events.size(); ++i) {
    const GameEvent &e = events[i];
    if (i > 0)
      json += ",";
    json += "{\"type\": \"" + EscapeJSON(e.type) + "\",";
    json += "\"actor\": \"" + EscapeJSON(e.actor) + "\",";
    json += "\"actor_faction\": \"" + EscapeJSON(e.actorFaction) + "\",";
    json += "\"target\": \"" + EscapeJSON(e.target) + "\",";
    json += "\"target_faction\": \"" + EscapeJSON(e.targetFaction) + "\",";
    json += "\"msg\": \"" + EscapeJSON(e.message) + "\",";
    json += "\"day\": " + ToString(e.day) + ",";
    json += "\"hour\": " + ToString(e.hour) + ",";
    json += "\"minute\": " + ToString(e.minute) + ",";
    json += "\"town\": \"" + EscapeJSON(e.town) + "\"}";
  }
  return json + "]";
}

std::string GameReport() {
  std::string player = "{}";
  GameWorld *world = ppWorld ? *ppWorld : nullptr;
  if (world && world->player && world->player->playerCharacters.size() > 0)
    player = GetDetailedContext(world->player->playerCharacters[0], "player");
  return "{\"player\": " + player + ", \"events\": " + TakeGameEvents() +
         "}";
}
