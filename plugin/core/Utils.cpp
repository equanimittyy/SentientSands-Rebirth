#include "Utils.h"
#include "Globals.h"
#include <fstream>
#include <iomanip>
#include <kenshi/Enums.h>
#include <kenshi/util/hand.h>
#include <sstream>

#include <algorithm>
#include <cctype>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <windows.h>

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
    std::string logDir = g_modRoot + "\\logs";
    std::string logPath = logDir + "\\SentientSands_SDK.log";
    CreateDirectoryA(logDir.c_str(), NULL);
    // Keeps the previous game's log, so a crash log survives the relaunch
    MoveFileExA(logPath.c_str(), (logDir + "\\SentientSands_SDK.old.log").c_str(),
                MOVEFILE_REPLACE_EXISTING);
    s_logFile.open(logPath.c_str(), std::ios::app);
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
std::string JsonBool(bool value) { return value ? "true" : "false"; }

std::string EscapeJSON(const std::string &s) {
  static const char HEX[] = "0123456789abcdef";
  std::string res;
  for (size_t i = 0; i < s.length(); ++i) {
    unsigned char c = (unsigned char)s[i];
    if (c == '\"')
      res += "\\\"";
    else if (c == '\\')
      res += "\\\\";
    else if (c == '\n')
      res += "\\n";
    else if (c == '\r')
      res += "\\r";
    else if (c == '\t')
      res += "\\t";
    else if (c < 0x20) {
      // Python's json rejects a raw control character in a string
      res += "\\u00";
      res += HEX[c >> 4];
      res += HEX[c & 15];
    } else
      res += s[i];
  }
  return res;
}

static bool ReadHex4(const std::string &s, size_t at, unsigned int &value) {
  if (at + 4 > s.length())
    return false;
  value = 0;
  for (size_t j = at; j < at + 4; ++j) {
    char c = s[j];
    value <<= 4;
    if (c >= '0' && c <= '9')
      value += c - '0';
    else if (c >= 'a' && c <= 'f')
      value += 10 + c - 'a';
    else if (c >= 'A' && c <= 'F')
      value += 10 + c - 'A';
    else
      return false;
  }
  return true;
}

static void AppendUtf8(std::string &out, unsigned int cp) {
  if (cp <= 0x7F) {
    out += (char)cp;
  } else if (cp <= 0x7FF) {
    out += (char)(0xC0 | (cp >> 6));
    out += (char)(0x80 | (cp & 0x3F));
  } else if (cp <= 0xFFFF) {
    out += (char)(0xE0 | (cp >> 12));
    out += (char)(0x80 | ((cp >> 6) & 0x3F));
    out += (char)(0x80 | (cp & 0x3F));
  } else {
    out += (char)(0xF0 | (cp >> 18));
    out += (char)(0x80 | ((cp >> 12) & 0x3F));
    out += (char)(0x80 | ((cp >> 6) & 0x3F));
    out += (char)(0x80 | (cp & 0x3F));
  }
}

std::string UnescapeJSON(const std::string &s) {
  std::string res;
  for (size_t i = 0; i < s.length(); ++i) {
    if (s[i] != '\\' || i + 1 == s.length()) {
      res += s[i];
      continue;
    }
    char e = s[++i];
    unsigned int cp, low;
    if (e == 'n')
      res += '\n';
    else if (e == 'r')
      res += '\r';
    else if (e == 't')
      res += '\t';
    else if (e == 'b')
      res += '\b';
    else if (e == 'f')
      res += '\f';
    else if (e == '"' || e == '\\' || e == '/')
      res += e;
    else if (e == 'u' && ReadHex4(s, i + 1, cp)) {
      i += 4;
      // Flask escapes a character outside the BMP as a surrogate pair
      if (cp >= 0xD800 && cp <= 0xDBFF && s.compare(i + 1, 2, "\\u") == 0 &&
          ReadHex4(s, i + 3, low) && low >= 0xDC00 && low <= 0xDFFF) {
        cp = 0x10000 + ((cp - 0xD800) << 10) + (low - 0xDC00);
        i += 6;
      }
      AppendUtf8(res, cp);
    } else {
      res += '\\';
      res += e;
    }
  }
  return res;
}

