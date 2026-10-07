import json
import logging
import queue
import re
import threading
import time

from flask import Blueprint, jsonify, request

from chat import background, chat_prompt, radiant, retrieval, rumors, scene_text
from chat.bio import BIO_PARTS, generate_bio, recorded_history, write_bio
from chat.characters import get_character_data, npc_name, should_save_profile
from chat.llm import call_llm
from chat.memory import quiet_seconds
from chat.prompts import PROMPT_RUMORS, build_system_prompt, describe_faction, describe_npc, describe_race, fill_prompt, find_location, load_prompt_component, npc_scene, scene_values
from core import bounties, deeds, state
from core.game import context_dict, get_current_time_prefix, is_player_faction, note_faction, take_report
from core.pipe import send_to_pipe
from core.routes import campaign_write
from core.settings import get_config_radii, load_settings
from store import campaign_db

bp = Blueprint("chat", __name__)

_REPLIES = queue.Queue()
# A radiant conversation holds it from its "..." to its last line, so a chat reply waits for it and a second one cannot start
_STAGE = threading.Lock()
_last_line = 0.0

@bp.route('/radiant', methods=['POST'])
def radiant_conversation():
    logging.debug("HTTP: POST /radiant")
    data = request.json
    if not data: return jsonify({"status": "error"}), 400
    center = context_dict(data.get('player_context'))
    take_report(center, data.get('events'), data.get('changed_towns'))
    participants = {str(npc['id']): npc for npc in data.get('participants', [])}
    npc_ids = [npc['npc_id'] for npc in participants.values()]

    if deeds.fought_recently(npc_ids, center):
        logging.info(f"RADIANT: A participant fought within the last {deeds.FIGHT_QUIET_MINUTES // 60} game hours, so nobody talks.")
        return jsonify({"status": "ignore"})

    names, profiles = {}, {}
    for serial, npc in participants.items():
        # The faction of a participant is its identity faction, not the current faction that Campaign Canon shows
        merge_live_context({key: value for key, value in npc.items() if key != 'faction'})
        names[serial] = npc_name(npc)
        profiles[serial] = get_character_data(names[serial], context=json.dumps(npc))

    rumor_texts = [rumor["text"] for rumor in campaign_db.rumors()[-PROMPT_RUMORS:]]
    environment = center.get("environment") or {}
    location = find_location(environment["town_name"]) if environment.get("town_name") else None
    topic = radiant.topic(campaign_db.shared_memories(npc_ids), environment, rumor_texts, location=location)
    if not topic:
        logging.info("RADIANT: No topic, so nobody talks.")
        return jsonify({"status": "ignore"})

    if not _STAGE.acquire(blocking=False):
        logging.info("RADIANT: A conversation plays, so nobody else talks.")
        return jsonify({"status": "ignore"})
    playing = False
    try:
        descriptions = [
            f"{describe_npc(f'{names[serial]}|{serial}', profiles[serial], npc['npc_id'])}\nHEALTH: {npc.get('health') or 'Unknown'}\nGEAR: {npc.get('equipment') or 'nothing notable'}"
            for serial, npc in participants.items()
        ]
        prompt = fill_prompt("prompt_radiant.txt", place=scene_text.location_text(environment, "They"), participants="\n\n".join(descriptions), topic=topic)
        logging.info(f"RADIANT: {', '.join(names.values())} talk. Topic: {topic}")
        for serial in participants:
            send_to_pipe(f"NPC_SAY: {names[serial]}|{serial}: ...")
        content = call_llm("radiant", [{"role": "system", "content": build_system_prompt()}, {"role": "user", "content": prompt}])
        lines = radiant.lines(content or "", participants)
        if not lines:
            logging.warning("RADIANT: The reply of the LLM is not a conversation of the participants, so nobody talks.")
            return jsonify({"status": "none"})

        time_prefix = get_current_time_prefix()
        thread_id = campaign_db.join_thread(None, [(npc_id, "speaker", True) for npc_id in npc_ids], campaign_db.game_time(time_prefix), scene_text.location_name(center))
        stored = [(f"{time_prefix}{names[serial]}: {text}", participants[serial]['npc_id']) for serial, text in lines]
        for serial, npc in participants.items():
            campaign_db.append_dialogue(npc['npc_id'], stored, profiles[serial], thread_id)
        state.LAST_RADIANT = time.monotonic()
        # Before the start: a thread that ends at once releases the stage, and the finally would release it again
        playing = True
        threading.Thread(target=play_radiant, args=([f"{names[serial]}|{serial}: {text}" for serial, text in lines],), daemon=True).start()
        logging.debug(f"RADIANT: {[line for line, _ in stored]}")
        return jsonify({"status": "ok"})
    finally:
        if not playing:
            _STAGE.release()

