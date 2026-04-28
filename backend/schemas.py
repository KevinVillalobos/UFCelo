from datetime import date
from typing import Dict, List, Optional

from pydantic import BaseModel


class EloHistoryPoint(BaseModel):
    date: Optional[date]
    elo: float
    opponent_id: Optional[str]
    opponent_name: Optional[str]
    result: Optional[str]
    event: Optional[str]


class SkillHistoryPoint(BaseModel):
    date: Optional[date]
    fight_id: str
    opponent_id: Optional[str]
    opponent_name: Optional[str]
    result: Optional[str]
    skill_score: Dict[str, float]
    event: Optional[str]


class RankingEntry(BaseModel):
    fighter_id: str
    fighter_name: str
    division: str
    elo: float
    rank: int
    record: Optional[str]
    fight_count: Optional[int] = None
    last_fight_date: Optional[str] = None
    peak_elo: Optional[float] = None
    peak_elo_date: Optional[str] = None
    peak_elo_opponent: Optional[str] = None
    active: Optional[bool] = None


class FighterProfile(BaseModel):
    fighter_id: str
    fighter_name: str
    division: str
    elo: float
    record: Optional[str]
    country: Optional[str]
    height: Optional[str]
    weight: Optional[str]
    reach: Optional[str]
    stance: Optional[str]
    elo_history: List[EloHistoryPoint]
    skill_score: Dict[str, float]
    skill_composite: Optional[float] = None
    skill_history: List[SkillHistoryPoint]


class PredictionResult(BaseModel):
    fighter_a_id: str
    fighter_b_id: str
    fighter_a_name: str
    fighter_b_name: str
    probability_a: float
    probability_b: float
    elo_probability_a: float
    elo_difference: float
    skill_composite_a: float
    skill_composite_b: float
    skill_advantages: Dict[str, float]
    method_prediction: str
    key_advantage: Optional[str] = None


class MatchupEntry(BaseModel):
    fighter_a_id: str
    fighter_b_id: str
    fighter_a_name: str
    fighter_b_name: str
    elo_a: float
    elo_b: float
    elo_difference: float
    competitiveness_score: float
    skill_contrast_score: float
    matchup_score: float
    key_dimension: Optional[str]
    key_dimension_diff: float
    probability_a: float
    probability_b: float


class RetireBody(BaseModel):
    retired: bool


class FightSimulation(BaseModel):
    fighter_a_id: str
    fighter_b_id: str
    fighter_a_name: str
    fighter_b_name: str
    simulations: int
    rounds: int
    probability_a: float
    probability_b: float
    fighter_a_wins: int
    fighter_b_wins: int
    method_breakdown: Dict[str, Dict[str, float]]
    round_distribution: Dict[str, Dict[str, float]]
    most_likely_outcome: str
    skill_comparison: Dict[str, Dict[str, float]]


class EventFightPrediction(BaseModel):
    fight_id: str
    fighter_a_id: str
    fighter_b_id: str
    fighter_a_name: str
    fighter_b_name: str
    probability_a: float
    probability_b: float


class UpcomingFight(BaseModel):
    fight_id: str
    fighter_a_id: str
    fighter_b_id: str
    fighter_a_name: str
    fighter_b_name: str
    scheduled_round: Optional[int]
    scheduled_time: Optional[str]
    prediction: Optional[PredictionResult]


class UpcomingEvent(BaseModel):
    event_id: str
    name: str
    date: Optional[date]
    venue: Optional[str]
    fights: List[UpcomingFight]
