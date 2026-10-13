#pragma once
#include "Widgets.h"

class Character;
class hand;

namespace SentientSands {
namespace UI {

extern MyGUI::Window *g_chatWindow;
extern MyGUI::EditBox *g_chatInput;
extern MyGUI::Button *g_chatModeBtns[3];
extern std::string g_chatTargetHandleStr;
extern std::string g_chatTargetNameStr;
extern size_t g_lastChatModeIndex;

void CreateChatUI(Character *npc);
void CloseChatUI();
// False when the line goes nowhere
bool SendChatLine(const std::string &npcName, const std::string &handleStr,
                  Character *speaker, const std::string &text,
                  const std::string &mode, const std::string &offerAnswer,
                  const std::string &barterJson = "");
void SetOfferPending(const std::string &npcName);
std::string CurrentChatMode();
void SetChatHistory(const std::string &data);

DWORD WINAPI ChatResponseThread(LPVOID lpParam);
void OnChatInputChange(MyGUI::EditBox *sender);
void OnChatInputAccept(MyGUI::EditBox *sender);
void OnChatSendClick(MyGUI::Widget *sender);
void OnChatCancelClick(MyGUI::Widget *sender);
void OnChatSpeakerClick(MyGUI::Widget *sender);
void SelectChatSpeaker(const hand &member);
void ForgetChatTarget();
void OnModeButtonClick(MyGUI::Widget *sender);
void UpdateModeButtons();
void OnRadiantClick(MyGUI::Widget *sender);

} // namespace UI
} // namespace SentientSands
