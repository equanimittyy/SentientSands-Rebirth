import json
import logging
import os

import requests
from flask import Blueprint, Response, current_app, jsonify, request

from chat import background, chat_prompt, knowledge, llm, llm_config, llm_router, prompt_store, retrieval
from chat.bio import recorded_history
from chat.characters import send_rename
from chat.llm import default_llm_config, send_completion
from chat.prompts import describe_faction, describe_race, describe_record, faction_text, find_named
from chat.routes import add_deed_reply, bio_refusal, bio_reply, delete_deed_reply, delete_rumor_reply, keep_rumor_reply, rumor_reply
from core import deeds, state
from core.game import report_from_game
from core.paths import (CAMPAIGNS_DIR, DEFAULT_TEMPLATE, LLM_CONFIG_PATH, PROMPTS_DIR, USER_PROMPTS_DIR, USER_TEMPLATES_DIR,
                        WORLD_TEMPLATES_DIR)
from core.pipe import send_to_pipe
from core.routes import campaign_write, cull_future_data
from core.settings import load_settings
from dashboard.browser_launch import PanelTabs
from store import campaign_db, world_template
from store.campaigns import campaign_names, create_campaign, switch_campaign

bp = Blueprint("dashboard", __name__)

@bp.route('/')
def web_app():
    return current_app.send_static_file("index.html")

PANEL_TABS = PanelTabs()

# A GET, because EventSource sends only GET. A hostile page that holds it open can only stop a new tab from opening.
@bp.route('/web_panel/presence')
def web_panel_presence():
    return Response(PANEL_TABS.stream(), mimetype="text/event-stream")

def template_error(e):
    return jsonify({"status": "error", "errors": e.errors}), 400

@bp.route('/api/templates', methods=['GET'])
def list_templates():
    return jsonify({"status": "ok", "templates": world_template.listing(WORLD_TEMPLATES_DIR, USER_TEMPLATES_DIR)})

@bp.route('/api/templates/<name>', methods=['GET'])
def get_template(name):
    try:
        template = world_template.load(name, WORLD_TEMPLATES_DIR, USER_TEMPLATES_DIR)
    except world_template.TemplateError as e:
        return template_error(e)
    template["errors"], template["warnings"] = world_template.validate(template)
    return jsonify({"status": "ok", "template": template})

@bp.route('/api/templates/<name>/search', methods=['GET'])
def search_template(name):
    try:
        template = world_template.load(name, WORLD_TEMPLATES_DIR, USER_TEMPLATES_DIR)
    except world_template.TemplateError as e:
        return template_error(e)
    lore = retrieval.lore_records(
        [(category, record_id, data) for category, records in template["entities"].items() for record_id, data in records.items()],
        [{"faction_id": record_id, **data} for record_id, data in template["factions"].items()],
        template["history"],
        [{"npc_id": record_id, "profile": data.get("profile", {}), **{key: data[key] for key in ("knowledge", "known_by") if key in data}} for record_id, data in template["characters"].items()],
    )
    return search_reply(*background.search(request.args.get("message", ""), lore))

@bp.route('/api/templates/<name>/records', methods=['POST'])
def save_template_record(name):
    data = request.get_json(silent=True) or {}
    try:
        record_id, warnings = world_template.save_record(name, data.get("kind"), data.get("id"), data.get("data"), WORLD_TEMPLATES_DIR, USER_TEMPLATES_DIR, category=data.get("category"))
    except world_template.TemplateError as e:
        return template_error(e)
    logging.info(f"TEMPLATE: Saved the {data.get('kind')} {record_id or ''} of {name}")
    return jsonify({"status": "ok", "id": record_id, "warnings": warnings})

@bp.route('/api/templates/<name>/records/delete', methods=['POST'])
def delete_template_record(name):
    data = request.get_json(silent=True) or {}
    try:
        world_template.delete_record(name, data.get("kind"), data.get("id"), WORLD_TEMPLATES_DIR, USER_TEMPLATES_DIR, category=data.get("category"))
    except world_template.TemplateError as e:
        return template_error(e)
    logging.info(f"TEMPLATE: Deleted the {data.get('kind')} {data.get('id')} of {name}")
    return jsonify({"status": "ok"})

