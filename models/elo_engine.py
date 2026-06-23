import argparse
import csv
import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

BASE_ELO = 1500.0

# Baseline: elite HW fighter lands ~5 significant strikes per minute
_STRIKES_PER_MINUTE_BASELINE = 5.0
K_FACTOR = 32.0

_DIVISION_K_MULT: Dict[str, float] = {
    "heavyweight":       1.00,
    "light heavyweight": 0.95,
    "middleweight":      0.90,
    "welterweight":      0.75,
    "lightweight":       0.85,
    "featherweight":     0.85,
    "bantamweight":      0.90,
    "flyweight":         0.90,
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

_DIVISIONS_ALL = [
    "heavyweight", "light heavyweight", "middleweight", "welterweight",
    "lightweight", "featherweight", "bantamweight", "flyweight",
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
    breakdown: Optional[Dict[str, Any]] = None


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
    def __init__(
        self,
        base_elo: float = BASE_ELO,
        k_factor: float = K_FACTOR,
        division: str = "heavyweight",
        prior_elos: Optional[Dict[str, float]] = None,
        debug: bool = False,
    ):
        self.base_elo = base_elo
        self.k_factor = k_factor
        self.division = division.lower()
        # ELO a usar como punto de entrada para peleadores que vienen de otra división.
        # Si está vacío, se usa _initial_elo() basado en el récord.
        self.prior_elos: Dict[str, float] = prior_elos or {}
        self.debug = debug

    def process(
        self,
        fights: List[FightRecord],
        fighters: Dict[str, Dict[str, Optional[str]]],
    ) -> tuple:
        # Build name lookup from fight records — reliable even when fighters JSON is empty
        names_from_fights: Dict[str, str] = {}
        for fight in fights:
            if fight.fighter_a_id and fight.fighter_a_name:
                names_from_fights[fight.fighter_a_id] = fight.fighter_a_name
            if fight.fighter_b_id and fight.fighter_b_name:
                names_from_fights[fight.fighter_b_id] = fight.fighter_b_name

        ratings: Dict[str, float] = {fid: self._initial_elo(fid, fighters) for fid in fighters.keys()}
        initial_ratings: Dict[str, float] = dict(ratings)  # snapshot for division_elo_entry
        histories: Dict[str, List[Dict[str, object]]] = {fid: [] for fid in fighters.keys()}
        streaks: Dict[str, int] = {fid: 0 for fid in fighters.keys()}
        fight_counts: Dict[str, int] = {fid: 0 for fid in fighters.keys()}
        last_fight_dates: Dict[str, datetime] = {}
        peak_elos: Dict[str, float] = {fid: ratings[fid] for fid in fighters.keys()}
        peak_elo_dates: Dict[str, str] = {}
        peak_elo_opponents: Dict[str, str] = {}
        pair_history: Dict[frozenset, List[str]] = {}

        for fight in fights:
            for fid in (fight.fighter_a_id, fight.fighter_b_id):
                if fid not in ratings:
                    ratings[fid] = self._initial_elo(fid, fighters)
                    initial_ratings[fid] = ratings[fid]
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

            # ── Asymmetric method weights ─────────────────────────────────────
            # Winner: fight_weight (how informative this type of win is)
            # Loser:  loss_method_mult × consecutive_loss_mult
            #         Symmetric to wins but with separate tuning for losses.
            #         consecutive_loss_mult escalates each loss in a streak.
            fight_weight = self._fight_weight(fight.method, fight.is_title_fight, fight.round)
            was_a_favorite = elo_a >= elo_b

            # ── Method weights + consec-loss tracking ────────────────────────
            clm_a = clm_b = 1.0
            if score_a == 1.0:  # A wins
                weight_a = fight_weight
                consec_b = max(0, -streaks[fight.fighter_b_id]) + 1
                clm_b    = self._consecutive_loss_mult(consec_b)
                weight_b = (
                    self._loss_method_mult(fight.method, fight.is_title_fight, fight.round, not was_a_favorite)
                    * clm_b
                )
            elif score_b == 1.0:  # B wins
                weight_b = fight_weight
                consec_a = max(0, -streaks[fight.fighter_a_id]) + 1
                clm_a    = self._consecutive_loss_mult(consec_a)
                weight_a = (
                    self._loss_method_mult(fight.method, fight.is_title_fight, fight.round, was_a_favorite)
                    * clm_a
                )
            else:  # draw
                weight_a = weight_b = fight_weight

            k_a = self.k_factor * weight_a * quality_a * streak_a * k_var_a * rematch_mult * opp_mom_a * time_mult_a
            k_b = self.k_factor * weight_b * quality_b * streak_b * k_var_b * rematch_mult * opp_mom_b * time_mult_b

            expected_a = self._expected_score(elo_a, elo_b)
            expected_b = 1.0 - expected_a

            delta_a = k_a * (score_a - expected_a)
            delta_b = k_b * (score_b - expected_b)

            # Don't reward beating a very weak opponent too much
            cap_a = cap_b = False
            if score_a == 1.0 and elo_b < 1300 and delta_a > 8.0:
                delta_a = 8.0;  cap_a = True
            if score_b == 1.0 and elo_a < 1300 and delta_b > 8.0:
                delta_b = 8.0;  cap_b = True

            # Cap single-fight loss at -80 to avoid one-night ELO destruction
            if score_a == 0.0 and delta_a < -80.0:
                delta_a = -80.0;  cap_a = True
            if score_b == 0.0 and delta_b < -80.0:
                delta_b = -80.0;  cap_b = True

            # Peak ELO penalty: sustained decline far below career high
            pp_a = pp_b = False
            if score_a == 0.0 and streaks[fight.fighter_a_id] <= -3 and elo_a < peak_elos.get(fight.fighter_a_id, elo_a) * 0.85:
                delta_a *= 1.20;  pp_a = True
            if score_b == 0.0 and streaks[fight.fighter_b_id] <= -3 and elo_b < peak_elos.get(fight.fighter_b_id, elo_b) * 0.85:
                delta_b *= 1.20;  pp_b = True

            # ── Absolute sign guard ───────────────────────────────────────────
            # A winner must always gain ELO; a loser must always lose ELO.
            # This is a last-resort safety net — no combination of multipliers
            # or data quirks should invert the result of a fight.
            if score_a == 1.0:
                delta_a = max(delta_a, 1.0)
            elif score_a == 0.0:
                delta_a = min(delta_a, -1.0)
            if score_b == 1.0:
                delta_b = max(delta_b, 1.0)
            elif score_b == 0.0:
                delta_b = min(delta_b, -1.0)

            # Apply floor: no active fighter below 1000
            new_a = max(1000.0, elo_a + delta_a)
            new_b = max(1000.0, elo_b + delta_b)

            if self.debug:
                self._log_fight(
                    fight, elo_a, elo_b, expected_a,
                    score_a, score_b, k_a, k_b,
                    weight_a, weight_b, fight_weight,
                    quality_a, quality_b, streak_a, streak_b,
                    k_var_a, k_var_b, rematch_mult, opp_mom_a, opp_mom_b,
                    time_mult_a, time_mult_b,
                    delta_a, delta_b, new_a, new_b,
                    was_a_favorite,
                )

            ratings[fight.fighter_a_id] = new_a
            ratings[fight.fighter_b_id] = new_b

            # Peak ELO tracking (recorded before inactivity decay — true career high)
            fight_date_str = fight.event_date.strftime("%Y-%m-%d")
            if new_a > peak_elos.get(fight.fighter_a_id, self.base_elo):
                peak_elos[fight.fighter_a_id] = new_a
                peak_elo_dates[fight.fighter_a_id] = fight_date_str
                peak_elo_opponents[fight.fighter_a_id] = fight.fighter_b_name
            if new_b > peak_elos.get(fight.fighter_b_id, self.base_elo):
                peak_elos[fight.fighter_b_id] = new_b
                peak_elo_dates[fight.fighter_b_id] = fight_date_str
                peak_elo_opponents[fight.fighter_b_id] = fight.fighter_a_name

            # Save pre-update streaks for the breakdown
            streak_val_a = streaks[fight.fighter_a_id]
            streak_val_b = streaks[fight.fighter_b_id]

            streaks[fight.fighter_a_id] = self._update_streak(streaks[fight.fighter_a_id], score_a)
            streaks[fight.fighter_b_id] = self._update_streak(streaks[fight.fighter_b_id], score_b)
            fight_counts[fight.fighter_a_id] += 1
            fight_counts[fight.fighter_b_id] += 1
            last_fight_dates[fight.fighter_a_id] = fight.event_date
            last_fight_dates[fight.fighter_b_id] = fight.event_date
            pair_history.setdefault(pair_key, []).append(fight.winner_id)

            result_a = "Win" if score_a == 1.0 else "Loss" if score_a == 0.0 else "Draw"
            result_b = "Win" if score_b == 1.0 else "Loss" if score_b == 0.0 else "Draw"

            # ── Per-fight ELO breakdown ───────────────────────────────────────
            div_m = _DIVISION_K_MULT.get(self.division, 0.90)
            breakdown_a: Dict[str, Any] = {
                "elo_before":      round(elo_a, 2),
                "elo_after":       round(new_a, 2),
                "delta":           round(new_a - elo_a, 2),
                "k_base":          self.k_factor,
                "k_var":           round(k_var_a, 4),
                "div_mult":        round(div_m, 3),
                "streak_before":   streak_val_a,
                "streak_mult":     round(streak_a, 3),
                "method_weight":   round(weight_a, 4),
                "consec_loss_mult": round(clm_a, 3),
                "quality_mult":    round(quality_a, 3),
                "rematch_mult":    round(rematch_mult, 3),
                "opp_mom_mult":    round(opp_mom_a, 3),
                "time_mult":       round(time_mult_a, 3),
                "k_effective":     round(k_a, 3),
                "expected_prob":   round(expected_a, 4),
                "surprise":        round(score_a - expected_a, 4),
                "cap_applied":     cap_a,
                "peak_penalty":    pp_a,
            }
            breakdown_b: Dict[str, Any] = {
                "elo_before":      round(elo_b, 2),
                "elo_after":       round(new_b, 2),
                "delta":           round(new_b - elo_b, 2),
                "k_base":          self.k_factor,
                "k_var":           round(k_var_b, 4),
                "div_mult":        round(div_m, 3),
                "streak_before":   streak_val_b,
                "streak_mult":     round(streak_b, 3),
                "method_weight":   round(weight_b, 4),
                "consec_loss_mult": round(clm_b, 3),
                "quality_mult":    round(quality_b, 3),
                "rematch_mult":    round(rematch_mult, 3),
                "opp_mom_mult":    round(opp_mom_b, 3),
                "time_mult":       round(time_mult_b, 3),
                "k_effective":     round(k_b, 3),
                "expected_prob":   round(expected_b, 4),
                "surprise":        round(score_b - expected_b, 4),
                "cap_applied":     cap_b,
                "peak_penalty":    pp_b,
            }

            histories[fight.fighter_a_id].append(asdict(EloHistoryPoint(
                date=fight_date_str,
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
                breakdown=breakdown_a,
            )))

            histories[fight.fighter_b_id].append(asdict(EloHistoryPoint(
                date=fight_date_str,
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
                breakdown=breakdown_b,
            )))

        # Display-only inactivity decay: 0.5%/month toward base ELO, capped at 24 months.
        # Applied at ranking-output time — elo_histories stays as the pure fight record.
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
                "fighter_name": fighter_info.get("name") or names_from_fights.get(fighter_id) or "Unknown",
                "division": fighter_info.get("division") or self.division.title(),
                "elo": round(displayed_elo, 2),
                "peak_elo": round(peak_elos.get(fighter_id, self.base_elo), 2),
                "peak_elo_date": peak_elo_dates.get(fighter_id),
                "peak_elo_opponent": peak_elo_opponents.get(fighter_id),
                "record": fighter_info.get("record"),
                "fight_count": fight_counts.get(fighter_id, 0),
                "last_fight_date": last_date.strftime("%Y-%m-%d") if last_date else None,
                "active": active,
                "streak": streaks.get(fighter_id, 0),
                "division_elo_entry": round(initial_ratings.get(fighter_id, self.base_elo), 2),
            })

        ranking.sort(key=lambda x: x["elo"], reverse=True)
        return ranking, histories

    # ── ELO core ──────────────────────────────────────────────────────────────

    def _expected_score(self, elo_a: float, elo_b: float) -> float:
        diff = max(-250.0, min(250.0, elo_a - elo_b))
        return 1.0 / (1.0 + 10 ** (-diff / 400.0))

    def _result_score(self, fight: FightRecord) -> tuple:
        if fight.winner_id == fight.fighter_a_id:
            return 1.0, 0.0
        if fight.winner_id == fight.fighter_b_id:
            return 0.0, 1.0
        return 0.5, 0.5

    # ── K-factor multipliers ──────────────────────────────────────────────────

    def _fight_weight(self, method: str, is_title: bool, round_num: int) -> float:
        """Weight applied to the WINNER's K. Finishing wins are worth more."""
        if method in {"KO/TKO", "SUB"}:
            if round_num == 1:   weight = 1.40
            elif round_num == 2: weight = 1.25
            else:                weight = 1.10
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

    def _loss_method_mult(self, method: str, is_title: bool, round_num: int, was_favorite: bool) -> float:
        """Weight applied to the LOSER's K.
        Symmetric in spirit to _fight_weight but tuned for losses:
        - Being KO'd is more informative than losing a split decision.
        - SUB is flat (not round-dependent) since grappling dominance is consistent.
        - Extra ×1.20 if the loser was the ELO favorite in a title fight
          (strongest signal of ELO overestimation).
        """
        if method == "KO/TKO":
            if round_num == 1:   mult = 1.40
            elif round_num == 2: mult = 1.25
            else:                mult = 1.10
        elif method == "SUB":
            mult = 1.20
        elif method == "DEC U":
            mult = 1.05
        elif method == "DEC M":
            mult = 0.90
        else:  # DEC S, OTHER
            mult = 0.80
        if is_title and was_favorite:
            mult *= 1.20
        return mult

    def _consecutive_loss_mult(self, consec: int) -> float:
        """Escalating penalty for fighters deep in a losing streak.
        consec = ordinal position of this loss in the current run (1 = first loss).
        Resets to 1 after any win or draw.
        """
        if consec >= 5: return 1.80
        if consec >= 4: return 1.60
        if consec >= 3: return 1.40
        if consec >= 2: return 1.20
        return 1.00

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
        if streak >= 8:  return 1.35
        if streak >= 5:  return 1.25
        if streak >= 3:  return 1.15
        if streak <= -8: return 1.55
        if streak <= -5: return 1.40
        if streak <= -3: return 1.25
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

    def _initial_elo(self, fighter_id: str, fighters: Dict[str, Dict]) -> float:
        # Cross-division carry-over: use ELO from last fight in prior division
        if fighter_id in self.prior_elos:
            return self.prior_elos[fighter_id]
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

    def _log_fight(
        self, fight, elo_a, elo_b, expected_a,
        score_a, score_b, k_a, k_b,
        weight_a, weight_b, fight_weight,
        quality_a, quality_b, streak_a, streak_b,
        k_var_a, k_var_b, rematch_mult, opp_mom_a, opp_mom_b,
        time_mult_a, time_mult_b,
        delta_a, delta_b, new_a, new_b,
        was_a_favorite,
    ) -> None:
        result_a = "Win" if score_a == 1.0 else "Loss" if score_a == 0.0 else "Draw"
        result_b = "Win" if score_b == 1.0 else "Loss" if score_b == 0.0 else "Draw"
        title_flag = " [TÍTULO]" if fight.is_title_fight else ""
        fav_flag = "A es favorito" if was_a_favorite else "B es favorito"
        print(
            f"\n[{fight.fighter_a_name} vs {fight.fighter_b_name} — {fight.event_date.strftime('%Y-%m-%d')}{title_flag}]"
            f"\n  Método: {fight.method}  R{fight.round}  |  {fav_flag}"
            f"\n  {'Fighter A':>10}: {fight.fighter_a_name:<25} ELO={elo_a:>8.1f}  S={score_a}  ({result_a})"
            f"\n  {'Fighter B':>10}: {fight.fighter_b_name:<25} ELO={elo_b:>8.1f}  S={score_b}  ({result_b})"
            f"\n  E(A)={expected_a:.4f}  E(B)={1-expected_a:.4f}"
            f"\n  ── K factors ──────────────────────────────────────────"
            f"\n  K_base={self.k_factor}  K_div={_DIVISION_K_MULT.get(self.division, 0.9)}"
            f"\n  A: W={weight_a:.3f} (fight_w={fight_weight:.3f})  qual={quality_a:.3f}  str={streak_a:.3f}"
            f"\n     kvar={k_var_a:.4f}  rematch={rematch_mult:.2f}  mom={opp_mom_a:.2f}  time={time_mult_a:.2f}"
            f"\n     K_efectivo={k_a:.3f}"
            f"\n  B: W={weight_b:.3f}  qual={quality_b:.3f}  str={streak_b:.3f}"
            f"\n     kvar={k_var_b:.4f}  rematch={rematch_mult:.2f}  mom={opp_mom_b:.2f}  time={time_mult_b:.2f}"
            f"\n     K_efectivo={k_b:.3f}"
            f"\n  ── Deltas ─────────────────────────────────────────────"
            f"\n  delta_A={delta_a:+.2f}  ({elo_a:.1f} → {new_a:.1f})"
            f"\n  delta_B={delta_b:+.2f}  ({elo_b:.1f} → {new_b:.1f})"
        )


