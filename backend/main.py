from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .data_loader import set_fighter_retired
from .schemas import (  # noqa: F401
    EventFightPrediction,
    FightSimulation,
    FighterProfile,
    MatchupEntry,
    PredictionResult,
    RankingEntry,
    RetireBody,
    UpcomingEvent,
)
from .services import (
    build_fighter_profile,
    build_fight_simulation,
    build_fight_simulator_data,
    build_matchmaking,
    build_prediction,
    build_ranking_response,
    build_upcoming_events,
)

app = FastAPI(
    title="UFCelo.gg API",
    description="Backend API para rankings Elo de peleadores de UFC/MMA.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/rankings/{division}", response_model=list[RankingEntry])
def get_rankings(division: str):
    rankings = build_ranking_response(division)
    if not rankings:
        raise HTTPException(status_code=404, detail=f"No hay rankings disponibles para division '{division}'.")
    return rankings


@app.get("/rankings/{division}/alltime", response_model=list[RankingEntry])
def get_alltime_rankings(division: str):
    rankings = build_ranking_response(division, alltime=True)
    if not rankings:
        raise HTTPException(status_code=404, detail=f"No hay rankings all-time para division '{division}'.")
    return rankings


@app.get("/fighter/{fighter_id}", response_model=FighterProfile)
def get_fighter(
    fighter_id: str,
    division: str = Query(default="heavyweight", description="División del peleador"),
):
    profile = build_fighter_profile(fighter_id, division)
    if not profile:
        raise HTTPException(status_code=404, detail=f"Fighter '{fighter_id}' no encontrado en {division}.")
    return profile


@app.get("/predict", response_model=PredictionResult)
def get_prediction(
    fighter_a: str = Query(..., description="ID del primer peleador."),
    fighter_b: str = Query(..., description="ID del segundo peleador."),
    division: str = Query(default="heavyweight", description="División"),
):
    prediction = build_prediction(fighter_a, fighter_b, division)
    if not prediction:
        raise HTTPException(status_code=404, detail="Uno o ambos peleadores no fueron encontrados.")
    return prediction


@app.get("/events/upcoming", response_model=list[UpcomingEvent])
def get_upcoming_events(
    division: str = Query(default="heavyweight", description="División para predicciones"),
):
    events = build_upcoming_events(division)
    if not events:
        raise HTTPException(status_code=404, detail="No se encontraron eventos próximos.")
    return events


@app.get("/matchmaking/{division}", response_model=list[MatchupEntry])
def get_matchmaking(division: str, top_n: int = Query(default=50, ge=1, le=200)):
    matchups = build_matchmaking(division, top_n=top_n)
    if not matchups:
        raise HTTPException(status_code=404, detail=f"No se encontraron matchups para division '{division}'.")
    return matchups


@app.patch("/fighter/{fighter_id}/retire")
def retire_fighter(
    fighter_id: str,
    body: RetireBody,
    division: str = Query(default="heavyweight"),
):
    fighter = build_fighter_profile(fighter_id, division)
    if not fighter:
        raise HTTPException(status_code=404, detail=f"Fighter '{fighter_id}' no encontrado en {division}.")
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
        raise HTTPException(status_code=404, detail="Uno o ambos peleadores no fueron encontrados.")
    return data


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
        raise HTTPException(status_code=404, detail="Uno o ambos peleadores no fueron encontrados.")
    return result
