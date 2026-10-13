#pragma once
#include "Widgets.h"

namespace SentientSands {
namespace UI {

extern MyGUI::Window *g_libraryWindow;

void CreateLibraryUI();
void RefreshLibraryUI();
void PopulateLibraryUI(const std::string &data);
void SetLibraryProfile(const std::string &data);
void OpenBioEditor(const std::string &data, const std::string &failureKey);
void FinishKeptBio(const std::string &data);

} // namespace UI
} // namespace SentientSands