class SkillScoreEngine:
    def __init__(self, smoothing: float = 0.80):
        self.smoothing = smoothing

    def process(
        self,
        fights: List[FightRecord],
        fighters: Dict[str, Dict[str, Optional[str]]],
        prior_skills: Dict[str, Dict[str, float]] | None = None,
    ) -> tuple:
        # Initialize skill scores: use prior-division carry-over if available, else default 50.0
        skill_scores: Dict[str, Dict[str, float]] = {}
        for fighter_id in fighters.keys():
            if prior_skills and fighter_id in prior_skills:
                skill_scores[fighter_id] = dict(prior_skills[fighter_id])
            else:
                skill_scores[fighter_id] = {dim: 50.0 for dim in SKILL_DIMENSIONS}
        histories: Dict[str, List[Dict[str, object]]] = {fighter_id: [] for fighter_id in fighters.keys()}

        for fight in fights:
            for fighter_id, _, opponent_id, opponent_name, side in [
                (fight.fighter_a_id, fight.fighter_a_name, fight.fighter_b_id, fight.fighter_b_name, "a"),
                (fight.fighter_b_id, fight.fighter_b_name, fight.fighter_a_id, fight.fighter_a_name, "b"),
            ]:
                if fighter_id not in skill_scores:
                    if prior_skills and fighter_id in prior_skills:
                        skill_scores[fighter_id] = dict(prior_skills[fighter_id])
                    else:
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

        stats = fight.fighter_a_stats if side == "a" else fight.fighter_b_stats
        opponent_stats = fight.fighter_b_stats if side == "a" else fight.fighter_a_stats

        if not stats or not opponent_stats:
            return self._default_scores(method, is_winner)

        striking_accuracy = stats.strikes_landed / max(stats.strikes_attempted, 1)
        fight_minutes = fight.round * 5
        striking_volume = stats.strikes_landed / max(fight_minutes * _STRIKES_PER_MINUTE_BASELINE, 1)

        takedown_accuracy = stats.takedowns_landed / max(stats.takedowns_attempted, 1)
        takedown_defense = 1.0 - (opponent_stats.takedowns_landed / max(opponent_stats.takedowns_attempted, 1))

        control_seconds = self._time_to_seconds(stats.control_time)
        total_fight_seconds = fight.round * 300
        control_ratio = control_seconds / max(total_fight_seconds, 1)

        head_accuracy = stats.head_strikes_landed / max(stats.head_strikes_attempted, 1)
        body_accuracy = stats.body_strikes_landed / max(stats.body_strikes_attempted, 1)
        leg_accuracy = stats.leg_strikes_landed / max(stats.leg_strikes_attempted, 1)

        raw = {
            "Striking": min(1.0, (striking_accuracy * 0.6 + striking_volume * 0.4) * 1.2),
            "Grappling": min(1.0, (takedown_accuracy * 0.7 + takedown_defense * 0.3) * 1.1),
            "Defensa": min(1.0, takedown_defense * 0.8 + (1.0 - opponent_stats.strikes_landed / max(opponent_stats.strikes_attempted, 1)) * 0.2),
            "Consistencia": min(1.0, (head_accuracy + body_accuracy + leg_accuracy) / 3.0),
            "Finish Rate": 1.0 if method in {"KO/TKO", "SUB"} and is_winner else 0.3,
            "Cardio/Durabilidad": min(1.0, 0.8 + (fight.round - 1) * 0.1),
            "Presión": min(1.0, control_ratio * 0.7 + striking_volume * 0.3),
        }

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

        if fight.is_title_fight:
            for dim in raw:
                raw[dim] += 0.04
        if method in {"KO/TKO", "SUB"} and 1 <= fight.round <= 2:
            for dim in raw:
                raw[dim] += 0.03

        return {dim: round(min(100.0, max(0.0, raw[dim] * 100)), 2) for dim in SKILL_DIMENSIONS}

    def _default_scores(self, method: str, is_winner: bool) -> Dict[str, float]:
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
                "Striking": 0.88, "Grappling": 0.30, "Defensa": 0.72,
                "Consistencia": 0.58, "Finish Rate": 1.0,
                "Cardio/Durabilidad": 0.62, "Presión": 0.82,
            })
        elif method == "SUB":
            raw.update({
                "Striking": 0.42, "Grappling": 0.92, "Defensa": 0.68,
                "Consistencia": 0.64, "Finish Rate": 1.0,
                "Cardio/Durabilidad": 0.58, "Presión": 0.72,
            })
        elif method in {"DEC U", "DEC S", "DEC M"}:
            raw.update({
                "Striking": 0.72, "Grappling": 0.68, "Defensa": 0.79,
                "Consistencia": 0.84, "Finish Rate": 0.24,
                "Cardio/Durabilidad": 0.90, "Presión": 0.88,
            })

        outcome_factor = 1.0
        if not is_winner:
            if method == "KO/TKO":   outcome_factor = 0.72
            elif method == "SUB":    outcome_factor = 0.78
            else:                    outcome_factor = 0.90

        for dim, value in raw.items():
            raw[dim] = min(1.0, max(0.0, value * (0.70 + 0.30 * outcome_factor)))

        return {dim: round(v * 100, 2) for dim, v in raw.items()}

    def _time_to_seconds(self, time_str: str) -> int:
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


