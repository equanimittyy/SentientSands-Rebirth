#include "GameActions.h"
#include "Context.h"
#include "Probes.h"
#include "../core/Globals.h"
#include "../core/Utils.h"
#include <algorithm>
#include <kenshi/AI/Blackboard.h>
#include <kenshi/Building/Building.h>
#include <kenshi/Character.h>
#include <kenshi/Dialogue.h>
#include <kenshi/GameData.h>
#include <kenshi/GameWorld.h>
#include <kenshi/Gear.h>
#include <kenshi/Inventory.h>
#include <kenshi/Item.h>
#include <kenshi/Platoon.h>
#include <kenshi/PlayerInterface.h>
#include <kenshi/RootObjectFactory.h>
#include <kenshi/StateBroadcastData.h>
#include <kenshi/Town.h>
#include <kenshi/util/hand.h>
#include <set>
#include <vector>

static std::string TaskName(TaskType task) {
  switch (task) {
  case RAID_TOWN:
    return "RAID_TOWN";
  case TRAVEL_TO_TARGET_TOWN:
    return "TRAVEL_TO_TARGET_TOWN";
  case RELEASE_PRISONER:
    return "RELEASE_PRISONER";
  default:
    return "TASK_" + ToString((int)task);
  }
}

// The label with the grade first, then the exact name, so that a deal for
// Bread never hands over a Bread Loaf
static Item *FindInItems(const std::vector<Item *> &items,
                         const std::string &lowerName) {
  // An empty name is part of every name, so it would match the first item
  if (lowerName.empty())
    return nullptr;
  Item *named = nullptr;
  Item *partial = nullptr;
  for (size_t i = 0; i < items.size(); ++i) {
    if (!items[i])
      continue;
    if (Lower(ItemLabel(items[i])) == lowerName)
      return items[i];
    std::string name = Lower(items[i]->getName());
    if (!named && name == lowerName)
      named = items[i];
    if (!partial && name.find(lowerName) != std::string::npos)
      partial = items[i];
  }
  return named ? named : partial;
}

static Item *FindStockItem(Character *holder, const std::string &lowerName) {
  std::vector<Item *> stock;
  GetShopItems(holder, stock);
  return FindInItems(stock, lowerName);
}

// A shopkeeper also sells the stock in the furniture of its shop
static Item *FindNamedItem(Character *holder, const std::string &lowerName,
                           bool withShop = false) {
  std::vector<Item *> items;
  GetAllCharacterItems(holder, items);
  Item *found = FindInItems(items, lowerName);
  if (found || !withShop)
    return found;
  return FindStockItem(holder, lowerName);
}

// What giveItem returns after it drops an item is unknown, so the drop is a
// second call that runs only when the item did not fit
static bool GiveOrDrop(GameWorld *world, Character *c, Item *item) {
  if (c->giveItem(item, false, false))
    return true;
  std::string name = item->getName();
  c->giveItem(item, true, false);
  Log(LOG_INFO, "ACTION: " + c->getName() + " has no room for " + name +
                    ", so it drops at their feet");
  world->showPlayerAMessage(c->getName() + " has no room for " + name +
                                ", so it drops at their feet.",
                            true);
  return true;
}

static bool Carry(GameWorld *world, Character *c, Item *item) {
  return c->giveItem(item, false, false);
}

// The trader sells from the furniture, so what it buys goes there
static bool Stock(GameWorld *world, Character *trader, Item *item) {
  Building *building = BuildingOf(trader);
  if (!building)
    return false;
  lektor<Building *> furniture;
  building->findAllFurnitureWithFunction(furniture, BF_ANY);
  for (uint32_t i = 0; i < furniture.size(); ++i)
    if (furniture[i] && (uintptr_t)furniture[i] > 0x1000 &&
        furniture[i]->getInventory() &&
        furniture[i]->giveItem(item, false, false))
      return true;
  return false;
}

typedef bool (*Placer)(GameWorld *, Character *, Item *);

// Moves at most count of the stack, so a deal for 2 Bread never hands over a
// whole stack of 10. Returns how many moved.
static int MoveItems(GameWorld *world, Character *holder, Item *item,
                     int count, Character *receiver, Placer place) {
  int moved = count < item->quantity ? count : item->quantity;
  bool split = moved < item->quantity;
  if (item->isEquipped)
    holder->unequipItem(item->inventorySection, item);
  // Item::getInventory is the content of a container item, not the inventory
  // that holds the item, such as the furniture of a shop
  RootObject *owner = item->getInventoryWeAreIn().getRootObject();
  Inventory *inv = owner ? owner->getInventory() : holder->getInventory();
  Item *detached =
      inv ? inv->removeItemDontDestroy_returnsItem(item, moved, split) : nullptr;
  if (!detached)
    return 0;
  if (!place(world, receiver, detached)) {
    GiveOrDrop(world, holder, detached);
    return 0;
  }
  return moved;
}

