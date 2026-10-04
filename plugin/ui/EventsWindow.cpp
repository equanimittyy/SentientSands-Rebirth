#include "EventsWindow.h"
#include "../core/Comm.h"
#include "../core/Globals.h"
#include "../core/Utils.h"
#include "../game/Context.h"
#include <mygui/MyGUI_Button.h>
#include <mygui/MyGUI_Delegate.h>
#include <mygui/MyGUI_Gui.h>
#include <mygui/MyGUI_ListBox.h>
#include <mygui/MyGUI_Window.h>

namespace SentientSands {
namespace UI {

MyGUI::Window *g_eventsWindow = nullptr;
MyGUI::ListBox *g_eventsList = nullptr;
MyGUI::ListBox *g_eventsText = nullptr;
MyGUI::EditBox *g_eventsSearch = nullptr;
std::vector<std::string> g_eventsStorageIds;
std::vector<std::string> g_eventsAllIds;
std::vector<std::string> g_eventsAllTitles;
std::vector<std::string> g_eventsAllTexts;

void CloseEventsUI() {
  if (g_eventsWindow) {
    if (MyGUI::Gui::getInstancePtr())
      MyGUI::Gui::getInstancePtr()->destroyWidget(g_eventsWindow);
    g_eventsWindow = nullptr;
    g_eventsList = nullptr;
    g_eventsText = nullptr;
    g_eventsSearch = nullptr;
    g_eventsStorageIds.clear();
    g_eventsAllIds.clear();
    g_eventsAllTitles.clear();
    g_eventsAllTexts.clear();
  }
}

void ApplyEventsFilter(const std::string &keepId) {
  g_eventsList->removeAllItems();
  g_eventsStorageIds.clear();
  std::string query =
      g_eventsSearch ? g_eventsSearch->getOnlyText().asUTF8() : "";
  for (size_t i = 0; i < g_eventsAllIds.size(); i++) {
    if (!ContainsIgnoreCase(g_eventsAllTexts[i], query))
      continue;
    g_eventsList->addItem(Utf8ToWide(g_eventsAllTitles[i]).c_str());
    g_eventsStorageIds.push_back(g_eventsAllIds[i]);
    if (g_eventsAllIds[i] == keepId)
      g_eventsList->setIndexSelected(g_eventsStorageIds.size() - 1);
  }
}

void OnEventsSearchChange(MyGUI::EditBox *sender) {
  size_t index = g_eventsList->getIndexSelected();
  ApplyEventsFilter(index < g_eventsStorageIds.size()
                        ? g_eventsStorageIds[index]
                        : "");
}

void PopulateEventsUI(const std::string &data) {
  if (!g_eventsList)
    return;
  g_eventsAllIds.clear();
  g_eventsAllTitles.clear();
  g_eventsAllTexts.clear();
  // Flask sorts the keys, so each object's "inner" and "title" lie between its
  // "id" and the next one; an escaped quote in a value cannot fake an "id": key
  size_t cur = data.find("\"id\":");
  while (cur != std::string::npos) {
    size_t next = data.find("\"id\":", cur + 5);
    std::string entry = data.substr(cur, next - cur);
    g_eventsAllIds.push_back(GetJsonValue(entry, "id"));
    g_eventsAllTitles.push_back(GetJsonValue(entry, "title"));
    g_eventsAllTexts.push_back(GetJsonValue(entry, "inner"));
    cur = next;
  }
  ApplyEventsFilter("");
}

void SetEventsText(const std::string &data) {
  if (!g_eventsText)
    return;
  Log(LOG_DEBUG, "EVENTS_WINDOW: Received " + ToString((int)data.length()) +
                     " bytes");
  size_t start = (data.length() > 0 && data[0] == ' ') ? 1 : 0;
  std::stringstream ss(data.substr(start));
  std::string line;
  g_eventsText->removeAllItems();
  while (std::getline(ss, line)) {
    g_eventsText->addItem(Utf8ToWide(line).c_str());
  }
}

void OnSynthesizeClick(MyGUI::Widget *sender) {
  if (g_eventsText) {
    g_eventsText->removeAllItems();
    g_eventsText->addItem(
        Utf8ToWide(T("Synthesizing world narrative... Please wait.")).c_str());
  }
  CreateThread(NULL, 0, SynthesizeThread, new std::string(GameReport()), 0,
               NULL);
}

DWORD WINAPI SynthesizeThread(LPVOID lpParam) {
  std::string *report = (std::string *)lpParam;
  Log(LOG_INFO, "EVENTS_WINDOW: Requesting manual synthesis...");
  std::string response = PostToPythonWithResponse(L"/synthesize", *report);
  delete report;
  if (!response.empty()) {
    std::string rumor = GetJsonValue(response, "rumor");
    if (!rumor.empty()) {
      Log(LOG_INFO, "EVENTS_WINDOW: Synthesis successful: " + rumor);
      CreateThread(NULL, 0, EventsResponseThread, NULL, 0, NULL);
    } else {
      std::string error = GetJsonValue(response, "message");
      std::string msg = "CMD: SET_EVENTS_TEXT: " + T("Synthesis failed: ") +
                        (error.empty() ? T("Unknown error") : error);
      EnterCriticalSection(&g_msgMutex);
      g_messageQueue.push_back(msg);
      LeaveCriticalSection(&g_msgMutex);
    }
  }
  return 0;
}

void OnEventsSelect(MyGUI::ListBox *sender, size_t index) {
  if (index == MyGUI::ITEM_NONE)
    return;
  if (index >= g_eventsStorageIds.size())
    return;
  std::string dayId = g_eventsStorageIds[index];

  if (g_eventsText) {
    g_eventsText->removeAllItems();
    g_eventsText->addItem(
        Utf8ToWide(T("Reading global event: ") + dayId).c_str());
  }

  EventTask *t = new EventTask();
  t->day = dayId;
  t->json = "{\"day\":\"" + dayId + "\"}";
  CreateThread(NULL, 0, EventsContentThread, t, 0, NULL);
}

DWORD WINAPI EventsContentThread(LPVOID lpParam) {
  EventTask *t = (EventTask *)lpParam;
  Log(LOG_DEBUG, "EVENTS_WINDOW: Fetching content for Day " + t->day);
  std::string response = PostToPythonWithResponse(L"/events/content", t->json);
  if (!response.empty()) {
    std::string content = GetJsonValue(response, "text");
    if (!content.empty()) {
      std::string pipeMsg = "CMD: SET_EVENTS_TEXT: " + content;
      EnterCriticalSection(&g_msgMutex);
      g_messageQueue.push_back(pipeMsg);
      LeaveCriticalSection(&g_msgMutex);
    }
  }
  delete t;
  return 0;
}

DWORD WINAPI EventsResponseThread(LPVOID lpParam) {
  Log(LOG_DEBUG, "EVENTS_WINDOW: Fetching events list...");
  std::string response = PostToPythonWithResponse(L"/events", "");
  if (!response.empty()) {
    std::string eventsJson = GetJsonValue(response, "events");
    if (!eventsJson.empty()) {
      std::string pipeMsg = "CMD: POPULATE_EVENTS: " + eventsJson;
      EnterCriticalSection(&g_msgMutex);
      g_messageQueue.push_back(pipeMsg);
      LeaveCriticalSection(&g_msgMutex);
    }
  }
  return 0;
}

void OnEventsWindowClose(MyGUI::Window *sender, const std::string &name) {
  CloseEventsUI();
}

void CreateEventsUI() {
  MyGUI::Gui *gui = MyGUI::Gui::getInstancePtr();
  if (!gui)
    return;
  if (g_eventsWindow)
    CloseEventsUI();

  g_eventsWindow = gui->createWidgetReal<MyGUI::Window>(
      "Kenshi_WindowCX", 0.1f, 0.1f, 0.8f, 0.8f, MyGUI::Align::Center, "Popup",
      "SentientSands_EventsWindow");
  g_eventsWindow->setCaption(Utf8ToWide(T("Dynamic World Events Log")).c_str());
  g_eventsWindow->eventWindowButtonPressed +=
      MyGUI::newDelegate(OnEventsWindowClose);

  MyGUI::Widget *client = g_eventsWindow->getClientWidget();

  MyGUI::TextBox *searchLabel = client->createWidgetReal<MyGUI::TextBox>(
      "Kenshi_TextboxStandardText", 0.02f, 0.02f, 0.07f, 0.06f,
      MyGUI::Align::Left | MyGUI::Align::Top,
      "SentientSands_EventsSearchLabel");
  searchLabel->setCaption(Utf8ToWide(T("Search")).c_str());
  searchLabel->setTextAlign(MyGUI::Align::Left | MyGUI::Align::VCenter);

  g_eventsSearch = client->createWidgetReal<MyGUI::EditBox>(
      "Kenshi_EditBox", 0.09f, 0.02f, 0.21f, 0.06f,
      MyGUI::Align::Left | MyGUI::Align::Top, "SentientSands_EventsSearch");
  g_eventsSearch->setEditMultiLine(false);
  g_eventsSearch->setEditWordWrap(false);
  g_eventsSearch->setVisibleVScroll(false);
  g_eventsSearch->setTextAlign(MyGUI::Align::Default);
  g_eventsSearch->setFontHeight(18);
  g_eventsSearch->eventEditTextChange +=
      MyGUI::newDelegate(OnEventsSearchChange);

  g_eventsList = client->createWidgetReal<MyGUI::ListBox>(
      "Kenshi_ListBox", 0.02f, 0.10f, 0.28f, 0.74f,
      MyGUI::Align::Left | MyGUI::Align::VStretch, "SentientSands_EventsList");
  g_eventsList->eventListSelectAccept += MyGUI::newDelegate(OnEventsSelect);
  g_eventsList->eventListChangePosition += MyGUI::newDelegate(OnEventsSelect);

  MyGUI::Button *btnSync = client->createWidgetReal<MyGUI::Button>(
      "Kenshi_Button1", 0.02f, 0.86f, 0.28f, 0.08f,
      MyGUI::Align::Left | MyGUI::Align::Bottom, "SentientSands_SyncButton");
  btnSync->setCaption(Utf8ToWide(T("Generate World Event")).c_str());
  btnSync->eventMouseButtonClick += MyGUI::newDelegate(OnSynthesizeClick);

  g_eventsText = client->createWidgetReal<MyGUI::ListBox>(
      "Kenshi_ListBox", 0.32f, 0.02f, 0.66f, 0.96f, MyGUI::Align::Default,
      "SentientSands_EventsText");
  g_eventsText->addItem(
      Utf8ToWide(T("Select an entry to view details.")).c_str());

  CreateThread(NULL, 0, EventsResponseThread, NULL, 0, NULL);
}

} // namespace UI
} // namespace SentientSands
