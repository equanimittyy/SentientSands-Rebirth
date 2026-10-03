import { ask, el, field, getJson, icon, reportUnsaved, sendJson, setFieldError, showMessage } from "./api.js";

const page = document.getElementById("editor-page");
const message = document.getElementById("editor-message");
const PROFILE_KEYS = ["Name", "Race", "Sex", "Faction", "Job", "Personality", "Backstory", "SpeechQuirks"];
const LONG_PROFILE_KEYS = ["Personality", "Backstory", "SpeechQuirks"];
const SUGGESTED_CATEGORIES = ["locations", "zones", "items", "races"];
const KIND_LABELS = { manifest: "Template info", overview: "Overview", history: "History", faction: "Faction", character: "Character", entity: "World entry" };
const TEMPLATE_PARTS = ["manifest", "overview", "history"];
const SOURCES = [["campaign", "Campaign Canon"], ["template", "Templates"]];
const ORIGIN_LABELS = { template: "From the template", game: "Met in game", campaign: "Added in this campaign" };

let source = "campaign";
let canon = null;
let refusal = "";
let templates = [];
let current = "";
let template = null;
let records = [];
const drafts = new Map();
const notes = new Map();
let selected = "overview";
let query = "";
let kindFilter = "all";
let newCount = 0;
const creation = { kind: "faction", category: "locations", name: "" };
const duplication = { name: "" };

const commaList = (text) => text.split(",").map((item) => item.trim()).filter(Boolean);
const lineList = (text) => text.split("\n").map((item) => item.trim()).filter(Boolean);
const readOnly = () => (source === "template" ? !template || template.builtin : !canon);
const inCampaign = (record) => source === "campaign" && !record.isNew;

function numberOr(text) {
  const number = Number(text);
  return String(text).trim() !== "" && Number.isFinite(number) ? number : text;
}

function rest(object, keys) {
  return Object.fromEntries(Object.entries(object ?? {}).filter(([key]) => !keys.includes(key)));
}

// "original" keeps a value's JSON type, such as a number in a profile, when the player leaves the row as it was.
function rows(object) {
  return Object.entries(object ?? {}).map(([key, value]) => ({ key, value: Array.isArray(value) ? value.join(", ") : String(value), list: Array.isArray(value), original: value }));
}

function fromRows(list, skipEmpty = []) {
  const result = {};
  for (const row of list) {
    const key = row.key.trim();
    if (!key || (skipEmpty.includes(key) && row.value.trim() === "")) continue;
    if (row.list) result[key] = commaList(row.value);
    else result[key] = row.original !== undefined && row.value === String(row.original) ? row.original : row.value;
  }
  return result;
}

function toForm(kind, data) {
  if (kind === "overview") return { text: data ?? "" };
  if (kind === "history") return { entries: (Array.isArray(data) ? data : []).map((entry) => ({ title: entry?.title ?? "", text: entry?.text ?? "" })) };
  if (kind === "manifest") {
    return { name: data.name ?? "", version: data.version ?? "", authors: (data.authors ?? []).join(", "), credits: (data.credits ?? []).join("\n"), extra: rest(data, ["name", "version", "authors", "credits"]) };
  }
  if (kind === "faction") {
    return {
      game_id: data.game_id ?? "", name: data.name ?? "", aliases: (data.aliases ?? []).join(", "), major: Boolean(data.major), fields: rows(data.fields), description: data.description ?? "",
      extra: rest(data, ["game_id", "name", "aliases", "major", "fields", "description"]),
    };
  }
  if (kind === "character") {
    const profile = data.profile ?? {};
    const known = PROFILE_KEYS.map((key) => ({ key, value: profile[key] === undefined ? "" : String(profile[key]), list: false, original: profile[key] }));
    return { game_id: data.game_id ?? "", profile: [...known, ...rows(rest(profile, PROFILE_KEYS))], extra: rest(data, ["game_id", "profile"]) };
  }
  return {
    name: data.name ?? "", aliases: (data.aliases ?? []).join(", "), weight: data.weight === undefined ? "" : String(data.weight), fields: rows(data.fields), prose: rows(data.prose),
    children: (data.children ?? []).map((child) => ({ name: child.name ?? "", weight: child.weight === undefined ? "" : String(child.weight) })),
    access: JSON.stringify(data.access ?? []),
    extra: rest(data, ["name", "aliases", "weight", "fields", "prose", "children", "access"]),
  };
}

