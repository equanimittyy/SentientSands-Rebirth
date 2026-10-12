#pragma once
#include "ChatUIGlobals.h"

class Character;
class hand;

namespace SentientSands {
namespace UI {

extern MyGUI::Window *g_chatWindow;
extern MyGUI::EditBox *g_chatInput;
extern MyGUI::Button *g_chatModeBtns[3];
extern MyGUI::TextBox *g_chatLabel;
extern std::string g_chatTargetHandleStr;
extern std::string g_chatTargetNameStr;
extern size_t g_lastChatModeIndex;

void CreateChatUI(Character *npc);
void CloseChatUI();
// False when the line waits for an offer or for the reply to an action line
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
void OnModeButtonClick(MyGUI::Widget *sender);
void UpdateModeButtons();
void OnRadiantClick(MyGUI::Widget *sender);
void OnChatWindowButtonPressed(MyGUI::Window *sender, const std::string &name);

} // namespace UI
} // namespace SentientSands
