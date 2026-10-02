#include "LauncherWindow.h"
#include "CampaignsWindow.h"
#include "EventsWindow.h"
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

void CloseLauncherUI() {
  if (g_launcherWindow) {
    if (MyGUI::Gui::getInstancePtr())
      MyGUI::Gui::getInstancePtr()->destroyWidget(g_launcherWindow);
    g_launcherWindow = nullptr;
  }
}

void OnLauncherLibraryClick(MyGUI::Widget *sender) { CreateLibraryUI(); }
void OnLauncherEventsClick(MyGUI::Widget *sender) { CreateEventsUI(); }
void OnLauncherCampaignsClick(MyGUI::Widget *sender) { CreateCampaignsUI(); }
void OnLauncherWelcomeClick(MyGUI::Widget *sender) { CreateWelcomeUI(); }
void OnLauncherWebPanelClick(MyGUI::Widget *sender) {
  ShellExecuteA(NULL, "open", "http://127.0.0.1:5000/", NULL, NULL,
                SW_SHOWNORMAL);
}
void OnLauncherRestartClick(MyGUI::Widget *sender) { StartPythonServer(false); }

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
      "Kenshi_WindowCX", 0.82f, 0.1f, 0.15f, 0.62f,
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

  MyGUI::Button *campBtn = client->createWidgetReal<MyGUI::Button>(
      "Kenshi_Button1", 0.05f, yPos, 0.9f, bH,
      MyGUI::Align::Top | MyGUI::Align::HStretch,
      "SentientSands_LauncherCampBtn");
  campBtn->setCaption(Utf8ToWide(T("Campaign Manager")).c_str());
  campBtn->eventMouseButtonClick +=
      MyGUI::newDelegate(OnLauncherCampaignsClick);
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
                        {"SentientSands_LauncherCampBtn", "Campaign Manager"},
                        {"SentientSands_LauncherWebBtn", "Open Web Panel"},
                        {"SentientSands_LauncherRestartBtn", "Restart Server"},
                        {"SentientSands_LauncherWelBtn", "Welcome Popup"}};

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
