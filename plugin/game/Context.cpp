#include "Context.h"
#include "GameActions.h"
#include "../core/Globals.h"
#include "../core/Utils.h"
#include <kenshi/Building/Building.h>
#include <kenshi/CharStats.h>
#include <kenshi/Character.h>
#include <kenshi/Faction.h>
#include <kenshi/FactionRelations.h>
#include <kenshi/GameData.h>
#include <kenshi/GameWorld.h>
#include <kenshi/Inventory.h>
#include <kenshi/Item.h>
#include <kenshi/Kenshi.h>
#include <kenshi/MedicalSystem.h>
#include <kenshi/Platoon.h>
#include <kenshi/PlayerInterface.h>
#include <kenshi/AI/AITaskSystem.h>
#include <kenshi/AI/Blackboard.h>
#include <kenshi/RaceData.h>
#include <kenshi/SharedKing.h>
#include <kenshi/Tasker.h>
#include <kenshi/Town.h>
// Weather.h redefines WeatherRegion from PhysicsCollection.h; rename its copy
#define WeatherRegion WeatherRegion_WeatherH
#include <kenshi/Weather.h>
#undef WeatherRegion
#include <kenshi/WorldEventStateQuery.h>
#include <kenshi/util/hand.h>
#include <algorithm>
#include <cctype>
#include <map>
#include <set>
#include <vector>

