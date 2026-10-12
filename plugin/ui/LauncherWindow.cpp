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
void OnLauncherJournalClick(MyGUI::Widget *sender) { CreateJournalUI(); }
void OnLauncherHelpClick(MyGUI::Widget *sender) { CreateHelpUI(); }
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

void FinishCull(const std::string &data) {
  std::string tag, reply;
  if (!SplitTaggedReply(data, tag, reply))
    return;
  if (GetJsonValue(reply, "status") != "ok") {
    QueueMessage("NOTIFY: " + FailureText("Cull failed: ", reply));
    return;
  }
  QueueMessage("NOTIFY: " + T("Culled the data dated after: ") +
               GetJsonValue(reply, "time") + ". " + T("Dialogue lines: ") +
               GetJsonValue(reply, "dialogue") + ", " + T("events: ") +
               GetJsonValue(reply, "event") + ", " + T("rumors: ") +
               GetJsonValue(reply, "rumor") + ", " + T("profiles: ") +
               GetJsonValue(reply, "character") + ".");
}

void OnCullConfirmClick(MyGUI::Widget *sender) {
  CloseCullUI();
  Log(LOG_INFO, "LAUNCHER: Requesting cull of future data...");
  PostForGameThread(L"/cull", GameReport(), "CULLED", "");
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
      "This deletes every NPC memory, event, rumor, and profile of the active campaign",
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
  float yDelta = 0.137f;
  float yPos = 0.02f;
  float bH = 0.12f;

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
  evtBtn->setCaption(Utf8ToWide(T("Events")).c_str());
  evtBtn->eventMouseButtonClick += MyGUI::newDelegate(OnLauncherEventsClick);
  yPos += yDelta;

  MyGUI::Button *journalBtn = client->createWidgetReal<MyGUI::Button>(
      "Kenshi_Button1", 0.05f, yPos, 0.9f, bH,
      MyGUI::Align::Top | MyGUI::Align::HStretch,
      "SentientSands_LauncherJournalBtn");
  journalBtn->setCaption(Utf8ToWide(T("Journal")).c_str());
  journalBtn->eventMouseButtonClick +=
      MyGUI::newDelegate(OnLauncherJournalClick);
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
  webBtn->setCaption(Utf8ToWide(T("Open Web App")).c_str());
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

  MyGUI::Button *helpBtn = client->createWidgetReal<MyGUI::Button>(
      "Kenshi_Button1", 0.05f, yPos, 0.9f, bH,
      MyGUI::Align::Top | MyGUI::Align::HStretch,
      "SentientSands_LauncherHelpBtn");
  helpBtn->setCaption(Utf8ToWide(T("Help")).c_str());
  helpBtn->eventMouseButtonClick += MyGUI::newDelegate(OnLauncherHelpClick);
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
                        {"SentientSands_LauncherEvtBtn", "Events"},
                        {"SentientSands_LauncherJournalBtn", "Journal"},
                        {"SentientSands_LauncherWebBtn", "Open Web App"},
                        {"SentientSands_LauncherRestartBtn", "Restart Server"},
                        {"SentientSands_LauncherHelpBtn", "Help"},
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
