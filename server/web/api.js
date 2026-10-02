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
    const detail = data.errors?.join(" ") || data.message || data.error;
    throw new Error(detail || `HTTP ${response.status}`);
  }
  return data;
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
  let note = label.querySelector(".field-error");
  if (!note && text) note = label.appendChild(Object.assign(document.createElement("span"), { className: "field-error" }));
  if (note) note.textContent = text;
}

export const checkField = (input) => setFieldError(input, input.validity.valid ? "" : input.validationMessage);
