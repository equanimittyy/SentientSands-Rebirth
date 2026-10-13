import json
import logging
import queue
import random
import re
import threading
import time

from flask import Blueprint, jsonify, request

from chat import action_dialogue, background, chat_prompt, chat_window, offers, radiant, reply_text, retrieval, rumors, scene_text
from chat.bio import BIO_PARTS, generate_bio, recorded_history, write_bio
from chat.characters import animal_flag, get_character_data, npc_name, should_save_profile
from chat.llm import call_llm
from chat.memory import quiet_seconds
from chat.prompts import PROMPT_RUMORS, build_system_prompt, describe_faction, describe_npc, describe_persona, describe_race, fill_prompt, find_location, language_instruction, npc_scene, scene_values
from core import state, world_events
from core.game import context_dict, get_current_time_prefix, is_player_faction, note_faction, take_report
from core.pipe import send_to_pipe
from core.routes import campaign_write
from core.settings import get_config_radii, load_settings
from store import campaign_db

bp = Blueprint("chat", __name__)

_REPLIES = queue.Queue()
# A radiant conversation holds it from its call to its last line, so a chat reply waits for it and a second one cannot start
_STAGE = threading.Lock()
_last_line = 0.0
THINK_SHARE = 0.4

@bp.route('/radiant', methods=['POST'])
def radiant_conversation():
    logging.debug("HTTP: POST /radiant")
    data = request.json
    if not data: return jsonify({"status": "error"}), 400
    center = context_dict(data.get('player_context'))
    take_report(center, data.get('events'), data.get('changed_towns'))
    rumor_texts = [rumor["text"] for rumor in campaign_db.rumors()[-PROMPT_RUMORS:]]
    if state.PENDING_OFFER:
        logging.info("RADIANT: An offer waits for the player's answer, so nobody talks.")
        return jsonify({"status": "ignore"})
    npcs = radiant.npc_group(data.get('npcs') or [], campaign_db.character_exists)
    npc_talk = radiant.npc_talk(npcs, rumor_texts, load_settings()["npc_radiant_chance"])
    participants = {str(npc['id']): npc for npc in (npcs if npc_talk else data.get('participants') or [])}
    if not participants:
        logging.info("RADIANT: Too few of the player's characters stand together, so nobody talks.")
        return jsonify({"status": "ignore"})
    npc_ids = [npc['npc_id'] for npc in participants.values()]

    if world_events.fought_recently(npc_ids, center):
        logging.info(f"RADIANT: A participant fought within the last {world_events.FIGHT_QUIET_MINUTES // 60} game hours, so nobody talks.")
        return jsonify({"status": "ignore"})

    names, profiles = {}, {}
    for key, npc in participants.items():
        # The faction of a participant is its identity faction, not the current faction that Campaign Canon shows
        merge_live_context({field: value for field, value in npc.items() if field != 'faction'})
        names[key] = npc_name(npc)
        profiles[key] = get_character_data(names[key], context=json.dumps(npc))

    environment = center.get("environment") or {}
    memory_id = None
    if npc_talk:
        topic = random.choice(rumor_texts)
    else:
        location = find_location(environment["town_name"]) if environment.get("town_name") else None
        topic, memory_id = radiant.topic(campaign_db.shared_memories(npc_ids), environment, rumor_texts, location=location)
    if not topic:
        logging.info("RADIANT: No topic, so nobody talks.")
        return jsonify({"status": "ignore"})

    if not _STAGE.acquire(blocking=False):
        logging.info("RADIANT: A conversation plays, so nobody else talks.")
        return jsonify({"status": "ignore"})
    playing = False
    try:
        descriptions = [
            f"{describe_npc(f'{names[key]}|{key}', profiles[key], npc['npc_id'], persona=False)}\nHEALTH: {npc.get('health') or 'Unknown'}\nGEAR: {npc.get('equipment') or 'nothing notable'}"
            for key, npc in participants.items()
        ]
        length, order = radiant.plan(list(participants))
        values = {"place": scene_text.location_text(environment, "They"), "participants": "\n\n".join(descriptions), "length": length}
        if npc_talk:
            frame = fill_prompt("prompt_radiant_npc.txt", rumor=topic, **values)
        else:
            known = radiant.acquaintance({npc['npc_id']: names[key] for key, npc in participants.items()}, {npc_id: campaign_db.thread_partners(npc_id) for npc_id in npc_ids})
            frame = fill_prompt("prompt_radiant.txt", acquaintance=known, topic=topic, **values)
        logging.info(f"RADIANT: {', '.join(names.values())} talk{' among the NPCs' if npc_talk else ''}. Topic: {topic}")
        if memory_id:
            campaign_db.use_memories([memory_id], campaign_db.game_time(get_current_time_prefix()))
        conversation = {
            "system": build_system_prompt(reply_rules=False), "frame": frame, "order": order, "names": names,
            "personas": {key: describe_persona(profiles[key]) for key in participants}, "participants": participants,
            "profiles": profiles, "npc_talk": npc_talk, "time_prefix": get_current_time_prefix(),
            "place": scene_text.location_name(center), "campaign": state.ACTIVE_CAMPAIGN,
        }
        # Before the start: a thread that ends at once releases the stage, and the finally would release it again
        playing = True
        threading.Thread(target=play_radiant, args=(conversation,), daemon=True).start()
        return jsonify({"status": "ok"})
    finally:
        if not playing:
            _STAGE.release()

