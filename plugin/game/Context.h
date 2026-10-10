#pragma once
#include <string>
#include <vector>

class Character;
class Item;
class hand;

void GetAllCharacterItems(Character *npc, std::vector<Item *> &outItems);
void GetShopItems(Character *npc, std::vector<Item *> &out);
std::string ItemLabel(Item *item);
std::string GetDetailedContext(Character *npc, const std::string &type = "npc");
std::string GetIdentityFaction(Character *npc);
std::string GetNpcId(Character *npc);
unsigned int HandleKey(Character *npc);
Character *KeyedCharacter(unsigned int key);
void GetCurrentSquad(std::vector<Character *> &members);
void GetRadiantParticipants(Character *selected,
                            std::vector<Character *> &participants);
void GetRadiantNpcs(Character *center, std::vector<Character *> &npcs);
void LogFactionList();
void LogNpcRole(Character *npc);
void LogHandleProbe(const std::string &call, Character *npc, const hand &before,
                    bool always);
void RunProbe(Character *npc, Character *speaker, const std::string &payload);
std::string EventParty(Character *npc);
std::string RoleJson(Character *npc);
std::string ProfileJson(Character *npc);
std::string GetVisibleEquipment(Character *npc);
std::string TakeGameEvents();
std::string ChangedTowns();
std::string GameReport();
std::string GameTimeFields();
