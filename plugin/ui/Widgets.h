#pragma once
#include <mygui/MyGUI_Button.h>
#include <mygui/MyGUI_ComboBox.h>
#include <mygui/MyGUI_EditBox.h>
#include <mygui/MyGUI_ListBox.h>
#include <mygui/MyGUI_TextBox.h>
#include <mygui/MyGUI_Window.h>
#include <string>
#include <vector>
#include <windows.h>

namespace SentientSands {
namespace UI {

// Its static instance stays alive for the delegate of each window that it closes
struct CloseAction {
  void (*close)();
  void OnButton(MyGUI::Window *sender, const std::string &name);
};

typedef void (*ClickHandler)(MyGUI::Widget *);

// MyGUI reads a # in a caption as the start of a colour tag
MyGUI::UString PlainText(const std::string &utf8);
std::string ItemText(MyGUI::ListBox *list, size_t index);

// Returns the client widget, or null without a GUI
MyGUI::Widget *OpenWindow(MyGUI::Window *&window, float left, float top,
                          float width, float height, MyGUI::Align align,
                          const char *layer, const std::string &name,
                          const std::string &caption, CloseAction &onClose);
void DestroyWindow(MyGUI::Window *&window);
MyGUI::Button *AddButton(MyGUI::Widget *parent, const std::string &caption,
                         float left, float top, float width, float height,
                         MyGUI::Align align, const std::string &name,
                         ClickHandler onClick);
MyGUI::TextBox *AddLabel(
    MyGUI::Widget *parent, const std::string &text, float left, float top,
    float width, float height, MyGUI::Align align, const std::string &name,
    MyGUI::Align textAlign = MyGUI::Align::Left | MyGUI::Align::VCenter);
MyGUI::EditBox *AddLineBox(MyGUI::Widget *parent, float left, float top,
                           float width, float height, MyGUI::Align align,
                           const std::string &name);
MyGUI::EditBox *AddTextView(MyGUI::Widget *parent, float left, float top,
                            float width, float height, MyGUI::Align align,
                            const std::string &name);
MyGUI::EditBox *AddWordWrapBox(MyGUI::Widget *parent, float left, float top,
                               float width, float height,
                               const std::string &name);
void ShowFromTop(MyGUI::EditBox *box, const std::string &text);

// The names of the window and of its widgets start with prefix
void OpenConfirm(MyGUI::Window *&window, const std::string &prefix,
                 const std::string &caption, const MyGUI::UString lines[3],
                 const std::string &confirm, ClickHandler onConfirm,
                 ClickHandler onCancel, CloseAction &onClose);

// The Bio and Rumor popups, which write or edit a text through the server.
// The player can close the popup, or open it for another record, while a
// request runs, so each close makes the pending reply stale
struct EditorPopup {
  MyGUI::Window *window;
  MyGUI::Button *confirm;
  MyGUI::TextBox *status;
  int request;
  // An edit opens no popup until the stored text arrives, so its failure
  // shows in the window below
  void (*showOutside)(const std::string &text);
};

void CloseEditor(EditorPopup &popup);
MyGUI::Widget *OpenEditor(EditorPopup &popup, CloseAction &onClose,
                          const std::string &prefix, const std::string &caption,
                          float left, float top, float width, float height,
                          const std::string &confirm, ClickHandler onConfirm,
                          const std::string &cancel, ClickHandler onCancel);
MyGUI::TextBox *AddEditorLine(MyGUI::Widget *client, const std::string &text,
                              float top, const std::string &name);
MyGUI::EditBox *AddEditorBox(MyGUI::Widget *client, float top, float height,
                             const std::string &name);
void SetEditorStatus(EditorPopup &popup, const std::string &text);
void StartEditorRequest(EditorPopup &popup, const wchar_t *endpoint,
                        const std::string &json, const std::string &command);
bool TakeEditorReply(EditorPopup &popup, const std::string &data,
                     std::string &reply);
void ShowEditorFailure(EditorPopup &popup, const std::string &prefixKey,
                       const std::string &reply);

MyGUI::Button *AddRowButton(MyGUI::Widget *parent, const std::string &key,
                            float left, float top, float width,
                            const std::string &name, ClickHandler onClick);
MyGUI::TextBox *AddRowLabel(MyGUI::Widget *parent, const std::string &text,
                            float left, float top, float width,
                            const std::string &name);
MyGUI::EditBox *AddRowBox(MyGUI::Widget *parent, float left, float top,
                          float width, const std::string &name);

} // namespace UI
} // namespace SentientSands
