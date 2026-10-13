#pragma once
#include "Widgets.h"

class Character;
class GameWorld;

namespace SentientSands {
namespace UI {

void WatchHires(GameWorld *world);
void SetHireTerms(const std::string &data);
void ExpireHire(Character *npc);

} // namespace UI
} // namespace SentientSands
