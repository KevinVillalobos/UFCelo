import argparse
import csv
import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

BASE_ELO = 1500.0

# Baseline: elite HW fighter lands ~5 significant strikes per minute
_STRIKES_PER_MINUTE_BASELINE = 5.0
K_FACTOR = 32.0

METHOD_WEIGHTS = {
    "KO/TKO": 1.30,
    "SUB": 1.20,
    "DEC U": 1.00,
    "DEC S": 0.90,
    "DEC M": 0.85,
    "OTHER": 0.80,
}

_DIVISION_K_MULT: Dict[str, float] = {
    "heavyweight":      1.00,
    "light heavyweight": 0.95,
    "middleweight":     0.90,
    "welterweight":     0.75,
    "lightweight":      0.85,
    "featherweight":    0.85,
    "bantamweight":     0.90,
    "flyweight":        0.90,
}

SKILL_DIMENSIONS = [
    "Striking",
    "Grappling",
    "Defensa",
    "Consistencia",
    "Finish Rate",
    "Cardio/Durabilidad",
    "Presión",
]


@dataclass
class FightStats:
    fighter_id: str
    strikes_landed: int
    strikes_attempted: int
    takedowns_landed: int
    takedowns_attempted: int
    knockdowns: int
    control_time: str
    submission_attempts: int
    reversals: int
    head_strikes_landed: int
    head_strikes_attempted: int
    body_strikes_landed: int
    body_strikes_attempted: int
    leg_strikes_landed: int
    leg_strikes_attempted: int


@dataclass
class FightRecord:
    fight_id: str
    event_id: str
    event_name: str
    event_date: datetime
    fighter_a_id: str
    fighter_a_name: str
    fighter_b_id: str
    fighter_b_name: str
    winner_id: str
    method: str
    round: int
    time: str
    weight_class: str
    is_title_fight: bool
    fighter_a_stats: Optional[FightStats] = None
    fighter_b_stats: Optional[FightStats] = None


@dataclass
class EloHistoryPoint:
    date: str
    fight_id: str
    opponent_id: str
    opponent_name: str
    result: str
    elo: float
    event: str
    method: str
    round: int
    time: str
    weight_class: str
    is_title_fight: bool


@dataclass
class SkillHistoryPoint:
    date: str
    fight_id: str
    opponent_id: str
    opponent_name: str
    result: str
    skill_score: Dict[str, float]
    event: str
    method: str
    round: int
    time: str
    weight_class: str
    is_title_fight: bool