def say(lines, actions=()):
    """Sends the actions, then each line at least the dialogue delay after the line before it, also when that line ended an
    earlier conversation. The plugin shows a line when it arrives, so the server alone paces every conversation. A pause of
    the game does not stop the delay. The actions go first, so an AI state change cannot clear a bubble that is already up."""
    global _last_line
    for action in actions:
        send_to_pipe(f"NPC_ACTION: {action}")
    delay = load_settings()["dialogue_speed_seconds"]
    for line in lines:
        time.sleep(max(0.0, _last_line + delay - time.monotonic()))
        send_to_pipe(f"NPC_SAY: {line}")
        _last_line = time.monotonic()

def play_radiant(lines):
    try:
        say(lines)
    finally:
        _STAGE.release()

def play_lines(lines, actions=()):
    """Queues a chat reply, which plays after every reply before it and after a radiant conversation that holds the stage."""
    _REPLIES.put((lines, actions))

def reply_loop():
    while True:
        lines, actions = _REPLIES.get()
        try:
            with _STAGE:
                say(lines, actions)
        except Exception as e:
            # An error must not end the loop, or no later chat reply would play
            logging.error(f"CHAT: The lines of a reply failed: {e}")

def merge_live_context(ctx):
    # Merge rather than replace, because a nearby entry lacks fields, such as factionID, that a full context of the same character stored
    live = state.LIVE_CONTEXTS.setdefault(ctx['npc_id'], {})
    for key in ("race", "faction", "factionID", "origin_faction", "gender", "health"):
        if ctx.get(key): live[key] = ctx[key]
    if "nearby" in ctx:
        live["nearby"] = ctx["nearby"]
    if "dist" in ctx:
        live["player_dist"] = ctx["dist"]

