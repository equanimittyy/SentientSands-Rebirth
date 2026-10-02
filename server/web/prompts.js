import { confirmReset, el, getJson, reportUnsaved, sendJson, setFieldError, showMessage } from "./api.js";

const list = document.getElementById("prompts-list");
const message = document.getElementById("prompts-message");
let prompts = [];
const drafts = new Map();
const notes = new Map();
const openCards = new Set();

const OTHER = "Other prompts";
const PROMPT_INFO = {
  "prompt_system.txt": { group: "Conversations", title: "System prompt", blurb: "The frame of every chat and radiant conversation. It places the prompts below, the location, the player, and the recent world events." },
  "npc_base.txt": { group: "Conversations", title: "NPC persona", blurb: "Who every NPC is at heart: a weary survivor of Kenshi who stays in character." },
  "world_lore.txt": { group: "Conversations", title: "World lore", blurb: "The history, factions, and races of Kenshi that every NPC knows." },
  "response_rules.txt": { group: "Conversations", title: "Reply rules", blurb: "How an NPC writes a reply: spoken words only, short, with no formatting or modern slang." },
  "prompt_action_tags.txt": { group: "Conversations", title: "Action tags", blurb: "The game actions that an NPC can take from a reply, such as attack, join your squad, or give an item." },
  "prompt_chat_template.txt": { group: "Conversations", title: "Chat template", blurb: "How a chat request is put together: the system prompt, the NPC profiles, the conversation so far, and the final instruction." },
  "prompt_profile_generation.txt": { group: "NPC profiles", title: "One NPC profile", blurb: "Writes the personality, backstory, and speech quirks of one NPC the first time SSR needs them." },
  "prompt_batch_profile_generation.txt": { group: "NPC profiles", title: "NPC profiles in a batch", blurb: "Writes the profiles of several new NPCs in one request, before they speak." },
  "prompt_world_synthesis.txt": { group: "World events", title: "World events", blurb: "Turns the recent events of the world into one new rumor that NPCs can mention." },
};
const GROUPS = [...new Set(Object.values(PROMPT_INFO).map((info) => info.group)), OTHER];
const promptOrder = Object.keys(PROMPT_INFO);

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
  textarea.setAttribute("aria-label", info?.title ?? prompt.name);
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
    el("strong", {}, info?.title ?? prompt.name),
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
  list.replaceChildren(...GROUPS.map((group) => {
    const members = prompts
      .filter((prompt) => (PROMPT_INFO[prompt.name]?.group ?? OTHER) === group)
      .sort((a, b) => promptOrder.indexOf(a.name) - promptOrder.indexOf(b.name));
    return members.length > 0 ? el("fieldset", {}, el("legend", {}, group), ...members.map(card)) : null;
  }).filter(Boolean));
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

document.getElementById("prompts-save").addEventListener("click", save);
document.getElementById("prompts-reset").addEventListener("click", resetAll);
