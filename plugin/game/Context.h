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
void LogFactionList();
void LogNpcRole(Character *npc);
void RecordProbeHit(Character *target, Character *attacker);
void LogDeathProbe(const std::string &kind, Character *npc);
std::string RoleJson(Character *npc);
std::string TakeGameEvents();
std::string GameReport();