class EloEngine:
    def __init__(self, base_elo: float = BASE_ELO, k_factor: float = K_FACTOR, division: str = "heavyweight"):
        self.base_elo = base_elo
        self.k_factor = k_factor
        self.division = division.lower()

    def process(
        self,
        fights: List[FightRecord],
        fighters: Dict[str, Dict[str, Optional[str]]],
    ) -> (List[Dict[str, object]], Dict[str, List[Dict[str, object]]]):
        ratings: Dict[str, float] = {fid: self._initial_elo(fid, fighters) for fid in fighters.keys()}
        histories: Dict[str, List[Dict[str, object]]] = {fighter_id: [] for fighter_id in fighters.keys()}
        streaks: Dict[str, int] = {fighter_id: 0 for fighter_id in fighters.keys()}
        fight_counts: Dict[str, int] = {fighter_id: 0 for fighter_id in fighters.keys()}
        last_fight_dates: Dict[str, "datetime"] = {}
        peak_elos: Dict[str, float] = {fid: ratings[fid] for fid in fighters.keys()}
        peak_elo_dates: Dict[str, str] = {}
        peak_elo_opponents: Dict[str, str] = {}
        pair_history: Dict[frozenset, List[str]] = {}

        for fight in fights:
            for fid in (fight.fighter_a_id, fight.fighter_b_id):
                if fid not in ratings:
                    ratings[fid] = self._initial_elo(fid, fighters)
                    histories[fid] = []
                    streaks[fid] = 0
                    fight_counts[fid] = 0
                    peak_elos[fid] = ratings[fid]

            elo_a = ratings[fight.fighter_a_id]
            elo_b = ratings[fight.fighter_b_id]

            score_a, score_b = self._result_score(fight)

            quality_a = self._quality_multiplier(fight.fighter_b_id, ratings, score_a)
            quality_b = self._quality_multiplier(fight.fighter_a_id, ratings, score_b)
            streak_a = self._streak_multiplier(streaks[fight.fighter_a_id])
            streak_b = self._streak_multiplier(streaks[fight.fighter_b_id])

            weight = self._fight_weight(fight.method, fight.is_title_fight, fight.round)
            k_var_a = self._variable_k(fight_counts[fight.fighter_a_id])
            k_var_b = self._variable_k(fight_counts[fight.fighter_b_id])

            # Rematch multiplier
            pair_key = frozenset([fight.fighter_a_id, fight.fighter_b_id])
            prev = pair_history.get(pair_key, [])
            if len(prev) >= 2:
                rematch_mult = 0.50
            elif len(prev) == 1:
                rematch_mult = 0.70 if prev[0] == fight.winner_id else 1.20
            else:
                rematch_mult = 1.0

            # Opponent momentum and fight time proxy
            opp_mom_a = self._opponent_momentum_mult(streaks[fight.fighter_b_id])
            opp_mom_b = self._opponent_momentum_mult(streaks[fight.fighter_a_id])
            time_mult_a = self._time_pct_mult(fight, score_a)
            time_mult_b = self._time_pct_mult(fight, score_b)

            k_a = self.k_factor * weight * quality_a * streak_a * k_var_a * rematch_mult * opp_mom_a * time_mult_a
            k_b = self.k_factor * weight * quality_b * streak_b * k_var_b * rematch_mult * opp_mom_b * time_mult_b

            # Division change: adjust expected score only (not ELO storage)
            elo_a_eff = self._division_change_elo(fight.fighter_a_id, fight.weight_class, fighters, elo_a)
            elo_b_eff = self._division_change_elo(fight.fighter_b_id, fight.weight_class, fighters, elo_b)
            expected_a = self._expected_score(elo_a_eff, elo_b_eff)
            expected_b = 1.0 - expected_a

            delta_a = k_a * (score_a - expected_a)
            delta_b = k_b * (score_b - expected_b)

            # Opponent-quality cap/floor
            if score_a == 1.0 and elo_b < 1300:
                delta_a = min(delta_a, 8.0)
            elif score_a == 0.0 and elo_b > 1700:
                delta_a = max(delta_a, -12.0)
            if score_b == 1.0 and elo_a < 1300:
                delta_b = min(delta_b, 8.0)
            elif score_b == 0.0 and elo_a > 1700:
                delta_b = max(delta_b, -12.0)

            # Peak ELO penalty: sustained decline far below career high
            if score_a == 0.0 and streaks[fight.fighter_a_id] <= -3 and elo_a < peak_elos.get(fight.fighter_a_id, elo_a) * 0.85:
                delta_a *= 1.20
            if score_b == 0.0 and streaks[fight.fighter_b_id] <= -3 and elo_b < peak_elos.get(fight.fighter_b_id, elo_b) * 0.85:
                delta_b *= 1.20

            new_a = elo_a + delta_a
            new_b = elo_b + delta_b

            ratings[fight.fighter_a_id] = new_a
            ratings[fight.fighter_b_id] = new_b

            # Peak ELO tracking (recorded before inactivity decay, so it's the true career high)
            fight_date_str = fight.event_date.strftime("%Y-%m-%d")
            if new_a > peak_elos.get(fight.fighter_a_id, self.base_elo):
                peak_elos[fight.fighter_a_id] = new_a
                peak_elo_dates[fight.fighter_a_id] = fight_date_str
                peak_elo_opponents[fight.fighter_a_id] = fight.fighter_b_name
            if new_b > peak_elos.get(fight.fighter_b_id, self.base_elo):
                peak_elos[fight.fighter_b_id] = new_b
                peak_elo_dates[fight.fighter_b_id] = fight_date_str
                peak_elo_opponents[fight.fighter_b_id] = fight.fighter_a_name

            streaks[fight.fighter_a_id] = self._update_streak(streaks[fight.fighter_a_id], score_a)
            streaks[fight.fighter_b_id] = self._update_streak(streaks[fight.fighter_b_id], score_b)
            fight_counts[fight.fighter_a_id] += 1
            fight_counts[fight.fighter_b_id] += 1
            last_fight_dates[fight.fighter_a_id] = fight.event_date
            last_fight_dates[fight.fighter_b_id] = fight.event_date
            pair_history.setdefault(pair_key, []).append(fight.winner_id)

            result_a = "Win" if score_a == 1.0 else "Loss" if score_a == 0.0 else "Draw"
            result_b = "Win" if score_b == 1.0 else "Loss" if score_b == 0.0 else "Draw"

            histories[fight.fighter_a_id].append(asdict(EloHistoryPoint(
                date=fight.event_date.strftime("%Y-%m-%d"),
                fight_id=fight.fight_id,
                opponent_id=fight.fighter_b_id,
                opponent_name=fight.fighter_b_name,
                result=result_a,
                elo=round(new_a, 2),
                event=fight.event_name,
                method=fight.method,
                round=fight.round,
                time=fight.time,
                weight_class=fight.weight_class,
                is_title_fight=fight.is_title_fight,
            )))

            histories[fight.fighter_b_id].append(asdict(EloHistoryPoint(
                date=fight.event_date.strftime("%Y-%m-%d"),
                fight_id=fight.fight_id,
                opponent_id=fight.fighter_a_id,
                opponent_name=fight.fighter_a_name,
                result=result_b,
                elo=round(new_b, 2),
                event=fight.event_name,
                method=fight.method,
                round=fight.round,
                time=fight.time,
                weight_class=fight.weight_class,
                is_title_fight=fight.is_title_fight,
            )))

        # Display-only inactivity decay: 0.5%/month toward base ELO, capped at 24 months.
        # Applied at ranking-output time so elo_histories stays as-is (pure fight record).
        today = datetime.now()
        ranking = []
        for fighter_id, raw_elo in ratings.items():
            fighter_info = fighters.get(fighter_id, {})
            last_date = last_fight_dates.get(fighter_id)

            displayed_elo = raw_elo
            if last_date:
                months_inactive = (today - last_date).days / 30.44
                if months_inactive > 0:
                    capped = min(24.0, months_inactive)
                    decay_delta = (raw_elo - self.base_elo) * 0.005 * capped
                    if streaks.get(fighter_id, 0) <= -3:
                        decay_delta *= 1.30
                    displayed_elo = raw_elo - decay_delta

            active = last_date is not None and (today - last_date).days <= 730
            ranking.append({
                "fighter_id": fighter_id,
                "fighter_name": fighter_info.get("name") or "Unknown",
                "division": fighter_info.get("division") or "Unknown",
                "elo": round(displayed_elo, 2),
                "peak_elo": round(peak_elos.get(fighter_id, self.base_elo), 2),
                "peak_elo_date": peak_elo_dates.get(fighter_id),
                "peak_elo_opponent": peak_elo_opponents.get(fighter_id),
                "record": fighter_info.get("record"),
                "fight_count": fight_counts.get(fighter_id, 0),
                "last_fight_date": last_date.strftime("%Y-%m-%d") if last_date else None,
                "active": active,
                "streak": streaks.get(fighter_id, 0),
            })

        ranking.sort(key=lambda x: x["elo"], reverse=True)
        return ranking, histories

    def _expected_score(self, elo_a: float, elo_b: float) -> float:
        diff = max(-250.0, min(250.0, elo_a - elo_b))
        return 1.0 / (1.0 + 10 ** (-diff / 400.0))

    def _result_score(self, fight: FightRecord) -> (float, float):
        if fight.winner_id == fight.fighter_a_id:
            return 1.0, 0.0
        if fight.winner_id == fight.fighter_b_id:
            return 0.0, 1.0
        return 0.5, 0.5

    def _fight_weight(self, method: str, is_title: bool, round_num: int) -> float:
        if method in {"KO/TKO", "SUB"}:
            if round_num == 1:
                weight = 1.40
            elif round_num == 2:
                weight = 1.25
            else:
                weight = 1.10
        elif method == "DEC U":
            weight = 1.05
        elif method == "DEC M":
            weight = 0.90
        elif method in {"DEC S", "OTHER"}:
            weight = 0.80
        else:
            weight = 0.80
        if is_title:
            weight *= 1.20
        return weight

    def _quality_multiplier(self, opponent_id: str, ratings: Dict[str, float], score: float) -> float:
        sorted_ids = sorted(ratings, key=lambda fid: ratings[fid], reverse=True)
        total = len(sorted_ids)
        if opponent_id not in sorted_ids:
            return 1.0
        rank = sorted_ids.index(opponent_id) + 1
        multiplier = 1.0
        if rank <= 5:
            multiplier += 0.1 if score == 1.0 else -0.05
        elif rank <= 10:
            multiplier += 0.05 if score == 1.0 else 0.0
        elif rank >= max(total - 5, 1):
            multiplier -= 0.05 if score == 1.0 else 0.1
        return max(0.7, multiplier)

    def _streak_multiplier(self, streak: int) -> float:
        if streak >= 8:   return 1.35
        if streak >= 5:   return 1.25
        if streak >= 3:   return 1.15
        if streak <= -8:  return 1.55
        if streak <= -5:  return 1.40
        if streak <= -3:  return 1.25
        return 1.0

    def _update_streak(self, current_streak: int, score: float) -> int:
        if score == 1.0:
            return current_streak + 1 if current_streak >= 0 else 1
        if score == 0.0:
            return current_streak - 1 if current_streak <= 0 else -1
        return 0

    def _variable_k(self, fight_count: int) -> float:
        if fight_count < 5:
            base = 2.0
        elif fight_count < 15:
            base = 1.0
        else:
            base = 0.625
        return base * _DIVISION_K_MULT.get(self.division, 0.90)

    def _time_pct_mult(self, fight: "FightRecord", score: float) -> float:
        try:
            m, s = map(int, fight.time.split(":"))
            elapsed = (fight.round - 1) * 300 + m * 60 + s
        except (ValueError, AttributeError):
            return 1.0
        total = fight.round * 300
        pct = elapsed / max(total, 1)
        if pct < 0.30:
            return 1.15 if score == 1.0 else 0.90
        if pct > 0.80:
            return 0.90 if score == 1.0 else 0.85
        return 1.0

    def _opponent_momentum_mult(self, opponent_streak: int) -> float:
        if opponent_streak >= 3:  return 1.15
        if opponent_streak <= -3: return 0.90
        return 1.0

    def _division_change_elo(
        self, fighter_id: str, fight_weight_class: str,
        fighters: Dict[str, Dict], raw_elo: float,
    ) -> float:
        fighter_division = (fighters.get(fighter_id) or {}).get("division", "").lower()
        fight_div = fight_weight_class.lower()
        if fighter_division and fight_div and fighter_division not in fight_div and fight_div not in fighter_division:
            return raw_elo - (raw_elo - self.base_elo) * 0.15
        return raw_elo

    def _initial_elo(self, fighter_id: str, fighters: Dict[str, Dict]) -> float:
        record = (fighters.get(fighter_id) or {}).get("record")
        if record:
            try:
                parts = record.split("-")
                wins, losses = int(parts[0]), int(parts[1])
                total = wins + losses
                if total > 0:
                    return max(1300.0, min(1700.0, 1500.0 + (wins / total - 0.5) * 400.0))
            except (ValueError, IndexError):
                pass
        return self.base_elo


