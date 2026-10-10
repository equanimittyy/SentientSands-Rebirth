#pragma once

namespace MyGUI {
class Window;
class Button;
class EditBox;
class ListBox;
class TextBox;
class ComboBox;
class Widget;
} // namespace MyGUI

#include <mygui/MyGUI_Button.h>
#include <mygui/MyGUI_ComboBox.h>
#include <mygui/MyGUI_EditBox.h>
#include <mygui/MyGUI_ListBox.h>
#include <mygui/MyGUI_TextBox.h>
#include <mygui/MyGUI_Window.h>
#include <string>
#include <vector>
#include <windows.h>

namespace SentientSands {
namespace UI {

struct ChatTask {
  std::string json;
  std::string npcName;
  std::string handleStr;
  bool action;
};

struct LibraryTask {
  std::string npcName;
  std::string json;
  int request;
};

struct EventTask {
  std::string id;
  std::string json;
};

extern bool g_welcomeShown;
extern bool g_enableWelcome;
extern MyGUI::Button *g_welcomeCheckbox;

} // namespace UI
} // namespace SentientSands
