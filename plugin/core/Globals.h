#pragma once
#include <deque>
#include <map>
#include <string>
#include <windows.h>

#include "Utils.h"

class GameData;
class GameWorld;
class SharedKing;
#include <kenshi/util/hand.h>
// Character.h reaches OgrePrerequisites.h mid-cycle, where STLAllocator is not
// yet declared, so Ogre's headers must load first
#include <ogre/OgreVector3.h>

extern GameWorld **ppWorld;
extern SharedKing **ppSharedKing;
extern CRITICAL_SECTION g_LogMutex;
extern std::deque<std::string> g_messageQueue;
extern CRITICAL_SECTION g_msgMutex;
extern hand g_talkTargetHand;
extern DWORD g_mainThreadId;

const float VISION_RANGE = 100.0f;

extern float g_whisperRadius;
extern float g_proximityRadius;
extern float g_yellRadius;
extern int g_radiantIntervalSeconds;
extern bool g_enableRadiant;
extern bool g_triggerRadiant;
extern float g_speechBubbleLife;
extern bool g_openWebPanelOnStart;
extern bool g_enableWelcome;
extern bool g_characterisedDialogue;
extern LogLevel g_logLevel;

extern CRITICAL_SECTION g_stateMutex;
extern int g_chatHotkey;
extern std::string g_chatHotkeyStr;
extern std::map<std::string, std::string> g_uiTranslation;
std::string T(const std::string &key);

// Resolved from the DLL's own path so Steam Workshop numeric-ID folders work too
extern std::string g_modRoot;

enum ActionType {
  ACT_SAY,
  ACT_ATTACK,
  ACT_JOIN_PARTY,
  ACT_SET_TASK,
  ACT_NOTIFY,
  ACT_GIVE_ITEM,
  ACT_GIVE_CATS,
  ACT_TAKE_CATS,
  ACT_SPAWN_ITEM,
  ACT_RELEASE,
  ACT_TAKE_ITEM,
  ACT_PROBE,
  ACT_HIRE,
  ACT_END_HIRE,
  ACT_FIRST_AID,
  ACT_ADD_CATS,
  ACT_SELL_ITEM,
  ACT_BUY_ITEM
};

extern CRITICAL_SECTION g_eventMutex;

struct QueuedAction {
  ActionType type;
  hand actor;
  hand target;
  std::string message; // Text, item, faction, town name, or probe payload, depending on type
  int taskValue;       // Task ID, item count, cats, or relation delta, depending on type
  // A cheat spawn names its record and grade, so SPAWN_ITEM looks up neither
  GameData *itemData;
  GameData *itemModel; // The grade of a weapon
  GameData *itemMaker; // The manufacturer of a weapon
  int itemLevel;       // The grade of an armour or a crossbow, or the level of a weapon grade
  QueuedAction()
      : taskValue(0), itemData(NULL), itemModel(NULL), itemMaker(NULL),
        itemLevel(0) {}
};

extern std::deque<QueuedAction> g_uiActionQueue;
extern CRITICAL_SECTION g_uiMutex;
// The game thread runs a queued action in its next frame
void QueueAction(const QueuedAction &act);
void QueueAction(ActionType type, const hand &actor, const hand &target = hand(),
                 const std::string &message = std::string(), int value = 0);
