#include "LibraryWindow.h"
#include "../core/Comm.h"
#include "../core/Globals.h"
#include "../core/Utils.h"
#include <mygui/MyGUI_Button.h>
#include <mygui/MyGUI_Delegate.h>
#include <mygui/MyGUI_Gui.h>
#include <mygui/MyGUI_ListBox.h>
#include <mygui/MyGUI_Window.h>
#include <string>
#include <vector>

namespace SentientSands {
namespace UI {

MyGUI::Window *g_libraryWindow = nullptr;
MyGUI::ListBox *g_libraryList = nullptr;
MyGUI::EditBox *g_libraryText = nullptr;
MyGUI::TextBox *g_libraryName = nullptr;
MyGUI::Button *g_libraryFavBtn = nullptr;
MyGUI::EditBox *g_librarySearch = nullptr;

std::vector<std::string> g_libraryStorageIds;
std::string g_librarySortMode = "alphabetical";
int g_libraryRequest = 0;

struct LibraryRow {
  std::string name;
  std::string sid;
  bool fav;
};
static std::vector<LibraryRow> g_libraryRows;
static int g_libraryListRequest = 0;

static const int LIBRARY_FACT_COUNT = 9;
static const char *LIBRARY_FACT_KEYS[] = {"race",     "faction", "sex",
                                          "origin",   "job",     "location",
                                          "relation", "alias",   "bio"};
static const char *LIBRARY_FACT_LABELS[] = {"Race",     "Faction", "Sex",
                                            "Origin",   "Job",     "Location",
                                            "Relation", "Alias",   "Bio"};
MyGUI::TextBox *g_libraryFacts[LIBRARY_FACT_COUNT] = {nullptr};

void CloseLibraryUI() {
  g_libraryRequest++;
  g_libraryListRequest++;
  if (g_libraryWindow) {
    DestroyWindow(g_libraryWindow);
    g_libraryList = nullptr;
    g_libraryText = nullptr;
    g_libraryName = nullptr;
    for (int i = 0; i < LIBRARY_FACT_COUNT; i++)
      g_libraryFacts[i] = nullptr;
    g_libraryFavBtn = nullptr;
    g_librarySearch = nullptr;
    g_libraryStorageIds.clear();
    g_libraryRows.clear();
  }
}

static std::string SelectedLibrarySid() {
  size_t index =
      g_libraryList ? g_libraryList->getIndexSelected() : MyGUI::ITEM_NONE;
  return index < g_libraryStorageIds.size() ? g_libraryStorageIds[index] : "";
}

static void RequestLibraryList() {
  PostForGameThread(L"/characters",
                    "{\"sort\":\"" + g_librarySortMode + "\"}",
                    "POPULATE_LIBRARY", ToString(++g_libraryListRequest));
}

void OnLibrarySortLatest(MyGUI::Widget *sender) {
  g_librarySortMode = "latest";
  RequestLibraryList();
}

void OnLibrarySortAZ(MyGUI::Widget *sender) {
  g_librarySortMode = "alphabetical";
  RequestLibraryList();
}

void OnLibraryFavoriteClick(MyGUI::Widget *sender) {
  std::string sid = SelectedLibrarySid();
  if (!sid.empty())
    PostForGameThread(L"/favorite", "{\"sid\":\"" + EscapeJSON(sid) + "\"}",
                      "REFRESH_LIBRARY", "");
}

static const char *BIO_PARTS[] = {"Personality", "Backstory", "SpeechQuirks"};
static const char *BIO_CHOICES[] = {"Full bio", "Personality", "Backstory",
                                    "Speech"};

MyGUI::Window *g_bioWindow = nullptr;
MyGUI::Button *g_bioChoiceBtns[4] = {nullptr, nullptr, nullptr, nullptr};
MyGUI::EditBox *g_bioInstructions = nullptr;
MyGUI::EditBox *g_bioTexts[3] = {nullptr, nullptr, nullptr};
MyGUI::Button *g_bioConfirmBtn = nullptr;
MyGUI::TextBox *g_bioStatus = nullptr;
int g_bioChoice = 0;
int g_bioRequest = 0;
std::string g_bioSid;
std::string g_bioName;
std::string g_bioCampaign;

// The player can close the window, or open it for another NPC, while a
// request runs, so each close makes the pending reply stale.
void CloseBioUI() {
  g_bioRequest++;
  if (!g_bioWindow)
    return;
  if (MyGUI::Gui::getInstancePtr())
    MyGUI::Gui::getInstancePtr()->destroyWidget(g_bioWindow);
  g_bioWindow = nullptr;
  for (int i = 0; i < 4; i++)
    g_bioChoiceBtns[i] = nullptr;
  for (int i = 0; i < 3; i++)
    g_bioTexts[i] = nullptr;
  g_bioInstructions = nullptr;
  g_bioConfirmBtn = nullptr;
  g_bioStatus = nullptr;
}

void OnBioWindowButtonPressed(MyGUI::Window *sender, const std::string &name) {
  if (name == "close")
    CloseBioUI();
}

void OnBioCancelClick(MyGUI::Widget *sender) { CloseBioUI(); }

bool BioPartChosen(int part) {
  return g_bioChoice == 0 || g_bioChoice == part + 1;
}

void SetBioStatus(const std::string &text) {
  if (g_bioStatus)
    g_bioStatus->setCaption(Utf8ToWide(text).c_str());
}

void StartBioRequest(const wchar_t *endpoint, const std::string &json,
                     const std::string &command) {
  if (g_bioConfirmBtn)
    g_bioConfirmBtn->setEnabled(false);
  PostForGameThread(endpoint, json, command, ToString(g_bioRequest));
}

void ShowBioFailure(const std::string &prefixKey, const std::string &reply) {
  std::string text = FailureText(prefixKey, reply);
  // Edit Bio opens no window until the stored texts arrive
  if (!g_bioWindow) {
    SetLibraryText(text);
    return;
  }
  SetBioStatus(text);
  g_bioConfirmBtn->setEnabled(true);
}

void OnBioWriteClick(MyGUI::Widget *sender) {
  std::string parts;
  for (int i = 0; i < 3; i++)
    if (BioPartChosen(i))
      parts += std::string(parts.empty() ? "" : ",") + "\"" + BIO_PARTS[i] +
               "\"";
  SetBioStatus(T("This may take a moment..."));
  StartBioRequest(L"/write_bio",
                  "{\"sid\":\"" + EscapeJSON(g_bioSid) + "\",\"parts\":[" +
                      parts + "],\"instructions\":\"" +
                      EscapeJSON(g_bioInstructions->getOnlyText().asUTF8()) +
                      "\"}",
                  "BIO_WRITTEN");
}

void OnBioKeepClick(MyGUI::Widget *sender) {
  std::string bio;
  for (int i = 0; i < 3; i++)
    if (g_bioTexts[i])
      bio += std::string(bio.empty() ? "" : ",") + "\"" + BIO_PARTS[i] +
             "\":\"" + EscapeJSON(g_bioTexts[i]->getOnlyText().asUTF8()) +
             "\"";
  SetBioStatus("");
  StartBioRequest(L"/keep_bio",
                  "{\"sid\":\"" + EscapeJSON(g_bioSid) +
                      "\",\"campaign\":\"" + EscapeJSON(g_bioCampaign) +
                      "\",\"bio\":{" + bio + "}}",
                  "BIO_KEPT");
}

void UpdateBioChoiceButtons() {
  for (int i = 0; i < 4; i++) {
    std::string label = T(BIO_CHOICES[i]);
    g_bioChoiceBtns[i]->setCaption(
        Utf8ToWide(i == g_bioChoice ? "> " + label + " <" : label).c_str());
  }
}

void OnBioChoiceClick(MyGUI::Widget *sender) {
  for (int i = 0; i < 4; i++)
    if (sender == g_bioChoiceBtns[i])
      g_bioChoice = i;
  UpdateBioChoiceButtons();
}

MyGUI::Widget *CreateBioWindow(const char *captionKey, float left, float top,
                               float width, float height) {
  MyGUI::Gui *gui = MyGUI::Gui::getInstancePtr();
  if (!gui)
    return nullptr;
  CloseBioUI();
  g_bioWindow = gui->createWidgetReal<MyGUI::Window>(
      "Kenshi_WindowCX", left, top, width, height, MyGUI::Align::Center,
      "Popup", "SentientSands_BioWindow");
  g_bioWindow->setCaption(Utf8ToWide(T(captionKey)).c_str());
  g_bioWindow->eventWindowButtonPressed +=
      MyGUI::newDelegate(OnBioWindowButtonPressed);
  return g_bioWindow->getClientWidget();
}

MyGUI::TextBox *AddBioLine(MyGUI::Widget *client, const std::string &text,
                           float top, const std::string &name) {
  MyGUI::TextBox *line = client->createWidgetReal<MyGUI::TextBox>(
      "Kenshi_TextboxStandardText", 0.05f, top, 0.9f, 0.05f,
      MyGUI::Align::Top | MyGUI::Align::HStretch, name);
  line->setCaption(Utf8ToWide(text).c_str());
  line->setTextAlign(MyGUI::Align::Left | MyGUI::Align::VCenter);
  return line;
}

MyGUI::EditBox *AddBioEditBox(MyGUI::Widget *client, float top, float height,
                              const std::string &name) {
  return AddWordWrapBox(client, 0.05f, top, 0.9f, height, name);
}

void AddBioButtons(MyGUI::Widget *client, const char *confirmKey,
                   void (*onConfirm)(MyGUI::Widget *), const char *cancelKey) {
  g_bioConfirmBtn = client->createWidgetReal<MyGUI::Button>(
      "Kenshi_Button1", 0.10f, 0.87f, 0.38f, 0.10f,
      MyGUI::Align::Bottom | MyGUI::Align::Left, "SentientSands_BioConfirmBtn");
  g_bioConfirmBtn->setCaption(Utf8ToWide(T(confirmKey)).c_str());
  g_bioConfirmBtn->eventMouseButtonClick += MyGUI::newDelegate(onConfirm);

  MyGUI::Button *cancelBtn = client->createWidgetReal<MyGUI::Button>(
      "Kenshi_Button1", 0.52f, 0.87f, 0.38f, 0.10f,
      MyGUI::Align::Bottom | MyGUI::Align::Right, "SentientSands_BioCancelBtn");
  cancelBtn->setCaption(Utf8ToWide(T(cancelKey)).c_str());
  cancelBtn->eventMouseButtonClick += MyGUI::newDelegate(OnBioCancelClick);
}

void CreateBioAskUI() {
  MyGUI::Widget *client =
      CreateBioWindow("Generate Bio", 0.28f, 0.20f, 0.44f, 0.55f);
  if (!client)
    return;
  g_bioChoice = 0;

  AddBioLine(client, g_bioName, 0.03f, "SentientSands_BioName");
  AddBioLine(client, T("What to write"), 0.11f, "SentientSands_BioChoiceLabel");
  for (int i = 0; i < 4; i++) {
    g_bioChoiceBtns[i] = client->createWidgetReal<MyGUI::Button>(
        "Kenshi_Button1", 0.05f + i * 0.23f, 0.17f, 0.21f, 0.08f,
        MyGUI::Align::Top | MyGUI::Align::Left,
        "SentientSands_BioChoice_" + ToString(i));
    g_bioChoiceBtns[i]->eventMouseButtonClick +=
        MyGUI::newDelegate(OnBioChoiceClick);
  }
  UpdateBioChoiceButtons();

  AddBioLine(client, T("Instructions (optional)"), 0.28f,
             "SentientSands_BioInstructionsLabel");
  g_bioInstructions =
      AddBioEditBox(client, 0.34f, 0.26f, "SentientSands_BioInstructions");
  AddBioLine(client,
             T("The LLM also reads the name, sex, race, faction, job, the race "
               "lore,"),
             0.62f, "SentientSands_BioHint1");
  AddBioLine(client, T("the current texts, and the chats with this character."),
             0.67f, "SentientSands_BioHint2");
  g_bioStatus = AddBioLine(client, "", 0.76f, "SentientSands_BioStatus");
  AddBioButtons(client, "Write", OnBioWriteClick, "Cancel");
}

void CreateBioEditUI(const std::string &reply) {
  MyGUI::Widget *client =
      CreateBioWindow("Edit Bio", 0.20f, 0.08f, 0.60f, 0.84f);
  if (!client)
    return;

  AddBioLine(client, g_bioName, 0.02f, "SentientSands_BioName");
  AddBioLine(client, T("Edit the text, then Keep to store it."), 0.07f,
             "SentientSands_BioEditHint");
  // The choice buttons stay live while the LLM writes, so the reply and not
  // the current choice names the parts
  bool written[3];
  int count = 0;
  for (int i = 0; i < 3; i++) {
    written[i] = reply.find("\"" + std::string(BIO_PARTS[i]) + "\":") !=
                 std::string::npos;
    count += written[i] ? 1 : 0;
  }
  float slot = 0.63f / count;
  float top = 0.14f;
  for (int i = 0; i < 3; i++) {
    if (!written[i])
      continue;
    AddBioLine(client, T(BIO_CHOICES[i + 1]), top,
               "SentientSands_BioLabel_" + ToString(i));
    g_bioTexts[i] = AddBioEditBox(client, top + 0.05f, slot - 0.07f,
                                  "SentientSands_BioText_" + ToString(i));
    g_bioTexts[i]->setCaption(
        Utf8ToWide(GetJsonValue(reply, BIO_PARTS[i])).c_str());
    top += slot;
  }
  g_bioStatus = AddBioLine(client, "", 0.79f, "SentientSands_BioStatus");
  AddBioButtons(client, "Keep", OnBioKeepClick, "Discard");
}

void OpenBioEditor(const std::string &data, const std::string &failureKey) {
  std::string reply;
  if (!TakeTaggedReply(data, g_bioRequest, reply))
    return;
  if (GetJsonValue(reply, "status") != "ok") {
    ShowBioFailure(failureKey, reply);
    return;
  }
  g_bioCampaign = GetJsonValue(reply, "campaign");
  CreateBioEditUI(reply);
}

void FinishKeptBio(const std::string &data) {
  std::string reply;
  if (!TakeTaggedReply(data, g_bioRequest, reply))
    return;
  if (GetJsonValue(reply, "status") != "ok") {
    ShowBioFailure("Keep failed: ", reply);
    return;
  }
  CloseBioUI();
  RefreshLibraryUI();
}

bool SelectBioNpc() {
  size_t index = g_libraryList->getIndexSelected();
  if (index == MyGUI::ITEM_NONE)
    return false;
  g_bioSid = g_libraryStorageIds[index];
  g_bioName = g_libraryList->getItemNameAt(index).asUTF8();
  return true;
}

void OnLibraryBioClick(MyGUI::Widget *sender) {
  if (SelectBioNpc())
    CreateBioAskUI();
}

void OnLibraryEditBioClick(MyGUI::Widget *sender) {
  if (!SelectBioNpc())
    return;
  CloseBioUI();
  StartBioRequest(L"/read_bio", "{\"sid\":\"" + EscapeJSON(g_bioSid) + "\"}",
                  "BIO_READ");
}

// setIndexSelected fires no change event, so a reload also refreshes the
// caption
static void ShowFavCaption() {
  std::string sid = SelectedLibrarySid();
  bool fav = false;
  for (size_t i = 0; i < g_libraryRows.size(); i++)
    if (g_libraryRows[i].sid == sid)
      fav = g_libraryRows[i].fav;
  g_libraryFavBtn->setCaption(
      Utf8ToWide(T(sid.empty() ? "Fav Toggle" : fav ? "Fav: [YES]" : "Fav: [NO]"))
          .c_str());
}

void ApplyLibraryFilter(const std::string &keepSid) {
  g_libraryList->removeAllItems();
  g_libraryStorageIds.clear();
  std::string query =
      g_librarySearch ? g_librarySearch->getOnlyText().asUTF8() : "";
  for (size_t i = 0; i < g_libraryRows.size(); i++) {
    const LibraryRow &row = g_libraryRows[i];
    if (!ContainsIgnoreCase(row.name, query))
      continue;
    g_libraryList->addItem(
        Utf8ToWide(row.fav ? "[*] " + row.name : row.name).c_str());
    g_libraryStorageIds.push_back(row.sid);
    if (row.sid == keepSid)
      g_libraryList->setIndexSelected(g_libraryStorageIds.size() - 1);
  }
  ShowFavCaption();
}

void OnLibrarySearchChange(MyGUI::EditBox *sender) {
  ApplyLibraryFilter(SelectedLibrarySid());
}

void PopulateLibraryUI(const std::string &data) {
  std::string reply;
  if (!g_libraryList || !TakeTaggedReply(data, g_libraryListRequest, reply) ||
      GetJsonValue(reply, "status") != "ok")
    return;
  std::vector<std::string> items =
      JsonArrayItems(GetJsonValue(reply, "characters"));
  g_libraryRows.clear();
  for (size_t i = 0; i < items.size(); i++) {
    LibraryRow row;
    row.name = GetJsonValue(items[i], "name");
    row.sid = GetJsonValue(items[i], "sid");
    row.fav = GetJsonValue(items[i], "fav") == "true";
    g_libraryRows.push_back(row);
  }
  ApplyLibraryFilter(SelectedLibrarySid());
}

void SetLibraryText(const std::string &text) {
  if (g_libraryText)
    ShowFromTop(g_libraryText, text);
}

void ShowLibraryProfile(const std::string &json) {
  if (!g_libraryName)
    return;
  g_libraryName->setCaption(Utf8ToWide(GetJsonValue(json, "name")).c_str());
  for (int i = 0; i < LIBRARY_FACT_COUNT; i++)
    g_libraryFacts[i]->setCaption(
        Utf8ToWide(GetJsonValue(json, LIBRARY_FACT_KEYS[i])).c_str());
  SetLibraryText(GetJsonValue(json, "text"));
}

// The player can pick another NPC, or close the window, while a request runs,
// and the replies can come back out of order
void SetLibraryProfile(const std::string &data) {
  std::string reply;
  if (!TakeTaggedReply(data, g_libraryRequest, reply))
    return;
  if (GetJsonValue(reply, "status") != "ok") {
    SetLibraryText(FailureText("Load failed: ", reply));
    return;
  }
  ShowLibraryProfile(reply);
}

// The server keys profiles by npc_id, and two NPCs can share a display name
static void StartLibraryHistory(const std::string &sid) {
  PostForGameThread(L"/history", "{\"npc\":\"" + EscapeJSON(sid) + "\"}",
                    "SET_LIBRARY_PROFILE", ToString(++g_libraryRequest));
}

void OnLibraryNPCSelect(MyGUI::ListBox *sender, size_t index) {
  if (index >= g_libraryStorageIds.size())
    return;
  ShowFavCaption();
  ShowLibraryProfile("");
  SetLibraryText(T("Loading profile for ") +
                 sender->getItemNameAt(index).asUTF8() + "...");
  StartLibraryHistory(g_libraryStorageIds[index]);
}

static CloseAction g_libraryClose = {CloseLibraryUI};

static void AddLibraryFact(MyGUI::Widget *client, int i) {
  float left = i % 2 ? 0.66f : 0.32f;
  float top = 0.075f + (i / 2) * 0.045f;
  float valueWidth = i == LIBRARY_FACT_COUNT - 1 ? 0.57f : 0.23f;
  MyGUI::Align align = MyGUI::Align::Left | MyGUI::Align::Top;
  AddLabel(client, T(LIBRARY_FACT_LABELS[i]), left, top, 0.09f, 0.045f, align,
           "SentientSands_LibFactLabel_" + ToString(i))
      ->setTextColour(MyGUI::Colour(0.7f, 0.7f, 0.7f));
  g_libraryFacts[i] =
      AddLabel(client, "", left + 0.09f, top, valueWidth, 0.045f, align,
               "SentientSands_LibFact_" + ToString(i));
}

void CreateLibraryUI() {
  CloseLibraryUI();
  MyGUI::Widget *client =
      OpenWindow(g_libraryWindow, 0.15f, 0.1f, 0.7f, 0.8f,
                 MyGUI::Align::Center, "Popup", "SentientSands_LibraryWindow",
                 T("AI Dialogue Library & Logs"), g_libraryClose);
  if (!client)
    return;
  MyGUI::Align left = MyGUI::Align::Left;
  MyGUI::Align topLeft = MyGUI::Align::Left | MyGUI::Align::Top;

  AddButton(client, T("Latest"), 0.02f, 0.015f, 0.09f, 0.05f, left,
            "SentientSands_LibLatestBtn", OnLibrarySortLatest);
  AddButton(client, T("A-Z"), 0.115f, 0.015f, 0.08f, 0.05f, left,
            "SentientSands_LibAZBtn", OnLibrarySortAZ);
  g_libraryFavBtn =
      AddButton(client, T("Fav Toggle"), 0.20f, 0.015f, 0.1f, 0.05f, left,
                "SentientSands_LibFavBtn", OnLibraryFavoriteClick);

  AddLabel(client, T("Search"), 0.02f, 0.075f, 0.08f, 0.05f, topLeft,
           "SentientSands_LibSearchLabel");
  g_librarySearch = AddLineBox(client, 0.10f, 0.075f, 0.20f, 0.05f, topLeft,
                               "SentientSands_LibSearch");
  g_librarySearch->eventEditTextChange +=
      MyGUI::newDelegate(OnLibrarySearchChange);

  g_libraryList = client->createWidgetReal<MyGUI::ListBox>(
      "Kenshi_ListBox", 0.02f, 0.135f, 0.28f, 0.845f,
      MyGUI::Align::Left | MyGUI::Align::VStretch, "SentientSands_LibraryList");
  g_libraryList->eventListSelectAccept +=
      MyGUI::newDelegate(OnLibraryNPCSelect);
  g_libraryList->eventListChangePosition +=
      MyGUI::newDelegate(OnLibraryNPCSelect);

  g_libraryName = AddLabel(client, "", 0.32f, 0.015f, 0.44f, 0.05f, topLeft,
                           "SentientSands_LibName");
  g_libraryName->setTextColour(MyGUI::Colour(1.0f, 0.9f, 0.5f));
  AddButton(client, T("Generate Bio"), 0.775f, 0.015f, 0.11f, 0.05f, left,
            "SentientSands_LibBioBtn", OnLibraryBioClick);
  AddButton(client, T("Edit Bio"), 0.89f, 0.015f, 0.09f, 0.05f, left,
            "SentientSands_LibEditBioBtn", OnLibraryEditBioClick);

  for (int i = 0; i < LIBRARY_FACT_COUNT; i++)
    AddLibraryFact(client, i);

  g_libraryText = AddTextView(client, 0.32f, 0.31f, 0.66f, 0.67f,
                              MyGUI::Align::Default, "SentientSands_LibraryText");
  SetLibraryText(T("Select an NPC from the list to view their profile."));

  RequestLibraryList();
}

} // namespace UI
} // namespace SentientSands
