"""The system prompts: the shipped defaults in server/prompts/ and the player's overrides in server/user/prompts/.

An update replaces server/prompts/ but never server/user/, so an override survives it. base_hashes.json
holds the hash of the shipped text that each override was saved against, so the web app can mark an
override whose default changed after the save.
"""

import hashlib
import json
import logging
import os
import re
import tempfile
import threading

HASHES_FILE = "base_hashes.json"
_PLACEHOLDER = re.compile(r"\{(\w+)\}")
# Flask serves each request on its own thread, and a save reads and rewrites base_hashes.json
_lock = threading.Lock()


def placeholders(text):
    return set(_PLACEHOLDER.findall(text))


def render(template, values):
    """Fills each {name} that values holds and leaves every other brace as text, so a stray brace in an edited prompt cannot fail the call."""
    return _PLACEHOLDER.sub(lambda match: str(values[match.group(1)]) if match.group(1) in values else match.group(0), template)


def names(shipped_dir, exclude=()):
    return sorted(name for name in os.listdir(shipped_dir) if name.endswith(".txt") and name not in exclude)


def read(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""
    except (OSError, UnicodeDecodeError) as e:
        logging.warning(f"PROMPT: Cannot read {path}: {e}")
        return ""


def load(name, shipped_dir, user_dir):
    return read(os.path.join(user_dir, name)) or read(os.path.join(shipped_dir, name))


def _hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _hashes(user_dir):
    try:
        with open(os.path.join(user_dir, HASHES_FILE), "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        logging.warning(f"PROMPT: Cannot read {HASHES_FILE}, so each override counts as saved against an unknown default: {e}")
        return {}


def listing(shipped_dir, user_dir, exclude=()):
    """default_changed is None for an override with no stored hash, for example one made by hand."""
    hashes = _hashes(user_dir)
    result = []
    for name in names(shipped_dir, exclude):
        shipped = read(os.path.join(shipped_dir, name))
        override = read(os.path.join(user_dir, name)) or None
        changed = False
        if override is not None:
            changed = hashes[name] != _hash(shipped) if name in hashes else None
        result.append({"name": name, "shipped": shipped, "override": override, "default_changed": changed, "placeholders": sorted(placeholders(shipped))})
    return result


def save(name, text, shipped_dir, user_dir, exclude=()):
    """Returns the warnings of the save. A text equal to the default deletes the override, so the prompt keeps getting later default updates."""
    if name not in names(shipped_dir, exclude):
        raise ValueError(f"{name} is not a prompt.")
    shipped = read(os.path.join(shipped_dir, name))
    text = text.replace("\r\n", "\n").strip()
    unknown = placeholders(text) - placeholders(shipped)
    if unknown:
        raise ValueError(f"{name} uses {_braced(unknown)}, which the default does not fill.")
    is_override = bool(text) and text != shipped
    path = os.path.join(user_dir, name)
    with _lock:
        hashes = _hashes(user_dir)
        if is_override:
            _write(path, text)
            hashes[name] = _hash(shipped)
        else:
            if os.path.exists(path):
                os.remove(path)
            hashes.pop(name, None)
        _write(os.path.join(user_dir, HASHES_FILE), json.dumps(hashes, indent=4))
    missing = placeholders(shipped) - placeholders(text) if is_override else set()
    return [f"{name} leaves out {_braced(missing)}, so the prompt loses that data."] if missing else []


def _braced(keys):
    return ", ".join(f"{{{key}}}" for key in sorted(keys))


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