def say(lines, actions=(), think=False):
    """Sends the actions, then each line at least the dialogue delay after the line before it, also when that line ended an
    earlier conversation. The plugin shows a line when it arrives, so the server alone paces every conversation. A pause of
    the game does not stop the delay. The actions go first, so an AI state change cannot clear a bubble that is already up.
    With think, the speaker of each line shows "..." for the last THINK_SHARE of the delay before it."""
    global _last_line
    for action in actions:
        send_to_pipe(f"NPC_ACTION: {action}")
    delay = load_settings()["dialogue_speed_seconds"]
    for line in lines:
        due = _last_line + delay
        if think:
            time.sleep(max(0.0, due - THINK_SHARE * delay - time.monotonic()))
            send_to_pipe(f"NPC_SAY: {line.split(':', 1)[0]}: ...")
            due = max(due, time.monotonic() + THINK_SHARE * delay)
        time.sleep(max(0.0, due - time.monotonic()))
        send_to_pipe(f"NPC_SAY: {line}")
        _last_line = time.monotonic()

def play_radiant(conversation):
    """Writes each line with its own call, which holds the persona of its speaker alone, and shows it, so the next call
    runs while the line is up. The prompt grows only at the end of THE TALK SO FAR, so each call reuses the provider's
    cache of the call before it up to the newest line. A call without a line ends the talk, and the lines so far count."""
    names, spoken = conversation["names"], []
    try:
        for index, (speaker, _) in enumerate(conversation["order"]):
            label = f"{names[speaker]}|{speaker}"
            text = write_line(conversation, spoken, index)
            if not text:
                logging.warning(f"RADIANT: The LLM wrote no line for {names[speaker]}, so the talk ends.")
                break
            # The same npc_id can name another character in another campaign
            if state.ACTIVE_CAMPAIGN != conversation["campaign"]:
                logging.info("RADIANT: The active campaign changed, so the talk ends, and nobody remembers it.")
                return
            say([f"{label}: {text}"], think=True)
            spoken.append((speaker, text))
        if spoken:
            remember_radiant(conversation, spoken)
    except Exception as e:
        # A thread, where nothing else would log the error
        logging.error(f"RADIANT: The conversation failed: {e}")
    finally:
        _STAGE.release()

def write_line(conversation, spoken, index):
    """The words of line index of the order, or "" when the LLM wrote none. spoken holds the (handle key, text) of the lines
    before it."""
    names, order = conversation["names"], conversation["order"]
    speaker = order[index][0]
    prompt = conversation["frame"] + "\n\n" + fill_prompt("prompt_radiant_line.txt", talk=radiant.talk(spoken, names), speaker=f"{names[speaker]}|{speaker}", persona=conversation["personas"][speaker], turn=radiant.turn(index, order, names))
    return reply_text.spoken(call_llm("radiant", [{"role": "system", "content": conversation["system"]}, {"role": "user", "content": prompt}]) or "", *radiant.voices(names, speaker))

def play_yell(yell):
    """The replies of a yell after the first one, each written as a radiant line while the line before it shows. It runs in
    reply_loop, which holds the stage, so no other reply plays between them. Each line joins the chat thread when it is
    said, so a quick next yell already sees it."""
    names, ids, spoken = yell["names"], yell["ids"], yell["spoken"]
    for index in range(len(spoken), len(yell["order"])):
        speaker, addressee = yell["order"][index]
        text = write_line(yell, spoken, index)
        if not text:
            logging.warning(f"CHAT: The LLM wrote no line for {names[speaker]}, so the yell ends.")
            return
        if state.ACTIVE_CAMPAIGN != yell["campaign"]:
            logging.info("CHAT: The active campaign changed, so the yell ends.")
            return
        say([f"{names[speaker]}|{speaker}: {text}"], think=True)
        spoken.append((speaker, text))
        speaker_id = ids[speaker]
        if speaker_id in yell["copies"]:
            campaign_db.join_thread(yell["thread"], [(speaker_id, "speaker", yell["in_squad"].get(speaker_id, False))], campaign_db.game_time(yell["time_prefix"]), exchange=False)
        for npc_id, profile in yell["copies"].items():
            line = chat_prompt.heard_line(yell["time_prefix"], npc_id, (speaker_id, names[speaker]), (ids[addressee], names[addressee]), text)
            campaign_db.append_dialogue(npc_id, [(line, speaker_id)], profile, yell["thread"])
        with state.THREAD_LOCK:
            if state.CURRENT_THREAD.get("id") == yell["thread"]:
                state.CURRENT_THREAD["replied"] = time.monotonic()
        state.restart_quiet_clock()
        logging.info(f'CHAT: {names[speaker]} to {names[addressee]}: "{text}"')

def remember_radiant(conversation, spoken):
    names, participants, time_prefix = conversation["names"], conversation["participants"], conversation["time_prefix"]
    spoke = {key for key, _ in spoken}
    members = [(npc['npc_id'], "speaker" if key in spoke else "overheard", not conversation["npc_talk"]) for key, npc in participants.items()]
    thread_id = campaign_db.join_thread(None, members, campaign_db.game_time(time_prefix), conversation["place"], exchange=False, kinds=("radiant",))
    stored = [(f"{time_prefix}{names[key]}: {text}", participants[key]['npc_id']) for key, text in spoken]
    for key, npc in participants.items():
        campaign_db.append_dialogue(npc['npc_id'], stored, conversation["profiles"][key], thread_id)
    state.LAST_RADIANT = time.monotonic()
    logging.info("RADIANT: " + " | ".join(f'{names[key]}: "{text}"' for key, text in spoken))

def play_lines(lines, actions=(), after=(), then=None):
    """Queues a chat reply, which plays after every reply before it and after a radiant conversation that holds the stage.
    The pipe messages of after go out after the last line, so the popup of an offer opens when the NPC has spoken. then
    runs after them on the stage, so the next reply waits for it."""
    _REPLIES.put((lines, actions, after, then))

