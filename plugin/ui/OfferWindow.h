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

} // namespace UI
} // namespace SentientSands