// Throws when the access rules are not valid JSON.
function toData(kind, form) {
  if (kind === "overview") return form.text.trim();
  if (kind === "history") return form.entries.map((entry) => ({ title: entry.title.trim(), text: entry.text.trim() }));
  if (kind === "manifest") return { ...form.extra, name: form.name.trim(), version: form.version.trim(), authors: commaList(form.authors), credits: lineList(form.credits) };
  if (kind === "faction") {
    return { ...form.extra, game_id: form.game_id.trim(), name: form.name.trim(), aliases: commaList(form.aliases), major: form.major, fields: fromRows(form.fields), description: form.description.trim() };
  }
  if (kind === "character") return { ...form.extra, game_id: form.game_id.trim(), profile: fromRows(form.profile, PROFILE_KEYS) };
  let access;
  try {
    access = JSON.parse(form.access.trim() || "[]");
  } catch {
    throw new Error("The access rules are not valid JSON.");
  }
  return {
    ...form.extra,
    name: form.name.trim(),
    aliases: commaList(form.aliases),
    ...(form.weight.trim() ? { weight: numberOr(form.weight) } : {}),
    fields: fromRows(form.fields),
    prose: fromRows(form.prose),
    children: form.children.filter((child) => child.name.trim()).map((child) => ({ name: child.name.trim(), ...(child.weight.trim() ? { weight: numberOr(child.weight) } : {}) })),
    access,
  };
}

function savedRecords(loaded) {
  const list = TEMPLATE_PARTS.map((kind) => ({ key: kind, kind, data: loaded[kind] }));
  for (const [id, data] of Object.entries(loaded.factions)) list.push({ key: `faction/${id}`, kind: "faction", id, data });
  for (const [id, data] of Object.entries(loaded.characters)) list.push({ key: `character/${id}`, kind: "character", id, data });
  for (const [category, entries] of Object.entries(loaded.entities)) {
    for (const [id, data] of Object.entries(entries)) list.push({ key: `entity/${category}/${id}`, kind: "entity", category, id, data });
  }
  return list;
}

function canonRecords(loaded) {
  const list = ["overview", "history"].map((kind) => ({ key: kind, kind, data: loaded[kind] }));
  for (const entry of loaded.factions) list.push({ key: `faction/${entry.id}`, kind: "faction", ...entry });
  for (const entry of loaded.characters) list.push({ key: `character/${entry.id}`, kind: "character", ...entry });
  for (const entry of loaded.entities) list.push({ key: `entity/${entry.category}/${entry.id}`, kind: "entity", ...entry });
  return list;
}

function allRecords() {
  return [...records, ...[...drafts.values()].filter((entry) => entry.isNew)];
}

function isChanged(record) {
  const entry = drafts.get(record.key);
  if (!entry) return false;
  if (entry.isNew) return true;
  try {
    return JSON.stringify(toData(record.kind, entry.form)) !== JSON.stringify(toData(record.kind, toForm(record.kind, record.data)));
  } catch {
    return true;
  }
}

const changedRecords = () => allRecords().filter(isChanged);

function formOf(record) {
  if (!drafts.has(record.key)) drafts.set(record.key, { form: toForm(record.kind, record.data) });
  return drafts.get(record.key).form;
}

function title(record) {
  const form = drafts.get(record.key)?.form;
  if (TEMPLATE_PARTS.includes(record.kind)) return KIND_LABELS[record.kind];
  if (record.kind === "character") {
    const name = form ? form.profile.find((row) => row.key === "Name")?.value : record.data?.profile?.Name;
    return name || record.id || "New character";
  }
  return (form ? form.name : record.data?.name) || record.id || `New ${KIND_LABELS[record.kind].toLowerCase()}`;
}

function kindLabel(record) {
  return record.kind === "entity" ? record.category : KIND_LABELS[record.kind];
}

