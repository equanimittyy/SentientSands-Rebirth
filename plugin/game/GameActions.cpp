#include "GameActions.h"
#include "Context.h"
#include "../core/Globals.h"
#include "../core/Utils.h"
#include <algorithm>
#include <core/Functions.h>
#include <kenshi/AI/Blackboard.h>
#include <kenshi/Character.h>
#include <kenshi/Dialogue.h>
#include <kenshi/Faction.h>
#include <kenshi/GameData.h>
#include <kenshi/GameWorld.h>
#include <kenshi/Inventory.h>
#include <kenshi/Item.h>
#include <kenshi/Platoon.h>
#include <kenshi/PlayerInterface.h>
#include <kenshi/RootObjectFactory.h>
#include <kenshi/SensoryData.h>
#include <kenshi/Town.h>
#include <kenshi/util/YesNoMaybe.h>
#include <kenshi/util/hand.h>
#include <ogre/OgreColourValue.h>
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

// Moves at most count of the stack, so a deal for 2 Bread never hands over a
// whole stack of 10. Returns how many moved.
static int MoveItems(Character *holder, Item *item, int count,
                     Character *receiver) {
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
  if (!receiver->giveItem(detached, true, false)) {
    holder->giveItem(detached, true, false);
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
  GameData *first = nullptr;
  boost::unordered::unordered_map<std::string, GameData *>::iterator it;
  for (it = world->gamedata.gamedataSID.begin();
       it != world->gamedata.gamedataSID.end(); ++it) {
    GameData *check = it->second;
    if (!check || (gradeType && check->type != gradeType))
      continue;
    if (check->name.find("Standard") != std::string::npos ||
        check->name.find("Catun") != std::string::npos)
      return check;
    if (!first)
      first = check;
  }
  return first;
}

static hand g_newestBubble;
static hand g_previousBubble;

static void KeepTwoBubbles(const hand &speaker) {
  if (speaker == g_newestBubble)
    return;
  Character *dropped =
      g_previousBubble.isValid() && !(speaker == g_previousBubble)
          ? g_previousBubble.getCharacter()
          : nullptr;
  if (dropped && dropped->dialogue && (uintptr_t)dropped->dialogue > 0x1000 &&
      dropped->dialogue->speechTextTimer > 0.0f) {
    // clearSpeechBox is private, so the engine hides the bubble when this
    // timer runs out on its next update
    dropped->dialogue->speechTextTimer = 0.001f;
    dropped->dialogue->speechTextTimer_forced = 0.001f;
  }
  g_previousBubble = g_newestBubble;
  g_newestBubble = speaker;
}

static bool IsLockedUp(Character *c) {
  return c->inSomething == IN_PRISON || c->isChained || c->isChainedMode();
}

static void FreePrisoner(GameWorld *world, Character *target) {
  if (target->isChained || target->isChainedMode()) {
    target->setChainedMode(false, hand());
    target->isChained = false;
  }
  if (target->inSomething == IN_PRISON) {
    target->setPrisonMode(false, nullptr);
    // setPrisonMode may not reset inSomething, so clear it directly
    target->inSomething = IN_NOTHING;
  }
  world->showPlayerAMessage("You have been freed!", true);
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

struct PendingRelease {
  unsigned int key; // A key outlives the new handle of a squad change
  DWORD waited;
};
static std::vector<PendingRelease> g_releases;

void WatchReleases(GameWorld *world) {
  static DWORD last = GetTickCount();
  DWORD step = UnpausedStep(world, last);
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
                      " locked up, so the plugin frees it");
    FreePrisoner(world, target);
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

void WatchFights(GameWorld *world) {
  static DWORD last = GetTickCount();
  DWORD step = UnpausedStep(world, last);
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

struct PendingTreatment {
  unsigned int key;
  DWORD waited;
};
static std::vector<PendingTreatment> g_treatments;

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
  PendingTreatment check = {HandleKey(medic), 0};
  g_treatments.push_back(check);
  return medic->getName() + " is treating " + patient->getName() + ".";
}

void WatchTreatments(GameWorld *world) {
  static DWORD last = GetTickCount();
  DWORD step = UnpausedStep(world, last);
  for (size_t i = 0; i < g_treatments.size();) {
    g_treatments[i].waited += step;
    if (g_treatments[i].waited < TREATMENT_CHECK_MS) {
      ++i;
      continue;
    }
    Character *medic = KeyedCharacter(g_treatments[i].key);
    if (medic) {
      std::string line = "FIRSTAID_PROBE: name='" + medic->getName() +
                         "' after=" +
                         ToString((int)(TREATMENT_CHECK_MS / 1000)) + "s";
      try {
        line += OrdersLine(medic);
      } catch (...) {
        line += " [tasks failed]";
      }
      Log(LOG_DEBUG, line);
    }
    g_treatments.erase(g_treatments.begin() + i);
  }
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

void ExecuteQueuedActions(GameWorld *thisptr) {
  std::deque<QueuedAction> localQueue;
  if (TryEnterCriticalSection(&g_uiMutex)) {
    localQueue = g_uiActionQueue;
    g_uiActionQueue.clear();
    LeaveCriticalSection(&g_uiMutex);
  }

  for (size_t actIdx = 0; actIdx < localQueue.size(); ++actIdx) {
    try {
      const QueuedAction &act = localQueue[actIdx];
      Character *npc = act.actor.getCharacter();
      Character *target = act.target.getCharacter();

      if (act.type == ACT_NOTIFY) {
        thisptr->showPlayerAMessage(act.message, true);
      } else if (act.type == ACT_SAY && npc) {
        bool isPC = npc->isPlayerCharacter();
        Log(LOG_DEBUG, "ACTION: SAY [" + npc->getName() + "]: " + act.message +
            (isPC ? " (PC)" : " (NPC)"));
        KeepTwoBubbles(act.actor);
        if (!g_shortPayers.empty())
          g_shortPayers.erase(HandleKey(npc));
        try {
          // No endDialogue/setInDialog(false): they clear AI goals, killing the task just queued
          npc->sayALine(act.message, true);

          // Scaled by game speed, else bubbles vanish too fast at high speeds.
          // Both timers are set so the engine honors the duration.
          if (npc->dialogue && (uintptr_t)npc->dialogue > 0x1000) {
            float speed = thisptr->getFrameSpeedMultiplier();
            if (speed < 1.0f)
              speed = 1.0f;
            float duration = g_speechBubbleLife * speed;
            npc->dialogue->speechTextTimer = duration;
            npc->dialogue->speechTextTimer_forced = duration;
          } else {
            npc->say(act.message);
          }

        } catch (...) {
          Log(LOG_ERROR, "ACTION: SAY: Exception during sayALine/say");
        }
      } else if (npc) {
        if (act.type == ACT_ATTACK && target) {
          StartFight(npc, target);
          npc->attackTarget(target);
          npc->addGoal(MELEE_ATTACK, (RootObjectBase *)target);
          npc->reThinkCurrentAIAction();
          thisptr->showPlayerAMessage(npc->getName() + " is attacking!", false);
        } else if (act.type == ACT_JOIN_PARTY && thisptr->player) {
          // A hired follower joins for good, so its contract must not run out
          Blackboard *board = npc->getBlackboard();
          if (board && (uintptr_t)board > 0x1000 && board->hasContractJob())
            board->endContractJob();
          thisptr->player->recruit(npc, false);
          thisptr->playNotification("ui_cat_change");
          thisptr->showPlayerAMessage_withLog(
              npc->getName() + " joined your squad.", true);
        } else if (act.type == ACT_SET_TASK) {
          Log(LOG_INFO, "ACTION: Setting task for " + npc->getName() + ": " +
              ToString(act.taskValue));

          // No endDialogue here: it kills the speech bubble the NPC just displayed

          // Passive/Hold standing orders can block the new task
          npc->setStandingOrder((MessageForB::StandingOrder)13 /* PASSIVE */,
                                false);
          npc->setStandingOrder((MessageForB::StandingOrder)12 /* HOLD */,
                                false);

          npc->clearAllAIGoals();

          TaskType tt = (TaskType)act.taskValue;
          RootObject *taskTarget = NULL;

          if (!act.message.empty()) {
            std::string tName = Trim(act.message, " \t\r\n\"'");

            Log(LOG_DEBUG, "ACTION: Resolving town target for " + ToString(tt) +
                ": '" + tName + "'");

            TownBase *town = FindTown(tName);
            taskTarget = town;
            if (town)
              Log(LOG_DEBUG, "ACTION: Found town match: " + town->getName());
            else
              Log(LOG_WARN, "ACTION: Town '" + tName + "' not found!");
          }

          Log(LOG_DEBUG,
              "ACTION: Final Dispatch -> Task: " + ToString((int)tt) +
                  " (" + TaskName(tt) + "), Target: " +
                  (taskTarget ? ((RootObjectBase *)taskTarget)->getName()
                              : "NULL"));

          npc->addJob(tt, taskTarget, false, true, npc->getPosition());
          thisptr->showPlayerAMessage(
              npc->getName() + " is now executing: " + TaskName(tt), false);

          npc->addGoal(tt, (RootObjectBase *)taskTarget);
          npc->reThinkCurrentAIAction();
        } else if (act.type == ACT_TAKE_ITEM) {
          Character *player = target ? target : FirstPlayerCharacter();
          if (player) {
            std::string targetName = Trim(act.message, " \t\r\n\"'");
            std::string lowerTarget = Lower(targetName);

            int count = act.taskValue;
            if (count < 1)
              count = 1;
            int taken = 0;

            Log(LOG_INFO,
                "ACTION: NPC " + npc->getName() + " attempting to take " +
                    ToString(count) + "x '" + targetName + "'");

            // Rescan per stack: removals reorder the inventory
            while (taken < count) {
              Item *found = FindNamedItem(player, lowerTarget);
              if (!found)
                break;
              int moved = MoveItems(player, found, count - taken, npc);
              if (moved == 0) {
                Log(LOG_WARN, "ACTION: NPC " + npc->getName() +
                                  " could not take " + found->getName() + ".");
                break;
              }
              taken += moved;
            }

            if (taken < count) {
              g_shortPayers.insert(HandleKey(npc));
              Log(LOG_WARN, "ACTION: Transaction failed: " + npc->getName() + " wanted " + ToString(count) + " but only found " + ToString(taken));
            }

            if (taken > 0) {
              std::string msg = npc->getName() + " took " +
                                (taken > 1 ? ToString(taken) + "x " : "") +
                                targetName + " from you.";
              thisptr->showPlayerAMessage_withLog(msg, true);
              npc->reThinkCurrentAIAction();
            } else {
              Log(LOG_WARN, "ACTION: NPC " + npc->getName() +
                  " found NO items matching '" + targetName + "' on player.");
            }
          }
        } else if (act.type == ACT_GIVE_ITEM || act.type == ACT_SELL_ITEM) {
          if (HeldBack(npc, act.type == ACT_SELL_ITEM ? "SELL_ITEM" : "GIVE_ITEM"))
            continue;
          std::string originalTargetName = Trim(act.message, " \t\r\n\"'");
          std::string targetName = Lower(originalTargetName);

          int count = act.taskValue;
          if (count < 1)
            count = 1;
          int given = 0;

          Character *player = target ? target : FirstPlayerCharacter();
          if (player) {
            while (given < count) {
              // A trader in a shop sells its stock and keeps what it carries
              Item *found = act.type == ACT_SELL_ITEM
                                ? FindStockItem(npc, targetName)
                                : FindNamedItem(npc, targetName, true);
              if (!found)
                break;
              int moved = MoveItems(npc, found, count - given, player);
              if (moved == 0) {
                Log(LOG_WARN, "ACTION: Failed to detach " + found->getName() +
                                  " from " + npc->getName() + "'s inventory.");
                break;
              }
              Log(LOG_DEBUG, "ACTION: Gave " + ToString(moved) + "x " +
                                 found->getName());
              given += moved;
            }

            if (given < count)
              Log(LOG_WARN, "ACTION: NPC " + npc->getName() + " only had " +
                                ToString(given) + " of " + ToString(count) +
                                "x '" + originalTargetName + "'");

            if (given > 0) {
              std::string msg =
                  npc->getName() + " gave you " +
                  (given > 1 ? ToString(given) + "x " : "") +
                  originalTargetName;
              thisptr->showPlayerAMessage_withLog(msg, true);
              npc->reThinkCurrentAIAction();
            }
          }
        } else if (act.type == ACT_GIVE_CATS) {
          if (HeldBack(npc, "GIVE_CATS"))
            continue;
          Character *payee = FirstPlayerCharacter();
          if (payee) {
            int amt = act.taskValue;
            if (amt > 0) {
              payee->takeMoney(-amt);

              // Skip player-faction characters: the transfer would be a no-op
              if (!InPlayerFaction(npc))
                npc->takeMoney(amt);

              thisptr->showPlayerAMessage_withLog(
                  "Gained " + ToString(amt) + " cats.", true);
            }
          }
        } else if (act.type == ACT_TAKE_CATS) {
          Character *p = FirstPlayerCharacter();
          if (p) {
            int targetAmt = act.taskValue;
            int pMoney = MoneyOf(p);

            int amt = targetAmt;
            bool fellShort = amt > pMoney;
            if (fellShort) {
              amt = pMoney;
              g_shortPayers.insert(HandleKey(npc));
            }
            if (amt < 1) {
              amt = 0;
            }

            Log(LOG_INFO, "ACTION: Taking " + ToString(amt) +
                              " cats from the player (Requested: " +
                              ToString(targetAmt) +
                              ", Bank: " + ToString(pMoney) + ")");
            p->takeMoney(amt);

            // Don't pay a recruit from this batch: the fee would land back in the player's pocket
            bool beingRecruited = false;
            for (size_t i = 0; i < localQueue.size(); ++i) {
              if (localQueue[i].type == ACT_JOIN_PARTY &&
                  localQueue[i].actor == act.actor) {
                beingRecruited = true;
                break;
              }
            }

            if (!beingRecruited && !InPlayerFaction(npc)) {
              npc->takeMoney(-amt);
            } else {
              Log(LOG_DEBUG,
                  "ACTION: Recruitment fee or sign-on bonus. Money spent "
                      "but not given to recruit pocket.");
            }

            thisptr->showPlayerAMessage_withLog(
                "Lost " + ToString(amt) + " cats.", true);

            if (fellShort) {
              thisptr->showPlayerAMessage(
                  npc->getName() +
                      " looks annoyed. \"That's not what we agreed on!\"",
                  true);
            }
          }
        } else if (act.type == ACT_RELEASE && target) {
          if (HeldBack(npc, "RELEASE"))
            continue;
          bool inCage = (target->inSomething == IN_PRISON);
          bool shackled = target->isChained || target->isChainedMode();
          float dist = npc->getPosition().distance(target->getPosition());

          Log(LOG_INFO,
              "ACTION: Release by " + npc->getName() + " on " +
                  target->getName() + ". InCage: " + ToString(inCage) +
                  ", Shackled: " + ToString(shackled) +
                  ", Dist: " + ToString(dist));

          // Free directly when close: for recruits/friends the engine cancels the release task
          bool freed = dist < 4.0f && (inCage || shackled);
          if (freed) {
            Log(LOG_DEBUG, "ACTION: Proximity force-release triggered.");
            FreePrisoner(thisptr, target);
          }

          bool didSomething = freed;

          if (npc->isCarryingSomething &&
              npc->carryingObject == target->getHandle()) {
            Log(LOG_DEBUG, "ACTION: NPC is carrying target. Dropping.");
            npc->dropCarriedObject(false, false);
            didSomething = true;
          }

          if ((inCage || shackled) && !freed) {
            TaskType tt = RELEASE_PRISONER;

            Log(LOG_DEBUG, "ACTION: Assigning task: " + TaskName(tt) + " (" +
                ToString((int)tt) + ")");

            // addOrder overrides at once, unlike addJob; clear=true halts background AI (staying home)
            npc->clearAllAIGoals();
            npc->addOrder(nullptr, tt, (RootObject *)target, false, true,
                          target->getPosition());
            npc->reThinkCurrentAIAction();
            PendingRelease pending = {HandleKey(target), 0};
            g_releases.push_back(pending);

            thisptr->showPlayerAMessage(
                npc->getName() + " is releasing " + target->getName() + "!",
                false);
            didSomething = true;
          }

          if (!didSomething && !npc->isPlayerCharacter()) {
            Log(LOG_DEBUG, "ACTION: Target already free. Clearing NPC goals.");
            npc->clearAllAIGoals();
            npc->reThinkCurrentAIAction();
          }
        } else if (act.type == ACT_HIRE && target) {
          if (HeldBack(npc, "HIRE"))
            continue;
          Blackboard *board = npc->getBlackboard();
          GameData *bodyguard = thisptr->gamedata.getData("5090-gamedata.base");
          if (board && (uintptr_t)board > 0x1000 && bodyguard) {
            // A renewal finds the old contract still running, and
            // _setContractJob is tested only on an NPC without a contract
            if (board->hasContractJob())
              board->endContractJob();
            // The game's hire dialogues give the Bodyguard package with hours
            board->_setContractJob(bodyguard, act.taskValue, target->getHandle());
            thisptr->showPlayerAMessage_withLog(
                npc->getName() + " follows you for " + ToString(act.taskValue) +
                    " hours.",
                true);
          }
        } else if (act.type == ACT_ADD_CATS) {
          // Charity costs the NPC nothing, so the cats come from no purse
          Character *payee = FirstPlayerCharacter();
          if (payee && act.taskValue > 0) {
            payee->takeMoney(-act.taskValue);
            thisptr->showPlayerAMessage_withLog(
                "Gained " + ToString(act.taskValue) + " cats.", true);
          }
        } else if (act.type == ACT_END_HIRE) {
          Blackboard *board = npc->getBlackboard();
          if (board && (uintptr_t)board > 0x1000 && board->hasContractJob()) {
            board->endContractJob();
            thisptr->showPlayerAMessage_withLog(
                npc->getName() + " no longer follows you.", true);
          }
        } else if (act.type == ACT_FIRST_AID && target) {
          if (HeldBack(npc, "FIRST_AID"))
            continue;
          bool firstAid, repair;
          std::string message = StartTreatment(npc, target, firstAid, repair);
          Log(LOG_DEBUG, "ACTION: " + message + " first_aid_order=" +
                             (firstAid ? "1" : "0") +
                             " repair_order=" + (repair ? "1" : "0"));
          thisptr->showPlayerAMessage(message, false);
        } else if (act.type == ACT_PROBE) {
          RunProbe(npc, target, act.message);
        } else if (act.type == ACT_SPAWN_ITEM) {
          // "<record name>|<label>": the Cheats window also names its record,
          // and the server names only the food of a charity
          size_t pipe = act.message.find('|');
          std::string templateName = act.message.substr(0, pipe);
          std::string label = pipe == std::string::npos
                                  ? std::string()
                                  : act.message.substr(pipe + 1);
          GameData *gd = act.itemData ? act.itemData
                                      : FindItemData(thisptr, templateName);
          if (!gd) {
            Log(LOG_WARN,
                "ACTION: Could not find template for: " + templateName);
            thisptr->showPlayerAMessage(
                "Error: Item template '" + templateName + "' not found.", true);
            continue;
          }
          Character *p = target ? target : FirstPlayerCharacter();
          if (!p) {
            Log(LOG_WARN, "ACTION: No character found to give item to.");
            continue;
          }
          GameData *gradeData =
              act.itemModel ? act.itemModel : GearGrade(thisptr, gd);
          int count = act.taskValue < 1 ? 1 : act.taskValue;
          int spawnedCount = 0;
          for (int c = 0; c < count; c++) {
            Item *item =
                CreateItem(thisptr, gd, act.itemMaker, gradeData, act.itemLevel);
            if (!item) {
              Log(LOG_ERROR, "ACTION: Resolved " + gd->name +
                                 " but Factory failed to createItem! (Grade: " +
                                 (gradeData ? gradeData->name : "NULL") +
                                 ", Maker: " +
                                 (act.itemMaker ? act.itemMaker->name : "NULL") +
                                 ")");
              continue;
            }
            item->quantity = 1;
            item->quality = 1.0f;
            item->chargesLeft = item->originalFullChargeAmount;
            if (item->chargesLeft <= 0.0f)
              item->chargesLeft = 1.0f;

            item->setProperOwner(p->getHandle());
            item->visible = true;
            item->isTradeItem = true;

            if (!item->container && p->container) {
              item->container = p->container;
              p->container->addActiveObject(item);
            }

            if (p->giveItem(item, true, false)) {
              spawnedCount++;
              Log(LOG_INFO, "ACTION: Successfully spawned and gave " +
                                gd->name + " to " + p->getName());
            } else {
              Log(LOG_WARN, "ACTION: Resolved " + gd->name +
                                " but giveItem failed (inventory full?) for " +
                                p->getName());
            }
          }

          if (spawnedCount > 0) {
            if (p->getInventory()) {
              p->getInventory()->autoArrange();
              p->getInventory()->refreshGui();
            }
            thisptr->addPortraitUpdate(p->getHandle());
            thisptr->showPlayerAMessage_withLog(
                "Received " +
                    (spawnedCount > 1 ? ToString(spawnedCount) + "x " : "") +
                    (label.empty() ? gd->name : label),
                true);
          }
        }
      }
    } catch (...) {
      Log(LOG_ERROR, "ACTION: Exception during action index " +
          ToString((int)actIdx));
    }
  }
}
