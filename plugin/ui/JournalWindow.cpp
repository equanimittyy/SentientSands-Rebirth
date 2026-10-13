#include "JournalWindow.h"
#include "../core/Comm.h"
#include "../core/Globals.h"
#include "../core/Utils.h"
#include "../game/Context.h"
#include <cstdlib>
#include <mygui/MyGUI_Delegate.h>
#include <mygui/MyGUI_Gui.h>
#include <mygui/MyGUI_TextIterator.h>

namespace SentientSands {
namespace UI {

MyGUI::Window *g_journalWindow = nullptr;
MyGUI::EditBox *g_journalSearch = nullptr;
MyGUI::ListBox *g_journalList = nullptr;
MyGUI::Button *g_journalPrevBtn = nullptr;
MyGUI::Button *g_journalNextBtn = nullptr;
MyGUI::TextBox *g_journalPageText = nullptr;
MyGUI::TextBox *g_journalTime = nullptr;
MyGUI::EditBox *g_journalTitle = nullptr;
MyGUI::EditBox *g_journalText = nullptr;
MyGUI::TextBox *g_journalStatus = nullptr;
MyGUI::Window *g_journalDeleteWindow = nullptr;
std::vector<std::string> g_journalIds;
int g_journalPage = 1;
int g_journalPages = 1;
int g_journalListRequest = 0;
int g_journalEntryRequest = 0;
std::string g_journalCampaign;
std::string g_journalSelectedId;
// Empty while an entry loads, so no save sends the blank boxes
std::string g_journalEntryId;
std::string g_journalSavedTitle;
std::string g_journalSavedText;
std::string g_journalDeleteId;

void SetJournalStatus(const std::string &text) {
  if (g_journalStatus)
    g_journalStatus->setCaption(Utf8ToWide(text).c_str());
}

void ShowJournalEntry(const std::string &time, const std::string &title,
                      const std::string &text) {
  g_journalTime->setCaption(Utf8ToWide(time).c_str());
  // setOnlyText, because setCaption reads a # in the text as a colour tag
  g_journalTitle->setOnlyText(Utf8ToWide(title).c_str());
  ShowFromTop(g_journalText, text);
  bool loaded = !g_journalEntryId.empty();
  g_journalTitle->setEnabled(loaded);
  g_journalText->setEnabled(loaded);
  g_journalSavedTitle = g_journalTitle->getOnlyText().asUTF8();
  g_journalSavedText = g_journalText->getOnlyText().asUTF8();
}

void RequestJournalPage(int page) {
  g_journalPage = page;
  std::string query =
      g_journalSearch ? g_journalSearch->getOnlyText().asUTF8() : "";
  PostForGameThread(L"/journal",
                      "{\"page\":" + ToString(page) + ",\"query\":\"" +
                          EscapeJSON(query) + "\"}",
                      "POPULATE_JOURNAL", ToString(++g_journalListRequest));
}

void PopulateJournalUI(const std::string &data) {
  std::string tag, reply;
  if (!g_journalList || !SplitTaggedReply(data, tag, reply) ||
      atoi(tag.c_str()) != g_journalListRequest)
    return;
  if (GetJsonValue(reply, "status") != "ok") {
    SetJournalStatus(FailureText("Load failed: ", reply));
    return;
  }
  g_journalCampaign = GetJsonValue(reply, "campaign");
  g_journalPage = atoi(GetJsonValue(reply, "page").c_str());
  g_journalPages = atoi(GetJsonValue(reply, "pages").c_str());
  std::string entries = GetJsonValue(reply, "entries");
  g_journalList->removeAllItems();
  g_journalIds.clear();
  // Flask sorts the keys, so each entry's label lies between its "id" and the
  // next one
  size_t cur = entries.find("\"id\":");
  while (cur != std::string::npos) {
    size_t next = entries.find("\"id\":", cur + 5);
    std::string entry = entries.substr(cur, next - cur);
    g_journalIds.push_back(GetJsonValue(entry, "id"));
    g_journalList->addItem(MyGUI::TextIterator::toTagsString(
        Utf8ToWide(GetJsonValue(entry, "label"))));
    if (g_journalIds.back() == g_journalSelectedId)
      g_journalList->setIndexSelected(g_journalIds.size() - 1);
    cur = next;
  }
  g_journalPageText->setCaption(
      Utf8ToWide(T("Page ") + ToString(g_journalPage) + " / " +
                 ToString(g_journalPages))
          .c_str());
  g_journalPrevBtn->setEnabled(g_journalPage > 1);
  g_journalNextBtn->setEnabled(g_journalPage < g_journalPages);
}

void LoadJournalEntry(const std::string &id) {
  g_journalSelectedId = id;
  g_journalEntryId = "";
  ShowJournalEntry("", "", "");
  SetJournalStatus(T("Loading the entry..."));
  PostForGameThread(L"/journal/read",
                      "{\"id\":\"" + EscapeJSON(id) + "\"}", "JOURNAL_ENTRY",
                      ToString(++g_journalEntryRequest));
}

void SetJournalEntry(const std::string &data) {
  std::string tag, reply;
  if (!g_journalWindow || !SplitTaggedReply(data, tag, reply) ||
      atoi(tag.c_str()) != g_journalEntryRequest)
    return;
  if (GetJsonValue(reply, "status") != "ok") {
    SetJournalStatus(FailureText("Load failed: ", reply));
    return;
  }
  g_journalEntryId = g_journalSelectedId;
  ShowJournalEntry(GetJsonValue(reply, "time"), GetJsonValue(reply, "title"),
                   GetJsonValue(reply, "text"));
  SetJournalStatus("");
}

void SaveJournalEntry() {
  std::string title = g_journalTitle->getOnlyText().asUTF8();
  std::string text = g_journalText->getOnlyText().asUTF8();
  g_journalSavedTitle = title;
  g_journalSavedText = text;
  PostForGameThread(L"/journal/save",
                      "{\"campaign\":\"" + EscapeJSON(g_journalCampaign) +
                          "\",\"id\":\"" + EscapeJSON(g_journalEntryId) +
                          "\",\"title\":\"" + EscapeJSON(title) +
                          "\",\"text\":\"" + EscapeJSON(text) + "\"}",
                      "JOURNAL_SAVED", g_journalEntryId);
}

void SaveJournalIfChanged() {
  if (g_journalEntryId.empty())
    return;
  if (g_journalTitle->getOnlyText().asUTF8() != g_journalSavedTitle ||
      g_journalText->getOnlyText().asUTF8() != g_journalSavedText)
    SaveJournalEntry();
}

void FinishJournalSave(const std::string &data) {
  std::string id, reply;
  if (!SplitTaggedReply(data, id, reply))
    return;
  bool saved = GetJsonValue(reply, "status") == "ok";
  if (!g_journalWindow) {
    if (!saved)
      Log(LOG_WARN, "JOURNAL: The save of the entry " + id +
                        " failed: " + reply);
    return;
  }
  if (!saved) {
    SetJournalStatus(FailureText("Save failed: ", reply));
    return;
  }
  if (id == g_journalEntryId)
    SetJournalStatus(T("Saved."));
  // A new title can change the label
  RequestJournalPage(g_journalPage);
}

void OnJournalSaveClick(MyGUI::Widget *sender) {
  if (g_journalEntryId.empty())
    return;
  SetJournalStatus(T("Saving..."));
  SaveJournalEntry();
}

void OnJournalSelect(MyGUI::ListBox *sender, size_t index) {
  if (index == MyGUI::ITEM_NONE || index >= g_journalIds.size() ||
      g_journalIds[index] == g_journalSelectedId)
    return;
  SaveJournalIfChanged();
  LoadJournalEntry(g_journalIds[index]);
}

void OnJournalSearchChange(MyGUI::EditBox *sender) { RequestJournalPage(1); }

void OnJournalPrevClick(MyGUI::Widget *sender) {
  SaveJournalIfChanged();
  RequestJournalPage(g_journalPage - 1);
}

void OnJournalNextClick(MyGUI::Widget *sender) {
  SaveJournalIfChanged();
  RequestJournalPage(g_journalPage + 1);
}

void OnJournalNewClick(MyGUI::Widget *sender) {
  SaveJournalIfChanged();
  SetJournalStatus("");
  PostForGameThread(L"/journal/add",
                      "{\"campaign\":\"" + EscapeJSON(g_journalCampaign) +
                          "\"" + GameTimeFields() + "}",
                      "JOURNAL_ADDED", "");
}

void FinishJournalAdd(const std::string &data) {
  std::string tag, reply;
  if (!g_journalWindow || !SplitTaggedReply(data, tag, reply))
    return;
  if (GetJsonValue(reply, "status") != "ok") {
    SetJournalStatus(FailureText("Add failed: ", reply));
    return;
  }
  // The search could hide the new entry
  g_journalSearch->setOnlyText(L"");
  LoadJournalEntry(GetJsonValue(reply, "id"));
  RequestJournalPage(1);
}

void CloseJournalDeleteUI() { DestroyWindow(g_journalDeleteWindow); }

void OnJournalDeleteConfirmClick(MyGUI::Widget *sender) {
  CloseJournalDeleteUI();
  SetJournalStatus("");
  PostForGameThread(L"/journal/delete",
                      "{\"campaign\":\"" + EscapeJSON(g_journalCampaign) +
                          "\",\"id\":\"" + EscapeJSON(g_journalDeleteId) +
                          "\"}",
                      "JOURNAL_DELETED", g_journalDeleteId);
}

void OnJournalDeleteCancelClick(MyGUI::Widget *sender) {
  CloseJournalDeleteUI();
}

static CloseAction g_journalDeleteClose = {CloseJournalDeleteUI};

void CreateJournalDeleteUI() {
  CloseJournalDeleteUI();
  // The player can select another entry while the popup is open
  g_journalDeleteId = g_journalEntryId;
  MyGUI::UString label;
  for (size_t i = 0; i < g_journalIds.size(); i++)
    if (g_journalIds[i] == g_journalDeleteId)
      label = g_journalList->getItemNameAt(i);
  const MyGUI::UString lines[] = {
      Utf8ToWide(T("This deletes the journal entry:")), label,
      Utf8ToWide(T("The delete takes effect immediately and is irreversible."))};
  OpenConfirm(g_journalDeleteWindow, "SentientSands_JournalDelete",
              T("Delete the entry"), lines, T("Delete"),
              OnJournalDeleteConfirmClick, OnJournalDeleteCancelClick,
              g_journalDeleteClose);
}

void OnJournalDeleteClick(MyGUI::Widget *sender) {
  if (!g_journalEntryId.empty())
    CreateJournalDeleteUI();
}

void FinishJournalDelete(const std::string &data) {
  std::string id, reply;
  if (!g_journalWindow || !SplitTaggedReply(data, id, reply))
    return;
  if (GetJsonValue(reply, "status") != "ok") {
    SetJournalStatus(FailureText("Delete failed: ", reply));
    return;
  }
  if (id == g_journalSelectedId) {
    g_journalSelectedId = "";
    g_journalEntryId = "";
    g_journalEntryRequest++;
    ShowJournalEntry("", "", "");
  }
  SetJournalStatus(T("Deleted."));
  RequestJournalPage(g_journalPage);
}

void CloseJournalUI() {
  CloseJournalDeleteUI();
  if (!g_journalWindow)
    return;
  SaveJournalIfChanged();
  g_journalListRequest++;
  g_journalEntryRequest++;
  DestroyWindow(g_journalWindow);
  g_journalSearch = nullptr;
  g_journalList = nullptr;
  g_journalPrevBtn = nullptr;
  g_journalNextBtn = nullptr;
  g_journalPageText = nullptr;
  g_journalTime = nullptr;
  g_journalTitle = nullptr;
  g_journalText = nullptr;
  g_journalStatus = nullptr;
  g_journalIds.clear();
  g_journalSelectedId.clear();
  g_journalEntryId.clear();
}

static CloseAction g_journalClose = {CloseJournalUI};

void CreateJournalUI() {
  CloseJournalUI();
  MyGUI::Widget *client =
      OpenWindow(g_journalWindow, 0.1f, 0.1f, 0.8f, 0.8f, MyGUI::Align::Center,
                 "Popup", "SentientSands_JournalWindow", T("Journal"),
                 g_journalClose);
  if (!client)
    return;

  AddRowLabel(client, T("Search"), 0.02f, 0.02f, 0.07f,
              "SentientSands_JournalSearchLabel");
  g_journalSearch =
      AddRowBox(client, 0.09f, 0.02f, 0.21f, "SentientSands_JournalSearch");
  g_journalSearch->eventEditTextChange +=
      MyGUI::newDelegate(OnJournalSearchChange);

  g_journalList = client->createWidgetReal<MyGUI::ListBox>(
      "Kenshi_ListBox", 0.02f, 0.10f, 0.28f, 0.66f,
      MyGUI::Align::Left | MyGUI::Align::VStretch, "SentientSands_JournalList");
  g_journalList->eventListSelectAccept += MyGUI::newDelegate(OnJournalSelect);
  g_journalList->eventListChangePosition += MyGUI::newDelegate(OnJournalSelect);

  g_journalPrevBtn = AddRowButton(client, "<", 0.02f, 0.78f, 0.05f,
                                  "SentientSands_JournalPrevBtn",
                                  OnJournalPrevClick);
  g_journalPageText = AddRowLabel(client, "", 0.07f, 0.79f, 0.18f,
                                  "SentientSands_JournalPageText");
  g_journalPageText->setTextAlign(MyGUI::Align::Center);
  g_journalNextBtn = AddRowButton(client, ">", 0.25f, 0.78f, 0.05f,
                                  "SentientSands_JournalNextBtn",
                                  OnJournalNextClick);
  AddRowButton(client, "New Entry", 0.02f, 0.88f, 0.135f,
               "SentientSands_JournalNewBtn", OnJournalNewClick);
  AddRowButton(client, "Delete", 0.165f, 0.88f, 0.135f,
               "SentientSands_JournalDeleteBtn", OnJournalDeleteClick);

  g_journalTime =
      AddRowLabel(client, "", 0.32f, 0.02f, 0.66f, "SentientSands_JournalTime");
  g_journalTime->setTextColour(MyGUI::Colour(1.0f, 0.9f, 0.5f));
  AddRowLabel(client, T("Title"), 0.32f, 0.10f, 0.06f,
              "SentientSands_JournalTitleLabel");
  g_journalTitle =
      AddRowBox(client, 0.38f, 0.10f, 0.60f, "SentientSands_JournalTitle");
  g_journalText = AddWordWrapBox(client, 0.32f, 0.18f, 0.66f, 0.68f,
                                 "SentientSands_JournalText");
  g_journalStatus = AddRowLabel(client, "", 0.32f, 0.89f, 0.50f,
                                "SentientSands_JournalStatus");
  AddRowButton(client, "Save", 0.84f, 0.88f, 0.14f,
               "SentientSands_JournalSaveBtn", OnJournalSaveClick);

  ShowJournalEntry("", "", "");
  SetJournalStatus(T("Select an entry, or press New Entry."));
  RequestJournalPage(1);
}

} // namespace UI
} // namespace SentientSands