class SkillScoreEngine:
    def __init__(self, smoothing: float = 0.80):
        self.smoothing = smoothing

    def process(
        self,
        fights: List[FightRecord],
        fighters: Dict[str, Dict[str, Optional[str]]],
    ) -> (List[Dict[str, object]], Dict[str, List[Dict[str, object]]]):
        skill_scores: Dict[str, Dict[str, float]] = {
            fighter_id: {dim: 50.0 for dim in SKILL_DIMENSIONS} for fighter_id in fighters.keys()
        }
        histories: Dict[str, List[Dict[str, object]]] = {fighter_id: [] for fighter_id in fighters.keys()}

        for fight in fights:
            for fighter_id, fighter_name, opponent_id, opponent_name, side in [
                (fight.fighter_a_id, fight.fighter_a_name, fight.fighter_b_id, fight.fighter_b_name, "a"),
                (fight.fighter_b_id, fight.fighter_b_name, fight.fighter_a_id, fight.fighter_a_name, "b"),
            ]:
                if fighter_id not in skill_scores:
                    skill_scores[fighter_id] = {dim: 50.0 for dim in SKILL_DIMENSIONS}
                    histories[fighter_id] = []

                raw_scores = self._raw_scores(fight, fighter_id, side)
                current = skill_scores[fighter_id]
                next_scores = {}
                for dim in SKILL_DIMENSIONS:
                    next_scores[dim] = round(current[dim] * self.smoothing + raw_scores[dim] * (1.0 - self.smoothing), 2)
                skill_scores[fighter_id] = next_scores

                histories[fighter_id].append(asdict(SkillHistoryPoint(
                    date=fight.event_date.strftime("%Y-%m-%d"),
                    fight_id=fight.fight_id,
                    opponent_id=opponent_id,
                    opponent_name=opponent_name,
                    result=self._result_label(fight, fighter_id),
                    skill_score=next_scores,
                    event=fight.event_name,
                    method=fight.method,
                    round=fight.round,
                    time=fight.time,
                    weight_class=fight.weight_class,
                    is_title_fight=fight.is_title_fight,
                )))

        # Composite weights mirror the prediction blending in services.py
        _composite_weights = {
            "Striking": 0.20, "Grappling": 0.15, "Defensa": 0.20,
            "Consistencia": 0.15, "Finish Rate": 0.10,
            "Cardio/Durabilidad": 0.10, "Presión": 0.10,
        }

        current_scores = []
        for fighter_id, score in skill_scores.items():
            fighter_info = fighters.get(fighter_id, {})
            composite = sum(score[d] * _composite_weights.get(d, 0) for d in score)
            current_scores.append({
                "fighter_id": fighter_id,
                "fighter_name": fighter_info.get("name") or "Unknown",
                "division": fighter_info.get("division") or "Unknown",
                "skill_score": score,
                "skill_composite": round(composite, 2),
            })

        return current_scores, histories

    def _result_label(self, fight: FightRecord, fighter_id: str) -> str:
        if fight.winner_id == fighter_id:
            return "Win"
        if fight.winner_id and fight.winner_id != fighter_id:
            return "Loss"
        return "Draw"

    def _raw_scores(self, fight: FightRecord, fighter_id: str, side: str) -> Dict[str, float]:
        method = fight.method
        is_winner = fight.winner_id == fighter_id

        # Obtener estadísticas del peleador
        stats = fight.fighter_a_stats if side == "a" else fight.fighter_b_stats
        opponent_stats = fight.fighter_b_stats if side == "a" else fight.fighter_a_stats

        # Valores base por defecto si no hay estadísticas
        if not stats or not opponent_stats:
            return self._default_scores(method, is_winner)

        # Calcular métricas reales
        striking_accuracy = stats.strikes_landed / max(stats.strikes_attempted, 1)
        fight_minutes = fight.round * 5
        striking_volume = stats.strikes_landed / max(fight_minutes * _STRIKES_PER_MINUTE_BASELINE, 1)

        takedown_accuracy = stats.takedowns_landed / max(stats.takedowns_attempted, 1)
        takedown_defense = 1.0 - (opponent_stats.takedowns_landed / max(opponent_stats.takedowns_attempted, 1))

        # Control time en segundos
        control_seconds = self._time_to_seconds(stats.control_time)
        total_fight_seconds = fight.round * 300  # 5 minutos por ronda
        control_ratio = control_seconds / max(total_fight_seconds, 1)

        # Strikes por zona
        head_accuracy = stats.head_strikes_landed / max(stats.head_strikes_attempted, 1)
        body_accuracy = stats.body_strikes_landed / max(stats.body_strikes_attempted, 1)
        leg_accuracy = stats.leg_strikes_landed / max(stats.leg_strikes_attempted, 1)

        # Calcular puntuaciones basadas en estadísticas reales
        raw = {
            "Striking": min(1.0, (striking_accuracy * 0.6 + striking_volume * 0.4) * 1.2),
            "Grappling": min(1.0, (takedown_accuracy * 0.7 + takedown_defense * 0.3) * 1.1),
            "Defensa": min(1.0, takedown_defense * 0.8 + (1.0 - opponent_stats.strikes_landed / max(opponent_stats.strikes_attempted, 1)) * 0.2),
            "Consistencia": min(1.0, (head_accuracy + body_accuracy + leg_accuracy) / 3.0),
            "Finish Rate": 1.0 if method in {"KO/TKO", "SUB"} and is_winner else 0.3,
            "Cardio/Durabilidad": min(1.0, 0.8 + (fight.round - 1) * 0.1),  # Mejor en rondas tardías
            "Presión": min(1.0, control_ratio * 0.7 + striking_volume * 0.3),
        }

        # Ajustes por método de victoria
        if method == "KO/TKO" and is_winner:
            raw["Striking"] *= 1.3
            raw["Finish Rate"] = 1.0
        elif method == "SUB" and is_winner:
            raw["Grappling"] *= 1.3
            raw["Finish Rate"] = 1.0
        elif method in {"DEC U", "DEC S", "DEC M"}:
            raw["Consistencia"] *= 1.2
            raw["Cardio/Durabilidad"] *= 1.2
            raw["Presión"] *= 1.1

        # Ajuste por resultado
        outcome_factor = 1.0
        if not is_winner:
            if fight.winner_id == "":
                outcome_factor = 0.95
            elif method == "KO/TKO":
                outcome_factor = 0.75
            elif method == "SUB":
                outcome_factor = 0.80
            else:
                outcome_factor = 0.90

        for dim in raw:
            raw[dim] *= outcome_factor

        # Bonus por título y rondas tempranas
        if fight.is_title_fight:
            for dim in raw:
                raw[dim] += 0.04
        if method in {"KO/TKO", "SUB"} and 1 <= fight.round <= 2:
            for dim in raw:
                raw[dim] += 0.03

        return {dim: round(min(100.0, max(0.0, raw[dim] * 100)), 2) for dim in SKILL_DIMENSIONS}

    def _default_scores(self, method: str, is_winner: bool) -> Dict[str, float]:
        """Puntuaciones por defecto cuando no hay estadísticas detalladas."""
        raw = {
            "Striking": 0.5,
            "Grappling": 0.5,
            "Defensa": 0.6,
            "Consistencia": 0.6,
            "Finish Rate": 0.4,
            "Cardio/Durabilidad": 0.6,
            "Presión": 0.6,
        }

        if method == "KO/TKO":
            raw.update({
                "Striking": 0.88,
                "Grappling": 0.30,
                "Defensa": 0.72,
                "Consistencia": 0.58,
                "Finish Rate": 1.0,
                "Cardio/Durabilidad": 0.62,
                "Presión": 0.82,
            })
        elif method == "SUB":
            raw.update({
                "Striking": 0.42,
                "Grappling": 0.92,
                "Defensa": 0.68,
                "Consistencia": 0.64,
                "Finish Rate": 1.0,
                "Cardio/Durabilidad": 0.58,
                "Presión": 0.72,
            })
        elif method in {"DEC U", "DEC S", "DEC M"}:
            raw.update({
                "Striking": 0.72,
                "Grappling": 0.68,
                "Defensa": 0.79,
                "Consistencia": 0.84,
                "Finish Rate": 0.24,
                "Cardio/Durabilidad": 0.90,
                "Presión": 0.88,
            })

        outcome_factor = 1.0
        if not is_winner:
            if method == "KO/TKO":
                outcome_factor = 0.72
            elif method == "SUB":
                outcome_factor = 0.78
            else:
                outcome_factor = 0.90

        for dim, value in raw.items():
            adjusted = value * (0.70 + 0.30 * outcome_factor)
            raw[dim] = min(1.0, max(0.0, adjusted))

        return {dim: round(v * 100, 2) for dim, v in raw.items()}

    def _time_to_seconds(self, time_str: str) -> int:
        """Convierte tiempo en formato MM:SS a segundos."""
        try:
            minutes, seconds = map(int, time_str.split(":"))
            return minutes * 60 + seconds
        except (ValueError, AttributeError):
            return 0


