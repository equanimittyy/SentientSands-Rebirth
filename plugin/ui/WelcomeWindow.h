#pragma once
#include "Widgets.h"

namespace SentientSands {
namespace UI {

void CreateWelcomeUI();
void RefreshWelcomeUI();
DWORD WINAPI WelcomeResponseThread(LPVOID lpParam);

} // namespace UI
} // namespace SentientSands
