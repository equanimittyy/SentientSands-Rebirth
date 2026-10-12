#include "HelpWindow.h"
#include "../core/Globals.h"
#include "../core/Utils.h"
#include <mygui/MyGUI_Button.h>
#include <mygui/MyGUI_Delegate.h>
#include <mygui/MyGUI_EditBox.h>
#include <mygui/MyGUI_Gui.h>
#include <mygui/MyGUI_TextBox.h>
#include <mygui/MyGUI_TextIterator.h>
#include <mygui/MyGUI_Window.h>

namespace SentientSands {
namespace UI {

struct HelpLine {
  const char *label;
  const char *text;
};

static const int HELP_LINE_MAX = 12;

struct HelpTopic {
  const char *title;
  HelpLine lines[HELP_LINE_MAX];
};

// The Tutorial tab of the web app has a card with each title, and
// server/tests/test_tutorial.py fails when one is missing
static const HelpTopic HELP_TOPICS[] = {
    {"Start the game",
     {{NULL, "Sentient Sands Rebirth (SSR) lets you talk to the NPCs of "
             "Kenshi. An AI model writes what they say."},
      {NULL, "When Kenshi starts, SSR starts its server and opens the web app "
             "in your browser. Connect a model on the Models tab of the web "
             "app before you talk to an NPC. The Tutorial tab of the web app "
             "shows how."},
      {"SSR HUB", "Press [ F8 ] to open the SSR HUB again."},
      {"Open Web App",
       "If the web app does not open, press Open Web App in the SSR HUB."},
      {"Restart Server", "If the web app says that the server is not running, "
                         "press Restart Server in the SSR HUB."},
      {"Chat", "Select an NPC and press [ {key} ] to talk to it."},
      {"Help", "Choose a topic on the left, or press Next to read the topics "
               "in order."}}},
    {"Talk to an NPC",
     {{NULL, "Select an NPC and press the chat key, [ {key} ]. The chat goes "
             "to the last NPC that you selected, even when you select a squad "
             "member after it. You can change the chat key on the Settings tab "
             "of the web app."},
      {"Target", "To talk to one of your characters within the Talk range of "
                 "your squad, press the button on the right, with the name of "
                 "the NPC, until it shows that character."},
      {"Speaker", "To speak as another squad member, press the button on the "
                  "left, with the name of the speaker, until it shows that "
                  "member."},
      {"Whisper", "Only the NPC hears it."},
      {"Talk", "The NPCs within the Talk range hear it."},
      {"Yell", "The NPCs within the Yell range hear it. Up to 3 of them can "
               "answer, one after another."},
      {"Send", "Type your line and press Enter. The NPC replies in a speech "
               "bubble."},
      {NULL, "Above the input, the chat window shows the type of the current "
             "conversation, such as Chat or Barter, with its speakers and its "
             "place, and below them its lines."},
      {"Cancel", "Closes the chat window. Enter on an empty line also closes "
                 "it."}}},
    {"Make a deal",
     {{NULL, "Start a line with ! to ask the NPC for something that the game "
             "can carry out, such as a trade, a hire, or a release from "
             "prison. For example: !b I want to buy your water. The NPC can "
             "then make an offer."},
      {"! and a space", "SSR picks the kind of deal from your line, for "
                        "example: ! Can you patch me up?"},
      {"!t", "Threaten the NPC, or make a demand."},
      {"!b", "Buy, sell, or swap items, give a gift, or ask for charity."},
      {"!h", "Ask for the treatment of your wounds, or the repair of your "
             "robotic parts, paid or free."},
      {"!l", "Ask for a release from prison or slavery, paid or free."},
      {"!r", "Ask the NPC to join your squad for good."},
      {"!f", "Ask the NPC to come along, or hire it for a while."},
      {"!d", "Tell a hired follower to leave."},
      {"!end", "Ends the deal."},
      {"Offer", "When the NPC makes an offer, a popup opens. Press Accept to "
                "carry out the deal, or press Decline and type your reply. "
                "Answer the offer before you say another line."},
      {NULL, "You can type the full word instead of the letter, for example "
             "!barter. Your next lines without ! stay in the same deal. "
             "Animals and the members of your faction make no deals."}}},
    {"The Barter window",
     {{NULL, "During a barter (!b), the chat window shows a Barter button. It "
             "opens a window in which you build the deal from real items and "
             "cats."},
      {"Left side", "Your cats and the items of one squad member. Press the "
                    "button with the name to show the next squad member near "
                    "the NPC."},
      {"Right side", "The cats and the goods of the NPC: the stock of its "
                     "shop, or else the items that it carries."},
      {"Double-click", "Moves one item between the holdings and the offer of "
                       "a side. Shift and double-click moves the whole "
                       "stack."},
      {"Cats", "Type the cats of each side in its Cats box."},
      {"Estimate", "The line under the boxes shows the profit or the loss of "
                   "the NPC at the full price. The NPC cannot agree to a loss, "
                   "except for charity. A profit does not mean that the NPC "
                   "agrees."},
      {"Send", "Sends the deal on the table with your line, or with \"How "
               "about this deal?\" when the line is blank."},
      {"Accept", "Carries out the deal after the NPC agrees to it."},
      {"Close", "Closes the window, and declines an offer that waits."}}},
    {"Radiant conversations",
     {{NULL, "Each Radiant chat timer (10 minutes of unpaused time by "
             "default), 3 to 5 of your characters who stand together talk. The "
             "topic is a memory that they share, the place, or a rumor."},
      {NULL, "Sometimes the NPCs of one squad who relax at a bar talk about a "
             "rumor instead. NPC radiant chance on the Settings tab of the web "
             "app sets how often."},
      {NULL, "Characters who fought in the last 3 game hours do not talk."},
      {"Trigger Radiant", "Press it in the chat window to start a radiant "
                          "conversation now."},
      {NULL, "To stop them, clear Radiant conversations on the Settings tab "
             "of the web app."}}},
    {"The SSR HUB",
     {{NULL, "Press [ F8 ] to open the SSR HUB."},
      {"Dialogue Library", "The NPCs that you talked to, with their profiles "
                           "and conversation logs."},
      {"Events", "The kills, captures, and rumors of the campaign."},
      {"Journal", "Your own notes on the campaign."},
      {"Cull Future Data", "Makes NPCs forget what happened after the current "
                           "game time."},
      {"Open Web App", "Opens the web app in a new browser tab."},
      {"Restart Server", "Restarts the SSR server, for example when the web "
                         "app says that the server is not running."},
      {"Help", "Opens this guide."}}},
    {"The Dialogue Library",
     {{NULL, "The Dialogue Library lists the NPCs that you talked to. Select "
             "an NPC to see its profile and its conversation log."},
      {"Latest and A-Z", "Sort the list by the newest change to a profile, or "
                         "by name. The favorites stay at the top."},
      {"Search", "Finds an NPC by name."},
      {"Fav Toggle", "Makes the selected NPC a favorite, marked [*]. SSR never "
                     "prunes the profile of a favorite."},
      {"Generate Bio", "The AI writes the bio from the current texts and the "
                       "chats with the NPC. Choose what to write, add "
                       "instructions if you want, for example \"a former "
                       "slave who distrusts every noble\", and press Write. "
                       "Then press Keep to store it, or Discard."},
      {"Edit Bio", "Edit the text, then press Keep to store it."},
      {NULL, "After Chats before a bio (5 by default), the AI writes the full "
             "bio by itself."}}},
    {"The Events window",
     {{NULL, "The Events window lists the events of the campaign: the unique "
             "characters that your squad killed or captured, such as Tinfist, "
             "and the custom and auto events. Select an event to see its "
             "rumor."},
      {"Show", "Press it until it shows the kind of event that you want: Kill, "
               "Capture, Custom, or Auto."},
      {"Search", "Finds an event by its text."},
      {"Generate Rumor", "The AI writes the rumor of the selected event now, "
                         "with optional instructions. Then press Keep to "
                         "store it, or Discard."},
      {"Edit Rumor", "Edit the text of the rumor, then press Keep."},
      {"Add Event", "Write the rumor of an event that the game does not "
                    "track. A custom event has no game time, so Cull Future "
                    "Data keeps it."},
      {"Delete", "Deletes the rumor of a kill or a capture, or a whole custom "
                 "or auto event. The delete is irreversible."},
      {NULL, "NPCs mention the 3 newest rumors, and recall an older one when "
             "your line touches it."}}},
    {"The Journal",
     {{NULL, "The Journal holds your own notes. Each campaign has its own "
             "journal. NPCs never read it, and Cull Future Data keeps it."},
      {"New Entry", "Adds an entry at the current game time."},
      {"Title and text", "Type your note. The window saves a changed entry "
                         "when you select another entry, change the page, "
                         "press New Entry, or close the window."},
      {"Save", "Saves the entry now."},
      {"Search", "Finds the entries whose title or text holds your words."},
      {"< and >", "Go to the previous or the next page of 20 entries."},
      {"Delete", "Deletes the selected entry. The delete is irreversible."}}},
    {"Campaigns",
     {{NULL, "A campaign holds the memories, rumors, and world events of one "
             "playthrough. SSR creates the campaign Default on the first "
             "start."},
      {"New playthrough", "Create a campaign on the Campaigns tab of the web "
                          "app, and choose it under Current Campaign."},
      {"Another playthrough", "SSR does not link a campaign to a save. Before "
                              "you load the save of another playthrough, "
                              "choose its campaign."},
      {"Older save", "When you load an older save of the same playthrough, "
                     "press Cull Future Data in the SSR HUB. NPCs then forget "
                     "what happened after the time of the save."}}},
    {"Cheats",
     {{NULL, "Type /cheat or /cheats in the chat window to open the Cheats "
             "window."},
      {"Name button", "Press it until it shows the character that you want to "
                      "change: the NPC that you talked to, or a member of "
                      "your squad."},
      {"Rename", "Gives the character a new name."},
      {"Heal", "Heals all the wounds of the character at once."},
      {"Set Stat", "Sets a stat from 0 to 100."},
      {"Set Relation", "Sets how much the character likes your group, from "
                       "-100 to 100."},
      {"Set Faction", "Sets how much the faction in the list likes your "
                      "group, from -100 to 100. The list starts on the "
                      "faction of the character, and you can choose any "
                      "other faction."},
      {"Spawn", "Gives the character items. The list shows each weapon, "
                "armour, and crossbow once for each grade, from the worst "
                "grade to the best."},
      {"Add Cats and Take Cats", "Add or take the cats of the player."}}},
    {"Troubleshooting",
     {{"The NPC could not respond",
       "On the Models tab of the web app, press Test on your default profile. "
       "If the test fails, check the API key and the Model ID."},
      {"The chat key does nothing",
       "Select an NPC first, and close the Dialogue Library and the Barter "
       "window."},
      {"The server is not running", "Press Restart Server in the SSR HUB."},
      {"Replies are slow with a local model",
       "See Local models on the Tutorial tab of the web app."},
      {"A bug report", "Attach logs\\SentientSands_SDK.log and "
                       "logs\\server.log from the SSR folder."}}},
};
static const int HELP_TOPIC_COUNT =
    sizeof(HELP_TOPICS) / sizeof(HELP_TOPICS[0]);

MyGUI::Window *g_helpWindow = nullptr;
static MyGUI::Button *g_helpTopicBtns[HELP_TOPIC_COUNT];
static MyGUI::TextBox *g_helpTitle = nullptr;
static MyGUI::EditBox *g_helpText = nullptr;
static MyGUI::TextBox *g_helpPage = nullptr;
static MyGUI::Button *g_helpBackBtn = nullptr;
static MyGUI::Button *g_helpNextBtn = nullptr;
static int g_helpTopic = 0;

// The text goes through setCaption for its colour tags, so a # of a
// translation must be escaped
static std::wstring HelpText(const char *key) {
  std::string text = T(key);
  size_t slot = text.find("{key}");
  if (slot != std::string::npos)
    text.replace(slot, 5, g_chatHotkeyStr);
  return MyGUI::TextIterator::toTagsString(Utf8ToWide(text)).asWStr();
}

static void ShowHelpTopic(int topic) {
  g_helpTopic = topic;
  const HelpTopic &shown = HELP_TOPICS[topic];
  for (int i = 0; i < HELP_TOPIC_COUNT; ++i)
    g_helpTopicBtns[i]->setStateSelected(i == topic);
  g_helpTitle->setCaption(Utf8ToWide(T(shown.title)).c_str());

  std::wstring body;
  for (int i = 0; i < HELP_LINE_MAX && shown.lines[i].text; ++i) {
    if (i > 0)
      body += L"\n\n";
    if (shown.lines[i].label)
      body += L"#FFE680" + HelpText(shown.lines[i].label) + L"#D9D9D9:  ";
    else
      body += L"#D9D9D9";
    body += HelpText(shown.lines[i].text);
  }
  g_helpText->setCaption(body.c_str());
  // setCaption leaves the cursor at the end, and the view follows the cursor
  g_helpText->setTextCursor(0);
  g_helpText->setVScrollPosition(0);

  g_helpPage->setCaption(
      Utf8ToWide(ToString(topic + 1) + " / " + ToString(HELP_TOPIC_COUNT))
          .c_str());
  g_helpBackBtn->setEnabled(topic > 0);
  g_helpNextBtn->setEnabled(topic < HELP_TOPIC_COUNT - 1);
}

static void OnHelpTopicClick(MyGUI::Widget *sender) {
  for (int i = 0; i < HELP_TOPIC_COUNT; ++i)
    if (sender == g_helpTopicBtns[i])
      ShowHelpTopic(i);
}

static void OnHelpBackClick(MyGUI::Widget *sender) {
  if (g_helpTopic > 0)
    ShowHelpTopic(g_helpTopic - 1);
}

static void OnHelpNextClick(MyGUI::Widget *sender) {
  if (g_helpTopic < HELP_TOPIC_COUNT - 1)
    ShowHelpTopic(g_helpTopic + 1);
}

static void OnHelpWindowButtonPressed(MyGUI::Window *sender,
                                      const std::string &name) {
  if (name == "close")
    CloseHelpUI();
}

static MyGUI::Button *AddHelpButton(MyGUI::Widget *client,
                                    const std::string &caption, float left,
                                    float top, float width, float height,
                                    void (*onClick)(MyGUI::Widget *),
                                    const std::string &name) {
  MyGUI::Button *button = client->createWidgetReal<MyGUI::Button>(
      "Kenshi_Button1", left, top, width, height,
      MyGUI::Align::Left | MyGUI::Align::Top, name);
  button->setCaption(Utf8ToWide(caption).c_str());
  button->eventMouseButtonClick += MyGUI::newDelegate(onClick);
  return button;
}

void CloseHelpUI() {
  if (g_helpWindow) {
    if (MyGUI::Gui::getInstancePtr())
      MyGUI::Gui::getInstancePtr()->destroyWidget(g_helpWindow);
    g_helpWindow = nullptr;
  }
}

void CreateHelpUI() {
  MyGUI::Gui *gui = MyGUI::Gui::getInstancePtr();
  if (!gui)
    return;
  if (g_helpWindow)
    CloseHelpUI();

  g_helpWindow = gui->createWidgetReal<MyGUI::Window>(
      "Kenshi_WindowCX", 0.15f, 0.1f, 0.7f, 0.8f, MyGUI::Align::Center,
      "Popup", "SentientSands_HelpWindow");
  g_helpWindow->setCaption(Utf8ToWide(T("SSR Help")).c_str());
  g_helpWindow->eventWindowButtonPressed +=
      MyGUI::newDelegate(OnHelpWindowButtonPressed);
  MyGUI::Widget *client = g_helpWindow->getClientWidget();

  float step = 0.94f / HELP_TOPIC_COUNT;
  for (int i = 0; i < HELP_TOPIC_COUNT; ++i)
    g_helpTopicBtns[i] = AddHelpButton(
        client, T(HELP_TOPICS[i].title), 0.02f, 0.02f + i * step, 0.25f,
        step - 0.01f, OnHelpTopicClick,
        "SentientSands_HelpTopic" + ToString(i));

  g_helpTitle = client->createWidgetReal<MyGUI::TextBox>(
      "Kenshi_TextboxStandardText", 0.29f, 0.02f, 0.69f, 0.06f,
      MyGUI::Align::Left | MyGUI::Align::Top, "SentientSands_HelpTitle");
  g_helpTitle->setTextAlign(MyGUI::Align::Left | MyGUI::Align::VCenter);
  g_helpTitle->setTextColour(MyGUI::Colour(1.0f, 0.9f, 0.5f));

  g_helpText = client->createWidgetReal<MyGUI::EditBox>(
      "Kenshi_WordWrap", 0.29f, 0.09f, 0.69f, 0.77f, MyGUI::Align::Default,
      "SentientSands_HelpText");
  g_helpText->setEditMultiLine(true);
  g_helpText->setEditWordWrap(true);
  g_helpText->setEditReadOnly(true);
  g_helpText->setVisibleVScroll(true);
  // MyGUI cuts text at 2048 characters by default, and a translation can be
  // longer
  g_helpText->setMaxTextLength(16384);
  g_helpText->setTextAlign(MyGUI::Align::Left | MyGUI::Align::Top);
  g_helpText->setFontHeight(18);

  g_helpBackBtn = AddHelpButton(client, "< " + T("Back"), 0.29f, 0.88f, 0.14f,
                                0.08f, OnHelpBackClick,
                                "SentientSands_HelpBackBtn");
  g_helpPage = client->createWidgetReal<MyGUI::TextBox>(
      "Kenshi_TextboxStandardText", 0.43f, 0.88f, 0.41f, 0.08f,
      MyGUI::Align::Left | MyGUI::Align::Top, "SentientSands_HelpPage");
  g_helpPage->setTextAlign(MyGUI::Align::Center);
  g_helpNextBtn = AddHelpButton(client, T("Next") + " >", 0.84f, 0.88f, 0.14f,
                                0.08f, OnHelpNextClick,
                                "SentientSands_HelpNextBtn");

  ShowHelpTopic(g_helpTopic);
}

void RefreshHelpUI() {
  if (g_helpWindow)
    CreateHelpUI();
}

} // namespace UI
} // namespace SentientSands
