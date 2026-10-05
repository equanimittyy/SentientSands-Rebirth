import json
import logging
import re
import threading
import time

from flask import Blueprint, jsonify, request

from chat import chat_prompt, rumors
from chat.bio import BIO_PARTS, generate_bio, recorded_history, write_bio
from chat.characters import animal_flag, get_character_data, npc_name, reported_sex, should_save_profile
from chat.llm import call_llm
from chat.memory import quiet_seconds
from chat.prompts import build_system_prompt, describe_faction, describe_npc, describe_race, fill_prompt, load_prompt_component, npc_scene, scene_values
from core import state
from core.game import context_dict, get_current_time_prefix, is_player_faction, note_faction, npc_serial, take_report
from core.routes import campaign_write
from core.settings import get_config_radii, load_settings
from store import campaign_db

bp = Blueprint("chat", __name__)

@bp.route('/ambient', methods=['POST'])
def ambient_event():
    logging.debug("HTTP: POST /ambient")
    data = request.json
    if not data: return jsonify({"status": "error"}), 400
    take_report(data.get('player_context'), data.get('events'))
    
    npcs_data = [npc for npc in data.get('npcs', []) if not (isinstance(npc, dict) and animal_flag(npc))]
    player_name = data.get('player', 'Drifter')
    
    logging.info(f"AMBIENT: Banter request ({len(npcs_data)} NPCs nearby)")
    
    # Without the animals, one NPC can remain, and banter needs two
    if len(npcs_data) < 2:
        return jsonify({"status": "ignore"})

    char_profiles = ""
    name_to_id = {}
    
    npc_limit = npcs_data[:12]

    recent_dialogue = []
    for npc in npc_limit:
        if isinstance(npc, dict):
            name = npc_name(npc)
            nid = npc.get('id', 0)
            name_to_id[name] = nid
            d = get_character_data(name, context=json.dumps(npc))
            
            if d.get("ConversationHistory"):
                recent_dialogue.extend(d["ConversationHistory"][-15:])

            # "Name|ID" lets the plugin map each banter line to the right NPC
            health = npc.get('health', 'Healthy')
            gear = npc.get('equipment', 'nothing notable')
            char_profiles += f"\n- {name}|{nid} ({reported_sex(npc.get('race'), npc.get('gender'))} {npc.get('race')}, {npc.get('faction')}) | Health: {health} | Gear: {gear} | Personality: {d.get('Personality') or ''} | Speech quirks: {d.get('SpeechQuirks') or ''}"
        else:
            name_to_id[npc] = 0
            d = get_character_data(npc, "")
            
            if d.get("ConversationHistory"):
                recent_dialogue.extend(d["ConversationHistory"][-15:])
                
            char_profiles += f"\n- {npc} (A traveler): {d.get('Personality') or ''} | Speech quirks: {d.get('SpeechQuirks') or ''}"

    unique_history = []
    seen_history = set()
    for line in reversed(recent_dialogue):
        if line not in seen_history:
            unique_history.append(line)
            seen_history.add(line)
    
    unique_history = list(reversed(unique_history))[-40:]
    
    history_block = ""
    if unique_history:
        history_block = "\nRECENT LOCAL DIALOGUE (DO NOT REPEAT TOPICS OR JOKES FROM HERE):\n" + "\n".join(unique_history)

    dynamic_system_prompt = build_system_prompt()
    scene = scene_values(state.PLAYER_CONTEXT, player_name, facing=False)

    ambient_system_prompt = f"""{dynamic_system_prompt}

{scene['location']}

{scene['rumors']}

{scene['player']}

[RADIANT DIALOGUE SYSTEM - BANTER MODE]
You are generating a short, atmospheric back-and-forth conversation (banter) between NPCs in Kenshi.
Kenshi is a post-apocalyptic, harsh world. NPCs should sound cynical, weary, or suspicious.

NEARBY CHARACTERS:
{char_profiles}

{history_block}

INSTRUCTIONS:
1. Select 2 or 3 characters from the list to have a short conversation.
2. Each participant MUST speak AT LEAST TWICE (total 4-6 lines).
3. DO NOT include the Player as a speaker and DO NOT let the Player participate.
4. The topic should be grounded in the harsh reality of Kenshi: local rumors, faction politics, the weather, gear maintenance, hunger, or a passing, often cynical comment about the 'drifter' (player) nearby.
5. Format MUST be 'Name|ID: Message' (e.g., 'Lungrot|1234: Wheeze...').
6. Only use characters from the NEARBY list.
7. Use the EXACT Name and ID strings provided in the list for the 'Name|ID' portion.
8. DO NOT use [ACTION] tags or any bracketed text. Radiant mode is for atmospheric dialogue only.
9. CRITICAL: Do NOT repeat topics, lines, or jokes found in the RECENT LOCAL DIALOGUE section. Talk about something new.
10. WORLD-CENTRIC: Remember that in Kenshi, the player is NOT the center of the universe. NPCs have their own lives, problems, and social circles. They should speak to and about each other about what is going on around them more often than they speak about the player.
"""
    
    messages = [
        {"role": "system", "content": ambient_system_prompt},
        {"role": "user", "content": "The world is quiet. Generate a radiant interaction."}
    ]
    
    content = call_llm("ambient", messages)
    if content:
        # The LLM sometimes emits [ACTION] tags despite the prompt forbidding them
        content = re.sub(r'\[\s*[A-Z_]+(?::\s*[^\]]+)?\s*\]', '', content).strip()
        
        content = content.replace('"', '').strip()
        
        lines = []
        for line in content.split('\n'):
            line = line.strip()
            if not line: continue
            
            if ':' in line:
                header, msg = line.split(':', 1)
                name_part = header.split('|')[0].strip()
                
                if name_part.lower() == player_name.lower():
                    continue

                if '|' not in header:
                    if name_part in name_to_id:
                        header = f"{name_part}|{name_to_id[name_part]}"
                
                lines.append(f"{header.strip()}: {msg.strip()}")
            elif '|' in line and len(line) < 100:
                continue
            else:
                if len(line) > 5: lines.append(line)
        
        final_text = "\n".join(lines)
        
        # Keyed by npc_id, because NPCs near the player can share a name; a banter line names its speaker by the serial
        memories = {}
        npc_ids = {}
        for npc_obj in npc_limit:
            if isinstance(npc_obj, dict) and npc_obj.get('npc_id'):
                memories[npc_obj['npc_id']] = get_character_data(npc_obj.get('name'), context=json.dumps(npc_obj))
                npc_ids[str(npc_obj.get('id'))] = npc_obj['npc_id']

        banter = []
        for line in lines:
            if ':' in line:
                header, msg = line.split(':', 1)
                speaker_name, _, serial = header.partition('|')
                speaker_name = speaker_name.strip()
                time_prefix = get_current_time_prefix()
                speaker_id = npc_ids.get(serial.strip())
                banter.append((f"{time_prefix}{speaker_name}: {msg.strip()}", speaker_id))

        for npc_id, d in memories.items():
            campaign_db.append_dialogue(npc_id, banter, d)

        logging.debug(f"AMBIENT: Banter: {final_text}")
        return jsonify({"status": "ok", "text": final_text})
    
    return jsonify({"status": "none"})

