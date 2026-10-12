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
#include <vector>

void PerformLeaveSquad(Character *npc, GameWorld *world,
                       const std::string &originFaction) {
  if (!npc || !world)
    return;

  std::string factionPart = originFaction;
  std::string platoonPart = "";
  size_t pipePos = originFaction.find('|');
  if (pipePos != std::string::npos) {
    factionPart = originFaction.substr(0, pipePos);
    platoonPart = originFaction.substr(pipePos + 1);
  }

  Log(LOG_INFO, "ACTION: Dismissing " + npc->getName() + " (Target Faction: " +
      factionPart + ", Target Platoon: " + platoonPart + ")");

  if (world->player) {
    world->player->unselectPlayerCharacter(npc);
    lektor<Character *> &pc = world->player->playerCharacters;
    for (uint32_t i = 0; i < pc.size(); ++i) {
      if (pc.stuff[i] == npc) {
        for (uint32_t j = i; j < pc.size() - 1; ++j)
          pc.stuff[j] = pc.stuff[j + 1];
        pc.count--;
        Log(LOG_DEBUG, "ACTION: Removed " + npc->getName() +
            " from playerCharacters list.");
        break;
      }
    }
  }

  if (world->factionMgr) {
    FactionManager *fm = world->factionMgr;

    Faction *namedFaction = NULL;
    if (!factionPart.empty() && factionPart != "Unknown")
      namedFaction = fm->getFactionByName(factionPart);
    // A profile made after recruitment names the player's own faction
    bool useNamedFaction = namedFaction && !namedFaction->isThePlayer();

    std::string targetFactionName = "Drifters";
    if (useNamedFaction) {
      targetFactionName = factionPart;
    } else if (g_originFactions.count(GetNpcId(npc))) {
      targetFactionName = g_originFactions[GetNpcId(npc)];
    }

    Faction *targetFaction = fm->getFactionByName(targetFactionName);

    if ((!useNamedFaction || targetFactionName == "Drifters") &&
        npc->getGameData()) {
      GameData *characterData = npc->getGameData();
      const Ogre::vector<GameDataReference>::type *refs =
          characterData->getReferenceListIfExists("faction");
      if (refs && !refs->empty()) {
        Faction *refFaction = fm->getFactionByStringID(refs->at(0).sid);
        if (refFaction && !refFaction->isThePlayer()) {
          targetFaction = refFaction;
          targetFactionName = targetFaction->getName();
        }
      }
    }

    if (!targetFaction || targetFaction->isThePlayer() ||
        targetFaction->isNotARealFaction()) {
      targetFactionName = "Drifters";
      targetFaction = fm->getFactionByName("Drifters");
    }

    if (!targetFaction || targetFaction->isThePlayer()) {
      targetFaction = NULL;
      const lektor<Faction *> *all = fm->getAllFactions();
      if (all) {
        for (uint32_t i = 0; i < all->count; ++i) {
          Faction *f = all->stuff[i];
          if (f && !f->isThePlayer() && !f->isNotARealFaction()) {
            targetFaction = f;
            if (f->getName() == targetFactionName)
              break;
          }
        }
      }
    }

    if (targetFaction) {
      Log(LOG_DEBUG, "ACTION: Moving character to target faction: " +
          targetFaction->getName());

      ActivePlatoon *ap = NULL;

      if (!platoonPart.empty()) {
        const lektor<Platoon *> *activePlats =
            targetFaction->getActivePlatoons();
        if (activePlats) {
          for (uint32_t i = 0; i < activePlats->count; ++i) {
            Platoon *p = activePlats->stuff[i];
            if (p && (p->stringID == platoonPart ||
                      p->getPlatoonStringID() == platoonPart)) {
              ap = p->getActivePlatoon();
              if (ap) {
                Log(LOG_DEBUG, "ACTION: Found existing active platoon: " +
                    platoonPart);
                break;
              }
            }
          }
        }
      }

      if (!ap) {
        Platoon *newPlat = targetFaction->createNewEmptyActivePlatoon(
            NULL, true, npc->getPosition());
        if (newPlat) {
          ap = newPlat->getActivePlatoon();
          Log(LOG_DEBUG, "ACTION: Created new platoon for dismissal.");
        }
      }

      if (ap) {
        npc->setFaction(targetFaction, ap);

        if (ap->getSquadSize() == 1 || !ap->getSquadLeader()) {
          ap->setSquadLeader(npc);
        }

        // Squad members run on player AI; reinstall the NPC AI
        npc->setupAI();
        npc->setupPlatoonAI();

        // Recruits often lose their home town, so adopt the current one
        TownBase *currentTown = npc->getCurrentTownLocation();
        if (currentTown) {
          Ownerships *own = npc->getOwnerships();
          if (own)
            own->setHomeTown(currentTown, SQ_RESIDENT);
        }

        npc->reThinkCurrentAIAction();
      } else {
        Log(LOG_ERROR, "ACTION: Could not create or find a platoon for "
            "dismissal!");
      }
    }
  }
}

