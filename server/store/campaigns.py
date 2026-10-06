import logging
import os

from core import log_setup, state
from core.paths import CAMPAIGNS_DIR, DEFAULT_TEMPLATE, USER_TEMPLATES_DIR, WORLD_TEMPLATES_DIR
from core.settings import _save_settings_raw, load_settings, save_settings
from store import campaign_db, world_template

def get_campaign_dir():
    if not os.path.exists(CAMPAIGNS_DIR):
        os.makedirs(CAMPAIGNS_DIR)
        logging.info(f"CAMPAIGN: Created the campaigns folder {CAMPAIGNS_DIR}")
        
    cdir = os.path.join(CAMPAIGNS_DIR, state.ACTIVE_CAMPAIGN)
    if not os.path.exists(cdir):
        os.makedirs(cdir)
        logging.info(f"CAMPAIGN: Created the campaign folder {cdir}")
    return cdir

def load_campaign_config():
    try:
        if state.ACTIVE_CAMPAIGN:
            campaign_db.open_campaign(get_campaign_dir(), lambda: world_template.campaign_seed(DEFAULT_TEMPLATE, WORLD_TEMPLATES_DIR, USER_TEMPLATES_DIR))
        else:
            campaign_db.close_campaign()
    except Exception as e:
        logging.error(f"CAMPAIGN: Cannot load the campaign: {e}")

def init_server_state():
    try:
        settings = load_settings()
        log_setup.set_level(settings["log_level"])
        state.ACTIVE_CAMPAIGN = settings.get("current_campaign", "Default")
        logging.info(f"CAMPAIGN: Active campaign: {state.ACTIVE_CAMPAIGN or 'none'}")
        
        # Backfills missing keys into the INI with defaults
        _save_settings_raw(settings)
        
        load_campaign_config()
    except Exception as e:
        logging.error(f"SYSTEM: Cannot initialize the server state: {e}")

def create_campaign(name, template):
    """Returns the folder name of the new campaign. Raises ValueError or world_template.TemplateError with the reason."""
    if not name: raise ValueError("Missing name")
    safe_name = "".join([c for c in name if c.isalnum() or c in (' ', '_', '-')]).strip()
    if not safe_name: raise ValueError("Invalid name")
    cdir = os.path.join(CAMPAIGNS_DIR, safe_name)
    if os.path.exists(cdir): raise ValueError("Campaign already exists")
    seed = world_template.campaign_seed(template, WORLD_TEMPLATES_DIR, USER_TEMPLATES_DIR)
    os.makedirs(cdir)
    try:
        campaign_db.create(cdir, seed)
    except Exception:
        # An empty folder would open later as a campaign of the default template
        import shutil
        shutil.rmtree(cdir, ignore_errors=True)
        raise
    return safe_name

def switch_campaign(name):
    cdir = os.path.join(CAMPAIGNS_DIR, name)
    if not name or os.path.exists(cdir):
        state.ACTIVE_CAMPAIGN = name
        save_settings({"current_campaign": name})
        state.LIVE_CONTEXTS.clear()
        state.SEEN_FACTIONS.clear()
        state.CONVERSATION_SCENE.clear()
        state.CURRENT_THREAD.clear()
        state.RECENT_HITS.clear()
        state.restart_quiet_clock()
        load_campaign_config()
        return True
    return False

def campaign_names():
    return sorted(d for d in os.listdir(CAMPAIGNS_DIR) if os.path.isdir(os.path.join(CAMPAIGNS_DIR, d))) if os.path.exists(CAMPAIGNS_DIR) else []
