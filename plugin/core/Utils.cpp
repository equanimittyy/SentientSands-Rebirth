#include "Utils.h"
#include "../ui/ChatUIGlobals.h"
#include "Globals.h"
#include <fstream>
#include <iomanip>
#include <kenshi/Enums.h>
#include <kenshi/util/hand.h>
#include <sstream>

#include <algorithm>
#include <cctype>
#include <cstdio>
#include <cstdlib>
#include <windows.h>

using namespace SentientSands::UI;

std::wstring Utf8ToWide(const std::string &str) {
  if (str.empty())
    return L"";
  int size_needed =
      MultiByteToWideChar(CP_UTF8, 0, &str[0], (int)str.size(), NULL, 0);
  std::wstring wstrTo(size_needed, 0);
  MultiByteToWideChar(CP_UTF8, 0, &str[0], (int)str.size(), &wstrTo[0],
                      size_needed);
  return wstrTo;
}

// File scope: VC++ 2010 does not construct function statics thread-safely
static std::ofstream s_logFile;
static bool s_logRotated = false;

LogLevel ParseLogLevel(const std::string &text) {
  std::string upper = text;
  std::transform(upper.begin(), upper.end(), upper.begin(), ::toupper);
  if (upper == "DEBUG")
    return LOG_DEBUG;
  if (upper == "WARN")
    return LOG_WARN;
  if (upper == "ERROR")
    return LOG_ERROR;
  return LOG_INFO;
}

bool LogEnabled(LogLevel level) { return level >= g_logLevel; }

void Log(LogLevel level, const std::string &msg) {
  if (!LogEnabled(level))
    return;

  static const char *const levelNames[] = {"DEBUG", "INFO", "WARN", "ERROR"};

  EnterCriticalSection(&g_LogMutex);
  SYSTEMTIME now;
  GetLocalTime(&now);
  char stamp[32];
  sprintf_s(stamp, "%04d-%02d-%02d %02d:%02d:%02d,%03d", now.wYear,
            now.wMonth, now.wDay, now.wHour, now.wMinute, now.wSecond,
            now.wMilliseconds);

  std::string line = std::string(stamp) + " - " + levelNames[level] + " - ";
  for (size_t i = 0; i < msg.size(); ++i) {
    if (msg[i] == '\n')
      line += "\\n";
    else if (msg[i] != '\r')
      line += msg[i];
  }

  if (!s_logRotated) {
    // Keeps the previous game's log, so a crash log survives the relaunch
    MoveFileExA("SentientSands_SDK.log", "SentientSands_SDK.old.log",
                MOVEFILE_REPLACE_EXISTING);
    s_logFile.open("SentientSands_SDK.log", std::ios::app);
    s_logRotated = true;
  }
  if (s_logFile.is_open())
    s_logFile << line << std::endl;
  LeaveCriticalSection(&g_LogMutex);
  OutputDebugStringA(("[SentientSands] " + line + "\n").c_str());
}

template <typename T> std::string ToStringT(T val) {
  std::ostringstream ss;
  ss << val;
  return ss.str();
}

std::string ToString(int val) { return ToStringT(val); }
std::string ToString(unsigned int val) { return ToStringT(val); }
std::string ToString(float val) { return ToStringT(val); }

std::string EscapeJSON(const std::string &s) {
  std::string res = "";
  for (size_t i = 0; i < s.length(); ++i) {
    char c = s[i];
    if (c == '\"')
      res += "\\\"";
    else if (c == '\\')
      res += "\\\\";
    else if (c == '\n')
      res += "\\n";
    else if (c == '\r')
      res += "\\r";
    else
      res += c;
  }
  return res;
}

std::string UnescapeJSON(const std::string &s) {
  std::string res = "";
  for (size_t i = 0; i < s.length(); ++i) {
    if (s[i] == '\\' && i + 1 < s.length()) {
      if (s[i + 1] == 'n') {
        res += '\n';
        i++;
      } else if (s[i + 1] == 'r') {
        res += '\r';
        i++;
      } else if (s[i + 1] == '\"') {
        res += '\"';
        i++;
      } else if (s[i + 1] == '\\') {
        res += '\\';
        i++;
      } else if (s[i + 1] == 'u' && i + 5 < s.length()) {
        unsigned int cp = 0;
        bool valid = true;
        for (int j = 0; j < 4; ++j) {
          char c = s[i + 2 + j];
          cp <<= 4;
          if (c >= '0' && c <= '9')
            cp += (c - '0');
          else if (c >= 'a' && c <= 'f')
            cp += (10 + c - 'a');
          else if (c >= 'A' && c <= 'F')
            cp += (10 + c - 'A');
          else {
            valid = false;
            break;
          }
        }

        if (valid) {
          if (cp <= 0x7F) {
            res += (char)cp;
          } else if (cp <= 0x7FF) {
            res += (char)(0xC0 | ((cp >> 6) & 0x1F));
            res += (char)(0x80 | (cp & 0x3F));
          } else {
            res += (char)(0xE0 | ((cp >> 12) & 0x0F));
            res += (char)(0x80 | ((cp >> 6) & 0x3F));
            res += (char)(0x80 | (cp & 0x3F));
          }
          i += 5; // skip uXXXX
        } else {
          res += s[i];
        }
      } else {
        res += s[i];
      }
    } else {
      res += s[i];
    }
  }
  return res;
}

