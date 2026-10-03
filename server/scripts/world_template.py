"""World templates: folders of JSON and text that describe a world, which each new campaign copies.

The shipped templates in server/world_templates/ are read-only, because an update replaces them. The player's
templates are in server/user/world_templates/. Only this module writes a template, and it validates the whole
template before each write, so a template that a campaign cannot load never reaches the disk.
"""

import hashlib
import json
import os
import re
import shutil
import tempfile

FORMAT_VERSION = 1
MANIFEST = "manifest.json"
OVERVIEW = "overview.txt"
HISTORY = "history.json"
RECORD_FOLDERS = {"faction": "factions", "character": "characters"}
CATEGORIES = ("races", "locations", "regions")
FACTS = {
    "factions": {"leader": str, "capital": str, "founder": str, "nobles": list, "bases": list, "territory": list, "allies": list, "enemies": list},
    "races": {"type": str, "homeland": str, "faction": str},
    "locations": {"type": str, "zone": list, "owner": list},
    "regions": {"animals": list, "factions": list, "hazards": list},
}
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9 _-]*")
_ID = re.compile(r"[A-Za-z0-9_-]+")


class TemplateError(Exception):
    """errors holds one {"field": path, "message": text} per problem, the shape that the web app marks."""

    def __init__(self, errors):
        super().__init__(" ".join(error["message"] for error in errors))
        self.errors = errors


def listing(shipped_dir, user_dir):
    """Opens only the manifests: a full load of each template opens every record file, which took seconds on a mounted drive."""
    result = []
    for name, builtin in _names(shipped_dir, user_dir):
        path = os.path.join(shipped_dir if builtin else user_dir, name)
        manifest = _read_json(path, MANIFEST, {}, [])
        result.append({
            "name": name,
            "builtin": builtin,
            "title": manifest.get("name") or name,
            "description": manifest.get("description", ""),
            "counts": {"factions": len(_record_ids(path, "factions")), "characters": len(_record_ids(path, "characters")), "entities": sum(len(_record_ids(path, category)) for category in CATEGORIES)},
        })
    return result


def load(name, shipped_dir, user_dir):
    """The whole template. A file that does not parse is left out and named in "errors", like a folder that is not a part of a template."""
    path, builtin = _folder(name, shipped_dir, user_dir)
    errors = []
    template = {
        "name": name,
        "builtin": builtin,
        "manifest": _read_json(path, MANIFEST, {}, errors),
        "overview": _read_text(os.path.join(path, OVERVIEW)),
        "history": _read_json(path, HISTORY, [], errors),
        "factions": _read_records(path, "factions", errors),
        "characters": _read_records(path, "characters", errors),
        "entities": {category: _read_records(path, category, errors) for category in CATEGORIES},
    }
    for folder in sorted(os.listdir(path)):
        if os.path.isdir(os.path.join(path, folder)) and folder not in (*RECORD_FOLDERS.values(), *CATEGORIES):
            errors.append({"field": [folder], "message": f"{folder}/ is not a part of a template. Put each entry in factions/, characters/, races/, locations/, or regions/."})
    template["errors"] = errors
    return template