std::string GetTaskName(TaskType tt) {
  switch ((int)tt) {
  case 1:
    return "MOVE_ON_FREE_WILL";
  case 4:
    return "MELEE_ATTACK";
  case 14:
    return "IDLE";
  case 15:
    return "WANDER_TOWN";
  case 18:
    return "RAID_TOWN";
  case 19:
    return "GO_HOMEBUILDING";
  case 20:
    return "STAND_AT_SHOPKEEPER_NODE";
  case 23:
    return "ATTACK_TOWN";
  case 24:
    return "WANDERER";
  case 35:
    return "RUN_AWAY";
  case 36:
    return "PATROL_TOWN";
  case 44:
    return "FOLLOW_PLAYER_ORDER";
  case 46:
    return "CHASE";
  case 53:
    return "TRAVEL_TO_TARGET_TOWN";
  case 55:
    return "BODYGUARD";
  case 57:
    return "JOB_REPAIR_ROBOT";
  case 58:
    return "JOB_MEDIC";
  case 67:
    return "MOVE_ON_FREE_WILL_FAST";
  case 105:
    return "FIND_AND_RESCUE";
  case 110:
    return "RELEASE_PRISONER";
  case 111:
    return "BREAKOUT_PRISONER";
  case 185:
    return "CUT_SHACKLES";
  case 201:
    return "PICK_LOCK_ON_SHACKLES";
  default:
    return "TASK_" + ToString((int)tt);
  }
}

