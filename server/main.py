# Sentient Sands - Kenshi AI Mod
# Copyright (C) 2026 Sentient Sands Team
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import logging
import os
import sys
import threading

SERVER_DIR = os.path.dirname(os.path.abspath(__file__))

# The embedded runtime's ._pth file runs Python isolated, which leaves the script dir off sys.path
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from chat import llm
from chat import routes as chat_routes
from chat.llm import load_llm_config, player2_ping_loop
from chat.memory import memory_loop
from chat.synthesis import RUMOR_SYNTHESIS, synthesis_loop
from core import log_setup
from core import routes as core_routes
from core.app import app
from core.process import kill_old_servers, monitor_kenshi_process
from core.settings import load_configs, push_settings_to_plugin
from dashboard import routes as dashboard_routes
from dashboard.browser_launch import open_when_ready
from store.campaigns import init_server_state

for blueprint in (core_routes.bp, chat_routes.bp, dashboard_routes.bp):
    app.register_blueprint(blueprint)

def start():
    log_setup.setup(os.path.join(SERVER_DIR, "logs"))
    kill_old_servers()
    load_configs()
    init_server_state()
    llm.LLM_CONFIG = load_llm_config()
    if RUMOR_SYNTHESIS:
        threading.Thread(target=synthesis_loop, daemon=True).start()
    threading.Thread(target=memory_loop, daemon=True).start()
    threading.Thread(target=player2_ping_loop, daemon=True).start()
    threading.Thread(target=monitor_kenshi_process, daemon=True).start()

if __name__ == '__main__':
    start()
    logging.info("SYSTEM: Server starting on port 5000.")
    # A thread, because each message waits up to 0.25 s for a pipe that a closed game never opens
    threading.Thread(target=push_settings_to_plugin, daemon=True).start()
    if "--open-browser" in sys.argv[1:]:
        threading.Thread(target=open_when_ready, args=("127.0.0.1", 5000, dashboard_routes.PANEL_TABS), daemon=True).start()
    # Threaded: the plugin's polling must not block chat and settings requests
    app.run(host='127.0.0.1', port=5000, threaded=True)
