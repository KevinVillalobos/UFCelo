import json
import os
import urllib.request
from pathlib import Path

import hmac

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .data_loader import set_fighter_retired

# ── Visit counter ─────────────────────────────────────────────────────────────
# Uses Upstash Redis when env vars are present; falls back to a local file.
_KV_URL   = os.environ.get("KV_REST_API_URL", "")
_KV_TOKEN = os.environ.get("KV_REST_API_TOKEN", "")
_KV_KEY   = "ufcelo_visits"

_DATA_DIR       = Path(__file__).parent.parent / "data"
_VISITS_PRIMARY = _DATA_DIR / "visits.json"
_VISITS_TMP     = Path("/tmp/visits.json")


def _kv_request(path: str) -> int | None:
    if not (_KV_URL and _KV_TOKEN):
        return None
    try:
        req = urllib.request.Request(
            f"{_KV_URL.rstrip('/')}/{path}",
            headers={"Authorization": f"Bearer {_KV_TOKEN}"},
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            result = json.loads(resp.read()).get("result")
            return int(result) if result is not None else 0
    except Exception:
        return None


def _load_visits() -> int:
    kv = _kv_request(f"get/{_KV_KEY}")
    if kv is not None:
        return kv
    for p in (_VISITS_PRIMARY, _VISITS_TMP):
        if p.exists():
            try:
                return int(json.loads(p.read_text()).get("total", 0))
            except Exception:
                pass
    return 0


def _save_visits(total: int) -> None:
    data = json.dumps({"total": total})
    for p in (_VISITS_PRIMARY, _VISITS_TMP):
        try:
            p.write_text(data)
            return
        except (PermissionError, OSError):
            continue
from .schemas import (  # noqa: F401
    AccuracyResponse,
    EventFightPrediction,
    FightSimulation,
    FighterProfile,
    FighterTagsResult,
    MatchupEntry,
    PredictionResult,
    RankingEntry,
    RetireBody,
    UpcomingEvent,
)
from .ufc_rankings import load_ufc_rankings, refresh as refresh_ufc_rankings, start_background_refresh
from .upcoming import start_background_refresh as start_upcoming_refresh
from .services import (
    build_accuracy,
    build_fighter_profile,
    build_fight_simulation,
    build_fight_simulator_data,
    build_matchmaking,
    build_prediction,
    build_ranking_response,
    build_upcoming_events,
    get_fighter_tags,
)

# Comma-separated list; the site itself talks to the API same-origin through nginx (/api/).
_CORS_ORIGINS = [
    o.strip()
    for o in os.environ.get("CORS_ORIGINS", "https://ufcelo.gg,https://www.ufcelo.gg").split(",")
    if o.strip()
]
_ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")


def require_admin(x_admin_token: str = Header(default="")) -> None:
    if not _ADMIN_TOKEN:
        raise HTTPException(status_code=503, detail="Admin endpoints are disabled (ADMIN_TOKEN not set).")
    if not hmac.compare_digest(x_admin_token.encode(), _ADMIN_TOKEN.encode()):
        raise HTTPException(status_code=401, detail="Invalid admin token.")


app = FastAPI(
    title="UFCelo.gg API",
    description="Backend API para rankings Elo de peleadores de UFC/MMA.",
    version="0.1.0",
)


@app.on_event("startup")
def _sync_ufc_rankings() -> None:
    # Keeps data/ufc_rankings.json, data/champions.json and data/upcoming_events.json aligned with ufc.com
    start_background_refresh()
    start_upcoming_refresh()


app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["Content-Type", "X-Admin-Token"],
)


@app.get("/rankings/{division}", response_model=list[RankingEntry])
def get_rankings(division: str):
    rankings = build_ranking_response(division)
    if not rankings:
        raise HTTPException(status_code=404, detail=f"No rankings available for division '{division}'.")
    return rankings


@app.get("/rankings/{division}/alltime", response_model=list[RankingEntry])
def get_alltime_rankings(division: str):
    rankings = build_ranking_response(division, alltime=True)
    if not rankings:
        raise HTTPException(status_code=404, detail=f"No all-time rankings for division '{division}'.")
    return rankings


@app.get("/fighter/{fighter_id}", response_model=FighterProfile)
def get_fighter(
    fighter_id: str,
    division: str = Query(default="heavyweight", description="División del peleador"),
):
    profile = build_fighter_profile(fighter_id, division)
    if not profile:
        raise HTTPException(status_code=404, detail=f"Fighter '{fighter_id}' not found in {division}.")
    return profile