@bp.route('/api/templates/<name>/duplicate', methods=['POST'])
def duplicate_template(name):
    data = request.get_json(silent=True) or {}
    try:
        new_name = world_template.duplicate(name, data.get("new_name"), WORLD_TEMPLATES_DIR, USER_TEMPLATES_DIR)
    except world_template.TemplateError as e:
        return template_error(e)
    logging.info(f"TEMPLATE: Duplicated {name} as {new_name}")
    return jsonify({"status": "ok", "name": new_name})

@bp.route('/api/templates/<name>/export', methods=['GET'])
def export_template(name):
    try:
        data = world_template.export_template(name, WORLD_TEMPLATES_DIR, USER_TEMPLATES_DIR)
    except world_template.TemplateError as e:
        return template_error(e)
    # Not jsonify: it sorts the keys, and the shared file reads best in the order of the template folder
    return current_app.response_class(json.dumps(data, ensure_ascii=False), mimetype="application/json")

@bp.route('/api/templates/import', methods=['POST'])
def import_template():
    data = request.get_json(silent=True) or {}
    try:
        name = world_template.import_template(data.get("template"), data.get("name"), WORLD_TEMPLATES_DIR, USER_TEMPLATES_DIR)
    except world_template.TemplateError as e:
        return template_error(e)
    logging.info(f"TEMPLATE: Imported {name}")
    return jsonify({"status": "ok", "name": name})

@bp.route('/api/templates/<name>/delete', methods=['POST'])
def delete_template(name):
    try:
        world_template.delete(name, WORLD_TEMPLATES_DIR, USER_TEMPLATES_DIR)
    except world_template.TemplateError as e:
        return template_error(e)
    logging.info(f"TEMPLATE: Deleted {name}")
    return jsonify({"status": "ok"})

@bp.route('/api/campaigns', methods=['GET'])
def list_campaigns():
    campaigns = [{"name": name, "active": name == state.ACTIVE_CAMPAIGN} for name in campaign_names()]
    return jsonify({"status": "ok", "campaigns": campaigns, "refusal": campaign_db.unavailable_reason(), "templates": world_template.listing(WORLD_TEMPLATES_DIR, USER_TEMPLATES_DIR), "default_template": DEFAULT_TEMPLATE})

@bp.route('/api/campaigns', methods=['POST'])
def create_campaign_from_web():
    data = request.get_json(silent=True) or {}
    try:
        name = create_campaign(data.get("name"), data.get("template") or DEFAULT_TEMPLATE)
    except world_template.TemplateError as e:
        return template_error(e)
    except ValueError as e:
        return jsonify({"status": "error", "errors": [{"field": ["name"], "message": str(e)}]}), 400
    logging.info(f"CAMPAIGN: Created the campaign '{name}' from the web app")
    return jsonify({"status": "ok", "name": name})

@bp.route('/api/campaigns/switch', methods=['POST'])
def switch_campaign_from_web():
    name = (request.get_json(silent=True) or {}).get("name")
    # Only a listed folder, so a name such as ../x cannot point the campaign outside the campaigns folder
    if name not in campaign_names():
        return jsonify({"status": "error", "message": f"There is no campaign named {name}."}), 404
    switch_campaign(name)
    logging.info(f"CAMPAIGN: Switched to '{name}' from the web app")
    return jsonify({"status": "ok", "current": state.ACTIVE_CAMPAIGN})

@bp.route('/api/campaigns/delete', methods=['POST'])
def delete_campaign():
    name = (request.get_json(silent=True) or {}).get("name")
    names = campaign_names()
    if name not in names:
        return jsonify({"status": "error", "message": f"There is no campaign named {name}."}), 404
    if name == state.ACTIVE_CAMPAIGN:
        switch_campaign(next((other for other in names if other != name), ""))
    import shutil
    try:
        shutil.rmtree(os.path.join(CAMPAIGNS_DIR, name))
    except OSError as e:
        logging.error(f"CAMPAIGN: Cannot delete the campaign '{name}': {e}")
        return jsonify({"status": "error", "message": f"Cannot delete {name}: {e}"}), 500
    logging.info(f"CAMPAIGN: Deleted the campaign '{name}' from the web app")
    return jsonify({"status": "ok", "current": state.ACTIVE_CAMPAIGN})

