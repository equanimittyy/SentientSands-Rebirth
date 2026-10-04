import os

SERVER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MOD_DIR = os.path.dirname(SERVER_DIR)

def resolve_mod_file(filename):
    """Falls back to the repo's mod/ subdirectory when run from a source checkout."""
    path = os.path.join(MOD_DIR, filename)
    if os.path.exists(path):
        return path
        
    dev_dir = os.path.join(MOD_DIR, "mod")
    if os.path.isdir(dev_dir):
        return os.path.join(dev_dir, filename)

    return path

INI_PATH = resolve_mod_file("SentientSands_Config.ini")
DEFAULTS_DIR = os.path.join(SERVER_DIR, "data", "defaults")
LLM_CONFIG_PATH = os.path.join(SERVER_DIR, "config", "llm_config.json")
DEFAULT_MODELS_PATH = os.path.join(DEFAULTS_DIR, "default_models.json")
DEFAULT_PROVIDERS_PATH = os.path.join(DEFAULTS_DIR, "default_providers.json")
NAMES_PATH = os.path.join(DEFAULTS_DIR, "names.json")
LOCALIZATION_PATH = os.path.join(DEFAULTS_DIR, "localization.json")
WEB_DIR = os.path.join(SERVER_DIR, "dashboard", "web")
CAMPAIGNS_DIR = os.path.join(SERVER_DIR, "data", "campaigns")
PROMPTS_DIR = os.path.join(SERVER_DIR, "data", "prompts")
USER_PROMPTS_DIR = os.path.join(SERVER_DIR, "config", "prompts")
WORLD_TEMPLATES_DIR = os.path.join(SERVER_DIR, "data", "templates")
USER_TEMPLATES_DIR = os.path.join(SERVER_DIR, "data", "user_templates")
DEFAULT_TEMPLATE = "kenshi_ssr_vanilla"
