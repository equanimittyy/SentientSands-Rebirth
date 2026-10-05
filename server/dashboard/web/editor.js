import { ask, deleteButton, el, field, flashMessage, getJson, icon, iconButton, progress, reportUnsaved, sendJson, setFieldError, showMessage, tell, withHelp } from "./api.js";

const page = document.getElementById("editor-page");
const message = document.getElementById("editor-message");
const PROFILE_KEYS = ["Name", "Race", "Sex", "Faction", "Personality", "Backstory", "SpeechQuirks"];
const LONG_PROFILE_KEYS = ["Personality", "Backstory", "SpeechQuirks"];
const CHOICE_KEYS = ["Race", "Sex", "Faction"];
const PROFILE_HELP = {
  Name: "The name of the character. The game shows this name.",
  Race: "The race of the character.",
  Sex: "The sex of the character.",
  Faction: "The faction that SSR tells the LLM the character belongs to.",
  Personality: "The traits of the character. The LLM plays the character to match them.",
  Backstory: "The past life of the character. It shapes what the character says about where they come from.",
  SpeechQuirks: "How the character tends to talk, for example a catchphrase.",
};
const KIND_LABELS = { manifest: "Template info", overview: "Overview", history: "History", faction: "Faction", character: "Character" };
const CATEGORY_LABELS = { races: "Race", locations: "Location", regions: "Region" };
// Mirrors FACTS in server/store/world_template.py, whose validator refuses any other category.
const FACTS = {
  factions: { leader: "text", capital: "text", founder: "text", nobles: "list", bases: "list", territory: "list", allies: "list", enemies: "list" },
  races: { type: "text", homeland: "text", faction: "text" },
  locations: { type: "text", zone: "list", owner: "list" },
  regions: { animals: "list", factions: "list", hazards: "list" },
};
const TEMPLATE_PARTS = ["manifest", "overview", "history"];
const SOURCES = [["campaign", "Campaign Canon"], ["events", "Campaign Log"], ["template", "Templates"]];
const LOG_VIEWS = [["dialogue", "Dialogue & Memories"], ["events", "Deeds"]];
const ORIGIN_LABELS = { seed: "Seeded", game: "Met in game", campaign: "Added in this campaign" };
// Mirrors campaign_db.PROVISIONAL: the chat count of a provisional profile is also its mark.
const PROVISIONAL = "Interactions";
const IMPORT_PROBLEMS_SHOWN = 10;
const EVENTS_PER_PAGE = 50;
const NOTABLE_KINDS = { kill: "Kill", capture: "Capture" };

let source = "campaign";
let canon = null;
let refusal = "";
let templates = [];
let current = "";
let template = null;
let records = [];
const drafts = new Map();
let log = null;
// A rumor that only Generate Rumor wrote has no ID yet, so its key is new: and the ID of its notable event
let rumorDrafts = {};
let rumorInstructions = {};
let memoryDrafts = {};
const eventView = { query: "", type: "all", page: 1 };
let logView = "dialogue";
const threadView = { query: "", selected: null };
const notes = new Map();
let selected = "overview";
let query = "";
let kindFilter = "all";
const listSwitches = { showSeeded: true, showProvisional: true, playerFactionOnly: false, uniqueOnly: false };
for (const name in listSwitches) {
  try { listSwitches[name] = (localStorage.getItem(name) ?? String(listSwitches[name])) === "true"; } catch {}
}
let newCount = 0;
const creation = { kind: "faction", name: "" };
const duplication = { name: "" };
const importing = { name: "" };

const commaList = (text) => text.split(",").map((item) => item.trim()).filter(Boolean);
const lineList = (text) => text.split("\n").map((item) => item.trim()).filter(Boolean);
const readOnly = () => ({ campaign: !canon, events: !log, template: !template || template.builtin })[source];
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
const changedRumors = () => [
  ...Object.keys(rumorDrafts).filter((key) => key.startsWith("new:")),
  ...(log?.rumors ?? []).filter((rumor) => rumorDrafts[rumor.id].trim() !== rumor.text || rumor.id in rumorInstructions).map((rumor) => String(rumor.id)),
];
const changedMemories = () => (log?.threads ?? []).filter((thread) => thread.memory && memoryDrafts[thread.id].trim() !== thread.memory);
const hasChanges = () => (source === "events" ? [...changedRumors(), ...changedMemories()] : changedRecords()).length > 0;

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

