#pragma once
#include "Widgets.h"

namespace SentientSands {
namespace UI {

void CreateEventsUI();
void PopulateEventsUI(const std::string &data);
void SetEventContent(const std::string &data);
void OpenRumorEditor(const std::string &data, const std::string &failureKey);
void FinishEventChange(const std::string &data, const std::string &failureKey);

} // namespace UI
} // namespace SentientSands
