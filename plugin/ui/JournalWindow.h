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
void StartJournalRequest(const wchar_t *endpoint, const std::string &json,
                         const std::string &command, const std::string &tag);
bool SplitJournalReply(const std::string &data, std::string &tag,
                       std::string &reply);
MyGUI::Button *AddJournalButton(MyGUI::Widget *client, const char *captionKey,
                                float left, float top, float width,
                                void (*onClick)(MyGUI::Widget *),
                                const std::string &name);
MyGUI::TextBox *AddJournalLine(MyGUI::Widget *client, float left, float top,
                               float width, const std::string &name);
MyGUI::EditBox *AddJournalLineBox(MyGUI::Widget *client, float left,
                                  float top, float width,
                                  const std::string &name);

} // namespace UI
} // namespace SentientSands
