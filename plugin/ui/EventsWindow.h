#pragma once
#include "Widgets.h"

namespace SentientSands {
namespace UI {

extern MyGUI::Window *g_eventsWindow;
extern MyGUI::ListBox *g_eventsList;
extern MyGUI::ListBox *g_eventsText;
extern std::vector<std::string> g_eventsStorageIds;

void CreateEventsUI();
void CloseEventsUI();
void PopulateEventsUI(const std::string &data);
void SetEventContent(const std::string &data);
void OpenRumorEditor(const std::string &data, const std::string &failureKey);
void FinishEventChange(const std::string &data, const std::string &failureKey);

void OnEventsSelect(MyGUI::ListBox *sender, size_t index);

} // namespace UI
} // namespace SentientSands