static std::string SlotToString(AttachSlot slot) {
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

std::string GetHealthStatus(Character *npc) {
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

// A bandaged wound needs no kit, because the game counts the bandage as healed
// when it picks a patient for first aid
void TreatmentNeeds(Character *patient, bool &firstAid, bool &repair) {
  firstAid = repair = false;
  MedicalSystem *med = patient->getMedical();
  if (!med || (uintptr_t)med < 0x1000)
    return;
  RaceData *race = patient->getRace() ? patient->getRace() : patient->myRace;
  bool robotBody = race && race->robot;
  for (uint32_t i = 0; i < med->anatomy.size(); ++i) {
    MedicalSystem::HealthPartStatus *part = med->anatomy[i];
    if (!part || part->flesh + part->bandaging >= part->maxHealth())
      continue;
    if (robotBody || part->robotLimb)
      repair = true;
    else
      firstAid = true;
  }
}

std::string GetVisibleEquipment(Character *npc) {
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

// The whole handle, because characters of other squads can share a serial and
// a template. A squad change gives a new handle, so RekeyCharacter follows it
static std::string NpcIdOf(Character *npc, const hand &h) {
  if (npc->isUnique() && npc->data)
    return "u:" + npc->data->stringID;
  return "h:" + ToString(h.index) + "-" + ToString(h.serial) + "-" +
         ToString(h.container) + "-" + ToString(h.containerSerial);
}

std::string GetNpcId(Character *npc) { return NpcIdOf(npc, npc->getHandle()); }

struct KeyedCharacterEntry {
  Character *character;
  hand handle;
};

// Without a lock, because only the game thread keys or looks up a character
static std::vector<KeyedCharacterEntry> g_keyed;
// The faction of a character before the player recruited it, by npc_id. The
// game thread alone uses it, as g_keyed
static std::map<std::string, std::string> g_originFactions;

// A squad change gives a character a new handle, and RekeyCharacter gives the
// key that handle, so a key outlives the change
unsigned int HandleKey(Character *npc) {
  hand h = npc->getHandle();
  for (size_t i = 0; i < g_keyed.size(); ++i)
    if (g_keyed[i].character == npc && g_keyed[i].handle.serial == h.serial) {
      g_keyed[i].handle = h;
      return (unsigned int)i + 1;
    }
  KeyedCharacterEntry entry;
  entry.character = npc;
  entry.handle = h;
  g_keyed.push_back(entry);
  return (unsigned int)g_keyed.size();
}

Character *KeyedCharacter(unsigned int key) {
  if (key == 0 || key > g_keyed.size())
    return nullptr;
  KeyedCharacterEntry &entry = g_keyed[key - 1];
  Character *c = entry.handle.getCharacter();
  if (c || !ppWorld || !*ppWorld)
    return c;
  // Compared as a pointer before any read, because the object can be gone
  const auto &chars = (*ppWorld)->getCharacterUpdateList();
  for (auto it = chars.begin(); it != chars.end(); ++it) {
    if (*it != entry.character)
      continue;
    hand h = entry.character->getHandle();
    if (h.serial != entry.handle.serial)
      return nullptr;
    entry.handle = h;
    return entry.character;
  }
  return nullptr;
}

// A character that loads gets its first handle, which replaces no npc_id
void RekeyCharacter(Character *npc, const hand &before) {
  if (!npc || before.isNull())
    return;
  std::string oldId = NpcIdOf(npc, before);
  std::string newId = GetNpcId(npc);
  if (oldId == newId)
    return;
  for (size_t i = 0; i < g_keyed.size(); ++i)
    if (g_keyed[i].character == npc &&
        g_keyed[i].handle.serial == before.serial)
      g_keyed[i].handle = npc->getHandle();
  std::map<std::string, std::string>::iterator origin =
      g_originFactions.find(oldId);
  if (origin != g_originFactions.end()) {
    g_originFactions[newId] = origin->second;
    g_originFactions.erase(origin);
  }
  QueueGameEvent("rekey", "\"old\": \"" + EscapeJSON(oldId) +
                              "\", \"new\": \"" + EscapeJSON(newId) + "\"");
  Log(LOG_INFO,
      "REKEY: '" + npc->getName() + "' " + oldId + " is now " + newId);
}

static std::string RaceName(Character *npc) {
  RaceData *race = npc->getRace() ? npc->getRace() : npc->myRace;
  if (race && (uintptr_t)race > 0x1000 && race->data) {
    if (!race->data->name.empty())
      return race->data->name;
    if (!race->data->stringID.empty())
      return race->data->stringID;
  }
  return "Unknown";
}

Faction *CharacterFaction(Character *npc) {
  Faction *faction = npc->getFaction() ? npc->getFaction() : npc->owner;
  return faction && (uintptr_t)faction > 0x1000 ? faction : nullptr;
}

// Modded factions often have no name, so the string ID stands in
std::string FactionName(Faction *faction) {
  if (!faction)
    return "Neutral";
  std::string name = faction->getName();
  if (!name.empty() && name != "Unknown")
    return name;
  if (faction->data && !faction->data->name.empty())
    return faction->data->name;
  if (faction->data && !faction->data->stringID.empty())
    return faction->data->stringID;
  return "Neutral";
}

static std::string GenderOf(Character *npc) {
  if (npc->sex == "female" || npc->sex == "male")
    return npc->sex;
  return npc->isFemale() ? "female" : "male";
}

static std::string FactionID(Faction *faction) {
  if (!faction)
    return "Neutral";
  if (faction->data && !faction->data->stringID.empty())
    return faction->data->stringID;
  return FactionName(faction);
}

// A captive keeps its own faction, so the cage or the slave owner names the
// captor
static Faction *CaptorFaction(Character *npc) {
  hand captor;
  if (npc->inSomething == IN_PRISON)
    captor = npc->inWhat;
  else if (npc->isSlave() != NOT_SLAVE && npc->isChainedMode())
    captor = npc->getMySlaveOwner();
  else
    return nullptr;
  RootObjectBase *object = captor.getRootObjectBase();
  if (!object || (uintptr_t)object < 0x1000)
    return nullptr;
  Faction *faction = object->getFaction() ? object->getFaction() : object->owner;
  return faction && (uintptr_t)faction > 0x1000 ? faction : nullptr;
}

std::string EventParty(Character *npc) {
  Faction *faction = CharacterFaction(npc);
  return "{\"id\": \"" + EscapeJSON(GetNpcId(npc)) + "\", \"template_id\": \"" +
         EscapeJSON(npc->data ? npc->data->stringID : std::string()) +
         "\", \"name\": \"" + EscapeJSON(npc->getName()) +
         "\", \"faction\": \"" + EscapeJSON(FactionName(faction)) +
         "\", \"player\": " +
         (faction && faction->isThePlayer() ? "true" : "false") + "}";
}

// KenshiLib does not map slot 0x10 of the zone object, so only a pointer that
// is a zone record is followed.
static std::string ZoneOf(AreaBiomeGroup *biome) {
  static std::set<GameData *> zones;
  GameWorld *world = ppWorld ? *ppWorld : NULL;
  if (!world || !biome)
    return "";

  if (zones.empty()) {
    lektor<GameData *> list;
    world->gamedata.getDataOfType(list, BIOME_GROUP);
    for (uint32_t i = 0; i < list.size(); ++i) {
      if (list[i])
        zones.insert(list[i]);
    }
  }
  GameData *zone = *(GameData **)((char *)biome + 0x10);
  return zones.count(zone) ? zone->name : "";
}

// The zone around the camera, for example Vain: the game gives no zone for each
// character, and a chat happens near the camera
static std::string ZoneName() {
  WeatherSystem *weather = WeatherSystem::getInstance();
  return weather ? ZoneOf(weather->ActiveRegion) : "";
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
    ROLE_TASK(FIND_CAGE_AND_PUT_DEADGUY_IN),
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

static std::string RoleJson(Character *npc) {
  bool trader = false;
  bool follower = false;
  std::string jobs;
  // isATrader covers the whole trader squad, guards too; the trader leads it
  ActivePlatoon *active = npc->getPlatoon();
  trader = npc->isATrader() && active && (uintptr_t)active > 0x1000 &&
           active->squadleader == npc;
  // A hire or escort contract makes an NPC follow the player without a recruit
  Blackboard *board = BoardOf(npc);
  follower = board && board->hasContractJob();
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
  return std::string("\"is_trader\":") + (trader ? "true" : "false") +
         ",\"temporary_follower\":" + (follower ? "true" : "false") +
         ",\"squad_jobs\":[" + jobs + "]";
}

Building *BuildingOf(Character *npc) {
  const hand &building = npc->isIndoors();
  return building.isValid() ? building.getBuilding() : nullptr;
}

static std::string BuildingName(Character *npc) {
  Building *building = BuildingOf(npc);
  return building ? building->getName() : "Unknown";
}

static std::string ProfileJson(Character *npc) {
  std::string json = "\"health\":\"" + EscapeJSON(GetHealthStatus(npc)) +
                     "\",\"origin_faction\":\"" +
                     EscapeJSON(GetIdentityFaction(npc)) +
                     "\",\"building_name\":\"" + EscapeJSON(BuildingName(npc)) +
                     "\",\"environment\":{";
  TownBase *town = npc->getCurrentTownLocation();
  if (town)
    json += "\"town_name\":\"" +
            EscapeJSON(((RootObjectBase *)town)->getName()) + "\",";
  return json + "\"zone_name\":\"" + EscapeJSON(ZoneName()) + "\"}";
}

// The fields that the nearby entry of a chat and a radiant entry share, so
// each caller adds its own
std::string PartyFields(Character *c) {
  Faction *faction = CharacterFaction(c);
  return "\"name\": \"" + EscapeJSON(c->getName()) +
         "\", \"id\": " + ToString(HandleKey(c)) + ", \"npc_id\": \"" +
         EscapeJSON(GetNpcId(c)) + "\", \"race\": \"" +
         EscapeJSON(RaceName(c)) + "\", \"animal\": " +
         JsonBool(c->isAnimal() != nullptr) +
         ", \"gender\": \"" + GenderOf(c) + "\", \"template\": \"" +
         EscapeJSON(c->data ? c->data->name : std::string()) +
         "\", \"template_id\": \"" +
         EscapeJSON(c->data ? c->data->stringID : std::string()) +
         "\", \"unique\": " + JsonBool(c->isUnique()) +
         ", \"in_player_faction\": " +
         JsonBool(faction && faction->isThePlayer()) + ", " + RoleJson(c) +
         ", " + ProfileJson(c);
}

void SectionItems(Inventory *inv, std::vector<Item *> &out) {
  if (!inv || (uintptr_t)inv < 0x1000)
    return;
  for (auto it = inv->sections.begin(); it != inv->sections.end(); ++it) {
    if (!it->second)
      continue;
    const Ogre::vector<InventorySection::SectionItem>::type &items =
        it->second->getItems();
    for (uint32_t i = 0; i < items.size(); ++i)
      if (items[i].item)
        out.push_back(items[i].item);
  }
}

// The levels of the armour grades on the wiki, which crossbows and robotic limbs
// share; the game showed 40 as Standard and 60 as High on armour
const GearGradeLevel GEAR_GRADES[6] = {
    {"Prototype", 5}, {"Shoddy", 20},     {"Standard", 40},
    {"High", 60},     {"Specialist", 80}, {"Masterwork", 95}};

static const char *GradeAtLevel(int level) {
  const char *grade = GEAR_GRADES[0].name;
  for (size_t g = 1; g < sizeof(GEAR_GRADES) / sizeof(GEAR_GRADES[0]); ++g)
    if (level >= GEAR_GRADES[g].level)
      grade = GEAR_GRADES[g].name;
  return grade;
}

// Two items with one name can differ in grade and price, so the name of a
// graded item holds its grade, and a deal names the right one
std::string ItemLabel(Item *item) {
  std::string name = item->getName();
  if (item->objectType == WEAPON && item->materialData) {
    std::string grade = item->materialData->name;
    // The game data numbers the weapon grades, as in "09 - Refitted Blade"
    size_t dash = grade.find(" - ");
    if (dash != std::string::npos && dash < 4)
      grade = grade.substr(dash + 3);
    std::string maker =
        item->manufacturerData ? item->manufacturerData->name : std::string();
    if (maker.empty() || maker == "Unknown")
      return name + " (" + grade + ")";
    return name + " (" + maker + ", " + grade + ")";
  }
  if (item->objectType == ARMOUR || item->objectType == CROSSBOW ||
      item->objectType == LIMB_REPLACEMENT)
    return name + " (" + GradeAtLevel(item->getLevel()) + ")";
  return name;
}

void GetShopItems(Character *npc, std::vector<Item *> &out) {
  Building *building = BuildingOf(npc);
  if (!building)
    return;
  lektor<Building *> furniture;
  building->findAllFurnitureWithFunction(furniture, BF_ANY);
  for (uint32_t i = 0; i < furniture.size(); ++i)
    if (furniture[i] && (uintptr_t)furniture[i] > 0x1000)
      SectionItems(furniture[i]->getInventory(), out);
}

// Only carried sections count, so a deal never relies on the receiver wearing
// what it gets; a stack that fits only split over sections counts as no room
bool InventoryHasRoom(Inventory *inv, GameData *data, int count) {
  if (!inv)
    return false;
  lektor<InventorySection *> &sections = inv->sectionsInSearchOrder;
  for (uint32_t s = 0; s < sections.size(); ++s)
    if (sections[s] && !sections[s]->isAnEquippedItemSection &&
        sections[s]->hasRoomForItem(data, count))
      return true;
  return false;
}

bool HasRoomFor(Character *c, GameData *data, int count) {
  ContainerItem *backpack = c->hasABackpackOn();
  return InventoryHasRoom(c->getInventory(), data, count) ||
         (backpack && InventoryHasRoom(backpack->inventory, data, count));
}

// KIND_WORDS in server/chat/offers.py keys on these names
static const char *ItemKind(Item *item) {
  switch (item->objectType) {
  case WEAPON:
    return "weapon";
  case CROSSBOW:
    return "crossbow";
  case ARMOUR:
    return "armour";
  case BLUEPRINT:
    return "blueprint";
  case LIMB_REPLACEMENT:
    return "limb";
  default:
    break;
  }
  switch (item->itemFunction) {
  case ITEM_FOOD:
  case ITEM_FOOD_RESTRICTED:
    return "food";
  case ITEM_NARCOTIC:
    return "drug";
  case ITEM_FIRSTAID:
  case ITEM_MEDRIGGING:
    return "medical";
  case ITEM_ROBOTREPAIR:
    return "repair";
  case ITEM_BOOK:
    return "book";
  case ITEM_AMMO:
    return "ammo";
  case ITEM_CONTAINER:
    return "backpack";
  case ITEM_TOOL:
    return "tool";
  case ITEM_BLUEPRINT:
    return "blueprint";
  default:
    return "goods";
  }
}

std::string ItemsJson(const std::vector<Item *> &items) {
  std::string json = "[";
  for (uint32_t i = 0; i < items.size(); ++i) {
    // NPCs carry loose cats as items apart from their purse, and the model
    // took them for the purse
    if (!items[i] || items[i]->itemFunction == ITEM_MONEY)
      continue;
    int price = items[i]->getValueSingle(false);
    if (json.size() > 1)
      json += ",";
    json += "{\"name\": \"" + EscapeJSON(ItemLabel(items[i])) +
            "\", \"count\": " + ToString((int)items[i]->quantity) +
            ", \"price\": " + ToString(price) + ", \"equipped\": " +
            (items[i]->isEquipped ? "true" : "false") + ", \"slot\": \"" +
            SlotToString(items[i]->slotType) + "\", \"kind\": \"" +
            ItemKind(items[i]) + "\"}";
  }
  return json + "]";
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

static bool CanTalk(Character *c) {
  if (!c || (uintptr_t)c < 0x1000)
    return false;
  return !c->isDead() && !c->isUnconcious() && !c->isAnimal();
}

// The center is a character that the player watches, so the speech bubbles show
// on the screen
void GetRadiantParticipants(Character *selected,
                            std::vector<Character *> &participants) {
  GameWorld *world = ppWorld ? *ppWorld : NULL;
  if (!world || !world->player)
    return;
  lektor<Character *> &characters = world->player->playerCharacters;
  Character *center = nullptr;
  for (uint32_t i = 0; i < characters.size() && !center; ++i) {
    if (characters[i] == selected && CanTalk(selected))
      center = selected;
  }
  if (!center) {
    std::vector<Character *> squad;
    GetCurrentSquad(squad);
    for (size_t i = 0; i < squad.size() && !center; ++i) {
      if (CanTalk(squad[i]))
        center = squad[i];
    }
  }
  if (!center)
    return;

  std::vector<std::pair<float, Character *> > nearby;
  for (uint32_t i = 0; i < characters.size(); ++i) {
    Character *c = characters[i];
    if (c == center || !CanTalk(c))
      continue;
    float dist = center->getPosition().distance(c->getPosition());
    if (dist < g_proximityRadius)
      nearby.push_back(std::make_pair(dist, c));
  }
  std::sort(nearby.begin(), nearby.end());
  participants.push_back(center);
  for (size_t i = 0; i < nearby.size() && participants.size() < 5; ++i)
    participants.push_back(nearby[i].second);
}

// Every candidate, because the server picks the squad: only its job table
// tells a bar visit from the side task of a guard
void GetRadiantNpcs(Character *center, std::vector<Character *> &npcs) {
  GameWorld *world = ppWorld ? *ppWorld : NULL;
  if (!world || !center)
    return;
  std::vector<std::pair<float, Character *> > nearby;
  const auto &chars = world->getCharacterUpdateList();
  for (auto it = chars.begin(); it != chars.end(); ++it) {
    Character *c = *it;
    if (!CanTalk(c) || !c->getPlatoon())
      continue;
    Faction *faction = c->getFaction() ? c->getFaction() : c->owner;
    if (faction && faction->isThePlayer())
      continue;
    float dist = center->getPosition().distance(c->getPosition());
    if (dist < g_yellRadius)
      nearby.push_back(std::make_pair(dist, c));
  }
  std::sort(nearby.begin(), nearby.end());
  for (size_t i = 0; i < nearby.size(); ++i)
    npcs.push_back(nearby[i].second);
}

// The faction that the template of a recruit names, outside the player faction
static Faction *TemplateFaction(Character *npc) {
  GameWorld *world = ppWorld ? *ppWorld : nullptr;
  GameData *data = npc->getGameData();
  if (!world || !world->factionMgr || !data)
    return nullptr;
  const Ogre::vector<GameDataReference>::type *refs =
      data->getReferenceListIfExists("faction");
  Faction *faction = refs && !refs->empty()
                         ? world->factionMgr->getFactionByStringID(refs->at(0).sid)
                         : nullptr;
  return faction && !faction->isThePlayer() ? faction : nullptr;
}

// Each sighting outside the player faction keeps the faction, because the game
// forgets it at a recruit
std::string GetIdentityFaction(Character *npc) {
  if (!npc || (uintptr_t)npc < 0x1000)
    return "Neutral";
  std::string npcId = GetNpcId(npc);
  std::map<std::string, std::string>::iterator cached =
      g_originFactions.find(npcId);
  if (cached != g_originFactions.end() && !cached->second.empty())
    return cached->second;
  Faction *faction = CharacterFaction(npc);
  if (faction && faction->isThePlayer()) {
    Faction *origin = TemplateFaction(npc);
    // Player faction names change when the squad is renamed, so use a stable label
    if (!origin)
      return "Drifters";
    return g_originFactions[npcId] = origin->getName();
  }
  std::string name = FactionName(faction);
  if (name != "Neutral")
    g_originFactions[npcId] = name;
  return name;
}

static std::string StateFields(Character *npc) {
  std::string state = "normal";
  Faction *captor = nullptr;
  if (npc->isDead()) {
    state = "dead";
  } else if (npc->isUnconcious()) {
    state = "unconscious";
  } else if (npc->inSomething == IN_PRISON) {
    state = "imprisoned";
    captor = CaptorFaction(npc);
  } else if (npc->isSlave() != NOT_SLAVE) {
    state = npc->isChainedMode() ? "enslaved" : "escaped-slave";
    captor = CaptorFaction(npc);
  }
  bool needsFirstAid, needsRepair;
  TreatmentNeeds(npc, needsFirstAid, needsRepair);
  Inventory *inv = npc->getInventory();
  return "\"character_state\": \"" + state + "\", \"captor\": \"" +
         EscapeJSON(captor ? FactionID(captor) : std::string()) +
         "\", \"health\": \"" + GetHealthStatus(npc) +
         "\", \"slave\": " + JsonBool(npc->isSlave() != 0) +
         ", \"bounty\": " + ToString(npc->crimes.getTotalBounty()) +
         ", \"has_first_aid\": " +
         JsonBool(inv && inv->hasItemFunction(ITEM_FIRSTAID)) +
         ", \"has_repair_kit\": " +
         JsonBool(inv && inv->hasItemFunction(ITEM_ROBOTREPAIR)) +
         ", \"needs_first_aid\": " + JsonBool(needsFirstAid) +
         ", \"needs_repair\": " + JsonBool(needsRepair) +
         ", \"in_combat\": " +
         JsonBool(npc->getAttackTarget().getCharacter() != nullptr);
}

static std::string ContextName(Character *npc) {
  std::string name = npc->getName();
  if (!name.empty() && name != "Unknown Entity" && name != "Unknown")
    return name;
  if (!npc->displayName.empty())
    return npc->displayName;
  if (npc->data && !npc->data->name.empty())
    return npc->data->name;
  return name;
}

static std::string JobNames(Character *npc) {
  std::string jobs;
  for (int i = 0; i < npc->getPermajobCount(); ++i) {
    std::string job = npc->getPermajobName(i);
    if (!job.empty())
      jobs += (jobs.empty() ? "" : ", ") + job;
  }
  return jobs.empty() ? "None" : jobs;
}

static bool LeadsFaction(Character *npc, Faction *faction) {
  hand leader;
  return faction && faction->data && (uintptr_t)faction->data > 0x1000 &&
         faction->data->getHandle(leader, "leader") && leader.isValid() &&
         leader == npc->getHandle();
}

static std::string IdentityFields(GameWorld *world, Character *npc) {
  Faction *faction = CharacterFaction(npc);
  std::string json =
      "\"name\": \"" + EscapeJSON(ContextName(npc)) + "\", \"template\": \"" +
      EscapeJSON(npc->data ? npc->data->name : std::string()) +
      "\", \"template_id\": \"" +
      EscapeJSON(npc->data ? npc->data->stringID : std::string()) +
      "\", \"unique\": " + JsonBool(npc->isUnique()) + ", \"race\": \"" +
      EscapeJSON(RaceName(npc)) + "\", \"animal\": " +
      JsonBool(npc->isAnimal() != nullptr) + ", \"gender\": \"" +
      GenderOf(npc) +
      "\", \"faction\": \"" + EscapeJSON(FactionName(faction)) +
      "\", \"factionID\": \"" + EscapeJSON(FactionID(faction)) +
      "\", \"job\": \"" + EscapeJSON(JobNames(npc)) +
      "\", \"origin_faction\": \"" + EscapeJSON(GetIdentityFaction(npc)) +
      "\", \"npc_id\": \"" + EscapeJSON(GetNpcId(npc)) + "\", ";
  Faction *playerFaction = world->player ? world->player->getFaction() : nullptr;
  if (faction && playerFaction && playerFaction->relations)
    json += "\"relation\": " +
            ToString((int)playerFaction->relations->getFactionRelation(faction)) +
            ", ";
  return json + RoleJson(npc) +
         ", \"is_leader\": " + JsonBool(LeadsFaction(npc, faction));
}

// Only the faction of each character in sight, which the threat count of an
// action dialogue reads. A sighting outside the player faction keeps the
// origin faction of the character, so a later recruit still has it
static std::string NearbyFactions(GameWorld *world, Character *npc) {
  lektor<RootObject *> results;
  world->getCharactersWithinSphere(results, npc->getPosition(), VISION_RANGE,
                                   0.0f, 0.0f, 16, 0, npc);
  Character *first = FirstPlayerCharacter();
  std::string json = "[";
  for (uint32_t i = 0; i < results.size(); ++i) {
    Character *other = (Character *)results.stuff[i];
    if (!other || (uintptr_t)other < 0x1000 || other == first)
      continue;
    Faction *faction = CharacterFaction(other);
    std::string name = FactionName(faction);
    if (faction && !faction->isThePlayer())
      g_originFactions.insert(std::make_pair(GetNpcId(other), name));
    json += (json.size() > 1 ? ", " : "") + std::string("{\"faction\": \"") +
            EscapeJSON(name) + "\"}";
  }
  return json + "]";
}

static std::string SquadNames(GameWorld *world) {
  std::string json = "[";
  lektor<Character *> &members = world->player->playerCharacters;
  for (uint32_t i = 0; i < members.size(); ++i)
    json += std::string(i ? ", " : "") + "\"" +
            EscapeJSON(members[i]->getName()) + "\"";
  return json + "]";
}

static std::string LimbFields(const std::string &name,
                              MedicalSystem::HealthPartStatus *part) {
  return "\"" + name + "\": " + ToString(part ? (int)part->flesh : 100) +
         ", \"" + name +
         "_max\": " + ToString(part ? (int)part->maxHealth() : 100);
}

static std::string MedicalJson(MedicalSystem *med) {
  // hunger is a deficit (0 full, 300 starving); fed is food still being digested
  float hunger = (300.0f - med->hunger) + med->fed;
  return "{\"blood\": " + ToString((int)med->blood) +
         ", \"max_blood\": " + ToString((int)med->getMaxBlood()) +
         ", \"blood_rate\": " + ToString(med->currentBleedRate) +
         ", \"hunger\": " + ToString((int)(hunger < 0 ? 0 : hunger)) +
         ", \"is_unconscious\": " + JsonBool(med->unconcious) +
         ", \"limbs\": {" + LimbFields("head", med->getPart(0)) + ", " +
         LimbFields("stomach", med->getPart(1)) + ", " +
         LimbFields("left_arm", med->leftArm) + ", " +
         LimbFields("right_arm", med->rightArm) + ", " +
         LimbFields("left_leg", med->leftLeg) + ", " +
         LimbFields("right_leg", med->rightLeg) + "}}";
}

static bool IsPlayerTown(TownBase *town) {
  Faction *owner = ((RootObjectBase *)town)->getFaction();
  return owner && owner->isThePlayer();
}

// Every outpost is "Your Outpost" until the player renames it, so only the
// handle tells two apart
static std::string TownKey(TownBase *town) {
  const hand &h = ((RootObjectBase *)town)->getHandle();
  return "t:" + ToString(h.index) + "-" + ToString(h.serial) + "-" +
         ToString(h.container) + "-" + ToString(h.containerSerial);
}

static std::string EnvironmentJson(Character *npc) {
  std::string json = "{\"indoors\": " + JsonBool(npc->isIndoors().isValid()) +
                     ", \"in_town\": " +
                     JsonBool(npc->amInsideTownWalls() != 0);
  TownBase *town = npc->getCurrentTownLocation();
  if (town) {
    json += ", \"town_name\": \"" + EscapeJSON(town->getName()) + "\"";
    if (IsPlayerTown(town))
      json += ", \"player_town\": \"" + TownKey(town) + "\"";
  }
  std::string zone = ZoneName();
  if (!zone.empty())
    json += ", \"zone_name\": \"" + EscapeJSON(zone) + "\"";
  return json + ", \"weather\": " +
         ToString((int)npc->getCurrentWeatherAffectStatus()) + "}";
}

template <class Tag>
static std::string TagList(Character *npc, Character *other, int count) {
  std::string list;
  for (int i = 1; i < count; ++i)
    if (npc->getCharacterMemoryTag(other, (Tag)i))
      list += (list.empty() ? "" : ",") + ToString(i);
  return "[" + list + "]";
}

std::string GetDetailedContext(Character *npc, const std::string &type,
                               Character *speaker) {
  GameWorld *world = ppWorld ? *ppWorld : nullptr;
  if (!npc || (uintptr_t)npc < 0x1000 || !world)
    return "{}";
  bool player = type == "player";
  Building *building = BuildingOf(npc);
  bool inShop = building && (building->isAShop() ||
                             building->designation == BD_SHOP ||
                             building->designation == BD_BAR);
  std::string json =
      "{" + StateFields(npc) + GameTimeFields() + ", " +
      IdentityFields(world, npc) + ", \"in_shop\": " + JsonBool(inShop) +
      ", \"building_name\": \"" + EscapeJSON(BuildingName(npc)) +
      "\", \"nearby\": " + NearbyFactions(world, npc) +
      ", \"money\": " + ToString(MoneyOf(npc));
  if (player && world->player)
    json += ", \"squad\": " + SquadNames(world);
  CharStats *stats = npc->getStats();
  if (stats)
    json += ", \"stats\": {\"melee_attack\": " +
            ToString((int)stats->getStat(STAT_MELEE_ATTACK, false)) +
            ", \"melee_defence\": " +
            ToString((int)stats->getStat(STAT_MELEE_DEFENCE, false)) + "}";
  MedicalSystem *med = npc->getMedical();
  if (med)
    json += ", \"medical\": " + MedicalJson(med);
  json += ", \"environment\": " + EnvironmentJson(npc);

  if (GetCurrentThreadId() == g_mainThreadId) {
    std::vector<Item *> items;
    GetAllCharacterItems(npc, items);
    json += ", \"inventory\": " + ItemsJson(items);
    // The trade window of a shop shows the items of all its furniture as its
    // stock
    if (!player && inShop) {
      std::vector<Item *> stock;
      GetShopItems(npc, stock);
      json += ", \"stock\": " + ItemsJson(stock);
    }
  } else {
    json += ", \"inventory\": []";
  }

  if (speaker && speaker != npc)
    json += ", \"combat_side\": \"" + CombatSide(npc, speaker) + "\"";

  Character *first = FirstPlayerCharacter();
  json += ", \"memories\": ";
  if (first)
    json += "{\"short_term\": " +
            TagList<CharacterPerceptionTags_ShortTerm>(npc, first, 8) +
            ", \"long_term\": " +
            TagList<CharacterPerceptionTags_LongTerm>(npc, first, 17) + "}";
  else
    json += "{}";
  return json + "}";
}

struct GameEvent {
  std::string kind;
  std::string fields;
  unsigned long long attack;
  int day, hour, minute;
  DWORD queuedAt;
};
// Under g_eventMutex, because the hooks of knockouts, deaths, and prisons run
// off the game thread
static std::deque<GameEvent> g_gameEvents;
static std::set<unsigned long long> g_waitingAttacks;

static void GameClock(GameWorld *world, int &day, int &hour, int &minute) {
  TimeOfDay tod = world->getTimeStamp_inGameHours();
  day = (int)tod.getTotalDays();
  hour = (int)fmod(tod.getTotalHours(), 24.0);
  minute = (int)fmod(tod.getTotalMinutes(), 60.0);
}

void QueueGameEvent(const std::string &kind, const std::string &fields,
                    unsigned long long attack) {
  // The cull deletes by game time, so an event needs one
  GameWorld *world = ppWorld ? *ppWorld : nullptr;
  if (!world)
    return;
  GameEvent ev;
  ev.kind = kind;
  ev.fields = fields;
  ev.attack = attack;
  ev.queuedAt = GetTickCount();

  EnterCriticalSection(&g_eventMutex);
  // Read under the lock, so that the queue holds the events in the order of
  // their game times: the server takes a step back of the game time as a load
  GameClock(world, ev.day, ev.hour, ev.minute);
  g_gameEvents.push_back(ev);
  if (kind == "attack")
    g_waitingAttacks.insert(attack);
  if (g_gameEvents.size() > 100) {
    // A dropped attack no longer waits, so the hook can add it again
    if (g_gameEvents.front().kind == "attack")
      g_waitingAttacks.erase(g_gameEvents.front().attack);
    g_gameEvents.pop_front();
  }
  LeaveCriticalSection(&g_eventMutex);

  if (LogEnabled(LOG_DEBUG))
    Log(LOG_DEBUG, "EVENT: " + kind + ": " + fields);
}

bool AttackWaits(unsigned long long attack) {
  EnterCriticalSection(&g_eventMutex);
  bool waits = g_waitingAttacks.count(attack) > 0;
  LeaveCriticalSection(&g_eventMutex);
  return waits;
}

// The buffer drops its oldest past 100, and the events that wait are lost
// when the game closes. A save holds the new handle, so a re-key that dies
// with the game would cut the character off from its records
bool ReportDue() {
  EnterCriticalSection(&g_eventMutex);
  bool due = g_gameEvents.size() >= 50 ||
             (!g_gameEvents.empty() &&
              GetTickCount() - g_gameEvents.front().queuedAt >= 60000);
  for (size_t i = 0; !due && i < g_gameEvents.size(); ++i)
    due = g_gameEvents[i].kind == "rekey";
  LeaveCriticalSection(&g_eventMutex);
  return due;
}

// Empties the buffer, because the server records each event that it gets
std::string TakeGameEvents() {
  std::deque<GameEvent> events;
  EnterCriticalSection(&g_eventMutex);
  events.swap(g_gameEvents);
  g_waitingAttacks.clear();
  LeaveCriticalSection(&g_eventMutex);

  std::string json = "[";
  for (size_t i = 0; i < events.size(); ++i) {
    const GameEvent &e = events[i];
    if (i > 0)
      json += ",";
    json += "{\"kind\": \"" + e.kind + "\", " + e.fields + ", ";
    json += "\"day\": " + ToString(e.day) + ", ";
    json += "\"hour\": " + ToString(e.hour) + ", ";
    json += "\"minute\": " + ToString(e.minute) + "}";
  }
  return json + "]";
}

// The towns whose data a world state swapped for an override, for example
// Brink after the Reavers take it. The name is the one of the original data,
// which the location records use, and the type is a TownType.
std::string ChangedTowns() {
  std::string json = "[";
  SharedKing *shared = ppSharedKing ? *ppSharedKing : nullptr;
  if (!shared || !shared->townList)
    return json + "]";
  // Not getObjectsWithinSphere: with TOWN it gives items, and isTown crashes
  lektor<RootObject *> &towns = shared->townList->getAllTowns();
  for (uint32_t i = 0; i < towns.size(); ++i) {
    Town *town = towns[i] ? ((TownBase *)towns[i])->isTown() : nullptr;
    if (!town)
      continue;
    GameData *now = town->getGameData();
    GameData *original = town->getOriginalGameData();
    if (!now || !original || now == original)
      continue;
    Faction *owner = ((RootObjectBase *)town)->getFaction();
    auto type = now->idata.find("type");
    if (json.size() > 1)
      json += ",";
    json += "{\"name\": \"" + EscapeJSON(original->name) + "\", \"owner\": \"" +
            EscapeJSON(owner ? FactionName(owner) : std::string()) +
            "\", \"owner_id\": \"" +
            EscapeJSON(owner && owner->data ? owner->data->stringID
                                            : std::string()) +
            "\", \"type\": " +
            ToString(type != now->idata.end() ? type->second : -1) + "}";
  }
  return json + "]";
}

// KenshiLib declares neither the class nor its getter, so the layout and the
// getter addresses come from Lucius64's KenshiExtensionPlugin.
class UniqueNPCManager {
public:
  struct UniqueCharacterState {
    GameData *characterTemplate;
    hand handle;
    WorldStateEnum state;
    bool playerInvolvement;
  };
  ogre_unordered_map<GameData *, UniqueCharacterState>::type
      uniqueCharacterStates;
};

typedef UniqueNPCManager *(*UniqueNPCManagerGetter)();

static const struct {
  KenshiLib::BinaryVersion::KenshiPlatform platform;
  const char *version;
  uintptr_t rva;
} UNIQUE_NPC_MANAGER_GETTERS[] = {
    {KenshiLib::BinaryVersion::STEAM, "1.0.65", 0x354500},
    {KenshiLib::BinaryVersion::GOG, "1.0.65", 0x3540b0},
    {KenshiLib::BinaryVersion::STEAM, "1.0.68", 0x354560},
    {KenshiLib::BinaryVersion::GOG, "1.0.68", 0x353f00},
};

static UniqueNPCManager *UniqueNPCs() {
  static UniqueNPCManagerGetter getter = nullptr;
  static bool resolved = false;
  if (!resolved) {
    resolved = true;
    KenshiLib::BinaryVersion version = KenshiLib::GetKenshiVersion();
    for (size_t i = 0; i < sizeof(UNIQUE_NPC_MANAGER_GETTERS) /
                               sizeof(UNIQUE_NPC_MANAGER_GETTERS[0]);
         ++i) {
      if (UNIQUE_NPC_MANAGER_GETTERS[i].platform == version.GetPlatform() &&
          version.GetVersion() == UNIQUE_NPC_MANAGER_GETTERS[i].version)
        getter = (UniqueNPCManagerGetter)(
            (uintptr_t)GetModuleHandleA(nullptr) +
            UNIQUE_NPC_MANAGER_GETTERS[i].rva);
    }
    if (!getter)
      Log(LOG_WARN, "SYSTEM: No address of the unique NPC states for " +
                           version.GetPlatformStr() + " " +
                           version.GetVersion() +
                           ", so the faction lore keeps every leader alive");
  }
  return getter ? getter() : nullptr;
}

// The id is the string ID of the template, which the npc_id of a canon
// character holds. Without the states it gives null, because an empty list
// would mean that every unique NPC lives.
std::string UniqueStates() {
  UniqueNPCManager *manager = UniqueNPCs();
  if (!manager)
    return "null";
  std::string json = "[";
  ogre_unordered_map<GameData *,
                     UniqueNPCManager::UniqueCharacterState>::type &states =
      manager->uniqueCharacterStates;
  for (auto it = states.begin(); it != states.end(); ++it) {
    WorldStateEnum state = it->second.state;
    if (!it->first || (state != DEAD && state != IMPRISONED))
      continue;
    if (json.size() > 1)
      json += ",";
    json += "{\"id\": \"" + EscapeJSON(it->first->stringID) +
            "\", \"name\": \"" + EscapeJSON(it->first->name) +
            "\", \"state\": \"" + (state == DEAD ? "dead" : "imprisoned") +
            "\"}";
  }
  return json + "]";
}

static std::string NameWords(const std::string &text) {
  std::string words;
  for (size_t i = 0; i < text.size(); ++i) {
    unsigned char c = (unsigned char)text[i];
    if (isalnum(c))
      words += (char)tolower(c);
    else if (!words.empty() && words[words.size() - 1] != ' ')
      words += ' ';
  }
  if (!words.empty() && words[words.size() - 1] == ' ')
    words.erase(words.size() - 1);
  return words;
}

// Matches a name as the server does, so each town that the server finds by
// name gets its offset. Towns can share a name, such as the Holy Farms, so the
// nearest one counts.
std::string NamedTowns(const std::string &line, Character *from) {
  std::string json = "[";
  SharedKing *shared = ppSharedKing ? *ppSharedKing : nullptr;
  if (!shared || !shared->townList || !from)
    return json + "]";
  std::string said = " " + NameWords(line) + " ";
  Ogre::Vector3 here = from->getPosition();
  std::map<std::string, std::pair<std::string, Ogre::Vector3> > nearest;
  lektor<RootObject *> &towns = shared->townList->getAllTowns();
  for (uint32_t i = 0; i < towns.size(); ++i) {
    Town *town = towns[i] ? ((TownBase *)towns[i])->isTown() : nullptr;
    if (!town)
      continue;
    GameData *original = town->getOriginalGameData();
    std::string name = original ? original->name : town->getName();
    std::string words = NameWords(name);
    if (words.compare(0, 4, "the ") == 0)
      words.erase(0, 4);
    if (words.empty() || said.find(" " + words + " ") == std::string::npos)
      continue;
    Ogre::Vector3 at = town->getPosition();
    std::map<std::string, std::pair<std::string, Ogre::Vector3> >::iterator
        found = nearest.find(words);
    if (found == nearest.end() ||
        here.distance(at) < here.distance(found->second.second))
      nearest[words] = std::make_pair(name, at);
  }
  for (std::map<std::string,
                std::pair<std::string, Ogre::Vector3> >::iterator it =
           nearest.begin();
       it != nearest.end(); ++it) {
    int dx = (int)(it->second.second.x - here.x);
    int dz = (int)(it->second.second.z - here.z);
    Log(LOG_DEBUG, "CHAT: " + it->second.first + " lies at x " +
                       ToString(dx) + ", z " + ToString(dz) + " from " +
                       from->getName());
    if (json.size() > 1)
      json += ",";
    json += "{\"name\": \"" + EscapeJSON(it->second.first) +
            "\", \"dx\": " + ToString(dx) + ", \"dz\": " + ToString(dz) + "}";
  }
  return json + "]";
}

TownBase *FindTown(const std::string &name) {
  SharedKing *shared = ppSharedKing ? *ppSharedKing : nullptr;
  if (!shared || !shared->townList || name.empty())
    return nullptr;
  TownBase *partial = nullptr;
  lektor<RootObject *> &towns = shared->townList->getAllTowns();
  for (uint32_t i = 0; i < towns.size(); ++i) {
    TownBase *town = (TownBase *)towns[i];
    std::string townName = town ? town->getName() : std::string();
    if (!town || !ContainsIgnoreCase(townName, name))
      continue;
    if (townName.size() == name.size())
      return town;
    if (!partial)
      partial = town;
  }
  return partial;
}

// The cats belong to the whole player faction, so this character pays
Character *FirstPlayerCharacter() {
  GameWorld *world = ppWorld ? *ppWorld : nullptr;
  return world && world->player && world->player->playerCharacters.size() > 0
             ? world->player->playerCharacters[0]
             : nullptr;
}

Blackboard *BoardOf(Character *c) {
  Blackboard *board = c->getBlackboard();
  return board && (uintptr_t)board > 0x1000 ? board : nullptr;
}

GameData *BodyguardPackage() {
  GameWorld *world = ppWorld ? *ppWorld : nullptr;
  return world ? world->gamedata.getData("5090-gamedata.base") : nullptr;
}

int MoneyOf(Character *c) {
  int money = c->getMoney();
  if (money <= 0 && c->getOwnerships())
    money = c->getOwnerships()->getMoney();
  return money;
}

bool InPlayerFaction(Character *c) {
  Faction *faction = c->getFaction();
  return faction && faction->isThePlayer();
}

bool HeldByPlayer(Character *c) {
  Faction *captor = CaptorFaction(c);
  return captor && captor->isThePlayer();
}

// null without a town list, because an empty list makes the server delete the
// record of every outpost
std::string PlayerTowns() {
  SharedKing *shared = ppSharedKing ? *ppSharedKing : nullptr;
  if (!shared || !shared->townList)
    return "null";
  std::string json = "[";
  lektor<RootObject *> &towns = shared->townList->getAllTowns();
  for (uint32_t i = 0; i < towns.size(); ++i) {
    TownBase *town = (TownBase *)towns[i];
    if (!town || !IsPlayerTown(town))
      continue;
    if (json.size() > 1)
      json += ",";
    json += "{\"key\": \"" + TownKey(town) + "\", \"name\": \"" +
            EscapeJSON(town->getName()) + "\", \"zone\": \"" +
            EscapeJSON(ZoneOf(town->getBiome())) + "\"}";
  }
  return json + "]";
}

std::string GameReport() {
  Character *first = FirstPlayerCharacter();
  std::string player = first ? GetDetailedContext(first, "player") : "{}";
  return "{\"player\": " + player + ", \"events\": " + TakeGameEvents() +
         ", \"changed_towns\": " + ChangedTowns() +
         ", \"unique_states\": " + UniqueStates() +
         ", \"player_towns\": " + PlayerTowns() + "}";
}

// Leading commas, so the empty result without a world leaves the object valid
std::string GameTimeFields() {
  GameWorld *world = ppWorld ? *ppWorld : nullptr;
  if (!world)
    return "";
  int day, hour, minute;
  GameClock(world, day, hour, minute);
  return ", \"day\": " + ToString(day) + ", \"hour\": " + ToString(hour) +
         ", \"minute\": " + ToString(minute);
}
