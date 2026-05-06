from datetime import date
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class EloBreakdown(BaseModel):
    elo_before:        Optional[float] = None
    elo_after:         Optional[float] = None
    delta:             Optional[float] = None
    k_base:            Optional[float] = None
    k_var:             Optional[float] = None
    div_mult:          Optional[float] = None
    streak_before:     Optional[int]   = None
    streak_mult:       Optional[float] = None
    method_weight:     Optional[float] = None
    consec_loss_mult:  Optional[float] = None
    quality_mult:      Optional[float] = None
    rematch_mult:      Optional[float] = None
    opp_mom_mult:      Optional[float] = None
    time_mult:         Optional[float] = None
    k_effective:       Optional[float] = None
    expected_prob:     Optional[float] = None
    surprise:          Optional[float] = None
    cap_applied:       Optional[bool]  = None
    peak_penalty:      Optional[bool]  = None


class EloHistoryPoint(BaseModel):
    date:           Optional[date]         = None
    elo:            float
    elo_change:     Optional[float]        = None
    opponent_id:    Optional[str]          = None
    opponent_name:  Optional[str]          = None
    result:         Optional[str]          = None
    method:         Optional[str]          = None
    round:          Optional[int]          = None
    time:           Optional[str]          = None
    is_title_fight: Optional[bool]         = None
    event:          Optional[str]          = None
    breakdown:      Optional[EloBreakdown] = None


class SkillHistoryPoint(BaseModel):
    date:          Optional[date]    = None
    fight_id:      str
    opponent_id:   Optional[str]     = None
    opponent_name: Optional[str]     = None
    result:        Optional[str]     = None
    skill_score:   Dict[str, float]
    event:         Optional[str]     = None


class FightStats(BaseModel):
    total_fights:           Optional[int]            = None
    sig_strikes_per_min:    Optional[float]          = None
    strike_accuracy:        Optional[float]          = None
    strike_defense:         Optional[float]          = None
    knockdowns_per_fight:   Optional[float]          = None
    head_pct:               Optional[float]          = None
    body_pct:               Optional[float]          = None
    leg_pct:                Optional[float]          = None
    td_per_min:             Optional[float]          = None
    td_accuracy:            Optional[float]          = None
    td_defense:             Optional[float]          = None
    ctrl_pct:               Optional[float]          = None
    sub_attempts_per_fight: Optional[float]          = None
    wins:                   Optional[Dict[str, int]] = None
    losses:                 Optional[Dict[str, int]] = None
    avg_finish_round_ko:    Optional[float]          = None
    avg_finish_round_sub:   Optional[float]          = None
    timeline:               Optional[List[Any]]      = None


class RankingEntry(BaseModel):
    fighter_id:         str
    fighter_name:       str
    division:           str
    elo:                float
    rank:               int
    record:             Optional[str]   = None
    fight_count:        Optional[int]   = None
    last_fight_date:    Optional[str]   = None
    peak_elo:           Optional[float] = None
    peak_elo_date:      Optional[str]   = None
    peak_elo_opponent:  Optional[str]   = None
    active:             Optional[bool]  = None
    streak:             Optional[int]   = None
    is_champion:        Optional[bool]  = None
    visitor:            Optional[bool]  = None
    visitor_label:      Optional[str]   = None


class FighterProfile(BaseModel):
    fighter_id:     str
    fighter_name:   str
    division:       str
    elo:            float
    record:         Optional[str]       = None
    country:        Optional[str]       = None
    height:         Optional[str]       = None
    weight:         Optional[str]       = None
    reach:          Optional[str]       = None
    stance:         Optional[str]       = None
    height_inches:  Optional[float]     = None
    reach_inches:   Optional[float]     = None
    weight_lbs:     Optional[float]     = None
    elo_history:    List[EloHistoryPoint]
    skill_score:    Dict[str, float]
    skill_composite: Optional[float]   = None
    skill_history:  List[SkillHistoryPoint]
    fight_stats:    Optional[FightStats] = None


class PredictionResult(BaseModel):
    fighter_a_id:      str
    fighter_b_id:      str
    fighter_a_name:    str
    fighter_b_name:    str
    probability_a:     float
    probability_b:     float
    elo_probability_a: float
    elo_difference:    float
    skill_composite_a: float
    skill_composite_b: float
    skill_advantages:  Dict[str, float]
    skill_comparison:  Optional[Dict[str, Dict[str, float]]] = None
    method_prediction: str
    key_advantage:     Optional[str] = None


class MatchupEntry(BaseModel):
    fighter_a_id:          str
    fighter_b_id:          str
    fighter_a_name:        str
    fighter_b_name:        str
    elo_a:                 float
    elo_b:                 float
    elo_difference:        float
    competitiveness_score: float
    skill_contrast_score:  float
    matchup_score:         float
    key_dimension:         Optional[str]
    key_dimension_diff:    float
    probability_a:         float
    probability_b:         float


class RetireBody(BaseModel):
    retired: bool


class FightSimulation(BaseModel):
    fighter_a_id:      str
    fighter_b_id:      str
    fighter_a_name:    str
    fighter_b_name:    str
    simulations:       int
    rounds:            int
    probability_a:     float
    probability_b:     float
    fighter_a_wins:    int
    fighter_b_wins:    int
    method_breakdown:  Dict[str, Dict[str, float]]
    round_distribution: Dict[str, Dict[str, float]]
    most_likely_outcome: str
    skill_comparison:  Dict[str, Dict[str, float]]


class EventFightPrediction(BaseModel):
    fight_id:      str
    fighter_a_id:  str
    fighter_b_id:  str
    fighter_a_name: str
    fighter_b_name: str
    probability_a: float
    probability_b: float


class UpcomingFight(BaseModel):
    fight_id:        str
    fighter_a_id:    str
    fighter_b_id:    str
    fighter_a_name:  str
    fighter_b_name:  str
    scheduled_round: Optional[int]  = None
    scheduled_time:  Optional[str]  = None
    prediction:      Optional[PredictionResult] = None


class UpcomingEvent(BaseModel):
    event_id: str
    name:     str
    date:     Optional[date]        = None
    venue:    Optional[str]         = None
    fights:   List[UpcomingFight]
