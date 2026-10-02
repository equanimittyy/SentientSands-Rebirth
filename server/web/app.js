import { getJson } from "./api.js";
import { initSettings } from "./settings.js";

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
try {
  const settings = await getJson("/settings");
  status.textContent = `Campaign: ${settings.current_campaign} | Model: ${settings.current}`;
} catch (error) {
  status.textContent = `The server is not responding (${error.message}).`;
}

initSettings();
