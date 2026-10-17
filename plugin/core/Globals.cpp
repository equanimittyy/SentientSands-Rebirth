#include "Globals.h"

GameWorld **ppWorld = nullptr;
SharedKing **ppSharedKing = nullptr;
CRITICAL_SECTION g_LogMutex;
std::deque<std::string> g_messageQueue;
CRITICAL_SECTION g_msgMutex;
hand g_talkTargetHand;
DWORD g_mainThreadId = 0;
std::string g_modRoot = "";

// LoadPluginConfig keeps these when the INI lacks a key, as at a first start,
// so g_openWebPanelOnStart must match SETTINGS_DEFAULTS of the server
float g_whisperRadius = 50.0f;
float g_proximityRadius = 150.0f;
float g_yellRadius = 200.0f;
int g_radiantIntervalSeconds = 600;
bool g_enableRadiant = true;
bool g_triggerRadiant = false;
float g_speechBubbleLife = 10.0f;
bool g_openWebPanelOnStart = true;
bool g_enableWelcome = true;
LogLevel g_logLevel = LOG_INFO;

CRITICAL_SECTION g_stateMutex;

CRITICAL_SECTION g_eventMutex;

std::deque<QueuedAction> g_uiActionQueue;
CRITICAL_SECTION g_uiMutex;

void QueueAction(const QueuedAction &act) {
  EnterCriticalSection(&g_uiMutex);
  g_uiActionQueue.push_back(act);
  LeaveCriticalSection(&g_uiMutex);
}

void QueueAction(ActionType type, const hand &actor, const hand &target,
                 const std::string &message, int value) {
  QueuedAction act;
  act.type = type;
  act.actor = actor;
  act.target = target;
  act.message = message;
  act.taskValue = value;
  QueueAction(act);
}

int g_chatHotkey = VK_OEM_5; // '\' by default
std::string g_chatHotkeyStr = "\\";
std::map<std::string, std::string> g_uiTranslation;

// Under the lock, because the reply threads read the strings while the game
// thread swaps in a new language
std::string T(const std::string &key) {
  EnterCriticalSection(&g_stateMutex);
  auto it = g_uiTranslation.find(key);
  std::string text = it != g_uiTranslation.end() ? it->second : key;
  LeaveCriticalSection(&g_stateMutex);
  return text;
}
