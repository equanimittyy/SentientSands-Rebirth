import { el, getJson, reportUnsaved, sendJson, setFieldError, showMessage } from "./api.js";

const list = document.getElementById("prompts-list");
const message = document.getElementById("prompts-message");
let prompts = [];
const drafts = new Map();
const notes = new Map();
const openCards = new Set();

const savedText = (prompt) => prompt.override ?? prompt.shipped;
const changedPrompts = () => prompts.filter((prompt) => drafts.get(prompt.name) !== savedText(prompt));

function updateUnsaved() {
  const unsaved = changedPrompts().length > 0;
  reportUnsaved(list, unsaved);
  showMessage(message, unsaved ? "Unsaved changes." : "");
}

function badges(prompt) {
  if (prompt.override === null) return [];
  const result = [el("span", { className: "badge" }, "Edited")];
  if (prompt.default_changed) result.push(el("span", { className: "badge fail" }, "Default changed"));
  if (prompt.default_changed === null) result.push(el("span", { className: "badge" }, "Default unknown"));
  return result;
}

function setDraft(textarea, text) {
  textarea.value = text;
  drafts.set(textarea.dataset.name, text);
  setFieldError(textarea, "");
}

function card(prompt) {
  const textarea = el("textarea", {
    className: "mono",
    rows: 12,
    value: drafts.get(prompt.name),
    oninput: (event) => {
      setDraft(event.target, event.target.value);
      updateUnsaved();
    },
  });
  textarea.dataset.name = prompt.name;
  textarea.setAttribute("aria-label", prompt.name);
  const note = notes.get(prompt.name);
  if (note?.error) setFieldError(textarea, note.text);
  const details = el("details", {
    className: "card",
    open: openCards.has(prompt.name),
    ontoggle: () => {
      if (details.open) openCards.add(prompt.name);
      else openCards.delete(prompt.name);
    },
  },
  el("summary", {}, el("strong", { className: "name" }, prompt.name), ...badges(prompt)),
  prompt.placeholders.length > 0 ? el("p", { className: "hint" }, `Placeholders: ${prompt.placeholders.map((name) => `{${name}}`).join(", ")}`) : null,
  textarea,
  prompt.override !== null ? el("details", { open: prompt.default_changed === true },
    el("summary", {}, "Shipped default"),
    el("textarea", { className: "mono", rows: 12, readOnly: true, value: prompt.shipped })) : null,
  el("div", { className: "card-actions" },
    el("button", { type: "button", onclick: () => { setDraft(textarea, prompt.shipped); updateUnsaved(); } }, "Use default"),
    el("span", { className: `message${note?.error ? " error" : ""}` }, note?.text ?? "")));
  return details;
}

// Keeps the drafts that failed to save, so the player can fix them.
async function fetchPrompts(kept) {
  try {
    ({ prompts } = await getJson("/api/prompts"));
  } catch (error) {
    showMessage(message, `Could not load the prompts: ${error.message}`, true);
    return false;
  }
  drafts.clear();
  for (const prompt of prompts) drafts.set(prompt.name, kept.get(prompt.name) ?? savedText(prompt));
  list.replaceChildren(...prompts.map(card));
  updateUnsaved();
  return true;
}

async function save() {
  const changed = changedPrompts();
  if (changed.length === 0) {
    showMessage(message, "No changes to save.");
    return;
  }
  notes.clear();
  const kept = new Map();
  for (const prompt of changed) {
    const text = drafts.get(prompt.name);
    try {
      const reply = await sendJson("POST", "/api/prompts", { name: prompt.name, text });
      notes.set(prompt.name, { text: reply.warnings.join(" ") || "Saved." });
    } catch (error) {
      kept.set(prompt.name, text);
      notes.set(prompt.name, { error: true, text: error.message });
      openCards.add(prompt.name);
    }
  }
  if (!(await fetchPrompts(kept))) return;
  if (kept.size > 0) showMessage(message, `${kept.size} of ${changed.length} prompts were not saved.`, true);
  else showMessage(message, "Saved. The next LLM call uses the new prompts.");
}

function resetAll() {
  for (const textarea of list.querySelectorAll("textarea[data-name]")) {
    setDraft(textarea, prompts.find((prompt) => prompt.name === textarea.dataset.name).shipped);
  }
  updateUnsaved();
  if (changedPrompts().length > 0) showMessage(message, "Each prompt now shows its default. Save to delete your edited copies.");
}

export async function loadPrompts() {
  notes.clear();
  return fetchPrompts(new Map());
}

document.getElementById("prompts-save").addEventListener("click", save);
document.getElementById("prompts-reset").addEventListener("click", resetAll);
