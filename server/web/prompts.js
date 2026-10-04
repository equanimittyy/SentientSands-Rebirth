import { confirmReset, el, getJson, reportUnsaved, sendJson, setFieldError, showMessage } from "./api.js";

const list = document.getElementById("prompts-list");
const message = document.getElementById("prompts-message");
let prompts = [];
const drafts = new Map();
const notes = new Map();
const openCards = new Set();

const OTHER = "Other prompts";
const PROMPT_INFO = {
  "prompt_system.txt": { group: "Conversations", title: "System prompt", blurb: "The stable frame of every chat and banter: the rules and the world lore. It comes first, so a provider can cache it." },
  "npc_chat_template.txt": { group: "Conversations", title: "NPC chat template", blurb: "How a chat describes the NPC, from its profile. It stays the same from turn to turn." },
  "response_rules.txt": { group: "Conversations", title: "Reply rules", blurb: "The rules for how an NPC writes a reply." },
  "prompt_chat_template.txt": { group: "Conversations", title: "Chat request", blurb: "The system message of a chat: the system prompt, the judgment rule, the NPC chat template, then the chat scene. It stays the same for a whole conversation, so a provider can cache it." },
  "prompt_chat_scene.txt": { group: "Conversations", title: "Chat scene", blurb: "A snapshot of the place, the latest rumors, the player, and the NPC, written as plain sentences and taken when a conversation starts. A conversation lasts until you talk to another NPC or speak as another squad member." },
  "prompt_chat_turn.txt": { group: "Conversations", title: "Chat turn", blurb: "The last message of a chat request, which changes each turn: the player's line, then a short reminder of whom to reply as." },
  "prompt_profile_generation.txt": { group: "NPC profiles", title: "NPC bio", blurb: "Writes the bio of an NPC, or one part of it: after a few chats with it, or with Generate Bio in the Dialogue Library or in the editor. It builds on the current personality, backstory, and speech quirks, on the dialogue so far, and on your instructions." },
  "prompt_world_synthesis.txt": { group: "World events", title: "World events", blurb: "Turns the recent events of the world into one new rumor that NPCs can mention." },
};
const GROUPS = [...new Set(Object.values(PROMPT_INFO).map((info) => info.group)), OTHER];
const titleOf = (prompt) => PROMPT_INFO[prompt.name]?.title ?? prompt.name;

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
    value: drafts.get(prompt.name),
    oninput: (event) => {
      setDraft(event.target, event.target.value);
      updateUnsaved();
    },
  });
  textarea.dataset.name = prompt.name;
  const info = PROMPT_INFO[prompt.name];
  textarea.setAttribute("aria-label", titleOf(prompt));
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
  el("summary", {},
    el("strong", {}, titleOf(prompt)),
    info ? el("span", { className: "detail" }, prompt.name) : null,
    ...badges(prompt),
    info ? el("span", { className: "blurb" }, info.blurb) : null),
  prompt.placeholders.length > 0
    ? el("p", { className: "hint" }, "Placeholders: ", ...prompt.placeholders.map((name) => el("code", { className: "chip" }, `{${name}}`)))
    : null,
  textarea,
  el("div", { className: "card-actions" },
    el("button", { type: "button", onclick: () => { setDraft(textarea, prompt.shipped); updateUnsaved(); } }, "Use default"),
    el("span", { className: `message${note?.error ? " error" : ""}` }, note?.text ?? "")));
  return details;
}

async function getPrompts() {
  try {
    ({ prompts } = await getJson("/api/prompts"));
    return true;
  } catch (error) {
    showMessage(message, `Could not load the prompts: ${error.message}`, true);
    return false;
  }
}

// Keeps the drafts that failed to save, so the player can fix them.
async function fetchPrompts(kept) {
  if (!(await getPrompts())) return false;
  showPrompts(kept);
  updateUnsaved();
  return true;
}

function showPrompts(kept) {
  drafts.clear();
  for (const prompt of prompts) drafts.set(prompt.name, kept.get(prompt.name) ?? savedText(prompt));
  list.replaceChildren(...GROUPS.map((group) => {
    const members = prompts
      .filter((prompt) => (PROMPT_INFO[prompt.name]?.group ?? OTHER) === group)
      .sort((a, b) => titleOf(a).localeCompare(titleOf(b)));
    return members.length > 0 ? el("fieldset", {}, el("legend", {}, group), ...members.map(card)) : null;
  }).filter(Boolean));
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

async function resetAll() {
  if (!(await confirmReset("Prompts"))) return;
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

export async function refreshPrompts() {
  const shown = JSON.stringify(prompts);
  const unsaved = changedPrompts().length > 0;
  const kept = new Map(changedPrompts().map((prompt) => [prompt.name, drafts.get(prompt.name)]));
  if (!(await getPrompts())) return;
  if (JSON.stringify(prompts) === shown) return "current";
  showPrompts(kept);
  if (changedPrompts().length > 0 !== unsaved) updateUnsaved();
  return "loaded";
}

document.getElementById("prompts-save").addEventListener("click", save);
document.getElementById("prompts-reset").addEventListener("click", resetAll);
