import json
import logging
import os
import re
import time

import requests

from chat import llm_config, llm_router
from core.log_setup import llm_log
from core.paths import DEFAULT_MODELS_PATH, DEFAULT_PROVIDERS_PATH, LLM_CONFIG_PATH

# main.py loads it at start-up, after the log setup, so the load can log
LLM_CONFIG = None
PLAYER2_SESSION_KEY = None

def sanitize_llm_text(text):
    if not text: return ""
    # Kenshi's engine chokes on these non-ASCII characters
    replacements = {
        '\u2018': "'", '\u2019': "'",
        '\u201c': '"', '\u201d': '"',
        '\u2013': '-', '\u2014': '-',
        '\u2026': '...',
        '\u00a0': ' ',
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    
    text = text.replace('\r\n', '\n')
    text = text.replace('\\n', '\n')
    text = text.replace('\\r', '')
    return text

def robust_json_parse(text):
    if not text: return None
    
    text = text.strip()
    
    start = text.find('{')
    end = text.rfind('}')
    if start == -1 or end == -1:
        return None
    
    json_str = text[start:end+1]
    
    json_str = re.sub(r',\s*([}\]])', r'\1', json_str)
    
    json_str = re.sub(r'//.*?\n', '\n', json_str)
    json_str = re.sub(r'/\*.*?\*/', '', json_str, flags=re.DOTALL)
    
    try:
        return json.loads(json_str)
    except Exception as eFirst:
        # Unescaped quotes between word characters are usually dialogue quotes inside a value
        try:
            sanitized = re.sub(r'(?<=[a-zA-Z0-9])"(?=[a-zA-Z0-9\s])', "'", json_str)
            return json.loads(sanitized)
        except:
            logging.warning(f"LLM: Cannot parse the reply as JSON: {json_str[:200]}...")
            raise eFirst

def default_llm_config():
    return llm_config.build(llm_config.load(DEFAULT_PROVIDERS_PATH), llm_config.load(DEFAULT_MODELS_PATH), "player2-default")

def load_llm_config():
    if not os.path.exists(LLM_CONFIG_PATH):
        config = default_llm_config()
        llm_config.save(LLM_CONFIG_PATH, config)
        logging.info("LLM: Built llm_config.json from the default providers and models.")
        return config
    try:
        config = llm_config.load(LLM_CONFIG_PATH)
    except Exception as e:
        # Not saved over, so a hand-edited file with a typo keeps its keys until the player fixes it
        logging.error(f"LLM: Cannot read {LLM_CONFIG_PATH}: {e}. Using the default configuration until a save from the web app.")
        return default_llm_config()
    # A task that a later version adds gets the default route, so the file of an earlier version keeps working
    for task in llm_config.TASKS:
        config["routes"].setdefault(task, llm_config.default_route(task))
    for error in llm_config.validate(config):
        logging.warning(f"LLM: {error['message']}")
    return config

def refresh_player2_session(provider):
    global PLAYER2_SESSION_KEY
    try:
        auth_resp = requests.post(f"http://localhost:4315/v1/login/web/{provider.get('game_key', '')}", timeout=5)
        new_key = auth_resp.json().get("p2Key") if auth_resp.status_code == 200 else None
    except Exception as e:
        # The Player2 app may not be running or logged in
        logging.warning(f"PLAYER2: Cannot refresh the session key: {e}")
        return False
    if new_key:
        PLAYER2_SESSION_KEY = new_key
    return bool(new_key)

def extract_completion(data, model):
    choices = data.get("choices") or []
    if not choices:
        return ""
    msg_obj = choices[0].get("message") or {}
    content = msg_obj.get("content")

    # Some providers put the text in reasoning_content (DeepSeek-style) or completions-style choices[0].text
    if content is None:
        content = msg_obj.get("reasoning_content")
    if content is None:
        content = choices[0].get("text")
    if content is None:
        llm_log.debug(f"{model} reply without text: {data}")
        return ""

    if "</thought>" in content:
        content = content.split("</thought>")[-1]

    content = re.sub(r'<thought>.*?</thought>', '', content, flags=re.DOTALL | re.IGNORECASE)
    content = re.sub(r'<thought>.*', '', content, flags=re.DOTALL | re.IGNORECASE)

    if "\n\n" in content and ("thought" in model.lower() or content.strip().lower().startswith("thought:")):
        parts = content.split("\n\n")
        if "thought" in parts[0].lower() or "reasoning" in parts[0].lower():
            content = "\n\n".join(parts[1:])

    return sanitize_llm_text(content.strip())

def send_completion(provider, profile, body, timeout):
    is_player2 = provider["type"] == "player2"
    target_url = f"{provider['base_url'].rstrip('/')}/chat/completions"

    for attempt in (1, 2):
        api_key = PLAYER2_SESSION_KEY if is_player2 and PLAYER2_SESSION_KEY else provider.get("api_key", "")
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        # OpenRouter uses these headers for app attribution
        if "openrouter.ai" in target_url:
            headers["X-Title"] = "Sentient Sands Rebirth"
            headers["HTTP-Referer"] = "https://github.com/equanimittyy/SentientSands-Rebirth"

        if is_player2:
            headers["player2-game-key"] = provider.get("game_key", "")

        logging.debug(f"LLM: Request to {profile['model']} at {target_url}")
        start_time = time.time()
        response = requests.post(target_url, headers=headers, json=body, timeout=timeout)
        seconds = time.time() - start_time
        logging.debug(f"LLM: {profile['model']} answered HTTP {response.status_code} in {seconds:.1f} s")

        # A Player2 session key expires, so a refreshed key gets one more try on the same profile
        if response.status_code == 401 and is_player2 and attempt == 1 and refresh_player2_session(provider):
            logging.info("PLAYER2: Refreshed the session key.")
            continue
        break

    if response.status_code != 200:
        raise RuntimeError(f"HTTP {response.status_code}: {response.text[:200]}")
    try:
        data = response.json()
    except ValueError:
        raise RuntimeError(f"invalid JSON in the response: {response.text[:200]}")
    log_usage(profile["model"], data, seconds)
    return extract_completion(data, profile["model"])

def log_usage(model, data, seconds):
    """Shows whether the provider's prompt cache served the stable start of a prompt, and where the time of a reply went.
    Each provider reports these under its own keys, and only llama.cpp splits the time into reading and writing."""
    if not isinstance(data, dict):
        return
    usage = data.get("usage") or {}
    timings = data.get("timings") or {}
    cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens", usage.get("prompt_cache_hit_tokens", timings.get("cache_n")))
    line = (f"LLM: {model} read {usage.get('prompt_tokens', 'an unknown number of')} prompt tokens, {'an unknown number' if cached is None else cached} of them from its cache, "
            f"and wrote {usage.get('completion_tokens', 'an unknown number of')} tokens in {seconds:.1f} s")
    if {"prompt_ms", "predicted_ms", "predicted_per_second"} <= timings.keys():
        line += f": {timings['prompt_ms'] / 1000:.1f} s reading, {timings['predicted_ms'] / 1000:.1f} s writing at {timings['predicted_per_second']:.1f} tokens/s"
    logging.info(line)

def call_llm(task, messages):
    """Returns the completion text from the first profile of the task's route that answers, or None."""
    llm_log.debug(f"{task} request:\n" + "\n".join(f"[{m['role']}]\n{m['content']}" for m in messages))
    text = llm_router.run_route(LLM_CONFIG, task, messages, send_completion)
    llm_log.debug(f"{task} reply:\n{text}")
    return text

def player2_ping_loop():
    logging.debug("PLAYER2: Health check thread started.")
    
    while True:
        try:
            for name in llm_config.player2_providers_in_use(LLM_CONFIG):
                provider = LLM_CONFIG["providers"][name]
                if not PLAYER2_SESSION_KEY and refresh_player2_session(provider):
                    logging.info("PLAYER2: Session authorized.")

                try:
                    h = {
                        "player2-game-key": provider.get("game_key", ""),
                        "Authorization": f"Bearer {PLAYER2_SESSION_KEY}" if PLAYER2_SESSION_KEY else ""
                    }
                    resp = requests.get(f"{provider['base_url'].rstrip('/')}/health", headers=h, timeout=5)
                    if resp.status_code == 200:
                        logging.debug("PLAYER2: The Player2 app is up.")
                    else:
                        logging.warning(f"PLAYER2: Health check returned status {resp.status_code}")
                except Exception as e:
                    logging.warning(f"PLAYER2: The Player2 app is down or unreachable: {e}")
            
        except Exception as e:
            logging.error(f"PLAYER2: Health check loop failed: {e}")
        
        time.sleep(60)