def validate(template):
    """Returns (errors, warnings). An error stops a save and a campaign creation; a warning does not."""
    errors = list(template.get("errors", []))
    warnings = []

    def error(field, message):
        errors.append({"field": field, "message": message})

    manifest = template["manifest"]
    if not isinstance(manifest, dict):
        error(["manifest"], f"{MANIFEST} must hold a JSON object.")
        manifest = {}
    if manifest.get("format_version") != FORMAT_VERSION:
        error(["manifest", "format_version"], "This template was made for another version of SSR, so this version cannot read it.")
    if not _is_text(manifest.get("name")):
        error(["manifest", "name"], "Give the template a name.")
    if "description" in manifest and not isinstance(manifest["description"], str):
        error(["manifest", "description"], "The description must be text.")
    if "version" in manifest and not isinstance(manifest["version"], str):
        error(["manifest", "version"], 'The template version must be in quotes, for example "1.0.0".')
    for key in ("authors", "credits"):
        if key in manifest and not _is_text_list(manifest[key]):
            error(["manifest", key], f"The {key} must be a list of names.")

    if not isinstance(template["overview"], str):
        error(["overview"], "The overview must be text.")
    _check_history(template["history"], error)

    game_ids = {}
    for record_id, faction in template["factions"].items():
        _check_faction(faction, ["factions", record_id], game_ids, error)

    game_ids = {}
    for record_id, character in template["characters"].items():
        _check_character(character, ["characters", record_id], game_ids, error)

    entries = {f"{category}/{record_id}" for category, records in template["entities"].items() for record_id in records}
    for category, records in template["entities"].items():
        for record_id, entity in records.items():
            _check_entity(entity, [category, record_id], entries, error, warnings)
    return errors, warnings


def record_problems(kind, data, field, entries=frozenset()):
    """The (errors, warnings) of one record outside a template, for example its copy in a campaign.

    entries holds the "<category>/<id>" of each race, location, and region that a child may point to.
    """
    errors, warnings = [], []

    def error(path, message):
        errors.append({"field": path, "message": message})

    if kind == "overview":
        if not isinstance(data, str):
            error(field, "The overview must be text.")
    elif kind == "history":
        _check_history(data, error)
    elif kind == "faction":
        _check_faction(data, field, {}, error)
    elif kind == "character":
        _check_character(data, field, {}, error)
    elif kind == "entity":
        _check_entity(data, field, entries, error, warnings)
    else:
        error(["kind"], f"{kind} is not a kind of record.")
    return errors, warnings


def campaign_seed(name, shipped_dir, user_dir):
    """The parts of a template that a new campaign copies. Raises TemplateError if the template has an error."""
    template = load(name, shipped_dir, user_dir)
    errors, _ = validate(template)
    if errors:
        raise TemplateError(errors)
    path, _ = _folder(name, shipped_dir, user_dir)
    return {
        "template": {"name": name, "version": template["manifest"].get("version", ""), "hash": _content_hash(path)},
        "overview": template["overview"],
        "factions": [
            {
                "faction_id": faction["game_id"],
                "name": faction["name"],
                "aliases": faction.get("aliases", []),
                "major": faction.get("major", False),
                "fields": faction.get("fields", {}),
                "description": faction.get("description", ""),
            }
            for faction in template["factions"].values()
        ],
        "history": template["history"],
        "characters": [{"game_id": character["game_id"], "profile": character["profile"]} for character in template["characters"].values()],
        "entities": [{"category": category, "id": record_id, "data": entity} for category, records in template["entities"].items() for record_id, entity in records.items()],
    }


def save_record(name, kind, record_id, data, shipped_dir, user_dir, category=None):
    """Writes one record of a user template and returns (record_id, warnings).

    kind is manifest, overview, history, faction, character, or entity. A faction, character, or entity with no
    record_id is new, and its ID comes from its name.
    """
    template = _editable(name, shipped_dir, user_dir)
    path, _ = _folder(name, shipped_dir, user_dir)
    if kind in ("manifest", "overview", "history"):
        template[kind] = data
        file_path, text = os.path.join(path, {"manifest": MANIFEST, "overview": OVERVIEW, "history": HISTORY}[kind]), data
    else:
        records, folder = _records(template, kind, category)
        if record_id is None:
            record_id = new_id(data, records)
        elif not _ID.fullmatch(str(record_id)):
            raise TemplateError([{"field": [kind], "message": "An ID may hold only letters, digits, _ and -."}])
        records[record_id] = data
        file_path, text = os.path.join(path, folder, f"{record_id}.json"), data
    errors, warnings = validate(template)
    if errors:
        raise TemplateError(errors)
    _write(file_path, text if isinstance(text, str) else json.dumps(text, indent=2, ensure_ascii=False) + "\n")
    return record_id, warnings