@bp.route('/chat', methods=['POST'])
def chat():
    started = time.monotonic()
    data = request.json
    logging.debug("HTTP: POST /chat")
    if not data: return jsonify({"text": "Error: No JSON data provided"}), 400

    speaker = context_dict(data.get('speaker'))
    take_report(speaker, data.get('events'), data.get('changed_towns'))
    
    raw_npc = data.get('npc', 'Someone')
    raw_npcs = data.get('npcs', [])
    
    def register(raw):
        if not raw: return ""
        return raw.split('|')[0] if '|' in raw else raw

    primary_npc = register(raw_npc)
    npcs = [register(n) for n in raw_npcs]
    target_serial = raw_npcs[0].partition('|')[2] if raw_npcs else ""

    def reply(*texts, actions=()):
        # The plugin takes the text before a first colon as the speaker. It finds the NPC by the serial after the bar,
        # because its request named the NPC before a rename.
        voice = f"{primary_npc}|{target_serial}"
        play_lines([f"{voice}: {text}" for text in texts], [f"{voice}: {action}" for action in actions])
        return jsonify({"status": "ok"})
    
    player_name = data.get('player', 'Drifter')
    mode = data.get('mode', 'talk')
    
    nearby = data.get('nearby', [])

    # Keeps the LLM from being asked to voice the player
    npcs = [n for n in npcs if n != player_name]
    if primary_npc == player_name and len(npcs) > 0:
        primary_npc = npcs[0]
        
    player_message = data.get('message', '')
    
    if player_message.startswith('/'):
        cmd_parts = player_message[1:].split(' ', 1)
        cmd = cmd_parts[0].lower()
        args = cmd_parts[1].strip() if len(cmd_parts) > 1 else ""
        
        test_action = None
        if cmd == "help" or cmd == "commands":
            help_text = "[DEBUG] Available test commands:\n" + \
                        "/take, /attack, /follow, /idle, /patrol, /join, /leave, /free, /breakout,\n" + \
                        "/move, /movefast, /home, /shop, /raid [Town], /travel [Town], /medic, /rescue, /repair,\n" + \
                        "/notify [msg], /give_cats [n], /take_cats [n], /drop [item],\n" + \
                        "/take_item [item], /spawn [Templ|Name|Desc], /relations [Fact] [n], /task [TASK],\n" + \
                        "/bounty [Fact] [crime] [n]"
            return reply(*help_text.split("\n"))
            
        if cmd == "attack": test_action = "[ATTACK]"
        elif cmd == "follow": test_action = "[ACTION: FOLLOW_PLAYER]"
        elif cmd == "idle": test_action = "[ACTION: IDLE]"
        elif cmd == "patrol": test_action = "[ACTION: PATROL_TOWN]"
        elif cmd == "join": test_action = "[ACTION: JOIN_PARTY]"
        elif cmd == "leave": test_action = "[ACTION: LEAVE]"
        elif cmd == "free": test_action = "[ACTION: FREE_PLAYER]"
        elif cmd == "breakout": test_action = "[ACTION: BREAKOUT_PLAYER]"
        elif cmd == "move": test_action = "[ACTION: MOVE_ON_FREE_WILL]"
        elif cmd == "movefast": test_action = "[ACTION: MOVE_ON_FREE_WILL_FAST]"
        elif cmd == "home": test_action = "[ACTION: GO_HOMEBUILDING]"
        elif cmd == "shop": test_action = "[ACTION: STAND_AT_SHOPKEEPER_NODE]"
        elif cmd == "raid": test_action = f"[ACTION: RAID_TOWN: {args}]"
        elif cmd == "travel": test_action = f"[ACTION: TRAVEL_TO_TARGET_TOWN: {args}]"
        elif cmd == "medic": test_action = "[ACTION: JOB_MEDIC]"
        elif cmd == "rescue": test_action = "[ACTION: FIND_AND_RESCUE]"
        elif cmd == "repair": test_action = "[ACTION: JOB_REPAIR_ROBOT]"
        elif cmd == "notify": test_action = f"[ACTION: NOTIFY: {args}]"
        elif cmd == "give_cats": test_action = f"[ACTION: GIVE_CATS: {args}]"
        elif cmd == "take_cats": test_action = f"[ACTION: TAKE_CATS: {args}]"
        elif cmd == "take_item": test_action = f"[ACTION: TAKE_ITEM: {args}]"
        elif cmd == "take":
            inv = state.PLAYER_CONTEXT.get("inventory", [])
            if inv:
                item_name = inv[0].get("name", "Unknown Item")
                test_action = f"[ACTION: TAKE_ITEM: {item_name}]"
            else:
                return reply("[DEBUG] Error: Player inventory is empty or unknown.")
        elif cmd == "drop": test_action = f"[ACTION: DROP_ITEM: {args}]"
        elif cmd == "spawn": test_action = f"[ACTION: SPAWN_ITEM: {args}]"
        elif cmd == "relations":
            rparts = args.rsplit(' ', 1)
            if len(rparts) == 2:
                test_action = f"[ACTION: FACTION_RELATIONS: {rparts[0].strip()}: {rparts[1].strip()}]"
        elif cmd == "task": test_action = f"[TASK: {args.upper()}]"
        elif cmd == "bounty":
            parts = args.rsplit(' ', 2)
            if not args:
                probe = "[ACTION: BOUNTY_PROBE]"
            elif len(parts) == 3 and parts[1].upper() in bounties.CRIMES and parts[2].isdigit():
                probe = f"[ACTION: BOUNTY_PROBE: {bounties.CRIMES.index(parts[1].upper()) + 1}: {parts[2]}: {parts[0]}]"
            else:
                return reply("[DEBUG] /bounty [Fact] [crime] [n] puts a bounty on the target. /bounty alone logs its bounties.",
                             f"[DEBUG] Crimes: {', '.join(crime.lower() for crime in bounties.CRIMES)}")
            logging.info(f"CHAT: Test command {cmd} -> {probe}")
            # The plugin also runs a tag in a spoken line, so an echo of the tag would place the bounty twice
            return reply("[DEBUG] Executing test command: bounty probe", actions=[probe])
        
        if test_action:
            logging.info(f"CHAT: Test command {cmd} -> {test_action}")
            return reply(f"[DEBUG] Executing test command: {test_action}", actions=[test_action])

    if not player_message:
        return reply("...")

    context = data.get('context', '')
    ctx_dict = context_dict(context)
    primary_id = ctx_dict.get('npc_id')

    # A new profile and the scene read race/faction from state.LIVE_CONTEXTS
    if primary_npc and context:
        try:
            if ctx_dict:
                note_faction(ctx_dict)
            if primary_id:
                merge_live_context(ctx_dict)
        except Exception as e:
            logging.error(f"CHAT: Cannot register the context of the chat target: {e}")

    if primary_id:
        primary_npc = npc_name(ctx_dict)

    speaker_id = speaker.get("npc_id")
    # The listeners leave out the speaker, so only this stores its live context and its profile
    if speaker_id:
        merge_live_context(speaker)
        npc_name(speaker)
    thread_key = (speaker_id, primary_id, mode)
    timeout = quiet_seconds()
    with state.THREAD_LOCK:
        current_thread = state.CURRENT_THREAD.get("id") if state.CURRENT_THREAD.get("key") == thread_key and time.monotonic() - state.CURRENT_THREAD["replied"] < timeout else None
        state.restart_quiet_clock()

    talk_radius, yell_radius = get_config_radii()
    # A whisper is one-on-one: nobody overhears
    radius = {"talk": talk_radius, "yell": yell_radius}.get(mode)

    # Keyed by npc_id, because NPCs near the player can share a name, for example two Dust Bandits
    listeners = {primary_id: (primary_npc, context)}
    in_squad = {primary_id: bool(ctx_dict.get("in_player_faction") or is_player_faction(ctx_dict.get("faction"), ctx_dict.get("factionID"))), speaker_id: True}
    for n in chat_prompt.overhearers(nearby, radius, {primary_id, speaker.get("npc_id")}):
        merge_live_context(n)
        listeners[n["npc_id"]] = (npc_name(n), json.dumps(n))
        in_squad[n["npc_id"]] = bool(n.get("in_player_faction") or is_player_faction(n.get("faction"), n.get("factionID")))

    char_datas = {}
    for npc_id, (name, local_context) in listeners.items():
        try:
            char_datas[npc_id] = get_character_data(name, local_context)
        except Exception as e:
            logging.error(f"PROFILE: Cannot fetch the profile of {name}: {e}")

    primary_data = char_datas.get(primary_id)
    if not primary_data:
        logging.warning(f"PROFILE: No profile for {primary_npc}, so the chat uses a generic one.")
        primary_data = char_datas[primary_id] = {"Name": primary_npc, "Personality": "A generic NPC.", "Backstory": "", "ConversationHistory": []}

    logging.info(f"CHAT: {mode} with {primary_npc} ({len(listeners) - 1} others hear it)...")

    animal = primary_data.get("Animal")

    # A rule that rated the player's politeness let a scornful NPC warm up with each apology
    judgment = "JUDGMENT: End every reply with [JUDGMENT: n], the change that the player's line makes to how you feel about the player, from -5 (it angers, frightens, hurts, or offends you) to 5 (it pleases you); 0 is no change. Judge by your personality, not by how polite the line is."
    if animal:
        system_prompt = load_prompt_component("prompt_animal_system.txt")
        final_instruction = f"Reply as {primary_npc} with one action or sound in asterisks, and no words. End with [JUDGMENT: n]."
    else:
        system_prompt = build_system_prompt()
        final_instruction = f"Reply as {primary_npc}{', quietly' if mode == 'whisper' else ''}. End with [JUDGMENT: n]."

    mode_tag = {"whisper": "(Whispered) ", "yell": "(Yelled) "}.get(mode, "")
    time_prefix = get_current_time_prefix()
    full_player_entry = f"{time_prefix}{mode_tag}{player_name}: {player_message}"

    live = state.LIVE_CONTEXTS.get(primary_id, {})
    rows = campaign_db.dialogue(primary_id)
    spoken = chat_prompt.spoken_with(rows, campaign_db.thread_partners(primary_id), primary_id)
    met = speaker_id in spoken
    conversation = (speaker.get("npc_id"), primary_id or primary_npc, primary_npc, live.get("faction"), met)
    scene = state.CONVERSATION_SCENE.get(conversation)
    if scene is None:
        others = [npc_id for npc_id in spoken if npc_id != speaker_id]
        names = campaign_db.names_of(others)
        squad = set(state.PLAYER_CONTEXT.get("squad") or [])
        player = speaker or state.PLAYER_CONTEXT
        scene = fill_prompt(
            "prompt_chat_scene.txt",
            **scene_values(player, player_name),
            npc=npc_scene(ctx_dict or primary_data, primary_data, player_name, met, [names[i] for i in others if names.get(i) in squad], player.get("stats") or {}),
        )
        state.CONVERSATION_SCENE.clear()
        state.CONVERSATION_SCENE[conversation] = scene
    # Read on each turn, not with the scene, so a memory that the distillation writes during a conversation reaches the next turn
    memories = chat_prompt.memories_block(chat_prompt.starting_memories(campaign_db.memories_of(primary_id), primary_id), primary_id)
    system = fill_prompt("prompt_chat_template.txt", system_prompt=system_prompt, judgment=judgment, primary_npc=primary_npc, npc_profiles=describe_npc(primary_npc, primary_data, primary_id), scene=scene, memories=memories)
    pair = (speaker_id, primary_id)
    cooldown = load_settings()["retrieval_cooldown_turns"]
    recent_turns = state.RECENT_HITS.get(pair, [])
    found_memories, found_entries = [], []
    # An animal replies only in actions
    if not animal:
        environment = ctx_dict.get("environment") or {}
        found_memories, found_entries, _ = background.search(
            player_message, background.campaign_lore(), primary_id, primary_data, live.get("factionID"), (speaker or state.PLAYER_CONTEXT).get("race"),
            environment.get("town_name"), environment.get("zone_name"), retrieval.held(recent_turns, cooldown),
        )
    background_block = chat_prompt.background_block(
        [hit["record"]["memory"] for hit in found_memories], [hit["record"] for hit in found_entries if not hit["travels"]], primary_id, player_name,
        [hit["record"] for hit in found_entries if hit["travels"]],
    )
    turn = fill_prompt("prompt_chat_turn.txt", background=background_block, player_line=full_player_entry, final_instruction=final_instruction).strip()
    history = chat_prompt.history_window(chat_prompt.chat_lines(rows), campaign_db.DIALOGUE_BLOCK)
    notes = chat_prompt.overheard_notes(campaign_db.thread_members({thread_id for _, _, thread_id in history if thread_id}), primary_id)
    messages = chat_prompt.chat_messages(system, chat_prompt.history_turns(chat_prompt.with_notes(history, notes), primary_id), turn)

    content = call_llm("chat", messages)
    state.restart_quiet_clock()
    if not content:
        logging.error("CHAT: No reply from the LLM.")
    
    if content:
        judged = re.search(r'\[[^\]]*JUDGMENT\D*?(-?\d+)[^\]]*\]', content, re.IGNORECASE)
        judgment_value = max(-5, min(5, int(judged.group(1)))) if judged else 0

        # Allows one level of nested brackets: item names like "Bolts [Toothpicks]" contain them
        content = re.sub(r'\[\s*(?:[^\[\]]|\[[^\[\]]*\])+\s*\]', '', content).strip()


        content = content.replace('"', '').strip()
        
        lines = content.split('\n')
        # The chat window keeps the name that the target had when it opened, so the request can name the target by an old name
        own_names = {primary_npc.lower(), register(raw_npc).lower()}
        # The game name and the Name of an NPC differ when the game gave it a title
        other_names = {name.lower() for name in [*npcs, *(n["name"] for n in nearby if n.get("name")), *(name for name, _ in listeners.values())]} - own_names
        filtered_lines = []
        for line in lines:
            line = line.strip()
            if not line: continue
            
            line = re.sub(r'\[\s*[^\]]+\s*\]', '', line).strip()
            if not line: continue

            lower_line = line.lower()
            if any(lower_line.startswith(prefix) for prefix in [
                "thought:", "thinking:", "observation:", "note:", "(thinking", 
                "as an ai", "i cannot", "here is", "raw llm response:", 
                "timestamp:", "request for:", "prompt:", "user message:",
                "history:", "character:", "personality:", "backstory:", "current condition"
            ]):
                continue
            
            # A divider such as "===" holds no letters, but an animal's "Grr" does
            if not any(c.isalnum() for c in line):
                continue
                
            # Only a known name counts as a speaker, so a reply such as "Listen: ..." keeps its first word
            prefix_match = re.match(r'^([^:]{1,63}):\s*', line)
            if prefix_match:
                p = prefix_match.group(1).strip().lower()
                if p == player_name.lower() or p in other_names:
                    logging.debug(f"CHAT: Filter: Discarded a line voiced as {p} (expected {primary_npc})")
                    continue
                if p in own_names:
                    line = line[prefix_match.end():]
            
            if line:
                filtered_lines.append(line)
        
        # The plugin shows each line as its own speech bubble, so one reply is one line
        content = " ".join(filtered_lines) if filtered_lines else "..."
        # The model still gives an animal words now and then, so only the *action* parts reach the game
        if animal:
            content = " ".join(re.findall(r"\*[^*\n]+\*", content)) or "..."

        if len(content) > 500:
            content = content[:497] + "..."
        
        recorders = {speaker_id: (player_name, speaker), **listeners} if speaker_id else listeners
        copies = []
        for npc_id, (name, local_context) in recorders.items():
            overheard_tag = "" if npc_id in (primary_id, speaker_id) else "(Overheard) "
            # Without the addressees, a listener takes the "you" of a line as itself
            to_npc, to_player = (f" to {primary_npc}", f" to {player_name}") if overheard_tag else ("", "")

            if npc_id not in char_datas:
                char_datas[npc_id] = get_character_data(name, local_context)

            new_lines = [
                (f"{time_prefix}{overheard_tag}{mode_tag}{player_name}{to_npc}: {player_message}", speaker.get("npc_id")),
                (f"{time_prefix}{overheard_tag}{primary_npc}{to_player}: {content}", primary_id),
            ]
            char_datas[npc_id]["ConversationHistory"].extend(line for line, _ in new_lines)

            if npc_id and should_save_profile(name, npc_id, char_datas[npc_id]):
                copies.append((npc_id, name, new_lines))

        thread_id = None
        if primary_id:
            members = [(npc_id, "speaker" if npc_id in (primary_id, speaker_id) else "overheard", in_squad.get(npc_id, False)) for npc_id, _, _ in copies]
            thread_id = campaign_db.join_thread(current_thread, members, campaign_db.game_time(time_prefix), scene_text.location_name(speaker or state.PLAYER_CONTEXT))
            state.CURRENT_THREAD.update(key=thread_key, id=thread_id, replied=time.monotonic())
        for npc_id, name, new_lines in copies:
            campaign_db.append_dialogue(npc_id, new_lines, char_datas[npc_id], thread_id)
            if npc_id == primary_id and judgment_value:
                # Applied as a delta at save time: the profile read before the LLM call can be stale by then
                new_rel = campaign_db.change_relation(npc_id, judgment_value)
                logging.info(f"RELATION: {name} personal relation is now {new_rel} (judgment={judgment_value})")

        state.RECENT_HITS.clear()
        state.RECENT_HITS[pair] = retrieval.next_turns(recent_turns, [hit["record"]["key"] for hit in found_memories + found_entries], cooldown)

        interactions = campaign_db.count_interaction(primary_id) if primary_id else None
        threshold = load_settings()["bio_interactions"]
        if interactions is not None and threshold and interactions >= threshold:
            # In the background, so the reply does not wait for a second LLM call
            threading.Thread(target=generate_bio, args=(primary_id,), daemon=True).start()

        logging.info(f'CHAT: {mode_tag}{player_name} to {primary_npc}: "{player_message}" | {primary_npc}: "{content}" ({time.monotonic() - started:.1f} s)')
        return reply(content)
    return jsonify({"error": "No reply from the LLM.", "status": "error"}), 502