function searchText(record) {
  const form = drafts.get(record.key)?.form;
  return `${title(record)} ${kindLabel(record)} ${record.id ?? ""} ${JSON.stringify(form ?? record.data)}`.toLowerCase();
}

function filterValue(record) {
  if (TEMPLATE_PARTS.includes(record.kind)) return "template";
  return record.kind === "entity" ? `entity:${record.category}` : record.kind;
}

function updateUnsaved() {
  const unsaved = changedRecords().length > 0;
  reportUnsaved(page, unsaved);
  showMessage(message, unsaved ? "Unsaved changes." : "");
}

function changed() {
  updateUnsaved();
  renderList();
}

function control(tag, object, key, path, { label, disabled = false, ...props } = {}) {
  const input = el(tag, {
    ...props,
    disabled: disabled || readOnly(),
    value: object[key],
    oninput: (event) => {
      object[key] = event.target.value;
      setFieldError(event.target, "");
      changed();
    },
  });
  input.dataset.field = JSON.stringify(path);
  if (label) input.setAttribute("aria-label", label);
  return input;
}

function iconButton(name, label, onClick) {
  const button = el("button", { type: "button", className: "icon-button", disabled: readOnly(), onclick: onClick }, icon(name));
  button.setAttribute("aria-label", label);
  return button;
}

function addButton(text, onClick) {
  return el("button", { type: "button", disabled: readOnly(), onclick: () => { onClick(); changed(); renderForm(); } }, text);
}

function removeButton(list, index, label) {
  return iconButton("trash", label, () => { list.splice(index, 1); changed(); renderForm(); });
}

function rowsEditor(legend, hint, list, path, { long = false, placeholder = "Name" } = {}) {
  return el("fieldset", {},
    el("legend", {}, legend),
    el("p", { className: "hint" }, hint),
    ...list.map((row, index) => el("div", { className: "inline row" },
      control("input", row, "key", [...path, index, "key"], { placeholder, label: `${legend} name` }),
      control(long ? "textarea" : "input", row, "value", [...path, index, "value"], { placeholder: row.list ? "Values, separated by commas" : "Value", rows: 3, label: `${legend} value` }),
      removeButton(list, index, `Remove the ${legend.toLowerCase()} row`))),
    addButton(`Add ${legend.toLowerCase().replace(/s$/, "")}`, () => list.push({ key: "", value: "", list: false })));
}

function gameIdField(form, path, record, help) {
  const locked = inCampaign(record);
  return field("Game ID", control("input", form, "game_id", [...path, "game_id"], { disabled: locked }), null, `${help}${locked ? " It cannot change after you add the entry." : ""}`);
}

function factionForm(form, path, record) {
  const major = el("input", { type: "checkbox", checked: form.major, disabled: readOnly(), onchange: (event) => { form.major = event.target.checked; changed(); } });
  return [
    gameIdField(form, path, record, "The string ID of the faction in the game data, for example 1083-gamedata.base. The Forgotten Construction Set (FCS) shows it."),
    field("Name", control("input", form, "name", [...path, "name"], { disabled: record.is_player }), null,
      record.is_player ? "The name of your faction in game. Rename your faction in game to change it." : "The name that NPCs use for the faction."),
    field("Aliases", control("input", form, "aliases", [...path, "aliases"]), null, "Other names of the faction, separated by commas."),
    el("label", { className: "check" }, major, "Major world power. Its members resist an offer to join your squad."),
    rowsEditor("Fields", "Short facts about the faction, for example its leader.", form.fields, [...path, "fields"]),
    field("Description", control("textarea", form, "description", [...path, "description"], { rows: 5 }), null, record.is_player ? "What every NPC knows about your squad." : "What NPCs know about the faction."),
  ];
}

