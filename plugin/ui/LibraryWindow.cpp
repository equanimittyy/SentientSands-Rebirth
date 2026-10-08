#include "LibraryWindow.h"
#include "../core/Comm.h"
#include "../core/Globals.h"
#include "../core/Utils.h"
#include <algorithm>
#include <cstdlib>
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
MyGUI::Button *g_libraryLatestBtn = nullptr;
MyGUI::Button *g_libraryAZBtn = nullptr;
MyGUI::Button *g_libraryFavBtn = nullptr;
MyGUI::Button *g_libraryBioBtn = nullptr;
MyGUI::EditBox *g_librarySearch = nullptr;

std::vector<std::string> g_libraryStorageIds;
std::vector<std::string> g_libraryAllNames;
std::vector<std::string> g_libraryAllSids;
std::string g_librarySortMode = "alphabetical";
std::vector<std::string> g_libraryFavorites;
int g_libraryRequest = 0;

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
  if (g_libraryWindow) {
    if (MyGUI::Gui::getInstancePtr())
      MyGUI::Gui::getInstancePtr()->destroyWidget(g_libraryWindow);
    g_libraryWindow = nullptr;
    g_libraryList = nullptr;
    g_libraryText = nullptr;
    g_libraryName = nullptr;
    for (int i = 0; i < LIBRARY_FACT_COUNT; i++)
      g_libraryFacts[i] = nullptr;
    g_libraryLatestBtn = nullptr;
    g_libraryAZBtn = nullptr;
    g_libraryFavBtn = nullptr;
    g_libraryBioBtn = nullptr;
    g_librarySearch = nullptr;
    g_libraryStorageIds.clear();
    g_libraryAllNames.clear();
    g_libraryAllSids.clear();
    g_libraryFavorites.clear();
  }
}

void OnLibrarySortLatest(MyGUI::Widget *sender) {
  g_librarySortMode = "latest";
  CreateThread(NULL, 0, LibraryListThread, NULL, 0, NULL);
}

void OnLibrarySortAZ(MyGUI::Widget *sender) {
  g_librarySortMode = "alphabetical";
  CreateThread(NULL, 0, LibraryListThread, NULL, 0, NULL);
}

