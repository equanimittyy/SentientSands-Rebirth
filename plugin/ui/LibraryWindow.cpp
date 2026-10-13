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
static MyGUI::ListBox *g_libraryList = nullptr;
static MyGUI::EditBox *g_libraryText = nullptr;
static MyGUI::TextBox *g_libraryName = nullptr;
static MyGUI::Button *g_libraryFavBtn = nullptr;
static MyGUI::EditBox *g_librarySearch = nullptr;

static std::vector<std::string> g_libraryStorageIds;
static std::string g_librarySortMode = "alphabetical";
static int g_libraryRequest = 0;

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
static MyGUI::TextBox *g_libraryFacts[LIBRARY_FACT_COUNT] = {nullptr};

static void CloseLibraryUI() {
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

static void OnLibrarySortLatest(MyGUI::Widget *sender) {
  g_librarySortMode = "latest";
  RequestLibraryList();
}

static void OnLibrarySortAZ(MyGUI::Widget *sender) {
  g_librarySortMode = "alphabetical";
  RequestLibraryList();
}

static void OnLibraryFavoriteClick(MyGUI::Widget *sender) {
  std::string sid = SelectedLibrarySid();
  if (!sid.empty())
    PostForGameThread(L"/favorite", "{\"sid\":\"" + EscapeJSON(sid) + "\"}",
                      "REFRESH_LIBRARY", "");
}

static const char *BIO_PARTS[] = {"Personality", "Backstory", "SpeechQuirks"};
static const char *BIO_CHOICES[] = {"Full bio", "Personality", "Backstory",
                                    "Speech"};

static void SetLibraryText(const std::string &text);
static EditorPopup g_bio = {nullptr, nullptr, nullptr, 0, SetLibraryText};
static MyGUI::Button *g_bioChoiceBtns[4] = {nullptr, nullptr, nullptr, nullptr};
static MyGUI::EditBox *g_bioInstructions = nullptr;
static MyGUI::EditBox *g_bioTexts[3] = {nullptr, nullptr, nullptr};
static int g_bioChoice = 0;
static std::string g_bioSid;
static std::string g_bioName;
static std::string g_bioCampaign;

static void CloseBioUI() {
  CloseEditor(g_bio);
  for (int i = 0; i < 4; i++)
    g_bioChoiceBtns[i] = nullptr;
  for (int i = 0; i < 3; i++)
    g_bioTexts[i] = nullptr;
  g_bioInstructions = nullptr;
}

static CloseAction g_bioClose = {CloseBioUI};

static void OnBioCancelClick(MyGUI::Widget *sender) { CloseBioUI(); }

static bool BioPartChosen(int part) {
  return g_bioChoice == 0 || g_bioChoice == part + 1;
}

static void OnBioWriteClick(MyGUI::Widget *sender) {
  std::string parts;
  for (int i = 0; i < 3; i++)
    if (BioPartChosen(i))
      parts += std::string(parts.empty() ? "" : ",") + "\"" + BIO_PARTS[i] +
               "\"";
  SetEditorStatus(g_bio, T("This may take a moment..."));
  StartEditorRequest(g_bio, L"/write_bio",
                  "{\"sid\":\"" + EscapeJSON(g_bioSid) + "\",\"parts\":[" +
                      parts + "],\"instructions\":\"" +
                      EscapeJSON(g_bioInstructions->getOnlyText().asUTF8()) +
                      "\"}",
                  "BIO_WRITTEN");
}

static void OnBioKeepClick(MyGUI::Widget *sender) {
  std::string bio;
  for (int i = 0; i < 3; i++)
    if (g_bioTexts[i])
      bio += std::string(bio.empty() ? "" : ",") + "\"" + BIO_PARTS[i] +
             "\":\"" + EscapeJSON(g_bioTexts[i]->getOnlyText().asUTF8()) +
             "\"";
  SetEditorStatus(g_bio, "");
  StartEditorRequest(g_bio, L"/keep_bio",
                  "{\"sid\":\"" + EscapeJSON(g_bioSid) +
                      "\",\"campaign\":\"" + EscapeJSON(g_bioCampaign) +
                      "\",\"bio\":{" + bio + "}}",
                  "BIO_KEPT");
}

static void UpdateBioChoiceButtons() {
  for (int i = 0; i < 4; i++) {
    std::string label = T(BIO_CHOICES[i]);
    g_bioChoiceBtns[i]->setCaption(
        PlainText(i == g_bioChoice ? "> " + label + " <" : label));
  }
}

static void OnBioChoiceClick(MyGUI::Widget *sender) {
  for (int i = 0; i < 4; i++)
    if (sender == g_bioChoiceBtns[i])
      g_bioChoice = i;
  UpdateBioChoiceButtons();
}

static void CreateBioAskUI() {
  CloseBioUI();
  MyGUI::Widget *client =
      OpenEditor(g_bio, g_bioClose, "SentientSands_Bio", T("Generate Bio"),
                 0.28f, 0.20f, 0.44f, 0.55f, T("Write"), OnBioWriteClick,
                 T("Cancel"), OnBioCancelClick);
  if (!client)
    return;
  g_bioChoice = 0;

  AddEditorLine(client, g_bioName, 0.03f, "SentientSands_BioName");
  AddEditorLine(client, T("What to write"), 0.11f, "SentientSands_BioChoiceLabel");
  for (int i = 0; i < 4; i++)
    g_bioChoiceBtns[i] =
        AddButton(client, "", 0.05f + i * 0.23f, 0.17f, 0.21f, 0.08f,
                  MyGUI::Align::Top | MyGUI::Align::Left,
                  "SentientSands_BioChoice_" + ToString(i), OnBioChoiceClick);
  UpdateBioChoiceButtons();

  AddEditorLine(client, T("Instructions (optional)"), 0.28f,
             "SentientSands_BioInstructionsLabel");
  g_bioInstructions =
      AddEditorBox(client, 0.34f, 0.26f, "SentientSands_BioInstructions");
  AddEditorLine(client,
             T("The LLM also reads the name, sex, race, faction, job, the race "
               "lore,"),
             0.62f, "SentientSands_BioHint1");
  AddEditorLine(client, T("the current texts, and the chats with this character."),
             0.67f, "SentientSands_BioHint2");
  g_bio.status = AddEditorLine(client, "", 0.76f, "SentientSands_BioStatus");
}

static void CreateBioEditUI(const std::string &reply) {
  CloseBioUI();
  MyGUI::Widget *client =
      OpenEditor(g_bio, g_bioClose, "SentientSands_Bio", T("Edit Bio"), 0.20f,
                 0.08f, 0.60f, 0.84f, T("Keep"), OnBioKeepClick, T("Discard"),
                 OnBioCancelClick);
  if (!client)
    return;

  AddEditorLine(client, g_bioName, 0.02f, "SentientSands_BioName");
  AddEditorLine(client, T("Edit the text, then Keep to store it."), 0.07f,
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
    AddEditorLine(client, T(BIO_CHOICES[i + 1]), top,
               "SentientSands_BioLabel_" + ToString(i));
    g_bioTexts[i] = AddEditorBox(client, top + 0.05f, slot - 0.07f,
                                  "SentientSands_BioText_" + ToString(i));
    g_bioTexts[i]->setOnlyText(
        Utf8ToWide(GetJsonValue(reply, BIO_PARTS[i])).c_str());
    top += slot;
  }
  g_bio.status = AddEditorLine(client, "", 0.79f, "SentientSands_BioStatus");
}

void OpenBioEditor(const std::string &data, const std::string &failureKey) {
  std::string reply;
  if (!TakeEditorReply(g_bio, data, reply))
    return;
  if (GetJsonValue(reply, "status") != "ok") {
    ShowEditorFailure(g_bio, failureKey, reply);
    return;
  }
  g_bioCampaign = GetJsonValue(reply, "campaign");
  CreateBioEditUI(reply);
}

void FinishKeptBio(const std::string &data) {
  std::string reply;
  if (!TakeEditorReply(g_bio, data, reply))
    return;
  if (GetJsonValue(reply, "status") != "ok") {
    ShowEditorFailure(g_bio, "Keep failed: ", reply);
    return;
  }
  CloseBioUI();
  RefreshLibraryUI();
}

static const LibraryRow *RowOf(const std::string &sid) {
  for (size_t i = 0; i < g_libraryRows.size(); i++)
    if (g_libraryRows[i].sid == sid)
      return &g_libraryRows[i];
  return nullptr;
}

static bool SelectBioNpc() {
  size_t index = g_libraryList->getIndexSelected();
  if (index == MyGUI::ITEM_NONE)
    return false;
  g_bioSid = g_libraryStorageIds[index];
  const LibraryRow *row = RowOf(g_bioSid);
  g_bioName = row ? row->name : "";
  return true;
}

static void OnLibraryBioClick(MyGUI::Widget *sender) {
  if (SelectBioNpc())
    CreateBioAskUI();
}

static void OnLibraryEditBioClick(MyGUI::Widget *sender) {
  if (!SelectBioNpc())
    return;
  CloseBioUI();
  StartEditorRequest(g_bio, L"/read_bio", "{\"sid\":\"" + EscapeJSON(g_bioSid) + "\"}",
                  "BIO_READ");
}

// setIndexSelected fires no change event, so a reload also refreshes the
// caption
static void ShowFavCaption() {
  std::string sid = SelectedLibrarySid();
  const LibraryRow *row = RowOf(sid);
  bool fav = row && row->fav;
  g_libraryFavBtn->setCaption(PlainText(
      T(sid.empty() ? "Fav Toggle" : fav ? "Fav: [YES]" : "Fav: [NO]")));
}

static void ApplyLibraryFilter(const std::string &keepSid) {
  g_libraryList->removeAllItems();
  g_libraryStorageIds.clear();
  std::string query =
      g_librarySearch ? g_librarySearch->getOnlyText().asUTF8() : "";
  for (size_t i = 0; i < g_libraryRows.size(); i++) {
    const LibraryRow &row = g_libraryRows[i];
    if (!ContainsIgnoreCase(row.name, query))
      continue;
    g_libraryList->addItem(PlainText(row.fav ? "[*] " + row.name : row.name));
    g_libraryStorageIds.push_back(row.sid);
    if (row.sid == keepSid)
      g_libraryList->setIndexSelected(g_libraryStorageIds.size() - 1);
  }
  ShowFavCaption();
}

static void OnLibrarySearchChange(MyGUI::EditBox *sender) {
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
    row.fav = JsonTrue(items[i], "fav");
    g_libraryRows.push_back(row);
  }
  ApplyLibraryFilter(SelectedLibrarySid());
}

static void SetLibraryText(const std::string &text) {
  if (g_libraryText)
    ShowFromTop(g_libraryText, text);
}

static void ShowLibraryProfile(const std::string &json) {
  if (!g_libraryName)
    return;
  g_libraryName->setCaption(PlainText(GetJsonValue(json, "name")));
  for (int i = 0; i < LIBRARY_FACT_COUNT; i++)
    g_libraryFacts[i]->setCaption(
        PlainText(GetJsonValue(json, LIBRARY_FACT_KEYS[i])));
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

static void OnLibraryNPCSelect(MyGUI::ListBox *sender, size_t index) {
  if (index >= g_libraryStorageIds.size())
    return;
  ShowFavCaption();
  ShowLibraryProfile("");
  const LibraryRow *row = RowOf(g_libraryStorageIds[index]);
  SetLibraryText(T("Loading profile for ") + (row ? row->name : "") + "...");
  StartLibraryHistory(g_libraryStorageIds[index]);
}

void RefreshLibraryUI() {
  if (!g_libraryList)
    return;
  RequestLibraryList();
  std::string sid = SelectedLibrarySid();
  if (!sid.empty())
    StartLibraryHistory(sid);
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
