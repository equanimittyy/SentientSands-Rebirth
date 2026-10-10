#pragma once
#include "ChatUIGlobals.h"

class Character;

namespace SentientSands {
namespace UI {

extern MyGUI::Window *g_chatWindow;
extern MyGUI::EditBox *g_chatInput;
extern MyGUI::Button *g_chatModeBtns[3];
extern MyGUI::TextBox *g_chatLabel;
extern std::string g_chatTargetHandleStr;
extern std::string g_chatTargetNameStr;
extern size_t g_lastChatModeIndex;

void CreateChatUI(const std::string &npcName, const std::string &handleStr);
void CloseChatUI();
void SendChatLine(const std::string &npcName, const std::string &handleStr,
                  Character *speaker, const std::string &text,
                  const std::string &mode, const std::string &offerAnswer);
void SetOfferPending(const std::string &npcName);
std::string CurrentChatMode();

DWORD WINAPI ChatResponseThread(LPVOID lpParam);
void OnChatInputChange(MyGUI::EditBox *sender);
void OnChatInputAccept(MyGUI::EditBox *sender);
void OnChatSendClick(MyGUI::Widget *sender);
void OnChatCancelClick(MyGUI::Widget *sender);
void OnChatSpeakerClick(MyGUI::Widget *sender);
void OnModeButtonClick(MyGUI::Widget *sender);
void UpdateModeButtons();
void OnRadiantClick(MyGUI::Widget *sender);
void OnChatWindowButtonPressed(MyGUI::Window *sender, const std::string &name);

} // namespace UI
} // namespace SentientSands
