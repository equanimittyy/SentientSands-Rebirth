import { ask, deleteButton, el, field, getJson, progress, reportUnsaved, sendJson, setFieldError, showMessage, tell, withHelp } from "./api.js";

const page = document.getElementById("editor-page");
const message = document.getElementById("editor-message");
const PROFILE_KEYS = ["Name", "Race", "Sex", "Faction", "Job", "Personality", "Backstory", "SpeechQuirks"];
const LONG_PROFILE_KEYS = ["Personality", "Backstory", "SpeechQuirks"];
const CHOICE_KEYS = ["Race", "Sex", "Faction"];
const CHOICE_HELP = {
  Race: "The choices are the race entries. Unknown also stands for a race that has no entry.",
  Faction: "The choices are the factions. Unknown also stands for a faction that has no record.",
};
const KIND_LABELS = { manifest: "Template info", overview: "Overview", history: "History", faction: "Faction", character: "Character" };
const CATEGORY_LABELS = { races: "Race", locations: "Location", regions: "Region" };
// Mirrors FACTS in server/scripts/world_template.py, whose validator refuses any other category.
const FACTS = {
  factions: { leader: "text", capital: "text", founder: "text", nobles: "list", bases: "list", territory: "list", allies: "list", enemies: "list" },
  races: { type: "text", homeland: "text", faction: "text" },
  locations: { type: "text", zone: "list", owner: "list" },
  regions: { animals: "list", factions: "list", hazards: "list" },
};
const TEMPLATE_PARTS = ["manifest", "overview", "history"];
const SOURCES = [["campaign", "Campaign Canon"], ["template", "Templates"]];
const ORIGIN_LABELS = { seed: "Seeded", game: "Met in game", campaign: "Added in this campaign" };
const IMPORT_PROBLEMS_SHOWN = 10;

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
let showSeeded = true;
try { showSeeded = localStorage.getItem("showSeeded") !== "false"; } catch {}
let newCount = 0;
const creation = { kind: "faction", name: "" };
const duplication = { name: "" };
const importing = { name: "" };

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
    return { name: data.name ?? "", description: data.description ?? "", version: data.version ?? "", authors: (data.authors ?? []).join(", "), credits: (data.credits ?? []).join("\n"), extra: rest(data, ["name", "description", "version", "authors", "credits"]) };
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
    return { game_id: data.game_id ?? "", profile: known, details: rest(profile, PROFILE_KEYS), extra: rest(data, ["game_id", "profile"]) };
  }
  const labels = entryLabels();
  return {
    name: data.name ?? "", aliases: (data.aliases ?? []).join(", "), fields: rows(data.fields), description: data.description ?? "",
    children: (data.children ?? []).map((child) => ({ entry: child.entry ?? "", text: labels.get(child.entry) ?? child.entry ?? "", weight: child.weight === undefined ? "" : String(child.weight) })),
    extra: rest(data, ["name", "aliases", "fields", "description", "children"]),
  };
}

// Throws when a relation names no entry.
function toData(kind, form) {
  if (kind === "overview") return form.text.trim();
  if (kind === "history") return form.entries.map((entry) => ({ title: entry.title.trim(), text: entry.text.trim() }));
  if (kind === "manifest") return { ...form.extra, name: form.name.trim(), description: form.description.trim(), version: form.version.trim(), authors: commaList(form.authors), credits: lineList(form.credits) };
  if (kind === "faction") {
    return { ...form.extra, game_id: form.game_id.trim(), name: form.name.trim(), aliases: commaList(form.aliases), major: form.major, fields: fromRows(form.fields), description: form.description.trim() };
  }
  if (kind === "character") {
    const profile = form.profile.map((row) => (CHOICE_KEYS.includes(row.key) ? { ...row, value: choice(row.key, row.value) } : row));
    return { ...form.extra, game_id: form.game_id.trim(), profile: { ...fromRows(profile, PROFILE_KEYS), ...form.details } };
  }
  return {
    ...form.extra,
    name: form.name.trim(),
    aliases: commaList(form.aliases),
    fields: fromRows(form.fields),
    description: form.description.trim(),
    children: form.children.filter((child) => child.text.trim()).map((child) => {
      if (!child.entry) throw new Error(`${child.text.trim()} is not an entry. Choose one from the list.`);
      return { entry: child.entry, ...(child.weight.trim() ? { weight: numberOr(child.weight) } : {}) };
    }),
  };
}