def bio_refusal(data):
    parts, profile = data.get("parts"), data.get("profile")
    if isinstance(profile, dict) and isinstance(parts, list) and parts and set(parts) <= set(BIO_PARTS):
        return None
    return jsonify({"status": "error", "message": f"Name the parts to write: {', '.join(BIO_PARTS)}."}), 400

def bio_reply(data, history, race_lore, faction, **reply):
    """The web app puts the parts into its form, and the Dialogue Library into its editor, so the player reads them before a
    save keeps them."""
    parts = [part for part in BIO_PARTS if part in data["parts"]]
    bio = write_bio(data["profile"], parts, str(data.get("instructions") or ""), history, race_lore, faction)
    if not bio:
        return jsonify({"status": "error", "message": "The LLM gave no usable text. Try again."}), 500
    return jsonify({"status": "ok", "bio": bio, **reply})

def rumor_reply(notable_id, instruction, so_far=None, **reply):
    """The web app puts the text into the row of the deed, so the player reads it before a save keeps it. so_far None takes
    the stored rumor. Stores nothing."""
    try:
        notable_id = int(notable_id)
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "Name the notable event of the rumor."}), 400
    notable = campaign_db.notable(notable_id)
    if not notable:
        return jsonify({"status": "error", "message": "The notable event is gone. Load the events again."}), 404
    if so_far is None:
        so_far = next((rumor["text"] for rumor in campaign_db.rumors() if rumor["notable_id"] == notable_id), "")
    text = rumors.clean(call_llm("synthesis", [{"role": "user", "content": rumors.prompt(*notable, instruction, so_far)}]))
    if not text:
        return jsonify({"status": "error", "message": "The LLM gave no usable text. Try again."}), 500
    return jsonify({"status": "ok", "text": text, **reply})

