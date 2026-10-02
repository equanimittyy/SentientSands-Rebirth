import { getJson, reportUnsaved, sendJson, setFieldError, showMessage } from "./api.js";

const TASK_LABELS = {
  chat: "Chat",
  ambient: "Radiant conversations",
  profile: "NPC profile",
  profile_batch: "NPC profiles in a batch",
  synthesis: "World events",
};
const GAME_WAIT_S = 60;

const editor = document.getElementById("llm-editor");
const message = document.getElementById("llm-message");
let state = null;
let tasks = [];
let providerTypes = [];
let dirty = false;
const openCards = new Set();
const testResults = new Map();
const checks = new WeakMap();
let focusCard = null;

function el(tag, props = {}, ...children) {
  const element = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (key.startsWith("on")) element.addEventListener(key.slice(2), value);
    else element[key] = value;
  }
  element.append(...children.filter((child) => child !== null && child !== false));
  return element;
}

const field = (label, input, hint) => el("label", {}, label, input, hint ? el("span", { className: "hint" }, hint) : null);

function joinNames(names) {
  return names.length < 3 ? names.join(" and ") : `${names.slice(0, -1).join(", ")}, and ${names.at(-1)}`;
}

function markDirty() {
  dirty = true;
  reportUnsaved(editor, true);
  showMessage(message, "Unsaved changes.");
}

function changed() {
  markDirty();
  render();
}

function checkInput(input) {
  setFieldError(input, input.validationMessage || checks.get(input)?.(input.value) || "");
}

// The path names the field across renders, so the focus can return to it.
function control(tag, path, props, check) {
  const element = el(tag, props);
  element.dataset.field = JSON.stringify(path);
  if (check) checks.set(element, check);
  return element;
}

function textInput(object, key, path, { tag = "input", ...props } = {}, check) {
  return control(tag, path, {
    ...props,
    value: object[key] ?? "",
    oninput: (event) => {
      object[key] = event.target.value;
      checkInput(event.target);
      markDirty();
    },
  }, check);
}

function numberInput(object, key, path, props, check) {
  return control("input", path, {
    type: "number",
    required: true,
    ...props,
    value: object[key],
    oninput: (event) => {
      object[key] = Number(event.target.value);
      checkInput(event.target);
      markDirty();
    },
  }, check);
}

function selectInput(values, current, path, onChange) {
  const missing = !values.includes(current);
  const select = control("select", path, { onchange: (event) => onChange(event.target.value) });
  if (missing) select.append(new Option(`${current} (missing)`, current, false, true));
  select.append(...values.map((value) => new Option(value, value, false, value === current)));
  select.classList.toggle("invalid", missing);
  return select;
}

function button(label, onClick, ariaLabel) {
  const element = el("button", { type: "button", disabled: !onClick, onclick: onClick || null }, label);
  if (ariaLabel) element.setAttribute("aria-label", ariaLabel);
  return element;
}

function addForm(placeholder, onAdd) {
  const name = el("input", { placeholder, required: true });
  return el("form", {
    className: "add",
    onsubmit: (event) => {
      event.preventDefault();
      const value = name.value.trim();
      if (value) onAdd(value);
    },
  }, name, el("button", { type: "submit" }, "Add"));
}

function collapsible(key, summary, ...children) {
  const details = el("details", {
    className: "card",
    open: openCards.has(key),
    ontoggle: () => {
      if (details.open) openCards.add(key);
      else openCards.delete(key);
    },
  }, el("summary", {}, ...summary), ...children);
  details.dataset.card = key;
  return details;
}

function addNamed(kind, collection, name, value) {
  if (name in collection) {
    showMessage(message, `A ${kind.slice(0, -1)} named ${name} already exists.`, true);
    return;
  }
  collection[name] = value;
  const key = `${kind}/${name}`;
  openCards.add(key);
  focusCard = key;
  changed();
}

function dropProfile(name) {
  delete state.profiles[name];
  for (const route of Object.values(state.routes)) route.profiles = route.profiles.filter((entry) => entry !== name);
}

function removeProvider(name) {
  const users = Object.keys(state.profiles).filter((profile) => state.profiles[profile].provider === name);
  const one = users.length === 1;
  if (users.length > 0 && !confirm(`The profile${one ? "" : "s"} ${joinNames(users)} use${one ? "s" : ""} this provider. Remove ${one ? "it" : "them"} too?`)) return;
  users.forEach(dropProfile);
  delete state.providers[name];
  changed();
}

function removeProfile(name) {
  const users = tasks.filter((task) => state.routes[task].profiles.includes(name)).map((task) => TASK_LABELS[task] ?? task);
  const one = users.length === 1;
  if (users.length > 0 && !confirm(`${joinNames(users)} use${one ? "s" : ""} this profile. Remove it from ${one ? "that task" : "them"} too?`)) return;
  dropProfile(name);
  changed();
}