function choices(key) {
  if (key === "Sex") return ["Male", "Female", "Other"].map((name) => ({ name, aliases: [] }));
  const owners = allRecords().filter((record) => (key === "Race" ? record.category === "races" : record.kind === "faction"));
  return owners.map((record) => {
    const form = drafts.get(record.key)?.form;
    return { name: (form ? form.name : record.data?.name ?? "").trim(), aliases: form ? commaList(form.aliases) : record.data?.aliases ?? [] };
  }).filter((option) => option.name);
}

function choice(key, value) {
  const text = String(value).trim().toLowerCase();
  return choices(key).find((option) => [option.name, ...option.aliases].some((name) => name.toLowerCase() === text))?.name ?? "Unknown";
}

const entryKey = (record) => `${record.category}/${record.id}`;

// A label names one entry, so two entries with one name and category also show their IDs.
function entryLabels() {
  const entries = records.filter((record) => record.kind === "entity");
  const plain = (record) => `${title(record)} (${CATEGORY_LABELS[record.category]})`;
  const seen = new Set();
  const repeated = new Set();
  for (const record of entries) (seen.has(plain(record)) ? repeated : seen).add(plain(record));
  return new Map(entries.map((record) => [entryKey(record), repeated.has(plain(record)) ? `${title(record)} (${CATEGORY_LABELS[record.category]}, ${record.id})` : plain(record)]));
}

function entryOf(label) {
  const wanted = label.trim().toLowerCase();
  return [...entryLabels()].find(([, text]) => text.toLowerCase() === wanted)?.[0] ?? "";
}

function savedRecords(loaded) {
  const list = TEMPLATE_PARTS.map((kind) => ({ key: kind, kind, data: loaded[kind] }));
  for (const [id, data] of Object.entries(loaded.factions)) list.push({ key: `faction/${id}`, kind: "faction", id, data });
  for (const [id, data] of Object.entries(loaded.characters)) list.push({ key: `character/${id}`, kind: "character", id, data });
  for (const category of Object.keys(CATEGORY_LABELS)) {
    for (const [id, data] of Object.entries(loaded.entities[category])) list.push({ key: `entity/${category}/${id}`, kind: "entity", category, id, data });
  }
  return list;
}

function canonRecords(loaded) {
  const list = ["overview", "history"].map((kind) => ({ key: kind, kind, data: loaded[kind] }));
  for (const entry of loaded.factions) list.push({ key: `faction/${entry.id}`, kind: "faction", ...entry });
  for (const entry of loaded.characters) list.push({ key: `character/${entry.id}`, kind: "character", ...entry });
  for (const category of Object.keys(CATEGORY_LABELS)) {
    for (const entry of loaded.entities.filter((entity) => entity.category === category)) list.push({ key: `entity/${category}/${entry.id}`, kind: "entity", ...entry });
  }
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
  return (form ? form.name : record.data?.name) || record.id || `New ${kindLabel(record).toLowerCase()}`;
}

function kindLabel(record) {
  return record.kind === "entity" ? CATEGORY_LABELS[record.category] : KIND_LABELS[record.kind];
}

function searchText(record) {
  const form = drafts.get(record.key)?.form;
  return `${title(record)} ${kindLabel(record)} ${record.id ?? ""} ${JSON.stringify(form ?? record.data)}`.toLowerCase();
}