def keep_rumor_reply(data):
    """Saves the text of a rumor by its id, or the rumor of a notable event, which a new rumor has no id for yet."""
    refused = campaign_write(data)
    if refused: return refused
    text = str(data.get("text") or "").strip()
    if not text:
        key = str(data["id"]) if data.get("id") else f"new:{data.get('notable')}"
        return jsonify({"status": "error", "errors": [{"field": ["rumors", key], "message": "A rumor needs text. Delete it instead."}]}), 400
    instruction = data.get("instruction")
    if not campaign_db.save_rumor(data.get("id"), data.get("notable"), text, None if instruction is None else str(instruction).strip()):
        return jsonify({"status": "error", "message": "The rumor or its event is gone. Load the events again."}), 404
    return jsonify({"status": "ok"})

def delete_rumor_reply(data):
    refused = campaign_write(data)
    if refused: return refused
    campaign_db.delete_rumor(data.get("id"))
    return jsonify({"status": "ok"})

def add_deed_reply(data, source):
    """The Deeds window selects the new deed by its id."""
    refused = campaign_write(data)
    if refused: return refused
    rumor = str(data.get("rumor") or "").strip()
    if not rumor:
        return jsonify({"status": "error", "message": "Write the rumor of the deed."}), 400
    notable_id = campaign_db.add_custom_deed(rumor)
    logging.info(f"DEEDS: Added the custom deed {notable_id} from {source}")
    return jsonify({"status": "ok", "id": notable_id})