def delete_record(name, kind, record_id, shipped_dir, user_dir, category=None):
    template = _editable(name, shipped_dir, user_dir)
    path, _ = _folder(name, shipped_dir, user_dir)
    records, folder = _records(template, kind, category)
    if record_id not in records:
        raise TemplateError([{"field": [kind], "message": f"{record_id} is not in {name}."}])
    os.remove(os.path.join(path, folder, f"{record_id}.json"))


def duplicate(name, new_name, shipped_dir, user_dir):
    """Copies every file, the credit and licence files included, so a derived template keeps its attribution."""
    path, _ = _folder(name, shipped_dir, user_dir)
    new_name = _check_new_name(new_name, shipped_dir, user_dir)
    files = {}
    for root, _, file_names in os.walk(path):
        for file_name in file_names:
            with open(os.path.join(root, file_name), "rb") as f:
                files[os.path.relpath(os.path.join(root, file_name), path)] = f.read()
    manifest = _read_json(path, MANIFEST, {}, [])
    if isinstance(manifest, dict):
        files[MANIFEST] = json.dumps(dict(manifest, name=new_name), indent=2, ensure_ascii=False) + "\n"
    _write_new_template(user_dir, new_name, files)
    return new_name


def export_template(name, shipped_dir, user_dir):
    """The whole template as one JSON object: the file that players share, which import_template reads."""
    template = load(name, shipped_dir, user_dir)
    return {**{key: template[key] for key in ("manifest", "overview", "history", "factions", "characters")}, **template["entities"]}


def import_template(data, new_name, shipped_dir, user_dir):
    """Writes the object of export_template as the user template new_name.

    The file can come from another player, so each record ID must match _ID before it becomes a file name, and nothing
    reaches the disk before the whole template passes the validator and _unknown_keys.
    """
    if not isinstance(data, dict) or not isinstance(data.get("manifest"), dict):
        raise TemplateError([{"field": [], "message": "This file is not an SSR world template. Choose a file that the Export button saved."}])
    record_keys = ("factions", "characters", *CATEGORIES)
    errors = [{"field": [key], "message": f"SSR does not use the section {key}. Check the spelling, or remove it."} for key in data if key not in ("manifest", "overview", "history", *record_keys)]
    for key in record_keys:
        records = data.get(key, {})
        if not isinstance(records, dict):
            errors.append({"field": [key], "message": f"The section {key} must list each entry under its ID."})
            continue
        seen = {}
        for record_id in records:
            other = seen.setdefault(record_id.lower(), record_id)
            if not _ID.fullmatch(record_id):
                errors.append({"field": [key, record_id], "message": f"The ID {record_id} in {key} is not valid. An ID can hold only letters, digits, _ and -."})
            elif other != record_id:
                # Windows file names ignore case, so the second entry would overwrite the first
                errors.append({"field": [key, record_id], "message": f"The IDs {other} and {record_id} in {key} differ only in capital letters, so SSR cannot keep both. Give one of them another ID."})
    if errors:
        raise TemplateError(errors)
    new_name = _check_new_name(new_name, shipped_dir, user_dir)
    manifest = data.get("manifest", {})
    if isinstance(manifest, dict):
        manifest = dict(manifest, name=new_name)
    template = {
        "manifest": manifest,
        "overview": data.get("overview", ""),
        "history": data.get("history", []),
        "factions": data.get("factions", {}),
        "characters": data.get("characters", {}),
        "entities": {category: data.get(category, {}) for category in CATEGORIES},
    }
    errors, _ = validate(template)
    errors = [dict(error, message=f"{_place(data, error['field'])}: {error['message']}") if error["field"][0] in record_keys else error for error in errors]
    errors += _unknown_keys(data)
    if errors:
        raise TemplateError(errors)
    files = {MANIFEST: manifest, OVERVIEW: template["overview"], HISTORY: template["history"]}
    for key in record_keys:
        files.update({os.path.join(key, f"{record_id}.json"): record for record_id, record in data.get(key, {}).items()})
    _write_new_template(user_dir, new_name, {relative: content if isinstance(content, str) else json.dumps(content, indent=2, ensure_ascii=False) + "\n" for relative, content in files.items()})
    return new_name


