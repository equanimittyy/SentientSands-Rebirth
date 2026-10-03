#include "LauncherWindow.h"
#include "EventsWindow.h"
#include "../core/Comm.h"
#include "../core/Globals.h"
#include "LibraryWindow.h"
#include "../core/Utils.h"
#include "WelcomeWindow.h"
#include <shellapi.h>
#include <mygui/MyGUI_Button.h>
#include <mygui/MyGUI_Delegate.h>
#include <mygui/MyGUI_Gui.h>
#include <mygui/MyGUI_TextBox.h>
#include <mygui/MyGUI_Window.h>

namespace SentientSands {
namespace UI {

MyGUI::Window *g_launcherWindow = nullptr;
MyGUI::Window *g_cullWindow = nullptr;

void CloseLauncherUI() {
  if (g_launcherWindow) {
    if (MyGUI::Gui::getInstancePtr())
      MyGUI::Gui::getInstancePtr()->destroyWidget(g_launcherWindow);
    g_launcherWindow = nullptr;
  }
}

void OnLauncherLibraryClick(MyGUI::Widget *sender) { CreateLibraryUI(); }
void OnLauncherEventsClick(MyGUI::Widget *sender) { CreateEventsUI(); }
void OnLauncherWelcomeClick(MyGUI::Widget *sender) { CreateWelcomeUI(); }
void OnLauncherWebPanelClick(MyGUI::Widget *sender) {
  ShellExecuteA(NULL, "open", "http://127.0.0.1:5000/", NULL, NULL,
                SW_SHOWNORMAL);
}
void OnLauncherRestartClick(MyGUI::Widget *sender) { StartPythonServer(false); }

void CloseCullUI() {
  if (g_cullWindow) {
    if (MyGUI::Gui::getInstancePtr())
      MyGUI::Gui::getInstancePtr()->destroyWidget(g_cullWindow);
    g_cullWindow = nullptr;
  }
}

DWORD WINAPI CullThread(LPVOID lpParam) {
  Log(LOG_INFO, "LAUNCHER: Requesting cull of future data...");
  std::string response = PostToPythonWithResponse(L"/cull", "");
  std::string text;
  if (GetJsonValue(response, "status") == "ok") {
    text = T("Culled the data dated after: ") +
           GetJsonValue(response, "time") + ". " + T("Dialogue lines: ") +
           GetJsonValue(response, "dialogue") + ", " + T("events: ") +
           GetJsonValue(response, "event") + ", " + T("rumors: ") +
           GetJsonValue(response, "rumor") + ".";
  } else {
    std::string error = GetJsonValue(response, "message");
    if (error.empty())
      error = GetJsonValue(response, "error");
    text = T("Cull failed: ") + (error.empty() ? T("Unknown error") : error);
  }
  EnterCriticalSection(&g_msgMutex);
  g_messageQueue.push_back("NOTIFY: " + text);
  LeaveCriticalSection(&g_msgMutex);
  return 0;
}

void OnCullConfirmClick(MyGUI::Widget *sender) {
  CloseCullUI();
  CreateThread(NULL, 0, CullThread, NULL, 0, NULL);
}

void OnCullCancelClick(MyGUI::Widget *sender) { CloseCullUI(); }

void OnCullWindowButtonPressed(MyGUI::Window *sender, const std::string &name) {
  if (name == "close")
    CloseCullUI();
}

void CreateCullUI() {
  MyGUI::Gui *gui = MyGUI::Gui::getInstancePtr();
  if (!gui)
    return;
  if (g_cullWindow)
    CloseCullUI();

  g_cullWindow = gui->createWidgetReal<MyGUI::Window>(
      "Kenshi_WindowCX", 0.30f, 0.25f, 0.40f, 0.25f, MyGUI::Align::Center,
      "Popup", "SentientSands_CullWindow");
  g_cullWindow->setCaption(Utf8ToWide(T("Cull Future Data")).c_str());
  g_cullWindow->eventWindowButtonPressed +=
      MyGUI::newDelegate(OnCullWindowButtonPressed);

  MyGUI::Widget *client = g_cullWindow->getClientWidget();

  const char *lineKeys[] = {
      "This deletes every NPC memory, event, and rumor of the active campaign",
      "dated after the current game time.",
      "The cull takes effect immediately and is irreversible!"};
  const char *lineNames[] = {"SentientSands_CullL1", "SentientSands_CullL2",
                             "SentientSands_CullWarning"};
  float lineTops[] = {0.06f, 0.19f, 0.36f};
  for (int i = 0; i < 3; i++) {
    MyGUI::TextBox *line = client->createWidgetReal<MyGUI::TextBox>(
        "Kenshi_TextboxStandardText", 0.05f, lineTops[i], 0.9f, 0.11f,
        MyGUI::Align::Top | MyGUI::Align::HStretch, lineNames[i]);
    line->setCaption(Utf8ToWide(T(lineKeys[i])).c_str());
    line->setTextAlign(MyGUI::Align::Center);
    line->setTextColour(i == 2 ? MyGUI::Colour(1.0f, 0.6f, 0.6f)
                               : MyGUI::Colour(0.85f, 0.85f, 0.85f));
  }

  MyGUI::Button *cullBtn = client->createWidgetReal<MyGUI::Button>(
      "Kenshi_Button1", 0.10f, 0.62f, 0.38f, 0.30f,
      MyGUI::Align::Bottom | MyGUI::Align::Left,
      "SentientSands_CullConfirmBtn");
  cullBtn->setCaption(Utf8ToWide(T("Cull")).c_str());
  cullBtn->eventMouseButtonClick += MyGUI::newDelegate(OnCullConfirmClick);

  MyGUI::Button *cancelBtn = client->createWidgetReal<MyGUI::Button>(
      "Kenshi_Button1", 0.52f, 0.62f, 0.38f, 0.30f,
      MyGUI::Align::Bottom | MyGUI::Align::Right,
      "SentientSands_CullCancelBtn");
  cancelBtn->setCaption(Utf8ToWide(T("Cancel")).c_str());
  cancelBtn->eventMouseButtonClick += MyGUI::newDelegate(OnCullCancelClick);
}

void OnLauncherCullClick(MyGUI::Widget *sender) { CreateCullUI(); }

void OnLauncherWindowButtonPressed(MyGUI::Window *sender,
                                   const std::string &name) {
  if (name == "close")
    CloseLauncherUI();
}

void CreateLauncherUI() {
  MyGUI::Gui *gui = MyGUI::Gui::getInstancePtr();
  if (!gui)
    return;
  if (g_launcherWindow)
    CloseLauncherUI();

  g_launcherWindow = gui->createWidgetReal<MyGUI::Window>(
      "Kenshi_WindowCX", 0.82f, 0.1f, 0.15f, 0.74f,
      MyGUI::Align::Right | MyGUI::Align::Top, "Popup", "SentientSands_AIHub");
  g_launcherWindow->setCaption(Utf8ToWide(T("SSR HUB")).c_str());
  g_launcherWindow->eventWindowButtonPressed +=
      MyGUI::newDelegate(OnLauncherWindowButtonPressed);

  MyGUI::Widget *client = g_launcherWindow->getClientWidget();
  float yDelta = 0.16f;
  float yPos = 0.02f;
  float bH = 0.14f;

  MyGUI::Button *libBtn = client->createWidgetReal<MyGUI::Button>(
      "Kenshi_Button1", 0.05f, yPos, 0.9f, bH,
      MyGUI::Align::Top | MyGUI::Align::HStretch,
      "SentientSands_LauncherLibBtn");
  libBtn->setCaption(Utf8ToWide(T("Dialogue Library")).c_str());
  libBtn->eventMouseButtonClick += MyGUI::newDelegate(OnLauncherLibraryClick);
  yPos += yDelta;

  MyGUI::Button *evtBtn = client->createWidgetReal<MyGUI::Button>(
      "Kenshi_Button1", 0.05f, yPos, 0.9f, bH,
      MyGUI::Align::Top | MyGUI::Align::HStretch,
      "SentientSands_LauncherEvtBtn");
  evtBtn->setCaption(Utf8ToWide(T("World Event Log")).c_str());
  evtBtn->eventMouseButtonClick += MyGUI::newDelegate(OnLauncherEventsClick);
  yPos += yDelta;

  MyGUI::Button *cullBtn = client->createWidgetReal<MyGUI::Button>(
      "Kenshi_Button1", 0.05f, yPos, 0.9f, bH,
      MyGUI::Align::Top | MyGUI::Align::HStretch,
      "SentientSands_LauncherCullBtn");
  cullBtn->setCaption(Utf8ToWide(T("Cull Future Data")).c_str());
  cullBtn->eventMouseButtonClick += MyGUI::newDelegate(OnLauncherCullClick);
  yPos += yDelta;

  MyGUI::Button *webBtn = client->createWidgetReal<MyGUI::Button>(
      "Kenshi_Button1", 0.05f, yPos, 0.9f, bH,
      MyGUI::Align::Top | MyGUI::Align::HStretch,
      "SentientSands_LauncherWebBtn");
  webBtn->setCaption(Utf8ToWide(T("Open Web Panel")).c_str());
  webBtn->eventMouseButtonClick += MyGUI::newDelegate(OnLauncherWebPanelClick);
  yPos += yDelta;

  MyGUI::Button *restartBtn = client->createWidgetReal<MyGUI::Button>(
      "Kenshi_Button1", 0.05f, yPos, 0.9f, bH,
      MyGUI::Align::Top | MyGUI::Align::HStretch,
      "SentientSands_LauncherRestartBtn");
  restartBtn->setCaption(Utf8ToWide(T("Restart Server")).c_str());
  restartBtn->eventMouseButtonClick +=
      MyGUI::newDelegate(OnLauncherRestartClick);
  yPos += yDelta;

  MyGUI::Button *welBtn = client->createWidgetReal<MyGUI::Button>(
      "Kenshi_Button1", 0.05f, yPos, 0.9f, bH,
      MyGUI::Align::Top | MyGUI::Align::HStretch,
      "SentientSands_LauncherWelBtn");
  welBtn->setCaption(Utf8ToWide(T("Welcome Popup")).c_str());
  welBtn->eventMouseButtonClick += MyGUI::newDelegate(OnLauncherWelcomeClick);
}

void RefreshLauncherUI() {
  if (!g_launcherWindow)
    return;
  g_launcherWindow->setCaption(Utf8ToWide(T("SSR HUB")).c_str());
  MyGUI::Widget *client = g_launcherWindow->getClientWidget();
  if (!client)
    return;

  struct RefreshMap {
    std::string name;
    std::string key;
  };
  RefreshMap items[] = {{"SentientSands_LauncherLibBtn", "Dialogue Library"},
                        {"SentientSands_LauncherEvtBtn", "World Event Log"},
                        {"SentientSands_LauncherWebBtn", "Open Web Panel"},
                        {"SentientSands_LauncherRestartBtn", "Restart Server"},
                        {"SentientSands_LauncherWelBtn", "Welcome Popup"},
                        {"SentientSands_LauncherCullBtn", "Cull Future Data"}};

  for (int i = 0; i < sizeof(items) / sizeof(items[0]); ++i) {
    const RefreshMap &item = items[i];
    MyGUI::Widget *w = client->findWidget(item.name);
    if (w) {
      if (w->castType<MyGUI::Button>(false))
        w->castType<MyGUI::Button>()->setCaption(
            Utf8ToWide(T(item.key)).c_str());
      else if (w->castType<MyGUI::TextBox>(false))
        w->castType<MyGUI::TextBox>()->setCaption(
            Utf8ToWide(T(item.key)).c_str());
    }
  }
}

} // namespace UI
} // namespace SentientSands