// For a weapon, createItem takes the manufacturer first and the weapon third;
// the weapon first makes it return null
static Item *CreateItem(GameWorld *world, GameData *data, GameData *maker,
                        GameData *grade, int level) {
  if (data->type != WEAPON)
    return world->theFactory->createItem(data, hand(), NULL, grade, level,
                                         NULL);
  if (!grade) {
    Log(LOG_WARN, "ACTION: No grade for the weapon " + data->name);
    return NULL;
  }
  return world->theFactory->createItem(maker, hand(), data, grade, level,
                                       NULL);
}

static GameData *FindItemData(GameWorld *world, const std::string &name) {
  static const itemType TYPES[] = {ITEM,      WEAPON,           ARMOUR,  CROSSBOW,
                                   BLUEPRINT, LIMB_REPLACEMENT, MAP_ITEM};
  GameDataManager *sources[] = {&world->leveldata, &world->gamedata};
  for (int s = 0; s < 2; ++s)
    for (size_t t = 0; t < sizeof(TYPES) / sizeof(TYPES[0]); ++t) {
      GameData *found = sources[s]->getDataByName(name, TYPES[t]);
      if (found)
        return found;
    }
  return nullptr;
}

// The Cheats window gives an armour or a crossbow a level but no grade
static GameData *GearGrade(GameWorld *world, GameData *gd) {
  if (gd->type != ARMOUR && gd->type != CROSSBOW)
    return nullptr;
  int gradeType = gd->type == ARMOUR ? MATERIAL_SPECS_CLOTHING : 0;
  static const char *REFS[] = {"material", "model", "mesh"};
  for (int r = 0; r < 3; ++r) {
    const Ogre::vector<GameDataReference>::type *refs =
        gd->getReferenceListIfExists(REFS[r]);
    GameData *grade =
        refs && !refs->empty() ? world->gamedata.getData(refs->at(0).sid)
                               : nullptr;
    if (grade && (!gradeType || grade->type == gradeType))
      return grade;
  }
  // createItem takes a null grade and sets the grade from the level
  return nullptr;
}

static unsigned int g_newestBubble;
static unsigned int g_previousBubble;
// A call can outlast a bubble life, so a "..." waits for its line. This only
// ends one whose line never came, past the default 55 s deadline of a call
static const float THINKING_LIFE = 60.0f;

static void EndBubble(Character *c) {
  if (c && c->dialogue && (uintptr_t)c->dialogue > 0x1000 &&
      c->dialogue->speechTextTimer > 0.0f) {
    // clearSpeechBox is private, so the engine hides the bubble when this
    // timer runs out on its next update
    c->dialogue->speechTextTimer = 0.001f;
    c->dialogue->speechTextTimer_forced = 0.001f;
  }
}

// By key, because hand == gave false for two handles of one character
static void KeepTwoBubbles(Character *speaker) {
  unsigned int key = HandleKey(speaker);
  if (key == g_newestBubble)
    return;
  if (g_previousBubble && key != g_previousBubble)
    EndBubble(KeyedCharacter(g_previousBubble));
  g_previousBubble = g_newestBubble;
  g_newestBubble = key;
}

static bool IsLockedUp(Character *c) {
  return c->inSomething == IN_PRISON || c->isChained || c->isChainedMode();
}

// KenshiLib declares DoorLock without members; this is the layout that
// Lucius64's KenshiExtensionPlugin reads
class DoorLock {
public:
  int level;
  float hardness;
  UseableStuff *stuff;
  float minTime;
  float maxTime;
  float pickingTime;
  float waitingTime;
  bool locked;
  bool broken;
};

// Unlocks as Lucius64's KenshiExtensionPlugin does, so the game lets the
// prisoner out instead of the plugin writing the prison state
static void UnlockPrisoner(GameWorld *world, Character *target) {
  Building *cage =
      target->inSomething == IN_PRISON ? target->inWhat.getBuilding() : NULL;
  DoorLock *door = cage ? cage->getDoorLock() : NULL;
  if (door)
    door->locked = false;
  LockedArmour *shackles = target->getChainedModeShackles();
  if (shackles && shackles->lock)
    shackles->lock->locked = false;
  Character *rescuer =
      world->player ? world->player->getNearestCharacterTo(target->getPosition())
                    : NULL;
  if (rescuer && target->dialogue && (uintptr_t)target->dialogue > 0x1000)
    target->dialogue->sendEvent(rescuer, EV_UNLOCK_MY_CAGE_OR_SHACKLES);
}

// An unlock leaves the slave state, so slavers would hunt the recruit
static void FreeCaptive(GameWorld *world, Character *npc) {
  UnlockPrisoner(world, npc);
  StateBroadcastData *broadcast = npc->getStateBroadcast();
  if (npc->isSlave() != NOT_SLAVE && broadcast)
    broadcast->setSlaveState(NOT_SLAVE);
}

