import json
import logging
import mimetypes

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from core import state
from core.game import adopt_canon
from core.paths import WEB_DIR
from core.request_guard import is_request_allowed
from store import campaign_db

# A Windows registry entry can map .js to text/plain, and browsers refuse to run a module script with that type
mimetypes.add_type("text/javascript", ".js")
app = Flask(__name__, static_folder=WEB_DIR, static_url_path="/web")
# ASCII-only responses: the plugin's UnescapeJSON decodes the \u escapes
app.json.ensure_ascii = True

@app.errorhandler(Exception)
def handle_exception(e):
    if isinstance(e, HTTPException):
        return jsonify({"error": e.description, "status": "error"}), e.code
    if isinstance(e, campaign_db.CampaignUnavailable):
        logging.warning(f"HTTP: {request.path} needs a campaign: {e}")
        return jsonify({"error": str(e), "status": "error"}), 409
    logging.exception(f"HTTP: Unhandled exception in {request.path}: {e}")
    try:
        if request.json:
            logging.debug(f"HTTP: Request body: {json.dumps(request.json)}")
    except:
        pass
    return jsonify({"error": str(e), "status": "error"}), 500

@app.before_request
def reject_foreign_requests():
    host = request.headers.get("Host")
    origin = request.headers.get("Origin")
    if not is_request_allowed(host, origin):
        logging.warning(f"HTTP: Rejected request to {request.path}: Host={host}, Origin={origin}")
        return jsonify({"status": "error", "message": "Forbidden"}), 403

# Before every route, so each npc_id that the server reads or stores is already the canon one
@app.before_request
def adopt_canon_ids():
    if request.is_json:
        try:
            adopt_canon(request.get_json(silent=True))
        except campaign_db.CampaignUnavailable:
            pass  # No campaign, so no canon

# The web app polls this count with campaign_db.writes, so an open page loads a change from another tab or the game.
# A POST that only reads, such as a model test, costs an open page one needless load.
@app.after_request
def count_write_requests(response):
    if request.method == "POST" and response.status_code < 400 and (request.path.startswith("/api/") or request.path == "/settings"):
        state.WRITE_REQUESTS += 1
    return response
