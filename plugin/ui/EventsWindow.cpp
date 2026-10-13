#include "EventsWindow.h"
#include "../core/Comm.h"
#include "../core/Globals.h"
#include "../core/Utils.h"
#include <mygui/MyGUI_Delegate.h>
#include <mygui/MyGUI_Gui.h>
#include <mygui/MyGUI_ListBox.h>
#include <mygui/MyGUI_Window.h>

namespace SentientSands {
namespace UI {

static const char *EVENT_KINDS[] = {"all", "kill", "capture", "custom",
                                   "auto"};
static const char *EVENT_KIND_LABELS[] = {"All kinds", "Kill", "Capture",
                                         "Custom", "Auto"};
static const int EVENT_KIND_COUNT = sizeof(EVENT_KINDS) / sizeof(EVENT_KINDS[0]);

MyGUI::Window *g_eventsWindow = nullptr;
MyGUI::ListBox *g_eventsList = nullptr;
MyGUI::ListBox *g_eventsText = nullptr;
MyGUI::EditBox *g_eventsSearch = nullptr;
MyGUI::Button *g_eventsKindBtn = nullptr;
std::vector<std::string> g_eventsStorageIds;

struct EventRow {
  std::string id;
  std::string title;
  std::string text;
  std::string instruction;
  std::string kind;
  std::string rumor;
};
static std::vector<EventRow> g_eventRows;
int g_eventsKind = 0;
std::string g_eventsCampaign;
std::string g_eventsSelectId;
// The arrow keys move the selection faster than the server answers, so the
// replies can come back out of order
static int g_eventsListRequest = 0;
static int g_eventsContentRequest = 0;

static void SetEventsText(const std::string &text);
static EditorPopup g_rumor = {nullptr, nullptr, nullptr, 0, SetEventsText};
static MyGUI::EditBox *g_rumorBox = nullptr;
bool g_rumorWritten = false;
std::string g_rumorEvent;
std::string g_rumorLine;
std::string g_rumorInstruction;
std::string g_rumorCampaign;
std::string g_rumorKind;
std::string g_rumorId;

static void CloseRumorUI() {
  CloseEditor(g_rumor);
  g_rumorBox = nullptr;
}

static CloseAction g_rumorClose = {CloseRumorUI};

void CloseEventsUI() {
  CloseRumorUI();
  g_eventsListRequest++;
  g_eventsContentRequest++;
  if (g_eventsWindow) {
    DestroyWindow(g_eventsWindow);
    g_eventsList = nullptr;
    g_eventsText = nullptr;
    g_eventsSearch = nullptr;
    g_eventsKindBtn = nullptr;
    g_eventsStorageIds.clear();
    g_eventRows.clear();
    g_eventsKind = 0;
    g_eventsSelectId.clear();
  }
}

void ApplyEventsFilter(const std::string &keepId) {
  g_eventsList->removeAllItems();
  g_eventsStorageIds.clear();
  std::string query =
      g_eventsSearch ? g_eventsSearch->getOnlyText().asUTF8() : "";
  for (size_t i = 0; i < g_eventRows.size(); i++) {
    const EventRow &row = g_eventRows[i];
    if (g_eventsKind != 0 && row.kind != EVENT_KINDS[g_eventsKind])
      continue;
    if (!ContainsIgnoreCase(row.text, query))
      continue;
    g_eventsList->addItem(Utf8ToWide(row.title).c_str());
    g_eventsStorageIds.push_back(row.id);
    if (row.id == keepId)
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
  int count = 0;
  for (size_t i = 0; i < g_eventRows.size(); i++)
    if (kind == 0 || g_eventRows[i].kind == EVENT_KINDS[kind])
      count++;
  return count;
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

static void RequestEventsList() {
  PostForGameThread(L"/events", "", "POPULATE_EVENTS",
                    ToString(++g_eventsListRequest));
}

void PopulateEventsUI(const std::string &data) {
  std::string reply;
  if (!g_eventsList || !TakeTaggedReply(data, g_eventsListRequest, reply) ||
      GetJsonValue(reply, "status") != "ok")
    return;
  std::string keepId =
      g_eventsSelectId.empty() ? SelectedEventId() : g_eventsSelectId;
  g_eventsSelectId.clear();
  g_eventsCampaign = GetJsonValue(reply, "campaign");
  std::vector<std::string> events =
      JsonArrayItems(GetJsonValue(reply, "events"));
  g_eventRows.clear();
  for (size_t i = 0; i < events.size(); i++) {
    EventRow row;
    row.id = GetJsonValue(events[i], "id");
    row.title = GetJsonValue(events[i], "title");
    row.text = GetJsonValue(events[i], "inner");
    row.instruction = GetJsonValue(events[i], "instruction");
    row.kind = GetJsonValue(events[i], "kind");
    row.rumor = GetJsonValue(events[i], "rumor");
    g_eventRows.push_back(row);
  }
  ShowEventsKind();
  ApplyEventsFilter(keepId);
}

static void SetEventsText(const std::string &text) {
  if (!g_eventsText)
    return;
  std::stringstream ss(text);
  std::string line;
  g_eventsText->removeAllItems();
  while (std::getline(ss, line)) {
    g_eventsText->addItem(Utf8ToWide(line).c_str());
  }
}

// A gone event comes back with an error status and its own text
void SetEventContent(const std::string &data) {
  std::string reply;
  if (!TakeTaggedReply(data, g_eventsContentRequest, reply))
    return;
  std::string text = GetJsonValue(reply, "text");
  SetEventsText(text.empty() ? FailureText("Load failed: ", reply) : text);
}

void ShowEventContent(const std::string &id) {
  SetEventsText(T("Loading the event..."));
  PostForGameThread(L"/events/content", "{\"id\":\"" + EscapeJSON(id) + "\"}",
                    "SET_EVENTS_TEXT", ToString(++g_eventsContentRequest));
}

void OnEventsSelect(MyGUI::ListBox *sender, size_t index) {
  if (index == MyGUI::ITEM_NONE)
    return;
  if (index >= g_eventsStorageIds.size())
    return;
  ShowEventContent(g_eventsStorageIds[index]);
}

static void OnRumorCancelClick(MyGUI::Widget *sender) { CloseRumorUI(); }

static MyGUI::Widget *CreateRumorWindow(const char *captionKey,
                                        const char *confirmKey,
                                        ClickHandler onConfirm,
                                        const char *cancelKey) {
  CloseRumorUI();
  MyGUI::Widget *client = OpenEditor(
      g_rumor, g_rumorClose, "SentientSands_Rumor", T(captionKey), 0.28f,
      0.22f, 0.44f, 0.50f, T(confirmKey), onConfirm, T(cancelKey),
      OnRumorCancelClick);
  if (!client)
    return nullptr;
  AddEditorLine(client, g_rumorLine, 0.03f, "SentientSands_RumorLine");
  g_rumor.status =
      AddEditorLine(client, "", 0.76f, "SentientSands_RumorStatus");
  return client;
}

void OnRumorWriteClick(MyGUI::Widget *sender) {
  g_rumorInstruction = g_rumorBox->getOnlyText().asUTF8();
  g_rumorWritten = true;
  SetEditorStatus(g_rumor, T("This may take a moment..."));
  StartEditorRequest(g_rumor, L"/write_rumor",
                    "{\"event\":\"" + EscapeJSON(g_rumorEvent) +
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
  SetEditorStatus(g_rumor, "");
  StartEditorRequest(g_rumor, L"/keep_rumor",
                    "{\"event\":\"" + EscapeJSON(g_rumorEvent) +
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
  AddEditorLine(client, T("Instructions (optional)"), 0.12f,
             "SentientSands_RumorInstructionsLabel");
  g_rumorBox =
      AddEditorBox(client, 0.18f, 0.40f, "SentientSands_RumorInstructions");
  g_rumorBox->setCaption(Utf8ToWide(g_rumorInstruction).c_str());
  AddEditorLine(client,
             T("The LLM also reads the event, the characters in it, and the "
               "rumor so far."),
             0.62f, "SentientSands_RumorHint");
}

void CreateRumorEditUI(const std::string &text) {
  MyGUI::Widget *client =
      CreateRumorWindow("Edit Rumor", "Keep", OnRumorKeepClick, "Discard");
  if (!client)
    return;
  AddEditorLine(client, T("Edit the text, then Keep to store it."), 0.10f,
             "SentientSands_RumorEditHint");
  g_rumorBox = AddEditorBox(client, 0.17f, 0.55f, "SentientSands_RumorText");
  g_rumorBox->setCaption(Utf8ToWide(text).c_str());
}

void OnEventAddClick(MyGUI::Widget *sender) {
  SetEditorStatus(g_rumor, "");
  StartEditorRequest(g_rumor, L"/add_event",
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
  AddEditorLine(client,
             T("Write the rumor of an event that the game does not track."),
             0.10f, "SentientSands_EventAddHint");
  g_rumorBox = AddEditorBox(client, 0.17f, 0.40f, "SentientSands_EventRumor");
  AddEditorLine(client,
             T("A custom event has no game time, so Cull Future Data keeps it."),
             0.62f, "SentientSands_EventAddCullHint");
}

bool DeletesWholeEvent() {
  return g_rumorKind == "custom" || g_rumorKind == "auto";
}

void OnEventDeleteClick(MyGUI::Widget *sender) {
  bool whole = DeletesWholeEvent();
  SetEditorStatus(g_rumor, "");
  StartEditorRequest(g_rumor, whole ? L"/delete_event" : L"/delete_rumor",
                    "{\"campaign\":\"" + EscapeJSON(g_eventsCampaign) +
                        "\",\"id\":\"" +
                        EscapeJSON(whole ? g_rumorEvent : g_rumorId) +
                        "\"}",
                    "EVENT_DELETED");
}

void CreateEventDeleteUI() {
  bool whole = DeletesWholeEvent();
  bool isAuto = g_rumorKind == "auto";
  MyGUI::Widget *client = CreateRumorWindow(
      !whole   ? "Delete the rumor"
      : isAuto ? "Delete the auto event"
               : "Delete the custom event",
      "Delete", OnEventDeleteClick, "Cancel");
  if (!client)
    return;
  AddEditorLine(client,
             T(!whole   ? "NPCs stop mentioning this rumor."
               : isAuto ? "This deletes the auto event and its rumor, so NPCs "
                          "stop mentioning it."
                        : "This deletes the custom event and its rumor, so NPCs "
                          "stop mentioning it."),
             0.12f, "SentientSands_EventDeleteText");
  MyGUI::TextBox *warning = AddEditorLine(
      client, T("The delete takes effect immediately and is irreversible."),
      0.18f, "SentientSands_EventDeleteWarning");
  warning->setTextColour(MyGUI::Colour(1.0f, 0.6f, 0.6f));
}

void OpenRumorEditor(const std::string &data, const std::string &failureKey) {
  std::string reply;
  if (!TakeEditorReply(g_rumor, data, reply))
    return;
  if (GetJsonValue(reply, "status") != "ok") {
    ShowEditorFailure(g_rumor, failureKey, reply);
    return;
  }
  g_rumorCampaign = GetJsonValue(reply, "campaign");
  CreateRumorEditUI(GetJsonValue(reply, "text"));
}

void FinishEventChange(const std::string &data, const std::string &failureKey) {
  std::string reply;
  if (!TakeEditorReply(g_rumor, data, reply))
    return;
  if (GetJsonValue(reply, "status") != "ok") {
    ShowEditorFailure(g_rumor, failureKey, reply);
    return;
  }
  CloseRumorUI();
  if (!g_eventsWindow)
    return;
  std::string added = GetJsonValue(reply, "id");
  // The search or the kind filter could hide the new event
  if (!added.empty()) {
    g_rumorEvent = added;
    g_eventsSearch->setCaption("");
    g_eventsKind = 0;
  }
  g_eventsSelectId = g_rumorEvent;
  RequestEventsList();
  ShowEventContent(g_rumorEvent);
}

bool SelectRumorEvent() {
  size_t index = g_eventsList->getIndexSelected();
  if (index == MyGUI::ITEM_NONE || index >= g_eventsStorageIds.size())
    return false;
  g_rumorEvent = g_eventsStorageIds[index];
  g_rumorLine = g_eventsList->getItemNameAt(index).asUTF8();
  g_rumorInstruction = "";
  for (size_t i = 0; i < g_eventRows.size(); i++)
    if (g_eventRows[i].id == g_rumorEvent) {
      g_rumorInstruction = g_eventRows[i].instruction;
      g_rumorKind = g_eventRows[i].kind;
      g_rumorId = g_eventRows[i].rumor;
    }
  return true;
}

void OnEventsGenerateClick(MyGUI::Widget *sender) {
  if (SelectRumorEvent())
    CreateRumorAskUI();
}

void OnEventsEditClick(MyGUI::Widget *sender) {
  if (!SelectRumorEvent())
    return;
  CloseRumorUI();
  g_rumorWritten = false;
  StartEditorRequest(g_rumor, L"/read_rumor",
                    "{\"event\":\"" + EscapeJSON(g_rumorEvent) + "\"}",
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

static CloseAction g_eventsClose = {CloseEventsUI};

void CreateEventsUI() {
  CloseEventsUI();
  MyGUI::Widget *client =
      OpenWindow(g_eventsWindow, 0.1f, 0.1f, 0.8f, 0.8f, MyGUI::Align::Center,
                 "Popup", "SentientSands_EventsWindow", T("Events"),
                 g_eventsClose);
  if (!client)
    return;

  AddRowLabel(client, T("Search"), 0.02f, 0.02f, 0.07f,
              "SentientSands_EventsSearchLabel");
  g_eventsSearch =
      AddRowBox(client, 0.09f, 0.02f, 0.21f, "SentientSands_EventsSearch");
  g_eventsSearch->eventEditTextChange +=
      MyGUI::newDelegate(OnEventsSearchChange);

  g_eventsKindBtn =
      AddButton(client, "", 0.02f, 0.10f, 0.28f, 0.06f,
                MyGUI::Align::Left | MyGUI::Align::Top,
                "SentientSands_EventsKindBtn", OnEventsKindClick);
  ShowEventsKind();

  g_eventsList = client->createWidgetReal<MyGUI::ListBox>(
      "Kenshi_ListBox", 0.02f, 0.18f, 0.28f, 0.58f,
      MyGUI::Align::Left | MyGUI::Align::VStretch, "SentientSands_EventsList");
  g_eventsList->eventListSelectAccept += MyGUI::newDelegate(OnEventsSelect);
  g_eventsList->eventListChangePosition += MyGUI::newDelegate(OnEventsSelect);

  AddRowButton(client, "Generate Rumor", 0.02f, 0.78f, 0.135f,
               "SentientSands_EventsGenerateRumorBtn", OnEventsGenerateClick);
  AddRowButton(client, "Edit Rumor", 0.165f, 0.78f, 0.135f,
               "SentientSands_EventsEditRumorBtn", OnEventsEditClick);
  AddRowButton(client, "Add Event", 0.02f, 0.88f, 0.135f,
               "SentientSands_EventsAddEventBtn", OnEventsAddClick);
  AddRowButton(client, "Delete", 0.165f, 0.88f, 0.135f,
               "SentientSands_EventsDeleteBtn", OnEventsDeleteClick);

  g_eventsText = client->createWidgetReal<MyGUI::ListBox>(
      "Kenshi_ListBox", 0.32f, 0.02f, 0.66f, 0.96f, MyGUI::Align::Default,
      "SentientSands_EventsText");
  g_eventsText->addItem(Utf8ToWide(T("Select an event to view details.")).c_str());

  RequestEventsList();
}

} // namespace UI
} // namespace SentientSands
