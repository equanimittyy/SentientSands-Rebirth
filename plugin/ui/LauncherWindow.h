#pragma once
#include "Widgets.h"

namespace SentientSands {
namespace UI {

extern MyGUI::Window *g_launcherWindow;

void CreateLauncherUI();
void CloseLauncherUI();
void RefreshLauncherUI();
void FinishCull(const std::string &data);

} // namespace UI
} // namespace SentientSands