@bp.route('/api/campaign', methods=['GET'])
def get_active_campaign():
    try:
        return jsonify({
            "status": "ok",
            "name": state.ACTIVE_CAMPAIGN,
            "notables": deeds.notable_events(),
            "rumors": [
                {"id": rumor["id"], "notable": rumor["notable_id"], "text": rumor["text"], "instruction": rumor["instruction"], "time": campaign_db.game_time_text(rumor["game_time"]) if rumor["game_time"] is not None else "-"}
                for rumor in reversed(campaign_db.rumors())
            ],
            "threads": [
                {
                    "id": thread["id"],
                    "time": campaign_db.game_time_text(thread["game_time"]) if thread["game_time"] is not None else "",
                    "location": thread["location"] or "",
                    "members": [{"name": name or "", "role": role} for _, name, role, _ in thread["members"]],
                    "memory": chat_prompt.named(thread["memory"], {npc_id: name or "Unknown" for npc_id, name, _, _ in thread["members"]}) if thread["memory"] else None,
                    "lines": thread["lines"],
                }
                for thread in campaign_db.threads()
            ],
        })
    except campaign_db.CampaignUnavailable as e:
        return jsonify({"status": "error", "name": state.ACTIVE_CAMPAIGN, "message": str(e)}), 409

@bp.route('/api/campaign/canon', methods=['GET'])
def get_campaign_canon():
    try:
        squad_deeds = deeds.character_deeds()
        known = campaign_db.character_knowledge()
        return jsonify({
            "status": "ok",
            "name": state.ACTIVE_CAMPAIGN,
            "template": campaign_db.template_info(),
            "bio_interactions": load_settings()["bio_interactions"],
            "overview": campaign_db.overview(),
            "history": campaign_db.history(),
            "factions": [
                {"id": f["faction_id"], "data": {"game_id": f["faction_id"], **{key: f[key] for key in campaign_db.FACTION_KEYS}}, "is_player": f["is_player"], "origin": f["origin"], "updated_at": f["updated_at"]}
                for f in campaign_db.list_factions()
            ],
            "characters": [
                {"id": npc_id, "data": {"game_id": npc_id.removeprefix("u:"), "profile": profile, **known[npc_id]}, "origin": origin, "updated_at": updated_at, "current_faction": state.LIVE_CONTEXTS.get(npc_id, {}).get("faction"), "status": state.LIVE_CONTEXTS.get(npc_id, {}).get("health"),
                 **({"deeds": squad_deeds[npc_id]} if npc_id in squad_deeds else {})}
                for (npc_id,), profile, origin, updated_at in campaign_db.list_records("character")
            ],
            "entities": [
                {"category": category, "id": ext_id, "data": data, "origin": origin, "updated_at": updated_at}
                for (category, ext_id), data, origin, updated_at in campaign_db.list_records("entity")
            ],
        })
    except campaign_db.CampaignUnavailable as e:
        return jsonify({"status": "error", "name": state.ACTIVE_CAMPAIGN, "message": str(e)}), 409

def search_reply(memories, entries, skipped, npc_id=None, dropped=()):
    """The hits of a test search in prompt order, each with how it was found: by a name or by the words of the line, and
    with its tier, and an entry with whether the NPC knows it only from its travels. dropped holds the records that the
    line names and that the NPC cannot know."""
    def found(hit):
        return {key: hit[key] for key in ("name", "words") if key in hit}

    settings = load_settings()
    return jsonify({
        "status": "ok",
        "slots": settings["retrieval_slots"],
        "memory_slots": settings["memory_slots"],
        "memories": [{"heading": chat_prompt.memory_heading(hit["record"]["memory"], npc_id), "text": retrieval.clipped(hit["record"]["text"]), **found(hit)} for hit in memories],
        "entries": [{"name": hit["record"]["name"], "kind": hit["record"]["kind"], "tier": knowledge.tier(hit["record"]), "travels": hit["travels"], **found(hit)} for hit in entries],
        "dropped": [{"name": record["name"], "kind": record["kind"], "tier": knowledge.tier(record)} for record in dropped],
        "skipped": [{"word": word, "reason": reason} for word, reason in skipped],
    })

