# Kenshi gotchas

This page records the KenshiLib calls and the plugin patterns that broke the plugin, in the game or in the build, and what the plugin does instead. Its sister page, [kenshi_internals.md](kenshi_internals.md), records how the game objects behave and the methods that work in the game. Read both before you change plugin code that calls the game.

Add a gotcha when a call or a pattern crashes the game, gives wrong data, or breaks the build. Give the failure, how it showed, and the fix. When an in-game test shows that the fix works, record the method in [kenshi_internals.md](kenshi_internals.md). [Crash dumps](kenshi_internals.md#crash-dumps) shows how to find the plugin call that crashed the game.

## Game objects

- A C-style cast from `RootObject *` to a subclass, such as `TownBase *`, checks nothing. A virtual function of the subclass, called on an object of another class, runs the function in the same vtable slot of that class. The game then crashes inside its own code, far from the plugin line. Take the objects from a list that holds only the class of the cast.
- `GameWorld::getObjectsWithinSphere` with the `itemType` `TOWN` gives items, not towns. `TownBase::isTown` on such an item ran the function in vtable slot `0x268` of `Item` (`Item::serialiseInInventory`) with wrong arguments, and the game crashed at each chat when it read address `0x9`. `ChangedTowns` in `plugin/game/Context.cpp` now reads the town list of the game (`TownList::getAllTowns`) through the KenshiLib global `shou`.

## KenshiLib headers

- `AI/AIPackage.h` and `AI/Blackboard.h` define the same enum, `BlackboardSignalFunctions`, so one source file cannot include both (error C2011). The plugin reads the AI package only by name, through `Blackboard::getCurrentAIPackageName` (`LogNpcRole` in `plugin/game/Context.cpp`).
- `Weather.h` and `PhysicsCollection.h`, which `Building/Building.h` includes, define the same class, `WeatherRegion` (error C2011). `plugin/game/Context.cpp` renames the copy of `Weather.h` with a macro while it includes that header.

## Threads

- The hooks of knockouts, deaths, and prisons run off the game thread (see [kenshi_internals.md](kenshi_internals.md#deaths-and-captures)). A check against the thread that started the plugin (`g_mainThreadId`) in such a hook skips every call. The hooks guard their shared data with `g_eventMutex` instead.
- A new thread must follow the threading rule of [architecture.md](architecture.md#threading): it does not change game objects or MyGUI widgets.

## MyGUI

- On the `Popup` layer, a click raises a window over its open drop-down list, so the list shows under the window. The chat window is on the `Window` layer because of its speaker list (`CreateChatUI` in `plugin/ui/ChatWindow.cpp`). The Deeds window stays on the `Popup` layer and uses a button that goes to the next kind on each click.