void OnLibraryFavoriteClick(MyGUI::Widget *sender) {
  size_t index = g_libraryList->getIndexSelected();
  if (index == MyGUI::ITEM_NONE)
    return;

  std::string sid = g_libraryStorageIds[index];

  LibraryTask *t = new LibraryTask();
  t->npcName = g_libraryList->getItemNameAt(index);
  t->json = "{\"sid\":\"" + EscapeJSON(sid) + "\"}";

  struct FavHelper {
    static DWORD WINAPI ThreadProc(LPVOID lpParam) {
      LibraryTask *lt = (LibraryTask *)lpParam;
      PostToPythonWithResponse(L"/favorite", lt->json);
      delete lt;
      CreateThread(NULL, 0, LibraryListThread, NULL, 0, NULL);
      return 0;
    }
  };

  CreateThread(NULL, 0, FavHelper::ThreadProc, t, 0, NULL);
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

struct BioTask {
  int request;
  std::wstring endpoint;
  std::string json;
  std::string command;
};

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

DWORD WINAPI BioThread(LPVOID lpParam) {
  BioTask *t = (BioTask *)lpParam;
  std::string response = PostToPythonWithResponse(t->endpoint, t->json);
  std::string pipeMsg =
      "CMD: " + t->command + ": " + ToString(t->request) + "|" + response;
  EnterCriticalSection(&g_msgMutex);
  g_messageQueue.push_back(pipeMsg);
  LeaveCriticalSection(&g_msgMutex);
  delete t;
  return 0;
}

void StartBioRequest(const wchar_t *endpoint, const std::string &json,
                     const std::string &command) {
  if (g_bioConfirmBtn)
    g_bioConfirmBtn->setEnabled(false);
  BioTask *t = new BioTask();
  t->request = g_bioRequest;
  t->endpoint = endpoint;
  t->json = json;
  t->command = command;
  CreateThread(NULL, 0, BioThread, t, 0, NULL);
}

bool TakeBioReply(const std::string &data, std::string &reply) {
  size_t sep = data.find('|');
  if (sep == std::string::npos || atoi(data.c_str()) != g_bioRequest)
    return false;
  reply = data.substr(sep + 1);
  return true;
}

void ShowBioFailure(const std::string &prefixKey, const std::string &reply) {
  std::string error = GetJsonValue(reply, "message");
  std::string text =
      T(prefixKey) + (error.empty() ? T("Unknown error") : error);
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
  MyGUI::EditBox *box = client->createWidgetReal<MyGUI::EditBox>(
      "Kenshi_EditBox", 0.05f, top, 0.9f, height,
      MyGUI::Align::Top | MyGUI::Align::HStretch, name);
  box->setEditMultiLine(true);
  box->setEditWordWrap(true);
  box->setVisibleVScroll(true);
  // MyGUI cuts text at 2048 characters by default, and Keep would store the
  // cut text
  box->setMaxTextLength(16384);
  box->setTextAlign(MyGUI::Align::Left | MyGUI::Align::Top);
  box->setFontHeight(18);
  return box;
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
  if (!TakeBioReply(data, reply))
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
  if (!TakeBioReply(data, reply))
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

void ApplyLibraryFilter(const std::string &keepSid) {
  g_libraryList->removeAllItems();
  g_libraryStorageIds.clear();
  std::string query =
      g_librarySearch ? g_librarySearch->getOnlyText().asUTF8() : "";
  for (size_t i = 0; i < g_libraryAllSids.size(); i++) {
    const std::string &name = g_libraryAllNames[i];
    const std::string &sid = g_libraryAllSids[i];
    if (!ContainsIgnoreCase(name, query))
      continue;
    bool isFav = std::find(g_libraryFavorites.begin(), g_libraryFavorites.end(),
                           sid) != g_libraryFavorites.end();
    g_libraryList->addItem(Utf8ToWide(isFav ? "[*] " + name : name).c_str());
    g_libraryStorageIds.push_back(sid);
    if (sid == keepSid)
      g_libraryList->setIndexSelected(g_libraryStorageIds.size() - 1);
  }
}

void OnLibrarySearchChange(MyGUI::EditBox *sender) {
  size_t index = g_libraryList->getIndexSelected();
  ApplyLibraryFilter(index < g_libraryStorageIds.size()
                         ? g_libraryStorageIds[index]
                         : "");
}

void PopulateLibraryUI(const std::string &dataInput) {
  if (!g_libraryList)
    return;

  size_t selIndex = g_libraryList->getIndexSelected();
  std::string selSid = "";
  if (selIndex != MyGUI::ITEM_NONE && selIndex < g_libraryStorageIds.size()) {
    selSid = g_libraryStorageIds[selIndex];
  }

  g_libraryAllNames.clear();
  g_libraryAllSids.clear();
  g_libraryFavorites.clear();

  std::string data = dataInput;
  std::string favsPart = "";
  size_t mainPipe = std::string::npos;
  // "name|sid,...|[favs]": entries contain '|' too, so split at the last '|' followed by '['
  for (int i = (int)strlen(data.c_str()) - 1; i >= 0; i--) {
    if (data[i] == '|') {
      if (data.find('[', i) != std::string::npos) {
        mainPipe = (size_t)i;
        break;
      }
    }
  }
  if (mainPipe != std::string::npos &&
      data.find("[", mainPipe) != std::string::npos) {
    favsPart = data.substr(mainPipe + 1);
    data = data.substr(0, mainPipe);
  }

  if (!favsPart.empty()) {
    size_t cur = 0, next;
    while ((next = favsPart.find("\"", cur)) != std::string::npos) {
      size_t end = favsPart.find("\"", next + 1);
      if (end == std::string::npos)
        break;
      g_libraryFavorites.push_back(favsPart.substr(next + 1, end - next - 1));
      cur = end + 1;
    }
  }

  if (!data.empty() && data[0] == '[')
    data = data.substr(1);
  if (!data.empty() && data[data.length() - 1] == ']')
    data = data.substr(0, data.length() - 1);

  auto trim = [](std::string &s) {
    s.erase(0, s.find_first_not_of(" \t\r\n"));
    s.erase(s.find_last_not_of(" \t\r\n") + 1);
  };

  if (!data.empty()) {
    size_t cur = 0, next;
    while ((next = data.find(",", cur)) != std::string::npos) {
      std::string entry = data.substr(cur, next - cur);
      trim(entry);
      if (!entry.empty()) {
        if (entry[0] == '"')
          entry = entry.substr(1);
        if (entry[entry.length() - 1] == '"')
          entry = entry.substr(0, entry.length() - 1);

        size_t pipePos = entry.find("|");
        std::string sid = entry;
        std::string display = entry;
        if (pipePos != std::string::npos) {
          display = entry.substr(0, pipePos);
          sid = entry.substr(pipePos + 1);
        }

        g_libraryAllNames.push_back(display);
        g_libraryAllSids.push_back(sid);
      }
      cur = next + 1;
    }
    std::string last = data.substr(cur);
    trim(last);
    if (!last.empty()) {
      if (last[0] == '"')
        last = last.substr(1);
      if (last[last.length() - 1] == '"')
        last = last.substr(0, last.length() - 1);

      size_t pipePos = last.find("|");
      std::string sid = last;
      std::string display = last;
      if (pipePos != std::string::npos) {
        display = last.substr(0, pipePos);
        sid = last.substr(pipePos + 1);
      }

      g_libraryAllNames.push_back(display);
      g_libraryAllSids.push_back(sid);
    }
  }

  ApplyLibraryFilter(selSid);
}

void SetLibraryText(const std::string &text) {
  if (!g_libraryText)
    return;
  g_libraryText->setOnlyText(Utf8ToWide(text).c_str());
  // setOnlyText leaves the cursor at the end, and the view follows the cursor
  g_libraryText->setTextCursor(0);
  g_libraryText->setVScrollPosition(0);
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
  size_t sep = data.find('|');
  if (sep == std::string::npos || atoi(data.c_str()) != g_libraryRequest)
    return;
  ShowLibraryProfile(data.substr(sep + 1));
}

void StartLibraryHistory(const std::string &npcName, const std::string &sid) {
  LibraryTask *t = new LibraryTask();
  t->npcName = npcName;
  t->json = "{\"npc\":\"" + EscapeJSON(sid) + "\"}";
  t->request = ++g_libraryRequest;
  CreateThread(NULL, 0, LibraryHistoryThread, t, 0, NULL);
}

void OnLibraryNPCSelect(MyGUI::ListBox *sender, size_t index) {
  if (index == MyGUI::ITEM_NONE)
    return;
  std::string displayName = sender->getItemNameAt(index);

  // The server keys profiles by npc_id, and two NPCs can share a display name
  std::string storageId = displayName;
  if (index < g_libraryStorageIds.size()) {
    storageId = g_libraryStorageIds[index];
  }

  if (g_libraryFavBtn) {
    bool isFav = false;
    for (size_t f = 0; f < g_libraryFavorites.size(); f++) {
      if (g_libraryFavorites[f] == storageId) {
        isFav = true;
        break;
      }
    }
    g_libraryFavBtn->setCaption(
        Utf8ToWide(isFav ? T("Fav: [YES]") : T("Fav: [NO]")).c_str());
  }

  ShowLibraryProfile("");
  SetLibraryText(T("Loading profile for ") + displayName + "...");
  StartLibraryHistory(displayName, storageId);
}

void OnLibraryWindowButtonPressed(MyGUI::Window *sender,
                                  const std::string &name) {
  if (name == "close")
    CloseLibraryUI();
}

DWORD WINAPI LibraryListThread(LPVOID lpParam) {
  Log(LOG_DEBUG, "LIBRARY: Fetching characters (Sort: " + g_librarySortMode +
                     ")...");
  std::string json = "{\"sort\":\"" + g_librarySortMode + "\"}";
  std::string response = PostToPythonWithResponse(L"/characters", json);
  if (!response.empty()) {
    std::string chars = GetJsonValue(response, "names");
    if (chars.empty())
      chars = GetJsonValue(response, "characters");

    if (!chars.empty()) {
      std::string favs = GetJsonValue(response, "favorites");
      std::string pipeMsg = "CMD: POPULATE_LIBRARY: " + chars + "|" + favs;
      EnterCriticalSection(&g_msgMutex);
      g_messageQueue.push_back(pipeMsg);
      LeaveCriticalSection(&g_msgMutex);
    }
  }
  return 0;
}

DWORD WINAPI LibraryHistoryThread(LPVOID lpParam) {
  LibraryTask *t = (LibraryTask *)lpParam;
  Log(LOG_DEBUG, "LIBRARY: Fetching history for " + t->npcName);
  std::string response = PostToPythonWithResponse(L"/history", t->json);
  Log(LOG_DEBUG,
      "LIBRARY: Received " + ToString((int)response.length()) + " bytes");
  if (!GetJsonValue(response, "text").empty()) {
    EnterCriticalSection(&g_msgMutex);
    g_messageQueue.push_back("CMD: SET_LIBRARY_PROFILE: " +
                             ToString(t->request) + "|" + response);
    LeaveCriticalSection(&g_msgMutex);
  }
  delete t;
  return 0;
}

void RefreshLibraryUI() {
  if (!g_libraryList)
    return;
  CreateThread(NULL, 0, LibraryListThread, NULL, 0, NULL);
  size_t index = g_libraryList->getIndexSelected();
  if (index >= g_libraryStorageIds.size())
    return;
  StartLibraryHistory(g_libraryList->getItemNameAt(index).asUTF8(),
                      g_libraryStorageIds[index]);
}

void AddLibraryFact(MyGUI::Widget *client, int i) {
  float left = i % 2 ? 0.66f : 0.32f;
  float top = 0.075f + (i / 2) * 0.045f;
  float valueWidth = i == LIBRARY_FACT_COUNT - 1 ? 0.57f : 0.23f;
  MyGUI::TextBox *label = client->createWidgetReal<MyGUI::TextBox>(
      "Kenshi_TextboxStandardText", left, top, 0.09f, 0.045f,
      MyGUI::Align::Left | MyGUI::Align::Top,
      "SentientSands_LibFactLabel_" + ToString(i));
  label->setCaption(Utf8ToWide(T(LIBRARY_FACT_LABELS[i])).c_str());
  label->setTextAlign(MyGUI::Align::Left | MyGUI::Align::VCenter);
  label->setTextColour(MyGUI::Colour(0.7f, 0.7f, 0.7f));

  g_libraryFacts[i] = client->createWidgetReal<MyGUI::TextBox>(
      "Kenshi_TextboxStandardText", left + 0.09f, top, valueWidth, 0.045f,
      MyGUI::Align::Left | MyGUI::Align::Top,
      "SentientSands_LibFact_" + ToString(i));
  g_libraryFacts[i]->setTextAlign(MyGUI::Align::Left | MyGUI::Align::VCenter);
}

void CreateLibraryUI() {
  MyGUI::Gui *gui = MyGUI::Gui::getInstancePtr();
  if (!gui)
    return;
  if (g_libraryWindow)
    CloseLibraryUI();

  g_libraryWindow = gui->createWidgetReal<MyGUI::Window>(
      "Kenshi_WindowCX", 0.15f, 0.1f, 0.7f, 0.8f, MyGUI::Align::Center, "Popup",
      "SentientSands_LibraryWindow");
  g_libraryWindow->setCaption(
      Utf8ToWide(T("AI Dialogue Library & Logs")).c_str());
  g_libraryWindow->eventWindowButtonPressed +=
      MyGUI::newDelegate(OnLibraryWindowButtonPressed);

  MyGUI::Widget *client = g_libraryWindow->getClientWidget();

  g_libraryLatestBtn = client->createWidgetReal<MyGUI::Button>(
      "Kenshi_Button1", 0.02f, 0.015f, 0.09f, 0.05f, MyGUI::Align::Left,
      "SentientSands_LibLatestBtn");
  g_libraryLatestBtn->setCaption(Utf8ToWide(T("Latest")).c_str());
  g_libraryLatestBtn->eventMouseButtonClick +=
      MyGUI::newDelegate(OnLibrarySortLatest);

  g_libraryAZBtn = client->createWidgetReal<MyGUI::Button>(
      "Kenshi_Button1", 0.115f, 0.015f, 0.08f, 0.05f, MyGUI::Align::Left,
      "SentientSands_LibAZBtn");
  g_libraryAZBtn->setCaption(Utf8ToWide(T("A-Z")).c_str());
  g_libraryAZBtn->eventMouseButtonClick += MyGUI::newDelegate(OnLibrarySortAZ);

  g_libraryFavBtn = client->createWidgetReal<MyGUI::Button>(
      "Kenshi_Button1", 0.20f, 0.015f, 0.1f, 0.05f, MyGUI::Align::Left,
      "SentientSands_LibFavBtn");
  g_libraryFavBtn->setCaption(Utf8ToWide(T("Fav Toggle")).c_str());
  g_libraryFavBtn->eventMouseButtonClick +=
      MyGUI::newDelegate(OnLibraryFavoriteClick);

  MyGUI::TextBox *searchLabel = client->createWidgetReal<MyGUI::TextBox>(
      "Kenshi_TextboxStandardText", 0.02f, 0.075f, 0.08f, 0.05f,
      MyGUI::Align::Left | MyGUI::Align::Top, "SentientSands_LibSearchLabel");
  searchLabel->setCaption(Utf8ToWide(T("Search")).c_str());
  searchLabel->setTextAlign(MyGUI::Align::Left | MyGUI::Align::VCenter);

  g_librarySearch = client->createWidgetReal<MyGUI::EditBox>(
      "Kenshi_EditBox", 0.10f, 0.075f, 0.20f, 0.05f,
      MyGUI::Align::Left | MyGUI::Align::Top, "SentientSands_LibSearch");
  g_librarySearch->setEditMultiLine(false);
  g_librarySearch->setEditWordWrap(false);
  g_librarySearch->setVisibleVScroll(false);
  g_librarySearch->setTextAlign(MyGUI::Align::Default);
  g_librarySearch->setFontHeight(18);
  g_librarySearch->eventEditTextChange +=
      MyGUI::newDelegate(OnLibrarySearchChange);

  g_libraryList = client->createWidgetReal<MyGUI::ListBox>(
      "Kenshi_ListBox", 0.02f, 0.135f, 0.28f, 0.845f,
      MyGUI::Align::Left | MyGUI::Align::VStretch, "SentientSands_LibraryList");
  g_libraryList->eventListSelectAccept +=
      MyGUI::newDelegate(OnLibraryNPCSelect);
  g_libraryList->eventListChangePosition +=
      MyGUI::newDelegate(OnLibraryNPCSelect);

  g_libraryName = client->createWidgetReal<MyGUI::TextBox>(
      "Kenshi_TextboxStandardText", 0.32f, 0.015f, 0.44f, 0.05f,
      MyGUI::Align::Left | MyGUI::Align::Top, "SentientSands_LibName");
  g_libraryName->setTextAlign(MyGUI::Align::Left | MyGUI::Align::VCenter);
  g_libraryName->setTextColour(MyGUI::Colour(1.0f, 0.9f, 0.5f));

  g_libraryBioBtn = client->createWidgetReal<MyGUI::Button>(
      "Kenshi_Button1", 0.775f, 0.015f, 0.11f, 0.05f, MyGUI::Align::Left,
      "SentientSands_LibBioBtn");
  g_libraryBioBtn->setCaption(Utf8ToWide(T("Generate Bio")).c_str());
  g_libraryBioBtn->eventMouseButtonClick +=
      MyGUI::newDelegate(OnLibraryBioClick);

  MyGUI::Button *editBioBtn = client->createWidgetReal<MyGUI::Button>(
      "Kenshi_Button1", 0.89f, 0.015f, 0.09f, 0.05f, MyGUI::Align::Left,
      "SentientSands_LibEditBioBtn");
  editBioBtn->setCaption(Utf8ToWide(T("Edit Bio")).c_str());
  editBioBtn->eventMouseButtonClick +=
      MyGUI::newDelegate(OnLibraryEditBioClick);

  for (int i = 0; i < LIBRARY_FACT_COUNT; i++)
    AddLibraryFact(client, i);

  g_libraryText = client->createWidgetReal<MyGUI::EditBox>(
      "Kenshi_EditBox", 0.32f, 0.31f, 0.66f, 0.67f, MyGUI::Align::Default,
      "SentientSands_LibraryText");
  g_libraryText->setEditMultiLine(true);
  g_libraryText->setEditWordWrap(true);
  g_libraryText->setEditReadOnly(true);
  g_libraryText->setVisibleVScroll(true);
  // The default cap of 2048 characters would cut the newest lines of the log
  g_libraryText->setMaxTextLength(262144);
  g_libraryText->setTextAlign(MyGUI::Align::Left | MyGUI::Align::Top);
  g_libraryText->setFontHeight(18);
  SetLibraryText(T("Select an NPC from the list to view their profile."));

  CreateThread(NULL, 0, LibraryListThread, NULL, 0, NULL);
}

} // namespace UI
} // namespace SentientSands