def parse_event_date(value: str) -> Optional[datetime]:
    if not value:
        return None
    for fmt in ("%B %d, %Y", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def read_fights(csv_path: Path) -> List[FightRecord]:
    fights: List[FightRecord] = []
    with csv_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            date = parse_event_date(row.get("event_date", ""))
            if not date:
                log.warning("Fecha inválida en pelea %s: %s", row.get("fight_id"), row.get("event_date"))
                continue

            # Cargar estadísticas si existen
            fighter_a_stats = None
            fighter_b_stats = None

            if row.get("fighter_a_strikes_landed"):
                fighter_a_stats = FightStats(
                    fighter_id=row.get("fighter_a_id", ""),
                    strikes_landed=int(row.get("fighter_a_strikes_landed", 0)),
                    strikes_attempted=int(row.get("fighter_a_strikes_attempted", 0)),
                    takedowns_landed=int(row.get("fighter_a_takedowns_landed", 0)),
                    takedowns_attempted=int(row.get("fighter_a_takedowns_attempted", 0)),
                    knockdowns=int(row.get("fighter_a_knockdowns", 0)),
                    control_time=row.get("fighter_a_control_time", "00:00"),
                    submission_attempts=int(row.get("fighter_a_submission_attempts", 0)),
                    reversals=int(row.get("fighter_a_reversals", 0)),
                    head_strikes_landed=int(row.get("fighter_a_head_strikes_landed", 0)),
                    head_strikes_attempted=int(row.get("fighter_a_head_strikes_attempted", 0)),
                    body_strikes_landed=int(row.get("fighter_a_body_strikes_landed", 0)),
                    body_strikes_attempted=int(row.get("fighter_a_body_strikes_attempted", 0)),
                    leg_strikes_landed=int(row.get("fighter_a_leg_strikes_landed", 0)),
                    leg_strikes_attempted=int(row.get("fighter_a_leg_strikes_attempted", 0)),
                )

            if row.get("fighter_b_strikes_landed"):
                fighter_b_stats = FightStats(
                    fighter_id=row.get("fighter_b_id", ""),
                    strikes_landed=int(row.get("fighter_b_strikes_landed", 0)),
                    strikes_attempted=int(row.get("fighter_b_strikes_attempted", 0)),
                    takedowns_landed=int(row.get("fighter_b_takedowns_landed", 0)),
                    takedowns_attempted=int(row.get("fighter_b_takedowns_attempted", 0)),
                    knockdowns=int(row.get("fighter_b_knockdowns", 0)),
                    control_time=row.get("fighter_b_control_time", "00:00"),
                    submission_attempts=int(row.get("fighter_b_submission_attempts", 0)),
                    reversals=int(row.get("fighter_b_reversals", 0)),
                    head_strikes_landed=int(row.get("fighter_b_head_strikes_landed", 0)),
                    head_strikes_attempted=int(row.get("fighter_b_head_strikes_attempted", 0)),
                    body_strikes_landed=int(row.get("fighter_b_body_strikes_landed", 0)),
                    body_strikes_attempted=int(row.get("fighter_b_body_strikes_attempted", 0)),
                    leg_strikes_landed=int(row.get("fighter_b_leg_strikes_landed", 0)),
                    leg_strikes_attempted=int(row.get("fighter_b_leg_strikes_attempted", 0)),
                )

            fights.append(FightRecord(
                fight_id=row.get("fight_id", ""),
                event_id=row.get("event_id", ""),
                event_name=row.get("event_name", ""),
                event_date=date,
                fighter_a_id=row.get("fighter_a_id", ""),
                fighter_a_name=row.get("fighter_a_name", ""),
                fighter_b_id=row.get("fighter_b_id", ""),
                fighter_b_name=row.get("fighter_b_name", ""),
                winner_id=row.get("winner_id", ""),
                method=row.get("method", "OTHER"),
                round=int(row.get("round", "0") or 0),
                time=row.get("time", ""),
                weight_class=row.get("weight_class", ""),
                is_title_fight=row.get("is_title_fight", "False").strip().lower() == "true",
                fighter_a_stats=fighter_a_stats,
                fighter_b_stats=fighter_b_stats,
            ))
    fights.sort(key=lambda item: item.event_date)
    return fights


def load_fighters(fighters_path: Path, division: str = "heavyweight") -> Dict[str, Dict[str, Optional[str]]]:
    if not fighters_path.exists():
        return {}
    with fighters_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    division_label = division.title()
    fighters: Dict[str, Dict[str, Optional[str]]] = {}
    if isinstance(data, dict):
        for fighter_id, details in data.items():
            fighters[fighter_id] = {
                "name": details.get("name") if isinstance(details, dict) else None,
                "record": _extract_record(details) if isinstance(details, dict) else None,
                "division": division_label,
            }
    elif isinstance(data, list):
        for item in data:
            fighter_id = str(item.get("fighter_id") or item.get("id") or "")
            if not fighter_id:
                continue
            fighters[fighter_id] = {
                "name": item.get("name") or item.get("full_name"),
                "record": _extract_record(item),
                "division": item.get("division") or division_label,
            }
    return fighters


def _extract_record(item: Optional[dict]) -> Optional[str]:
    if not item or not isinstance(item, dict):
        return None
    wins = item.get("wins")
    losses = item.get("losses")
    draws = item.get("draws")
    if wins is None or losses is None:
        return None
    draws_val = int(draws) if draws is not None else 0
    return f"{wins}-{losses}-{draws_val}"


def write_json(path: Path, data: object) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def main():
    parser = argparse.ArgumentParser(description="Elo engine para UFC")
    parser.add_argument("--division", default="heavyweight",
                        help="División a procesar (ej: heavyweight, lightweight)")
    parser.add_argument("--fights", default=None,
                        help="Ruta al CSV de peleas (default: data/fights_{division}.csv)")
    parser.add_argument("--fighters", default=None,
                        help="Ruta al JSON de peleadores (default: data/fighters_{division}.json)")
    parser.add_argument("--output", default="data", help="Directorio de salida")
    args = parser.parse_args()

    division_slug = args.division.lower().replace(" ", "_")
    if args.fights is None:
        args.fights = f"data/fights_{division_slug}.csv"
    if args.fighters is None:
        fighters_path_candidate = Path(f"data/fighters_{division_slug}.json")
        args.fighters = str(fighters_path_candidate) if fighters_path_candidate.exists() else "data/fighters.json"

    fights_path = Path(args.fights)
    fighters_path = Path(args.fighters)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    fights = read_fights(fights_path)
    fighters = load_fighters(fighters_path, division=args.division)

    if not fights:
        log.error("No se encontraron peleas para procesar.")
        return
    if not fighters:
        log.error("No se encontraron peleadores para procesar.")
        return

    elo_engine = EloEngine(division=args.division)
    skill_engine = SkillScoreEngine()

    ranking, elo_histories = elo_engine.process(fights, fighters)
    skill_scores, skill_histories = skill_engine.process(fights, fighters)

    # All-time ranking: same data re-sorted by peak_elo instead of current elo
    alltime_ranking = sorted(ranking, key=lambda x: x["peak_elo"], reverse=True)
    for i, entry in enumerate(alltime_ranking, 1):
        entry["alltime_rank"] = i

    retired_path = output_dir / "retired_overrides.json"
    retired_overrides: Dict[str, bool] = {}
    if retired_path.exists():
        with retired_path.open("r", encoding="utf-8") as _f:
            retired_overrides = json.load(_f)

    active_ranking = [
        entry for entry in ranking
        if entry.get("active") and not retired_overrides.get(str(entry["fighter_id"]), False)
    ]
    write_json(output_dir / f"rankings_{division_slug}.json", active_ranking)
    write_json(output_dir / f"rankings_{division_slug}_alltime.json", alltime_ranking)
    write_json(output_dir / f"elo_histories_{division_slug}.json", elo_histories)
    write_json(output_dir / f"skill_scores_{division_slug}.json", skill_scores)
    write_json(output_dir / f"skill_histories_{division_slug}.json", skill_histories)

    log.info(
        "[%s] Generados %s rankings activos (%s all-time, %s total), %s historiales Elo, %s skill scores, %s skill historiales.",
        args.division, len(active_ranking), len(alltime_ranking), len(ranking),
        len(elo_histories), len(skill_scores), len(skill_histories),
    )


if __name__ == "__main__":
    main()
