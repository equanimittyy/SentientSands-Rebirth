#pragma once
#include "ChatUIGlobals.h"

namespace SentientSands {
namespace UI {

void CreateJournalUI();
void CloseJournalUI();
void PopulateJournalUI(const std::string &data);
void SetJournalEntry(const std::string &data);
void FinishJournalAdd(const std::string &data);
void FinishJournalSave(const std::string &data);
void FinishJournalDelete(const std::string &data);

} // namespace UI
} // namespace SentientSands