// The unpaused time after which a watcher stops waiting for the game: a jailer
// whose package keeps it at its desk never walks to the cage, and a squad that
// runs from a fight never goes down
static const DWORD ACTION_WAIT_MS = 30000;

static DWORD UnpausedStep(GameWorld *world, DWORD &last) {
  DWORD now = GetTickCount();
  DWORD step = world->isPaused() ? 0 : now - last;
  last = now;
  return step;
}

struct Pending {
  unsigned int key; // A key outlives the new handle of a squad change
  DWORD waited;
};
static std::vector<Pending> g_releases;

static void WatchReleases(GameWorld *world, DWORD step) {
  for (size_t i = 0; i < g_releases.size();) {
    Character *target = KeyedCharacter(g_releases[i].key);
    if (!target || !IsLockedUp(target)) {
      g_releases.erase(g_releases.begin() + i);
      continue;
    }
    g_releases[i].waited += step;
    if (g_releases[i].waited < ACTION_WAIT_MS) {
      ++i;
      continue;
    }
    Log(LOG_INFO, "ACTION: The release task left " + target->getName() +
                      " locked up, so the plugin unlocks it");
    UnlockPrisoner(world, target);
    world->showPlayerAMessage("You have been freed!", true);
    g_releases.erase(g_releases.begin() + i);
  }
}

struct Fight {
  std::vector<unsigned int> npcs;
  std::vector<unsigned int> players;
  DWORD quiet;
};
static std::vector<Fight> g_fights;

static void SquadKeys(Character *member, std::vector<unsigned int> &keys) {
  ActivePlatoon *active = member->getPlatoon();
  if (!active || (uintptr_t)active < 0x1000) {
    keys.push_back(HandleKey(member));
    return;
  }
  for (uint32_t i = 0; i < active->things.size(); ++i) {
    RootObject *thing = active->things[i];
    // A pack animal does not fight, so the fight would go on until it died
    if (thing && (uintptr_t)thing > 0x1000 &&
        thing->getDataType() == CHARACTER &&
        !((Character *)thing)->isAnimal())
      keys.push_back(HandleKey((Character *)thing));
  }
}

static void Members(const std::vector<unsigned int> &keys,
                    std::vector<Character *> &out) {
  for (size_t i = 0; i < keys.size(); ++i) {
    Character *c = KeyedCharacter(keys[i]);
    if (c)
      out.push_back(c);
  }
}

// The game marks only the hitter of a character as its enemy, so a squad-mate
// that no one hits stays out of the fight
static void MarkEnemies(const std::vector<Character *> &side,
                        const std::vector<Character *> &enemies, bool enemy) {
  for (size_t i = 0; i < side.size(); ++i)
    for (size_t j = 0; j < enemies.size(); ++j) {
      if (enemy)
        side[i]->rememberCharacter(enemies[j], ST_TEMPORARY_ENEMY);
      else
        side[i]->clearTempEnemyStatus(enemies[j]);
    }
}

static bool Down(const std::vector<Character *> &side) {
  for (size_t i = 0; i < side.size(); ++i)
    if (!side[i]->isDead() && !side[i]->isUnconcious())
      return false;
  return true;
}

static bool Attacks(const std::vector<Character *> &side,
                    const std::vector<Character *> &enemies) {
  for (size_t i = 0; i < side.size(); ++i) {
    Character *target = side[i]->getAttackTarget().getCharacter();
    if (target &&
        std::find(enemies.begin(), enemies.end(), target) != enemies.end())
      return true;
  }
  return false;
}

// Unlike SquadKeys, an animal counts, because a wild animal attacks
static void SquadOf(Character *member, std::vector<Character *> &out) {
  ActivePlatoon *active = member->getPlatoon();
  if (!active || (uintptr_t)active < 0x1000) {
    out.push_back(member);
    return;
  }
  for (uint32_t i = 0; i < active->things.size(); ++i) {
    RootObject *thing = active->things[i];
    if (thing && (uintptr_t)thing > 0x1000 &&
        thing->getDataType() == CHARACTER)
      out.push_back((Character *)thing);
  }
}

static bool CommonFoe(const std::vector<Character *> &side,
                      const std::vector<Character *> &allies) {
  for (size_t i = 0; i < side.size(); ++i) {
    std::vector<Character *> foe(1, side[i]->getAttackTarget().getCharacter());
    if (foe[0] && (Attacks(foe, allies) || Attacks(allies, foe)))
      return true;
  }
  return false;
}

