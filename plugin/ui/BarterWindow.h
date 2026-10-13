#pragma once
#include "Widgets.h"

namespace SentientSands {
namespace UI {

extern MyGUI::Window *g_barterWindow;

void ShowBarterUI(const std::string &npcName, unsigned int npcKey,
                  const std::string &thread);
bool ShowBarterOffer(unsigned int npcKey, unsigned int speakerKey,
                     const std::vector<std::string> &deal);
void BarterOfferGone();
void SetBarterTurn(const std::string &data);

} // namespace UI
} // namespace SentientSands