function characterForm(form, path, record) {
  const known = form.profile.filter((row) => PROFILE_KEYS.includes(row.key));
  const others = form.profile.filter((row) => !PROFILE_KEYS.includes(row.key));
  return [
    gameIdField(form, path, record, "The string ID of the character's template in the game data, for example 19576-Dialogue.mod. The Forgotten Construction Set (FCS) shows it."),
    ...known.map((row) => field(row.key, control(LONG_PROFILE_KEYS.includes(row.key) ? "textarea" : "input", row, "value", [...path, "profile", row.key], { rows: 4 }))),
    el("fieldset", {},
      el("legend", {}, "Other profile keys"),
      ...others.map((row) => el("div", { className: "inline row" },
        control("input", row, "key", [...path, "profile", "other", row.key, "key"], { placeholder: "Key", label: "Profile key" }),
        control("input", row, "value", [...path, "profile", "other", row.key, "value"], { placeholder: "Value", label: "Profile value" }),
        removeButton(form.profile, form.profile.indexOf(row), "Remove the profile key"))),
      addButton("Add profile key", () => form.profile.push({ key: "", value: "", list: false }))),
  ];
}

function entityForm(form, path) {
  return [
    field("Name", control("input", form, "name", [...path, "name"]), null, "The name of the entry, for example a town or a zone."),
    field("Aliases", control("input", form, "aliases", [...path, "aliases"]), null, "Other names of the entry, separated by commas."),
    field("Weight", control("input", form, "weight", [...path, "weight"], { inputMode: "decimal", placeholder: "1" }), null, "How strongly the entry competes for a place in a prompt. A higher weight wins."),
    rowsEditor("Fields", "Short facts, for example the owner of a town. A value that names another entry links the two.", form.fields, [...path, "fields"]),
    rowsEditor("Prose", "Longer text about the entry, for example its description.", form.prose, [...path, "prose"], { long: true, placeholder: "Name, for example description" }),
    el("fieldset", {},
      el("legend", {}, "Children"),
      el("p", { className: "hint" }, "Other entries that belong to this one, for example the buildings of a town, by name."),
      ...form.children.map((child, index) => el("div", { className: "inline row" },
        control("input", child, "name", [...path, "children", index, "name"], { placeholder: "Name of an entry", label: "Child name" }),
        control("input", child, "weight", [...path, "children", index, "weight"], { placeholder: "Weight", inputMode: "decimal", className: "short", label: "Child weight" }),
        removeButton(form.children, index, "Remove the child"))),
      addButton("Add child", () => form.children.push({ name: "", weight: "" }))),
    field("Access rules (JSON)", control("textarea", form, "access", [...path, "access"], { className: "mono", rows: 3 }), null, "Which NPCs know this entry. Leave [] for every NPC."),
  ];
}

function historyForm(form, path) {
  return [
    el("p", { className: "hint" }, "The timeline of the world, oldest first."),
    ...form.entries.map((entry, index) => el("div", { className: "card" },
      el("div", { className: "inline row" },
        control("input", entry, "title", [...path, index, "title"], { placeholder: "Title, for example The Second Empire", label: "Title" }),
        removeButton(form.entries, index, "Remove the history entry")),
      control("textarea", entry, "text", [...path, index, "text"], { rows: 4, label: "Text" }))),
    addButton("Add history entry", () => form.entries.push({ title: "", text: "" })),
  ];
}

function manifestForm(form) {
  return [
    field("Name", control("input", form, "name", ["manifest", "name"]), null, "The name of the template that players see."),
    field("Version", control("input", form, "version", ["manifest", "version"]), null, "Your version of the template, for example 1.0.0."),
    field("Authors", control("input", form, "authors", ["manifest", "authors"]), null, "The authors of the template, separated by commas."),
    field("Credits", control("textarea", form, "credits", ["manifest", "credits"], { rows: 3 }), null, "One credit line on each line. Keep the credits of the template that you copied."),
  ];
}

function recordPath(record) {
  if (record.kind === "faction") return ["factions", record.id ?? "new"];
  if (record.kind === "character") return ["characters", record.id ?? "new"];
  if (record.kind === "entity") return ["entities", record.category, record.id ?? "new"];
  return [record.kind];
}

function selectedRecord() {
  return allRecords().find((record) => record.key === selected);
}

