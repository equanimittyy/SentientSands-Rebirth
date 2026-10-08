#pragma once
#include "ChatUIGlobals.h"

namespace SentientSands {
namespace UI {

extern MyGUI::Window *g_libraryWindow;
extern MyGUI::ListBox *g_libraryList;
extern MyGUI::EditBox *g_libraryText;
extern std::vector<std::string> g_libraryStorageIds;

void CreateLibraryUI();
void CloseLibraryUI();
void RefreshLibraryUI();
void PopulateLibraryUI(const std::string &data);
void SetLibraryText(const std::string &text);
void SetLibraryProfile(const std::string &data);
void OpenBioEditor(const std::string &data, const std::string &failureKey);
void FinishKeptBio(const std::string &data);
MyGUI::TextBox *AddBioLine(MyGUI::Widget *client, const std::string &text,
                           float top, const std::string &name);
MyGUI::EditBox *AddBioEditBox(MyGUI::Widget *client, float top, float height,
                              const std::string &name);

void OnLibraryNPCSelect(MyGUI::ListBox *sender, size_t index);
void OnLibraryWindowButtonPressed(MyGUI::Window *sender,
                                  const std::string &name);
DWORD WINAPI LibraryListThread(LPVOID lpParam);
DWORD WINAPI LibraryHistoryThread(LPVOID lpParam);

} // namespace UI
} // namespace SentientSands
