#pragma once
#include <string>
#include <vector>

class Character;
class Item;

void GetAllCharacterItems(Character *npc, std::vector<Item *> &outItems);
std::string GetDetailedContext(Character *npc, const std::string &type = "npc");
std::string GetIdentityFaction(Character *npc);
std::string GetNpcId(Character *npc);
// Game thread only, because the game thread writes the generic name lists
bool IsGenericName(Character *npc, const std::string &name);
void GetCurrentSquad(std::vector<Character *> &members);
void LogNpcZone(Character *npc);
void LogFactionList();