def reply_loop():
    while True:
        lines, actions, after, then = _REPLIES.get()
        try:
            with _STAGE:
                say(lines, actions)
                for message in after:
                    send_to_pipe(message)
                if then:
                    then()
        except Exception as e:
            # An error must not end the loop, or no later chat reply would play
            logging.error(f"CHAT: The lines of a reply failed: {e}")

def notify(text):
    send_to_pipe(f"NOTIFY: {text}")

def end_thread():
    with state.THREAD_LOCK:
        state.CURRENT_THREAD.clear()

def thread_of(thread_key, speaker_id):
    """The ID and the action dialogue of the current chat thread for a line, or (None, None) for a new chat thread. Call it
    under THREAD_LOCK. An action dialogue belongs to its speaker, so a line of another squad member starts a new chat thread."""
    live = state.CURRENT_THREAD
    if live.get("key") != thread_key or time.monotonic() - live["replied"] >= quiet_seconds():
        return None, None
    action = live.get("action")
    if action and action["speaker"] != speaker_id:
        return None, None
    return live.get("id"), action

def record_deal(thread_id, line, parties, location, kinds=()):
    """Writes the line of a deal into the chat thread of each party, (npc_id, name, context, in_player_faction), as an
    exchange, so that a chat thread that ends in a deal is not deleted as a thread of one exchange. Returns the thread ID."""
    time_prefix = get_current_time_prefix()
    thread_id = campaign_db.join_thread(thread_id, [(npc_id, "speaker", in_faction) for npc_id, _, _, in_faction in parties], campaign_db.game_time(time_prefix), location, kinds=kinds)
    for npc_id, name, context, _ in parties:
        campaign_db.append_dialogue(npc_id, [(f"{time_prefix}{line}", None)], get_character_data(name, context), thread_id)
    return thread_id

@bp.route('/offer', methods=['POST'])
def answer_offer():
    """The player's answer to an offer: accept, decline, cancel after a save load, a knockout, or a death, or failed when
    the plugin found that a side no longer holds its part of the deal. A decline keeps the action dialogue, and the plugin
    sends the player's reply as the next chat line. show sends the popup again, because the pipe drops a message that
    finds no pipe instance in time."""
    data = request.json or {}
    answer = data.get("answer")
    if answer == "show":
        send_to_pipe(state.PENDING_OFFER["command"] if state.PENDING_OFFER else "CMD: OFFER_GONE")
        return jsonify({"status": "ok"})
    held = offers.take(data.get("id"))
    if not held:
        logging.info(f"ACTION: The answer {answer} names an offer that the server no longer holds.")
        if answer == "accept":
            end_thread()
            npc = data.get("npc")
            notify(f"{npc}'s offer no longer stands." if npc else "The offer no longer stands.")
        return jsonify({"status": "gone"})
    offer, npc, player = held["offer"], held["npc"], held["player"]
    if answer == "accept":
        record_deal(held["thread"], offers.accepted_line(offer, npc, player), held["parties"], held["location"])
        terms = offers.hire_terms(offer)
        if terms:
            campaign_db.set_hire(held["npc_id"], *terms)
        end_thread()
        voice = held["voice"]
        play_lines([f"{voice}: {action_dialogue.end_line(offers.ACCEPT_LINES[offer['category']])}"], offers.voiced(offer, voice))
        logging.info(f"ACTION: {player} accepted: {offers.popup_text(offer, npc, player)}")
        if offer.get("charity"):
            state.CHARITY_DAYS[held["npc_id"]] = held["day"]
        if offer.get("gift"):
            relation = campaign_db.change_relation(held["npc_id"], offer["gift"])
            notify(f"{npc} appreciates the gift.")
            logging.info(f"RELATION: {npc} personal relation is now {relation} (gift={offer['gift']})")
    elif answer == "decline":
        record_deal(held["thread"], offers.declined_line(offer, npc, player), held["parties"], held["location"])
        with state.THREAD_LOCK:
            # The player can take longer than the timeout to answer, and the reply still belongs to this action dialogue
            if state.CURRENT_THREAD:
                state.CURRENT_THREAD["replied"] = time.monotonic()
        logging.info(f"ACTION: {player} declined: {offers.popup_text(offer, npc, player)}")
    else:
        end_thread()
        logging.info(f"ACTION: The offer of {npc} ended: {answer}.")
    return jsonify({"status": "ok"})

@bp.route('/hire_terms', methods=['POST'])
def hire_terms():
    """The terms of the hire of the NPC, with the text of its renewal popup. A hire of the game's own dialogues has no terms,
    and it expires as in the game."""
    data = request.json or {}
    terms = campaign_db.hire(data.get("npc_id"))
    if not terms:
        return jsonify({"status": "none"})
    hours, fee = terms
    return jsonify({"status": "ok", "hours": hours, "fee": fee, "text": offers.renewal_text(data.get("npc"), hours, fee)})

@bp.route('/hire_end', methods=['POST'])
def hire_end():
    data = request.json or {}
    campaign_db.end_hire(data.get("npc_id"))
    logging.info(f"ACTION: The hire of {data.get('npc')} ended.")
    return jsonify({"status": "ok"})