def _load_prior_division_elos(
    current_division: str,
    fights: List[FightRecord],
    output_dir: Path,
) -> Dict[str, float]:
    """For fighters who competed in another division before this one,
    return their exit ELO from that division as their starting point here.

    Only uses fights from the other division that occurred BEFORE the
    fighter's first appearance in the current division.
    """
    current_slug = current_division.lower().replace(" ", "_")

    # Earliest fight date per fighter in the current division
    earliest_here: Dict[str, datetime] = {}
    for fight in fights:
        for fid in (fight.fighter_a_id, fight.fighter_b_id):
            if fid not in earliest_here or fight.event_date < earliest_here[fid]:
                earliest_here[fid] = fight.event_date

    prior_elos: Dict[str, float] = {}
    for other_div in _DIVISIONS_ALL:
        other_slug = other_div.replace(" ", "_")
        if other_slug == current_slug:
            continue
        hist_path = output_dir / f"elo_histories_{other_slug}.json"
        if not hist_path.exists():
            continue
        try:
            with hist_path.open("r", encoding="utf-8") as f:
                histories = json.load(f)
        except Exception:
            continue

        for fid, hist in histories.items():
            if not hist or fid not in earliest_here:
                continue
            cutoff = earliest_here[fid].strftime("%Y-%m-%d")
            prior_fights = [h for h in hist if h.get("date", "") < cutoff]
            if not prior_fights:
                continue
            last_prior = max(prior_fights, key=lambda h: h.get("date", ""))
            prior_elo = float(last_prior["elo"])
            # Keep the highest prior ELO if multiple divisions qualify
            if fid not in prior_elos or prior_elo > prior_elos[fid]:
                prior_elos[fid] = prior_elo

    if prior_elos:
        log.info("[%s] Cross-division ELO carry-over: %d fighters", current_division, len(prior_elos))
    return prior_elos


