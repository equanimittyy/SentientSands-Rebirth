import { ask, deleteButton, el, field, getJson, progress, sendJson, showMessage, tell } from "./api.js";

const page = document.getElementById("campaigns-page");
const message = document.getElementById("campaigns-message");
let campaigns = [];
let templates = [];
let refusal = "";
const notes = new Map();
const creation = { name: "", template: "" };

const count = (number, noun) => `${number} ${noun}${number === 1 ? "" : "s"}`;
const currentName = () => campaigns.find((campaign) => campaign.active)?.name ?? "";

function noteLine(key) {
  const note = notes.get(key);
  return note ? el("p", { className: `hint${note.error ? " error" : ""}` }, note.text) : null;
}

function render() {
  page.replaceChildren(...renderCurrent(), renderCampaigns());
}

function renderCampaigns() {
  const rows = campaigns.map((campaign) => el("li", {},
    el("strong", { className: "name" }, campaign.name),
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
      el("label", {}, "Campaign Name", el("input", { value: creation.name, required: true, oninput: (event) => { creation.name = event.target.value; } })),
      el("label", {}, "Template", template),
      el("button", { type: "submit" }, "Create")),
    description,
    noteLine("create"));
}

function renderCurrent() {
  const current = currentName();
  const choice = el("select", { onchange: (event) => switchCampaign(event.target.value) },
    campaigns.some((campaign) => campaign.name === current) ? null : el("option", { value: "", disabled: true, selected: true }, "None"),
    ...campaigns.map((campaign) => new Option(campaign.name, campaign.name, false, campaign.name === current)));
  return [el("fieldset", {},
    el("legend", {}, "Current Campaign"),
    field("Campaign", choice, null, "The campaign that the game plays. Choose another one to switch to it. The next chat uses it."),
    refusal ? el("p", { className: "hint error" }, refusal) : null,
    ...(current && !refusal ? [
      el("p", { className: "hint" }, "Loaded an older save? Cull makes NPCs forget everything dated after the current game time."),
      el("div", { className: "card-actions" }, el("button", { type: "button", className: "danger", onclick: cull }, "Cull future data")),
    ] : []))];
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
  await fetchAll();
  steps.close();
}

async function deleteCampaign(campaign) {
  const next = campaigns.find((other) => other !== campaign)?.name;
  const switchNote = next ? `SSR switches to ${next} first` : "SSR has no current campaign until you create and choose one";
  if (!(await ask(`Delete ${campaign.name}`, "Delete", `This deletes the campaign ${campaign.name} with its NPC memories, factions, world events, and rumors. `,
    campaign.active ? `It is the current campaign, so ${switchNote}. ` : "",
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
  if (await (campaign.active ? loadCampaigns() : fetchAll())) showMessage(message, `Deleted ${campaign.name}.`);
  steps.close();
}

async function switchCampaign(name) {
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
  if (!(await ask("Cull future data", "Cull", `This deletes every NPC memory, event, and rumor of ${currentName()} dated after the current game time. `,
    "\n\n", el("b", { className: "warning" }, "The cull takes effect immediately and is irreversible!")))) return;
  try {
    const reply = await sendJson("POST", "/api/campaign/cull", { campaign: currentName() });
    const { dialogue, event, rumor } = reply.culled;
    showMessage(message, `Culled after ${reply.time}: ${count(dialogue, "dialogue line")}, ${count(event, "event")}, and ${count(rumor, "rumor")}.`);
  } catch (error) {
    showMessage(message, `Cull failed: ${error.message}`, true);
  }
}

async function fetchAll() {
  try {
    const list = await getJson("/api/campaigns");
    campaigns = list.campaigns;
    templates = list.templates;
    if (!templates.some((template) => template.name === creation.template)) creation.template = list.default_template;
    refusal = list.refusal ?? "";
  } catch (error) {
    showMessage(message, `Could not load the campaigns: ${error.message}`, true);
    return false;
  }
  render();
  showMessage(message, "");
  return true;
}

export async function loadCampaigns() {
  notes.clear();
  return fetchAll();
}

document.addEventListener("campaignchange", (event) => {
  if (currentName() !== event.detail) loadCampaigns();
});