// Past the closing quote of the string that opens at quote, or npos
static size_t ReadJsonString(const std::string &json, size_t quote,
                             std::string &out) {
  for (size_t i = quote + 1; i < json.length(); ++i) {
    if (json[i] == '\\') {
      ++i;
    } else if (json[i] == '"') {
      out = UnescapeJSON(json.substr(quote + 1, i - quote - 1));
      return i + 1;
    }
  }
  return std::string::npos;
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
    std::string res;
    return ReadJsonString(json, valStart, res) == std::string::npos ? "" : res;
  } else if (json[valStart] == '[' || json[valStart] == '{') {
    char open = json[valStart];
    char close = (open == '[') ? ']' : '}';
    int bracketCount = 0;
    bool inString = false;
    size_t i = valStart;
    for (; i < json.length(); i++) {
      if (inString) {
        if (json[i] == '\\')
          i++;
        else if (json[i] == '"')
          inString = false;
      } else if (json[i] == '"') {
        inString = true;
      } else if (json[i] == open) {
        bracketCount++;
      } else if (json[i] == close && --bracketCount == 0) {
        break;
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

static void AddArrayItem(std::vector<std::string> &items,
                         const std::string &array, size_t start, size_t end) {
  size_t first = array.find_first_not_of(" \t\r\n", start);
  size_t last = array.find_last_not_of(" \t\r\n", end - 1);
  if (first < end && last != std::string::npos && last >= first)
    items.push_back(array.substr(first, last - first + 1));
}

std::vector<std::string> JsonArrayItems(const std::string &array) {
  std::vector<std::string> items;
  int depth = 0;
  bool inString = false;
  size_t start = 0;
  for (size_t i = 0; i < array.length(); ++i) {
    char c = array[i];
    if (inString) {
      if (c == '\\')
        ++i;
      else if (c == '"')
        inString = false;
    } else if (c == '"') {
      inString = true;
    } else if (c == '[' || c == '{') {
      if (depth++ == 0)
        start = i + 1;
    } else if (c == ']' || c == '}') {
      if (--depth == 0)
        AddArrayItem(items, array, start, i);
    } else if (c == ',' && depth == 1) {
      AddArrayItem(items, array, start, i);
      start = i + 1;
    }
  }
  return items;
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

static char LowerChar(char c) { return (char)tolower((unsigned char)c); }

std::string Lower(std::string text) {
  std::transform(text.begin(), text.end(), text.begin(), LowerChar);
  return text;
}

std::string Trim(const std::string &text, const char *chars) {
  size_t first = text.find_first_not_of(chars);
  if (first == std::string::npos)
    return "";
  return text.substr(first, text.find_last_not_of(chars) - first + 1);
}

std::string Fill(std::string text, const std::string &slot,
                 const std::string &value) {
  size_t at = text.find(slot);
  if (at != std::string::npos)
    text.replace(at, slot.size(), value);
  return text;
}

void SetHotkeyFromString(const std::string &keyStr) {
  char letter =
      keyStr.size() == 1 ? (char)toupper((unsigned char)keyStr[0]) : '\0';
  g_chatHotkeyStr = keyStr;
  if (keyStr == "\\") {
    g_chatHotkey = VK_OEM_5;
  } else if (keyStr == "[") {
    g_chatHotkey = VK_OEM_4;
  } else if (letter && strchr("PTJUK", letter)) {
    g_chatHotkey = letter;
  } else {
    g_chatHotkey = VK_OEM_5;
    g_chatHotkeyStr = "\\";
  }
}

void LoadUITranslation(const std::string &json) {
  std::string uiTransJson = GetJsonValue(json, "ui_translation");
  if (uiTransJson.empty())
    return;

  std::map<std::string, std::string> table;
  size_t pos = 0;
  std::string key, val;
  while ((pos = uiTransJson.find('"', pos)) != std::string::npos &&
         (pos = ReadJsonString(uiTransJson, pos, key)) != std::string::npos &&
         (pos = uiTransJson.find('"', pos)) != std::string::npos &&
         (pos = ReadJsonString(uiTransJson, pos, val)) != std::string::npos)
    table[key] = val;
  EnterCriticalSection(&g_stateMutex);
  g_uiTranslation.swap(table);
  LeaveCriticalSection(&g_stateMutex);
}

static int IniInt(const std::string &ini, const char *key, int fallback) {
  return GetPrivateProfileIntA("Settings", key, fallback, ini.c_str());
}

static std::string IniString(const std::string &ini, const char *key,
                             const std::string &fallback) {
  char value[64];
  GetPrivateProfileStringA("Settings", key, fallback.c_str(), value,
                           sizeof(value), ini.c_str());
  return value;
}

void LoadPluginConfig() {
  std::string ini = g_modRoot + "\\SentientSands_Config.ini";
  SetHotkeyFromString(IniString(ini, "ChatHotkey", g_chatHotkeyStr));
  g_whisperRadius = (float)IniInt(ini, "WhisperRadius", (int)g_whisperRadius);
  g_proximityRadius = (float)IniInt(ini, "TalkRadius", (int)g_proximityRadius);
  g_yellRadius = (float)IniInt(ini, "YellRadius", (int)g_yellRadius);
  g_radiantIntervalSeconds =
      60 * IniInt(ini, "RadiantChatMinutes", g_radiantIntervalSeconds / 60);
  g_enableRadiant =
      IniInt(ini, "EnableRadiantConversations", g_enableRadiant) != 0;
  g_enableWelcome = IniInt(ini, "EnableWelcomePopup", g_enableWelcome) != 0;
  g_speechBubbleLife = (float)atof(
      IniString(ini, "SpeechBubbleLife", ToString(g_speechBubbleLife)).c_str());
  g_openWebPanelOnStart =
      IniInt(ini, "OpenWebPanelOnStart", g_openWebPanelOnStart) != 0;
  std::string logLevel = IniString(ini, "LogLevel", "INFO");
  g_logLevel = ParseLogLevel(logLevel);

  Log(LOG_INFO, "CONFIG: Loaded TalkRadius=" + ToString(g_proximityRadius) +
                    ", RadiantInterval=" + ToString(g_radiantIntervalSeconds) +
                    "s" + ", EnableRadiant=" + JsonBool(g_enableRadiant) +
                    ", EnableWelcome=" + JsonBool(g_enableWelcome) +
                    ", LogLevel=" + logLevel);
}

void StartPythonServer(bool openBrowser) {
  Log(LOG_INFO, "SYSTEM: Starting Python server...");

  std::string localPython = g_modRoot + "\\server\\python\\python.exe";
  std::string serverScript =
      g_modRoot + "\\server\\main.py";
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