const isProvisional = (record) => source === "campaign" && record.kind === "character" && PROVISIONAL in (record.data?.profile ?? {});
// Mirrors GetNpcId in plugin/game/Context.cpp: the game's unique flag gives the u: prefix, as the deeds read it.
const isUnique = (record) => record.kind === "character" && Boolean(record.id?.startsWith("u:"));

function inPlayerFaction(record) {
  if (record.kind === "faction") return Boolean(record.is_player);
  const player = allRecords().find((faction) => faction.is_player);
  // The Faction of a profile keeps the faction of the first meeting, so it misses a recruit that the game reported
  return record.kind === "character" && Boolean(player) && choice("Faction", record.current_faction || record.data?.profile?.Faction || "") === title(player);
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
  const unsaved = hasChanges();
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
      ? field(row.key, choiceControl(row, [...path, "profile", row.key]), null, PROFILE_HELP[row.key])
      : field(row.key, control(LONG_PROFILE_KEYS.includes(row.key) ? "textarea" : "input", row, "value", [...path, "profile", row.key], { rows: 4 }), null, PROFILE_HELP[row.key]))),
    el("fieldset", {},
      el("legend", {}, "Other Details"),
      el("p", { className: "hint" }, "The game and your chats set these details."),
      field("Relation (to you)", relationBar(form.details.Relation), null, "How much the character likes you, from -100 to 100. Your chats with the character change it."),
      source === "campaign" ? field("Current Faction", el("span", {}, record.current_faction || "Unknown"), null, "The faction that the game reports for the character. It shows after you select the character or talk near it while the game runs.") : null,
      source === "campaign" ? field("Status", el("span", {}, record.status || "Unknown"), null, "How the character was when the game last reported it: Healthy, Injured, Crippled, Unconscious, Dead, or Playing Dead. It shows after you talk to the character or near it while the game runs.") : null,
      field("Original Faction", el("span", {}, form.details.OriginFaction || "Unknown"), null, "The faction that the character comes from."),
      source === "campaign" ? field("Animal", el("span", {}, { 1: "Yes", 0: "No" }[form.details.Animal] ?? "Unknown"), null, "Whether the character is an animal, such as a bonedog or a goat. An animal answers only with an action or a sound, never with words. The game decides it, and a Fishman always counts as an animal.") : null,
      source === "campaign" ? field("Unique", el("span", {}, record.id ? (isUnique(record) ? "Yes" : "No") : "Unknown"), null, "Whether the game marks the character as unique, such as Tinfist, and not generic, such as a Dust Bandit. When your squad kills or captures a unique character, the deed shows on Campaign Log > Deeds.") : null,
      isProvisional(record) ? field("Chats", el("span", {}, chatCount(form.details[PROVISIONAL])), null, "How many times you talked to the character. Its personality, backstory, and speech quirks are rolled, not written. When the count reaches Chats before a bio on the Settings page, the LLM writes its full bio.") : null,
      source === "campaign" ? field("Current Job", el("span", {}, form.details.CurrentJob || "Unknown"), null, "What the character does in the game, for example Guarding a building. It updates each time the character chats or banters.") : null,
      source === "campaign" ? field("Current Location", el("span", {}, form.details.CurrentLocation || "Unknown"), null, "Where the character was when you last talked to it, for example Bar, The Hub, or Wilderness, Vain.") : null,
      source === "campaign" ? field("Known Figures", el("span", {}, record.deeds?.join(", ") || "Unknown"), null, "The known figures that the character killed or captured as a member of your squad. A kill or capture counts for each squad member that attacked the victim.") : null),
  ];
}

function chatCount(count) {
  const threshold = canon.bio_interactions;
  return threshold > 0 ? `${count} of ${threshold} chats` : `${count} chats. The LLM writes the bio only when you ask for it.`;
}

const BIO_CHOICES = { all: "bio", Personality: "personality", Backstory: "backstory", SpeechQuirks: "speech quirks" };

function askBio(record) {
  const dialog = document.getElementById("bio");
  const form = dialog.querySelector("form");
  form.reset();
  dialog.querySelector("p").textContent = title(record);
  dialog.returnValue = "";
  dialog.showModal();
  return new Promise((resolve) => dialog.addEventListener("close", () => {
    resolve(dialog.returnValue === "ok" ? { part: form.elements.part.value, instructions: form.elements.instructions.value } : null);
  }, { once: true }));
}