def _write_new_template(user_dir, name, files):
    """Writes files, a map of relative path to text or bytes, as the user template name.

    The files go into a staging folder that is renamed only when it is complete, so a failure leaves no half-written
    template. That makes the temporary file of _write unnecessary, which matters on a mounted drive, where each file
    operation took about 5 ms and a template has hundreds of files.
    """
    os.makedirs(user_dir, exist_ok=True)
    # The dot keeps a folder that a crash leaves behind out of the template list
    staging = tempfile.mkdtemp(dir=user_dir, prefix=".new-")
    try:
        for folder in {os.path.dirname(relative) for relative in files} - {""}:
            os.makedirs(os.path.join(staging, folder), exist_ok=True)
        for relative, content in files.items():
            with open(os.path.join(staging, relative), "wb") as f:
                f.write(content if isinstance(content, bytes) else content.encode("utf-8"))
        os.rename(staging, os.path.join(user_dir, name))
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


_FORMAT_KEYS = {
    "manifest": {"format_version", "name", "description", "version", "authors", "credits"},
    "history": {"title", "text"},
    "factions": {"game_id", "name", "aliases", "major", "fields", "description"},
    "characters": {"game_id", "profile"},
    "entity": {"name", "aliases", "fields", "description", "children"},
    "child": {"entry", "weight"},
}


def _unknown_keys(data):
    """The keys of an imported file that the format does not name, such as the typo "descripton", whose text no campaign would read.

    Only an import refuses them, because the editor keeps a key that someone added to a template folder by hand.
    """
    errors = []

    def check(record, kind, field):
        if isinstance(record, dict):
            errors.extend({"field": field + [key], "message": f"{_place(data, field)}: SSR does not use {key}. Check the spelling, or remove it."} for key in record if key not in _FORMAT_KEYS[kind])

    check(data.get("manifest"), "manifest", ["manifest"])
    history = data.get("history")
    for index, entry in enumerate(history if isinstance(history, list) else []):
        check(entry, "history", ["history", index])
    for key in ("factions", "characters", *CATEGORIES):
        for record_id, record in data.get(key, {}).items():
            kind = key if key in _FORMAT_KEYS else "entity"
            check(record, kind, [key, record_id])
            children = record.get("children") if kind == "entity" and isinstance(record, dict) else None
            for index, child in enumerate(children if isinstance(children, list) else []):
                check(child, "child", [key, record_id, "children", index])
    return errors


_KIND_LABELS = {"factions": "faction", "characters": "character", "races": "race", "locations": "location", "regions": "region"}


def _place(data, field):
    """Names the part of an imported file that an error points to, because the editor cannot mark a field of a file."""
    if field[0] == "manifest":
        return "Template info"
    if field[0] == "history":
        return f"History entry {field[1] + 1}"
    record = data[field[0]][field[1]]
    if field[0] == "characters" and isinstance(record, dict):
        record = record.get("profile")
    name = record.get("Name" if field[0] == "characters" else "name") if isinstance(record, dict) else None
    place = f"{name if _is_text(name) else field[1]} ({_KIND_LABELS[field[0]]})"
    return f"{place}, relation {field[3] + 1}" if field[2:3] == ["children"] and len(field) > 3 else place


def delete(name, shipped_dir, user_dir):
    path, builtin = _folder(name, shipped_dir, user_dir)
    if builtin:
        raise TemplateError([{"field": ["name"], "message": f"{name} ships with SSR, so it cannot be deleted."}])
    shutil.rmtree(path)