function renderForm() {
  const container = page.querySelector("#record-form");
  if (!container) return;
  const record = selectedRecord();
  if (!record) {
    container.replaceChildren(el("p", { className: "hint" }, "Choose an entry on the left."));
    return;
  }
  const form = formOf(record);
  const path = recordPath(record);
  const note = notes.get(record.key);
  let body;
  const overviewHelp = source === "template" ? "The world lore that every NPC knows. A new campaign copies it." : "The world lore that every NPC of this campaign knows.";
  if (record.kind === "overview") body = [field("Overview", control("textarea", form, "text", ["overview"], { className: "tall" }), null, overviewHelp)];
  else if (record.kind === "history") body = historyForm(form, ["history"]);
  else if (record.kind === "manifest") body = manifestForm(form);
  else if (record.kind === "faction") body = factionForm(form, path, record);
  else if (record.kind === "character") body = characterForm(form, path, record);
  else body = entityForm(form, path);
  // The game reports the player's faction again, so a delete would only lose its description
  const deletable = !TEMPLATE_PARTS.includes(record.kind) && !record.is_player;
  container.replaceChildren(el("div", { className: "card" },
    el("div", { className: "card-head" },
      el("span", {}, el("strong", { className: "name" }, title(record)), " ", el("span", { className: "badge" }, kindLabel(record)),
        record.is_player ? el("span", { className: "badge ok" }, "Your faction") : null,
        ORIGIN_LABELS[record.origin] ? el("span", { className: "badge" }, ORIGIN_LABELS[record.origin]) : null),
      deletable ? el("button", { type: "button", disabled: readOnly(), onclick: () => deleteRecord(record) }, "Delete") : null),
    note ? el("p", { className: `hint${note.error ? " error" : ""}` }, note.text) : null,
    ...body));
  if (note?.field) {
    const input = [...container.querySelectorAll("[data-field]")].find((element) => element.dataset.field === JSON.stringify(note.field));
    if (input) setFieldError(input, note.text);
  }
}

function renderList() {
  const list = page.querySelector("#record-list");
  if (!list) return;
  const needle = query.trim().toLowerCase();
  const shown = allRecords().filter((record) => (kindFilter === "all" || filterValue(record) === kindFilter) && (!needle || searchText(record).includes(needle)));
  list.replaceChildren(...shown.map((record) => {
    const item = el("button", {
      type: "button",
      className: `record${isChanged(record) ? " unsaved" : ""}${notes.get(record.key)?.error ? " failed" : ""}`,
      onclick: () => {
        selected = record.key;
        renderList();
        renderForm();
      },
    }, el("span", { className: "name" }, title(record)), el("span", { className: "detail" }, kindLabel(record)));
    if (record.key === selected) item.setAttribute("aria-current", "true");
    return item;
  }));
  if (shown.length === 0) list.append(el("p", { className: "hint" }, "Nothing matches."));
}

function categories() {
  return [...new Set(allRecords().filter((record) => record.kind === "entity").map((record) => record.category))].sort();
}

function filterSelect() {
  const options = [["all", "Everything"], ["template", source === "template" ? "Template info, overview, history" : "Overview, history"], ["faction", "Factions"], ["character", "Characters"], ...categories().map((category) => [`entity:${category}`, `World entries: ${category}`])];
  const select = el("select", { onchange: (event) => { kindFilter = event.target.value; renderList(); } }, ...options.map(([value, text]) => new Option(text, value, false, value === kindFilter)));
  select.setAttribute("aria-label", "Show only");
  return select;
}

function newRecordForm() {
  if (readOnly()) return null;
  const kind = el("select", { onchange: (event) => { creation.kind = event.target.value; render(); } },
    ...["faction", "character", "entity"].map((value) => new Option(KIND_LABELS[value], value, false, value === creation.kind)));
  kind.setAttribute("aria-label", "Kind of the new entry");
  const listId = "category-list";
  const category = el("input", { value: creation.category, placeholder: "Category", oninput: (event) => { creation.category = event.target.value; } });
  category.setAttribute("list", listId);
  category.setAttribute("aria-label", "Category of the new world entry");
  const name = el("input", { value: creation.name, placeholder: "Name", required: true, oninput: (event) => { creation.name = event.target.value; } });
  name.setAttribute("aria-label", "Name of the new entry");
  return el("form", { className: "new-record", onsubmit: addRecord },
    el("strong", {}, "New entry"),
    kind,
    creation.kind === "entity" ? category : null,
    el("datalist", { id: listId }, ...[...new Set([...SUGGESTED_CATEGORIES, ...categories()])].map((value) => new Option(value, value))),
    name,
    el("button", { type: "submit" }, "Add"));
}

