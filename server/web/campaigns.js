import { ask, el, field, getJson, icon, reportUnsaved, sendJson, setFieldError, showMessage } from "./api.js";

const page = document.getElementById("campaigns-page");
const message = document.getElementById("campaigns-message");
let campaigns = [];
let templates = [];
let active = null;
let refusal = "";
const draft = { overview: "" };
let factionDrafts = {};
let rumorDrafts = {};
const notes = new Map();
const openCards = new Set();
const creation = { name: "", template: "" };
let factionFilter = "";

const commaList = (text) => text.split(",").map((item) => item.trim()).filter(Boolean);
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

function factionDraft(faction) {
  return {
    name: faction.name,
    aliases: faction.aliases.join(", "),
    major: faction.major,
    description: faction.description,
    fields: Object.entries(faction.fields).map(([key, value]) => ({ key, value: Array.isArray(value) ? value.join(", ") : value, list: Array.isArray(value) })),
  };
}

function factionChanges(faction) {
  const fields = {};
  for (const row of faction.fields) if (row.key.trim()) fields[row.key.trim()] = row.list ? commaList(row.value) : row.value.trim();
  return { name: faction.name.trim(), aliases: commaList(faction.aliases), major: faction.major, fields, description: faction.description.trim() };
}

const changedFactions = () => (active?.factions ?? []).filter((faction) => !same(factionChanges(factionDrafts[faction.faction_id]), factionChanges(factionDraft(faction))));
const changedRumors = () => (active?.rumors ?? []).filter((rumor) => rumorDrafts[rumor.id].trim() !== rumor.text);
const overviewChanged = () => active !== null && draft.overview.trim() !== active.overview;
const hasChanges = () => overviewChanged() || changedFactions().length > 0 || changedRumors().length > 0;

function updateUnsaved() {
  reportUnsaved(page, hasChanges());
  showMessage(message, hasChanges() ? "Unsaved changes." : "");
}

function noteLine(key) {
  const note = notes.get(key);
  return note ? el("p", { className: `hint${note.error ? " error" : ""}` }, note.text) : null;
}

function textInput(object, key, path, { tag = "input", label, ...props } = {}) {
  const input = el(tag, {
    ...props,
    value: object[key],
    oninput: (event) => {
      object[key] = event.target.value;
      setFieldError(event.target, "");
      updateUnsaved();
    },
  });
  input.dataset.field = JSON.stringify(path);
  if (label) input.setAttribute("aria-label", label);
  return input;
}

function iconButton(name, label, onClick) {
  const button = el("button", { type: "button", className: "icon-button", onclick: onClick }, icon(name));
  button.setAttribute("aria-label", label);
  return button;
}

function collapsible(key, summary, ...children) {
  return el("details", {
    className: "card",
    open: openCards.has(key),
    ontoggle: (event) => {
      if (event.target.open) openCards.add(key);
      else openCards.delete(key);
    },
  }, el("summary", {}, ...summary), ...children);
}

const templateTitle = (name) => templates.find((template) => template.name === name)?.title ?? name;

function render() {
  page.replaceChildren(renderCampaigns(), ...renderActive());
  for (const note of notes.values()) {
    const input = note.field && [...page.querySelectorAll("[data-field]")].find((element) => element.dataset.field === JSON.stringify(note.field));
    if (input) setFieldError(input, note.text);
  }
}

function renderCampaigns() {
  const rows = campaigns.map((campaign) => el("li", {},
    el("strong", { className: "name" }, campaign.name),
    campaign.template ? el("span", { className: "detail" }, `from ${templateTitle(campaign.template)}`) : null,
    campaign.active ? el("span", { className: "badge ok" }, "Current") : null,
    campaign.outdated ? el("span", { className: "badge fail" }, "Made by an earlier version") : null));
  const template = el("select", { onchange: (event) => { creation.template = event.target.value; } },
    ...templates.map((entry) => new Option(entry.title, entry.name, false, entry.name === creation.template)));
  template.setAttribute("aria-label", "World template of the new campaign");
  return el("fieldset", {},
    el("legend", {}, "Campaigns"),
    el("p", { className: "hint" }, "A campaign is one playthrough with its own NPC memories, factions, and world events. To switch the campaign, use the Campaign Manager in the SSR HUB in game."),
    el("ul", { className: "plain-list" }, ...rows),
    el("form", { className: "add", onsubmit: createCampaign },
      textInput(creation, "name", ["create", "name"], { placeholder: "New campaign name", required: true, label: "New campaign name" }),
      template,
      el("button", { type: "submit" }, "Create")),
    noteLine("create"),
    el("p", { className: "hint" }, "A new campaign starts with a copy of the overview and the factions of its world template. Edit the templates on the Editor tab."));
}

