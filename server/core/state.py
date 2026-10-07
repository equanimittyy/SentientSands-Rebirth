"""Session state that the chat, the game routes, the web app routes, and the campaign switch share.

Read and assign it as state.NAME. A from-import copies the value once, so a later assignment, such as the campaign
switch, never reaches the copy.
"""
import threading
import time

ACTIVE_CAMPAIGN = "Default"
LIVE_CONTEXTS = {}
PLAYER_CONTEXT = {}
CHANGED_TOWNS = []
# The scene stays fixed for a whole conversation, so the prompt cache can serve it; a chat with another NPC or as another squad member, a new name or faction of the NPC, or a first exchange with it starts a new one
CONVERSATION_SCENE = {}
# {"key": (npc_id of the squad member, npc_id of the NPC), "id": thread ID, "replied": time.monotonic() of the last reply}
CURRENT_THREAD = {}
# Held while a chat picks its thread and while the distillation ends the current thread, so a chat never adds lines to a thread whose memory is being written
THREAD_LOCK = threading.Lock()
# {(npc_id of the squad member, npc_id of the NPC): the keys of the retrieval hits of each of its last turns, oldest first}; a chat of another pair drops it
RECENT_HITS = {}
# Starts with the server, so the threads that a restart left pending get their memories one quiet period after the start
QUIET_SINCE = time.monotonic()
LAST_RADIANT = None
WRITE_REQUESTS = 0
SEEN_FACTIONS = set()
GAME_REPORTED = threading.Event()
NAMES_CONFIG = {}
LOCALIZATION_CONFIG = {}

def restart_quiet_clock():
    global QUIET_SINCE
    QUIET_SINCE = time.monotonic()