std::string CombatSide(Character *npc, Character *speaker) {
  std::vector<Character *> npcs, players;
  SquadOf(npc, npcs);
  SquadOf(speaker, players);
  if (Attacks(npcs, players) || Attacks(players, npcs))
    return "against";
  if (CommonFoe(npcs, players) || CommonFoe(players, npcs))
    return "with";
  return "";
}

static void StartFight(Character *npc, Character *speaker) {
  Fight fight;
  fight.quiet = 0;
  SquadKeys(npc, fight.npcs);
  SquadKeys(speaker, fight.players);
  std::vector<Character *> npcs, players;
  Members(fight.npcs, npcs);
  Members(fight.players, players);
  MarkEnemies(npcs, players, true);
  MarkEnemies(players, npcs, true);
  g_fights.push_back(fight);
}

static void WatchFights(DWORD step) {
  for (size_t i = 0; i < g_fights.size();) {
    std::vector<Character *> npcs, players;
    Members(g_fights[i].npcs, npcs);
    Members(g_fights[i].players, players);
    bool fighting = Attacks(npcs, players) || Attacks(players, npcs);
    g_fights[i].quiet = fighting ? 0 : g_fights[i].quiet + step;
    bool down = Down(npcs) || Down(players);
    if (!down && g_fights[i].quiet < ACTION_WAIT_MS) {
      ++i;
      continue;
    }
    // The marks and the attack goal outlive the fight, so the NPC attacked the
    // speaker again when it got up
    MarkEnemies(npcs, players, false);
    MarkEnemies(players, npcs, false);
    for (size_t j = 0; j < npcs.size(); ++j)
      if (!npcs[j]->isDead()) {
        npcs[j]->clearAllAIGoals();
        npcs[j]->reThinkCurrentAIAction();
      }
    Log(LOG_INFO, std::string("ACTION: A fight ended, because ") +
                      (down ? "a squad is down" : "no one attacked"));
    g_fights.erase(g_fights.begin() + i);
  }
}

// The AI picks its goal frames later, so a read at the order shows no goal
static const DWORD TREATMENT_CHECK_MS = 5000;

static std::vector<Pending> g_treatments;

// A half-robot needs both kits, so the repair queues behind the first aid
std::string StartTreatment(Character *medic, Character *patient,
                           bool &firstAid, bool &repair, TaskType robotOrder) {
  bool needsFirstAid, needsRepair;
  TreatmentNeeds(patient, needsFirstAid, needsRepair);
  Inventory *inv = medic->getInventory();
  firstAid = needsFirstAid && inv && inv->hasItemFunction(ITEM_FIRSTAID);
  repair = needsRepair && inv && inv->hasItemFunction(ITEM_ROBOTREPAIR);
  if (!needsFirstAid && !needsRepair)
    return patient->getName() + " needs no treatment.";
  if (!firstAid && !repair)
    return medic->getName() + " has no " +
           (needsFirstAid && needsRepair ? "first aid kit or repair kit"
            : needsFirstAid              ? "first aid kit"
                                         : "repair kit") +
           ".";
  medic->clearAllAIGoals();
  if (firstAid)
    medic->addOrder(nullptr, FIRST_AID_ORDER, (RootObject *)patient, false,
                    true, patient->getPosition());
  if (repair)
    medic->addOrder(nullptr, robotOrder, (RootObject *)patient, firstAid,
                    !firstAid, patient->getPosition());
  medic->reThinkCurrentAIAction();
  Pending check = {HandleKey(medic), 0};
  g_treatments.push_back(check);
  return medic->getName() + " is treating " + patient->getName() + ".";
}

static void WatchTreatments(DWORD step) {
  for (size_t i = 0; i < g_treatments.size();) {
    g_treatments[i].waited += step;
    if (g_treatments[i].waited < TREATMENT_CHECK_MS) {
      ++i;
      continue;
    }
    Character *medic = KeyedCharacter(g_treatments[i].key);
    if (medic) {
      Log(LOG_DEBUG, "FIRSTAID_PROBE: name='" + medic->getName() + "' after=" +
                         ToString((int)(TREATMENT_CHECK_MS / 1000)) + "s" +
                         OrdersLine(medic));
    }
    g_treatments.erase(g_treatments.begin() + i);
  }
}

void WatchActions(GameWorld *world) {
  static DWORD last = GetTickCount();
  DWORD step = UnpausedStep(world, last);
  WatchReleases(world, step);
  WatchFights(step);
  WatchTreatments(step);
}

// The server sends each action of a deal as its own pipe message, so the
// actions can arrive over several frames. A payment that fell short therefore
// holds back the NPC's side until the NPC's next line
static std::set<unsigned int> g_shortPayers;

static bool HeldBack(Character *npc, const std::string &action) {
  if (!g_shortPayers.count(HandleKey(npc)))
    return false;
  Log(LOG_INFO, "ACTION: Skipping " + action + " of " + npc->getName() +
                    ", because the payment fell short");
  return true;
}

