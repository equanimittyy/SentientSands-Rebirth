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

MyGUI::Window *g_welcomeWindow = nullptr;

void CloseWelcomeUI() {
  if (g_welcomeWindow) {
    if (MyGUI::Gui::getInstancePtr())
      MyGUI::Gui::getInstancePtr()->destroyWidget(g_welcomeWindow);
    g_welcomeWindow = nullptr;
    g_welcomeCheckbox = nullptr;
  }
}

void OnWelcomeToggleClick(MyGUI::Widget *sender) {
  g_enableWelcome = !g_enableWelcome;
  ((MyGUI::Button *)sender)
      ->setCaption(g_enableWelcome
                       ? Utf8ToWide(T("Show on Startup: [ON]")).c_str()
                       : Utf8ToWide(T("Show on Startup: [OFF]")).c_str());
  AsyncPostToPython(L"/settings", std::string("{\"enable_welcome\": ") +
                                      (g_enableWelcome ? "true" : "false") +
                                      "}");
}

void OnWelcomeWindowButtonPressed(MyGUI::Window *sender,
                                  const std::string &name) {
  if (name == "close")
    CloseWelcomeUI();
}

DWORD WINAPI WelcomeResponseThread(LPVOID lpParam) {
  Log(LOG_DEBUG, "WELCOME: Fetching initial config...");
  std::string response = PostToPythonWithResponse(L"/settings", "");
  if (response.empty()) {
    Log(LOG_WARN, "WELCOME: Server not responding.");
    return 0;
  }

  std::string pipeMsg = "CMD: APPLY_TRANSLATION: " + response;
  EnterCriticalSection(&g_msgMutex);
  g_messageQueue.push_back(pipeMsg);
  LeaveCriticalSection(&g_msgMutex);

  return 0;
}