def delete_deed_reply(data):
    refused = campaign_write(data)
    if refused: return refused
    campaign_db.delete_custom_deed(data.get("id"))
    return jsonify({"status": "ok"})

@bp.route('/write_rumor', methods=['POST'])
def write_events_rumor():
    data = request.get_json(silent=True) or {}
    # The Deeds window sends the campaign back with Keep, because the same notable event ID can name another deed in another campaign
    return rumor_reply(data.get("notable"), str(data.get("instruction") or ""), campaign=state.ACTIVE_CAMPAIGN)

@bp.route('/read_rumor', methods=['POST'])
def read_events_rumor():
    """Answers in the shape of /write_rumor, so Edit Rumor in the Deeds window opens the same editor as Generate Rumor."""
    data = request.get_json(silent=True) or {}
    rumor = next((rumor for rumor in campaign_db.rumors() if str(rumor["notable_id"]) == str(data.get("notable"))), None)
    if not rumor:
        return jsonify({"status": "error", "message": "The deed has no rumor yet."}), 404
    return jsonify({"status": "ok", "text": rumor["text"], "campaign": state.ACTIVE_CAMPAIGN})

@bp.route('/keep_rumor', methods=['POST'])
def keep_events_rumor():
    return keep_rumor_reply(request.get_json(silent=True) or {})