@bp.route('/chat', methods=['POST'])
def chat():
    started = time.monotonic()
    data = request.json
    logging.debug("HTTP: POST /chat")
    if not data: return jsonify({"text": "Error: No JSON data provided"}), 400

    # The squad member who talks
    speaker = context_dict(data.get('speaker'))
    take_report(speaker, data.get('events'))
    
    raw_npc = data.get('npc', 'Someone')
    raw_npcs = data.get('npcs', [])
    
    def register(raw):
        if not raw: return ""
        return raw.split('|')[0] if '|' in raw else raw

    primary_npc = register(raw_npc)
    npcs = [register(n) for n in raw_npcs]
    
    player_name = data.get('player', 'Drifter')
    mode = data.get('mode', 'talk')
    
    nearby = data.get('nearby', [])
    for n in nearby:
        npc_id = n.get('npc_id')
        if n.get('name') and npc_id:
            state.LIVE_CONTEXTS[npc_id] = {
                "race": n.get('race', 'Unknown'),
                "faction": n.get('faction', 'Unknown'),
                "gender": n.get('gender', 'Unknown'),
                "health": n.get('health'),
                "nearby": [x for x in nearby if x.get('npc_id') != npc_id],
                "player_dist": n.get('dist', 999.0)
            }

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
                        "/take_item [item], /spawn [Templ|Name|Desc], /relations [Fact] [n], /task [TASK]"
            return jsonify({"text": help_text, "actions": []}), 200
            
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
                return jsonify({"text": "[DEBUG] Error: Player inventory is empty or unknown.", "actions": []}), 200
        elif cmd == "drop": test_action = f"[ACTION: DROP_ITEM: {args}]"
        elif cmd == "spawn": test_action = f"[ACTION: SPAWN_ITEM: {args}]"
        elif cmd == "relations":
            rparts = args.rsplit(' ', 1)
            if len(rparts) == 2:
                test_action = f"[ACTION: FACTION_RELATIONS: {rparts[0].strip()}: {rparts[1].strip()}]"
        elif cmd == "task": test_action = f"[TASK: {args.upper()}]"
        
        if test_action:
            logging.info(f"CHAT: Test command {cmd} -> {test_action}")
            return jsonify({
                "text": f"[DEBUG] Executing test command: {test_action}",
                "actions": [test_action]
            }), 200

    if not player_message:
        return jsonify({"text": "...", "actions": []}), 200

    context = data.get('context', '')
    ctx_dict = context_dict(context)
    primary_id = ctx_dict.get('npc_id')

    # A new profile and the scene read race/faction from state.LIVE_CONTEXTS
    if primary_npc and context:
        try:
            if ctx_dict:
                note_faction(ctx_dict)
            if primary_id:
                # Merge rather than replace, to keep the nearby list and other tracked fields
                target = state.LIVE_CONTEXTS.setdefault(ctx_dict['npc_id'], {})
                if ctx_dict.get('race'): target["race"] = ctx_dict.get('race')
                if ctx_dict.get('faction'): target["faction"] = ctx_dict.get('faction')
                if ctx_dict.get('factionID'): target["factionID"] = ctx_dict.get('factionID')
                if ctx_dict.get('origin_faction'): target["origin_faction"] = ctx_dict.get('origin_faction')
                if ctx_dict.get('health'): target["health"] = ctx_dict.get('health')

                if "nearby" in ctx_dict:
                    target["nearby"] = ctx_dict["nearby"]

                if "dist" in ctx_dict:
                    target["player_dist"] = ctx_dict["dist"]
        except Exception as e:
            logging.error(f"CHAT: Cannot register the context of the chat target: {e}")

    if primary_id:
        primary_npc = npc_name(ctx_dict)

    speaker_id = speaker.get("npc_id")
    # Stores a profile for the speaker, whom the listeners leave out
    if speaker_id:
        npc_name(speaker)
    thread_key = (speaker_id, primary_id, mode)
    timeout = quiet_seconds()
    with state.THREAD_LOCK:
        current_thread = state.CURRENT_THREAD.get("id") if state.CURRENT_THREAD.get("key") == thread_key and time.monotonic() - state.CURRENT_THREAD["replied"] < timeout else None
        state.restart_quiet_clock()

    _, talk_radius, yell_radius = get_config_radii()
    # A whisper is one-on-one: nobody overhears
    radius = {"talk": talk_radius, "yell": yell_radius}.get(mode)

    # Keyed by npc_id, because NPCs near the player can share a name, for example two Dust Bandits
    listeners = {primary_id: (primary_npc, context)}
    in_squad = {primary_id: bool(ctx_dict.get("in_player_faction") or is_player_faction(ctx_dict.get("faction"), ctx_dict.get("factionID"))), speaker_id: True}
    for n in chat_prompt.overhearers(nearby, radius, {primary_id, speaker.get("npc_id")}):
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

    if animal:
        system_prompt = load_prompt_component("prompt_animal_system.txt")
        final_instruction = f"Reply as {primary_npc} with one action or sound in asterisks, and no words."
        judgment = ""
    else:
        system_prompt = build_system_prompt()
        judgment = "JUDGMENT: End every reply with [JUDGMENT: n], from -5 (the player was hostile or insulting) to 5 (the player was friendly or respectful); 0 is neutral."
        final_instruction = f"Reply as {primary_npc}{', quietly' if mode == 'whisper' else ''}.{' End with [JUDGMENT: n].' if judgment else ''}"

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
    memories = chat_prompt.memories_block(campaign_db.memories_of(primary_id, chat_prompt.MEMORY_LIMIT), primary_id)
    system = fill_prompt("prompt_chat_template.txt", system_prompt=system_prompt, judgment=judgment, primary_npc=primary_npc, npc_profiles=describe_npc(primary_npc, primary_data, primary_id), scene=scene, memories=memories)
    turn = fill_prompt("prompt_chat_turn.txt", player_line=full_player_entry, final_instruction=final_instruction)
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
            thread_id = campaign_db.join_thread(current_thread, members, campaign_db.game_time(time_prefix))
            state.CURRENT_THREAD.update(key=thread_key, id=thread_id, replied=time.monotonic())
        for npc_id, name, new_lines in copies:
            campaign_db.append_dialogue(npc_id, new_lines, char_datas[npc_id], thread_id)
            if npc_id == primary_id and judgment_value:
                # Applied as a delta at save time: the profile read before the LLM call can be stale by then
                new_rel = campaign_db.change_relation(npc_id, judgment_value)
                logging.info(f"RELATION: {name} personal relation is now {new_rel} (judgment={judgment_value})")

        interactions = campaign_db.count_interaction(primary_id) if primary_id else None
        threshold = load_settings()["bio_interactions"]
        if interactions is not None and threshold and interactions >= threshold:
            # In the background, so the reply does not wait for a second LLM call
            threading.Thread(target=generate_bio, args=(primary_id,), daemon=True).start()

        logging.info(f'CHAT: {mode_tag}{player_name} to {primary_npc}: "{player_message}" | {primary_npc}: "{content}" ({time.monotonic() - started:.1f} s)')
        # The plugin takes the text before a first colon as the speaker. It finds the NPC by the serial after the bar,
        # because its request named the NPC before a rename.
        serial = npc_serial(primary_id)
        return jsonify({"text": f"{primary_npc}|{serial}: {content}" if serial else f"{primary_npc}: {content}", "actions": []})
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

@bp.route('/write_rumor', methods=['POST'])
def write_events_rumor():
    data = request.get_json(silent=True) or {}
    # The World Events Log sends the campaign back with Keep, because the same notable event ID can name another deed in another campaign
    return rumor_reply(data.get("notable"), str(data.get("instruction") or ""), campaign=state.ACTIVE_CAMPAIGN)

@bp.route('/read_rumor', methods=['POST'])
def read_events_rumor():
    """Answers in the shape of /write_rumor, so Edit Rumor in the World Events Log opens the same editor as Generate Rumor."""
    data = request.get_json(silent=True) or {}
    rumor = next((rumor for rumor in campaign_db.rumors() if str(rumor["notable_id"]) == str(data.get("notable"))), None)
    if not rumor:
        return jsonify({"status": "error", "message": "The event has no rumor yet."}), 404
    return jsonify({"status": "ok", "text": rumor["text"], "campaign": state.ACTIVE_CAMPAIGN})

@bp.route('/keep_rumor', methods=['POST'])
def keep_events_rumor():
    return keep_rumor_reply(request.get_json(silent=True) or {})

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