function filterValue(record) {
  if (TEMPLATE_PARTS.includes(record.kind)) return "template";
  return record.kind === "entity" ? record.category : record.kind;
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

function addButton(text, onClick) {
  return el("button", { type: "button", disabled: readOnly(), onclick: () => { onClick(); changed(); renderForm(); } }, text);
}

function removeButton(list, index, label) {
  return deleteButton(label, () => { list.splice(index, 1); changed(); renderForm(); }, readOnly());
}

function factsEditor(list, path, categories) {
  const free = Object.keys(categories).filter((key) => !list.some((row) => row.key === key));
  const add = addButton("Add fact", () => list.push({ key: free[0], value: "", list: categories[free[0]] === "list" }));
  add.disabled ||= free.length === 0;
  return el("fieldset", {},
    el("legend", {}, "Facts"),
    el("p", { className: "hint" }, "Short facts about the entry. Each fact has a predefined type."),
    ...list.map((row, index) => el("div", { className: "inline row" },
      factCategory(row, free, categories),
      control("input", row, "value", [...path, index, "value"], { placeholder: row.list ? "Values, separated by commas" : "Value", label: "Fact value" }),
      removeButton(list, index, "Delete the fact"))),
    add);
}

function factCategory(row, free, categories) {
  const keys = new Set([...Object.keys(categories).filter((key) => key === row.key || free.includes(key)), row.key]);
  const select = el("select", {
    disabled: readOnly(),
    onchange: (event) => {
      row.key = event.target.value;
      row.list = categories[row.key] === "list";
      changed();
      renderForm();
    },
  }, ...[...keys].map((key) => new Option(key[0].toUpperCase() + key.slice(1), key, false, key === row.key)));
  select.setAttribute("aria-label", "Fact type");
  return select;
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
    field("Description", control("textarea", form, "description", [...path, "description"], { rows: 5 }), null, record.is_player ? "What every NPC knows about your squad." : "What NPCs know about the faction."),
    factsEditor(form.fields, [...path, "fields"], FACTS.factions),
  ];
}

function characterForm(form, path, record) {
  return [
    gameIdField(form, path, record, "The string ID of the character's template in the game data, for example 19576-Dialogue.mod. The Forgotten Construction Set (FCS) shows it."),
    ...form.profile.map((row) => (CHOICE_KEYS.includes(row.key)
      ? field(row.key, choiceControl(row, [...path, "profile", row.key]), null, CHOICE_HELP[row.key])
      : field(row.key, control(LONG_PROFILE_KEYS.includes(row.key) ? "textarea" : "input", row, "value", [...path, "profile", row.key], { rows: 4 })))),
    el("fieldset", {},
      el("legend", {}, "Other Details"),
      el("p", { className: "hint" }, "The game and your chats set these details."),
      field("Relation (to you)", relationBar(form.details.Relation), null, "How much the character likes you, from -100 to 100. Your chats with the character change it."),
      field("Original Faction", el("span", {}, form.details.OriginFaction || "Unknown"), null, "The faction that the character comes from.")),
  ];
}

// The labels and thresholds match the relation bar that the game shows (generate_relation_bar in kenshi_llm_server.py).
function relationLabel(value) {
  if (value <= -90) return "ARCH-ENEMY";
  if (value <= -60) return "HOSTILE";
  if (value <= -25) return "UNFRIENDLY";
  if (value >= 90) return "SOUL-MATE";
  if (value >= 60) return "ALLIED";
  if (value >= 25) return "FRIENDLY";
  return "NEUTRAL";
}

function relationBar(stored) {
  const value = Math.max(-100, Math.min(100, Math.trunc(Number(stored)) || 0));
  const text = `${relationLabel(value)} (${value >= 0 ? "+" : ""}${value} pts)`;
  const bar = el("div", { className: "relation-bar" },
    el("span", { className: "relation-track" }, el("span", { className: "relation-marker", style: `left: ${(value + 100) / 2}%` })),
    el("span", {}, text));
  for (const [name, attribute] of Object.entries({ role: "meter", "aria-label": "Relation to you", "aria-valuemin": -100, "aria-valuemax": 100, "aria-valuenow": value, "aria-valuetext": text })) bar.setAttribute(name, attribute);
  return bar;
}

function choiceControl(row, path) {
  const select = control("select", row, "value", path);
  const names = [...new Set(choices(row.key).map((option) => option.name))].sort((a, b) => a.localeCompare(b));
  select.append(...["Unknown", ...names].map((name) => new Option(name, name)));
  select.value = choice(row.key, row.value);
  return select;
}