std::string GetJsonValue(const std::string &json, const std::string &key) {
  std::string keyQuery = "\"" + key + "\":";
  size_t pos = json.find(keyQuery);
  if (pos == std::string::npos) {
    return "";
  }

  size_t valStart = json.find_first_not_of(" \t\r\n", pos + keyQuery.length());
  if (valStart == std::string::npos)
    return "";

  if (json[valStart] == '\"') {
    valStart++;
    std::string res = "";
    for (size_t i = valStart; i < json.length(); ++i) {
      if (json[i] == '\\' && i + 1 < json.length()) {
        res += json[i];
        res += json[i + 1];
        i++;
      } else if (json[i] == '\"') {
        return UnescapeJSON(res);
      } else {
        res += json[i];
      }
    }
  } else if (json[valStart] == '[' || json[valStart] == '{') {
    char open = json[valStart];
    char close = (open == '[') ? ']' : '}';
    int bracketCount = 0;
    bool inString = false;
    size_t i = valStart;
    for (; i < json.length(); i++) {
      if (json[i] == '"' && (i == 0 || json[i - 1] != '\\')) {
        inString = !inString;
      } else if (!inString) {
        if (json[i] == open)
          bracketCount++;
        else if (json[i] == close) {
          bracketCount--;
          if (bracketCount == 0)
            break;
        }
      }
    }
    if (i < json.length() && json[i] == close) {
      return json.substr(valStart, i - valStart + 1);
    }
  } else {
    size_t end = json.find_first_of(",}", valStart);
    if (end != std::string::npos) {
      return json.substr(valStart, end - valStart);
    }
  }
  return "";
}

static bool CharEqualIgnoreCase(char a, char b) {
  return tolower((unsigned char)a) == tolower((unsigned char)b);
}

// Folds ASCII only, so a Cyrillic letter matches only in the same case
bool ContainsIgnoreCase(const std::string &text, const std::string &query) {
  return query.empty() ||
         std::search(text.begin(), text.end(), query.begin(), query.end(),
                     CharEqualIgnoreCase) != text.end();
}

void SetHotkeyFromString(const std::string &keyStr) {
  g_chatHotkeyStr = keyStr;
  if (keyStr == "\\")
    g_chatHotkey = VK_OEM_5;
  else if (keyStr == "[")
    g_chatHotkey = VK_OEM_4;
  else if (keyStr == "P" || keyStr == "p")
    g_chatHotkey = 'P';
  else if (keyStr == "T" || keyStr == "t")
    g_chatHotkey = 'T';
  else if (keyStr == "J" || keyStr == "j")
    g_chatHotkey = 'J';
  else if (keyStr == "U" || keyStr == "u")
    g_chatHotkey = 'U';
  else if (keyStr == "K" || keyStr == "k")
    g_chatHotkey = 'K';
  else {
    g_chatHotkey = VK_OEM_5;
    g_chatHotkeyStr = "\\";
  }
}

void LoadUITranslation(const std::string &json) {
  std::string uiTransJson = GetJsonValue(json, "ui_translation");
  if (uiTransJson.empty())
    return;

  g_uiTranslation.clear();
  size_t pos = 1;
  while (pos < uiTransJson.length() - 1) {
    size_t q1 = uiTransJson.find('"', pos);
    if (q1 == std::string::npos)
      break;
    size_t q2 = uiTransJson.find('"', q1 + 1);
    if (q2 == std::string::npos)
      break;
    std::string key = uiTransJson.substr(q1 + 1, q2 - q1 - 1);

    size_t colon = uiTransJson.find(':', q2);
    if (colon == std::string::npos)
      break;

    size_t v1 = uiTransJson.find('"', colon);
    if (v1 == std::string::npos)
      break;
    size_t v2 = uiTransJson.find('"', v1 + 1);
    if (v2 == std::string::npos)
      break;
    std::string val = uiTransJson.substr(v1 + 1, v2 - v1 - 1);

    g_uiTranslation[UnescapeJSON(key)] = UnescapeJSON(val);
    pos = v2 + 1;
  }
}

