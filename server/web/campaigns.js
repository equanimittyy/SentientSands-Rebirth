import { ask, deleteButton, el, field, getJson, progress, reportUnsaved, sendJson, setFieldError, showMessage, tell } from "./api.js";

const page = document.getElementById("campaigns-page");
const message = document.getElementById("campaigns-message");
let campaigns = [];
let templates = [];
let active = null;
let refusal = "";
let rumorDrafts = {};
const notes = new Map();
const creation = { name: "", template: "" };

const count = (number, noun) => `${number} ${noun}${number === 1 ? "" : "s"}`;

const changedRumors = () => (active?.rumors ?? []).filter((rumor) => rumorDrafts[rumor.id].trim() !== rumor.text);
const hasChanges = () => changedRumors().length > 0;

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

const templateTitle = (name) => templates.find((template) => template.name === name)?.title ?? name;

function render() {
  page.replaceChildren(...renderCurrent(), renderCampaigns(), ...renderActive());
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
    deleteButton(`Delete the campaign ${campaign.name}`, () => deleteCampaign(campaign))));
  const description = el("p", { className: "hint" });
  const describe = () => {
    description.textContent = templates.find((entry) => entry.name === creation.template)?.description ?? "";
    description.hidden = !description.textContent;
  };
  describe();
  // Not render(): it rebuilds the select, so a player who steps through the options with the arrow keys loses focus on each step
  const template = el("select", { onchange: (event) => { creation.template = event.target.value; describe(); } },
    ...templates.map((entry) => new Option(entry.title, entry.name, false, entry.name === creation.template)));
  return el("fieldset", {},
    el("legend", {}, "Campaign Manager"),
    el("ul", { className: "plain-list" }, ...rows),
    el("form", { className: "add", onsubmit: createCampaign },
      el("label", {}, "Campaign Name", textInput(creation, "name", ["create", "name"], { required: true })),
      el("label", {}, "Template", template),
      el("button", { type: "submit" }, "Create")),
    description,
    noteLine("create"));
}

function renderCurrent() {
  const current = campaigns.find((campaign) => campaign.active)?.name ?? active?.name;
  const choice = el("select", { onchange: (event) => switchCampaign(event.target.value) },
    campaigns.some((campaign) => campaign.name === current) ? null : el("option", { value: "", disabled: true, selected: true }, "None"),
    ...campaigns.map((campaign) => new Option(campaign.name, campaign.name, false, campaign.name === current)));
  const template = active?.template.name ? `Made from ${templateTitle(active.template.name)} ${active.template.version ?? ""}`.trim() : null;
  return [el("fieldset", {},
    el("legend", {}, "Current Campaign"),
    field("Campaign", choice, template ? el("span", { className: "detail" }, template) : null, "The campaign that the game plays. Choose another one to switch to it. The next chat uses it."),
    refusal ? el("p", { className: "hint error" }, refusal) : null,
    ...(active ? [
      el("p", { className: "hint" }, "Loaded an older save? Cull makes NPCs forget everything dated after the current game time."),
      el("div", { className: "card-actions" }, el("button", { type: "button", className: "danger", onclick: cull }, "Cull future data")),
    ] : []))];
}

function renderActive() {
  return active ? [renderRumors(), renderEvents()] : [];
}

function renderRumors() {
  const rows = active.rumors.map((rumor) => el("div", { className: "card" },
    el("div", { className: "inline row" },
      textInput(rumorDrafts, rumor.id, ["rumors", rumor.id], { tag: "textarea", rows: 2, label: "Rumor" }),
      deleteButton("Delete the rumor", () => deleteRow("rumor", rumor.id))),
    noteLine(`rumor:${rumor.id}`)));
  return el("fieldset", {},
    el("legend", {}, `Rumors (${active.rumors.length})`),
    el("p", { className: "hint" }, "The world news that SSR writes from what happened in game. NPCs mention the newest rumors."),
    ...(rows.length > 0 ? rows : [el("p", { className: "hint" }, "No rumors yet.")]));
}

function renderEvents() {
  const rows = [...active.events].reverse().map((event) => el("li", {},
    el("span", { className: "detail" }, event.line),
    deleteButton("Delete the event", () => deleteRow("event", event.id))));
  return el("fieldset", {},
    el("legend", {}, `Event history (${active.events.length})`),
    el("p", { className: "hint" }, "What happened in game, newest first. SSR writes the rumors from it."),
    rows.length > 0 ? el("details", {}, el("summary", {}, "Show the events"), el("ul", { className: "plain-list" }, ...rows)) : el("p", { className: "hint" }, "No events yet."));
}