function relationEntry(child, path, open) {
  const input = el("input", {
    value: child.text,
    placeholder: "Type to search",
    disabled: readOnly(),
    oninput: (event) => {
      child.text = event.target.value;
      child.entry = entryOf(child.text);
      open.disabled = !child.entry;
      setFieldError(event.target, child.text.trim() && !child.entry ? "Choose an entry from the list." : "");
      changed();
    },
  });
  input.dataset.field = JSON.stringify(path);
  input.setAttribute("aria-label", "Related entry");
  input.setAttribute("list", "relation-entries");
  return input;
}

function openEntry(key) {
  selected = records.find((record) => record.kind === "entity" && entryKey(record) === key).key;
  renderList();
  renderForm();
}

async function deleteRelation(form, index, record) {
  const { text } = form.children[index];
  if (text.trim() && !(await ask("Delete the relation", "Delete", `This deletes the relation between ${title(record)} and ${text}. The delete takes effect when you save.`))) return;
  form.children.splice(index, 1);
  changed();
  renderForm();
}

function relationsEditor(form, path, record) {
  const labels = entryLabels();
  const self = record.id ? entryKey(record) : null;
  const parents = records.filter((entry) => entry.kind === "entity").flatMap((entry) =>
    (drafts.get(entry.key)?.form.children ?? entry.data.children ?? []).filter((child) => child.entry === self).map((child) => ({ entry, weight: child.weight })));
  return el("fieldset", {},
    el("legend", {}, "Relations"),
    el("p", { className: "hint" }, "The entries that belong to this one, and the entries that it belongs to."),
    el("div", { className: "relation-grid" },
      withHelp("Entry", "The race, location, or region on the other side of the relation. Type to search, then choose one from the list."),
      withHelp("Relationship", "Child: the entry belongs to this one, for example a town in its region. Parent: this one belongs to the entry. Open the parent to change that relation."),
      withHelp("Weight", "How strong the relation is. A higher number marks a closer link. Empty counts as 1."),
      el("span"),
      ...form.children.flatMap((child, index) => {
        const open = el("button", { type: "button", disabled: !labels.has(child.entry), onclick: () => openEntry(child.entry) }, "Open");
        return [
          relationEntry(child, [...path, "children", index, "entry"], open),
          el("span", {}, "Child"),
          control("input", child, "weight", [...path, "children", index, "weight"], { placeholder: "1", inputMode: "decimal", label: "Relation weight" }),
          el("span", { className: "inline" }, open, deleteButton("Delete the relation", () => deleteRelation(form, index, record), readOnly())),
        ];
      }),
      ...parents.flatMap(({ entry, weight }) => [
        el("span", {}, labels.get(entryKey(entry))),
        el("span", {}, "Parent"),
        el("span", {}, weight === undefined || weight === "" ? "1" : String(weight)),
        el("button", { type: "button", onclick: () => openEntry(entryKey(entry)) }, "Open"),
      ])),
    el("datalist", { id: "relation-entries" }, ...[...labels].filter(([key]) => key !== self).map(([, text]) => el("option", { value: text }))),
    addButton("Add child", () => form.children.push({ entry: "", text: "", weight: "" })));
}

function entityForm(form, path, record) {
  return [
    field("Name", control("input", form, "name", [...path, "name"]), null, "The name that NPCs use for it."),
    field("Aliases", control("input", form, "aliases", [...path, "aliases"]), null, "Other names of the entry, separated by commas."),
    field("Description", control("textarea", form, "description", [...path, "description"], { rows: 5 }), null, `What NPCs know about the ${CATEGORY_LABELS[record.category].toLowerCase()}.`),
    factsEditor(form.fields, [...path, "fields"], FACTS[record.category]),
    relationsEditor(form, path, record),
  ];
}

function historyForm(form, path) {
  return [
    el("p", { className: "hint" }, "The timeline of the world, oldest first."),
    ...form.entries.map((entry, index) => el("div", { className: "card" },
      el("div", { className: "inline row" },
        control("input", entry, "title", [...path, index, "title"], { placeholder: "Title, for example The Second Empire", label: "Title" }),
        removeButton(form.entries, index, "Delete the history entry")),
      control("textarea", entry, "text", [...path, index, "text"], { rows: 4, label: "Text" }))),
    addButton("Add history entry", () => form.entries.push({ title: "", text: "" })),
  ];
}

