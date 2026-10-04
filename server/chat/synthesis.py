import logging
import re
import time

from chat.llm import call_llm
from chat.prompts import fill_prompt
from core import state
from core.game import get_current_time_prefix
from core.pipe import send_to_pipe
from core.settings import load_settings
from store import campaign_db

RUMOR_SYNTHESIS = False
SYNTHESIS_STATUS = {"elapsed": 0, "interval": 60}

def generate_global_narrative_thread():
    # A rumor without a game time is never culled
    if "day" not in state.PLAYER_CONTEXT:
        logging.debug("NARRATIVE: No game time yet, so no synthesis.")
        return None
    settings = load_settings()
    last_chunk = campaign_db.recent_events(100)

    # Kept low so short sessions can still synthesize
    min_needed = 5
    if len(last_chunk) < min_needed:
        logging.debug(f"NARRATIVE: Not enough events to synthesize (have {len(last_chunk)}, need {min_needed}).")
        return None

    grouped_events = {}
    for evt in last_chunk:
        location = "Unknown Region"
        if " @ " in evt:
            try:
                parts = evt.split(" @ ")
                if len(parts) > 1:
                    location = parts[1].split(":")[0].strip()
            except: pass
        
        if location not in grouped_events:
            grouped_events[location] = []
        grouped_events[location].append(evt)

    events_text = ""
    for loc, evts in grouped_events.items():
        events_text += f"\n--- {loc.upper()} ---\n"
        events_text += "\n".join(evts) + "\n"
    
    logging.debug(f"NARRATIVE: Grouped {len(last_chunk)} events into {len(grouped_events)} locations.")
    
    past_rumors_block = ""
    rumor_lines = []
    for _, line in campaign_db.rumors()[-20:]:
        match = re.search(r'\[RUMOR:\s*(.*?)\]', line)
        if match:
            rumor_lines.append(f"- {match.group(1).strip()}")
    if rumor_lines:
        past_rumors_block = "\nPREVIOUS RUMORS (Do NOT repeat these):\n" + "\n".join(rumor_lines[-5:])

    p_fact = state.PLAYER_CONTEXT.get("faction", "The Nameless")
    
    prompt = fill_prompt("prompt_world_synthesis.txt", events_text=events_text, past_rumors_block=past_rumors_block, p_fact=p_fact)

    language = settings.get("language", "English")
    if language and language.lower() != "english":
        prompt += f"\nLANGUAGE: You MUST write the rumor ONLY in {language}. Do not use English."

    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": "Synthesize the rumors of the borderlands."}
    ]
    
    logging.info("NARRATIVE: Calling LLM to synthesize world events...")
    rumor_text = call_llm("synthesis", messages)
    
    if rumor_text:
        rumor_text = rumor_text.strip()
        # The LLM sometimes still wraps the rumor in a [RUMOR: ...] tag
        tag_match = re.search(r'\[RUMOR:\s*(.*?)\]', rumor_text, re.DOTALL)
        if tag_match:
            rumor_text = tag_match.group(1).strip()
        rumor_text = re.sub(r'^[-•*]\s*', '', rumor_text).strip()
        
        if len(rumor_text) > 10:
            time_prefix = get_current_time_prefix().strip()
            rumor_tagged = f"- {time_prefix} [RUMOR: {rumor_text}]"
            try:
                campaign_db.add_rumor(rumor_tagged)
                logging.info(f"NARRATIVE: Generated and saved new global event: {rumor_tagged}")
                notice = "A new world rumor is spreading."
                send_to_pipe("NOTIFY: " + state.LOCALIZATION_CONFIG.get(language, {}).get(notice, notice))
                return rumor_tagged
            except Exception as e:
                logging.error(f"NARRATIVE: Cannot save the rumor: {e}")
    return None

def synthesis_loop():
    logging.info("NARRATIVE: Synthesis background loop started.")
    elapsed_minutes = 0
    while True:
        try:
            settings = load_settings()
            interval = settings.get("synthesis_interval_minutes", 5)
            if interval < 1: interval = 1
            
            SYNTHESIS_STATUS["interval"] = interval
            
            if elapsed_minutes >= interval:
                logging.debug(f"NARRATIVE: Interval shortened ({interval}m). Triggering synthesis.")
                generate_global_narrative_thread()
                elapsed_minutes = 0
                SYNTHESIS_STATUS["elapsed"] = 0
                continue

            for _ in range(6):
                time.sleep(10)
            
            speed = state.PLAYER_CONTEXT.get("gamespeed", 1.0)
            
            if speed > 0.1:
                elapsed_minutes += 1
                SYNTHESIS_STATUS["elapsed"] = elapsed_minutes
                if elapsed_minutes % 10 == 0:
                    logging.debug(f"NARRATIVE: Timer progress: {elapsed_minutes}/{interval} minutes.")
            
            if elapsed_minutes >= interval:
                logging.debug(f"NARRATIVE: Timer reached ({interval}m). Triggering periodic synthesis.")
                generate_global_narrative_thread()
                elapsed_minutes = 0
                SYNTHESIS_STATUS["elapsed"] = 0
                    
        except Exception as e:
            logging.error(f"NARRATIVE: Synthesis loop failed: {e}")
            time.sleep(60)
