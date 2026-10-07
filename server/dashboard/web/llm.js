import { ask, confirmReset, deleteButton, el, errorLine, field, flashMessage, getJson, icon, reportUnsaved, sendJson, setFieldError, showMessage } from "./api.js";

const TASK_LABELS = {
  chat: "Chat",
  radiant: "Radiant conversations",
  profile: "NPC profile",
  synthesis: "Rumors",
  memory: "Conversation memories",
};
const TASK_HINTS = {
  chat: "The reply of an NPC when you talk to it.",
  radiant: "A conversation between your characters who stand together, on the radiant timer.",
  profile: "The bio of an NPC, or one part of it, written after a few chats with it, or when you ask for it.",
  synthesis: "A rumor about a deed of your squad, when you stop chatting or press Generate Rumor.",
  memory: "A short summary of each conversation, written when you stop chatting for the Conversation timeout on the Settings page.",
};
const TYPE_LABELS = { openai: "OpenAI-compatible", player2: "Player2" };
const GAME_WAIT_S = 60;

const editor = document.getElementById("llm-editor");
const message = document.getElementById("llm-message");
let state = null;
let tasks = [];
let providerTypes = [];
let savedProviders = new Set();
const openCards = new Set();
const testResults = new Map();
const modelLists = new Map();
let listCount = 0;
const fieldErrors = new Map();
const checks = new WeakMap();
let focusCard = null;
let renaming = null;
let renameText = "";
let shownConfig = "";
let unsaved = false;

const cardKey = (kind, name) => `${kind}s/${name}`;

function joinNames(names) {
  return names.length < 3 ? names.join(" and ") : `${names.slice(0, -1).join(", ")}, and ${names.at(-1)}`;
}

function markDirty() {
  unsaved = true;
  reportUnsaved(editor, true);
  showMessage(message, "Unsaved changes.");
}

function changed() {
  markDirty();
  render();
}

function checkInput(input) {
  setFieldError(input, input.validationMessage || checks.get(input)?.(input.value) || fieldErrors.get(input.dataset.field) || "");
}

// The path names the field across renders, so the focus and the server's errors can find it.
function control(tag, path, props, check) {
  const element = el(tag, props);
  element.dataset.field = JSON.stringify(path);
  if (check) checks.set(element, check);
  return element;
}

function edited(input) {
  fieldErrors.delete(input.dataset.field);
  checkInput(input);
  markDirty();
}

function textInput(object, key, path, { tag = "input", ...props } = {}, check) {
  return control(tag, path, {
    ...props,
    value: object[key] ?? "",
    oninput: (event) => {
      object[key] = event.target.value;
      edited(event.target);
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
      edited(event.target);
    },
  }, check);
}

function selectInput(values, current, path, onChange, labels = {}, groups = null) {
  const missing = !values.includes(current);
  const select = control("select", path, {
    onchange: (event) => {
      fieldErrors.delete(event.target.dataset.field);
      onChange(event.target.value);
    },
  }, () => (missing ? `${current} does not exist.` : ""));
  if (missing) select.append(new Option(`${current} (missing)`, current, false, true));
  select.append(...(groups ?? values.map((value) => new Option(labels[value] ?? value, value, false, value === current))));
  return select;
}

function button(label, onClick, ariaLabel) {
  const element = el("button", { type: "button", disabled: !onClick, onclick: onClick || null }, label);
  if (ariaLabel) element.setAttribute("aria-label", ariaLabel);
  return element;
}

function addForm(placeholder, onAdd, ...controls) {
  const name = el("input", { placeholder, required: true });
  return el("form", {
    className: "add",
    onsubmit: (event) => {
      event.preventDefault();
      const value = name.value.trim();
      if (value) onAdd(value, event.target);
    },
  }, name, ...controls, el("button", { type: "submit" }, "Add"));
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
    showMessage(message, `A ${kind} named ${name} already exists.`, true);
    return;
  }
  collection[name] = value;
  openCards.add(cardKey(kind, name));
  focusCard = cardKey(kind, name);
  changed();
}

function renameKey(object, from, to) {
  return Object.fromEntries(Object.entries(object).map(([key, value]) => [key === from ? to : key, value]));
}

function finishRename(kind, collection, name, rename, apply) {
  if (renaming !== cardKey(kind, name)) return;
  renaming = null;
  const to = renameText.trim();
  if (apply && to && to !== name) {
    if (!(to in collection)) return rename(name, to);
    showMessage(message, `A ${kind} named ${to} already exists.`, true);
  }
  render();
}

