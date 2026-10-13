#pragma once
#include "Widgets.h"

namespace SentientSands {
namespace UI {

extern MyGUI::Window *g_welcomeWindow;

void CreateWelcomeUI();
void CloseWelcomeUI();
void RefreshWelcomeUI();
DWORD WINAPI WelcomeResponseThread(LPVOID lpParam);

} // namespace UI
} // namespace SentientSands
