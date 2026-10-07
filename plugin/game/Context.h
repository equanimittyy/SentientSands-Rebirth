#pragma once
#include <string>
#include <vector>

class Character;
class Item;

void GetAllCharacterItems(Character *npc, std::vector<Item *> &outItems);
std::string GetDetailedContext(Character *npc, const std::string &type = "npc");
std::string GetIdentityFaction(Character *npc);
std::string GetNpcId(Character *npc);
void GetCurrentSquad(std::vector<Character *> &members);
void GetRadiantParticipants(Character *selected,
                            std::vector<Character *> &participants);
void LogFactionList();
void LogNpcRole(Character *npc);
void ProbeBounty(Character *npc, const std::string &payload);
std::string EventParty(Character *npc);
std::string RoleJson(Character *npc);
std::string ProfileJson(Character *npc);
std::string GetVisibleEquipment(Character *npc);
std::string TakeGameEvents();
std::string ChangedTowns();
std::string GameReport();
