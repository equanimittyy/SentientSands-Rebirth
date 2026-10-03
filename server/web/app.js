import { getJson, watchConnection } from "./api.js";
import { loadCampaigns } from "./campaigns.js";
import { loadEditor } from "./editor.js";
import { loadLlm } from "./llm.js";
import { loadPrompts } from "./prompts.js";
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

const themeToggle = document.getElementById("theme-toggle");

function showTheme() {
  const dark = document.documentElement.dataset.theme === "dark";
  themeToggle.firstElementChild.style.setProperty("--icon", `url(/web/images/lucide/${dark ? "sun" : "moon"}.svg)`);
  themeToggle.setAttribute("aria-label", dark ? "Switch to light mode" : "Switch to dark mode");
}

themeToggle.addEventListener("click", () => {
  const theme = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = theme;
  try {
    localStorage.setItem("theme", theme);
  } catch {
    // Storage can be blocked, for example in a private window; the toggle then lasts until the page reloads.
  }
  showTheme();
});
showTheme();

const status = document.getElementById("status");
const offline = document.getElementById("offline");
const loaders = { settings: loadSettings, llm: loadLlm, prompts: loadPrompts, campaigns: loadCampaigns, editor: loadEditor };
const editors = pages.filter((page) => page.id in loaders);
const loaded = new Set();
const unsaved = new Set();
let online = true;
let campaign = null;

// A page that did not load has empty fields, and its Save would write them over the stored values.
function updateButtons() {
  for (const page of editors) {
    page.querySelector(".save").disabled = !online || !loaded.has(page.id);
    page.querySelector(".discard").disabled = !online || !unsaved.has(page.id);
  }
}

async function load(id) {
  if (await loaders[id]()) loaded.add(id);
  else loaded.delete(id);
  updateButtons();
}

document.querySelector("main").addEventListener("unsaved", (event) => {
  const id = event.target.closest("section").id;
  if (event.detail) unsaved.add(id);
  else unsaved.delete(id);
  for (const link of links) link.classList.toggle("unsaved", unsaved.has(link.hash.slice(1)));
  updateButtons();
});

for (const page of editors) page.querySelector(".discard").addEventListener("click", () => load(page.id));

window.addEventListener("beforeunload", (event) => {
  if (unsaved.size > 0) event.preventDefault();
});

async function poll() {
  try {
    const context = await getJson("/context");
    status.textContent = `Current Campaign: ${context.campaign || "None"}`;
    if (campaign !== null && context.campaign !== campaign) document.dispatchEvent(new CustomEvent("campaignchange", { detail: context.campaign }));
    campaign = context.campaign;
  } catch {
    // The offline banner reports a lost server.
  }
}

watchConnection((value) => {
  online = value;
  offline.hidden = online;
  updateButtons();
  if (online) for (const page of editors) if (!loaded.has(page.id)) load(page.id);
});

for (const page of editors) load(page.id);
poll();
setInterval(poll, POLL_MS);

// The server opens no second tab while this stream is open.
new EventSource("/web_panel/presence");
