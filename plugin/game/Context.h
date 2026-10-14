#pragma once
#include <string>
#include <vector>

class Blackboard;
class Building;
class Character;
class Faction;
class GameData;
class Inventory;
class Item;
class TownBase;
class hand;

void GetAllCharacterItems(Character *npc, std::vector<Item *> &outItems);
void GetShopItems(Character *npc, std::vector<Item *> &out);
bool InventoryHasRoom(Inventory *inv, GameData *data, int count);
bool HasRoomFor(Character *c, GameData *data, int count);
void SectionItems(Inventory *inv, std::vector<Item *> &out);
Building *BuildingOf(Character *npc);
std::string GetHealthStatus(Character *npc);
std::string ItemLabel(Item *item);
std::string ItemsJson(const std::vector<Item *> &items);
std::string GetDetailedContext(Character *npc, const std::string &type = "npc");
void TreatmentNeeds(Character *patient, bool &firstAid, bool &repair);
std::string GetIdentityFaction(Character *npc);
std::string GetNpcId(Character *npc);
unsigned int HandleKey(Character *npc);
Character *KeyedCharacter(unsigned int key);
void RekeyCharacter(Character *npc, const hand &before);
void GetCurrentSquad(std::vector<Character *> &members);
void GetRadiantParticipants(Character *selected,
                            std::vector<Character *> &participants);
void GetRadiantNpcs(Character *center, std::vector<Character *> &npcs);
std::string EventParty(Character *npc);
std::string PartyFields(Character *c);
Faction *CharacterFaction(Character *npc);
std::string FactionName(Faction *faction);
std::string GetVisibleEquipment(Character *npc);
void QueueGameEvent(const std::string &kind, const std::string &fields,
                    unsigned long long attack = 0);
bool AttackWaits(unsigned long long attack);
bool ReportDue();
std::string TakeGameEvents();
std::string ChangedTowns();
std::string NamedTowns(const std::string &line, Character *from);
TownBase *FindTown(const std::string &name);
Character *FirstPlayerCharacter();
Blackboard *BoardOf(Character *c);
// The Bodyguard package, which the game's hire dialogues give with hours
GameData *BodyguardPackage();
int MoneyOf(Character *c);
bool InPlayerFaction(Character *c);
std::string GameReport();
std::string GameTimeFields();