def _names(shipped_dir, user_dir):
    seen = set()
    result = []
    for root, builtin in ((shipped_dir, True), (user_dir, False)):
        if not os.path.isdir(root):
            continue
        for name in sorted(os.listdir(root)):
            if name not in seen and _NAME.fullmatch(name) and os.path.isfile(os.path.join(root, name, MANIFEST)):
                seen.add(name)
                result.append((name, builtin))
    return result


def _folder(name, shipped_dir, user_dir):
    for template_name, builtin in _names(shipped_dir, user_dir):
        if template_name == name:
            return os.path.join(shipped_dir if builtin else user_dir, name), builtin
    raise TemplateError([{"field": ["name"], "message": f"There is no template named {name}."}])


def _editable(name, shipped_dir, user_dir):
    template = load(name, shipped_dir, user_dir)
    if template["builtin"]:
        raise TemplateError([{"field": ["name"], "message": f"{name} ships with SSR, and an update replaces it. Duplicate it, and edit the copy."}])
    return template


def _records(template, kind, category):
    if kind in RECORD_FOLDERS:
        return template[RECORD_FOLDERS[kind]], RECORD_FOLDERS[kind]
    if kind == "entity":
        if category not in CATEGORIES:
            raise TemplateError([{"field": ["category"], "message": f"{category} is not a category. Use races, locations, or regions."}])
        return template["entities"][category], category
    raise TemplateError([{"field": ["kind"], "message": f"{kind} is not a kind of record."}])


def new_id(data, taken):
    name = data.get("name") or (data.get("profile") or {}).get("Name") if isinstance(data, dict) else None
    base = re.sub(r"[^a-z0-9]+", "_", str(name or "").lower()).strip("_") or "entry"
    record_id = base
    number = 2
    while record_id in taken:
        record_id = f"{base}_{number}"
        number += 1
    return record_id


def _check_new_name(new_name, shipped_dir, user_dir):
    new_name = str(new_name or "").strip()
    if not _NAME.fullmatch(new_name):
        raise TemplateError([{"field": ["new_name"], "message": "A template name may hold only letters, digits, spaces, _ and -."}])
    # The template list shows titles, so a name that matches another template's title would look like that template
    taken = {str(entry[key]).lower() for entry in listing(shipped_dir, user_dir) for key in ("name", "title")}
    if new_name.lower() in taken or os.path.exists(os.path.join(user_dir, new_name)):
        raise TemplateError([{"field": ["new_name"], "message": f"A template named {new_name} already exists. Choose another name."}])
    return new_name


def _read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().replace("\r\n", "\n").strip()
    except FileNotFoundError:
        return ""


