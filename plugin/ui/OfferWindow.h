#pragma once
#include "ChatUIGlobals.h"

class Character;

namespace SentientSands {
namespace UI {

extern MyGUI::Window *g_offerWindow;

void ShowOfferUI(const std::string &data);
void DropOfferUI();
void WatchOffer();
void AcceptOffer();
std::string DeclineOffer();
bool OfferHeldFor(unsigned int npcKey);
int MoneyOf(Character *c);
void NotifyText(const std::string &text);
std::string Fill(std::string text, const std::string &slot,
                 const std::string &value);

} // namespace UI
} // namespace SentientSands
