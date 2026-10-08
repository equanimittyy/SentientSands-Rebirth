#include "EventsWindow.h"
#include "../core/Comm.h"
#include "../core/Globals.h"
#include "../core/Utils.h"
#include "LibraryWindow.h"
#include <algorithm>
#include <mygui/MyGUI_Delegate.h>
#include <mygui/MyGUI_Gui.h>
#include <mygui/MyGUI_ListBox.h>
#include <mygui/MyGUI_Window.h>

namespace SentientSands {
namespace UI {

static const char *EVENT_KINDS[] = {"all",    "kill", "capture",
                                   "custom", "auto", "bounty"};
static const char *EVENT_KIND_LABELS[] = {"All kinds", "Kill", "Capture",
                                         "Custom",    "Auto", "Bounty"};
static const int EVENT_KIND_COUNT = sizeof(EVENT_KINDS) / sizeof(EVENT_KINDS[0]);

MyGUI::Window *g_eventsWindow = nullptr;
MyGUI::ListBox *g_eventsList = nullptr;
MyGUI::ListBox *g_eventsText = nullptr;
MyGUI::EditBox *g_eventsSearch = nullptr;
MyGUI::Button *g_eventsKindBtn = nullptr;
std::vector<std::string> g_eventsStorageIds;
std::vector<std::string> g_eventsAllIds;
std::vector<std::string> g_eventsAllTitles;
std::vector<std::string> g_eventsAllTexts;
std::vector<std::string> g_eventsAllInstructions;
std::vector<std::string> g_eventsAllKinds;
std::vector<std::string> g_eventsAllRumors;
int g_eventsKind = 0;
std::string g_eventsCampaign;
std::string g_eventsSelectId;

MyGUI::Window *g_rumorWindow = nullptr;
MyGUI::EditBox *g_rumorBox = nullptr;
MyGUI::Button *g_rumorConfirmBtn = nullptr;
MyGUI::TextBox *g_rumorStatus = nullptr;
int g_rumorRequest = 0;
bool g_rumorWritten = false;
std::string g_rumorNotable;
std::string g_rumorLine;
std::string g_rumorInstruction;
std::string g_rumorCampaign;
std::string g_rumorKind;
std::string g_rumorId;

struct RumorTask {
  int request;
  std::wstring endpoint;
  std::string json;
  std::string command;
};

// The player can close the window, or open it for another event, while a
// request runs, so each close makes the pending reply stale
void CloseRumorUI() {
  g_rumorRequest++;
  if (!g_rumorWindow)
    return;
  if (MyGUI::Gui::getInstancePtr())
    MyGUI::Gui::getInstancePtr()->destroyWidget(g_rumorWindow);
  g_rumorWindow = nullptr;
  g_rumorBox = nullptr;
  g_rumorConfirmBtn = nullptr;
  g_rumorStatus = nullptr;
}

void CloseEventsUI() {
  CloseRumorUI();
  if (g_eventsWindow) {
    if (MyGUI::Gui::getInstancePtr())
      MyGUI::Gui::getInstancePtr()->destroyWidget(g_eventsWindow);
    g_eventsWindow = nullptr;
    g_eventsList = nullptr;
    g_eventsText = nullptr;
    g_eventsSearch = nullptr;
    g_eventsKindBtn = nullptr;
    g_eventsStorageIds.clear();
    g_eventsAllIds.clear();
    g_eventsAllTitles.clear();
    g_eventsAllTexts.clear();
    g_eventsAllInstructions.clear();
    g_eventsAllKinds.clear();
    g_eventsAllRumors.clear();
    g_eventsKind = 0;
    g_eventsSelectId.clear();
  }
}

void ApplyEventsFilter(const std::string &keepId) {
  g_eventsList->removeAllItems();
  g_eventsStorageIds.clear();
  std::string query =
      g_eventsSearch ? g_eventsSearch->getOnlyText().asUTF8() : "";
  for (size_t i = 0; i < g_eventsAllIds.size(); i++) {
    if (g_eventsKind != 0 && g_eventsAllKinds[i] != EVENT_KINDS[g_eventsKind])
      continue;
    if (!ContainsIgnoreCase(g_eventsAllTexts[i], query))
      continue;
    g_eventsList->addItem(Utf8ToWide(g_eventsAllTitles[i]).c_str());
    g_eventsStorageIds.push_back(g_eventsAllIds[i]);
    if (g_eventsAllIds[i] == keepId)
      g_eventsList->setIndexSelected(g_eventsStorageIds.size() - 1);
  }
}

std::string SelectedEventId() {
  size_t index = g_eventsList->getIndexSelected();
  return index < g_eventsStorageIds.size() ? g_eventsStorageIds[index] : "";
}

void OnEventsSearchChange(MyGUI::EditBox *sender) {
  ApplyEventsFilter(SelectedEventId());
}

int CountEventsOfKind(int kind) {
  if (kind == 0)
    return (int)g_eventsAllKinds.size();
  return (int)std::count(g_eventsAllKinds.begin(), g_eventsAllKinds.end(),
                         EVENT_KINDS[kind]);
}

void ShowEventsKind() {
  if (CountEventsOfKind(g_eventsKind) == 0)
    g_eventsKind = 0;
  g_eventsKindBtn->setCaption(
      Utf8ToWide(T("Show: ") + T(EVENT_KIND_LABELS[g_eventsKind]) + " (" +
                 ToString(CountEventsOfKind(g_eventsKind)) + ")")
          .c_str());
}

void OnEventsKindClick(MyGUI::Widget *sender) {
  do
    g_eventsKind = (g_eventsKind + 1) % EVENT_KIND_COUNT;
  while (g_eventsKind != 0 && CountEventsOfKind(g_eventsKind) == 0);
  ShowEventsKind();
  ApplyEventsFilter(SelectedEventId());
}

void PopulateEventsUI(const std::string &data) {
  if (!g_eventsList)
    return;
  std::string keepId =
      g_eventsSelectId.empty() ? SelectedEventId() : g_eventsSelectId;
  g_eventsSelectId.clear();
  g_eventsCampaign = GetJsonValue(data, "campaign");
  std::string events = GetJsonValue(data, "events");
  g_eventsAllIds.clear();
  g_eventsAllTitles.clear();
  g_eventsAllTexts.clear();
  g_eventsAllInstructions.clear();
  g_eventsAllKinds.clear();
  g_eventsAllRumors.clear();
  // Flask sorts the keys, so each object's other keys lie between its "id" and
  // the next one; an escaped quote in a value cannot fake an "id": key
  size_t cur = events.find("\"id\":");
  while (cur != std::string::npos) {
    size_t next = events.find("\"id\":", cur + 5);
    std::string entry = events.substr(cur, next - cur);
    g_eventsAllIds.push_back(GetJsonValue(entry, "id"));
    g_eventsAllTitles.push_back(GetJsonValue(entry, "title"));
    g_eventsAllTexts.push_back(GetJsonValue(entry, "inner"));
    g_eventsAllInstructions.push_back(GetJsonValue(entry, "instruction"));
    g_eventsAllKinds.push_back(GetJsonValue(entry, "kind"));
    g_eventsAllRumors.push_back(GetJsonValue(entry, "rumor"));
    cur = next;
  }
  ShowEventsKind();
  ApplyEventsFilter(keepId);
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

void ShowEventContent(const std::string &id) {
  if (g_eventsText) {
    g_eventsText->removeAllItems();
    g_eventsText->addItem(Utf8ToWide(T("Loading the event...")).c_str());
  }
  EventTask *t = new EventTask();
  t->id = id;
  t->json = "{\"id\":\"" + EscapeJSON(id) + "\"}";
  CreateThread(NULL, 0, EventsContentThread, t, 0, NULL);
}

void OnEventsSelect(MyGUI::ListBox *sender, size_t index) {
  if (index == MyGUI::ITEM_NONE)
    return;
  if (index >= g_eventsStorageIds.size())
    return;
  ShowEventContent(g_eventsStorageIds[index]);
}

DWORD WINAPI EventsContentThread(LPVOID lpParam) {
  EventTask *t = (EventTask *)lpParam;
  Log(LOG_DEBUG, "EVENTS_WINDOW: Fetching content for event " + t->id);
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
  if (GetJsonValue(response, "status") == "ok") {
    std::string pipeMsg = "CMD: POPULATE_EVENTS: " + response;
    EnterCriticalSection(&g_msgMutex);
    g_messageQueue.push_back(pipeMsg);
    LeaveCriticalSection(&g_msgMutex);
  }
  return 0;
}

void SetRumorStatus(const std::string &text) {
  if (g_rumorStatus)
    g_rumorStatus->setCaption(Utf8ToWide(text).c_str());
}

DWORD WINAPI RumorThread(LPVOID lpParam) {
  RumorTask *t = (RumorTask *)lpParam;
  std::string response = PostToPythonWithResponse(t->endpoint, t->json);
  std::string pipeMsg =
      "CMD: " + t->command + ": " + ToString(t->request) + "|" + response;
  EnterCriticalSection(&g_msgMutex);
  g_messageQueue.push_back(pipeMsg);
  LeaveCriticalSection(&g_msgMutex);
  delete t;
  return 0;
}

void StartRumorRequest(const wchar_t *endpoint, const std::string &json,
                       const std::string &command) {
  if (g_rumorConfirmBtn)
    g_rumorConfirmBtn->setEnabled(false);
  RumorTask *t = new RumorTask();
  t->request = g_rumorRequest;
  t->endpoint = endpoint;
  t->json = json;
  t->command = command;
  CreateThread(NULL, 0, RumorThread, t, 0, NULL);
}

bool TakeRumorReply(const std::string &data, std::string &reply) {
  size_t sep = data.find('|');
  if (sep == std::string::npos || atoi(data.c_str()) != g_rumorRequest)
    return false;
  reply = data.substr(sep + 1);
  return true;
}

void ShowRumorFailure(const std::string &prefixKey, const std::string &reply) {
  std::string error = GetJsonValue(reply, "message");
  std::string text =
      T(prefixKey) + (error.empty() ? T("Unknown error") : error);
  // Edit Rumor opens no window until the stored text arrives
  if (!g_rumorWindow) {
    SetEventsText(text);
    return;
  }
  SetRumorStatus(text);
  g_rumorConfirmBtn->setEnabled(true);
}

void OnRumorCancelClick(MyGUI::Widget *sender) { CloseRumorUI(); }

void OnRumorWindowButtonPressed(MyGUI::Window *sender,
                                const std::string &name) {
  if (name == "close")
    CloseRumorUI();
}

MyGUI::Widget *CreateRumorWindow(const char *captionKey, const char *confirmKey,
                                 void (*onConfirm)(MyGUI::Widget *),
                                 const char *cancelKey) {
  MyGUI::Gui *gui = MyGUI::Gui::getInstancePtr();
  if (!gui)
    return nullptr;
  CloseRumorUI();
  g_rumorWindow = gui->createWidgetReal<MyGUI::Window>(
      "Kenshi_WindowCX", 0.28f, 0.22f, 0.44f, 0.50f, MyGUI::Align::Center,
      "Popup", "SentientSands_RumorWindow");
  g_rumorWindow->setCaption(Utf8ToWide(T(captionKey)).c_str());
  g_rumorWindow->eventWindowButtonPressed +=
      MyGUI::newDelegate(OnRumorWindowButtonPressed);
  MyGUI::Widget *client = g_rumorWindow->getClientWidget();
  AddBioLine(client, g_rumorLine, 0.03f, "SentientSands_RumorLine");
  g_rumorStatus = AddBioLine(client, "", 0.76f, "SentientSands_RumorStatus");

  g_rumorConfirmBtn = client->createWidgetReal<MyGUI::Button>(
      "Kenshi_Button1", 0.10f, 0.87f, 0.38f, 0.10f,
      MyGUI::Align::Bottom | MyGUI::Align::Left,
      "SentientSands_RumorConfirmBtn");
  g_rumorConfirmBtn->setCaption(Utf8ToWide(T(confirmKey)).c_str());
  g_rumorConfirmBtn->eventMouseButtonClick += MyGUI::newDelegate(onConfirm);

  MyGUI::Button *cancelBtn = client->createWidgetReal<MyGUI::Button>(
      "Kenshi_Button1", 0.52f, 0.87f, 0.38f, 0.10f,
      MyGUI::Align::Bottom | MyGUI::Align::Right,
      "SentientSands_RumorCancelBtn");
  cancelBtn->setCaption(Utf8ToWide(T(cancelKey)).c_str());
  cancelBtn->eventMouseButtonClick += MyGUI::newDelegate(OnRumorCancelClick);
  return client;
}

void OnRumorWriteClick(MyGUI::Widget *sender) {
  g_rumorInstruction = g_rumorBox->getOnlyText().asUTF8();
  g_rumorWritten = true;
  SetRumorStatus(T("This may take a moment..."));
  StartRumorRequest(L"/write_rumor",
                    "{\"notable\":\"" + EscapeJSON(g_rumorNotable) +
                        "\",\"instruction\":\"" +
                        EscapeJSON(g_rumorInstruction) + "\"}",
                    "RUMOR_WRITTEN");
}

void OnRumorKeepClick(MyGUI::Widget *sender) {
  // Edit Rumor sends no instruction, so the stored one stays
  std::string instruction =
      g_rumorWritten
          ? ",\"instruction\":\"" + EscapeJSON(g_rumorInstruction) + "\""
          : "";
  SetRumorStatus("");
  StartRumorRequest(L"/keep_rumor",
                    "{\"notable\":\"" + EscapeJSON(g_rumorNotable) +
                        "\",\"campaign\":\"" + EscapeJSON(g_rumorCampaign) +
                        "\",\"text\":\"" +
                        EscapeJSON(g_rumorBox->getOnlyText().asUTF8()) + "\"" +
                        instruction + "}",
                    "RUMOR_KEPT");
}

void CreateRumorAskUI() {
  MyGUI::Widget *client =
      CreateRumorWindow("Generate Rumor", "Write", OnRumorWriteClick, "Cancel");
  if (!client)
    return;
  AddBioLine(client, T("Instructions (optional)"), 0.12f,
             "SentientSands_RumorInstructionsLabel");
  g_rumorBox =
      AddBioEditBox(client, 0.18f, 0.40f, "SentientSands_RumorInstructions");
  g_rumorBox->setCaption(Utf8ToWide(g_rumorInstruction).c_str());
  AddBioLine(client,
             T("The LLM also reads the event, the characters in it, and the "
               "rumor so far."),
             0.62f, "SentientSands_RumorHint");
}

void CreateRumorEditUI(const std::string &text) {
  MyGUI::Widget *client =
      CreateRumorWindow("Edit Rumor", "Keep", OnRumorKeepClick, "Discard");
  if (!client)
    return;
  AddBioLine(client, T("Edit the text, then Keep to store it."), 0.10f,
             "SentientSands_RumorEditHint");
  g_rumorBox = AddBioEditBox(client, 0.17f, 0.55f, "SentientSands_RumorText");
  g_rumorBox->setCaption(Utf8ToWide(text).c_str());
}

void OnEventAddClick(MyGUI::Widget *sender) {
  SetRumorStatus("");
  StartRumorRequest(L"/add_event",
                    "{\"campaign\":\"" + EscapeJSON(g_eventsCampaign) +
                        "\",\"rumor\":\"" +
                        EscapeJSON(g_rumorBox->getOnlyText().asUTF8()) + "\"}",
                    "EVENT_ADDED");
}

void CreateEventAddUI() {
  g_rumorLine = "";
  MyGUI::Widget *client =
      CreateRumorWindow("Add Event", "Add", OnEventAddClick, "Cancel");
  if (!client)
    return;
  AddBioLine(client,
             T("Write the rumor of an event that the game does not track."),
             0.10f, "SentientSands_EventAddHint");
  g_rumorBox = AddBioEditBox(client, 0.17f, 0.40f, "SentientSands_EventRumor");
  AddBioLine(client,
             T("A custom event has no game time, so Cull Future Data keeps it."),
             0.62f, "SentientSands_EventAddCullHint");
}

bool DeletesWholeEvent() {
  return g_rumorKind == "custom" || g_rumorKind == "auto" ||
         g_rumorKind == "bounty";
}

void OnEventDeleteClick(MyGUI::Widget *sender) {
  bool whole = DeletesWholeEvent();
  SetRumorStatus("");
  StartRumorRequest(whole ? L"/delete_event" : L"/delete_rumor",
                    "{\"campaign\":\"" + EscapeJSON(g_eventsCampaign) +
                        "\",\"id\":\"" +
                        EscapeJSON(whole ? g_rumorNotable : g_rumorId) +
                        "\"}",
                    "EVENT_DELETED");
}

void CreateEventDeleteUI() {
  bool whole = DeletesWholeEvent();
  bool isAuto = g_rumorKind == "auto";
  bool isBounty = g_rumorKind == "bounty";
  MyGUI::Widget *client = CreateRumorWindow(
      !whole     ? "Delete the rumor"
      : isAuto   ? "Delete the auto event"
      : isBounty ? "Delete the bounty event"
                 : "Delete the custom event",
      "Delete", OnEventDeleteClick, "Cancel");
  if (!client)
    return;
  AddBioLine(client,
             T(!whole   ? "NPCs stop mentioning this rumor."
               : isAuto ? "This deletes the auto event and its rumor, so NPCs "
                          "stop mentioning it."
               : isBounty
                   ? "This deletes the bounty event and its rumor, so NPCs stop "
                     "mentioning it. The bounty in the game stays."
                   : "This deletes the custom event and its rumor, so NPCs "
                     "stop mentioning it."),
             0.12f, "SentientSands_EventDeleteText");
  MyGUI::TextBox *warning = AddBioLine(
      client, T("The delete takes effect immediately and is irreversible."),
      0.18f, "SentientSands_EventDeleteWarning");
  warning->setTextColour(MyGUI::Colour(1.0f, 0.6f, 0.6f));
}

void OpenRumorEditor(const std::string &data, const std::string &failureKey) {
  std::string reply;
  if (!TakeRumorReply(data, reply))
    return;
  if (GetJsonValue(reply, "status") != "ok") {
    ShowRumorFailure(failureKey, reply);
    return;
  }
  g_rumorCampaign = GetJsonValue(reply, "campaign");
  CreateRumorEditUI(GetJsonValue(reply, "text"));
}

void FinishEventChange(const std::string &data, const std::string &failureKey) {
  std::string reply;
  if (!TakeRumorReply(data, reply))
    return;
  if (GetJsonValue(reply, "status") != "ok") {
    ShowRumorFailure(failureKey, reply);
    return;
  }
  CloseRumorUI();
  if (!g_eventsWindow)
    return;
  std::string added = GetJsonValue(reply, "id");
  // The search or the kind filter could hide the new event
  if (!added.empty()) {
    g_rumorNotable = added;
    g_eventsSearch->setCaption("");
    g_eventsKind = 0;
  }
  g_eventsSelectId = g_rumorNotable;
  CreateThread(NULL, 0, EventsResponseThread, NULL, 0, NULL);
  ShowEventContent(g_rumorNotable);
}

bool SelectRumorEvent() {
  size_t index = g_eventsList->getIndexSelected();
  if (index == MyGUI::ITEM_NONE || index >= g_eventsStorageIds.size())
    return false;
  g_rumorNotable = g_eventsStorageIds[index];
  g_rumorLine = g_eventsList->getItemNameAt(index).asUTF8();
  g_rumorInstruction = "";
  for (size_t i = 0; i < g_eventsAllIds.size(); i++)
    if (g_eventsAllIds[i] == g_rumorNotable) {
      g_rumorInstruction = g_eventsAllInstructions[i];
      g_rumorKind = g_eventsAllKinds[i];
      g_rumorId = g_eventsAllRumors[i];
    }
  return true;
}

bool RefusesBountyRumor() {
  if (g_rumorKind != "bounty")
    return false;
  SetEventsText(T("SSR writes the notice and the rumor of a bounty, so they "
                  "cannot be written or edited."));
  return true;
}

void OnEventsGenerateClick(MyGUI::Widget *sender) {
  if (SelectRumorEvent() && !RefusesBountyRumor())
    CreateRumorAskUI();
}

void OnEventsEditClick(MyGUI::Widget *sender) {
  if (!SelectRumorEvent() || RefusesBountyRumor())
    return;
  CloseRumorUI();
  g_rumorWritten = false;
  StartRumorRequest(L"/read_rumor",
                    "{\"notable\":\"" + EscapeJSON(g_rumorNotable) + "\"}",
                    "RUMOR_READ");
}

void OnEventsAddClick(MyGUI::Widget *sender) { CreateEventAddUI(); }

void OnEventsDeleteClick(MyGUI::Widget *sender) {
  if (!SelectRumorEvent())
    return;
  if (!DeletesWholeEvent() && g_rumorId.empty()) {
    SetEventsText(T("The event has no rumor yet."));
    return;
  }
  CreateEventDeleteUI();
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
  g_eventsWindow->setCaption(Utf8ToWide(T("Events")).c_str());
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

  g_eventsKindBtn = client->createWidgetReal<MyGUI::Button>(
      "Kenshi_Button1", 0.02f, 0.10f, 0.28f, 0.06f,
      MyGUI::Align::Left | MyGUI::Align::Top, "SentientSands_EventsKindBtn");
  g_eventsKindBtn->eventMouseButtonClick +=
      MyGUI::newDelegate(OnEventsKindClick);
  ShowEventsKind();

  g_eventsList = client->createWidgetReal<MyGUI::ListBox>(
      "Kenshi_ListBox", 0.02f, 0.18f, 0.28f, 0.58f,
      MyGUI::Align::Left | MyGUI::Align::VStretch, "SentientSands_EventsList");
  g_eventsList->eventListSelectAccept += MyGUI::newDelegate(OnEventsSelect);
  g_eventsList->eventListChangePosition += MyGUI::newDelegate(OnEventsSelect);

  MyGUI::Button *generateBtn = client->createWidgetReal<MyGUI::Button>(
      "Kenshi_Button1", 0.02f, 0.78f, 0.135f, 0.08f,
      MyGUI::Align::Left | MyGUI::Align::Bottom,
      "SentientSands_EventsGenerateRumorBtn");
  generateBtn->setCaption(Utf8ToWide(T("Generate Rumor")).c_str());
  generateBtn->eventMouseButtonClick +=
      MyGUI::newDelegate(OnEventsGenerateClick);

  MyGUI::Button *editBtn = client->createWidgetReal<MyGUI::Button>(
      "Kenshi_Button1", 0.165f, 0.78f, 0.135f, 0.08f,
      MyGUI::Align::Left | MyGUI::Align::Bottom,
      "SentientSands_EventsEditRumorBtn");
  editBtn->setCaption(Utf8ToWide(T("Edit Rumor")).c_str());
  editBtn->eventMouseButtonClick += MyGUI::newDelegate(OnEventsEditClick);

  MyGUI::Button *addBtn = client->createWidgetReal<MyGUI::Button>(
      "Kenshi_Button1", 0.02f, 0.88f, 0.135f, 0.08f,
      MyGUI::Align::Left | MyGUI::Align::Bottom,
      "SentientSands_EventsAddEventBtn");
  addBtn->setCaption(Utf8ToWide(T("Add Event")).c_str());
  addBtn->eventMouseButtonClick += MyGUI::newDelegate(OnEventsAddClick);

  MyGUI::Button *deleteBtn = client->createWidgetReal<MyGUI::Button>(
      "Kenshi_Button1", 0.165f, 0.88f, 0.135f, 0.08f,
      MyGUI::Align::Left | MyGUI::Align::Bottom,
      "SentientSands_EventsDeleteBtn");
  deleteBtn->setCaption(Utf8ToWide(T("Delete")).c_str());
  deleteBtn->eventMouseButtonClick += MyGUI::newDelegate(OnEventsDeleteClick);

  g_eventsText = client->createWidgetReal<MyGUI::ListBox>(
      "Kenshi_ListBox", 0.32f, 0.02f, 0.66f, 0.96f, MyGUI::Align::Default,
      "SentientSands_EventsText");
  g_eventsText->addItem(Utf8ToWide(T("Select an event to view details.")).c_str());

  CreateThread(NULL, 0, EventsResponseThread, NULL, 0, NULL);
}

} // namespace UI
} // namespace SentientSands
