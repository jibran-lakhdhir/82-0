"""
82-0 Game — Flask API Server
"""
import uuid
import json
from flask import Flask, jsonify, request, send_from_directory

from game import (
    GameState, start_game, respin_team, respin_era,
    select_player, move_player, clear_selection, submit_lineup,
)
from scoring_engine import format_result

app = Flask(__name__, static_folder="static", static_url_path="")

# In-memory session store  {session_id: GameState}
SESSIONS: dict[str, GameState] = {}


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------

def _serialize_player_option(opt):
    s = opt.stats
    return {
        "name": s.name,
        "team": s.team,
        "decade": s.decade,
        "season": s.best_season_year,
        "best_award": s.best_award,
        "eligible_positions": s.eligible_positions(),
        "stats": {
            "ppg": s.ppg, "rpg": s.rpg, "apg": s.apg,
            "spg": s.spg, "bpg": s.bpg,
        },
        "advanced": {
            "ts_pct": s.ts_pct,
            "ws_per_48": s.ws_per_48,
            "usg_pct": s.usg_pct,
            "ast_pct": s.ast_pct,
        },
    }


def _serialize_spin(spin):
    players_by_pos = {}
    for pos, opts in spin.players.items():
        players_by_pos[pos] = [_serialize_player_option(o) for o in opts]

    selected = None
    if spin.selected_player:
        p = spin.selected_player
        selected = {
            "name": p.name,
            "team": p.team,
            "decade": p.decade,
            "season": p.best_season_year,
            "best_award": p.best_award,
            "eligible_positions": p.eligible_positions(),
            "stats": {
                "ppg": p.ppg, "rpg": p.rpg, "apg": p.apg,
                "spg": p.spg, "bpg": p.bpg,
            },
            "advanced": {
                "ts_pct": p.ts_pct,
                "ws_per_48": p.ws_per_48,
                "usg_pct": p.usg_pct,
                "ast_pct": p.ast_pct,
            },
        }

    return {
        "index": spin.index,
        "team": spin.team,
        "decade": spin.decade,
        "players": players_by_pos,
        "selected_player": selected,
        "assigned_position": spin.assigned_position,
        "is_resolved": spin.is_resolved(),
    }


def _serialize_state(state: GameState):
    return {
        "spins": [_serialize_spin(s) for s in state.spins],
        "team_respin_available": state.team_respin_available,
        "era_respin_available": state.era_respin_available,
        "respin_log": state.respin_log,
        "all_spins_resolved": state.all_spins_resolved(),
        "result": state.result,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/api/new_game", methods=["POST"])
def new_game():
    session_id = str(uuid.uuid4())
    state = start_game()
    SESSIONS[session_id] = state
    return jsonify({"session_id": session_id, "state": _serialize_state(state)})


@app.route("/api/state/<session_id>", methods=["GET"])
def get_state(session_id):
    state = SESSIONS.get(session_id)
    if not state:
        return jsonify({"error": "Session not found"}), 404
    return jsonify(_serialize_state(state))


@app.route("/api/respin_team/<session_id>", methods=["POST"])
def api_respin_team(session_id):
    state = SESSIONS.get(session_id)
    if not state:
        return jsonify({"error": "Session not found"}), 404
    data = request.get_json()
    spin_index = data.get("spin_index", 0)
    try:
        state = respin_team(state, spin_index)
        SESSIONS[session_id] = state
        return jsonify(_serialize_state(state))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/respin_era/<session_id>", methods=["POST"])
def api_respin_era(session_id):
    state = SESSIONS.get(session_id)
    if not state:
        return jsonify({"error": "Session not found"}), 404
    data = request.get_json()
    spin_index = data.get("spin_index", 0)
    try:
        state = respin_era(state, spin_index)
        SESSIONS[session_id] = state
        return jsonify(_serialize_state(state))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/select_player/<session_id>", methods=["POST"])
def api_select_player(session_id):
    state = SESSIONS.get(session_id)
    if not state:
        return jsonify({"error": "Session not found"}), 404
    data = request.get_json()
    try:
        state = select_player(
            state,
            data["spin_index"],
            data["player_name"],
            data["position"],
        )
        SESSIONS[session_id] = state
        return jsonify(_serialize_state(state))
    except (ValueError, KeyError) as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/move_player/<session_id>", methods=["POST"])
def api_move_player(session_id):
    state = SESSIONS.get(session_id)
    if not state:
        return jsonify({"error": "Session not found"}), 404
    data = request.get_json()
    try:
        state = move_player(state, data["spin_index"], data["new_position"])
        SESSIONS[session_id] = state
        return jsonify(_serialize_state(state))
    except (ValueError, KeyError) as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/clear_selection/<session_id>", methods=["POST"])
def api_clear_selection(session_id):
    state = SESSIONS.get(session_id)
    if not state:
        return jsonify({"error": "Session not found"}), 404
    data = request.get_json()
    state = clear_selection(state, data["spin_index"])
    SESSIONS[session_id] = state
    return jsonify(_serialize_state(state))


@app.route("/api/submit/<session_id>", methods=["POST"])
def api_submit(session_id):
    state = SESSIONS.get(session_id)
    if not state:
        return jsonify({"error": "Session not found"}), 404
    try:
        state = submit_lineup(state)
        SESSIONS[session_id] = state
        return jsonify(_serialize_state(state))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 8080))
    app.run(debug=False, port=port, threaded=True)
