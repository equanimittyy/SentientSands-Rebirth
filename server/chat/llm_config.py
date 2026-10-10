"""The LLM configuration: providers, profiles, the default profile, and the route that each task takes.

The server keeps it in server/config/llm_config.json, which the release does not
ship, so an update keeps the player's API keys. The web app gets it only
through masked(), so a stored API key never leaves the server.
"""

import copy
import json
import os
import tempfile
from urllib.parse import urlparse

TASKS = {
    "chat": {"max_tokens": 2048, "temperature": 0.8},
    "radiant": {"max_tokens": 2048, "temperature": 0.8},
    "profile": {"max_tokens": 1500, "temperature": 0.7},
    "synthesis": {"max_tokens": 2048, "temperature": 0.8},
    "memory": {"max_tokens": 1500, "temperature": 0.3},
    "action": {"max_tokens": 2048, "temperature": 0.8},
}
PROVIDER_TYPES = ("openai", "player2")
# The plugin stops waiting for a reply after 60 s, so a whole fallback chain must end before that
DEFAULT_DEADLINE = 55
DEFAULT_TIMEOUT = 120
# Marks the place of the default profile in a route, so a new default reaches every task without an edit of the routes
DEFAULT_SLOT = None


def _provider_type(name):
    return "player2" if name == "player2" else "openai"


def build(providers, models, first_profile):
    config = {"providers": {}, "profiles": {}, "default_profile": None, "routes": {}}
    for name, provider in providers.items():
        config["providers"][name] = dict(provider, type=_provider_type(name))
    for name, model in models.items():
        if model.get("provider") in config["providers"]:
            config["profiles"][name] = {
                "provider": model["provider"],
                "model": model["model"],
                "timeout": DEFAULT_TIMEOUT,
                "params": {},
            }
    config["default_profile"] = first_profile if first_profile in config["profiles"] else next(iter(config["profiles"]), None)
    for task in TASKS:
        config["routes"][task] = default_route(task)
    return config


def default_route(task):
    return dict(TASKS[task], profiles=[DEFAULT_SLOT], deadline=DEFAULT_DEADLINE)


def route_profiles(config, route):
    return [config["default_profile"] if name is DEFAULT_SLOT else name for name in route["profiles"]]


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _error(field, message):
    return {"field": field, "message": message}


def provider_errors(name, provider):
    where = ["providers", name]
    errors = []
    if not name.strip():
        errors.append(_error(where, "A provider has no name."))
    if provider.get("type") not in PROVIDER_TYPES:
        errors.append(_error(where + ["type"], f"Provider {name}: the type must be one of {', '.join(PROVIDER_TYPES)}."))
    base_url = provider.get("base_url")
    if not isinstance(base_url, str) or urlparse(base_url).scheme not in ("http", "https") or not urlparse(base_url).netloc:
        errors.append(_error(where + ["base_url"], f"Provider {name}: the base URL must be an http:// or https:// address."))
    if not isinstance(provider.get("api_key", ""), str) or not isinstance(provider.get("game_key", ""), str):
        errors.append(_error(where + ["api_key"], f"Provider {name}: the keys must be text."))
    return errors


def profile_errors(name, profile, providers):
    where = ["profiles", name]
    errors = []
    if not name.strip():
        errors.append(_error(where, "A profile has no name."))
    if profile.get("provider") not in providers:
        errors.append(_error(where + ["provider"], f"Profile {name}: the provider {profile.get('provider')} does not exist."))
    if not isinstance(profile.get("model"), str) or not profile["model"].strip():
        errors.append(_error(where + ["model"], f"Profile {name}: the model ID is empty."))
    if not _is_number(profile.get("timeout")) or profile["timeout"] <= 0:
        errors.append(_error(where + ["timeout"], f"Profile {name}: the timeout must be a number above 0."))
    if not isinstance(profile.get("params", {}), dict):
        errors.append(_error(where + ["params"], f"Profile {name}: the extra request parameters must be a JSON object."))
    return errors


