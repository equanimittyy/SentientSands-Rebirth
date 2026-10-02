import { getJson, sendJson, showMessage } from "./api.js";

const form = document.getElementById("settings-form");
const message = document.getElementById("settings-message");
let saved = {};

const fields = () => [...form.elements].filter((element) => element.name);

function valueOf(input) {
  if (input.type === "checkbox") return input.checked;
  if (input.type === "number") return Number(input.value);
  return input.value;
}

function setValue(input, value) {
  if (input.type === "checkbox") input.checked = Boolean(value);
  else input.value = value;
}

const snapshot = () => Object.fromEntries(fields().map((input) => [input.name, valueOf(input)]));

function fillOptions(select, values) {
  select.replaceChildren(...values.map((value) => new Option(value, value)));
}

// "radii.talk" reads settings.radii.talk, because /settings nests the three ranges.
function changedSettings(current) {
  const changes = {};
  for (const [name, value] of Object.entries(current)) {
    if (value === saved[name]) continue;
    const [group, key] = name.split(".");
    if (key) (changes[group] ??= {})[key] = value;
    else changes[name] = value;
  }
  return changes;
}

async function save(event) {
  event.preventDefault();
  const current = snapshot();
  const changes = changedSettings(current);
  if (Object.keys(changes).length === 0) {
    showMessage(message, "No changes to save.");
    return;
  }
  try {
    await sendJson("POST", "/settings", changes);
    saved = current;
    showMessage(message, "Saved.");
  } catch (error) {
    showMessage(message, `Save failed: ${error.message}`, true);
  }
}

export async function loadSettings() {
  try {
    const settings = await getJson("/settings");
    fillOptions(form.elements.language, settings.supported_languages);
    fillOptions(form.elements.chat_hotkey, settings.chat_hotkeys);
    for (const input of fields()) {
      setValue(input, input.name.split(".").reduce((object, key) => object?.[key], settings));
    }
    saved = snapshot();
    showMessage(message, "");
    return true;
  } catch (error) {
    showMessage(message, `Could not load the settings: ${error.message}`, true);
    return false;
  }
}

form.addEventListener("submit", save);
