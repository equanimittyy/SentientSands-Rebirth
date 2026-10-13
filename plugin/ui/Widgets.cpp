#include "Widgets.h"
#include "../core/Comm.h"
#include "../core/Globals.h"
#include "../core/Utils.h"

#include <mygui/MyGUI_Delegate.h>
#include <mygui/MyGUI_Gui.h>
#include <mygui/MyGUI_TextIterator.h>

namespace SentientSands {
namespace UI {

void CloseAction::OnButton(MyGUI::Window *sender, const std::string &name) {
  if (name == "close")
    close();
}

MyGUI::UString PlainText(const std::string &utf8) {
  return MyGUI::TextIterator::toTagsString(Utf8ToWide(utf8));
}

std::string ItemText(MyGUI::ListBox *list, size_t index) {
  return MyGUI::TextIterator::getOnlyText(list->getItemNameAt(index)).asUTF8();
}

MyGUI::Widget *OpenWindow(MyGUI::Window *&window, float left, float top,
                          float width, float height, MyGUI::Align align,
                          const char *layer, const std::string &name,
                          const std::string &caption, CloseAction &onClose) {
  MyGUI::Gui *gui = MyGUI::Gui::getInstancePtr();
  if (!gui)
    return nullptr;
  DestroyWindow(window);
  window = gui->createWidgetReal<MyGUI::Window>(
      "Kenshi_WindowCX", left, top, width, height, align, layer, name);
  window->setCaption(PlainText(caption));
  window->eventWindowButtonPressed +=
      MyGUI::newDelegate(&onClose, &CloseAction::OnButton);
  return window->getClientWidget();
}

void DestroyWindow(MyGUI::Window *&window) {
  if (window && MyGUI::Gui::getInstancePtr())
    MyGUI::Gui::getInstancePtr()->destroyWidget(window);
  window = nullptr;
}

MyGUI::Button *AddButton(MyGUI::Widget *parent, const std::string &caption,
                         float left, float top, float width, float height,
                         MyGUI::Align align, const std::string &name,
                         ClickHandler onClick) {
  MyGUI::Button *button = parent->createWidgetReal<MyGUI::Button>(
      "Kenshi_Button1", left, top, width, height, align, name);
  button->setCaption(PlainText(caption));
  button->eventMouseButtonClick += MyGUI::newDelegate(onClick);
  return button;
}

MyGUI::TextBox *AddLabel(MyGUI::Widget *parent, const std::string &text,
                         float left, float top, float width, float height,
                         MyGUI::Align align, const std::string &name,
                         MyGUI::Align textAlign) {
  MyGUI::TextBox *label = parent->createWidgetReal<MyGUI::TextBox>(
      "Kenshi_TextboxStandardText", left, top, width, height, align, name);
  label->setCaption(PlainText(text));
  label->setTextAlign(textAlign);
  return label;
}

MyGUI::EditBox *AddLineBox(MyGUI::Widget *parent, float left, float top,
                           float width, float height, MyGUI::Align align,
                           const std::string &name) {
  MyGUI::EditBox *box = parent->createWidgetReal<MyGUI::EditBox>(
      "Kenshi_EditBox", left, top, width, height, align, name);
  box->setEditMultiLine(false);
  box->setEditWordWrap(false);
  box->setVisibleVScroll(false);
  box->setTextAlign(MyGUI::Align::Default);
  box->setFontHeight(18);
  return box;
}

// The Kenshi_EditBox skin shows one line only (kenshi_gotchas.md)
static MyGUI::EditBox *AddWrapped(MyGUI::Widget *parent, float left, float top,
                                  float width, float height, MyGUI::Align align,
                                  const std::string &name) {
  MyGUI::EditBox *box = parent->createWidgetReal<MyGUI::EditBox>(
      "Kenshi_WordWrap", left, top, width, height, align, name);
  box->setEditMultiLine(true);
  box->setEditWordWrap(true);
  box->setVisibleVScroll(true);
  // MyGUI cuts text at 2048 characters by default, which would cut a long log
  // or make Keep store a cut text
  box->setMaxTextLength(262144);
  box->setTextAlign(MyGUI::Align::Left | MyGUI::Align::Top);
  box->setFontHeight(18);
  return box;
}

MyGUI::EditBox *AddTextView(MyGUI::Widget *parent, float left, float top,
                            float width, float height, MyGUI::Align align,
                            const std::string &name) {
  MyGUI::EditBox *box = AddWrapped(parent, left, top, width, height, align, name);
  box->setEditReadOnly(true);
  return box;
}

MyGUI::EditBox *AddWordWrapBox(MyGUI::Widget *parent, float left, float top,
                               float width, float height,
                               const std::string &name) {
  MyGUI::EditBox *box =
      AddWrapped(parent, left, top, width, height,
                 MyGUI::Align::Top | MyGUI::Align::HStretch, name);
  // Kenshi_WordWrap sets Static, which blocks typing
  box->setEditStatic(false);
  return box;
}

void ShowFromTop(MyGUI::EditBox *box, const std::string &text) {
  box->setOnlyText(Utf8ToWide(text).c_str());
  // setOnlyText leaves the cursor at the end, and the view follows the cursor
  box->setTextCursor(0);
  box->setVScrollPosition(0);
}

void OpenConfirm(MyGUI::Window *&window, const std::string &prefix,
                 const std::string &caption, const MyGUI::UString lines[3],
                 const std::string &confirm, ClickHandler onConfirm,
                 ClickHandler onCancel, CloseAction &onClose) {
  MyGUI::Widget *client =
      OpenWindow(window, 0.30f, 0.25f, 0.40f, 0.25f, MyGUI::Align::Center,
                 "Popup", prefix + "Window", caption, onClose);
  if (!client)
    return;
  const float tops[] = {0.06f, 0.19f, 0.36f};
  for (int i = 0; i < 3; i++) {
    MyGUI::TextBox *line =
        AddLabel(client, "", 0.05f, tops[i], 0.9f, 0.11f,
                 MyGUI::Align::Top | MyGUI::Align::HStretch,
                 prefix + "L" + ToString(i), MyGUI::Align::Center);
    line->setCaption(lines[i]);
    line->setTextColour(i == 2 ? MyGUI::Colour(1.0f, 0.6f, 0.6f)
                               : MyGUI::Colour(0.85f, 0.85f, 0.85f));
  }
  AddButton(client, confirm, 0.10f, 0.62f, 0.38f, 0.30f,
            MyGUI::Align::Bottom | MyGUI::Align::Left, prefix + "ConfirmBtn",
            onConfirm);
  AddButton(client, T("Cancel"), 0.52f, 0.62f, 0.38f, 0.30f,
            MyGUI::Align::Bottom | MyGUI::Align::Right, prefix + "CancelBtn",
            onCancel);
}

void CloseEditor(EditorPopup &popup) {
  popup.request++;
  DestroyWindow(popup.window);
  popup.confirm = nullptr;
  popup.status = nullptr;
}

MyGUI::Widget *OpenEditor(EditorPopup &popup, CloseAction &onClose,
                          const std::string &prefix, const std::string &caption,
                          float left, float top, float width, float height,
                          const std::string &confirm, ClickHandler onConfirm,
                          const std::string &cancel, ClickHandler onCancel) {
  MyGUI::Widget *client =
      OpenWindow(popup.window, left, top, width, height, MyGUI::Align::Center,
                 "Popup", prefix + "Window", caption, onClose);
  if (!client)
    return nullptr;
  popup.confirm = AddButton(client, confirm, 0.10f, 0.87f, 0.38f, 0.10f,
                            MyGUI::Align::Bottom | MyGUI::Align::Left,
                            prefix + "ConfirmBtn", onConfirm);
  AddButton(client, cancel, 0.52f, 0.87f, 0.38f, 0.10f,
            MyGUI::Align::Bottom | MyGUI::Align::Right, prefix + "CancelBtn",
            onCancel);
  return client;
}

MyGUI::TextBox *AddEditorLine(MyGUI::Widget *client, const std::string &text,
                              float top, const std::string &name) {
  return AddLabel(client, text, 0.05f, top, 0.9f, 0.05f,
                  MyGUI::Align::Top | MyGUI::Align::HStretch, name);
}

MyGUI::EditBox *AddEditorBox(MyGUI::Widget *client, float top, float height,
                             const std::string &name) {
  return AddWordWrapBox(client, 0.05f, top, 0.9f, height, name);
}

void SetEditorStatus(EditorPopup &popup, const std::string &text) {
  if (popup.status)
    popup.status->setCaption(PlainText(text));
}

void StartEditorRequest(EditorPopup &popup, const wchar_t *endpoint,
                        const std::string &json, const std::string &command) {
  if (popup.confirm)
    popup.confirm->setEnabled(false);
  PostForGameThread(endpoint, json, command, ToString(popup.request));
}

bool TakeEditorReply(EditorPopup &popup, const std::string &data,
                     std::string &reply) {
  return TakeTaggedReply(data, popup.request, reply);
}

void ShowEditorFailure(EditorPopup &popup, const std::string &prefixKey,
                       const std::string &reply) {
  std::string text = FailureText(prefixKey, reply);
  if (!popup.window) {
    popup.showOutside(text);
    return;
  }
  SetEditorStatus(popup, text);
  popup.confirm->setEnabled(true);
}

MyGUI::Button *AddRowButton(MyGUI::Widget *parent, const std::string &key,
                            float left, float top, float width,
                            const std::string &name, ClickHandler onClick) {
  return AddButton(parent, T(key), left, top, width, 0.08f,
                   MyGUI::Align::Left | MyGUI::Align::Bottom, name, onClick);
}

MyGUI::TextBox *AddRowLabel(MyGUI::Widget *parent, const std::string &text,
                            float left, float top, float width,
                            const std::string &name) {
  return AddLabel(parent, text, left, top, width, 0.06f,
                  MyGUI::Align::Left | MyGUI::Align::Top, name);
}

MyGUI::EditBox *AddRowBox(MyGUI::Widget *parent, float left, float top,
                          float width, const std::string &name) {
  return AddLineBox(parent, left, top, width, 0.06f,
                    MyGUI::Align::Left | MyGUI::Align::Top, name);
}

} // namespace UI
} // namespace SentientSands
