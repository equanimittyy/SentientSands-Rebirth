#pragma once
#include "Widgets.h"

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
// The renewal popup of a hire looks like an offer
MyGUI::Widget *OpenPopup(MyGUI::Window *&window, float top, float height,
                         const std::string &name, const std::string &npcName,
                         CloseAction &onClose);
MyGUI::Button *AddPopupButton(MyGUI::Widget *client, const std::string &key,
                              float left, const std::string &name,
                              ClickHandler onClick);

} // namespace UI
} // namespace SentientSands