static void PaidShort(GameWorld *world, Character *npc) {
  g_shortPayers.insert(HandleKey(npc));
  world->showPlayerAMessage(
      npc->getName() + " looks annoyed. \"That's not what we agreed on!\"",
      true);
}

static void DoSay(GameWorld *world, const QueuedAction &act, Character *npc) {
  Log(LOG_DEBUG, "ACTION: SAY [" + npc->getName() + "]: " + act.message +
                     (npc->isPlayerCharacter() ? " (PC)" : " (NPC)"));
  if (act.message.empty()) {
    EndBubble(npc);
    return;
  }
  KeepTwoBubbles(npc);
  if (!g_shortPayers.empty())
    g_shortPayers.erase(HandleKey(npc));
  if (!npc->dialogue || (uintptr_t)npc->dialogue <= 0x1000) {
    Log(LOG_ERROR, "ACTION: " + npc->getName() +
                       " has no dialogue object, so it cannot say: " +
                       act.message);
    return;
  }
  // No endDialogue/setInDialog(false): they clear AI goals, killing the task just queued
  npc->sayALine(act.message, true);
  // Scaled by game speed, else bubbles vanish too fast at high speeds.
  // Both timers are set so the engine honors the duration.
  float speed = world->getFrameSpeedMultiplier();
  float life = act.type == ACT_THINK ? THINKING_LIFE : g_speechBubbleLife;
  float duration = life * (speed < 1.0f ? 1.0f : speed);
  npc->dialogue->speechTextTimer = duration;
  npc->dialogue->speechTextTimer_forced = duration;
}

static void DoAttack(GameWorld *world, Character *npc, Character *target) {
  StartFight(npc, target);
  npc->attackTarget(target);
  npc->addGoal(MELEE_ATTACK, (RootObjectBase *)target);
  npc->reThinkCurrentAIAction();
  world->showPlayerAMessage(npc->getName() + " is attacking!", false);
}

// The fee goes to no purse, because the recruit's purse becomes the player's
static void DoJoinParty(GameWorld *world, const QueuedAction &act,
                        Character *npc) {
  if (!world->player)
    return;
  Character *payer = FirstPlayerCharacter();
  int fee = act.taskValue;
  if (fee > 0 && (!payer || MoneyOf(payer) < fee)) {
    Log(LOG_INFO, "ACTION: " + npc->getName() +
                      " did not join, because the player has less than " +
                      ToString(fee) + " cats");
    PaidShort(world, npc);
    return;
  }
  if (fee > 0) {
    payer->takeMoney(fee);
    world->showPlayerAMessage_withLog("Lost " + ToString(fee) + " cats.", true);
  }
  // A hired follower joins for good, so its contract must not run out
  Blackboard *board = BoardOf(npc);
  if (board && board->hasContractJob())
    board->endContractJob();
  bool held = HeldByPlayer(npc);
  world->player->recruit(npc, false);
  // A fellow captive stays locked up, because it joins to escape with the player
  if (held)
    FreeCaptive(world, npc);
  world->playNotification("ui_cat_change");
  world->showPlayerAMessage_withLog(npc->getName() + " joined your squad.",
                                    true);
}

static void DoSetTask(GameWorld *world, const QueuedAction &act,
                      Character *npc) {
  Log(LOG_INFO, "ACTION: Setting task for " + npc->getName() + ": " +
                    ToString(act.taskValue));
  // No endDialogue here: it kills the speech bubble the NPC just displayed

  // Passive/Hold standing orders can block the new task
  npc->setStandingOrder(MessageForB::M_SET_ORDER_PASSIVE, false);
  npc->setStandingOrder(MessageForB::M_SET_ORDER_HOLD, false);
  npc->clearAllAIGoals();

  TaskType tt = (TaskType)act.taskValue;
  TownBase *town = nullptr;
  if (!act.message.empty()) {
    std::string tName = Trim(act.message, " \t\r\n\"'");
    town = FindTown(tName);
    if (town)
      Log(LOG_DEBUG, "ACTION: Found town match: " + town->getName());
    else
      Log(LOG_WARN, "ACTION: Town '" + tName + "' not found!");
  }
  npc->addJob(tt, town, false, true, npc->getPosition());
  world->showPlayerAMessage(
      npc->getName() + " is now executing: " + TaskName(tt), false);
  npc->addGoal(tt, town);
  npc->reThinkCurrentAIAction();
}

static Item *CarriedItem(Character *holder, const std::string &lowerName) {
  return FindNamedItem(holder, lowerName);
}

static Item *CarriedOrStockItem(Character *holder,
                                const std::string &lowerName) {
  return FindNamedItem(holder, lowerName, true);
}

