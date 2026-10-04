import logging
import time

from chat import chat_prompt
from chat.llm import call_llm
from chat.prompts import fill_prompt
from core import state
from core.settings import load_settings
from store import campaign_db

def quiet_seconds():
    """The plugin sends no signal when a conversation ends, so this long without a chat ends a chat thread."""
    return load_settings()["conversation_timeout_minutes"] * 60

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
        timeout = quiet_seconds()
        with state.THREAD_LOCK:
            # Before each call, so a chat that starts during the distillation waits for one call at most
            if time.monotonic() - state.QUIET_SINCE < timeout:
                logging.info("MEMORY: A chat started, so the other chat threads wait for the next quiet period.")
                return
            # A chat during the call then starts a new thread, so each memory covers a whole thread
            state.CURRENT_THREAD.clear()
        write_memory(thread, members.get(thread["id"], []), campaign)

def memory_loop():
    """Runs the distillation once in each quiet period, so a thread whose call failed waits for the next one."""
    distilled = None
    while True:
        time.sleep(10)
        since = state.QUIET_SINCE
        if since == distilled or time.monotonic() - since < quiet_seconds():
            continue
        distilled = since
        try:
            distill_threads()
        except Exception as e:
            # A thread, where nothing else would log the error
            logging.error(f"MEMORY: The distillation of the chat threads failed: {e}")