void LoadPluginConfig() {
  std::string iniPath = g_modRoot + "\\SentientSands_Config.ini";

  char hotkeyBuf[32];
  GetPrivateProfileStringA("Settings", "ChatHotkey", "\\", hotkeyBuf, 32,
                           iniPath.c_str());
  SetHotkeyFromString(hotkeyBuf);

  g_radiantRange = (float)GetPrivateProfileIntA("Settings", "RadiantRange", 100,
                                                iniPath.c_str());
  g_proximityRadius = (float)GetPrivateProfileIntA("Settings", "TalkRadius",
                                                   100, iniPath.c_str());
  g_yellRadius = (float)GetPrivateProfileIntA("Settings", "YellRadius", 200,
                                              iniPath.c_str());

  g_visionRange = 100.0f;
  g_ambientIntervalSeconds =
      GetPrivateProfileIntA("Settings", "RadiantDelay", 240, iniPath.c_str());

  g_enableAmbient =
      GetPrivateProfileIntA("Settings", "EnableAmbientConversations", 1,
                            iniPath.c_str()) != 0;

  g_enableWelcome = GetPrivateProfileIntA("Settings", "EnableWelcomePopup", 1,
                                          iniPath.c_str()) != 0;

  g_dialogueSpeedSeconds =
      GetPrivateProfileIntA("Settings", "DialogueSpeed", 5, iniPath.c_str());

  char bubbleLifeBuf[32];
  GetPrivateProfileStringA("Settings", "SpeechBubbleLife", "5.0", bubbleLifeBuf,
                           32, iniPath.c_str());
  g_speechBubbleLife = (float)atof(bubbleLifeBuf);

  g_openWebPanelOnStart = GetPrivateProfileIntA("Settings",
                                                "OpenWebPanelOnStart", 1,
                                                iniPath.c_str()) != 0;

  char logLevelBuf[16];
  GetPrivateProfileStringA("Settings", "LogLevel", "INFO", logLevelBuf, 16,
                           iniPath.c_str());
  g_logLevel = ParseLogLevel(logLevelBuf);

  Log(LOG_INFO,
      "CONFIG: Loaded ProximityRadius=" + ToString(g_proximityRadius) +
          ", RadiantRange=" + ToString(g_radiantRange) +
          ", AmbientInterval=" + ToString(g_ambientIntervalSeconds) + "s" +
          ", EnableAmbient=" + (g_enableAmbient ? "true" : "false") +
          ", EnableWelcome=" + (g_enableWelcome ? "true" : "false") +
          ", LogLevel=" + logLevelBuf);
}

void StartPythonServer(bool openBrowser) {
  Log(LOG_INFO, "SYSTEM: Starting Python server...");

  std::string localPython = g_modRoot + "\\server\\python\\python.exe";
  std::string serverScript =
      g_modRoot + "\\server\\scripts\\kenshi_llm_server.py";
  std::string serverArgs = openBrowser ? " --open-browser" : "";

  Log(LOG_INFO, "SYSTEM: Python path: " + localPython);
  Log(LOG_INFO, "SYSTEM: Server script: " + serverScript);

  DWORD fileAttr = GetFileAttributesA(localPython.c_str());
  if (fileAttr != INVALID_FILE_ATTRIBUTES &&
      !(fileAttr & FILE_ATTRIBUTE_DIRECTORY)) {
    Log(LOG_INFO, "SYSTEM: Using embedded Python runtime.");
    std::string cmd =
        "\"" + localPython + "\" \"" + serverScript + "\"" + serverArgs;
    WinExec(cmd.c_str(), SW_HIDE);
  } else {
    int result = system("python --version >nul 2>&1");
    if (result == 0) {
      Log(LOG_WARN,
          "SYSTEM: Local Python not found, falling back to global 'python'.");
      WinExec(("python \"" + serverScript + "\"" + serverArgs).c_str(),
              SW_HIDE);
    } else {
      Log(LOG_ERROR, "SYSTEM: No Python installation found!");
      MessageBoxA(
          NULL,
          "Sentient Sands Rebirth requires a Python engine to connect to AI "
          "models, but no Python installation was found!\n\n"
          "The release package ships it in server\\python. Reinstall "
          "Sentient Sands Rebirth from the release zip, then restart the game.",
          "Sentient Sands Rebirth - Python Missing", MB_ICONERROR | MB_OK);
    }
  }
}
void LogGameEvent(const std::string &type, const std::string &actor,
                  const std::string &actorFaction, const std::string &target,
                  const std::string &targetFaction,
                  const std::string &message) {
  EnterCriticalSection(&g_eventMutex);
  GameEvent ev;
  ev.type = type;
  ev.actor = actor;
  ev.actorFaction = actorFaction;
  ev.target = target;
  ev.targetFaction = targetFaction;
  ev.message = message;
  ev.timestamp = GetTickCount();
  g_gameEvents.push_back(ev);
  if (g_gameEvents.size() > 100) {
    g_gameEvents.pop_front();
  }
  LeaveCriticalSection(&g_eventMutex);

  if (!LogEnabled(LOG_DEBUG))
    return;
  std::string logMsg = "EVENT: " + type + ": " + actor;
  if (!actorFaction.empty() && actorFaction != "None")
    logMsg += " (" + actorFaction + ")";
  logMsg += " -> " + target;
  if (!targetFaction.empty() && targetFaction != "None")
    logMsg += " (" + targetFaction + ")";
  logMsg += " (" + message + ")";
  Log(LOG_DEBUG, logMsg);
}

#include <kenshi/GameWorld.h>
void SleepIfPaused(DWORD ms) {
  DWORD start = GetTickCount();
  while (GetTickCount() - start < ms) {
    if (ppWorld && *ppWorld && (*ppWorld)->isPaused()) {
      Sleep(100);
      start +=
          100; // Paused time doesn't count toward the delay
      continue;
    }
    Sleep(100);
  }
}