// The text goes into the form and not into the campaign, so the player reads it before a save keeps it.
async function writeBio(record) {
  const choice = await askBio(record);
  if (!choice) return;
  const form = formOf(record);
  const what = BIO_CHOICES[choice.part];
  const steps = progress(`Writing the ${what} of ${title(record)}`, "Asking the LLM");
  try {
    const { bio } = await sendJson("POST", bioUrl(), {
      ...target(), id: record.id, parts: choice.part === "all" ? LONG_PROFILE_KEYS : [choice.part], instructions: choice.instructions, profile: toData("character", form).profile,
    });
    steps.close();
    for (const row of form.profile) if (row.key in bio) row.value = bio[row.key];
    changed();
    renderForm();
    showMessage(message, `The LLM wrote the ${what} of ${title(record)}. Save to keep it.`);
  } catch (error) {
    steps.close();
    showMessage(message, `Write failed: ${error.message}`, true);
  }
}

const bioButton = (record) => el("button", { type: "button", disabled: readOnly(), onclick: () => writeBio(record) }, icon("bot"), " Generate Bio");

// The labels and thresholds match the relation bar that the game shows (generate_relation_bar in server/core/game.py).
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
  const remove = deletable ? deleteButton(`Delete ${title(record)}`, () => deleteRecord(record), readOnly()) : null;
  container.replaceChildren(el("div", { className: "card" },
    el("div", { className: "card-head" },
      el("span", {}, el("strong", { className: "name" }, title(record)), " ", el("span", { className: "badge" }, kindLabel(record)),
        record.is_player ? el("span", { className: "badge ok" }, "Your faction") : null,
        ORIGIN_LABELS[record.origin] ? el("span", { className: `badge${record.origin === "seed" ? " seed" : ""}` }, ORIGIN_LABELS[record.origin]) : null,
        isProvisional(record) ? el("span", { className: "badge" }, "Provisional") : null),
      record.kind === "character" ? el("span", { className: "card-tools" }, bioButton(record), remove) : remove),
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
  const shown = allRecords().filter((record) => (listSwitches.showSeeded || record.origin !== "seed") && (listSwitches.showProvisional || !isProvisional(record)) && (source !== "campaign" || !listSwitches.playerFactionOnly || inPlayerFaction(record)) && (source !== "campaign" || !listSwitches.uniqueOnly || isUnique(record)) && (kindFilter === "all" || filterValue(record) === kindFilter) && (!needle || searchText(record).includes(needle)));
  list.replaceChildren(...shown.map((record) => {
    const item = el("button", {
      type: "button",
      className: `record${isChanged(record) ? " unsaved" : ""}${notes.get(record.key)?.error ? " failed" : ""}`,
      onclick: () => {
        selected = record.key;
        renderList();
        renderForm();
      },
    }, el("span", { className: "name" }, title(record)), el("span", { className: "detail" }, isProvisional(record) ? "Provisional character" : kindLabel(record)));
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

function listSwitch(name, label, help) {
  const toggle = el("button", {
    type: "button",
    className: "switch",
    title: help,
    onclick: () => {
      listSwitches[name] = !listSwitches[name];
      try {
        localStorage.setItem(name, String(listSwitches[name]));
      } catch {
        // Storage can be blocked, for example in a private window; the switch then lasts until the page reloads.
      }
      toggle.setAttribute("aria-checked", String(listSwitches[name]));
      renderList();
    },
  }, el("span", { className: "track" }), label);
  toggle.setAttribute("role", "switch");
  toggle.setAttribute("aria-checked", String(listSwitches[name]));
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
const bioUrl = () => (source === "template" ? `/api/templates/${encodeURIComponent(current)}/characters/bio` : "/api/campaign/characters/bio");
// A campaign write names the campaign that the page loaded, so the server refuses it after a switch
const target = () => (source === "template" ? {} : { campaign: canon.name });

async function deleteRecord(record) {
  if (!(await ask(`Delete ${title(record)}`, "Delete", deleteEffect(record), "\n\n", el("b", { className: "warning" }, "The delete takes effect immediately and is irreversible.")))) return;
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

const campaignName = () => (source === "events" ? log : canon)?.name;
const sourceTitle = () => (source === "template" ? templateTitle() : `the campaign ${campaignName()}`);

async function chooseSource(value) {
  if (value === source) return;
  const label = SOURCES.find(([key]) => key === value)[1];
  if (hasChanges() && !(await ask("Discard the changes", "Discard", `Your changes to ${sourceTitle()} are not saved. Open ${label} and lose them?`))) return;
  const previous = source;
  source = value;
  selected = "overview";
  query = "";
  kindFilter = "all";
  notes.clear();
  // Save sends the drafts to the URL of the source, so a failed load must not leave them under the other one
  if (!(await reload())) {
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
    flashMessage(message, `Created ${reply.name}. You can edit it now.`);
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
    flashMessage(message, `Imported ${reply.name}. You can edit it now.`);
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
    "\n\n", el("b", { className: "warning" }, "The delete takes effect immediately and is irreversible.")))) return;
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
    template?.builtin ? el("p", { className: "hint error" }, `${templateTitle()} ships with SSR and is read-only. Duplicate it to make your own copy.`) : null,
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

function renderSubtabs(tabs = SOURCES, shown = source, choose = chooseSource) {
  const list = el("div", { className: "subtabs" }, ...tabs.map(([value, text]) => {
    const tab = el("button", { type: "button", onclick: () => choose(value) }, text);
    tab.setAttribute("role", "tab");
    tab.setAttribute("aria-selected", String(value === shown));
    return tab;
  }));
  list.setAttribute("role", "tablist");
  return list;
}

function discardRumor(key) {
  delete rumorDrafts[key];
  delete rumorInstructions[key];
  updateUnsaved();
  render();
}

function askRumor(event, instruction) {
  const dialog = document.getElementById("rumor");
  const form = dialog.querySelector("form");
  form.reset();
  form.elements.instructions.value = instruction;
  dialog.querySelector("p").textContent = event.line;
  dialog.returnValue = "";
  dialog.showModal();
  return new Promise((resolve) => dialog.addEventListener("close", () => resolve(dialog.returnValue === "ok" ? form.elements.instructions.value : null), { once: true }));
}

// The text goes into the row of its deed and not into the campaign, so the player reads it before a save keeps it.
async function writeRumor(event) {
  const key = event.rumor === null ? `new:${event.id}` : String(event.rumor);
  const stored = log.rumors.find((rumor) => rumor.id === event.rumor);
  const instruction = await askRumor(event, rumorInstructions[key] ?? stored?.instruction ?? "");
  if (instruction === null) return;
  const steps = progress("Writing a rumor", "Asking the LLM");
  try {
    const { text } = await sendJson("POST", "/api/campaign/rumors/generate", { campaign: log.name, notable: event.id, instruction, rumor: rumorDrafts[key] ?? "" });
    steps.close();
    rumorDrafts[key] = text;
    rumorInstructions[key] = instruction;
    updateUnsaved();
    render();
    showMessage(message, "The LLM wrote the rumor into the row of its deed. Save to keep it.");
  } catch (error) {
    steps.close();
    showMessage(message, `Write failed: ${error.message}`, true);
  }
}

function rumorCell(event) {
  const key = event.rumor === null ? `new:${event.id}` : String(event.rumor);
  if (!(key in rumorDrafts)) return el("button", { type: "button", onclick: () => writeRumor(event) }, icon("bot"), " Generate Rumor");
  const note = notes.get(`rumor:${key}`);
  const input = control("textarea", rumorDrafts, key, ["rumors", key], { rows: 3, label: "Rumor" });
  if (note?.field) setFieldError(input, note.text);
  const again = iconButton("bot", "Generate the rumor again", () => writeRumor(event));
  const remove = event.rumor === null ? deleteButton("Discard the new rumor", () => discardRumor(key)) : deleteButton("Delete the rumor", () => deleteRumor(event.rumor));
  return el("div", {},
    el("div", { className: "inline row" }, input, again, remove),
    note ? el("p", { className: `hint${note.error ? " error" : ""}` }, note.text) : null);
}

function renderEvents() {
  const deeds = log.notables;
  const counts = new Map();
  for (const event of log.notables) counts.set(event.kind, (counts.get(event.kind) ?? 0) + 1);
  if (!counts.has(eventView.type)) eventView.type = "all";
  const search = el("input", {
    type: "search",
    value: eventView.query,
    placeholder: "Search the deeds",
    oninput: (event) => {
      eventView.query = event.target.value;
      eventView.page = 1;
      renderEventPage();
    },
  });
  search.setAttribute("aria-label", "Search the deeds");
  const options = [...counts].map(([kind, count]) => [kind, `${NOTABLE_KINDS[kind] ?? kind} (${count})`]).sort((a, b) => a[1].localeCompare(b[1]));
  const select = el("select", {
    onchange: (event) => {
      eventView.type = event.target.value;
      eventView.page = 1;
      renderEventPage();
    },
  }, ...[["all", `All kinds (${deeds.length})`], ...options].map(([value, text]) => new Option(text, value, false, value === eventView.type)));
  select.setAttribute("aria-label", "Show only");
  return el("fieldset", {},
    el("legend", {}, `Deeds (${deeds.length})`),
    el("p", { className: "hint" },
      "Each known figure that your squad killed or captured, newest first. A known figure is a character that the game marks as unique, such as Tinfist."),
    el("p", { className: "hint" },
      "SSR writes each rumor after the memories, when you stop chatting for the Conversation timeout. Generate Rumor writes one sooner, and the robot rewrites it with new instructions. NPCs hear the 5 newest."),
    ...(deeds.length > 0 ? [el("div", { className: "inline row" }, search, select), el("div", { id: "event-page" })] : [el("p", { className: "hint" }, "No deeds yet.")]));
}

function pager(shown, pages, start) {
  const turn = (label, number) => el("button", {
    type: "button",
    disabled: number === eventView.page || number < 1 || number > pages,
    onclick: () => {
      eventView.page = number;
      renderEventPage();
    },
  }, label);
  return el("div", { className: "pager" },
    turn("Newest", 1), turn("Newer", eventView.page - 1),
    el("span", {}, `${start + 1}–${Math.min(start + EVENTS_PER_PAGE, shown)} of ${shown}`),
    turn("Older", eventView.page + 1), turn("Oldest", pages));
}

function renderEventPage() {
  const holder = page.querySelector("#event-page");
  if (!holder) return;
  const needle = eventView.query.trim().toLowerCase();
  const shown = log.notables.filter((event) => (eventView.type === "all" || event.kind === eventView.type) && (!needle || event.line.toLowerCase().includes(needle)));
  if (shown.length === 0) {
    holder.replaceChildren(el("p", { className: "hint" }, "No results."));
    return;
  }
  const pages = Math.ceil(shown.length / EVENTS_PER_PAGE);
  eventView.page = Math.min(eventView.page, pages);
  const start = (eventView.page - 1) * EVENTS_PER_PAGE;
  const rows = shown.slice(start, start + EVENTS_PER_PAGE).map((event) => el("tr", {},
    el("td", {}, event.time),
    el("td", {}, el("span", { className: "badge" }, NOTABLE_KINDS[event.kind] ?? event.kind)),
    el("td", {}, event.line),
    el("td", {}, rumorCell(event))));
  const head = el("tr", {}, el("th", {}, "Time"), el("th", {}, "Kind"), el("th", {}, "Deed"), el("th", {}, "Rumor"));
  const table = el("table", { className: "event-table" }, el("thead", {}, head), el("tbody", {}, ...rows));
  holder.replaceChildren(...(pages > 1 ? [pager(shown.length, pages, start), table, pager(shown.length, pages, start)] : [table]));
}

async function deleteRumor(id) {
  if (!(await ask("Delete the rumor", "Delete", "NPCs stop mentioning this rumor. ", "\n\n", el("b", { className: "warning" }, "The delete takes effect immediately and is irreversible.")))) return;
  try {
    await sendJson("POST", "/api/campaign/rumors/delete", { campaign: log.name, id });
    await fetchLog(keptLog());
  } catch (error) {
    showMessage(message, `Delete failed: ${error.message}`, true);
  }
}

const membersAs = (thread, role) => thread.members.filter((member) => member.role === role).map((member) => member.name || "Unknown");
// Thread IDs restart in each campaign, so the selection names the campaign too
const threadKey = (thread) => `${log.name}/${thread.id}`;
const threadText = (thread) => [...thread.members.map((member) => member.name), ...thread.lines, thread.memory ?? ""].join("\n").toLowerCase();

function renderThreads() {
  const search = el("input", {
    type: "search",
    value: threadView.query,
    placeholder: "Search names, dialogue, and memories",
    oninput: (event) => {
      threadView.query = event.target.value;
      renderThreadList();
    },
  });
  search.setAttribute("aria-label", "Search the conversations");
  return [
    el("fieldset", {},
      el("legend", {}, `Dialogue & Memories: ${log.name}`),
      el("p", { className: "hint" }, "Each chat with an NPC, newest first. A conversation ends when you talk to someone else, speak as another squad member, or stop chatting for the Conversation timeout on the Settings page."),
      el("p", { className: "detail" }, `${log.threads.length} conversations`)),
    el("div", { className: "editor-layout" },
      el("div", { className: "record-panel" }, search, el("div", { id: "thread-list", className: "record-list" })),
      el("div", { id: "thread-view" })),
  ];
}

function renderThreadList() {
  const list = page.querySelector("#thread-list");
  if (!list) return;
  const needle = threadView.query.trim().toLowerCase();
  const shown = log.threads.filter((thread) => !needle || threadText(thread).includes(needle));
  list.replaceChildren(...shown.map((thread) => {
    const item = el("button", {
      type: "button",
      className: "record",
      onclick: () => {
        threadView.selected = threadKey(thread);
        renderThreadList();
        renderThread();
      },
    }, el("span", { className: "name" }, membersAs(thread, "speaker").join(" and ")), el("span", { className: "detail" }, thread.time || "Unknown"));
    if (threadKey(thread) === threadView.selected) item.setAttribute("aria-current", "true");
    return item;
  }));
  if (shown.length === 0) list.append(el("p", { className: "hint" }, log.threads.length === 0 ? "No conversations yet." : "No results."));
}

function renderThread() {
  const container = page.querySelector("#thread-view");
  if (!container) return;
  const thread = log.threads.find((entry) => threadKey(entry) === threadView.selected);
  if (!thread) {
    container.replaceChildren(el("p", { className: "hint" }, "Choose a conversation on the left."));
    return;
  }
  const heard = membersAs(thread, "overheard");
  const note = notes.get(`memory:${thread.id}`);
  let memory = null;
  if (thread.memory) {
    const input = control("textarea", memoryDrafts, thread.id, ["memories", thread.id], { className: "tall", label: "Memorised Summary" });
    if (note?.field) setFieldError(input, note.text);
    memory = field("Memorised Summary", el("div", { className: "inline row" }, input, deleteButton("Delete the memory", () => deleteMemory(thread.id))), null,
      "What each NPC of this conversation remembers. Edit it to change their memory.");
  }
  container.replaceChildren(el("div", { className: "card" },
    el("div", { className: "card-head" },
      el("span", {}, el("strong", { className: "name" }, membersAs(thread, "speaker").join(" and ")), " ", el("span", { className: "badge" }, thread.time || "Unknown"))),
    thread.lines.length > 0 ? field("Dialogue", el("textarea", { id: "thread-lines", className: "tall", readOnly: true, value: thread.lines.join("\n") }), null, "What was said, oldest first. The memory replaces it.") : null,
    memory,
    note ? el("p", { className: `hint${note.error ? " error" : ""}` }, note.text) : null,
    el("fieldset", {},
      el("legend", {}, "Involved Characters"),
      el("p", { className: "hint" }, "Each character here remembers the conversation."),
      field("Speakers", el("span", {}, membersAs(thread, "speaker").join(", ")), null, "The squad member who talked and the NPC who replied."),
      field("Listeners (Overheard)", el("span", {}, heard.join(", ") || "Nobody"), null, "The characters near enough to hear the conversation."))));
}

async function deleteMemory(id) {
  if (!(await ask("Delete the memory", "Delete", "The NPCs of this conversation forget it. ", "\n\n", el("b", { className: "warning" }, "The delete takes effect immediately and is irreversible.")))) return;
  try {
    await sendJson("POST", "/api/campaign/memories/delete", { campaign: log.name, id });
    await fetchLog(keptLog());
  } catch (error) {
    showMessage(message, `Delete failed: ${error.message}`, true);
  }
}

function chooseLogView(value) {
  logView = value;
  render();
}

function renderLog() {
  if (log) return [renderSubtabs(LOG_VIEWS, logView, chooseLogView), ...(logView === "events" ? [renderEvents()] : renderThreads())];
  const hint = el("p", { className: "hint" }, "Open a campaign to read its dialogue and deeds, and to edit its rumors.");
  return refusal ? [el("p", { className: "hint error" }, refusal), hint] : [hint];
}

function render() {
  if (source === "events") {
    page.replaceChildren(renderSubtabs(), ...renderLog());
    if (log && logView === "events") renderEventPage();
    if (log && logView === "dialogue") {
      renderThreadList();
      renderThread();
    }
    return;
  }
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
      el("div", { className: "record-panel" }, ...(source === "campaign" ? [
        listSwitch("showSeeded", "Show seeded data", "Entries that the campaign copied from its template when you created it."),
        listSwitch("showProvisional", "Show provisional characters", "Characters you met in game whose full bio the LLM has not written yet."),
        listSwitch("playerFactionOnly", "Player faction only", "Shows only your faction and the characters in it. A character counts by its Current Faction, or by its Faction when no Current Faction shows."),
        listSwitch("uniqueOnly", "Show unique only", "Shows only the characters that the game marks as unique, such as Tinfist."),
      ] : []), search, filterSelect(), el("div", { id: "record-list", className: "record-list" }), newRecordForm()),
      el("div", { id: "record-form" })) : el("p", { className: "hint" }, source === "template" ? "No template to edit." : "Open a campaign to edit its canon."));
  renderList();
  renderForm();
}

async function save() {
  if (readOnly()) {
    flashMessage(message, "No changes to save.");
    return;
  }
  if (source === "events") {
    await saveLog();
    return;
  }
  const changes = changedRecords();
  if (changes.length === 0) {
    flashMessage(message, "No changes to save.");
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
  else flashMessage(message, source === "template" ? "Saved. Campaigns that you create from this template from now on get the changes." : `Saved to the campaign ${canon.name}.`);
}

async function saveLog() {
  const changes = [...changedRumors().map((key) => ["rumors", key]), ...changedMemories().map((thread) => ["memories", thread.id])];
  if (changes.length === 0) {
    flashMessage(message, "No changes to save.");
    return;
  }
  notes.clear();
  const kept = { rumors: {}, instructions: {}, memories: {} };
  for (const [kind, id] of changes) {
    try {
      await sendJson("POST", `/api/campaign/${kind}`, kind === "rumors" ? rumorBody(id) : { campaign: log.name, id, text: memoryDrafts[id] });
    } catch (error) {
      if (kind === "rumors") {
        kept.rumors[id] = rumorDrafts[id];
        if (id in rumorInstructions) kept.instructions[id] = rumorInstructions[id];
      } else kept.memories[id] = memoryDrafts[id];
      notes.set(`${kind === "rumors" ? "rumor" : "memory"}:${id}`, { error: true, text: error.message, field: error.fieldErrors?.[0]?.field });
    }
  }
  const failed = Object.keys(kept.rumors).length + Object.keys(kept.memories).length;
  if (!(await fetchLog(kept))) return;
  if (failed > 0) showMessage(message, `${failed} of ${changes.length} changes were not saved.`, true);
  else flashMessage(message, "Saved.");
}

async function fetchTemplates() {
  ({ templates } = await getJson("/api/templates"));
  if (!templates.some((entry) => entry.name === current)) current = templates[0]?.name ?? "";
}

// A reply with an error status still has fieldErrors; a lost server has none and fails the whole load
async function getCampaign(url) {
  try {
    return [await getJson(url), ""];
  } catch (error) {
    if (!("fieldErrors" in error)) throw error;
    return [null, error.message];
  }
}

const rumorBody = (key) => ({
  campaign: log.name,
  ...(key.startsWith("new:") ? { notable: Number(key.slice(4)) } : { id: Number(key) }),
  text: rumorDrafts[key],
  ...(key in rumorInstructions ? { instruction: rumorInstructions[key] } : {}),
});

const keptLog = () => ({
  rumors: Object.fromEntries(changedRumors().map((key) => [key, rumorDrafts[key]])),
  instructions: { ...rumorInstructions },
  memories: Object.fromEntries(changedMemories().map((thread) => [thread.id, memoryDrafts[thread.id]])),
});

function showLog({ rumors = {}, instructions = {}, memories = {} }) {
  const events = new Map((log?.notables ?? []).map((event) => [`new:${event.id}`, event]));
  // A new rumor whose event got a rumor in the meantime, for example in another tab, becomes a draft of that rumor
  const keyOf = (key) => (events.get(key)?.rumor ?? key).toString();
  const kept = Object.fromEntries(Object.entries(rumors).map(([key, text]) => [keyOf(key), text]));
  rumorDrafts = Object.fromEntries((log?.rumors ?? []).map((rumor) => [rumor.id, kept[rumor.id] ?? rumor.text]));
  for (const [key, text] of Object.entries(kept)) if (events.has(key)) rumorDrafts[key] = text;
  rumorInstructions = Object.fromEntries(Object.entries(instructions).map(([key, text]) => [keyOf(key), text]).filter(([key]) => key in rumorDrafts));
  memoryDrafts = Object.fromEntries((log?.threads ?? []).filter((thread) => thread.memory).map((thread) => [thread.id, memories[thread.id] ?? thread.memory]));
  render();
}

async function fetchLog(kept) {
  try {
    [log, refusal] = await getCampaign("/api/campaign");
  } catch (error) {
    showMessage(message, `Could not load the campaign events: ${error.message}`, true);
    return false;
  }
  showLog(kept);
  updateUnsaved();
  return true;
}

function showRecords(kept, bases = new Map()) {
  const loaded = source === "campaign" ? (canon ? canonRecords(canon) : []) : (template ? savedRecords(template) : []);
  records = [...loaded.map((record) => bases.get(record.key) ?? record), ...[...bases.values()].filter((base) => !loaded.some((record) => record.key === base.key))];
  drafts.clear();
  for (const [key, entry] of kept) drafts.set(key, entry);
  if (!allRecords().some((record) => record.key === selected)) selected = "overview";
  render();
}

// Keeps the drafts that failed to save, so the player can fix them.
async function fetchRecords(kept) {
  try {
    if (source === "campaign") [canon, refusal] = await getCampaign("/api/campaign/canon");
    else {
      if (!current) await fetchTemplates();
      template = current ? (await getJson(`/api/templates/${encodeURIComponent(current)}`)).template : null;
    }
  } catch (error) {
    showMessage(message, `Could not load the ${source === "template" ? "template" : "campaign canon"}: ${error.message}`, true);
    return false;
  }
  showRecords(kept);
  updateUnsaved();
  return true;
}

const showing = () => `${source}/${current}`;

// A switch during the fetch loads the newer subtab or template, so a refresh that sees one leaves the page to it.
async function refreshLog() {
  const opened = showing();
  const fresh = await getCampaign("/api/campaign");
  if (showing() !== opened || JSON.stringify(fresh) === JSON.stringify([log, refusal])) return "current";
  const unsaved = hasChanges();
  // The drafts belong to the campaign that the page loaded
  if (unsaved && fresh[0]?.name !== log?.name) return "kept";
  const kept = keptLog();
  [log, refusal] = fresh;
  const scrolls = ["#thread-list", "#thread-lines"].map((selector) => [selector, page.querySelector(selector)?.scrollTop ?? 0]);
  showLog(kept);
  for (const [selector, scroll] of scrolls) page.querySelector(selector)?.scrollTo(0, scroll);
  if (hasChanges() !== unsaved) updateUnsaved();
  return "loaded";
}

// A changed record keeps the version that the page loaded, so its save still fails as stale when the record changed
// elsewhere, instead of overwriting that change.
async function refreshRecords() {
  const opened = showing();
  let fresh;
  if (source === "campaign") fresh = await getCampaign("/api/campaign/canon");
  else {
    const list = (await getJson("/api/templates")).templates;
    const name = list.some((entry) => entry.name === current) ? current : list[0]?.name ?? "";
    fresh = [list, name, name ? (await getJson(`/api/templates/${encodeURIComponent(name)}`)).template : null];
  }
  const shown = source === "campaign" ? [canon, refusal] : [templates, current, template];
  if (showing() !== opened || JSON.stringify(fresh) === JSON.stringify(shown)) return "current";
  const unsaved = hasChanges();
  if (unsaved && (source === "campaign" ? fresh[0]?.name !== canon?.name : fresh[1] !== current)) return "kept";
  const kept = keptDrafts();
  const bases = new Map(records.filter((record) => kept.has(record.key)).map((record) => [record.key, record]));
  if (source === "campaign") [canon, refusal] = fresh;
  else [templates, current, template] = fresh;
  const scroll = page.querySelector("#record-list")?.scrollTop ?? 0;
  showRecords(kept, bases);
  page.querySelector("#record-list")?.scrollTo(0, scroll);
  if (hasChanges() !== unsaved) updateUnsaved();
  return "loaded";
}

const reload = () => (source === "events" ? fetchLog({}) : fetchRecords(new Map()));

export async function refreshEditor() {
  try {
    if (source === "events") return await refreshLog();
    return await refreshRecords();
  } catch (error) {
    showMessage(message, `Refresh failed: ${error.message}`, true);
  }
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
  return reload();
}

document.getElementById("editor-save").addEventListener("click", save);
document.addEventListener("campaignchange", (event) => {
  if (source === "template" || campaignName() === event.detail) return;
  if (hasChanges()) showMessage(message, `The game switched to the campaign ${event.detail}. Your changes belong to ${campaignName()}, so they cannot be saved. Discard to load ${event.detail}.`, true);
  else reload();
});