function manifestForm(form) {
  return [
    field("Name", control("input", form, "name", ["manifest", "name"]), null, "The name of the template that players see."),
    field("Description", control("textarea", form, "description", ["manifest", "description"], { rows: 2 }), null, "A short text that players see when they choose the template, for example the mods that it supports."),
    field("Version", control("input", form, "version", ["manifest", "version"]), null, "Your version of the template, for example 1.0.0."),
    field("Authors", control("input", form, "authors", ["manifest", "authors"]), null, "The authors of the template, separated by commas."),
    field("Credits", control("textarea", form, "credits", ["manifest", "credits"], { rows: 3 }), null, "One credit line on each line. Keep the credits of the template that you copied."),
  ];
}

function recordPath(record) {
  if (record.kind === "faction") return ["factions", record.id ?? "new"];
  if (record.kind === "character") return ["characters", record.id ?? "new"];
  if (record.kind === "entity") return [record.category, record.id ?? "new"];
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
  else body = entityForm(form, path, record);
  // The game reports the player's faction again, so a delete would only lose its description
  const deletable = !TEMPLATE_PARTS.includes(record.kind) && !record.is_player;
  container.replaceChildren(el("div", { className: "card" },
    el("div", { className: "card-head" },
      el("span", {}, el("strong", { className: "name" }, title(record)), " ", el("span", { className: "badge" }, kindLabel(record)),
        record.is_player ? el("span", { className: "badge ok" }, "Your faction") : null,
        ORIGIN_LABELS[record.origin] ? el("span", { className: "badge" }, ORIGIN_LABELS[record.origin]) : null),
      deletable ? deleteButton(`Delete ${title(record)}`, () => deleteRecord(record), readOnly()) : null),
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
  const shown = allRecords().filter((record) => (showSeeded || record.origin !== "seed") && (kindFilter === "all" || filterValue(record) === kindFilter) && (!needle || searchText(record).includes(needle)));
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
  if (shown.length === 0) list.append(el("p", { className: "hint" }, "No results."));
}

function filterSelect() {
  const options = [["all", "Everything"], ["template", source === "template" ? "Template info, overview, history" : "Overview, history"], ["faction", "Factions"], ["character", "Characters"], ...Object.entries(CATEGORY_LABELS).map(([category, label]) => [category, `${label}s`])];
  const select = el("select", { onchange: (event) => { kindFilter = event.target.value; renderList(); } }, ...options.map(([value, text]) => new Option(text, value, false, value === kindFilter)));
  select.setAttribute("aria-label", "Show only");
  return select;
}

function seededSwitch() {
  const toggle = el("button", {
    type: "button",
    className: "switch",
    title: "Entries that the campaign copied from its template when you created it.",
    onclick: () => {
      showSeeded = !showSeeded;
      try {
        localStorage.setItem("showSeeded", String(showSeeded));
      } catch {
        // Storage can be blocked, for example in a private window; the switch then lasts until the page reloads.
      }
      toggle.setAttribute("aria-checked", String(showSeeded));
      renderList();
    },
  }, el("span", { className: "track" }), "Show seeded data");
  toggle.setAttribute("role", "switch");
  toggle.setAttribute("aria-checked", String(showSeeded));
  return toggle;
}

function newRecordForm() {
  if (readOnly()) return null;
  const kind = el("select", { onchange: (event) => { creation.kind = event.target.value; } },
    ...["faction", "character", ...Object.keys(CATEGORY_LABELS)].map((value) => new Option(KIND_LABELS[value] ?? CATEGORY_LABELS[value], value, false, value === creation.kind)));
  kind.setAttribute("aria-label", "Kind of the new entry");
  const name = el("input", { value: creation.name, placeholder: "Name", required: true, oninput: (event) => { creation.name = event.target.value; } });
  name.setAttribute("aria-label", "Name of the new entry");
  return el("form", { className: "new-record", onsubmit: addRecord },
    el("strong", {}, "New entry"),
    kind,
    name,
    el("button", { type: "submit" }, "Add"));
}

function addRecord(event) {
  event.preventDefault();
  const name = creation.name.trim();
  if (!name) return;
  const category = CATEGORY_LABELS[creation.kind] ? creation.kind : undefined;
  const kind = category ? "entity" : creation.kind;
  const key = `new:${++newCount}`;
  const data = kind === "character" ? { profile: { Name: name } } : { name };
  drafts.set(key, { isNew: true, key, kind, category, data, form: toForm(kind, data) });
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
  if (!(await ask(`Delete ${title(record)}`, "Delete", deleteEffect(record), "\n\n", el("b", { className: "warning" }, "The delete takes effect immediately.")))) return;
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

const discardChanges = async (action) => changedRecords().length === 0 || ask("Discard the changes", "Discard", `Your changes to ${templateTitle()} are not saved. ${action} and lose them?`);

async function chooseTemplate(name) {
  if (!(await discardChanges(`Open ${name}`))) {
    render();
    return;
  }
  await openTemplate(name);
}

async function openTemplate(name) {
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
  const name = duplication.name.trim();
  if (!(await discardChanges(`Duplicate ${templateTitle()}`))) return;
  const steps = progress("Duplicating the template", `Copying ${templateTitle()} as ${name}`, "Opening the template");
  try {
    const reply = await sendJson("POST", `/api/templates/${encodeURIComponent(current)}/duplicate`, { new_name: name });
    steps.next();
    duplication.name = "";
    await fetchTemplates();
    await openTemplate(reply.name);
    steps.close();
    showMessage(message, `Created ${reply.name}. You can edit it now.`);
  } catch (error) {
    steps.close();
    showMessage(message, `Duplicate failed: ${error.message}`, true);
  }
}

async function exportTemplate() {
  try {
    const data = await getJson(`/api/templates/${encodeURIComponent(current)}/export`);
    const url = URL.createObjectURL(new Blob([`${JSON.stringify(data, null, 2)}\n`], { type: "application/json" }));
    el("a", { href: url, download: `${current}.json` }).click();
    setTimeout(() => URL.revokeObjectURL(url));
  } catch (error) {
    showMessage(message, `Export failed: ${error.message}`, true);
  }
}

async function readTemplateFile(input) {
  const file = input.files[0];
  try {
    return JSON.parse(await file.text());
  } catch {
    throw new Error(`SSR cannot read ${file?.name ?? "the file"}. Choose a file that the Export button saved.`);
  }
}

async function prefillImportName(event, nameInput) {
  const data = await readTemplateFile(event.target).catch(() => null);
  importing.name = typeof data?.manifest?.name === "string" ? data.manifest.name : "";
  nameInput.value = importing.name;
  checkNewName(nameInput);
}

// A name that matches the title of another template would show twice in the template list.
function checkNewName(input) {
  const key = input.value.trim().toLowerCase();
  const text = templates.some((entry) => [entry.name, entry.title].some((name) => String(name).toLowerCase() === key)) ? `A template named ${input.value.trim()} already exists. Choose another name.` : "";
  input.setCustomValidity(text);
  setFieldError(input, text);
  return input;
}

async function importTemplate(event) {
  event.preventDefault();
  let data;
  try {
    data = await readTemplateFile(event.target.elements.file);
  } catch (error) {
    showMessage(message, `Import failed: ${error.message}`, true);
    return;
  }
  const manifest = data?.manifest ?? {};
  const names = (value) => (Array.isArray(value) && value.length > 0 ? value.join(", ") : "none");
  const name = importing.name.trim();
  if (!(await ask(`Import ${name}`, "Import", `Authors: ${names(manifest.authors)}\nCredits: ${names(manifest.credits)}`))) return;
  if (!(await discardChanges(`Import ${name}`))) return;
  const entries = ["factions", "characters", ...Object.keys(CATEGORY_LABELS)].reduce((sum, key) => sum + Object.keys(data?.[key] ?? {}).length, 0);
  const steps = progress("Importing the template", `Checking and saving ${name} (${entries} entries)`, "Opening the template");
  try {
    const reply = await sendJson("POST", "/api/templates/import", { name, template: data });
    steps.next();
    importing.name = "";
    await fetchTemplates();
    await openTemplate(reply.name);
    steps.close();
    showMessage(message, `Imported ${reply.name}. You can edit it now.`);
  } catch (error) {
    steps.close();
    const problems = error.fieldErrors?.map((problem) => problem.message) ?? [];
    if (problems.length <= 1) {
      showMessage(message, `Import failed: ${error.message}`, true);
      return;
    }
    showMessage(message, `Import failed: the file has ${problems.length} problems.`, true);
    const shown = problems.slice(0, IMPORT_PROBLEMS_SHOWN).map((problem) => `• ${problem}`);
    if (problems.length > shown.length) shown.push(`…and ${problems.length - shown.length} more.`);
    tell("Import failed", `SSR did not import the file, because it has these problems:\n\n${shown.join("\n")}`);
  }
}

async function deleteTemplate() {
  if (!(await ask(`Delete ${templateTitle()}`, "Delete", "This deletes the template and all its entries. Campaigns that you made from it keep their copy. ",
    "\n\n", el("b", { className: "warning" }, "The delete takes effect immediately and is irreversible!")))) return;
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
    ...templates.map((entry) => new Option(entry.title, entry.name, false, entry.name === current)));
  select.setAttribute("aria-label", "World template");
  const recordCounts = template ? counts() : "";
  const duplicateName = checkNewName(el("input", { value: duplication.name, placeholder: "Name of the copy", required: true, oninput: (event) => { duplication.name = checkNewName(event.target).value; } }));
  duplicateName.setAttribute("aria-label", "Name of the copy");
  const importName = checkNewName(el("input", { value: importing.name, placeholder: "Name of the imported template", required: true, oninput: (event) => { importing.name = checkNewName(event.target).value; } }));
  importName.setAttribute("aria-label", "Name of the imported template");
  const importFile = el("input", { type: "file", name: "file", accept: ".json,application/json", required: true, onchange: (event) => prefillImportName(event, importName) });
  importFile.setAttribute("aria-label", "Template file to import");
  return el("fieldset", {},
    el("legend", {}, "World template"),
    el("p", { className: "hint" }, "A new campaign starts as a copy of its template, so changes here apply only to campaigns that you create later."),
    field("Template", select, el("span", { className: "detail" }, recordCounts)),
    template?.manifest?.description ? el("p", { className: "hint" }, template.manifest.description) : null,
    template?.builtin ? el("p", { className: "hint" }, `${templateTitle()} ships with SSR and is read-only. Duplicate it to make your own copy.`) : null,
    ...(template?.errors ?? []).map((error) => el("p", { className: "hint error" }, error.message)),
    ...(template?.warnings ?? []).map((warning) => el("p", { className: "hint" }, warning.message)),
    el("form", { className: "add", onsubmit: duplicateTemplate }, duplicateName, el("button", { type: "submit" }, "Duplicate"),
      template && !template.builtin ? deleteButton(`Delete the template ${templateTitle()}`, deleteTemplate) : null,
      template ? el("button", { type: "button", onclick: exportTemplate }, "Export") : null),
    el("form", { className: "add", onsubmit: importTemplate }, importFile, importName, el("button", { type: "submit" }, "Import")));
}

function counts() {
  const tally = (value, noun) => `${records.filter((record) => filterValue(record) === value).length} ${noun}`;
  return [tally("faction", "factions"), tally("character", "characters"), ...Object.entries(CATEGORY_LABELS).map(([category, label]) => tally(category, `${label.toLowerCase()}s`))].join(", ");
}

function renderCanonBar() {
  return el("fieldset", {},
    el("legend", {}, canon ? `Campaign canon: ${canon.name}` : "Campaign canon"),
    el("p", { className: "hint" }, "Changes here apply only to the current campaign, from the next chat on."),
    refusal ? el("p", { className: "hint error" }, refusal) : null,
    canon ? el("p", { className: "detail" }, counts()) : null);
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
      el("div", { className: "record-panel" }, source === "campaign" ? seededSwitch() : null, search, filterSelect(), el("div", { id: "record-list", className: "record-list" }), newRecordForm()),
      el("div", { id: "record-form" })) : el("p", { className: "hint" }, source === "template" ? "No template to edit." : "Open a campaign to edit its canon."));
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