# A GET, because a POST under /api/ counts as a write, which makes every open page refresh
@bp.route('/api/campaign/search', methods=['GET'])
def search_campaign():
    npc_id, speaker_id = request.args.get("npc") or None, request.args.get("speaker") or None
    try:
        lore = background.campaign_lore()
        profile = (campaign_db.get_character(npc_id) or {}) if npc_id else {}
        speaker = (campaign_db.get_character(speaker_id) or {}) if speaker_id else {}
        town, zone = background.place_of(profile.get("CurrentLocation", ""), lore)
        message, faction_id = request.args.get("message", ""), state.LIVE_CONTEXTS.get(npc_id, {}).get("factionID")
        memories, entries, skipped = background.search(message, lore, npc_id, profile, faction_id, speaker.get("Race"), town, zone)
        dropped = []
        if npc_id:
            known = background.known_keys(lore, npc_id, profile, faction_id, town, zone)
            named = retrieval.name_matches(message, [(name, record) for record in lore if record["description"].strip() for name in (record["name"], *record["aliases"])])
            dropped = list({record["key"]: record for _, record in named if record["key"] not in known}.values())
    except campaign_db.CampaignUnavailable as e:
        return jsonify({"status": "error", "name": state.ACTIVE_CAMPAIGN, "message": str(e)}), 409
    return search_reply(memories, entries, skipped, npc_id, dropped)

def record_refusal(errors):
    return jsonify({"status": "error", "errors": errors}), 400

@bp.route('/api/campaign/records', methods=['POST'])
def save_campaign_record():
    data = request.get_json(silent=True) or {}
    refused = campaign_write(data)
    if refused: return refused
    kind, record_id, value = data.get("kind"), data.get("id"), data.get("data")
    # A record that the page loaded must name its version, so a missing one counts as stale
    updated_at = None if record_id is None else data.get("updated_at") or ""
    warnings = []
    if kind in ("overview", "history"):
        if kind == "overview" and isinstance(value, str):
            value = value.replace("\r\n", "\n").strip()
        errors, warnings = world_template.record_problems(kind, value, [kind], names=campaign_names())
        if errors: return record_refusal(errors)
        (campaign_db.set_overview if kind == "overview" else campaign_db.set_history)(value)
    elif kind in ("faction", "character", "entity"):
        value = value if isinstance(value, dict) else {}
        if kind != "entity":
            record_id = record_id or value.get("game_id")
        try:
            if kind == "faction":
                warnings = save_campaign_faction(record_id, value, updated_at)
            elif kind == "character":
                character = {"game_id": record_id, "profile": value.get("profile"), **{key: value[key] for key in ("knowledge", "known_by") if key in value}}
                errors, warnings = world_template.record_problems("character", character, ["characters", data.get("id") or "new"], names=campaign_names())
                if errors: return record_refusal(errors)
                if data.get("id") is None:
                    record_id = campaign_db.unique_npc_id(record_id)
                elif campaign_db.PROVISIONAL in character["profile"]:
                    # A later bio would overwrite text that the player wrote
                    stored = campaign_db.get_character(record_id) or {}
                    if any(character["profile"].get(key) != stored.get(key) for key in ("Personality", "Backstory", "SpeechQuirks")):
                        del character["profile"][campaign_db.PROVISIONAL]
                campaign_db.save_record("character", (record_id,), character["profile"], updated_at, {"knowledge": character.get("knowledge", ""), "known_by": character.get("known_by", [])})
                send_rename(record_id, character["profile"]["Name"])
                send_to_pipe("REFRESH_LIBRARY:")
            else:
                category = data.get("category")
                if category not in world_template.CATEGORIES:
                    return record_refusal([{"field": ["category"], "message": f"{category} is not a category. Use races, locations, or regions."}])
                stored = campaign_db.list_records("entity")
                record_id = record_id or world_template.new_id(value, {ext_id for (stored_category, ext_id), *_ in stored if stored_category == category})
                entries = {f"{stored_category}/{ext_id}" for (stored_category, ext_id), *_ in stored} | {f"{category}/{record_id}"}
                errors, warnings = world_template.record_problems("entity", value, [category, data.get("id") or "new"], entries, campaign_names())
                if errors: return record_refusal(errors)
                campaign_db.save_record("entity", (category, record_id), value, updated_at)
        except world_template.TemplateError as e:
            return record_refusal(e.errors)
        except campaign_db.DuplicateRecord:
            field = [data.get("category"), "new"] if kind == "entity" else [f"{kind}s", "new", "game_id"]
            return record_refusal([{"field": field, "message": f"This campaign already holds the {kind} {record_id}."}])
        except campaign_db.StaleRecord:
            name = value.get("name") or (value.get("profile") or {}).get("Name") or record_id
            return jsonify({"status": "error", "message": f"The {kind} {name} changed after the page loaded it, for example in game. Discard to load it again."}), 409
    else:
        return record_refusal([{"field": ["kind"], "message": f"{kind} is not a kind of record."}])
    logging.info(f"CAMPAIGN: Saved the {kind} {record_id or ''} of '{state.ACTIVE_CAMPAIGN}' from the web app")
    return jsonify({"status": "ok", "id": record_id, "warnings": warnings})