def validate(config):
    """Returns one {"field": path, "message": text} per problem, so the web app can mark the field."""
    providers = config.get("providers")
    profiles = config.get("profiles")
    routes = config.get("routes")
    if not all(isinstance(part, dict) for part in (providers, profiles, routes)):
        return [_error([], "The configuration needs providers, profiles, and routes.")]

    errors = []
    for name, provider in providers.items():
        errors += provider_errors(name, provider)
    for name, profile in profiles.items():
        errors += profile_errors(name, profile, providers)
    default = config.get("default_profile")
    if not isinstance(default, str) or default not in profiles:
        errors.append(_error(["default_profile"], "Choose a default profile."))

    for task in TASKS:
        if task not in routes:
            errors.append(_error(["routes", task], f"The {task} task has no route."))
    for task, route in routes.items():
        where = ["routes", task]
        if task not in TASKS:
            errors.append(_error(where, f"{task} is not a task."))
            continue
        chain = route.get("profiles")
        if not isinstance(chain, list):
            errors.append(_error(where + ["profiles"], f"Route {task}: the profiles must be a list."))
        else:
            if chain.count(DEFAULT_SLOT) != 1:
                errors.append(_error(where + ["profiles"], f"Route {task}: the default profile must be in the list once."))
            for index, name in enumerate(chain):
                if name is not DEFAULT_SLOT and name not in profiles:
                    errors.append(_error(where + ["profiles", index], f"Route {task}: the profile {name} does not exist."))
        max_tokens = route.get("max_tokens")
        if not isinstance(max_tokens, int) or isinstance(max_tokens, bool) or max_tokens <= 0:
            errors.append(_error(where + ["max_tokens"], f"Route {task}: max_tokens must be a whole number above 0."))
        if not _is_number(route.get("temperature")) or not 0 <= route["temperature"] <= 2:
            errors.append(_error(where + ["temperature"], f"Route {task}: the temperature must be from 0 to 2."))
        if not _is_number(route.get("deadline")) or route["deadline"] <= 0:
            errors.append(_error(where + ["deadline"], f"Route {task}: the deadline must be a number above 0."))
    return errors


def is_key_set(key):
    # The default providers ship placeholder keys such as YOUR_OPENROUTER_KEY.
    return bool(key) and not key.startswith("YOUR_")


def masked(config):
    result = copy.deepcopy(config)
    for provider in result["providers"].values():
        key = provider.pop("api_key", "")
        provider["api_key_set"] = is_key_set(key)
    return result


def _saved_provider(name, provider, old):
    """A renamed provider names its saved entry in previous_name."""
    return old.get("providers", {}).get(provider.get("previous_name", name), {})


def with_stored_keys(new, old):
    """Keeps the stored API key of each provider that the web app sends with an empty key field."""
    result = copy.deepcopy(new)
    for name, provider in result.get("providers", {}).items():
        provider.pop("api_key_set", None)
        if not provider.get("api_key"):
            provider["api_key"] = _saved_provider(name, provider, old).get("api_key", "")
        provider.pop("previous_name", None)
    return result


def provider_from_form(name, provider, old):
    """Uses the stored key only with the saved base URL, so a request from the form cannot send it to a mistyped host."""
    result = {key: provider[key] for key in ("type", "base_url", "api_key", "game_key") if key in provider}
    saved = _saved_provider(name, provider, old)
    if not result.get("api_key") and saved.get("base_url") == result.get("base_url"):
        result["api_key"] = saved.get("api_key", "")
    return result


def reset(defaults, old):
    """Keeps the stored key of a default provider only on its stored host, so a key for a custom host never reaches the default one. with_stored_keys cannot do this, because the defaults hold placeholder keys, not empty ones."""
    result = copy.deepcopy(defaults)
    for name, provider in result["providers"].items():
        saved = old.get("providers", {}).get(name, {})
        if is_key_set(saved.get("api_key", "")) and urlparse(saved.get("base_url", "")).netloc == urlparse(provider["base_url"]).netloc:
            provider["api_key"] = saved["api_key"]
    return result


def model_ids(listing):
    entries = listing.get("data") if isinstance(listing, dict) else None
    return sorted({entry["id"] for entry in entries or [] if isinstance(entry, dict) and isinstance(entry.get("id"), str)})


def player2_providers_in_use(config):
    names = set()
    for route in config["routes"].values():
        for profile_name in route_profiles(config, route):
            provider_name = config["profiles"].get(profile_name, {}).get("provider")
            if config["providers"].get(provider_name, {}).get("type") == "player2":
                names.add(provider_name)
    return sorted(names)


def load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save(path, config):
    """Writes to a temporary file first, so a crash during a save cannot leave a half-written key file."""
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(dir=folder, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4)
        os.replace(temp_path, path)
    except BaseException:
        os.unlink(temp_path)
        raise