def _load_prior_division_skills(
    current_division: str,
    fights: List[FightRecord],
    output_dir: Path,
) -> Dict[str, Dict[str, float]]:
    """For fighters entering this division from another, return their final skill
    scores from their previous division as the starting point for EMA here.
    Same logic as ELO carry-over: skills belong to the FIGHTER, not the division.
    """
    current_slug = current_division.lower().replace(" ", "_")

    earliest_here: Dict[str, datetime] = {}
    for fight in fights:
        for fid in (fight.fighter_a_id, fight.fighter_b_id):
            if fid not in earliest_here or fight.event_date < earliest_here[fid]:
                earliest_here[fid] = fight.event_date

    prior_skills: Dict[str, Dict[str, float]] = {}
    for other_div in _DIVISIONS_ALL:
        other_slug = other_div.replace(" ", "_")
        if other_slug == current_slug:
            continue
        hist_path = output_dir / f"skill_histories_{other_slug}.json"
        if not hist_path.exists():
            continue
        try:
            with hist_path.open("r", encoding="utf-8") as f:
                skill_histories = json.load(f)
        except Exception:
            continue

        for fid, hist in skill_histories.items():
            if not hist or fid not in earliest_here or fid in prior_skills:
                continue
            cutoff = earliest_here[fid].strftime("%Y-%m-%d")
            prior_entries = [h for h in hist if h.get("date", "") < cutoff]
            if not prior_entries:
                continue
            last_prior = max(prior_entries, key=lambda h: h.get("date", ""))
            skill = last_prior.get("skill_score")
            if skill:
                prior_skills[fid] = skill

    if prior_skills:
        log.info("[%s] Skill score carry-over: %d fighters", current_division, len(prior_skills))
    return prior_skills


