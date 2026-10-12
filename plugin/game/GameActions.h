#pragma once
#include <kenshi/Enums.h>
#include <string>
#include <windows.h>

class Character;
class GameWorld;

void ExecuteQueuedActions(GameWorld *thisptr);
// robotOrder lets /firstaid try another order, because FIRST_AID_ROBOT made a
// medic with a repair kit do nothing for a Skeleton
std::string StartTreatment(Character *medic, Character *patient,
                           bool &firstAid, bool &repair,
                           TaskType robotOrder = FIRST_AID_ROBOT);
void WatchActions(GameWorld *world);