@bp.route('/chat_thread', methods=['POST'])
def chat_thread():
    """The open chat thread with the NPC for the chat window."""
    thread = chat_window.open_thread((request.get_json(silent=True) or {}).get("npc_id"), quiet_seconds())
    return jsonify({"status": "ok", "open": thread is not None, **(thread or {})})

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
    target_key = raw_npcs[0].partition('|')[2] if raw_npcs else ""
    speaker_key = str(data.get('speaker_key') or "")
    window = data.get('barter')
    primary_id = thread_id = None

    def voice():
        # The plugin takes the text before a first colon as the speaker. It finds the NPC by the handle key after the bar,
        # because its request named the NPC before a rename, and the actions act on the squad member of the key after >.
        return f"{primary_npc}|{target_key}{f'>{speaker_key}' if speaker_key else ''}"

    def reply(*texts, actions=(), action_open=False, after=(), then=None):
        # After the lines, so the barter window shows them once they are said
        turn = [f"CMD: BARTER_TURN: {int(action_open)}\n{chat_window.thread_lines(primary_id, thread_id) if thread_id else ''}"] if window else []
        play_lines([f"{voice()}: {text}" for text in texts], [f"{voice()}: {action}" for action in actions], [*after, *turn], then)
        # The plugin takes no new line while the reply to a line of an open action dialogue is pending, or while an offer waits
        return jsonify({"status": "ok", "action_dialogue": action_open, "offer": bool(after)})
    
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
        if cmd == "recruit": test_action = "[ACTION: JOIN_PARTY]"
        elif cmd == "liberate": test_action = "[ACTION: FREE_PLAYER]"
        elif cmd == "raid": test_action = f"[ACTION: RAID_TOWN: {args}]"
        elif cmd == "travel": test_action = f"[ACTION: TRAVEL_TO_TARGET_TOWN: {args}]"
        elif cmd in ("stock", "firstaid", "follow"):
            if cmd == "follow" and args and not re.fullmatch(r"\d+|end|\d+-\S+", args):
                return reply("[DEBUG] /follow alone logs the contract of the target. /follow [hours] or /follow [line ID] starts one, and /follow end runs it out.")
            if cmd == "follow" and args:
                npc_id = context_dict(data.get('context', '')).get('npc_id')
                # Only a hire of hours has terms that a renewal repeats
                if args.isdigit():
                    campaign_db.set_hire(npc_id, int(args), 0)
                elif args == "end" and campaign_db.hire(npc_id):
                    logging.info("CHAT: Test command follow -> [ACTION: EXPIRE_HIRE]")
                    return reply("[DEBUG] Executing test command: follow expiry", actions=["[ACTION: EXPIRE_HIRE]"])
                else:
                    campaign_db.end_hire(npc_id)
            probe = f"[ACTION: PROBE: {'hire' if cmd == 'follow' else cmd}{': ' + args if args else ''}]"
            logging.info(f"CHAT: Test command {cmd} -> {probe}")
            # The plugin also runs a tag in a spoken line, so an echo of the tag would run the probe twice
            return reply(f"[DEBUG] Executing test command: {cmd} probe", actions=[probe])
        
        if test_action:
            logging.info(f"CHAT: Test command {cmd} -> {test_action}")
            return reply(f"[DEBUG] Executing test command: {cmd} {args}".rstrip(), actions=[test_action])

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
    # A yell at the speaker itself is a yell at everyone
    self_talk = bool(speaker_id) and speaker_id == primary_id and mode != "yell"
    # Not the speaker, so the squad members that take turns with the NPC share one thread and one memory. Talk with itself
    # stays apart, or the memory would take the words of the NPC to itself as words to a squad member.
    thread_key = (primary_id, mode, "self") if self_talk else (primary_id, mode)
    with state.THREAD_LOCK:
        current_thread, action = thread_of(thread_key, speaker_id)
        state.restart_quiet_clock()
    thread_id = current_thread
    if state.PENDING_OFFER:
        notify(f"Answer {state.PENDING_OFFER['npc']}'s offer first.")
        send_to_pipe(state.PENDING_OFFER["command"])
        return reply(action_open=bool(action))

    kind, category, text = action_dialogue.parse(player_message)
    npc_in_faction = bool(ctx_dict.get("in_player_faction") or is_player_faction(ctx_dict.get("faction"), ctx_dict.get("factionID")))
    blocked = action_dialogue.knockout_block(ctx_dict, speaker, primary_npc, player_name)
    chat_reason = None
    if kind in ("category", "classify") and not blocked:
        chat_reason = action_dialogue.mark_chat(ctx_dict, npc_in_faction)
    if kind == "category" and not blocked and not chat_reason:
        blocked = action_dialogue.gate_block(category, ctx_dict, speaker, primary_npc)
        chat_reason = action_dialogue.plain_chat(category, ctx_dict, speaker)
    if blocked:
        logging.info(f"ACTION: Blocked the line of {player_name} to {primary_npc}: {blocked}")
        notify(blocked)
        return reply(action_open=bool(action))
    if kind == "classify" and not chat_reason:
        listed = action_dialogue.choices(ctx_dict, speaker, primary_npc)
        prompt = fill_prompt("prompt_action_classify.txt", line=text, choices=action_dialogue.choice_list(listed))
        category = action_dialogue.chosen(call_llm("action", [{"role": "user", "content": prompt}]), listed)
        logging.info(f"ACTION: Classified the line of {player_name} to {primary_npc} as {category or 'no category'}.")
        chat_reason = action_dialogue.plain_chat(category, ctx_dict, speaker)
    if chat_reason:
        chat_reason = chat_reason.format(player=player_name)
        logging.info(f"ACTION: The line of {player_name} to {primary_npc} goes to plain chat: {chat_reason}")
        kind, category, player_message = None, None, text
    if kind == "failure" or (kind == "classify" and not category):
        end_thread()
        notify(f"{primary_npc} didn't understand what you meant.")
        return reply()
    if kind == "end":
        end_thread()
        logging.info(f"ACTION: {player_name} ended the conversation with {primary_npc}.")
        return reply(action_dialogue.end_line("end"))
    if kind:
        player_message = text
    elif action and not chat_reason:
        category = action["category"]
    category = action_dialogue.runs_as(category, ctx_dict, speaker)
    npc_party = (primary_id, primary_npc, context, npc_in_faction)
    speaker_party = (speaker_id, player_name, json.dumps(speaker), True)
    location = scene_text.location_name(speaker or state.PLAYER_CONTEXT)
    if category == "DISMISS":
        # The NPC never refuses, so a dismissal needs no call
        end_thread()
        record_deal(current_thread, f"({player_name} dismissed {primary_npc}.)", [npc_party, speaker_party], location, (mode, "dismiss"))
        campaign_db.end_hire(primary_id)
        logging.info(f"ACTION: {player_name} dismissed {primary_npc}.")
        return reply(action_dialogue.end_line("dismiss_end"), actions=["[ACTION: END_HIRE]"])

    yell = mode == "yell" and not category
    if yell:
        # One thread for all plain yells, so the NPCs that answered one yell are the ones already speaking at the next
        thread_key = (None, mode)
        with state.THREAD_LOCK:
            current_thread, _ = thread_of(thread_key, speaker_id)

    talk_radius, yell_radius = get_config_radii()
    # A whisper is one-on-one: nobody overhears
    radius = {"talk": talk_radius, "yell": yell_radius}.get(mode)

    # Keyed by npc_id, because NPCs near the player can share a name, for example two Dust Bandits
    listeners = {primary_id: (primary_npc, context)}
    in_squad = {primary_id: npc_in_faction, speaker_id: True}
    heard = chat_prompt.overhearers(nearby, radius, {primary_id, speaker.get("npc_id")})
    for n in heard:
        merge_live_context(n)
        listeners[n["npc_id"]] = (npc_name(n), json.dumps(n))
        in_squad[n["npc_id"]] = bool(n.get("in_player_faction") or is_player_faction(n.get("faction"), n.get("factionID")))

    target = (primary_id, primary_npc)
    order = None
    if yell and primary_id and speaker_id and (npc_in_faction or not animal_flag(ctx_dict)):
        crowd = {target_key: ctx_dict, **{str(n["id"]): n for n in heard if radiant.can_answer(n)}}
        # Only the player's speaker talks for the squad, so a yell at the speaker or at a squad member gets only the replies of bystanders
        answering = [key for key in crowd if key != target_key or not npc_in_faction]
        if not answering:
            logging.info(f"CHAT: No one outside the squad can answer the yell of {player_name}.")
            return reply()
        speaking = {npc_id for npc_id, _, role, _ in campaign_db.thread_members([current_thread]).get(current_thread, []) if role == "speaker"} if current_thread else set()
        aliases = {key: (listeners[npc["npc_id"]][0], npc.get("name")) for key, npc in crowd.items()}
        favoured = {target_key} | radiant.named(player_message, aliases) | {key for key, npc in crowd.items() if npc["npc_id"] in speaking}
        order = radiant.yell_turns(answering, favoured, speaker_key, target_key)
        if primary_id == speaker_id:
            # A yell at everyone counts as spoken only to the NPCs that answer it, so a bystander that stays quiet overhears it
            target = None
            answerers = {crowd[key]["npc_id"] for key, _ in order[1:]}
        first = order[1][0]
        if first != target_key:
            ctx_dict, raw_npc, target_key = crowd[first], crowd[first]["name"], first
            primary_id = ctx_dict["npc_id"]
            primary_npc = listeners[primary_id][0]
            # The reason judges the target, so it does not hold for another NPC
            chat_reason = None

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
    barter = window is not None and category == "BARTER"
    mates = window.get("squad") if barter else None

    # A rule that rated the player's politeness let a scornful NPC warm up with each apology
    judgment = "" if self_talk else "JUDGMENT: End every reply with [JUDGMENT: n], the change that the player's line makes to how you feel about the player, from -5 (it angers, frightens, hurts, or offends you) to 5 (it pleases you); 0 is no change. Judge by your personality, not by how polite the line is."
    judged_end = "" if self_talk else " End with [JUDGMENT: n]."
    action_rules = ""
    if animal:
        system_prompt = fill_prompt("prompt_animal_system.txt", language_instruction=language_instruction())
        final_instruction = f"Reply as {primary_npc} with one action or sound in asterisks, and no words.{judged_end}"
    else:
        system_prompt = build_system_prompt()
        if category:
            goods = {"stock": offers.stocktake(ctx_dict)} if category == "BARTER" else {}
            # The request of the barter window names no offer tag, because only the player sets a deal that the window can accept
            request_prompt = ("prompt_action_barter_table.txt" if barter
                              else "prompt_action_follow_mercenary.txt" if category == "FOLLOW" and action_dialogue.mercenary_rate(ctx_dict)
                              else f"prompt_action_{category.lower()}.txt")
            wanted = fill_prompt(request_prompt, speaker=player_name, **goods)
            action_rules = fill_prompt("prompt_action_rules.txt", request=wanted)
        final_instruction = f"{'Answer yourself' if self_talk else 'Reply'} as {primary_npc}{', quietly' if mode == 'whisper' else ''}.{judged_end}"

    mode_tag = {"whisper": "(Whispered) ", "yell": "(Yelled) "}.get(mode, "")
    time_prefix = get_current_time_prefix()
    full_player_entry = chat_prompt.heard_line(time_prefix, primary_id, (speaker_id, player_name), target or (primary_id, primary_npc), player_message, mode_tag)

    live = state.LIVE_CONTEXTS.get(primary_id, {})
    rows = campaign_db.dialogue(primary_id)
    # Only earlier threads count, so the scene of a first meeting, and the prompt cache with it, holds for the whole conversation
    earlier = [row for row in rows if current_thread is None or row[2] != current_thread]
    spoken = chat_prompt.spoken_with(earlier, campaign_db.thread_partners(primary_id, current_thread), primary_id)
    met = speaker_id in spoken
    current_members = campaign_db.thread_members([current_thread]).get(current_thread, []) if current_thread else []
    partners = tuple(npc_id for npc_id, _, role, _ in current_members if role == "speaker" and npc_id not in (primary_id, speaker_id))
    conversation = (speaker.get("npc_id"), primary_id or primary_npc, primary_npc, live.get("faction"), met, partners)
    scene = state.CONVERSATION_SCENE.get(conversation)
    if scene is None:
        others = [npc_id for npc_id in spoken if npc_id != speaker_id]
        names = campaign_db.names_of(others)
        squad = set(state.PLAYER_CONTEXT.get("squad") or [])
        player = speaker or state.PLAYER_CONTEXT
        scene = fill_prompt(
            "prompt_chat_scene.txt",
            **scene_values(player, player_name, self_talk),
            npc=npc_scene(ctx_dict or primary_data, primary_data, player_name, met, [names[i] for i in others if i not in partners and names.get(i) in squad],
                          [names[i] for i in partners if names.get(i) in squad], player.get("stats") or {}, self_talk),
        )
        state.CONVERSATION_SCENE.clear()
        state.CONVERSATION_SCENE[conversation] = scene
    # Read on each turn, not with the scene, so a memory that the distillation writes during a conversation reaches the next turn
    starting = chat_prompt.starting_memories(campaign_db.memories_of(primary_id), primary_id)
    system = fill_prompt("prompt_chat_template.txt", system_prompt=system_prompt, judgment=judgment, primary_npc=primary_npc, npc_profiles=describe_npc(primary_npc, primary_data, primary_id), scene=scene, memories=chat_prompt.memories_block(starting, primary_id), action_rules=action_rules)
    pair = (speaker_id, primary_id)
    cooldown = load_settings()["retrieval_cooldown_turns"]
    recent_turns = state.RECENT_HITS.get(pair, [])
    found_memories, found_rumors, found_entries = [], [], []
    # An animal replies only in actions
    if not animal:
        environment = ctx_dict.get("environment") or {}
        found_memories, found_rumors, found_entries, _ = background.search(
            player_message, background.campaign_lore(), primary_id, primary_data, live.get("factionID"), (speaker or state.PLAYER_CONTEXT).get("race"),
            environment.get("town_name"), environment.get("zone_name"), retrieval.held(recent_turns, cooldown),
        )
    background_block = chat_prompt.background_block(
        [hit["record"]["memory"] for hit in found_memories], [hit["record"]["rumor"] for hit in found_rumors], [hit["record"] for hit in found_entries if not hit["travels"]], primary_id, player_name,
        [hit["record"] for hit in found_entries if hit["travels"]], state.PLAYER_CONTEXT.get("day"),
    )
    campaign_db.use_memories([memory["id"] for memory in starting] + [hit["record"]["memory"]["id"] for hit in found_memories], campaign_db.game_time(time_prefix))
    if category:
        relation = primary_data.get("Relation")
        lean = action_dialogue.lean(category, ctx_dict, speaker, relation, nearby, mode)
        last_reply = next((line for line, who, _ in reversed(rows) if who == primary_id), "")
        said, side, table = f"{player_message}\n{last_reply}", speaker, []
        if barter:
            deal = window.get("deal") or {}
            table_offer, table_reason, table, profit = offers.on_table(deal, ctx_dict, speaker, mates, player_name, relation)
            lean += profit
            # The price guide then gives the price of each item on the table, so a counter-offer can name a fair price
            said += "".join(f"\n{item['name']}" for item in [*(deal.get("give") or []), *(deal.get("take") or [])])
            side = dict(speaker, inventory=offers.pooled(mates))
        background_block = offers.facts(category, ctx_dict, side, player_name, lean, said, table, relation) + "\n\n" + background_block
    elif chat_reason:
        background_block = f"YOUR THOUGHT: {chat_reason}\n\n{background_block}"
    turn = fill_prompt("prompt_chat_turn.txt", background=background_block, player_line=full_player_entry, final_instruction=final_instruction).strip()
    history = chat_prompt.history_window(chat_prompt.chat_lines(rows), campaign_db.DIALOGUE_BLOCK)
    notes = chat_prompt.overheard_notes(campaign_db.thread_members({thread_id for _, _, thread_id in history if thread_id}), primary_id)
    messages = chat_prompt.chat_messages(system, chat_prompt.history_turns(chat_prompt.with_notes(history, notes), primary_id), turn)

    if mode == "yell":
        # The plugin shows these at once for a talk, but only the server knows which NPC answers a yell
        thinking = state.LOCALIZATION_CONFIG.get(load_settings()["language"], {}).get("{name} is thinking...", "{name} is thinking...")
        notify(thinking.replace("{name}", primary_npc))
        send_to_pipe(f"NPC_SAY: {voice()}: ...")
    content = call_llm("action" if category else "chat", messages)
    state.restart_quiet_clock()
    if not content:
        logging.error("CHAT: No reply from the LLM.")
        if category:
            end_thread()
    
    if content:
        judged = re.search(r'\[[^\]]*JUDGMENT\D*?(-?\d+)[^\]]*\]', content, re.IGNORECASE)
        # The prompt of an NPC that talks to itself asks for no judgment, but a model can still write one
        judgment_value = max(-5, min(5, int(judged.group(1)))) if judged and not self_talk else 0
        outcome, offer = None, None
        if category == "THREATEN" and offers.attacked(content):
            outcome = "attack"
        elif category in ("RECRUIT", "FOLLOW") and offers.refused(content):
            outcome = "refused"
        elif barter:
            # A counter-offer stays in the words of the NPC: a deal of the model took the place of the player's table
            if offers.agreed(content):
                offer = table_offer
                if not offer:
                    logging.info(f"ACTION: Dropped the agreement of {primary_npc} to the deal on the table, because {table_reason}.")
                outcome = "offer" if offer else "unkept"
            elif offers.read(content, category) is not None:
                logging.info(f"ACTION: Ignored the offer of {primary_npc} in the barter window: {offers.offer_text(content, category)}")
        elif category and offers.read(content, category) is not None:
            offer, unkept = offers.check(category, offers.read(content, category), ctx_dict, speaker)
            if not offer:
                logging.info(f"ACTION: Dropped the offer of {primary_npc}, because {unkept}: {offers.offer_text(content, category)}")
                outcome = "unkept"
            else:
                outcome = "free" if category == "HEAL" and not offer["takes"] else "offer"
        # A valid offer keeps the action dialogue open until the player answers it. An NPC that offers a deal leaves only on
        # the deal, and an accepted deal ends the thread anyway, so an [END] next to an offer or [AGREE] never closes it.
        dealt = offers.agreed(content) or offers.read(content, category) is not None
        closing = bool(category) and (outcome in ("attack", "refused", "free") or (not dealt and action_dialogue.ended(content)))
        offered = offers.offer_text(content, category)
        if offered:
            content = content.replace(offered, "")

        # The chat window keeps the name that the target had when it opened, so the request can name the target by an old name
        own_names = {primary_npc.lower(), register(raw_npc).lower()}
        # The game name and the Name of an NPC differ when the game gave it a title
        other_names = {name.lower() for name in [*npcs, *(n["name"] for n in nearby if n.get("name")), *(name for name, _ in listeners.values())]} - own_names
        content = reply_text.spoken(content, own_names, other_names | {player_name.lower()}) or "..."
        # The model still gives an animal words now and then, so only the *action* parts reach the game
        if animal:
            content = " ".join(re.findall(r"\*[^*\n]+\*", content)) or "..."

        if len(content) > 500:
            content = content[:497] + "..."
        
        recorders = {speaker_id: (player_name, speaker), **listeners} if speaker_id else listeners
        copies = []
        for npc_id, (name, local_context) in recorders.items():
            if npc_id not in char_datas:
                char_datas[npc_id] = get_character_data(name, local_context)

            new_lines = [
                (chat_prompt.heard_line(time_prefix, npc_id, (speaker_id, player_name), target or ((npc_id, name) if npc_id in answerers else (None, "everyone")), player_message, mode_tag), speaker_id),
                (chat_prompt.heard_line(time_prefix, npc_id, (primary_id, primary_npc), (speaker_id, player_name), content), primary_id),
            ]
            char_datas[npc_id]["ConversationHistory"].extend(line for line, _ in new_lines)

            if npc_id and should_save_profile(name, npc_id, char_datas[npc_id]):
                copies.append((npc_id, name, new_lines))

        thread_id = None
        if primary_id:
            members = [(npc_id, "speaker" if npc_id in (primary_id, speaker_id) else "overheard", in_squad.get(npc_id, False)) for npc_id, _, _ in copies]
            thread_id = campaign_db.join_thread(current_thread, members, campaign_db.game_time(time_prefix), scene_text.location_name(speaker or state.PLAYER_CONTEXT),
                                                kinds=(mode, category.lower()) if category else (mode,))
            state.CURRENT_THREAD.update(key=thread_key, id=thread_id, replied=time.monotonic(),
                                        action={"category": category, "speaker": speaker_id, "stock": offers.sells_stock(ctx_dict, category)} if category else None)
            if closing:
                state.CURRENT_THREAD.clear()
        for npc_id, name, new_lines in copies:
            campaign_db.append_dialogue(npc_id, new_lines, char_datas[npc_id], thread_id)
            if npc_id == primary_id and judgment_value:
                # Applied as a delta at save time: the profile read before the LLM call can be stale by then
                new_rel = campaign_db.change_relation(npc_id, judgment_value)
                logging.info(f"RELATION: {name} personal relation is now {new_rel} (judgment={judgment_value})")

        actions, last_words, after = [], [], []
        if outcome == "attack":
            actions, last_words = ["[ATTACK]"], [action_dialogue.end_line("threaten_attack")]
            record_deal(thread_id, f"({primary_npc} attacked {player_name}.)", [npc_party, speaker_party], location)
        elif outcome == "free":
            actions, last_words = offers.actions(offer), [action_dialogue.end_line("heal_start")]
            record_deal(thread_id, f"({primary_npc} treated {player_name} for free.)", [npc_party, speaker_party], location)
        elif outcome == "offer":
            popup = offers.popup_text(offer, primary_npc, player_name)
            offer_id = offers.hold(offer, npc=primary_npc, player=player_name, voice=voice(), thread=thread_id, parties=[npc_party, speaker_party],
                                   location=location, npc_id=primary_id, day=ctx_dict.get("day"))
            state.PENDING_OFFER["command"] = offers.command(offer_id, offer, primary_npc, target_key, speaker_key, popup, barter)
            after = [state.PENDING_OFFER["command"]]
            logging.info(f"ACTION: {popup}")

        state.RECENT_HITS.clear()
        state.RECENT_HITS[pair] = retrieval.next_turns(recent_turns, [hit["record"]["key"] for hit in found_memories + found_rumors + found_entries], cooldown)

        interactions = campaign_db.count_interaction(primary_id) if primary_id else None
        threshold = load_settings()["bio_interactions"]
        if interactions is not None and threshold and interactions >= threshold:
            # In the background, so the reply does not wait for a second LLM call
            threading.Thread(target=generate_bio, args=(primary_id,), daemon=True).start()

        more = None
        if order and len(order) > 2 and thread_id:
            yell_names = {speaker_key: player_name, **{key: listeners[npc["npc_id"]][0] for key, npc in crowd.items()}}
            yell_ids = {speaker_key: speaker_id, **{key: npc["npc_id"] for key, npc in crowd.items()}}
            contexts = {speaker_key: speaker, **crowd}
            descriptions = [
                f"{describe_npc(f'{yell_names[key]}|{key}', char_datas[yell_ids[key]], yell_ids[key], persona=False)}\nHEALTH: {contexts[key].get('health') or 'Unknown'}"
                for key in dict.fromkeys(key for pair in order for key in pair)
            ]
            frame = fill_prompt("prompt_yell.txt", speaker=player_name, target=target[1] if target else "everyone", length=len(order), participants="\n\n".join(descriptions),
                                place=scene_text.location_text((speaker or state.PLAYER_CONTEXT).get("environment") or {}, "They"))
            yell_talk = {
                "system": build_system_prompt(reply_rules=False), "frame": frame, "order": order, "names": yell_names, "ids": yell_ids,
                "personas": {key: describe_persona(char_datas[yell_ids[key]]) for key, _ in order[2:]}, "spoken": [(speaker_key, player_message), (target_key, content)],
                "copies": {npc_id: char_datas[npc_id] for npc_id, _, _ in copies}, "in_squad": in_squad, "thread": thread_id,
                "time_prefix": time_prefix, "campaign": state.ACTIVE_CAMPAIGN,
            }
            more = lambda: play_yell(yell_talk)

        logging.info(f'CHAT: {mode_tag}{player_name} to {primary_npc}{f" [{category}]" if category else ""}: "{player_message}" | {primary_npc}: "{content}" ({time.monotonic() - started:.1f} s)')
        if outcome == "unkept":
            notify(f"{primary_npc} made an offer it can't keep. (LLM hallucinated an offer it can't make)")
        if outcome == "refused":
            notify(f"{primary_npc} has refused your invitation to join {speaker.get('faction') or 'your squad'}." if category == "RECRUIT" else f"{primary_npc} refused to follow you.")
        return reply(f"[{category}] {content}" if category else content, *last_words, actions=actions, after=after, action_open=bool(category) and not closing, then=more)
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