def main():
    parser = argparse.ArgumentParser(description="Elo engine para UFC")
    parser.add_argument("--division", default="heavyweight",
                        help="División a procesar (ej: heavyweight, lightweight)")
    parser.add_argument("--fights", default=None,
                        help="Ruta al CSV de peleas (default: data/fights_{division}.csv)")
    parser.add_argument("--fighters", default=None,
                        help="Ruta al JSON de peleadores (default: data/fighters_{division}.json)")
    parser.add_argument("--output", default="data", help="Directorio de salida")
    parser.add_argument("--debug", action="store_true",
                        help="Imprime cálculo detallado de cada pelea a stdout")
    args = parser.parse_args()

    division_slug = args.division.lower().replace(" ", "_")
    if args.fights is None:
        args.fights = f"data/fights_{division_slug}.csv"
    if args.fighters is None:
        fighters_path_candidate = Path(f"data/fighters_{division_slug}.json")
        # Fall back to global fighters.json if the division file is missing or empty
        if fighters_path_candidate.exists() and fighters_path_candidate.stat().st_size > 4:
            args.fighters = str(fighters_path_candidate)
        else:
            args.fighters = "data/fighters.json"

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
        log.warning("[%s] fighters JSON vacío — se usarán nombres del CSV.", args.division)

    # Load cross-division carry-overs for fighters who moved divisions
    prior_elos = _load_prior_division_elos(args.division, fights, output_dir)
    prior_skills = _load_prior_division_skills(args.division, fights, output_dir)

    elo_engine = EloEngine(division=args.division, prior_elos=prior_elos, debug=args.debug)
    skill_engine = SkillScoreEngine()

    ranking, elo_histories = elo_engine.process(fights, fighters)
    skill_scores, skill_histories = skill_engine.process(fights, fighters, prior_skills=prior_skills)

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
