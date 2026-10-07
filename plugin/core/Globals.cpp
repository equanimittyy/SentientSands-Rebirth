#include "Globals.h"

GameWorld **ppWorld = nullptr;
SharedKing **ppSharedKing = nullptr;
CRITICAL_SECTION g_LogMutex;
std::deque<std::string> g_messageQueue;
CRITICAL_SECTION g_msgMutex;
hand g_talkTargetHand;
DWORD g_mainThreadId = 0;
DWORD g_lastRadiantTick = 0;
std::map<unsigned int, std::string> g_originFactions;
std::map<unsigned int, OriginState> g_originJobs;
std::string g_modRoot = "";
HMODULE g_hModule = nullptr;

float g_proximityRadius = 50.0f;
float g_yellRadius = 100.0f;
float g_visionRange = 100.0f;
int g_radiantIntervalSeconds = 600;
bool g_enableRadiant = true;
bool g_triggerRadiant = false;
float g_speechBubbleLife = 15.0f;
bool g_openWebPanelOnStart = true;
LogLevel g_logLevel = LOG_INFO;

hand g_lastSelectionHand;
hand g_lastChattingPlayerHand;
CRITICAL_SECTION g_stateMutex;

std::deque<GameEvent> g_gameEvents;
std::set<unsigned long long> g_waitingAttacks;
CRITICAL_SECTION g_eventMutex;

std::deque<QueuedAction> g_uiActionQueue;
CRITICAL_SECTION g_uiMutex;

int g_chatHotkey = VK_OEM_5; // '\' by default
std::string g_chatHotkeyStr = "\\";
std::map<std::string, std::string> g_uiTranslation;

std::string T(const std::string &key) {
  auto it = g_uiTranslation.find(key);
  if (it != g_uiTranslation.end())
    return it->second;
  return key;
}
