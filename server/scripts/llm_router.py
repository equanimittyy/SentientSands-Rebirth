"""Sends a task's request to the profiles of its route in order, until one returns text.

The HTTP call is a parameter, so the chain and the deadline run under unittest
without requests.
"""

import logging
import time


def build_body(route, profile, messages):
    body = {"model": profile["model"], "messages": messages, "top_p": 0.9}
    body["max_tokens"] = route["max_tokens"]
    body["temperature"] = route["temperature"]
    body.update(profile.get("params", {}))
    return body


def run_route(config, task, messages, send, clock=time.monotonic):
    """send(provider, profile, body, timeout) returns the completion text or raises. Returns None when every profile fails."""
    route = config["routes"].get(task)
    if route is None:
        logging.error(f"LLM: {task} has no route.")
        return None

    start = clock()
    deadline = start + route["deadline"]
    failures = []
    for name in route["profiles"]:
        remaining = deadline - clock()
        if remaining <= 0:
            failures.append(f"{name}: the {route['deadline']} s deadline passed")
            break
        profile = config["profiles"].get(name)
        provider = config["providers"].get(profile["provider"]) if profile else None
        if provider is None:
            failures.append(f"{name}: not configured")
            continue
        try:
            text = send(provider, profile, build_body(route, profile, messages), min(profile["timeout"], remaining))
        except Exception as e:
            failures.append(f"{name}: {e}")
            continue
        if text and text.strip():
            if failures:
                logging.warning(f"LLM: {task} served by {name} in {clock() - start:.1f} s after failures: {'; '.join(failures)}")
            else:
                logging.info(f"LLM: {task} served by {name} in {clock() - start:.1f} s")
            return text
        failures.append(f"{name}: empty completion")

    logging.error(f"LLM: {task} failed on every profile: {'; '.join(failures) or 'the route has no profiles'}")
    return None