@bp.route('/api/campaign/characters/bio', methods=['POST'])
def write_campaign_bio():
    data = request.get_json(silent=True) or {}
    refused = campaign_write(data) or bio_refusal(data)
    if refused: return refused
    profile = data["profile"]
    history = recorded_history(str(data["id"])) if data.get("id") else []
    # By name only, so a faction that the player changed in the form counts, not the one the game reports
    return bio_reply(data, history, describe_race(profile.get("Race", "Unknown")), describe_faction(profile.get("Faction")))

@bp.route('/api/templates/<name>/characters/bio', methods=['POST'])
def write_template_bio(name):
    data = request.get_json(silent=True) or {}
    refused = bio_refusal(data)
    if refused: return refused
    try:
        template = world_template.load(name, WORLD_TEMPLATES_DIR, USER_TEMPLATES_DIR)
    except world_template.TemplateError as e:
        return template_error(e)
    profile = data["profile"]
    race, faction = profile.get("Race", "Unknown"), profile.get("Faction")
    race_entry = find_named(template["entities"]["races"].values(), race)
    race_lore = describe_record(race_entry) if race_entry else f"{race}: The template has no entry for this race."
    return bio_reply(data, [], race_lore, faction_text(faction, find_named(template["factions"].values(), faction)))

def campaign_names():
    """The names that a known_by and a neighbour of the campaign can name, as world_template.template_names gives them
    for a template. Only a canon character is a lore record, so only its name counts."""
    entities = campaign_db.list_records("entity")
    return world_template.template_names({
        "factions": {faction["faction_id"]: faction for faction in campaign_db.list_factions()},
        "characters": {npc_id: {"profile": profile} for (npc_id,), profile, origin, _ in campaign_db.list_records("character") if origin != "game"},
        "entities": {category: {ext_id: data for (stored, ext_id), data, *_ in entities if stored == category} for category in world_template.CATEGORIES},
    })

def save_campaign_faction(faction_id, value, updated_at):
    """Returns the warnings. Raises world_template.TemplateError, or a campaign_db error, with the reason. A missing
    knowledge or known_by is the default, because the editor saves no key for the default."""
    changes = {"knowledge": "", "known_by": [], **{key: value[key] for key in campaign_db.FACTION_KEYS if key in value}}
    if updated_at is None:
        faction = {"aliases": [], "major": False, "fields": {}, "description": "", **changes, "game_id": faction_id}
        errors, warnings = world_template.record_problems("faction", faction, ["factions", "new"], names=campaign_names())
        if errors: raise world_template.TemplateError(errors)
        campaign_db.add_faction(faction_id, faction)
        return warnings
    stored = campaign_db.find_faction(faction_id)
    if not stored:
        raise campaign_db.StaleRecord(faction_id)
    # The game names the player's faction, and the next context would undo another name
    if stored["is_player"]:
        changes.pop("name", None)
    errors, warnings = world_template.record_problems("faction", dict(stored, game_id=faction_id, **changes), ["factions", faction_id], names=campaign_names())
    if errors: raise world_template.TemplateError(errors)
    campaign_db.update_faction(faction_id, changes, updated_at)
    return warnings