function renderActive() {
  if (refusal) return [el("fieldset", {}, el("legend", {}, "Current campaign"), el("p", { className: "hint error" }, refusal))];
  if (!active) return [];
  const template = active.template.name ? `${templateTitle(active.template.name)} ${active.template.version ?? ""}`.trim() : "an unknown template";
  return [
    el("fieldset", {},
      el("legend", {}, `Current campaign: ${active.name}`),
      el("p", { className: "hint" }, `Made from ${template}. Changes on this page apply only to this campaign, from the next chat on.`),
      field("Overview", textInput(draft, "overview", ["overview"], { tag: "textarea", className: "tall" }), noteLine("overview"), "The world lore that every NPC of this campaign knows.")),
    renderFactions(),
    renderRumors(),
    renderEvents(),
  ];
}

function fieldRows(rows, path) {
  return el("fieldset", {},
    el("legend", {}, "Fields"),
    el("p", { className: "hint" }, "Short facts about the faction, for example its leader. NPCs read them with the description."),
    ...rows.map((row, index) => el("div", { className: "inline row" },
      textInput(row, "key", [...path, index, "key"], { placeholder: "Name, for example leader", label: "Field name" }),
      textInput(row, "value", [...path, index, "value"], { placeholder: row.list ? "Values, separated by commas" : "Value", label: "Field value" }),
      iconButton("trash", "Remove the field", () => { rows.splice(index, 1); updateUnsaved(); render(); }))),
    el("button", { type: "button", onclick: () => { rows.push({ key: "", value: "", list: false }); render(); } }, "Add field"));
}

function factionCard(faction) {
  const id = faction.faction_id;
  const edit = factionDrafts[id];
  const path = (key) => ["factions", id, key];
  const major = el("input", { type: "checkbox", checked: edit.major, onchange: (event) => { edit.major = event.target.checked; updateUnsaved(); } });
  return collapsible(`faction:${id}`,
    [
      el("strong", { className: "name" }, faction.name),
      el("span", { className: "detail" }, id),
      faction.is_player ? el("span", { className: "badge ok" }, "Your faction") : null,
      faction.major ? el("span", { className: "badge" }, "Major") : null,
      el("span", { className: "badge" }, faction.origin === "template" ? "From the template" : "Met in game"),
    ],
    field("Name", textInput(edit, "name", path("name"), { disabled: faction.is_player }), null,
      faction.is_player ? "The name of your faction in game. Rename your faction in game to change it." : "The name that NPCs use for the faction."),
    field("Aliases", textInput(edit, "aliases", path("aliases")), null, "Other names of the faction, separated by commas, for example Okranites."),
    el("label", { className: "check" }, major, "Major world power. Its members resist an offer to join your squad."),
    fieldRows(edit.fields, path("fields")),
    field("Description", textInput(edit, "description", path("description"), { tag: "textarea", rows: 4 }), null, "What NPCs know about the faction."),
    noteLine(`faction:${id}`));
}

function matchingFactions() {
  const query = factionFilter.trim().toLowerCase();
  return active.factions.filter((faction) => !query || [faction.name, faction.faction_id, faction.description, ...faction.aliases, ...Object.values(faction.fields).flat()].some((text) => text.toLowerCase().includes(query)));
}

function renderFactions() {
  const list = el("div", {}, ...matchingFactions().map(factionCard));
  const search = el("input", {
    type: "search",
    placeholder: "Search the factions",
    value: factionFilter,
    oninput: (event) => {
      factionFilter = event.target.value;
      list.replaceChildren(...matchingFactions().map(factionCard));
    },
  });
  search.setAttribute("aria-label", "Search the factions");
  return el("fieldset", {},
    el("legend", {}, `Factions (${active.factions.length})`),
    el("p", { className: "hint" }, "The factions of this campaign. A faction that you meet in game and that the template lacks gets an empty entry here, so you can describe it. The description of your faction tells every NPC who your squad is."),
    search,
    list);
}

function renderRumors() {
  const rows = active.rumors.map((rumor) => el("div", { className: "card" },
    el("div", { className: "inline row" },
      textInput(rumorDrafts, rumor.id, ["rumors", rumor.id], { tag: "textarea", rows: 2, label: "Rumor" }),
      iconButton("trash", "Delete the rumor", () => deleteRow("rumor", rumor.id))),
    noteLine(`rumor:${rumor.id}`)));
  return el("fieldset", {},
    el("legend", {}, `Rumors (${active.rumors.length})`),
    el("p", { className: "hint" }, "The world news that SSR writes from what happened in game. NPCs mention the newest rumors."),
    ...(rows.length > 0 ? rows : [el("p", { className: "hint" }, "No rumors yet.")]));
}

function renderEvents() {
  const rows = [...active.events].reverse().map((event) => el("li", {},
    el("span", { className: "detail" }, event.line),
    iconButton("trash", "Delete the event", () => deleteRow("event", event.id))));
  return el("fieldset", {},
    el("legend", {}, `Event history (${active.events.length})`),
    el("p", { className: "hint" }, "What happened in game, newest first. SSR writes the rumors from it."),
    rows.length > 0 ? el("details", {}, el("summary", {}, "Show the events"), el("ul", { className: "plain-list" }, ...rows)) : el("p", { className: "hint" }, "No events yet."));
}

