import { getJson, sendJson, showMessage } from "./api.js";

const TASK_LABELS = {
  chat: "Chat",
  ambient: "Radiant conversations",
  profile: "NPC profile",
  profile_batch: "NPC profiles in a batch",
  synthesis: "World events",
};

const editor = document.getElementById("llm-editor");
const message = document.getElementById("llm-message");
let state = null;
let tasks = [];
let providerTypes = [];
let dirty = false;

function el(tag, props = {}, ...children) {
  const element = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (key.startsWith("on")) element.addEventListener(key.slice(2), value);
    else element[key] = value;
  }
  element.append(...children.filter((child) => child !== null && child !== false));
  return element;
}

const field = (label, input) => el("label", {}, label, input);

function markDirty() {
  dirty = true;
  showMessage(message, "Unsaved changes.");
}

function changed() {
  markDirty();
  render();
}

function textInput(object, key, props = {}) {
  return el("input", {
    ...props,
    value: object[key] ?? "",
    oninput: (event) => {
      object[key] = event.target.value;
      markDirty();
    },
  });
}

function numberInput(object, key, step) {
  return el("input", {
    type: "number",
    step,
    min: 0,
    required: true,
    value: object[key],
    oninput: (event) => {
      object[key] = Number(event.target.value);
      markDirty();
    },
  });
}

function selectInput(values, current, onChange) {
  const choices = values.includes(current) ? values : [current, ...values];
  const select = el("select", { onchange: (event) => onChange(event.target.value) });
  select.append(...choices.map((value) => new Option(value, value, false, value === current)));
  return select;
}

const button = (label, onClick) => el("button", { type: "button", disabled: !onClick, onclick: onClick || null }, label);

function addForm(placeholder, onAdd) {
  const name = el("input", { placeholder });
  return el("div", { className: "add" }, name, button("Add", () => {
    const value = name.value.trim();
    if (value) onAdd(value);
  }));
}

function card(title, onRemove, ...children) {
  return el("div", { className: "card" },
    el("div", { className: "card-head" }, el("strong", {}, title), onRemove ? button("Remove", onRemove) : null),
    ...children);
}

function addNamed(collection, kind, name, value) {
  if (name in collection) {
    showMessage(message, `A ${kind} named ${name} already exists.`, true);
    return;
  }
  collection[name] = value;
  changed();
}

function renderProviders() {
  const cards = Object.entries(state.providers).map(([name, provider]) => card(name,
    () => { delete state.providers[name]; changed(); },
    field("Type", selectInput(providerTypes, provider.type, (value) => { provider.type = value; changed(); })),
    field("Base URL", textInput(provider, "base_url")),
    field("API key", textInput(provider, "api_key", {
      type: "password",
      autocomplete: "off",
      placeholder: provider.api_key_hint ? `Stored key ends in ${provider.api_key_hint}. Leave empty to keep it.` : "Leave empty to keep the stored key.",
    })),
    provider.type === "player2" ? field("Game key", textInput(provider, "game_key")) : null));
  return el("fieldset", {},
    el("legend", {}, "Providers"),
    ...cards,
    addForm("New provider name", (name) => addNamed(state.providers, "provider", name, { type: "openai", base_url: "https://", api_key: "" })));
}

async function testProfile(name, result) {
  if (dirty) {
    showMessage(result, "Save first. The test uses the saved profile.", true);
    return;
  }
  showMessage(result, "Testing...");
  try {
    const reply = await sendJson("POST", "/api/llm/test", { profile: name });
    showMessage(result, `OK: ${reply.response}`);
  } catch (error) {
    showMessage(result, `Failed: ${error.message}`, true);
  }
}

function renderProfiles() {
  const providerNames = Object.keys(state.providers);
  const cards = Object.entries(state.profiles).map(([name, profile]) => {
    profile.paramsText ??= JSON.stringify(profile.params ?? {});
    const result = el("span", { className: "message" });
    return card(name,
      () => { delete state.profiles[name]; changed(); },
      field("Provider", selectInput(providerNames, profile.provider, (value) => { profile.provider = value; markDirty(); })),
      field("Model ID", textInput(profile, "model")),
      field("Timeout (s)", numberInput(profile, "timeout", 1)),
      field("Extra request parameters (JSON)", textInput(profile, "paramsText", { className: "mono" })),
      el("div", { className: "actions" }, button("Test", () => testProfile(name, result)), result));
  });
  return el("fieldset", {},
    el("legend", {}, "Profiles"),
    el("p", { className: "hint" }, "A profile is one model on one provider. Several tasks can use the same profile."),
    ...cards,
    addForm("New profile name", (name) => addNamed(state.profiles, "profile", name, {
      provider: providerNames[0] ?? "", model: "", timeout: 120, params: {},
    })));
}

function move(list, index, offset) {
  [list[index], list[index + offset]] = [list[index + offset], list[index]];
  changed();
}

function renderRoutes() {
  const profileNames = Object.keys(state.profiles);
  const cards = tasks.map((task) => {
    const route = state.routes[task];
    const chain = route.profiles.map((name, index) => el("li", {},
      selectInput(profileNames, name, (value) => { route.profiles[index] = value; markDirty(); }),
      button("Up", index > 0 && (() => move(route.profiles, index, -1))),
      button("Down", index < route.profiles.length - 1 && (() => move(route.profiles, index, 1))),
      button("Remove", () => { route.profiles.splice(index, 1); changed(); })));
    return card(TASK_LABELS[task] ?? task, null,
      el("ol", { className: "chain" }, ...chain),
      button("Add a profile", profileNames.length > 0 && (() => { route.profiles.push(profileNames[0]); changed(); })),
      field("Max tokens", numberInput(route, "max_tokens", 1)),
      field("Temperature", numberInput(route, "temperature", 0.05)),
      field("Deadline (s)", numberInput(route, "deadline", 1)));
  });
  return el("fieldset", {},
    el("legend", {}, "Tasks"),
    el("p", { className: "hint" },
      "Each task tries its profiles in order and moves to the next one after an error, a timeout, or an empty reply. " +
      "List a profile twice to retry it. The game stops waiting after 60 s, so keep the deadline under that."),
    ...cards);
}

function render() {
  editor.replaceChildren(renderProviders(), renderProfiles(), renderRoutes());
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
