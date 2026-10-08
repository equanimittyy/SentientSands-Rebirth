import logging
import time

from chat import chat_prompt, rumors
from chat.llm import call_llm, robust_json_parse
from chat.prompts import fill_prompt
from core import bounties, deeds, state
from core.settings import load_settings
from store import campaign_db

def quiet_seconds():
    """The plugin sends no signal when a conversation ends, so this long without a chat ends a chat thread."""
    return load_settings()["conversation_timeout_minutes"] * 60

def auto_rumor_seconds():
    """Real time, because each pass costs an LLM call, and a game hour passes much faster."""
    return load_settings()["radiant_rumor_minutes"] * 60

def chat_is_quiet():
    return time.monotonic() - state.QUIET_SINCE >= quiet_seconds()

def write_memory(thread, members, campaign):
    """Has the LLM write the memory of a pending chat thread and stores it. A failed call leaves the thread pending."""
    prompt = fill_prompt("prompt_thread_memory.txt", lines="\n".join(thread["lines"]))
    language = load_settings().get("language", "English")
    if language and language.lower() != "english":
        prompt += f"\nLANGUAGE: You MUST write the memory ONLY in {language}. Do not use English.\n"
    text = call_llm("memory", [{"role": "user", "content": prompt}])
    if not text:
        logging.warning(f"MEMORY: The LLM gave no memory for the chat thread {thread['id']}, so it stays pending.")
        return
    # A thread can outlive a campaign switch, and the same thread ID can name another thread in the new campaign
    if state.ACTIVE_CAMPAIGN != campaign:
        logging.info(f"MEMORY: Dropped the memory of the chat thread {thread['id']}, because the active campaign changed while the LLM wrote it.")
        return
    memory = chat_prompt.mark_names(" ".join(text.split()), [(npc_id, name) for npc_id, name, _, _ in members])
    if campaign_db.set_memory(thread["id"], memory, thread["game_time"]):
        logging.info(f"MEMORY: Stored the memory of the chat thread {thread['id']}.")
    else:
        logging.info(f"MEMORY: Dropped the memory of the chat thread {thread['id']}, because a cull or a delete changed the thread while the LLM wrote it.")

def write_rumor(notable_id, campaign):
    """Has the LLM write the rumor of a deed that has none and stores it. A failed call leaves the deed without one."""
    notable = campaign_db.notable(notable_id)
    if not notable:
        return
    if notable[1]["deed"] == "bounty":
        write_bounty_rumor(notable_id, notable, campaign)
        return
    text = rumors.clean(call_llm("synthesis", [{"role": "user", "content": rumors.prompt(*notable, "", "")}]))
    if not text:
        logging.warning(f"RUMOR: The LLM gave no rumor for the deed {notable_id}, so it waits for the next quiet period.")
        return
    # The same deed ID can name another deed in another campaign
    if state.ACTIVE_CAMPAIGN != campaign:
        logging.info(f"RUMOR: Dropped the rumor of the deed {notable_id}, because the active campaign changed while the LLM wrote it.")
        return
    if campaign_db.add_rumor(notable_id, text):
        logging.info(f"RUMOR: Stored the rumor of the deed {notable_id}.")
    else:
        logging.info(f"RUMOR: Dropped the rumor of the deed {notable_id}, because the player saved one or a cull deleted the deed while the LLM wrote it.")

def write_bounty_rumor(notable_id, notable, campaign):
    """Has the LLM write the wanted notice and the rumor of a bounty and the alias of its target in one reply, and stores
    them. A reply without all three leaves the bounty without a rumor."""
    try:
        parsed = rumors.bounty_reply(robust_json_parse(call_llm("synthesis", [{"role": "user", "content": rumors.bounty_prompt(*notable)}])))
    except ValueError:
        parsed = None
    if not parsed:
        logging.warning(f"RUMOR: The LLM gave no notice, rumor, and alias for the bounty {notable_id}, so it waits for the next quiet period.")
        return
    if state.ACTIVE_CAMPAIGN != campaign:
        logging.info(f"RUMOR: Dropped the rumor of the bounty {notable_id}, because the active campaign changed while the LLM wrote it.")
        return
    notice, text, alias = parsed
    if not campaign_db.add_bounty_rumor(notable_id, notice, text):
        logging.info(f"RUMOR: Dropped the rumor of the bounty {notable_id}, because a delete or a cull removed the bounty while the LLM wrote it.")
        return
    target = notable[1]["target"]
    named = campaign_db.add_alias(target["id"], alias)
    logging.info(f"RUMOR: Stored the notice and the rumor of the bounty {notable_id}" + (f", and {target['name']} is now known as {alias}." if named else "."))