async function createCampaign(event) {
  event.preventDefault();
  try {
    const reply = await sendJson("POST", "/api/campaigns", creation);
    creation.name = "";
    notes.set("create", { text: `Created ${reply.name}. To play it, switch to it in the Campaign Manager in the SSR HUB in game.` });
    const list = await getJson("/api/campaigns");
    campaigns = list.campaigns;
  } catch (error) {
    notes.set("create", { error: true, text: error.message });
  }
  render();
}

const DELETES = {
  rumor: { url: "/api/campaign/rumors/delete", title: "Delete the rumor", effect: "NPCs stop mentioning this rumor." },
  event: { url: "/api/campaign/events/delete", title: "Delete the event", effect: "Later rumors cannot draw on this event." },
};

async function deleteRow(kind, id) {
  const { url, title, effect } = DELETES[kind];
  if (!(await ask(title, "Delete", `${effect} `, el("b", { className: "warning" }, "The delete takes effect immediately.")))) return;
  try {
    await sendJson("POST", url, { campaign: active.name, id });
    await fetchAll(unsavedDrafts());
  } catch (error) {
    showMessage(message, `Delete failed: ${error.message}`, true);
  }
}

function unsavedDrafts() {
  return {
    overview: overviewChanged() ? draft.overview : null,
    factions: Object.fromEntries(changedFactions().map((faction) => [faction.faction_id, factionDrafts[faction.faction_id]])),
    rumors: Object.fromEntries(changedRumors().map((rumor) => [rumor.id, rumorDrafts[rumor.id]])),
  };
}

async function save() {
  if (!active) return;
  const kept = unsavedDrafts();
  const jobs = [];
  if (kept.overview !== null) {
    jobs.push(["overview", () => { kept.overview = null; }, () => sendJson("POST", "/api/campaign/overview", { campaign: active.name, text: draft.overview })]);
  }
  for (const faction of changedFactions()) {
    const id = faction.faction_id;
    const changes = factionChanges(factionDrafts[id]);
    jobs.push([`faction:${id}`, () => { delete kept.factions[id]; }, () => sendJson("POST", "/api/campaign/factions", { campaign: active.name, faction_id: id, updated_at: faction.updated_at, changes })]);
  }
  for (const rumor of changedRumors()) {
    jobs.push([`rumor:${rumor.id}`, () => { delete kept.rumors[rumor.id]; }, () => sendJson("POST", "/api/campaign/rumors", { campaign: active.name, id: rumor.id, text: rumorDrafts[rumor.id] })]);
  }
  if (jobs.length === 0) {
    showMessage(message, "No changes to save.");
    return;
  }
  notes.clear();
  let failed = 0;
  for (const [key, forget, send] of jobs) {
    try {
      await send();
      forget();
    } catch (error) {
      failed += 1;
      notes.set(key, { error: true, text: error.message, field: error.fieldErrors?.[0]?.field });
      openCards.add(key);
    }
  }
  if (!(await fetchAll(kept))) return;
  if (failed > 0) showMessage(message, `${failed} of ${jobs.length} changes were not saved.`, true);
  else showMessage(message, "Saved. The next chat uses the changes.");
}

// Keeps the drafts that failed to save, so the player can fix them.
async function fetchAll(kept) {
  try {
    const list = await getJson("/api/campaigns");
    campaigns = list.campaigns;
    templates = list.templates;
    if (!templates.some((template) => template.name === creation.template)) creation.template = list.default_template;
    try {
      active = await getJson("/api/campaign");
      refusal = "";
    } catch (error) {
      // A reply with an error status still has fieldErrors; a lost server has none and fails the whole load
      if (!("fieldErrors" in error)) throw error;
      active = null;
      refusal = error.message;
    }
  } catch (error) {
    showMessage(message, `Could not load the campaigns: ${error.message}`, true);
    return false;
  }
  draft.overview = kept.overview ?? active?.overview ?? "";
  factionDrafts = Object.fromEntries((active?.factions ?? []).map((faction) => [faction.faction_id, kept.factions[faction.faction_id] ?? factionDraft(faction)]));
  rumorDrafts = Object.fromEntries((active?.rumors ?? []).map((rumor) => [rumor.id, kept.rumors[rumor.id] ?? rumor.text]));
  render();
  updateUnsaved();
  return true;
}

export async function loadCampaigns() {
  notes.clear();
  return fetchAll({ overview: null, factions: {}, rumors: {} });
}

document.getElementById("campaigns-save").addEventListener("click", save);
document.addEventListener("campaignchange", (event) => {
  if (!active || active.name === event.detail) return;
  if (hasChanges()) showMessage(message, `The game switched to the campaign ${event.detail}. Your changes belong to ${active.name}, so they cannot be saved. Discard to load ${event.detail}.`, true);
  else loadCampaigns();
});