function addRecord(event) {
  event.preventDefault();
  const name = creation.name.trim();
  const category = creation.category.trim();
  if (!name) return;
  if (creation.kind === "entity" && !/^[A-Za-z0-9_-]+$/.test(category)) {
    showMessage(message, "A category may hold only letters, digits, _ and -, for example zones.", true);
    return;
  }
  const key = `new:${++newCount}`;
  const data = creation.kind === "character" ? { profile: { Name: name } } : { name };
  drafts.set(key, { isNew: true, key, kind: creation.kind, category: creation.kind === "entity" ? category : undefined, data, form: toForm(creation.kind, data) });
  creation.name = "";
  selected = key;
  query = "";
  kindFilter = "all";
  render();
  updateUnsaved();
}

function deleteEffect(record) {
  if (source === "template") return `This deletes the ${kindLabel(record)} ${title(record)} from the template ${templateTitle()}. Campaigns that you made from the template keep their copy. `;
  const comesBack = record.kind === "faction" ? " If the game reports the faction again, it comes back with an empty description." : "";
  return `This deletes the ${kindLabel(record)} ${title(record)} from the campaign ${canon.name}.${comesBack} `;
}

const recordsUrl = () => (source === "template" ? `/api/templates/${encodeURIComponent(current)}/records` : "/api/campaign/records");
// A campaign write names the campaign that the page loaded, so the server refuses it after a switch
const target = () => (source === "template" ? {} : { campaign: canon.name });

async function deleteRecord(record) {
  if (!(await ask(`Delete ${title(record)}`, "Delete", deleteEffect(record), el("b", { className: "warning" }, "The delete takes effect immediately.")))) return;
  if (drafts.get(record.key)?.isNew) {
    drafts.delete(record.key);
    selected = "overview";
    render();
    updateUnsaved();
    return;
  }
  try {
    await sendJson("POST", `${recordsUrl()}/delete`, { ...target(), kind: record.kind, id: record.id, category: record.category });
    drafts.delete(record.key);
    notes.delete(record.key);
    selected = "overview";
    await fetchRecords(keptDrafts());
  } catch (error) {
    showMessage(message, `Delete failed: ${error.message}`, true);
  }
}

const templateTitle = () => templates.find((entry) => entry.name === current)?.title ?? current;

function keptDrafts() {
  return new Map([...drafts].filter(([key]) => {
    const record = allRecords().find((entry) => entry.key === key);
    return record && isChanged(record);
  }));
}

async function chooseTemplate(name) {
  if (changedRecords().length > 0 && !(await ask("Discard the changes", "Discard", `Your changes to ${templateTitle()} are not saved. Open ${name} and lose them?`))) {
    render();
    return;
  }
  current = name;
  selected = "overview";
  notes.clear();
  await fetchRecords(new Map());
}

const sourceTitle = () => (source === "template" ? templateTitle() : `the campaign ${canon?.name}`);

async function chooseSource(value) {
  if (value === source) return;
  const label = SOURCES.find(([key]) => key === value)[1];
  if (changedRecords().length > 0 && !(await ask("Discard the changes", "Discard", `Your changes to ${sourceTitle()} are not saved. Open ${label} and lose them?`))) return;
  const previous = source;
  source = value;
  selected = "overview";
  query = "";
  kindFilter = "all";
  notes.clear();
  // Save sends the drafts to the URL of the source, so a failed load must not leave them under the other one
  if (!(await fetchRecords(new Map()))) {
    source = previous;
    render();
  }
}

