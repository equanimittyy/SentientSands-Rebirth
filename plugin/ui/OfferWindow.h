#pragma once
#include "Widgets.h"

class Character;

namespace SentientSands {
namespace UI {

extern MyGUI::Window *g_offerWindow;

// "<kind> <holder> <count> [<name>]", the shape of the CHECK and DEAL lines.
// The holder is npc, player for the speaker, or the key of a squad mate
struct DealLine {
  std::string kind;
  std::string holder;
  int count;
  std::string name;
};
DealLine ParseDealLine(const std::string &text);

// Accept restocks an item that the NPC lost as a copy of what this saw
void NoteNpcItems(Character *npc);
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
