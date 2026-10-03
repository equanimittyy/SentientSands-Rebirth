let online = true;
let onConnectionChange = () => {};

function setOnline(value) {
  if (value === online) return;
  online = value;
  onConnectionChange(online);
}

// fetch rejects only when no response arrives, so a rejection means the server is down or restarting.
async function request(url, options) {
  let response;
  try {
    response = await fetch(url, options);
  } catch {
    setOnline(false);
    throw new Error("The server is not running.");
  }
  setOnline(true);
  return response;
}

export function watchConnection(listener) {
  onConnectionChange = listener;
}

export async function getJson(url) {
  return readJson(await request(url));
}

export async function sendJson(method, url, body) {
  const response = await request(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return readJson(response);
}

async function readJson(response) {
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = data.errors?.map((error) => error.message).join(" ") || data.message || data.error;
    throw Object.assign(new Error(detail || `HTTP ${response.status}`), { fieldErrors: data.errors ?? [] });
  }
  return data;
}

export function el(tag, props = {}, ...children) {
  const element = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (key.startsWith("on")) element.addEventListener(key.slice(2), value);
    else element[key] = value;
  }
  element.append(...children.filter((child) => child !== null && child !== false));
  return element;
}

export const withHelp = (label, help) => el("span", { className: "label-text" }, label, el("span", { className: "help", tabIndex: 0 }, "?", el("span", { className: "tip" }, help)));

export function field(label, input, status, help) {
  return el("label", {}, help ? withHelp(label, help) : label, status ?? null, input);
}

export function deleteButton(label, onClick, disabled = false) {
  const button = el("button", { type: "button", className: "danger", disabled, onclick: onClick }, "Delete");
  button.setAttribute("aria-label", label);
  return button;
}

export const icon = (name) => el("span", { className: "icon", style: `--icon: url(/web/images/lucide/${name}.svg)` });

const ERROR_LENGTH = 60;

function iconButton(name, label, onClick) {
  const button = el("button", { type: "button", className: "icon-button", title: label, onclick: onClick }, icon(name));
  button.setAttribute("aria-label", label);
  return button;
}

// A provider error can hold a whole HTTP body, so the line shows only its start and the buttons give the rest.
export function errorLine(text) {
  const view = () => tell("Error", el("code", {}, text));
  const copy = iconButton("copy", "Copy the error", () => navigator.clipboard.writeText(text).then(() => {
    copy.replaceChildren(icon("check"));
    setTimeout(() => copy.replaceChildren(icon("copy")), 1500);
  }, view));
  return el("span", { className: "message error error-line" },
    el("span", {}, text.length > ERROR_LENGTH ? `${text.slice(0, ERROR_LENGTH).trimEnd()}…` : text),
    copy,
    iconButton("eye", "View the error", view));
}

export function showMessage(element, text, isError = false) {
  element.textContent = text;
  element.classList.toggle("error", isError);
}

export function reportUnsaved(element, unsaved) {
  element.dispatchEvent(new CustomEvent("unsaved", { bubbles: true, detail: unsaved }));
}

export function setFieldError(input, text) {
  input.classList.toggle("invalid", Boolean(text));
  const label = input.closest("label");
  if (!label) return;
  let note = label.querySelector(".field-error");
  if (!note && text) note = label.appendChild(Object.assign(document.createElement("span"), { className: "field-error" }));
  if (note) note.textContent = text;
}

// Not confirm(): the host program draws that box, for example as a VS Code dialog, so it cannot match the panel.
export function ask(title, action, ...text) {
  const dialog = document.getElementById("confirm");
  dialog.querySelector("h2").textContent = title;
  dialog.querySelector("p").replaceChildren(...text);
  const danger = dialog.querySelector(".danger");
  danger.textContent = action ?? "";
  danger.hidden = !action;
  dialog.querySelector('[value="cancel"]').textContent = action ? "Cancel" : "OK";
  dialog.returnValue = "";
  dialog.showModal();
  return new Promise((resolve) => dialog.addEventListener("close", () => resolve(dialog.returnValue === "ok"), { once: true }));
}

export const tell = (title, ...text) => ask(title, null, ...text);

export const confirmReset = (page, ...notes) =>
  ask("Reset to defaults", "Reset", "Are you sure you want to reset all settings on ", el("b", {}, page), " to their defaults?", ...notes.flatMap((note) => ["\n\n", note]));

export const checkField = (input) => setFieldError(input, input.validity.valid ? "" : input.validationMessage);
