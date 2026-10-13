#include "WelcomeWindow.h"
#include "../core/Comm.h"
#include "../core/Globals.h"
#include "../core/Utils.h"

#include <mygui/MyGUI_Button.h>
#include <mygui/MyGUI_Delegate.h>
#include <mygui/MyGUI_Gui.h>
#include <mygui/MyGUI_TextBox.h>
#include <mygui/MyGUI_Window.h>

namespace SentientSands {
namespace UI {

static MyGUI::Window *g_welcomeWindow = nullptr;

static void CloseWelcomeUI() { DestroyWindow(g_welcomeWindow); }

static CloseAction g_welcomeClose = {CloseWelcomeUI};

static void OnWelcomeToggleClick(MyGUI::Widget *sender) {
  g_enableWelcome = !g_enableWelcome;
  ((MyGUI::Button *)sender)
      ->setCaption(PlainText(T(g_enableWelcome ? "Show on Startup: [ON]"
                                               : "Show on Startup: [OFF]")));
  AsyncPostToPython(L"/settings", std::string("{\"enable_welcome\": ") +
                                      (g_enableWelcome ? "true" : "false") +
                                      "}");
}

DWORD WINAPI WelcomeResponseThread(LPVOID lpParam) {
  Log(LOG_DEBUG, "WELCOME: Fetching initial config...");
  std::string response = PostToPythonWithResponse(L"/settings", "");
  if (response.empty()) {
    Log(LOG_WARN, "WELCOME: Server not responding.");
    return 0;
  }

  QueueMessage("CMD: APPLY_TRANSLATION: " + response);

  return 0;
}

static const struct {
  const char *key;
  float red, green, blue;
} WELCOME_LINES[] = {
    {"Welcome to Sentient Sands Rebirth, an LLM mod for Kenshi", 0.85f, 0.85f,
     0.85f},
    {"Special thanks to Harvicus, the original author of Sentient Sands,", 1.0f,
     0.9f, 0.5f},
    {"and to BFrizzleFoShizzle and the RE_Kenshi contributors", 1.0f, 0.9f,
     0.5f},
    {"See the Web app for a tutorial on SSR!", 1.0f, 0.6f, 0.6f},
    {"It opens on start: Alt-Tab to it, or click Open Web App (F8)", 1.0f, 0.6f,
     0.6f},
};

static void OnWelcomeCloseClick(MyGUI::Widget *sender) { CloseWelcomeUI(); }

void CreateWelcomeUI() {
  CloseWelcomeUI();
  MyGUI::Widget *client = OpenWindow(
      g_welcomeWindow, 0.32f, 0.10f, 0.36f, 0.52f, MyGUI::Align::Center,
      "Popup", "SentientSands_WelcomeWindow",
      T("Welcome to Sentient Sands Rebirth"), g_welcomeClose);
  if (!client)
    return;
  MyGUI::Align topWide = MyGUI::Align::Top | MyGUI::Align::HStretch;

  for (size_t i = 0; i < sizeof(WELCOME_LINES) / sizeof(WELCOME_LINES[0]);
       ++i)
    AddLabel(client, T(WELCOME_LINES[i].key), 0.05f, 0.02f + i * 0.07f, 0.9f,
             0.06f, topWide, "SentientSands_WelcomeL" + ToString((int)i),
             MyGUI::Align::Center)
        ->setTextColour(MyGUI::Colour(WELCOME_LINES[i].red,
                                      WELCOME_LINES[i].green,
                                      WELCOME_LINES[i].blue));

  AddLabel(client,
           Fill(T("Use [ {key} ] to Chat and [ F8 ] to open the SSR HUB"),
                "{key}", g_chatHotkeyStr),
           0.05f, 0.47f, 0.9f, 0.1f, topWide, "SentientSands_WelcomeKeys",
           MyGUI::Align::Center)
      ->setTextColour(MyGUI::Colour(0.6f, 1.0f, 0.6f));

  AddButton(client,
            T(g_enableWelcome ? "Show on Startup: [ON]"
                              : "Show on Startup: [OFF]"),
            0.05f, 0.61f, 0.9f, 0.12f, topWide, "SentientSands_WelcomeToggle",
            OnWelcomeToggleClick);
  AddButton(client, T("CLOSE"), 0.29f, 0.78f, 0.42f, 0.18f,
            MyGUI::Align::Bottom | MyGUI::Align::HCenter,
            "SentientSands_WelcomeSaveBtn", OnWelcomeCloseClick);
}

void RefreshWelcomeUI() {
  if (g_welcomeWindow)
    CreateWelcomeUI();
}

} // namespace UI
} // namespace SentientSands