@bp.route('/api/campaign/records/delete', methods=['POST'])
def delete_campaign_record():
    data = request.get_json(silent=True) or {}
    refused = campaign_write(data)
    if refused: return refused
    kind, record_id = data.get("kind"), data.get("id")
    if kind == "faction":
        campaign_db.delete_faction(record_id)
    elif kind == "character":
        campaign_db.delete_record("character", (record_id,))
        send_to_pipe("REFRESH_LIBRARY:")
    elif kind == "entity":
        campaign_db.delete_record("entity", (data.get("category"), record_id))
    else:
        return record_refusal([{"field": ["kind"], "message": f"{kind} is not a kind of record."}])
    logging.info(f"CAMPAIGN: Deleted the {kind} {record_id} of '{state.ACTIVE_CAMPAIGN}' from the web app")
    return jsonify({"status": "ok"})

@bp.route('/api/campaign/rumors/generate', methods=['POST'])
def generate_campaign_rumor():
    data = request.get_json(silent=True) or {}
    refused = campaign_write(data)
    if refused: return refused
    return rumor_reply(data.get("notable"), str(data.get("instruction") or ""), str(data.get("rumor") or ""))

@bp.route('/api/campaign/rumors', methods=['POST'])
def save_campaign_rumor():
    return keep_rumor_reply(request.get_json(silent=True) or {})

@bp.route('/api/campaign/rumors/delete', methods=['POST'])
def delete_campaign_rumor():
    return delete_rumor_reply(request.get_json(silent=True) or {})

@bp.route('/api/campaign/deeds/add', methods=['POST'])
def add_campaign_deed():
    return add_deed_reply(request.get_json(silent=True) or {}, "the web app")

@bp.route('/api/campaign/deeds/delete', methods=['POST'])
def delete_campaign_deed():
    return delete_deed_reply(request.get_json(silent=True) or {})

@bp.route('/api/campaign/memories', methods=['POST'])
def save_campaign_memory():
    data = request.get_json(silent=True) or {}
    refused = campaign_write(data)
    if refused: return refused
    thread_id = data.get("id")
    text = " ".join(str(data.get("text") or "").split())
    if not text:
        return jsonify({"status": "error", "errors": [{"field": ["memories", thread_id], "message": "A memory needs text. Delete it instead."}]}), 400
    # The player writes names, as the LLM does, so a later rename reaches the edited memory too
    members = campaign_db.thread_members([thread_id]).get(thread_id, [])
    if not campaign_db.edit_memory(thread_id, chat_prompt.mark_names(text, [(npc_id, name) for npc_id, name, _, _ in members])):
        return jsonify({"status": "error", "message": "The memory is gone. Discard to load the conversations again."}), 404
    return jsonify({"status": "ok"})

@bp.route('/api/campaign/memories/delete', methods=['POST'])
def delete_campaign_memory():
    data = request.get_json(silent=True) or {}
    refused = campaign_write(data)
    if refused: return refused
    campaign_db.delete_memory(data.get("id"))
    return jsonify({"status": "ok"})

@bp.route('/api/campaign/cull', methods=['POST'])
def cull_campaign():
    data = request.get_json(silent=True) or {}
    refused = campaign_write(data)
    if refused: return refused
    # The player's context dates from the latest request, and a cull by an older time would delete what came after it
    if not report_from_game():
        return jsonify({"status": "error", "message": "Cull needs the game running, because it deletes what is dated after the current game time."}), 409
    return cull_future_data()

@bp.route('/api/llm', methods=['GET'])
def get_llm_config():
    return jsonify({
        "status": "ok",
        "tasks": list(llm_config.TASKS),
        "provider_types": list(llm_config.PROVIDER_TYPES),
        **llm_config.masked(llm.LLM_CONFIG)
    })

