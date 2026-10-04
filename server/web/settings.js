import { checkField, confirmReset, getJson, reportUnsaved, sendJson, showMessage } from "./api.js";

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

function fillFields(values) {
  for (const input of fields()) setValue(input, input.name.split(".").reduce((object, key) => object?.[key], values));
}

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

const hasChanges = () => Object.keys(changedSettings(snapshot())).length > 0;

function updateUnsaved() {
  const unsaved = hasChanges();
  reportUnsaved(form, unsaved);
  showMessage(message, unsaved ? "Unsaved changes." : "");
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
    reportUnsaved(form, false);
    showMessage(message, "Saved.");
  } catch (error) {
    showMessage(message, `Save failed: ${error.message}`, true);
  }
}

async function resetToDefaults() {
  if (!(await confirmReset("Settings"))) return;
  try {
    fillFields(await getJson("/settings/defaults"));
    fields().forEach(checkField);
    updateUnsaved();
  } catch (error) {
    showMessage(message, `Could not load the defaults: ${error.message}`, true);
  }
}

async function fetchSettings(kept) {
  try {
    const settings = await getJson("/settings");
    fillOptions(form.elements.language, settings.supported_languages);
    fillOptions(form.elements.chat_hotkey, settings.chat_hotkeys);
    fillOptions(form.elements.log_level, settings.log_levels);
    fillFields(settings);
    saved = snapshot();
    for (const [name, value] of kept) setValue(form.elements[name], value);
    fields().forEach(checkField);
    return true;
  } catch (error) {
    showMessage(message, `Could not load the settings: ${error.message}`, true);
    return false;
  }
}

export async function loadSettings() {
  if (!(await fetchSettings([]))) return false;
  reportUnsaved(form, false);
  showMessage(message, "");
  return true;
}

export async function refreshSettings() {
  const unsaved = hasChanges();
  const shown = JSON.stringify(saved);
  const kept = Object.entries(snapshot()).filter(([name, value]) => value !== saved[name]);
  if (!(await fetchSettings(kept))) return;
  if (hasChanges() !== unsaved) updateUnsaved();
  return JSON.stringify(saved) === shown ? "current" : "loaded";
}

form.addEventListener("submit", save);
document.getElementById("settings-reset").addEventListener("click", resetToDefaults);
form.addEventListener("input", (event) => {
  checkField(event.target);
  updateUnsaved();
});