async function duplicateTemplate(event) {
  event.preventDefault();
  try {
    const reply = await sendJson("POST", `/api/templates/${encodeURIComponent(current)}/duplicate`, { new_name: duplication.name });
    duplication.name = "";
    await fetchTemplates();
    await chooseTemplate(reply.name);
    showMessage(message, `Created ${reply.name}. You can edit it now.`);
  } catch (error) {
    showMessage(message, `Duplicate failed: ${error.message}`, true);
  }
}

async function deleteTemplate() {
  if (!(await ask(`Delete ${templateTitle()}`, "Delete", "This deletes the template and all its entries. Campaigns that you made from it keep their copy. ",
    el("b", { className: "warning" }, "The delete takes effect immediately and is irreversible!")))) return;
  try {
    await sendJson("POST", `/api/templates/${encodeURIComponent(current)}/delete`, {});
    drafts.clear();
    current = "";
    await fetchTemplates();
    await fetchRecords(new Map());
  } catch (error) {
    showMessage(message, `Delete failed: ${error.message}`, true);
  }
}

function renderTemplateBar() {
  const select = el("select", { onchange: (event) => chooseTemplate(event.target.value) },
    ...templates.map((entry) => new Option(`${entry.title}${entry.builtin ? " (shipped)" : ""}`, entry.name, false, entry.name === current)));
  select.setAttribute("aria-label", "World template");
  const recordCounts = template ? counts(Object.keys(template.factions).length, Object.keys(template.characters).length, Object.values(template.entities).reduce((sum, entries) => sum + Object.keys(entries).length, 0)) : "";
  const duplicateName = el("input", { value: duplication.name, placeholder: "Name of the copy", required: true, oninput: (event) => { duplication.name = event.target.value; } });
  duplicateName.setAttribute("aria-label", "Name of the copy");
  return el("fieldset", {},
    el("legend", {}, "World template"),
    el("p", { className: "hint" }, "A world template holds the canon of a world: its overview, history, factions, characters, and world entries such as towns and zones. A new campaign copies its template, so an edit here changes only the campaigns that you create later. To change the current campaign, use Campaign Canon."),
    field("Template", select, el("span", { className: "detail" }, recordCounts)),
    template?.builtin ? el("p", { className: "hint" }, `${templateTitle()} ships with SSR, and an update replaces it, so it is read-only. Duplicate it to edit a copy.`) : null,
    ...(template?.errors ?? []).map((error) => el("p", { className: "hint error" }, error.message)),
    ...(template?.warnings ?? []).map((warning) => el("p", { className: "hint" }, warning.message)),
    el("form", { className: "add", onsubmit: duplicateTemplate }, duplicateName, el("button", { type: "submit" }, "Duplicate"),
      template && !template.builtin ? el("button", { type: "button", className: "danger", onclick: deleteTemplate }, "Delete template") : null));
}

function counts(factions, characters, entities) {
  return `${factions} factions, ${characters} characters, ${entities} world entries`;
}

function renderCanonBar() {
  const made = canon?.template.name ? ` It was made from the template ${`${canon.template.name} ${canon.template.version ?? ""}`.trim()}.` : "";
  return el("fieldset", {},
    el("legend", {}, canon ? `Campaign canon: ${canon.name}` : "Campaign canon"),
    el("p", { className: "hint" }, `The canon of the current campaign: its own copy of the overview, history, factions, characters, and world entries of its world template.${made} An edit here changes only this campaign. To edit another campaign, make it the current one on the Campaigns tab.`),
    el("p", { className: "hint" }, "NPCs read the overview and the factions. A faction that you meet in game and that the campaign lacks gets an empty entry, so you can describe it. The history, characters, and world entries are kept for a later version of SSR."),
    refusal ? el("p", { className: "hint error" }, refusal) : null,
    canon ? el("p", { className: "detail" }, counts(canon.factions.length, canon.characters.length, canon.entities.length)) : null);
}

function renderSubtabs() {
  const list = el("div", { className: "subtabs" }, ...SOURCES.map(([value, text]) => {
    const tab = el("button", { type: "button", onclick: () => chooseSource(value) }, text);
    tab.setAttribute("role", "tab");
    tab.setAttribute("aria-selected", String(value === source));
    return tab;
  }));
  list.setAttribute("role", "tablist");
  return list;
}

