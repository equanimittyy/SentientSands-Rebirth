#include "LauncherWindow.h"
#include "EventsWindow.h"
#include "JournalWindow.h"
#include "../core/Comm.h"
#include "../core/Globals.h"
#include "LibraryWindow.h"
#include "../core/Utils.h"
#include "../game/Context.h"
#include "HelpWindow.h"
#include <shellapi.h>
#include <mygui/MyGUI_Button.h>
#include <mygui/MyGUI_Delegate.h>
#include <mygui/MyGUI_Gui.h>
#include <mygui/MyGUI_TextBox.h>
#include <mygui/MyGUI_Window.h>

namespace SentientSands {
namespace UI {

static MyGUI::Window *g_launcherWindow = nullptr;
static MyGUI::Window *g_cullWindow = nullptr;

static void CloseLauncherUI() { DestroyWindow(g_launcherWindow); }

static CloseAction g_launcherClose = {CloseLauncherUI};

static void OnLauncherLibraryClick(MyGUI::Widget *sender) { CreateLibraryUI(); }
static void OnLauncherEventsClick(MyGUI::Widget *sender) { CreateEventsUI(); }
static void OnLauncherJournalClick(MyGUI::Widget *sender) { CreateJournalUI(); }
static void OnLauncherHelpClick(MyGUI::Widget *sender) { CreateHelpUI(); }
static void OnLauncherWebPanelClick(MyGUI::Widget *sender) {
  ShellExecuteA(NULL, "open", "http://127.0.0.1:5000/", NULL, NULL,
                SW_SHOWNORMAL);
}
static void OnLauncherRestartClick(MyGUI::Widget *sender) {
  StartPythonServer(false);
}

static void CloseCullUI() { DestroyWindow(g_cullWindow); }

static CloseAction g_cullClose = {CloseCullUI};

void FinishCull(const std::string &data) {
  std::string tag, reply;
  if (!SplitTaggedReply(data, tag, reply))
    return;
  if (GetJsonValue(reply, "status") != "ok") {
    NotifyText(FailureText("Cull failed: ", reply));
    return;
  }
  NotifyText(T("Culled the data dated after: ") + GetJsonValue(reply, "time") +
             ". " + T("Dialogue lines: ") + GetJsonValue(reply, "dialogue") +
             ", " + T("events: ") + GetJsonValue(reply, "event") + ", " +
             T("rumors: ") + GetJsonValue(reply, "rumor") + ", " +
             T("profiles: ") + GetJsonValue(reply, "character") + ".");
}

static void OnCullConfirmClick(MyGUI::Widget *sender) {
  CloseCullUI();
  Log(LOG_INFO, "LAUNCHER: Requesting cull of future data...");
  PostForGameThread(L"/cull", GameReport(), "CULLED", "");
}

static void OnCullCancelClick(MyGUI::Widget *sender) { CloseCullUI(); }

static void OnLauncherCullClick(MyGUI::Widget *sender) {
  CloseCullUI();
  const MyGUI::UString lines[] = {
      Utf8ToWide(T("This deletes every NPC memory, event, rumor, and profile "
                   "of the active campaign")),
      Utf8ToWide(T("dated after the current game time.")),
      Utf8ToWide(T("The cull takes effect immediately and is irreversible!"))};
  OpenConfirm(g_cullWindow, "SentientSands_Cull", T("Cull Future Data"), lines,
              T("Cull"), OnCullConfirmClick, OnCullCancelClick, g_cullClose);
}

static const struct {
  const char *name;
  const char *key;
  ClickHandler onClick;
} LAUNCHER_BUTTONS[] = {
    {"SentientSands_LauncherLibBtn", "Dialogue Library", OnLauncherLibraryClick},
    {"SentientSands_LauncherEvtBtn", "Events", OnLauncherEventsClick},
    {"SentientSands_LauncherJournalBtn", "Journal", OnLauncherJournalClick},
    {"SentientSands_LauncherCullBtn", "Cull Future Data", OnLauncherCullClick},
    {"SentientSands_LauncherWebBtn", "Open Web App", OnLauncherWebPanelClick},
    {"SentientSands_LauncherRestartBtn", "Restart Server",
     OnLauncherRestartClick},
    {"SentientSands_LauncherHelpBtn", "Help", OnLauncherHelpClick},
};
static const size_t LAUNCHER_BUTTON_COUNT =
    sizeof(LAUNCHER_BUTTONS) / sizeof(LAUNCHER_BUTTONS[0]);

void CreateLauncherUI() {
  CloseLauncherUI();
  MyGUI::Widget *client =
      OpenWindow(g_launcherWindow, 0.82f, 0.1f, 0.15f, 0.74f,
                 MyGUI::Align::Right | MyGUI::Align::Top, "Popup",
                 "SentientSands_AIHub", T("SSR HUB"), g_launcherClose);
  for (size_t i = 0; client && i < LAUNCHER_BUTTON_COUNT; ++i)
    AddButton(client, T(LAUNCHER_BUTTONS[i].key), 0.05f, 0.02f + i * 0.137f,
              0.9f, 0.12f, MyGUI::Align::Top | MyGUI::Align::HStretch,
              LAUNCHER_BUTTONS[i].name, LAUNCHER_BUTTONS[i].onClick);
}

void RefreshLauncherUI() {
  if (!g_launcherWindow)
    return;
  g_launcherWindow->setCaption(Utf8ToWide(T("SSR HUB")).c_str());
  MyGUI::Widget *client = g_launcherWindow->getClientWidget();
  for (size_t i = 0; client && i < LAUNCHER_BUTTON_COUNT; ++i) {
    MyGUI::Widget *widget = client->findWidget(LAUNCHER_BUTTONS[i].name);
    MyGUI::Button *button =
        widget ? widget->castType<MyGUI::Button>(false) : nullptr;
    if (button)
      button->setCaption(Utf8ToWide(T(LAUNCHER_BUTTONS[i].key)).c_str());
  }
}

} // namespace UI
} // namespace SentientSands