@app.get("/fighter/{fighter_id}/tags", response_model=FighterTagsResult)
def get_fighter_tags_endpoint(
    fighter_id: str,
    division: str = Query(default="heavyweight", description="División del peleador"),
):
    return get_fighter_tags(fighter_id, division)


@app.get("/predict", response_model=PredictionResult)
def get_prediction(
    fighter_a: str = Query(..., description="ID del primer peleador."),
    fighter_b: str = Query(..., description="ID del segundo peleador."),
    division: str = Query(default="heavyweight", description="División"),
    is_title_fight: bool = Query(default=False, description="Title fights are 5 rounds (switches on the cardio rule)."),
    is_main_event: bool = Query(default=False, description="Main events are 5 rounds (switches on the cardio rule)."),
):
    prediction = build_prediction(fighter_a, fighter_b, division, is_title_fight, is_main_event)
    if not prediction:
        raise HTTPException(status_code=404, detail="One or both fighters were not found.")
    return prediction


@app.get("/events/upcoming", response_model=list[UpcomingEvent])
def get_upcoming_events(
    division: str = Query(default="heavyweight", description="División para predicciones"),
):
    events = build_upcoming_events(division)
    if not events:
        raise HTTPException(status_code=404, detail="No upcoming events found.")
    return events


@app.get("/accuracy", response_model=AccuracyResponse)
def get_accuracy():
    return build_accuracy()


@app.get("/matchmaking/{division}", response_model=list[MatchupEntry])
def get_matchmaking(division: str, top_n: int = Query(default=15, ge=1, le=200)):
    matchups = build_matchmaking(division, top_n=top_n)
    if not matchups:
        raise HTTPException(status_code=404, detail=f"No matchups found for division '{division}'.")
    return matchups


@app.patch("/fighter/{fighter_id}/retire", dependencies=[Depends(require_admin)])
def retire_fighter(
    fighter_id: str,
    body: RetireBody,
    division: str = Query(default="heavyweight"),
):
    fighter = build_fighter_profile(fighter_id, division)
    if not fighter:
        raise HTTPException(status_code=404, detail=f"Fighter '{fighter_id}' not found in {division}.")
    set_fighter_retired(fighter_id, body.retired)
    return {"fighter_id": fighter_id, "retired": body.retired}


@app.get("/simulator-data")
def get_simulator_data(
    fighter_a: str = Query(..., description="ID del primer peleador"),
    fighter_b: str = Query(..., description="ID del segundo peleador"),
    division: str = Query(default="heavyweight", description="División"),
):
    data = build_fight_simulator_data(fighter_a, fighter_b, division)
    if not data:
        raise HTTPException(status_code=404, detail="One or both fighters were not found.")
    return data


@app.get("/ufc-rankings")
def get_ufc_rankings():
    data = load_ufc_rankings()
    if not data["divisions"]:
        raise HTTPException(status_code=404, detail="Official UFC rankings are not available yet.")
    return data


@app.get("/ufc-rankings/{division}")
def get_ufc_rankings_division(division: str):
    data = load_ufc_rankings()
    info = data["divisions"].get(division.lower())
    if not info:
        raise HTTPException(status_code=404, detail=f"No official rankings for division '{division}'.")
    return {"updated_at": data["updated_at"], "division": division.lower(), **info}


@app.get("/visits")
def get_visits():
    return {"total": _load_visits()}


@app.post("/visits")
def record_visit():
    kv = _kv_request(f"incr/{_KV_KEY}")
    if kv is not None:
        return {"total": kv}
    total = _load_visits() + 1
    _save_visits(total)
    return {"total": total}


@app.get("/simulate", response_model=FightSimulation)
def simulate_fight(
    fighter_a: str = Query(..., description="ID del primer peleador"),
    fighter_b: str = Query(..., description="ID del segundo peleador"),
    division: str = Query(default="heavyweight", description="División"),
    simulations: int = Query(default=1000, ge=100, le=10000),
    rounds: int = Query(default=3, ge=3, le=5),
    seed: int = Query(default=None),
):
    result = build_fight_simulation(
        fighter_a, fighter_b, n=simulations, rounds=rounds, seed=seed, division=division
    )
    if not result:
        raise HTTPException(status_code=404, detail="One or both fighters were not found.")
    return result
