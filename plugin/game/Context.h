#pragma once
#include <string>
#include <vector>

class Character;
class Item;

void GetAllCharacterItems(Character *npc, std::vector<Item *> &outItems);
std::string GetDetailedContext(Character *npc, const std::string &type = "npc");
std::string GetIdentityFaction(Character *npc);
std::string GetStorageIDFor(Character *npc, const std::string &name,
                            const std::string &factionName);
void LogNpcIdentity(Character *npc);
void LogNpcBiome(Character *npc);
void LogFactionList();
void LogCurrentSquad();