def distill_threads():
    """Writes the memory of each pending chat thread of the active campaign, the oldest first, while the chat stays quiet."""
    campaign = state.ACTIVE_CAMPAIGN
    try:
        pending = campaign_db.pending_threads()
    except campaign_db.CampaignUnavailable:
        return
    if not pending:
        return
    members = campaign_db.thread_members(thread["id"] for thread in pending)
    logging.info(f"MEMORY: Writing the memories of the pending chat threads ({len(pending)})...")
    for thread in pending:
        with state.THREAD_LOCK:
            # Before each call, so a chat that starts during the distillation waits for one call at most
            if not chat_is_quiet():
                logging.info("MEMORY: A chat started, so the other chat threads wait for the next quiet period.")
                return
            # A chat during the call then starts a new thread, so each memory covers a whole thread
            state.CURRENT_THREAD.clear()
        write_memory(thread, members.get(thread["id"], []), campaign)

def write_rumors():
    """Writes the rumor of each deed of the active campaign that has none, the oldest first, while the chat stays quiet. The
    memories go first, so the rumors wait while a chat thread waits for its memory."""
    campaign = state.ACTIVE_CAMPAIGN
    try:
        if campaign_db.pending_threads():
            return
        waiting = [event["id"] for event in reversed(deeds.notable_events()) if event["rumor"] is None]
    except campaign_db.CampaignUnavailable:
        return
    if not waiting:
        return
    logging.info(f"RUMOR: Writing the rumors of the deeds without one ({len(waiting)})...")
    for notable_id in waiting:
        if not chat_is_quiet():
            logging.info("RUMOR: A chat started, so the other deeds wait for the next quiet period.")
            return
        write_rumor(notable_id, campaign)

def write_auto_rumor(pool, campaign):
    """Has the LLM spin at most one rumor from the memories of the pool (rumors.auto_pool)."""
    logging.info(f"RUMOR: Looking for an auto rumor in the memories ({len(pool)})...")
    text = call_llm("synthesis", [{"role": "user", "content": rumors.auto_prompt(pool)}])
    try:
        reply = robust_json_parse(text)
    except ValueError:
        reply = None
    rumors.keep_auto_rumor(reply, pool, campaign)

def memory_loop():
    """Runs the distillation, then the rumors, once in each quiet period and again after each radiant conversation or new
    bounty in it, so a thread or a deed whose call failed waits for the next run. A pass of the auto rumors runs in the same
    thread, so its call never overlaps a call of the memories or of the deed rumors, because a local model serves one
    request at a time."""
    distilled = None
    last_pass = time.monotonic()
    while True:
        time.sleep(10)
        try:
            bounties.tick()
        except Exception as e:
            logging.error(f"BOUNTY: The bounty timer failed: {e}")
        if time.monotonic() - last_pass >= auto_rumor_seconds() and chat_is_quiet():
            campaign = state.ACTIVE_CAMPAIGN
            try:
                pool = rumors.auto_pool()
                if pool:
                    # Before the call, so a provider that keeps failing costs one call in each period of the timer
                    last_pass = time.monotonic()
                    write_auto_rumor(pool, campaign)
            except Exception as e:
                logging.error(f"RUMOR: The auto rumor failed: {e}")
        since = state.QUIET_SINCE
        due = (since, state.LAST_RADIANT, state.LAST_BOUNTY)
        if due == distilled or time.monotonic() - since < quiet_seconds():
            continue
        distilled = due
        try:
            distill_threads()
        except Exception as e:
            # A thread, where nothing else would log the error
            logging.error(f"MEMORY: The distillation of the chat threads failed: {e}")
            continue
        try:
            write_rumors()
        except Exception as e:
            logging.error(f"RUMOR: The rumors of the deeds failed: {e}")