// Not prompt(): the VS Code browser has no prompt box, so the name is edited in place.
function cardName(kind, collection, name, rename) {
  const key = cardKey(kind, name);
  if (renaming !== key) {
    const edit = el("button", {
      type: "button",
      className: "edit",
      onclick: (event) => {
        event.preventDefault();
        renaming = key;
        renameText = name;
        render();
        editor.querySelector("input.rename").select();
      },
    }, icon("pencil"));
    edit.setAttribute("aria-label", `Rename ${name}`);
    return [el("strong", { className: "name" }, name), edit];
  }
  const input = control("input", ["rename", key], {
    className: "rename",
    value: renameText,
    oninput: (event) => { renameText = event.target.value; },
    onclick: (event) => event.preventDefault(),
    onkeydown: (event) => {
      if (event.key !== "Enter" && event.key !== "Escape") return;
      event.preventDefault();
      finishRename(kind, collection, name, rename, event.key === "Enter");
    },
    onblur: () => finishRename(kind, collection, name, rename, true),
  });
  input.setAttribute("aria-label", `New name for ${name}`);
  return [input];
}

function moveOpenCard(kind, from, to) {
  if (openCards.delete(cardKey(kind, from))) openCards.add(cardKey(kind, to));
}

function renameProvider(name, to) {
  const provider = state.providers[name];
  if (savedProviders.has(name)) provider.previous_name ??= name;
  if (provider.previous_name === to) delete provider.previous_name;
  state.providers = renameKey(state.providers, name, to);
  for (const profile of Object.values(state.profiles)) if (profile.provider === name) profile.provider = to;
  moveOpenCard("provider", name, to);
  changed();
}

function renameProfile(name, to) {
  state.profiles = renameKey(state.profiles, name, to);
  if (state.default_profile === name) state.default_profile = to;
  for (const route of Object.values(state.routes)) route.profiles = route.profiles.map((entry) => (entry === name ? to : entry));
  if (testResults.has(name)) testResults.set(to, testResults.get(name));
  testResults.delete(name);
  moveOpenCard("profile", name, to);
  changed();
}

function dropProfile(name) {
  delete state.profiles[name];
  for (const route of Object.values(state.routes)) route.profiles = route.profiles.filter((entry) => entry !== name);
}

async function removeProvider(name) {
  if (state.profiles[state.default_profile]?.provider === name) {
    showMessage(message, `The default profile ${state.default_profile} uses this provider. Choose another default first.`, true);
    return;
  }
  const users = Object.keys(state.profiles).filter((profile) => state.profiles[profile].provider === name);
  const one = users.length === 1;
  if (users.length > 0 && !(await ask(`Delete ${name}`, "Delete", `The profile${one ? "" : "s"} ${joinNames(users)} use${one ? "s" : ""} this provider. Delete ${one ? "it" : "them"} too?`))) return;
  users.forEach(dropProfile);
  delete state.providers[name];
  changed();
}