def rumor_reply(event_id, instruction, so_far=None, **reply):
    """The web app puts the text into the row of the event, so the player reads it before a save keeps it. so_far None takes
    the stored rumor. Stores nothing."""
    try:
        event_id = int(event_id)
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "Name the event of the rumor."}), 400
    event = campaign_db.event(event_id)
    if not event:
        return jsonify({"status": "error", "message": "The event is gone. Load the events again."}), 404
    if so_far is None:
        so_far = next((rumor["text"] for rumor in campaign_db.rumors() if rumor["event_id"] == event_id), "")
    text = rumors.clean(call_llm("synthesis", [{"role": "user", "content": rumors.prompt(*event, instruction, so_far)}]))
    if not text:
        return jsonify({"status": "error", "message": "The LLM gave no usable text. Try again."}), 500
    return jsonify({"status": "ok", "text": text, **reply})

def keep_rumor_reply(data):
    """Saves the text of a rumor by its id, or the rumor of an event, which a new rumor has no id for yet."""
    refused = campaign_write(data)
    if refused: return refused
    text = str(data.get("text") or "").strip()
    if not text:
        key = str(data["id"]) if data.get("id") else f"new:{data.get('event')}"
        return jsonify({"status": "error", "errors": [{"field": ["rumors", key], "message": "A rumor needs text. Delete it instead."}]}), 400
    instruction = data.get("instruction")
    if not campaign_db.save_rumor(data.get("id"), data.get("event"), text, None if instruction is None else str(instruction).strip()):
        return jsonify({"status": "error", "message": "The rumor or its event is gone. Load the events again."}), 404
    return jsonify({"status": "ok"})