// Rescans per stack, because removals reorder the inventory. Returns how many
// moved.
static int MoveNamed(GameWorld *world, Character *from, Character *to,
                     const std::string &lowerName, int count,
                     Item *(*find)(Character *, const std::string &),
                     Placer place) {
  int moved = 0;
  while (moved < count) {
    Item *found = find(from, lowerName);
    if (!found)
      break;
    int stack = MoveItems(world, from, found, count - moved, to, place);
    if (stack == 0) {
      Log(LOG_WARN, "ACTION: Could not move " + found->getName() + " from " +
                        from->getName() + ".");
      break;
    }
    moved += stack;
  }
  return moved;
}

static void DoTakeItem(GameWorld *world, const QueuedAction &act,
                       Character *npc, Character *target) {
  Character *player = target ? target : FirstPlayerCharacter();
  if (!player)
    return;
  std::string name = Trim(act.message, " \t\r\n\"'");
  int count = act.taskValue < 1 ? 1 : act.taskValue;
  bool stock = act.type == ACT_BUY_ITEM;
  int taken = MoveNamed(world, player, npc, Lower(name), count, CarriedItem,
                        stock ? Stock : Carry);
  if (taken < count) {
    g_shortPayers.insert(HandleKey(npc));
    Log(LOG_WARN, "ACTION: Transaction failed: " + npc->getName() +
                      " wanted " + ToString(count) + "x '" + name +
                      "' but took only " + ToString(taken));
    bool returnedForLackOfRoom = CarriedItem(player, Lower(name)) != nullptr;
    if (returnedForLackOfRoom)
      world->showPlayerAMessage(npc->getName() + " can't carry all that.",
                                true);
  }
  if (taken > 0) {
    world->showPlayerAMessage_withLog(
        npc->getName() + " took " + (taken > 1 ? ToString(taken) + "x " : "") +
            name + " from you.",
        true);
    npc->reThinkCurrentAIAction();
  }
}

static void DoGiveItem(GameWorld *world, const QueuedAction &act,
                       Character *npc, Character *target) {
  bool sell = act.type == ACT_SELL_ITEM;
  if (HeldBack(npc, sell ? "SELL_ITEM" : "GIVE_ITEM"))
    return;
  Character *player = target ? target : FirstPlayerCharacter();
  if (!player)
    return;
  std::string name = Trim(act.message, " \t\r\n\"'");
  int count = act.taskValue < 1 ? 1 : act.taskValue;
  // A trader in a shop sells its stock and keeps what it carries
  int given = MoveNamed(world, npc, player, Lower(name), count,
                        sell ? FindStockItem : CarriedOrStockItem, GiveOrDrop);
  if (given < count)
    Log(LOG_WARN, "ACTION: NPC " + npc->getName() + " only had " +
                      ToString(given) + " of " + ToString(count) + "x '" +
                      name + "'");
  if (given > 0) {
    world->showPlayerAMessage_withLog(
        npc->getName() + " gave you " +
            (given > 1 ? ToString(given) + "x " : "") + name,
        true);
    npc->reThinkCurrentAIAction();
  }
}

// Charity and the reward of a job (ADD_CATS) cost the NPC nothing, so their
// cats come from no purse
static void DoGiveCats(GameWorld *world, const QueuedAction &act,
                       Character *npc) {
  bool fromNpc = act.type == ACT_GIVE_CATS;
  Character *payee = FirstPlayerCharacter();
  if (!payee || act.taskValue < 1 ||
      HeldBack(npc, fromNpc ? "GIVE_CATS" : "ADD_CATS"))
    return;
  payee->takeMoney(-act.taskValue);
  // A player-faction NPC shares the purse, so the transfer would be a no-op
  if (fromNpc && !InPlayerFaction(npc))
    npc->takeMoney(act.taskValue);
  world->showPlayerAMessage_withLog(
      "Gained " + ToString(act.taskValue) + " cats.", true);
}

static void DoTakeCats(GameWorld *world, const QueuedAction &act,
                       Character *npc) {
  Character *payer = FirstPlayerCharacter();
  if (!payer)
    return;
  int purse = MoneyOf(payer);
  int amount = act.taskValue;
  bool fellShort = amount > purse;
  if (fellShort)
    amount = purse;
  if (amount < 0)
    amount = 0;
  Log(LOG_INFO, "ACTION: Taking " + ToString(amount) +
                    " cats from the player (Requested: " +
                    ToString(act.taskValue) + ", Bank: " + ToString(purse) +
                    ")");
  payer->takeMoney(amount);
  if (!InPlayerFaction(npc))
    npc->takeMoney(-amount);
  if (amount > 0)
    world->showPlayerAMessage_withLog("Lost " + ToString(amount) + " cats.",
                                      true);
  if (fellShort)
    PaidShort(world, npc);
}