async function createCampaign(event) {
  event.preventDefault();
  const switching = !campaigns.some((campaign) => campaign.active);
  const steps = progress("Creating the campaign", "Writing the campaign", ...(switching ? ["Switching campaigns"] : []), "Loading the campaign");
  try {
    const { name } = await sendJson("POST", "/api/campaigns", creation);
    creation.name = "";
    steps.next();
    notes.set("create", { text: `Created ${name}. Choose it under Current Campaign to play it.` });
    if (switching) {
      await sendJson("POST", "/api/campaigns/switch", { name });
      steps.next();
      notes.set("create", { text: `Created ${name} and switched to it. The next chat uses it.` });
    }
  } catch (error) {
    notes.set("create", { error: true, text: error.message });
  }
  await fetchAll(unsavedDrafts());
  steps.close();
}

async function deleteCampaign(campaign) {
  const next = campaigns.find((other) => other !== campaign)?.name;
  const switchNote = next ? `SSR switches to ${next} first` : "SSR has no current campaign until you create and choose one";
  if (!(await ask(`Delete ${campaign.name}`, "Delete", `This deletes the campaign ${campaign.name} with its NPC memories, factions, world events, and rumors. `,
    campaign.active ? `It is the current campaign, so ${switchNote}${hasChanges() ? ", and your unsaved changes are lost" : ""}. ` : "",
    "\n\n", el("b", { className: "warning" }, "The delete takes effect immediately and is irreversible!")))) return;
  const switching = campaign.active && next;
  const steps = progress("Deleting the campaign", ...(switching ? [`Opening ${next}`] : []), `Deleting ${campaign.name}`, "Loading the campaign");
  try {
    if (switching) {
      await sendJson("POST", "/api/campaigns/switch", { name: next });
      steps.next();
    }
    await sendJson("POST", "/api/campaigns/delete", { name: campaign.name });
  } catch (error) {
    steps.close();
    await tell("Cannot delete the campaign", error.message);
    return;
  }
  steps.next();
  if (await (campaign.active ? loadCampaigns() : fetchAll(unsavedDrafts()))) showMessage(message, `Deleted ${campaign.name}.`);
  steps.close();
}

async function switchCampaign(name) {
  if (hasChanges() && !(await ask("Discard the changes", "Discard", `Your changes to ${active.name} are not saved. Switch to ${name} and lose them?`))) {
    render();
    return;
  }
  const steps = progress("Switching campaigns", `Opening ${name}`, "Loading the campaign");
  try {
    await sendJson("POST", "/api/campaigns/switch", { name });
  } catch (error) {
    steps.close();
    showMessage(message, `Switch failed: ${error.message}`, true);
    return;
  }
  steps.next();
  notes.clear();
  if (await loadCampaigns()) showMessage(message, `Switched to ${name}. The next chat uses it.`);
  steps.close();
}

async function cull() {
  if (!(await ask("Cull future data", "Cull", `This deletes every NPC memory, event, and rumor of ${active.name} dated after the current game time. `,
    "\n\n", el("b", { className: "warning" }, "The cull takes effect immediately and is irreversible!")))) return;
  try {
    const reply = await sendJson("POST", "/api/campaign/cull", { campaign: active.name });
    const { dialogue, event, rumor } = reply.culled;
    if (await fetchAll(unsavedDrafts())) showMessage(message, `Culled after ${reply.time}: ${count(dialogue, "dialogue line")}, ${count(event, "event")}, and ${count(rumor, "rumor")}.`);
  } catch (error) {
    showMessage(message, `Cull failed: ${error.message}`, true);
  }
}

const DELETES = {
  rumor: { url: "/api/campaign/rumors/delete", title: "Delete the rumor", effect: "NPCs stop mentioning this rumor." },
  event: { url: "/api/campaign/events/delete", title: "Delete the event", effect: "Later rumors cannot draw on this event." },
};

async function deleteRow(kind, id) {
  const { url, title, effect } = DELETES[kind];
  if (!(await ask(title, "Delete", `${effect} `, "\n\n", el("b", { className: "warning" }, "The delete takes effect immediately.")))) return;
  try {
    await sendJson("POST", url, { campaign: active.name, id });
    await fetchAll(unsavedDrafts());
  } catch (error) {
    showMessage(message, `Delete failed: ${error.message}`, true);
  }
}

function unsavedDrafts() {
  return { rumors: Object.fromEntries(changedRumors().map((rumor) => [rumor.id, rumorDrafts[rumor.id]])) };
}

async function save() {
  if (!active) return;
  const kept = unsavedDrafts();
  const jobs = [];
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
  rumorDrafts = Object.fromEntries((active?.rumors ?? []).map((rumor) => [rumor.id, kept.rumors[rumor.id] ?? rumor.text]));
  render();
  updateUnsaved();
  return true;
}

export async function loadCampaigns() {
  notes.clear();
  return fetchAll({ rumors: {} });
}

document.getElementById("campaigns-save").addEventListener("click", save);
document.addEventListener("campaignchange", (event) => {
  if (!active || active.name === event.detail) return;
  if (hasChanges()) showMessage(message, `The game switched to the campaign ${event.detail}. Your changes belong to ${active.name}, so they cannot be saved. Discard to load ${event.detail}.`, true);
  else loadCampaigns();
});