def delete_rumor_reply(data):
    refused = campaign_write(data)
    if refused: return refused
    campaign_db.delete_rumor(data.get("id"))
    return jsonify({"status": "ok"})

def add_event_reply(data, source):
    """The Events window selects the new event by its id."""
    refused = campaign_write(data)
    if refused: return refused
    rumor = str(data.get("rumor") or "").strip()
    if not rumor:
        return jsonify({"status": "error", "message": "Write the rumor of the event."}), 400
    event_id = campaign_db.add_custom_event(rumor)
    logging.info(f"EVENTS: Added the custom event {event_id} from {source}")
    return jsonify({"status": "ok", "id": event_id})

def delete_event_reply(data):
    refused = campaign_write(data)
    if refused: return refused
    campaign_db.delete_event(data.get("id"))
    return jsonify({"status": "ok"})

@bp.route('/write_rumor', methods=['POST'])
def write_events_rumor():
    data = request.get_json(silent=True) or {}
    # The Events window sends the campaign back with Keep, because the same event ID can name another event in another campaign
    return rumor_reply(data.get("event"), str(data.get("instruction") or ""), campaign=state.ACTIVE_CAMPAIGN)

@bp.route('/read_rumor', methods=['POST'])
def read_events_rumor():
    """Answers in the shape of /write_rumor, so Edit Rumor in the Events window opens the same editor as Generate Rumor."""
    data = request.get_json(silent=True) or {}
    rumor = next((rumor for rumor in campaign_db.rumors() if str(rumor["event_id"]) == str(data.get("event"))), None)
    if not rumor:
        return jsonify({"status": "error", "message": "The event has no rumor yet."}), 404
    return jsonify({"status": "ok", "text": rumor["text"], "campaign": state.ACTIVE_CAMPAIGN})

@bp.route('/keep_rumor', methods=['POST'])
def keep_events_rumor():
    return keep_rumor_reply(request.get_json(silent=True) or {})

@bp.route('/delete_rumor', methods=['POST'])
def delete_events_rumor():
    return delete_rumor_reply(request.get_json(silent=True) or {})

@bp.route('/add_event', methods=['POST'])
def add_events_event():
    return add_event_reply(request.get_json(silent=True) or {}, "the game")

@bp.route('/delete_event', methods=['POST'])
def delete_events_event():
    return delete_event_reply(request.get_json(silent=True) or {})

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