def _read_json(folder, relative, default, errors):
    try:
        with open(os.path.join(folder, relative), "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except (OSError, UnicodeDecodeError, ValueError) as e:
        errors.append({"field": [relative.replace(os.sep, "/")], "message": f"{relative.replace(os.sep, '/')} cannot be read: {e}"})
        return default


def _record_ids(folder, relative):
    directory = os.path.join(folder, relative)
    if not os.path.isdir(directory):
        return []
    return [record_id for record_id, extension in map(os.path.splitext, sorted(os.listdir(directory))) if extension == ".json" and _ID.fullmatch(record_id)]


def _read_records(folder, relative, errors):
    records = {}
    for record_id in _record_ids(folder, relative):
        failed = len(errors)
        record = _read_json(folder, os.path.join(relative, record_id + ".json"), None, errors)
        if len(errors) == failed:
            records[record_id] = record
    return records


def _content_hash(path):
    digest = hashlib.sha256()
    for root, dirs, files in os.walk(path):
        dirs.sort()
        for file_name in sorted(files):
            file_path = os.path.join(root, file_name)
            digest.update(os.path.relpath(file_path, path).replace(os.sep, "/").encode("utf-8") + b"\0")
            with open(file_path, "rb") as f:
                digest.update(f.read())
    return digest.hexdigest()


def _check_history(history, error):
    if not isinstance(history, list):
        error(["history"], "The history must be a list of entries.")
        return
    for index, entry in enumerate(history):
        if not isinstance(entry, dict) or not _is_text(entry.get("title")) or not isinstance(entry.get("text"), str):
            error(["history", index], f"History entry {index + 1} needs a title and a text.")


def _check_faction(faction, field, game_ids, error):
    if not _check_object(faction, field, error):
        return
    if not _is_text(faction.get("name")):
        error(field + ["name"], "Give the faction a name.")
    _check_game_id(faction, field, "faction", game_ids, error)
    _check_aliases(faction, field, error)
    if "major" in faction and not isinstance(faction["major"], bool):
        error(field + ["major"], "Major must be true or false.")
    _check_fields(faction.get("fields", {}), "factions", field + ["fields"], error)
    if not isinstance(faction.get("description", ""), str):
        error(field + ["description"], "The description must be text.")


def _check_character(character, field, game_ids, error):
    if not _check_object(character, field, error):
        return
    _check_game_id(character, field, "character", game_ids, error)
    profile = character.get("profile")
    if not isinstance(profile, dict) or not _is_text(profile.get("Name")):
        error(field + ["profile", "Name"], "Give the character a name.")
    elif not all(isinstance(value, (str, int, float)) and not isinstance(value, bool) for value in profile.values()):
        error(field + ["profile"], "Each profile value must be text or a number.")


def _check_entity(entity, field, entries, error, warnings):
    if not _check_object(entity, field, error):
        return
    if not _is_text(entity.get("name")):
        error(field + ["name"], "Give the entry a name.")
    _check_aliases(entity, field, error)
    _check_fields(entity.get("fields", {}), field[0], field + ["fields"], error)
    if not isinstance(entity.get("description", ""), str):
        error(field + ["description"], "The description must be text.")
    children = entity.get("children", [])
    if not isinstance(children, list) or not all(isinstance(child, dict) and _is_text(child.get("entry")) and _is_number(child.get("weight", 1)) for child in children):
        error(field + ["children"], "Each relation needs an entry and a number as its weight.")
    else:
        for child in children:
            if child["entry"] not in entries:
                warnings.append({"field": field + ["children"], "message": f"The relation {child['entry']} of {entity.get('name', field[-1])} names no entry."})


def _check_object(record, field, error):
    if isinstance(record, dict):
        return True
    error(field, "The entry must be a JSON object.")
    return False


def _check_game_id(record, field, kind, seen, error):
    game_id = record.get("game_id")
    if not _is_text(game_id):
        error(field + ["game_id"], f"Give the {kind} its game ID.")
    elif game_id in seen:
        error(field + ["game_id"], f"The {kind}s {seen[game_id]} and {field[-1]} have the same game ID.")
    else:
        seen[game_id] = field[-1]


def _check_aliases(record, field, error):
    if "aliases" in record and not _is_text_list(record["aliases"]):
        error(field + ["aliases"], "The aliases must be a list of names.")


def _check_fields(fields, kind, field, error):
    if not isinstance(fields, dict):
        error(field, "The facts must be an object of categories and values.")
        return
    categories = FACTS[kind]
    for key, value in fields.items():
        if key not in categories:
            error(field, f"{key} is not a fact of a {_KIND_LABELS[kind]}. Choose one of {', '.join(categories)}.")
        elif categories[key] is list and not _is_text_list(value):
            error(field, f"The fact {key} must be a list of text.")
        elif categories[key] is str and not isinstance(value, str):
            error(field, f"The fact {key} must be text.")


def _is_text(value):
    return isinstance(value, str) and value.strip() != ""


def _is_text_list(value):
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _write(path, text):
    """Writes to a temporary file first, so a crash during a save cannot leave a half-written file."""
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(dir=folder, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(temp_path, path)
    except BaseException:
        os.unlink(temp_path)
        raise