static void DoRelease(GameWorld *world, Character *npc, Character *target) {
  if (HeldBack(npc, "RELEASE"))
    return;
  bool lockedUp = IsLockedUp(target);
  float dist = npc->getPosition().distance(target->getPosition());
  Log(LOG_INFO, "ACTION: Release by " + npc->getName() + " on " +
                    target->getName() + ". Locked up: " + ToString(lockedUp) +
                    ", Dist: " + ToString(dist));

  bool didSomething = false;
  if (npc->isCarryingSomething && npc->carryingObject == target->getHandle()) {
    Log(LOG_DEBUG, "ACTION: NPC is carrying target. Dropping.");
    npc->dropCarriedObject(false, false);
    didSomething = true;
  }
  if (lockedUp) {
    Log(LOG_DEBUG, "ACTION: Assigning task: " + TaskName(RELEASE_PRISONER));
    // addOrder overrides at once, unlike addJob; clear=true halts background AI (staying home)
    npc->clearAllAIGoals();
    npc->addOrder(nullptr, RELEASE_PRISONER, (RootObject *)target, false, true,
                  target->getPosition());
    npc->reThinkCurrentAIAction();
    Pending pending = {HandleKey(target), 0};
    g_releases.push_back(pending);
    world->showPlayerAMessage(
        npc->getName() + " is releasing " + target->getName() + "!", false);
    didSomething = true;
  }
  if (!didSomething && !npc->isPlayerCharacter()) {
    Log(LOG_DEBUG, "ACTION: Target already free. Clearing NPC goals.");
    npc->clearAllAIGoals();
    npc->reThinkCurrentAIAction();
  }
}

static void DoHire(GameWorld *world, const QueuedAction &act, Character *npc,
                   Character *target) {
  Blackboard *board = BoardOf(npc);
  GameData *bodyguard = BodyguardPackage();
  if (HeldBack(npc, "HIRE") || !board || !bodyguard)
    return;
  // A renewal finds the old contract still running, and
  // _setContractJob is tested only on an NPC without a contract
  if (board->hasContractJob())
    board->endContractJob();
  board->_setContractJob(bodyguard, act.taskValue, target->getHandle());
  world->showPlayerAMessage_withLog(npc->getName() + " follows you for " +
                                        ToString(act.taskValue) + " hours.",
                                    true);
}

static void DoEndHire(GameWorld *world, Character *npc) {
  Blackboard *board = BoardOf(npc);
  if (!board || !board->hasContractJob())
    return;
  board->endContractJob();
  world->showPlayerAMessage_withLog(npc->getName() + " no longer follows you.",
                                    true);
}

static void DoFirstAid(GameWorld *world, Character *npc, Character *target) {
  if (HeldBack(npc, "FIRST_AID"))
    return;
  bool firstAid, repair;
  std::string message = StartTreatment(npc, target, firstAid, repair);
  Log(LOG_DEBUG, "ACTION: " + message + " first_aid_order=" +
                     (firstAid ? "1" : "0") +
                     " repair_order=" + (repair ? "1" : "0"));
  world->showPlayerAMessage(message, false);
}

static Item *NewItem(GameWorld *world, GameData *gd, GameData *maker,
                     GameData *grade, int level, Character *owner) {
  Item *item = CreateItem(world, gd, maker, grade, level);
  if (!item)
    return NULL;
  item->quantity = 1;
  item->quality = 1.0f;
  item->chargesLeft = item->originalFullChargeAmount;
  if (item->chargesLeft <= 0.0f)
    item->chargesLeft = 1.0f;
  item->setProperOwner(owner->getHandle());
  item->visible = true;
  item->isTradeItem = true;
  if (!item->container && owner->container) {
    item->container = owner->container;
    owner->container->addActiveObject(item);
  }
  return item;
}

static Building *ShelfFor(Character *trader, GameData *gd) {
  Building *building = BuildingOf(trader);
  if (!building)
    return NULL;
  lektor<Building *> furniture;
  building->findAllFurnitureWithFunction(furniture, BF_ANY);
  for (uint32_t i = 0; i < furniture.size(); ++i)
    if (furniture[i] && (uintptr_t)furniture[i] > 0x1000 &&
        InventoryHasRoom(furniture[i]->getInventory(), gd, 1))
      return furniture[i];
  return NULL;
}

// A copy is made only where it fits, so none lies free on the ground, and the
// checks of Accept refuse the sale of a copy that did not fit
void Restock(Character *trader, bool stock, GameData *gd, GameData *maker,
             GameData *grade, int level, int count) {
  GameWorld *world = *ppWorld;
  for (int i = 0; i < count; ++i) {
    Building *shelf = stock ? ShelfFor(trader, gd) : NULL;
    if (stock ? !shelf : !HasRoomFor(trader, gd, 1))
      return;
    Item *item = NewItem(world, gd, maker, grade, level, trader);
    if (!item)
      return;
    if (shelf)
      shelf->giveItem(item, false, false);
    else
      Carry(world, trader, item);
  }
}

