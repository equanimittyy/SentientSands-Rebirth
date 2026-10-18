#pragma once
#include <string>

class Character;

void LogFactionList();
void LogNpcRole(Character *npc);
std::string OrdersLine(Character *npc);
void RunProbe(Character *npc, Character *speaker, const std::string &payload);
