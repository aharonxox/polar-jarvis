"""Tiny local dashboard that visualizes Polar/OpenJarvis voice sessions.

polar_listen.py posts events here (assistant_online, listening_started,
command_received, project_started, reply, ...). This keeps them in memory
and in a local JSON log, and serves a single-page UI that polls for updates
so you can *see* every project/session Polar starts by voice.

Run: `python app.py` then open http://localhost:5055
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

app = Flask(__name__, static_folder="static")

LOG_PATH = Path(__file__).parent / "events.jsonl"
STATE = {
    "assistant_online": False,
    "events": [],   # most recent first
    "projects": {},  # id -> {name, created_at, status, last_event}
}


def _save_event(event: dict):
    with LOG_PATH.open("a") as f:
        f.write(json.dumps(event) + "\n")


@app.post("/api/events")
def post_event():
    payload = request.get_json(force=True)
    payload["received_at"] = time.time()
    STATE["events"].insert(0, payload)
    STATE["events"] = STATE["events"][:200]
    _save_event(payload)

    kind = payload.get("event")
    if kind == "assistant_online":
        STATE["assistant_online"] = True
    elif kind == "project_started":
        pid = str(uuid.uuid4())[:8]
        STATE["projects"][pid] = {
            "id": pid,
            "name": payload.get("project_name", "Untitled project"),
            "created_at": payload["ts"],
            "status": "active",
        }

    return jsonify({"ok": True})


@app.get("/api/state")
def get_state():
    return jsonify(
        {
            "assistant_online": STATE["assistant_online"],
            "projects": list(STATE["projects"].values())[::-1],
            "events": STATE["events"][:50],
        }
    )


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5055, debug=False)
