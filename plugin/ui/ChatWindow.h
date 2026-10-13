#pragma once
#include "Widgets.h"

class Character;
class hand;

namespace SentientSands {
namespace UI {

extern MyGUI::Window *g_chatWindow;

void CreateChatUI(Character *npc);
// False when the line goes nowhere
bool SendChatLine(const std::string &npcName, unsigned int targetKey,
                  Character *speaker, const std::string &text,
                  const std::string &mode, const std::string &offerAnswer,
                  const std::string &barterJson = "");
void SetOfferPending(const std::string &npcName);
std::string CurrentChatMode();
void SetChatHistory(const std::string &data);

void SelectChatSpeaker(const hand &member);
void ForgetChatTarget();

} // namespace UI
} // namespace SentientSands
