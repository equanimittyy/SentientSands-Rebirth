#pragma once
#include <string>
#include <windows.h>

class Character;
class GameWorld;

void PerformLeaveSquad(Character *npc, GameWorld *world,
                       const std::string &originFaction);
void ExecuteQueuedActions(GameWorld *thisptr, int &inventoryTimer);
void StartTreatment(Character *medic, Character *patient, bool &firstAid,
                    bool &repair);
void WatchReleases(GameWorld *world);
void WatchFights(GameWorld *world);
