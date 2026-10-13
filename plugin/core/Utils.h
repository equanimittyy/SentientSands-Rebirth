#pragma once
#include <string>
#include <vector>
#include <windows.h>

enum LogLevel { LOG_DEBUG, LOG_INFO, LOG_WARN, LOG_ERROR };

void Log(LogLevel level, const std::string &msg);
bool LogEnabled(LogLevel level);
LogLevel ParseLogLevel(const std::string &text);
std::string ToString(int val);
std::string ToString(unsigned int val);
std::string ToString(float val);
std::string JsonBool(bool value);
std::string EscapeJSON(const std::string &s);
std::wstring Utf8ToWide(const std::string &str);
std::string GetJsonValue(const std::string &json, const std::string &key);
bool JsonTrue(const std::string &json, const std::string &key);
// The elements of a JSON array, each as its own JSON text
std::vector<std::string> JsonArrayItems(const std::string &array);
bool ContainsIgnoreCase(const std::string &text, const std::string &query);
// Folds ASCII only, as ContainsIgnoreCase does
std::string Lower(std::string text);
std::string Trim(const std::string &text, const char *chars = " \t\r\n");
std::string Fill(std::string text, const std::string &slot,
                 const std::string &value);
void LoadPluginConfig();
void SetHotkeyFromString(const std::string &keyStr);
void LoadUITranslation(const std::string &json);
void StartPythonServer(bool openBrowser);