@bp.route('/delete_rumor', methods=['POST'])
def delete_events_rumor():
    return delete_rumor_reply(request.get_json(silent=True) or {})

@bp.route('/add_deed', methods=['POST'])
def add_events_deed():
    return add_deed_reply(request.get_json(silent=True) or {}, "the game")

@bp.route('/delete_deed', methods=['POST'])
def delete_events_deed():
    return delete_deed_reply(request.get_json(silent=True) or {})

@bp.route('/write_bio', methods=['POST'])
def write_library_bio():
    data = request.get_json(silent=True) or {}
    campaign, sid = state.ACTIVE_CAMPAIGN, str(data.get("sid") or "")
    profile = campaign_db.get_character(sid)
    if not profile:
        return jsonify({"status": "error", "message": "The character has no profile."}), 404
    data["profile"] = profile
    refused = bio_refusal(data)
    if refused: return refused
    faction = describe_faction(profile.get("Faction"), (state.LIVE_CONTEXTS.get(sid) or {}).get("factionID"))
    # The Library sends the campaign back with Keep, because the same npc_id can name another character in another campaign
    return bio_reply(data, recorded_history(sid), describe_race(profile.get("Race", "Unknown")), faction, campaign=campaign)

@bp.route('/read_bio', methods=['POST'])
def read_library_bio():
    """Answers in the shape of /write_bio, so Edit Bio in the Dialogue Library opens the same editor as Generate Bio."""
    data = request.get_json(silent=True) or {}
    campaign, sid = state.ACTIVE_CAMPAIGN, str(data.get("sid") or "")
    profile = campaign_db.get_character(sid)
    if not profile:
        return jsonify({"status": "error", "message": "The character has no profile."}), 404
    return jsonify({"status": "ok", "bio": {part: profile.get(part) or "" for part in BIO_PARTS}, "campaign": campaign})

@bp.route('/keep_bio', methods=['POST'])
def keep_library_bio():
    data = request.get_json(silent=True) or {}
    refused = campaign_write(data)
    if refused: return refused
    sid, texts = str(data.get("sid") or ""), data.get("bio") or {}
    profile = campaign_db.get_character(sid)
    if not profile:
        return jsonify({"status": "error", "message": "The character has no profile."}), 404
    # As on Campaign Canon, only a changed part ends the provisional state, so a Keep of the rolled texts still gets the
    # bio of the chat threshold, and that bio cannot overwrite the player's text
    bio = {part: str(texts[part]).strip() for part in BIO_PARTS if part in texts and str(texts[part]).strip() != (profile.get(part) or "").strip()}
    if bio:
        if not campaign_db.promote_profile(sid, bio):
            campaign_db.upsert_profile(sid, bio)
        logging.info(f"PROFILE: Stored the bio of {profile.get('Name', sid)} ({sid}) from the Dialogue Library.")
    return jsonify({"status": "ok"})