async function removeProfile(name) {
  if (name === state.default_profile) {
    showMessage(message, `${name} is the default profile. Choose another default first.`, true);
    return;
  }
  const users = tasks.filter((task) => state.routes[task].profiles.includes(name)).map((task) => TASK_LABELS[task] ?? task);
  const one = users.length === 1;
  if (users.length > 0 && !(await ask(`Delete ${name}`, "Delete", `${joinNames(users)} use${one ? "s" : ""} this profile. Delete it, and take it out of ${one ? "that task" : "them"}?`))) return;
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

function keyBadge(provider) {
  if (!provider.api_key_set) return el("span", { className: "badge" }, "No key");
  return el("span", { className: "badge ok" }, "Key set");
}

function keyInput(provider, path) {
  const input = textInput(provider, "api_key", path, {
    type: "password",
    autocomplete: "off",
    placeholder: provider.api_key_set ? "Leave empty to keep the stored key." : "Paste the key from the provider.",
  });
  const toggle = button("Show", () => {
    const hidden = input.type === "password";
    input.type = hidden ? "text" : "password";
    toggle.textContent = hidden ? "Hide" : "Show";
  });
  return el("span", { className: "inline" }, input, toggle);
}

function typeSelect() {
  const select = el("select", {}, ...providerTypes.map((type) => new Option(TYPE_LABELS[type] ?? type, type)));
  select.setAttribute("aria-label", "Provider type");
  return select;
}

function addProvider(name, form) {
  addNamed("provider", state.providers, name, { type: form.querySelector("select").value, base_url: "", api_key: "" });
}

function renderProviders() {
  const cards = Object.entries(state.providers).sort(([a], [b]) => a.localeCompare(b)).map(([name, provider]) => {
    const path = (key) => ["providers", name, key];
    const profiles = Object.entries(state.profiles).filter(([, profile]) => profile.provider === name);
    return collapsible(cardKey("provider", name),
      [
        ...cardName("provider", state.providers, name, renameProvider),
        el("span", { className: "detail" }, `${TYPE_LABELS[provider.type] ?? provider.type} · ${host(provider.base_url)}`),
        keyBadge(provider),
      ],
      field("Type", selectInput(providerTypes, provider.type, path("type"), (value) => { provider.type = value; changed(); }, TYPE_LABELS), null, "The kind of API that the service uses. Most services use OpenAI-compatible."),
      field("Base URL", textInput(provider, "base_url", path("base_url"), { required: true, placeholder: "https://example.com/v1" }), null, "The API address from the docs of the service, for example https://example.com/v1."),
      field("API key", keyInput(provider, path("api_key")), null, "The page never shows a stored key. Leave this field empty to keep the stored key. A local server, for example Ollama, needs no key."),
      provider.type === "player2" ? field("Game key", textInput(provider, "game_key", path("game_key")), null, "The game ID that you register with Player2.") : null,
      el("div", { className: "card-actions" },
        deleteButton(`Delete ${name}`, () => removeProvider(name))),
      el("fieldset", {},
        el("legend", {}, "Profiles (Models)"),
        el("p", { className: "hint" }, "A profile is one model from this provider, with its own timeout and settings. Several tasks can use the same profile."),
        ...profiles.map(([profileName, profile]) => renderProfile(profileName, profile)),
        addForm("New profile name", (profileName) => addNamed("profile", state.profiles, profileName, {
          provider: name, model: "", timeout: 120, params: {},
        }))));
  });
  return el("fieldset", {},
    el("legend", {}, "Providers"),
    el("p", { className: "hint" }, "A provider is one AI service, for example OpenRouter or a local Ollama. It holds the address that the server sends requests to and the API key for that service."),
    ...cards,
    addForm("New provider name", addProvider, typeSelect()));
}

function testBadge(name) {
  const result = testResults.get(name);
  if (!result) return null;
  if (result.pending) return el("span", { className: "badge" }, "Testing");
  return el("span", { className: `badge ${result.ok ? "ok" : "fail"}` }, result.ok ? `OK ${result.seconds} s` : "Failed");
}

function providerPayload(provider) {
  const payload = { type: provider.type, base_url: provider.base_url, api_key: provider.api_key ?? "" };
  if (provider.type === "player2") payload.game_key = provider.game_key ?? "";
  if (provider.previous_name) payload.previous_name = provider.previous_name;
  return payload;
}

function profilePayload(name, profile) {
  let params;
  try {
    params = JSON.parse(profile.paramsText || "{}");
  } catch {
    throw new Error(`Profile ${name}: the extra request parameters are not valid JSON.`);
  }
  return { provider: profile.provider, model: profile.model, timeout: profile.timeout, params };
}

async function testProfile(name) {
  const profile = state.profiles[name];
  const provider = state.providers[profile.provider];
  let body;
  try {
    if (!provider) throw new Error(`The provider ${profile.provider} does not exist.`);
    body = { name, profile: profilePayload(name, profile), provider: providerPayload(provider) };
  } catch (error) {
    testResults.set(name, { ok: false, text: error.message });
    render();
    return;
  }
  testResults.set(name, { pending: true, text: "Testing..." });
  render();
  const start = performance.now();
  try {
    const reply = await sendJson("POST", "/api/llm/test", body);
    testResults.set(name, { ok: true, seconds: ((performance.now() - start) / 1000).toFixed(1), text: `OK: ${reply.response}` });
  } catch (error) {
    testResults.set(name, { ok: false, text: error.message });
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

async function listModels(providerName) {
  const provider = state.providers[providerName];
  if (!provider) return;
  modelLists.set(providerName, { text: "Listing the models..." });
  render();
  try {
    const reply = await sendJson("POST", "/api/llm/models", { name: providerName, provider: providerPayload(provider) });
    modelLists.set(providerName, { models: reply.models, text: `${reply.models.length} models from ${providerName}. Type to filter them.` });
  } catch (error) {
    modelLists.set(providerName, { error: true, text: `Could not list the models: ${error.message}` });
  }
  render();
}

function modelInput(profile, path) {
  const input = textInput(profile, "model", path, { required: true });
  const list = modelLists.get(profile.provider);
  const options = el("datalist", { id: `model-list-${++listCount}` }, ...(list?.models ?? []).map((id) => new Option(id, id)));
  input.setAttribute("list", options.id);
  return el("span", { className: "inline" }, input, options, button("List models", state.providers[profile.provider] && (() => listModels(profile.provider))));
}

function modelStatus(providerName) {
  const list = modelLists.get(providerName);
  return list && !list.error ? el("span", { className: "hint" }, list.text) : null;
}

// Outside the label: a button inside it before the input would become the control that the label names and clicks.
function modelError(providerName) {
  const list = modelLists.get(providerName);
  return list?.error ? el("div", { className: "field-note" }, errorLine(list.text)) : null;
}

function renderProfile(name, profile) {
  profile.paramsText ??= JSON.stringify(profile.params ?? {});
  const path = (key) => ["profiles", name, key];
  const result = testResults.get(name);
  return collapsible(cardKey("profile", name),
    [...cardName("profile", state.profiles, name, renameProfile), el("span", { className: "detail" }, profile.model || "no model ID"), testBadge(name)],
    field("Model ID", modelInput(profile, path("model")), modelStatus(profile.provider), "The exact model ID that the provider expects, for example anthropic/claude-3.5-sonnet. List models gets the IDs from the provider."),
    modelError(profile.provider),
    field("Timeout (s)", numberInput(profile, "timeout", path("timeout"), { step: 1, min: 1 }), null, "The longest that this profile waits for a reply. When the task deadline is shorter, the deadline wins."),
    field("Extra request parameters (JSON)", textInput(profile, "paramsText", path("params"), { tag: "textarea", className: "mono", rows: 3 }, paramsError), null, 'Optional model settings as JSON, for example {"top_p": 0.9}. They replace the same settings of the task.'),
    el("div", { className: "card-actions" },
      button("Test", () => testProfile(name), `Test ${name}`),
      result && !result.pending ? el("span", { className: `test-mark ${result.ok ? "ok" : "fail"}` }, icon(result.ok ? "check" : "x")) : null,
      result && !result.ok && !result.pending ? errorLine(result.text) : el("span", { className: "message" }, result?.text ?? ""),
      deleteButton(`Delete ${name}`, () => removeProfile(name))));
}

function move(list, index, offset) {
  [list[index], list[index + offset]] = [list[index + offset], list[index]];
  changed();
}

const byName = (a, b) => a.localeCompare(b);

function profileGroups(current) {
  return Object.keys(state.providers).sort(byName).map((provider) => {
    const names = Object.keys(state.profiles).filter((name) => state.profiles[name].provider === provider).sort(byName);
    return names.length > 0 ? el("optgroup", { label: provider }, ...names.map((name) => new Option(name, name, false, name === current))) : null;
  }).filter(Boolean);
}

function addProfileSelect(route, label) {
  const select = el("select", {
    onchange: (event) => {
      route.profiles.push(event.target.value);
      changed();
    },
  });
  const placeholder = new Option("Add a fallback…", "", true, true);
  placeholder.disabled = true;
  select.append(placeholder, ...profileGroups());
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
    const chain = route.profiles.map((entry, index) => {
      const isDefault = entry === null;
      const name = isDefault ? state.default_profile : entry;
      return el("li", {},
        isDefault
          ? el("strong", { className: "name" }, `${name} (default)`)
          : selectInput(profileNames, name, path("profiles", index), (value) => { route.profiles[index] = value; changed(); }, {}, profileGroups(name)),
        el("span", { className: "detail" }, state.profiles[name]?.provider ?? ""),
        testBadge(name),
        el("span", { className: "chain-buttons" },
          button(icon("arrow-up"), index > 0 && (() => move(route.profiles, index, -1)), `Move ${name} up`),
          button(icon("arrow-down"), index < route.profiles.length - 1 && (() => move(route.profiles, index, 1)), `Move ${name} down`),
          isDefault ? el("button", { type: "button", className: "danger spacer" }, "Delete") : deleteButton(`Delete ${name} from ${label}`, () => { route.profiles.splice(index, 1); changed(); })));
    });
    return el("div", { className: "card" },
      el("div", { className: "card-head" }, el("strong", {}, label)),
      TASK_HINTS[task] ? el("p", { className: "hint" }, TASK_HINTS[task]) : null,
      el("ol", { className: "chain" }, ...chain),
      profileNames.length > 0 ? addProfileSelect(route, label) : el("p", { className: "hint" }, "Add a profile to a provider first."),
      field("Max tokens", numberInput(route, "max_tokens", path("max_tokens"), { step: 1, min: 1 }), null, "The longest reply, in tokens. A token is about 3/4 of a word. Too low cuts replies short."),
      field("Temperature", numberInput(route, "temperature", path("temperature"), { step: 0.05, min: 0, max: 2 }), null, "How random the replies are. Lower is more predictable, higher is more varied."),
      field("Deadline (s)", numberInput(route, "deadline", path("deadline"), { step: 1, min: 1 }, deadlineWarning), null, "The total time that this task waits for a reply, over all of its profiles."));
  });
  return el("fieldset", {},
    el("legend", {}, "Tasks ", el("span", { className: "advanced" }, "(Advanced)")),
    el("p", { className: "hint" },
      "Each task is one kind of LLM call that SSR makes, with its own settings. It tries its profiles in order until one replies. " +
      `The game waits only ${GAME_WAIT_S} s, so keep the deadline under that.`),
    el("div", { className: "card-grid" }, ...cards));
}

function untestedWarning(name) {
  const result = testResults.get(name);
  if (result?.ok) return null;
  const failed = result && !result.pending;
  return el("p", { className: "hint error" }, failed
    ? "The last test of this profile failed. Check it under its provider."
    : "This profile is not tested yet and may not work. Press Test on it under its provider.");
}

function renderDefault() {
  return el("fieldset", {},
    el("legend", {}, "Default LLM Profile ", el("span", { className: "mandatory" }, "(Mandatory)")),
    el("p", { className: "hint" }, "Every LLM call of Sentient Sands Rebirth (SSR) uses this profile. Each task below can add other profiles before or after it."),
    field("Profile", selectInput(Object.keys(state.profiles), state.default_profile, ["default_profile"], (value) => { state.default_profile = value; changed(); }, {}, profileGroups(state.default_profile))),
    untestedWarning(state.default_profile));
}

function render() {
  const focused = document.activeElement?.dataset?.field;
  editor.replaceChildren(renderDefault(), renderProviders(), el("hr"), renderRoutes());
  for (const element of editor.querySelectorAll("[data-field]")) {
    if (element.value !== "" || fieldErrors.has(element.dataset.field)) checkInput(element);
  }
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
  for (const [name, provider] of Object.entries(state.providers)) providers[name] = providerPayload(provider);
  const profiles = {};
  for (const [name, profile] of Object.entries(state.profiles)) profiles[name] = profilePayload(name, profile);
  return { providers, profiles, default_profile: state.default_profile, routes: state.routes };
}

function load(config) {
  shownConfig = JSON.stringify(config);
  unsaved = false;
  state = { providers: config.providers, profiles: config.profiles, default_profile: config.default_profile, routes: config.routes };
  tasks = config.tasks;
  providerTypes = config.provider_types;
  savedProviders = new Set(Object.keys(config.providers));
  modelLists.clear();
  fieldErrors.clear();
  reportUnsaved(editor, false);
  render();
}

function showFieldErrors(errors) {
  fieldErrors.clear();
  for (const { field: path, message: text } of errors) {
    fieldErrors.set(JSON.stringify(path), text);
    if (path[0] === "providers" || path[0] === "profiles") openCards.add(`${path[0]}/${path[1]}`);
    if (path[0] === "profiles") openCards.add(cardKey("provider", state.profiles[path[1]].provider));
  }
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
    flashMessage(message, "Saved.");
  } catch (error) {
    showFieldErrors(error.fieldErrors ?? []);
    showMessage(message, `Save failed: ${error.message}`, true);
  }
}

// The stored keys are not in the page, so the server resets and saves in one step.
async function resetToDefaults() {
  if (!(await confirmReset("Models",
    "It removes the providers and profiles that you added, with their API keys, and any unsaved changes. The built-in providers keep their API keys.",
    el("b", { className: "warning" }, "Reset takes effect immediately and is irreversible!")))) return;
  try {
    load(await sendJson("POST", "/api/llm/reset", {}));
    showMessage(message, "");
  } catch (error) {
    showMessage(message, `Reset failed: ${error.message}`, true);
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

// Save writes the whole configuration, so the unsaved page stays whole and the player chooses which version to keep.
export async function refreshLlm() {
  let config;
  try {
    config = await getJson("/api/llm");
  } catch (error) {
    showMessage(message, `Could not load the LLM settings: ${error.message}`, true);
    return;
  }
  if (JSON.stringify(config) === shownConfig) return "current";
  if (unsaved) {
    showMessage(message, "Another tab changed the models. Save overwrites that change, and Discard loads it.", true);
    return "kept";
  }
  load(config);
  return "loaded";
}

document.getElementById("llm-save").addEventListener("click", save);
document.getElementById("llm-reset").addEventListener("click", resetToDefaults);