static std::string LowerText(std::string text) {
  std::transform(text.begin(), text.end(), text.begin(), ::tolower);
  return text;
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
    if (LowerText(ItemLabel(items[i])) == lowerName)
      return items[i];
    std::string name = LowerText(items[i]->getName());
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
// the weapon first makes it return null. The player's own manufacturer would
// mark a picked weapon as homemade.
static Item *CreateItem(GameWorld *world, GameData *data, GameData *maker,
                        GameData *grade, int level) {
  if (data->type != WEAPON)
    return world->theFactory->createItem(data, hand(), NULL, grade, level,
                                         NULL);
  if (!grade) {
    boost::unordered::unordered_map<std::string, GameData *>::iterator it;
    for (it = world->gamedata.gamedataSID.begin();
         it != world->gamedata.gamedataSID.end(); ++it) {
      GameData *check = it->second;
      if (!check || check->type != WEAPON_MANUFACTURER ||
          check->stringID == "PLAYER_WEAPONS")
        continue;
      const Ogre::vector<GameDataReference>::type *weapons =
          check->getReferenceListIfExists("weapon types");
      const Ogre::vector<GameDataReference>::type *models =
          check->getReferenceListIfExists("weapon models");
      if (!weapons || !models)
        continue;
      bool makes = false;
      for (size_t w = 0; !makes && w < weapons->size(); ++w)
        makes = weapons->at(w).sid == data->stringID;
      for (size_t m = 0; makes && m < models->size(); ++m) {
        GameData *model = world->gamedata.getData(models->at(m).sid);
        int modelLevel = models->at(m).values.value[0];
        if (model && modelLevel >= 1 && (!grade || modelLevel < level)) {
          maker = check;
          grade = model;
          level = modelLevel;
        }
      }
    }
    if (!grade) {
      Log(LOG_WARN, "ACTION: No manufacturer makes " + data->name);
      return NULL;
    }
    Log(LOG_DEBUG, "ACTION: Picked grade " + grade->name + " by " +
                       maker->name + " for " + data->name);
  }
  return world->theFactory->createItem(maker, hand(), data, grade, level,
                                       NULL);
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
  return medic->getName() + " is treating " + patient->getName() + ".";
}

void ExecuteQueuedActions(GameWorld *thisptr, int &inventoryTimer) {
  std::deque<QueuedAction> localQueue;
  if (TryEnterCriticalSection(&g_uiMutex)) {
    localQueue = g_uiActionQueue;
    g_uiActionQueue.clear();
    LeaveCriticalSection(&g_uiMutex);
  }

  bool transactionFailed = false;
  std::string failureReason = "";

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
          if (npc->getFaction() && npc->getFaction()->isThePlayer()) {
            PerformLeaveSquad(npc, thisptr, "");
            npc->clearAllAIGoals();
          }
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
            std::string tName = act.message;
            size_t fnot = tName.find_first_not_of(" \t\n\r\"'");
            if (fnot != std::string::npos) {
              tName.erase(0, fnot);
              size_t lnot = tName.find_last_not_of(" \t\n\r\"'");
              if (lnot != std::string::npos)
                tName.erase(lnot + 1);
            }

            Log(LOG_DEBUG, "ACTION: Resolving town target for " + ToString(tt) +
                ": '" + tName + "'");

            std::string tLow = tName;
            std::transform(tLow.begin(), tLow.end(), tLow.begin(), ::tolower);

            lektor<RootObject *> resultTowns;
            (*ppWorld)->getObjectsWithinSphere(resultTowns, npc->getPosition(),
                                               10000000.0f, TOWN, 500, NULL);
            for (uint32_t i = 0; i < resultTowns.size(); ++i) {
              TownBase *tb = (TownBase *)resultTowns[i];
              if (tb) {
                std::string tbName = ((RootObjectBase *)tb)->getName();
                std::transform(tbName.begin(), tbName.end(), tbName.begin(),
                               ::tolower);

                if (tbName == tLow || tbName.find(tLow) != std::string::npos) {
                  taskTarget = (RootObject *)tb;
                  Log(LOG_DEBUG, "ACTION: Found town match: " +
                      ((RootObjectBase *)tb)->getName());
                  break;
                }
              }
            }
            if (!taskTarget) {
              Log(LOG_WARN, "ACTION: Town '" + tName +
                  "' not found in 10M units!");
            }
          }

          if (tt == ATTACK_TOWN && !taskTarget) {
            TownBase *town = npc->getCurrentTownLocation();
            if (town)
              taskTarget = (RootObject *)town;
          }

          Log(LOG_DEBUG,
              "ACTION: Final Dispatch -> Task: " + ToString((int)tt) +
                  " (" + GetTaskName(tt) + "), Target: " +
                  (taskTarget ? ((RootObjectBase *)taskTarget)->getName()
                              : "NULL"));

          npc->addJob(tt, taskTarget, false, true, npc->getPosition());
          thisptr->showPlayerAMessage(
              npc->getName() + " is now executing: " + GetTaskName(tt), false);

          npc->addGoal(tt, (RootObjectBase *)taskTarget);
          npc->reThinkCurrentAIAction();
        } else if (act.type == ACT_TAKE_ITEM) {
          Character *player =
              target ? target
                     : (thisptr->player &&
                                thisptr->player->playerCharacters.size() > 0
                            ? thisptr->player->playerCharacters[0]
                            : nullptr);
          if (player) {
            std::string targetName = act.message;
            size_t fnot = targetName.find_first_not_of(" \t\n\r\"'");
            if (fnot != std::string::npos) {
              targetName.erase(0, fnot);
              size_t lnot = targetName.find_last_not_of(" \t\n\r\"'");
              if (lnot != std::string::npos)
                targetName.erase(lnot + 1);
            }
            std::string lowerTarget = targetName;
            std::transform(lowerTarget.begin(), lowerTarget.end(),
                           lowerTarget.begin(), ::tolower);

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
              transactionFailed = true;
              failureReason = "Not enough items.";
              Log(LOG_WARN, "ACTION: Transaction failed: " + npc->getName() + " wanted " + ToString(count) + " but only found " + ToString(taken));
            }

            if (taken > 0) {
              std::string msg = npc->getName() + " took " +
                                (taken > 1 ? ToString(taken) + "x " : "") +
                                targetName + " from you.";
              thisptr->showPlayerAMessage_withLog(msg, true);
              npc->reThinkCurrentAIAction();
              inventoryTimer = 999;
            } else {
              Log(LOG_WARN, "ACTION: NPC " + npc->getName() +
                  " found NO items matching '" + targetName + "' on player.");
            }
          }
        } else if (act.type == ACT_GIVE_ITEM || act.type == ACT_SELL_ITEM) {
          if (transactionFailed) {
            Log(LOG_INFO, "ACTION: Skipping GIVE_ITEM due to previous transaction failure (" + failureReason + ")");
            continue;
          }
          std::string targetName = act.message;
          size_t fnot = targetName.find_first_not_of(" \t\n\r\"'");
          if (fnot != std::string::npos) {
            targetName.erase(0, fnot);
            size_t lnot = targetName.find_last_not_of(" \t\n\r\"'");
            if (lnot != std::string::npos)
              targetName.erase(lnot + 1);
          }
          std::string originalTargetName = targetName;
          std::transform(targetName.begin(), targetName.end(),
                         targetName.begin(), ::tolower);

          int count = act.taskValue;
          if (count < 1)
            count = 1;
          int given = 0;

          Character *player =
              target ? target
                     : (thisptr->player &&
                                thisptr->player->playerCharacters.size() > 0
                            ? thisptr->player->playerCharacters[0]
                            : nullptr);

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

            if (given < count) {
              Log(LOG_WARN, "ACTION: NPC " + npc->getName() + " only had " +
                  ToString(given) + " of '" + originalTargetName +
                  "'. Fallback to SPAWN for remaining " +
                  ToString(count - given));
              itemType types[] = {ITEM,     WEAPON,    ARMOUR,
                                  CROSSBOW, BLUEPRINT, LIMB_REPLACEMENT,
                                  MAP_ITEM};
              GameData *gd = nullptr;
              for (int t = 0; t < 7; t++) {
                gd = thisptr->leveldata.getDataByName(originalTargetName,
                                                      types[t]);
                if (!gd)
                  gd = thisptr->gamedata.getDataByName(originalTargetName,
                                                       types[t]);
                if (gd)
                  break;
              }

              if (gd) {
                int toSpawn = count - given;
                for (int s = 0; s < toSpawn; s++) {
                  std::string uniqueID =
                      originalTargetName + "_AI_" +
                      ToString((unsigned int)GetTickCount()) + "_" +
                      ToString(s);
                  GameData *newGd = thisptr->savedata.createNewData(
                      gd->type, uniqueID, gd->name);
                  if (newGd) {
                    newGd->updateFrom(gd, true);
                    Item *spawned = CreateItem(thisptr, gd, NULL, NULL, 0);
                    if (spawned) {
                      spawned->quantity = 1;
                      spawned->setProperOwner(player->getHandle());
                      bool success = player->giveItem(spawned, true, false);
                      if (success)
                        given++;
                    }
                  }
                }
              }
            }

            if (given > 0) {
              std::string msg =
                  npc->getName() + " gave you " +
                  (given > 1 ? ToString(given) + "x " : "") +
                  originalTargetName;
              thisptr->showPlayerAMessage_withLog(msg, true);
              npc->reThinkCurrentAIAction();
              inventoryTimer = 999;
            }
          }
        } else if (act.type == ACT_GIVE_CATS) {
          if (transactionFailed) {
            Log(LOG_INFO, "ACTION: Skipping GIVE_CATS due to previous transaction failure (" + failureReason + ")");
            continue;
          }
          if (thisptr->player &&
                   thisptr->player->playerCharacters.size() > 0) {
            int amt = act.taskValue;
            if (amt > 0) {
              thisptr->player->playerCharacters[0]->takeMoney(-amt);

              // Skip player-faction characters: the transfer would be a no-op
              bool alreadyPlayer =
                  (npc->getFaction() && npc->getFaction()->isThePlayer());
              if (!alreadyPlayer)
                npc->takeMoney(amt);

              thisptr->showPlayerAMessage_withLog(
                  "Gained " + ToString(amt) + " cats.", true);
            }
          }
        } else if (act.type == ACT_TAKE_CATS) {
          Character *p =
              (thisptr->player && thisptr->player->playerCharacters.size() > 0)
                  ? thisptr->player->playerCharacters[0]
                  : nullptr;
          if (p) {
            int targetAmt = act.taskValue;
            int pMoney = p->getMoney();
            if (pMoney <= 0 && p->getOwnerships())
              pMoney = p->getOwnerships()->getMoney();

            int amt = targetAmt;
            if (amt > pMoney) {
              amt = pMoney;
              transactionFailed = true;
              failureReason = "Not enough cats.";
            }
            if (amt < 1) {
              amt = 0;
            }

            Log(LOG_INFO, "ACTION: Taking " + ToString(amt) + " cats from " +
                p->getName() + " (Requested: " + ToString(targetAmt) +
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

            bool alreadyPlayer =
                (npc->getFaction() && npc->getFaction()->isThePlayer());

            if (!beingRecruited && !alreadyPlayer) {
              npc->takeMoney(-amt);
            } else {
              Log(LOG_DEBUG,
                  "ACTION: Recruitment fee or sign-on bonus. Money spent "
                      "but not given to recruit pocket.");
            }

            thisptr->showPlayerAMessage_withLog(
                "Lost " + ToString(amt) + " cats.", true);

            if (transactionFailed) {
              thisptr->showPlayerAMessage(
                  npc->getName() +
                      " looks annoyed. \"That's not what we agreed on!\"",
                  true);
            }
          }
        } else if (act.type == ACT_RELEASE && target) {
          // IN_PRISON is enum value 2
          bool inCage = (target->inSomething == 2);
          bool shackled = target->isChained || target->isChainedMode();
          float dist = npc->getPosition().distance(target->getPosition());

          Log(LOG_INFO,
              "ACTION: Release/Breakout by " + npc->getName() + " on " +
                  target->getName() + ". InCage: " + ToString(inCage) +
                  ", Shackled: " + ToString(shackled) +
                  ", Dist: " + ToString(dist));

          // Free directly when close: for recruits/friends the engine cancels the release task
          if (dist < 4.0f && (inCage || shackled)) {
            Log(LOG_DEBUG, "ACTION: Proximity force-release triggered.");
            FreePrisoner(thisptr, target);
          }

          bool didSomething = false;

          if (npc->isCarryingSomething &&
              npc->carryingObject == target->getHandle()) {
            Log(LOG_DEBUG, "ACTION: NPC is carrying target. Dropping.");
            npc->dropCarriedObject(false, false);
            didSomething = true;
          }

          if (inCage || shackled) {
            TaskType tt = RELEASE_PRISONER; // 110
            if (act.taskValue == 111) {
              tt = BREAKOUT_PRISONER; // 111
              if (shackled && !inCage)
                tt = (TaskType)201; // PICK_LOCK_ON_SHACKLES
            }

            Log(LOG_DEBUG, "ACTION: Assigning task: " + GetTaskName(tt) + " (" +
                ToString((int)tt) + ")");

            // addOrder overrides at once, unlike addJob; clear=true halts background AI (staying home)
            npc->clearAllAIGoals();
            npc->addOrder(nullptr, tt, (RootObject *)target, false, true,
                          target->getPosition());
            npc->reThinkCurrentAIAction();
            PendingRelease pending = {HandleKey(target), 0};
            g_releases.push_back(pending);

            thisptr->showPlayerAMessage(npc->getName() +
                                            (act.taskValue == 111
                                                 ? " is breaking out "
                                                 : " is releasing ") +
                                            target->getName() + "!",
                                        false);
            didSomething = true;
          }

          if (!didSomething && !npc->isPlayerCharacter()) {
            Log(LOG_DEBUG, "ACTION: Target already free. Clearing NPC goals.");
            npc->clearAllAIGoals();
            npc->reThinkCurrentAIAction();
          }
        } else if (act.type == ACT_HIRE && target) {
          Blackboard *board = npc->getBlackboard();
          GameData *bodyguard = thisptr->gamedata.getData("5090-gamedata.base");
          if (board && (uintptr_t)board > 0x1000 && bodyguard) {
            // The game's hire dialogues give the Bodyguard package with hours
            board->_setContractJob(bodyguard, act.taskValue, target->getHandle());
            thisptr->showPlayerAMessage_withLog(
                npc->getName() + " follows you for " + ToString(act.taskValue) +
                    " hours.",
                true);
          }
        } else if (act.type == ACT_ADD_CATS) {
          // Charity costs the NPC nothing, so the cats come from no purse
          if (thisptr->player && thisptr->player->playerCharacters.size() > 0 &&
              act.taskValue > 0) {
            thisptr->player->playerCharacters[0]->takeMoney(-act.taskValue);
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
          bool firstAid, repair;
          thisptr->showPlayerAMessage(
              StartTreatment(npc, target, firstAid, repair), false);
        } else if (act.type == ACT_PROBE) {
          RunProbe(npc, target, act.message);
        } else if (act.type == ACT_SPAWN_ITEM) {
          std::string payload = act.message;

          // LLM replies and test commands sometimes repeat the SPAWN_ITEM: prefix
          if (payload.find("SPAWN_ITEM:") == 0) {
            payload = payload.substr(11);
            size_t first = payload.find_first_not_of(" \t\r\n");
            if (first != std::string::npos)
              payload = payload.substr(first);
          }

          std::string templateName, itemName;
          size_t pipe1 = payload.find('|');
          if (pipe1 != std::string::npos) {
            templateName = payload.substr(0, pipe1);
            size_t pipe2 = payload.find('|', pipe1 + 1);
            if (pipe2 != std::string::npos) {
              itemName = payload.substr(pipe1 + 1, pipe2 - pipe1 - 1);
            } else {
              itemName = payload.substr(pipe1 + 1);
            }
          } else {
            templateName = payload;
          }

          auto trim = [](std::string &s) {
            size_t first = s.find_first_not_of(" \t\n\r\"'");
            if (first == std::string::npos) {
              s = "";
              return;
            }
            s.erase(0, first);
            size_t last = s.find_last_not_of(" \t\n\r\"'");
            if (last != std::string::npos)
              s.erase(last + 1);

            for (size_t i = 0; i < s.length(); ++i) {
              if (s[i] == '\r' || s[i] == '\n' || s[i] == '\t')
                s[i] = ' ';
            }
            size_t p = s.find("  ");
            while (p != std::string::npos) {
              s.erase(p, 1);
              p = s.find("  ");
            }
          };
          trim(templateName);
          trim(itemName);

          itemType types[] = {ITEM,      WEAPON,           ARMOUR,  CROSSBOW,
                              BLUEPRINT, LIMB_REPLACEMENT, MAP_ITEM};
          GameData *gd = act.itemData;

          auto findInSource = [&](GameDataManager &dm,
                                  const std::string &name) -> GameData * {
            for (int i = 0; i < 7; i++) {
              GameData *found = dm.getDataByName(name, types[i]);
              if (found)
                return found;
            }
            std::string lowerName = name;
            std::transform(lowerName.begin(), lowerName.end(),
                           lowerName.begin(), ::tolower);
            boost::unordered::unordered_map<std::string, GameData *>::iterator
                it;
            for (it = dm.gamedataSID.begin(); it != dm.gamedataSID.end();
                 ++it) {
              GameData *check = it->second;
              if (check && !check->name.empty()) {
                std::string lowerCheck = check->name;
                std::transform(lowerCheck.begin(), lowerCheck.end(),
                               lowerCheck.begin(), ::tolower);
                if (lowerCheck == lowerName) {
                  for (int t = 0; t < 7; t++) {
                    if (check->type == types[t])
                      return check;
                  }
                }
              }
            }
            return (GameData *)nullptr;
          };

          if (!gd)
            gd = findInSource(thisptr->leveldata, templateName);
          if (!gd)
            gd = findInSource(thisptr->gamedata, templateName);

          if (!gd) {
            std::string plural = templateName + "s";
            gd = findInSource(thisptr->leveldata, plural);
            if (!gd)
              gd = findInSource(thisptr->gamedata, plural);
          }

          if (!gd) {
            std::string lowerTemplate = templateName;
            std::transform(lowerTemplate.begin(), lowerTemplate.end(),
                           lowerTemplate.begin(), ::tolower);
            boost::unordered::unordered_map<std::string, GameData *>::iterator
                it;
            for (it = thisptr->gamedata.gamedataSID.begin();
                 it != thisptr->gamedata.gamedataSID.end(); ++it) {
              GameData *check = it->second;
              if (check && !check->name.empty()) {
                std::string lowerName = check->name;
                std::transform(lowerName.begin(), lowerName.end(),
                               lowerName.begin(), ::tolower);
                if (lowerName.find(lowerTemplate) != std::string::npos) {
                  for (int t = 0; t < 7; t++) {
                    if (check->type == types[t]) {
                      gd = check;
                      break;
                    }
                  }
                  if (gd)
                    break;
                }
              }
            }
          }

          if (gd) {
            Log(LOG_DEBUG,
                "ACTION: Resolved " + templateName + " to " + gd->name +
                    " (Type: " + ToString(gd->type) + ")");

            Character *p = act.target.getCharacter();
            if (!p || (uintptr_t)p < 0x1000) {
              if (thisptr->player &&
                  thisptr->player->playerCharacters.size() > 0)
                p = thisptr->player->playerCharacters[0];
            }

            if (p) {
              int count = act.taskValue;
              if (count < 1)
                count = 1;
              int spawnedCount = 0;

              for (int c = 0; c < count; c++) {
                Log(LOG_DEBUG, "ACTION: Spawning " + gd->name + " (" +
                    ToString(c + 1) + "/" + ToString(count) + ") for " +
                    p->getName());

                GameData *gradeData = act.itemModel;

                if (!gradeData &&
                    (gd->type == ARMOUR || gd->type == CROSSBOW)) {
                  auto getRef = [&](const std::string &refName) -> GameData * {
                    const Ogre::vector<GameDataReference>::type *refs =
                        gd->getReferenceListIfExists(refName);
                    if (refs && !refs->empty()) {
                      GameData *r = thisptr->gamedata.getData(refs->at(0).sid);
                      if (r) {
                        Log(LOG_DEBUG, "ACTION: Found " + refName + " ref: " +
                            r->name + " (Type: " + ToString(r->type) + ")");
                      }
                      return r;
                    }
                    return nullptr;
                  };

                  int gradeType =
                      gd->type == ARMOUR ? MATERIAL_SPECS_CLOTHING : 0;

                  gradeData = getRef("material");
                  if (!gradeData ||
                      (gradeType && gradeData->type != gradeType))
                    gradeData = getRef("model");
                  if (!gradeData ||
                      (gradeType && gradeData->type != gradeType))
                    gradeData = getRef("mesh");

                  if (!gradeData ||
                      (gradeType && gradeData->type != gradeType)) {
                    GameData *firstGrade = nullptr;
                    boost::unordered::unordered_map<std::string,
                                                    GameData *>::iterator it;

                    for (it = thisptr->gamedata.gamedataSID.begin();
                         it != thisptr->gamedata.gamedataSID.end(); ++it) {
                      GameData *check = it->second;
                      if (!check)
                        continue;

                      if (!gradeType || check->type == gradeType) {
                        if (!firstGrade)
                          firstGrade = check;
                        if (check->name.find("Standard") != std::string::npos ||
                            check->name.find("Catun") != std::string::npos) {
                          gradeData = check;
                          break;
                        }
                      }
                    }

                    if (!gradeData)
                      gradeData = firstGrade;
                  }
                }

                Item *item = CreateItem(thisptr, gd, act.itemMaker, gradeData,
                                        act.itemLevel);
                if (item) {
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

                  bool success = p->giveItem(item, true, false);
                  if (success) {
                    spawnedCount++;
                    Log(LOG_INFO, "ACTION: Successfully spawned and gave " +
                        gd->name + " to " + p->getName());
                  } else {
                    Log(LOG_WARN, "ACTION: Resolved " + gd->name +
                        " but giveItem failed (inventory full?) for " +
                        p->getName());
                  }
                } else {
                  Log(LOG_ERROR, "ACTION: Resolved " + gd->name +
                      " but Factory failed to createItem! (Grade: " +
                      (gradeData ? gradeData->name : "NULL") + ", Maker: " +
                      (act.itemMaker ? act.itemMaker->name : "NULL") + ")");
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
                        (spawnedCount > 1 ? ToString(spawnedCount) + "x "
                                          : "") +
                        (itemName.empty() ? gd->name : itemName),
                    true);
                inventoryTimer = 999;
              }
            } else {
              Log(LOG_WARN, "ACTION: No character found to give item to.");
              Ogre::Vector3 dropPos = (npc && (uintptr_t)npc > 0x1000)
                                          ? npc->getPosition()
                                          : Ogre::Vector3::ZERO;
              dropPos.y += 2.0f;

              Log(LOG_WARN,
                  "ACTION: No player character found, dropping item at "
                      "NPC/Origin.");

              Item *item = CreateItem(thisptr, gd, NULL, NULL, 1);
              if (item) {
                item->quantity = 1;
                item->activate(true, dropPos, Ogre::Quaternion::IDENTITY, false,
                               YesNoMaybe::NO, true);
                thisptr->showPlayerAMessage_withLog(
                    "Item dropped nearby: " + templateName, true);
              }
            }
          } else {
            Log(LOG_WARN,
                "ACTION: Could not find template for: " + templateName);
            thisptr->showPlayerAMessage(
                "Error: Item template '" + templateName + "' not found.", true);
          }
        }
      }
    } catch (...) {
      Log(LOG_ERROR, "ACTION: Exception during action index " +
          ToString((int)actIdx));
    }
  }
}