@bp.route('/api/llm', methods=['POST'])
def save_llm_config():
    data = request.get_json(silent=True) or {}
    new_config = {part: data.get(part) for part in ("providers", "profiles", "default_profile", "routes")}
    errors = llm_config.validate(new_config)
    if errors:
        return jsonify({"status": "error", "errors": errors}), 400
    new_config = llm_config.with_stored_keys(new_config, llm.LLM_CONFIG)
    llm_config.save(LLM_CONFIG_PATH, new_config)
    llm.LLM_CONFIG = new_config
    logging.info("LLM: Saved the LLM configuration from the web app.")
    return get_llm_config()

@bp.route('/api/llm/reset', methods=['POST'])
def reset_llm_config():
    new_config = llm_config.reset(default_llm_config(), llm.LLM_CONFIG)
    llm_config.save(LLM_CONFIG_PATH, new_config)
    llm.LLM_CONFIG = new_config
    logging.info("LLM: Reset the LLM configuration to the defaults.")
    return get_llm_config()

@bp.route('/api/prompts', methods=['GET'])
def get_prompts():
    return jsonify({"status": "ok", "prompts": prompt_store.listing(PROMPTS_DIR, USER_PROMPTS_DIR)})

@bp.route('/api/prompts', methods=['POST'])
def save_prompt():
    data = request.get_json(silent=True) or {}
    name, text = data.get("name"), data.get("text")
    if not isinstance(name, str) or not isinstance(text, str):
        return jsonify({"status": "error", "message": "The request needs a prompt name and its text."}), 400
    try:
        warnings = prompt_store.save(name, text, PROMPTS_DIR, USER_PROMPTS_DIR)
    except ValueError as e:
        return jsonify({"status": "error", "errors": [{"field": [name], "message": str(e)}]}), 400
    logging.info(f"PROMPT: Saved {name} from the web app.")
    return jsonify({"status": "ok", "warnings": warnings})

@bp.route('/api/llm/test', methods=['POST'])
def test_llm_profile():
    """Tests the profile and the provider as the web app holds them, so the player can test before a save."""
    data = request.get_json(silent=True) or {}
    profile, provider = data.get("profile"), data.get("provider")
    if not isinstance(profile, dict) or not isinstance(provider, dict):
        return jsonify({"status": "error", "message": "The test needs a profile and its provider."}), 400
    provider_name = profile.get("provider", "")
    errors = llm_config.provider_errors(provider_name, provider) + llm_config.profile_errors(data.get("name", ""), profile, {provider_name: provider})
    if errors:
        return jsonify({"status": "error", "errors": errors}), 400
    provider = llm_config.provider_from_form(provider_name, provider, llm.LLM_CONFIG)
    messages = [{"role": "user", "content": "Keep your response extremely short. Reply with the word: Success"}]
    body = llm_router.build_body({"max_tokens": 200, "temperature": 0.7}, profile, messages)
    try:
        text = send_completion(provider, profile, body, min(profile["timeout"], 30))
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 502
    if not text:
        return jsonify({"status": "error", "message": "The model returned an empty completion."}), 502
    return jsonify({"status": "ok", "response": text})

# POST, because the provider in the form may not be saved.
@bp.route('/api/llm/models', methods=['POST'])
def list_llm_models():
    data = request.get_json(silent=True) or {}
    name, provider = data.get("name", ""), data.get("provider")
    if not isinstance(provider, dict):
        return jsonify({"status": "error", "message": "The request needs a provider."}), 400
    errors = llm_config.provider_errors(name, provider)
    if errors:
        return jsonify({"status": "error", "errors": errors}), 400
    provider = llm_config.provider_from_form(name, provider, llm.LLM_CONFIG)
    try:
        response = requests.get(f"{provider['base_url'].rstrip('/')}/models", headers={"Authorization": f"Bearer {provider.get('api_key', '')}"}, timeout=15)
        if response.status_code != 200:
            raise RuntimeError(f"HTTP {response.status_code}: {response.text[:200]}")
        models = llm_config.model_ids(response.json())
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 502
    return jsonify({"status": "ok", "models": models})