static void DoSpawnItem(GameWorld *world, const QueuedAction &act,
                        Character *target) {
  // "<record name>|<label>": the Cheats window also names its record, and the
  // server names only the food of a charity
  size_t pipe = act.message.find('|');
  std::string templateName = act.message.substr(0, pipe);
  std::string label =
      pipe == std::string::npos ? std::string() : act.message.substr(pipe + 1);
  GameData *gd = act.itemData ? act.itemData : FindItemData(world, templateName);
  if (!gd) {
    Log(LOG_WARN, "ACTION: Could not find template for: " + templateName);
    world->showPlayerAMessage(
        "Error: Item template '" + templateName + "' not found.", true);
    return;
  }
  Character *p = target && (uintptr_t)target >= 0x1000 ? target
                                                      : FirstPlayerCharacter();
  if (!p) {
    Log(LOG_WARN, "ACTION: No character found to give item to.");
    return;
  }
  GameData *gradeData = act.itemModel ? act.itemModel : GearGrade(world, gd);
  int count = act.taskValue < 1 ? 1 : act.taskValue;
  int spawnedCount = 0;
  for (int c = 0; c < count; c++) {
    Item *item =
        NewItem(world, gd, act.itemMaker, gradeData, act.itemLevel, p);
    if (!item) {
      Log(LOG_ERROR, "ACTION: Resolved " + gd->name +
                         " but Factory failed to createItem! (Grade: " +
                         (gradeData ? gradeData->name : "NULL") + ", Maker: " +
                         (act.itemMaker ? act.itemMaker->name : "NULL") + ")");
      continue;
    }
    GiveOrDrop(world, p, item);
    spawnedCount++;
    Log(LOG_INFO, "ACTION: Successfully spawned and gave " + gd->name +
                      " to " + p->getName());
  }
  if (spawnedCount == 0)
    return;
  if (p->getInventory()) {
    p->getInventory()->autoArrange();
    p->getInventory()->refreshGui();
  }
  world->addPortraitUpdate(p->getHandle());
  world->showPlayerAMessage_withLog(
      "Received " + (spawnedCount > 1 ? ToString(spawnedCount) + "x " : "") +
          (label.empty() ? gd->name : label),
      true);
}

static void RunAction(GameWorld *world, const QueuedAction &act,
                      Character *npc, Character *target) {
  switch (act.type) {
  case ACT_SAY:
  case ACT_THINK:
    DoSay(world, act, npc);
    break;
  case ACT_ATTACK:
    if (target)
      DoAttack(world, npc, target);
    break;
  case ACT_JOIN_PARTY:
    DoJoinParty(world, act, npc);
    break;
  case ACT_SET_TASK:
    DoSetTask(world, act, npc);
    break;
  case ACT_TAKE_ITEM:
  case ACT_BUY_ITEM:
    DoTakeItem(world, act, npc, target);
    break;
  case ACT_GIVE_ITEM:
  case ACT_SELL_ITEM:
    DoGiveItem(world, act, npc, target);
    break;
  case ACT_GIVE_CATS:
  case ACT_ADD_CATS:
    DoGiveCats(world, act, npc);
    break;
  case ACT_TAKE_CATS:
    DoTakeCats(world, act, npc);
    break;
  case ACT_RELEASE:
    if (target)
      DoRelease(world, npc, target);
    break;
  case ACT_HIRE:
    if (target)
      DoHire(world, act, npc, target);
    break;
  case ACT_END_HIRE:
    DoEndHire(world, npc);
    break;
  case ACT_FIRST_AID:
    if (target)
      DoFirstAid(world, npc, target);
    break;
  case ACT_PROBE:
    RunProbe(npc, target, act.message);
    break;
  case ACT_SPAWN_ITEM:
    DoSpawnItem(world, act, target);
    break;
  default:
    break;
  }
}

void ExecuteQueuedActions(GameWorld *world) {
  std::deque<QueuedAction> batch;
  if (!TryEnterCriticalSection(&g_uiMutex))
    return;
  batch.swap(g_uiActionQueue);
  LeaveCriticalSection(&g_uiMutex);

  for (size_t i = 0; i < batch.size(); ++i) {
    const QueuedAction &act = batch[i];
    // Catches only a C++ exception, such as one from Ogre when the factory
    // loads an item, so one failed action does not end the game
    try {
      if (act.type == ACT_NOTIFY) {
        world->showPlayerAMessage(act.message, true);
        continue;
      }
      Character *npc = act.actor.getCharacter();
      if (npc)
        RunAction(world, act, npc, act.target.getCharacter());
    } catch (...) {
      Log(LOG_ERROR, "ACTION: Exception during action index " + ToString((int)i));
    }
  }
}