void CreateWelcomeUI() {
  MyGUI::Gui *gui = MyGUI::Gui::getInstancePtr();
  if (!gui)
    return;
  if (g_welcomeWindow)
    CloseWelcomeUI();

  g_welcomeWindow = gui->createWidgetReal<MyGUI::Window>(
      "Kenshi_WindowCX", 0.32f, 0.10f, 0.36f, 0.52f, MyGUI::Align::Center,
      "Popup", "SentientSands_WelcomeWindow");
  g_welcomeWindow->setCaption(
      Utf8ToWide(T("Welcome to Sentient Sands Rebirth")).c_str());
  g_welcomeWindow->eventWindowButtonPressed +=
      MyGUI::newDelegate(OnWelcomeWindowButtonPressed);

  MyGUI::Widget *client = g_welcomeWindow->getClientWidget();

  float yProg = 0.02f;
  float yDelta = 0.07f;

  MyGUI::TextBox *l1 = client->createWidgetReal<MyGUI::TextBox>(
      "Kenshi_TextboxStandardText", 0.05f, yProg, 0.9f, 0.06f,
      MyGUI::Align::Top | MyGUI::Align::HStretch, "SentientSands_WelcomeL1");
  l1->setCaption(Utf8ToWide(T("Welcome to Sentient Sands Rebirth, an LLM mod "
                              "for Kenshi"))
                     .c_str());
  l1->setTextAlign(MyGUI::Align::Center);
  l1->setTextColour(MyGUI::Colour(0.85f, 0.85f, 0.85f));
  yProg += yDelta;

  MyGUI::TextBox *l3 = client->createWidgetReal<MyGUI::TextBox>(
      "Kenshi_TextboxStandardText", 0.05f, yProg, 0.9f, 0.06f,
      MyGUI::Align::Top | MyGUI::Align::HStretch, "SentientSands_WelcomeL3");
  l3->setCaption(Utf8ToWide(T("Special thanks to Harvicus, the original "
                              "author of Sentient Sands,"))
                     .c_str());
  l3->setTextAlign(MyGUI::Align::Center);
  l3->setTextColour(MyGUI::Colour(1.0f, 0.9f, 0.5f));
  yProg += yDelta;

  MyGUI::TextBox *l4 = client->createWidgetReal<MyGUI::TextBox>(
      "Kenshi_TextboxStandardText", 0.05f, yProg, 0.9f, 0.06f,
      MyGUI::Align::Top | MyGUI::Align::HStretch, "SentientSands_WelcomeL4");
  l4->setCaption(Utf8ToWide(T("and to BFrizzleFoShizzle and the RE_Kenshi "
                              "contributors"))
                     .c_str());
  l4->setTextAlign(MyGUI::Align::Center);
  l4->setTextColour(MyGUI::Colour(1.0f, 0.9f, 0.5f));
  yProg += yDelta;

  MyGUI::TextBox *l5 = client->createWidgetReal<MyGUI::TextBox>(
      "Kenshi_TextboxStandardText", 0.05f, yProg, 0.9f, 0.06f,
      MyGUI::Align::Top | MyGUI::Align::HStretch, "SentientSands_WelcomeL5");
  l5->setCaption(Utf8ToWide(T("Many original Sentient Sands features are now "
                              "in the SSR web app"))
                     .c_str());
  l5->setTextAlign(MyGUI::Align::Center);
  l5->setTextColour(MyGUI::Colour(0.85f, 0.85f, 0.85f));
  yProg += yDelta;

  MyGUI::TextBox *l6 = client->createWidgetReal<MyGUI::TextBox>(
      "Kenshi_TextboxStandardText", 0.05f, yProg, 0.9f, 0.06f,
      MyGUI::Align::Top | MyGUI::Align::HStretch, "SentientSands_WelcomeL6");
  l6->setCaption(Utf8ToWide(T("In game: chat with NPCs, the Dialogue Library, "
                              "and deeds"))
                     .c_str());
  l6->setTextAlign(MyGUI::Align::Center);
  l6->setTextColour(MyGUI::Colour(0.85f, 0.85f, 0.85f));
  yProg += yDelta;

  MyGUI::TextBox *l7 = client->createWidgetReal<MyGUI::TextBox>(
      "Kenshi_TextboxStandardText", 0.05f, yProg, 0.9f, 0.06f,
      MyGUI::Align::Top | MyGUI::Align::HStretch, "SentientSands_WelcomeL7");
  l7->setCaption(Utf8ToWide(T("Web app: settings, LLM models, prompts, "
                              "campaigns, and the editor"))
                     .c_str());
  l7->setTextAlign(MyGUI::Align::Center);
  l7->setTextColour(MyGUI::Colour(0.85f, 0.85f, 0.85f));

  MyGUI::TextBox *instructions = client->createWidgetReal<MyGUI::TextBox>(
      "Kenshi_TextboxStandardText", 0.05f, 0.47f, 0.9f, 0.1f,
      MyGUI::Align::Top | MyGUI::Align::HStretch, "SentientSands_WelcomeKeys");
  std::string keysText =
      T("Use [ {key} ] to Chat and [ F8 ] to open the SSR HUB");
  size_t keySlot = keysText.find("{key}");
  if (keySlot != std::string::npos)
    keysText.replace(keySlot, 5, g_chatHotkeyStr);
  instructions->setCaption(Utf8ToWide(keysText).c_str());
  instructions->setTextAlign(MyGUI::Align::Center);
  instructions->setTextColour(MyGUI::Colour(0.6f, 1.0f, 0.6f));

  g_welcomeCheckbox = client->createWidgetReal<MyGUI::Button>(
      "Kenshi_Button1", 0.05f, 0.61f, 0.9f, 0.12f,
      MyGUI::Align::Top | MyGUI::Align::HStretch,
      "SentientSands_WelcomeToggle");
  g_welcomeCheckbox->setCaption(Utf8ToWide(g_enableWelcome
                                               ? T("Show on Startup: [ON]")
                                               : T("Show on Startup: [OFF]"))
                                    .c_str());
  g_welcomeCheckbox->eventMouseButtonClick +=
      MyGUI::newDelegate(OnWelcomeToggleClick);

  MyGUI::Button *saveBtn = client->createWidgetReal<MyGUI::Button>(
      "Kenshi_Button1", 0.29f, 0.78f, 0.42f, 0.18f,
      MyGUI::Align::Bottom | MyGUI::Align::HCenter,
      "SentientSands_WelcomeSaveBtn");
  saveBtn->setCaption(Utf8ToWide(T("CLOSE")).c_str());
  saveBtn->eventMouseButtonClick += MyGUI::newDelegate(OnWelcomeSaveClick);
}

void RefreshWelcomeUI() {
  if (g_welcomeWindow)
    CreateWelcomeUI();
}

void OnWelcomeSaveClick(MyGUI::Widget *sender) { CloseWelcomeUI(); }

} // namespace UI
} // namespace SentientSands
