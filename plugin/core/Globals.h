#include <deque>
#include <map>
#include <set>
#include <string>
#include <vector>
#include <windows.h>

#include "Utils.h"

class GameWorld;
class SharedKing;
namespace Ogre {
class Vector3;
}
#include <kenshi/Enums.h>
#include <kenshi/util/hand.h>
#include <ogre/OgreVector3.h>

struct OriginJob {
  TaskType type;
  hand target;
  Ogre::Vector3 location;
};

struct OriginState {
  std::vector<OriginJob> jobs;
  hand homeTown;
  hand homeBuilding;
};

extern GameWorld **ppWorld;
extern SharedKing **ppSharedKing;
extern CRITICAL_SECTION g_LogMutex;
extern std::deque<std::string> g_messageQueue;
extern CRITICAL_SECTION g_msgMutex;
extern hand g_talkTargetHand;
extern DWORD g_mainThreadId;
extern DWORD g_lastRadiantTick;
extern std::map<std::string, std::string> g_originFactions;
extern std::map<std::string, OriginState> g_originJobs;

extern float g_proximityRadius;
extern float g_yellRadius;
extern float g_visionRange;
extern int g_radiantIntervalSeconds;
extern bool g_enableRadiant;
extern bool g_triggerRadiant;
extern float g_speechBubbleLife;
extern bool g_openWebPanelOnStart;
extern LogLevel g_logLevel;

extern hand g_lastSelectionHand;
extern hand g_lastChattingPlayerHand;
extern CRITICAL_SECTION g_stateMutex;
extern int g_chatHotkey;
extern std::string g_chatHotkeyStr;
extern std::map<std::string, std::string> g_uiTranslation;
std::string T(const std::string &key);

// Resolved from the DLL's own path so Steam Workshop numeric-ID folders work too
extern std::string g_modRoot;
extern HMODULE g_hModule;

enum ActionType {
  ACT_SAY,
  ACT_ATTACK,
  ACT_JOIN_PARTY,
  ACT_SET_TASK,
  ACT_NOTIFY,
  ACT_DROP_ITEM,
  ACT_GIVE_ITEM,
  ACT_LEAVE,
  ACT_GIVE_CATS,
  ACT_TAKE_CATS,
  ACT_FACTION_RELATIONS,
  ACT_SPAWN_ITEM,
  ACT_RELEASE,
  ACT_TAKE_ITEM,
  ACT_PROBE,
  ACT_HIRE,
  ACT_END_HIRE,
  ACT_FIRST_AID,
  ACT_ADD_CATS
};

struct GameEvent {
  std::string kind;
  std::string fields;
  unsigned long long attack;
  int day, hour, minute;
  DWORD queuedAt;
};

extern std::deque<GameEvent> g_gameEvents;
extern std::set<unsigned long long> g_waitingAttacks;
extern CRITICAL_SECTION g_eventMutex;
void QueueGameEvent(const std::string &kind, const std::string &fields,
                    unsigned long long attack = 0);
bool AttackWaits(unsigned long long attack);

struct QueuedAction {
  ActionType type;
  hand actor;
  hand target;
  std::string message; // Text, item, faction, town name, or probe payload, depending on type
  int taskValue;       // Task ID, item count, cats, or relation delta, depending on type
};

extern std::deque<QueuedAction> g_uiActionQueue;
extern CRITICAL_SECTION g_uiMutex;