function render() {
  const search = el("input", {
    type: "search",
    value: query,
    placeholder: "Search names and text",
    oninput: (event) => {
      query = event.target.value;
      renderList();
    },
  });
  search.setAttribute("aria-label", "Search the entries");
  page.replaceChildren(
    renderSubtabs(),
    source === "template" ? renderTemplateBar() : renderCanonBar(),
    (source === "template" ? template : canon) ? el("div", { className: "editor-layout" },
      el("div", { className: "record-panel" }, search, filterSelect(), el("div", { id: "record-list", className: "record-list" }), newRecordForm()),
      el("div", { id: "record-form" })) : null);
  renderList();
  renderForm();
}

async function save() {
  if (readOnly()) {
    showMessage(message, "No changes to save.");
    return;
  }
  const changes = changedRecords();
  if (changes.length === 0) {
    showMessage(message, "No changes to save.");
    return;
  }
  notes.clear();
  const kept = new Map();
  for (const record of changes) {
    const entry = drafts.get(record.key);
    try {
      const reply = await sendJson("POST", recordsUrl(), { ...target(), kind: record.kind, id: record.id ?? null, category: record.category, updated_at: record.updated_at, data: toData(record.kind, entry.form) });
      const key = entry.isNew ? (record.kind === "entity" ? `entity/${record.category}/${reply.id}` : `${record.kind}/${reply.id}`) : record.key;
      if (reply.warnings.length > 0) notes.set(key, { text: reply.warnings.map((warning) => warning.message).join(" ") });
      if (selected === record.key) selected = key;
    } catch (error) {
      kept.set(record.key, entry);
      notes.set(record.key, { error: true, text: error.message, field: error.fieldErrors?.[0]?.field });
    }
  }
  const failed = kept.size;
  if (!(await fetchRecords(kept))) return;
  if (failed > 0) showMessage(message, `${failed} of ${changes.length} entries were not saved.`, true);
  else showMessage(message, source === "template" ? "Saved. Campaigns that you create from this template from now on get the changes." : `Saved to the campaign ${canon.name}.`);
}

async function fetchTemplates() {
  ({ templates } = await getJson("/api/templates"));
  if (!templates.some((entry) => entry.name === current)) current = templates[0]?.name ?? "";
}

async function fetchCanon() {
  try {
    canon = await getJson("/api/campaign/canon");
    refusal = "";
  } catch (error) {
    // A reply with an error status still has fieldErrors; a lost server has none and fails the whole load
    if (!("fieldErrors" in error)) throw error;
    canon = null;
    refusal = error.message;
  }
}

// Keeps the drafts that failed to save, so the player can fix them.
async function fetchRecords(kept) {
  try {
    if (source === "campaign") await fetchCanon();
    else {
      if (!current) await fetchTemplates();
      template = current ? (await getJson(`/api/templates/${encodeURIComponent(current)}`)).template : null;
    }
  } catch (error) {
    showMessage(message, `Could not load the ${source === "template" ? "template" : "campaign canon"}: ${error.message}`, true);
    return false;
  }
  if (source === "campaign") records = canon ? canonRecords(canon) : [];
  else records = template ? savedRecords(template) : [];
  drafts.clear();
  for (const [key, entry] of kept) drafts.set(key, entry);
  if (!allRecords().some((record) => record.key === selected)) selected = "overview";
  render();
  updateUnsaved();
  return true;
}

export async function loadEditor() {
  notes.clear();
  if (source === "template") {
    try {
      await fetchTemplates();
    } catch (error) {
      showMessage(message, `Could not load the templates: ${error.message}`, true);
      return false;
    }
  }
  return fetchRecords(new Map());
}

document.getElementById("editor-save").addEventListener("click", save);
document.addEventListener("campaignchange", (event) => {
  if (source !== "campaign" || canon?.name === event.detail) return;
  if (changedRecords().length > 0) showMessage(message, `The game switched to the campaign ${event.detail}. Your changes belong to ${canon.name}, so they cannot be saved. Discard to load ${event.detail}.`, true);
  else fetchRecords(new Map());
});
