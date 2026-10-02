"""The LLM configuration: providers, profiles, and the route that each task takes.

The server keeps it in server/user/llm_config.json, which the release does not
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
    "ambient": {"max_tokens": 2048, "temperature": 0.8},
    "profile": {"max_tokens": 1500, "temperature": 0.7},
    "profile_batch": {"max_tokens": 1500, "temperature": 0.7},
    "synthesis": {"max_tokens": 2048, "temperature": 0.8},
}
PROVIDER_TYPES = ("openai", "player2")
# The plugin stops waiting for a reply after 60 s, so a whole fallback chain must end before that
DEFAULT_DEADLINE = 55
DEFAULT_TIMEOUT = 120


def build(providers, models, first_profile):
    config = {"providers": {}, "profiles": {}, "routes": {}}
    for name, provider in providers.items():
        config["providers"][name] = dict(provider, type="player2" if name == "player2" else "openai")
    for name, model in models.items():
        if model.get("provider") in config["providers"]:
            config["profiles"][name] = {
                "provider": model["provider"],
                "model": model["model"],
                "timeout": DEFAULT_TIMEOUT,
                "params": {},
            }
    first = first_profile if first_profile in config["profiles"] else next(iter(config["profiles"]), None)
    for task, sampling in TASKS.items():
        config["routes"][task] = dict(sampling, profiles=[first] if first else [], deadline=DEFAULT_DEADLINE)
    return config


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate(config):
    errors = []
    providers = config.get("providers")
    profiles = config.get("profiles")
    routes = config.get("routes")
    if not all(isinstance(part, dict) for part in (providers, profiles, routes)):
        return ["The configuration needs providers, profiles, and routes."]

    for name, provider in providers.items():
        if not name.strip():
            errors.append("A provider has no name.")
        if provider.get("type") not in PROVIDER_TYPES:
            errors.append(f"Provider {name}: the type must be one of {', '.join(PROVIDER_TYPES)}.")
        base_url = provider.get("base_url")
        if not isinstance(base_url, str) or urlparse(base_url).scheme not in ("http", "https") or not urlparse(base_url).netloc:
            errors.append(f"Provider {name}: the base URL must be an http:// or https:// address.")
        if not isinstance(provider.get("api_key", ""), str) or not isinstance(provider.get("game_key", ""), str):
            errors.append(f"Provider {name}: the keys must be text.")

    for name, profile in profiles.items():
        if not name.strip():
            errors.append("A profile has no name.")
        if profile.get("provider") not in providers:
            errors.append(f"Profile {name}: the provider {profile.get('provider')} does not exist.")
        if not isinstance(profile.get("model"), str) or not profile["model"].strip():
            errors.append(f"Profile {name}: the model ID is empty.")
        if not _is_number(profile.get("timeout")) or profile["timeout"] <= 0:
            errors.append(f"Profile {name}: the timeout must be a number above 0.")
        if not isinstance(profile.get("params", {}), dict):
            errors.append(f"Profile {name}: the extra request parameters must be a JSON object.")

    for task in TASKS:
        if task not in routes:
            errors.append(f"The {task} task has no route.")
    for task, route in routes.items():
        if task not in TASKS:
            errors.append(f"{task} is not a task.")
            continue
        chain = route.get("profiles")
        if not isinstance(chain, list):
            errors.append(f"Route {task}: the profiles must be a list.")
        else:
            for name in chain:
                if name not in profiles:
                    errors.append(f"Route {task}: the profile {name} does not exist.")
        max_tokens = route.get("max_tokens")
        if not isinstance(max_tokens, int) or isinstance(max_tokens, bool) or max_tokens <= 0:
            errors.append(f"Route {task}: max_tokens must be a whole number above 0.")
        if not _is_number(route.get("temperature")) or not 0 <= route["temperature"] <= 2:
            errors.append(f"Route {task}: the temperature must be from 0 to 2.")
        if not _is_number(route.get("deadline")) or route["deadline"] <= 0:
            errors.append(f"Route {task}: the deadline must be a number above 0.")
    return errors


def masked(config):
    result = copy.deepcopy(config)
    for provider in result["providers"].values():
        key = provider.pop("api_key", "")
        provider["api_key_hint"] = key[-4:] if len(key) > 4 else ""
    return result


def with_stored_keys(new, old):
    """Keeps the stored API key of each provider that the web app sends with an empty key field."""
    result = copy.deepcopy(new)
    for name, provider in result.get("providers", {}).items():
        provider.pop("api_key_hint", None)
        if not provider.get("api_key"):
            provider["api_key"] = old.get("providers", {}).get(name, {}).get("api_key", "")
    return result


def player2_providers_in_use(config):
    names = set()
    for route in config["routes"].values():
        for profile_name in route["profiles"]:
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
