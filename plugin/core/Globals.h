#include <deque>
#include <map>
#include <set>
#include <string>
#include <vector>
#include <windows.h>

class GameWorld;
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
extern CRITICAL_SECTION g_LogMutex;
extern std::deque<std::string> g_messageQueue;
extern CRITICAL_SECTION g_msgMutex;
extern hand g_talkTargetHand;
extern DWORD g_mainThreadId;
extern DWORD g_lastAmbientTick;
extern DWORD g_lastDialogueTick;
extern std::map<unsigned int, std::string> g_originFactions;
extern std::map<unsigned int, OriginState> g_originJobs;

extern float g_radiantRange;
extern float g_proximityRadius;
extern float g_yellRadius;
extern float g_visionRange;
extern int g_ambientIntervalSeconds;
extern bool g_enableAmbient;
extern bool g_triggerAmbient;
extern float g_minFactionRelation;
extern float g_maxFactionRelation;
extern int g_dialogueSpeedSeconds;
extern float g_speechBubbleLife;
extern bool g_openWebPanelOnStart;

extern hand g_lastSelectionHand;
extern hand g_lastChattingPlayerHand;
extern CRITICAL_SECTION g_stateMutex;
extern int g_chatHotkey;
extern std::string g_chatHotkeyStr;
extern std::string g_language;
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
  ACT_TAKE_ITEM
};

struct GameEvent {
  std::string type;
  std::string actor;
  std::string actorFaction;
  std::string target;
  std::string targetFaction;
  std::string message;
  DWORD timestamp;
};

extern std::deque<GameEvent> g_gameEvents;
extern CRITICAL_SECTION g_eventMutex;
void LogGameEvent(const std::string &type, const std::string &actor,
                  const std::string &actorFaction, const std::string &target,
                  const std::string &targetFaction, const std::string &message);

struct QueuedAction {
  ActionType type;
  hand actor;
  hand target;
  std::string message; // Text, item, faction, or town name, depending on type
  int taskValue;       // Task ID, item count, cats, or relation delta, depending on type
};

extern std::deque<QueuedAction> g_uiActionQueue;
extern CRITICAL_SECTION g_uiMutex;

struct NameCheckItem {
  unsigned int serial;
  std::string name;
  std::string gender; // "Male" | "Female"
  std::string race;
  bool is_generic;
};
extern std::deque<NameCheckItem> g_nameCheckQueue;
extern CRITICAL_SECTION g_nameCheckMutex;
extern std::set<unsigned int> g_renamedSerials;
extern DWORD g_lastContextPushTick;

extern std::vector<std::string> g_genericPrefixes;
extern std::vector<std::string> g_genericKeywords;
