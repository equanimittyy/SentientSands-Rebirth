import { getJson, watchConnection } from "./api.js";
import { loadLlm } from "./llm.js";
import { loadProfile, profileCampaign } from "./profile.js";
import { loadSettings } from "./settings.js";

const POLL_MS = 3000;

const pages = [...document.querySelectorAll("main > section")];
const links = [...document.querySelectorAll("nav a")];

function showPage() {
  const id = pages.some((page) => `#${page.id}` === location.hash) ? location.hash.slice(1) : pages[0].id;
  for (const page of pages) page.hidden = page.id !== id;
  for (const link of links) link.toggleAttribute("aria-current", link.hash === `#${id}`);
}

window.addEventListener("hashchange", showPage);
showPage();

const status = document.getElementById("status");
const offline = document.getElementById("offline");
const loaders = { settings: loadSettings, llm: loadLlm, profile: loadProfile };
const loaded = new Set();
let online = true;

// A page that did not load has empty fields, and its Save would write them over the stored values.
function updateSaveButtons() {
  for (const page of pages) page.querySelector(".save").disabled = !online || !loaded.has(page.id);
}

async function load(id) {
  if (await loaders[id]()) loaded.add(id);
  else loaded.delete(id);
  updateSaveButtons();
}

async function poll() {
  try {
    const { campaign } = await getJson("/context");
    status.textContent = `Campaign: ${campaign}`;
    if (loaded.has("profile") && profileCampaign() !== campaign) load("profile");
  } catch {
    // The offline banner reports a lost server.
  }
}

watchConnection((value) => {
  online = value;
  offline.hidden = online;
  updateSaveButtons();
  if (online) for (const page of pages) if (!loaded.has(page.id)) load(page.id);
});

for (const page of pages) load(page.id);
poll();
setInterval(poll, POLL_MS);

// The server opens no second tab while this stream is open.
new EventSource("/web_panel/presence");