function host(url) {
  try {
    return new URL(url).host || url;
  } catch {
    return url;
  }
}

function renderProviders() {
  const cards = Object.entries(state.providers).map(([name, provider]) => {
    const path = (key) => ["providers", name, key];
    return collapsible(`providers/${name}`,
      [el("strong", { className: "name" }, name), el("span", { className: "detail" }, `${provider.type} · ${host(provider.base_url)}`)],
      field("Type", selectInput(providerTypes, provider.type, path("type"), (value) => { provider.type = value; changed(); })),
      field("Base URL", textInput(provider, "base_url", path("base_url"))),
      field("API key", textInput(provider, "api_key", path("api_key"), {
        type: "password",
        autocomplete: "off",
        placeholder: provider.api_key_hint ? `Stored key ends in ${provider.api_key_hint}. Leave empty to keep it.` : "Leave empty to keep the stored key.",
      })),
      provider.type === "player2" ? field("Game key", textInput(provider, "game_key", path("game_key"))) : null,
      el("div", { className: "card-actions" }, button("Remove", () => removeProvider(name), `Remove ${name}`)));
  });
  return el("fieldset", {},
    el("legend", {}, "Providers"),
    ...cards,
    addForm("New provider name", (name) => addNamed("providers", state.providers, name, { type: "openai", base_url: "https://", api_key: "" })));
}

function testBadge(name) {
  const result = testResults.get(name);
  if (!result) return null;
  if (result.pending) return el("span", { className: "badge" }, "Testing");
  return el("span", { className: `badge ${result.ok ? "ok" : "fail"}` }, result.ok ? `OK ${result.seconds} s` : "Failed");
}

async function testProfile(name) {
  if (dirty) {
    testResults.set(name, { ok: false, text: "Save first. The test uses the saved profile." });
    render();
    return;
  }
  testResults.set(name, { pending: true, text: "Testing..." });
  render();
  const start = performance.now();
  try {
    const reply = await sendJson("POST", "/api/llm/test", { profile: name });
    testResults.set(name, { ok: true, seconds: ((performance.now() - start) / 1000).toFixed(1), text: `OK: ${reply.response}` });
  } catch (error) {
    testResults.set(name, { ok: false, text: `Failed: ${error.message}` });
  }
  render();
}

function paramsError(text) {
  try {
    const value = JSON.parse(text || "{}");
    return value && typeof value === "object" && !Array.isArray(value) ? "" : 'Enter a JSON object, for example {"top_p": 0.9}.';
  } catch (error) {
    return `This is not valid JSON: ${error.message}`;
  }
}

const profileDetail = (profile) => `${profile.provider} · ${profile.model || "no model ID"}`;

function renderProfiles() {
  const providerNames = Object.keys(state.providers);
  const cards = Object.entries(state.profiles).map(([name, profile]) => {
    profile.paramsText ??= JSON.stringify(profile.params ?? {});
    const path = (key) => ["profiles", name, key];
    const result = testResults.get(name);
    return collapsible(`profiles/${name}`,
      [el("strong", { className: "name" }, name), el("span", { className: "detail" }, profileDetail(profile)), testBadge(name)],
      field("Provider", selectInput(providerNames, profile.provider, path("provider"), (value) => { profile.provider = value; changed(); })),
      field("Model ID", textInput(profile, "model", path("model"), { required: true })),
      field("Timeout (s)", numberInput(profile, "timeout", path("timeout"), { step: 1, min: 1 }), "The task deadline can stop a profile before its timeout."),
      field("Extra request parameters (JSON)", textInput(profile, "paramsText", path("params"), { tag: "textarea", className: "mono", rows: 3 }, paramsError)),
      el("div", { className: "card-actions" },
        button("Test", () => testProfile(name), `Test ${name}`),
        el("span", { className: `message${result && !result.ok && !result.pending ? " error" : ""}` }, result?.text ?? ""),
        button("Remove", () => removeProfile(name), `Remove ${name}`)));
  });
  return el("fieldset", {},
    el("legend", {}, "Profiles"),
    el("p", { className: "hint" }, "A profile is one model on one provider. Several tasks can use the same profile."),
    ...cards,
    addForm("New profile name", (name) => addNamed("profiles", state.profiles, name, {
      provider: providerNames[0] ?? "", model: "", timeout: 120, params: {},
    })));
}

function move(list, index, offset) {
  [list[index], list[index + offset]] = [list[index + offset], list[index]];
  changed();
}

