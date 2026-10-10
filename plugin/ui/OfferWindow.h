#pragma once
#include "ChatUIGlobals.h"

namespace SentientSands {
namespace UI {

extern MyGUI::Window *g_offerWindow;

void ShowOfferUI(const std::string &data);
void DropOfferUI();
void WatchOffer();

} // namespace UI
} // namespace SentientSands