function addProfileSelect(route, label, profileNames) {
  const select = el("select", {
    onchange: (event) => {
      route.profiles.push(event.target.value);
      changed();
    },
  });
  const placeholder = new Option(route.profiles.length > 0 ? "Add a fallback…" : "Add a profile…", "", true, true);
  placeholder.disabled = true;
  select.append(placeholder, ...profileNames.map((name) => new Option(name, name)));
  select.setAttribute("aria-label", `Add a profile to ${label}`);
  return select;
}

function deadlineWarning(value) {
  return Number(value) >= GAME_WAIT_S ? `The game stops waiting after ${GAME_WAIT_S} s, so a reply after that comes too late.` : "";
}

function renderRoutes() {
  const profileNames = Object.keys(state.profiles);
  const cards = tasks.map((task) => {
    const route = state.routes[task];
    const label = TASK_LABELS[task] ?? task;
    const path = (...keys) => ["routes", task, ...keys];
    const chain = route.profiles.map((name, index) => el("li", {},
      selectInput(profileNames, name, path("profiles", index), (value) => { route.profiles[index] = value; changed(); }),
      el("span", { className: "detail" }, state.profiles[name] ? profileDetail(state.profiles[name]) : ""),
      testBadge(name),
      el("span", { className: "chain-buttons" },
        button("Up", index > 0 && (() => move(route.profiles, index, -1)), `Move ${name} up`),
        button("Down", index < route.profiles.length - 1 && (() => move(route.profiles, index, 1)), `Move ${name} down`),
        button("Remove", () => { route.profiles.splice(index, 1); changed(); }, `Remove ${name} from ${label}`))));
    return el("div", { className: "card" },
      el("div", { className: "card-head" }, el("strong", {}, label)),
      el("ol", { className: "chain" }, ...chain),
      profileNames.length > 0 ? addProfileSelect(route, label, profileNames) : el("p", { className: "hint" }, "Add a profile below first."),
      field("Max tokens", numberInput(route, "max_tokens", path("max_tokens"), { step: 1, min: 1 })),
      field("Temperature", numberInput(route, "temperature", path("temperature"), { step: 0.05, min: 0, max: 2 })),
      field("Deadline (s)", numberInput(route, "deadline", path("deadline"), { step: 1, min: 1 }, deadlineWarning)));
  });
  return el("fieldset", {},
    el("legend", {}, "Tasks"),
    el("p", { className: "hint" },
      "Each task tries its profiles in order and moves to the next one after an error, a timeout, or an empty reply. " +
      `List a profile twice to retry it. The game stops waiting after ${GAME_WAIT_S} s, so keep the deadline under that.`),
    ...cards);
}

function render() {
  const focused = document.activeElement?.dataset?.field;
  editor.replaceChildren(renderRoutes(), renderProfiles(), renderProviders());
  for (const input of editor.querySelectorAll("input, textarea")) if (input.value !== "") checkInput(input);
  if (focused) [...editor.querySelectorAll("[data-field]")].find((element) => element.dataset.field === focused)?.focus();
  if (focusCard) {
    const card = [...editor.querySelectorAll("[data-card]")].find((element) => element.dataset.card === focusCard);
    card?.querySelector("input, select")?.focus();
    card?.scrollIntoView({ block: "center" });
    focusCard = null;
  }
}

function buildPayload() {
  const providers = {};
  for (const [name, provider] of Object.entries(state.providers)) {
    providers[name] = { type: provider.type, base_url: provider.base_url, api_key: provider.api_key ?? "" };
    if (provider.type === "player2") providers[name].game_key = provider.game_key ?? "";
  }
  const profiles = {};
  for (const [name, profile] of Object.entries(state.profiles)) {
    let params;
    try {
      params = JSON.parse(profile.paramsText || "{}");
    } catch {
      throw new Error(`Profile ${name}: the extra request parameters are not valid JSON.`);
    }
    profiles[name] = { provider: profile.provider, model: profile.model, timeout: profile.timeout, params };
  }
  return { providers, profiles, routes: state.routes };
}

function load(config) {
  state = { providers: config.providers, profiles: config.profiles, routes: config.routes };
  tasks = config.tasks;
  providerTypes = config.provider_types;
  dirty = false;
  reportUnsaved(editor, false);
  render();
}

async function save() {
  let payload;
  try {
    payload = buildPayload();
  } catch (error) {
    showMessage(message, error.message, true);
    return;
  }
  try {
    load(await sendJson("POST", "/api/llm", payload));
    showMessage(message, "Saved. The next LLM call uses the new settings.");
  } catch (error) {
    showMessage(message, `Save failed: ${error.message}`, true);
  }
}

export async function loadLlm() {
  try {
    load(await getJson("/api/llm"));
    showMessage(message, "");
    return true;
  } catch (error) {
    showMessage(message, `Could not load the LLM settings: ${error.message}`, true);
    return false;
  }
}

document.getElementById("llm-save").addEventListener("click", save);
