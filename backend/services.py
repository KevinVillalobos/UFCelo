import random as _random
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from .data_loader import (
    get_fighter_by_id,
    get_skill_score_by_id,
    get_upcoming_events,
    load_champions,
    load_elo_histories,
    load_rankings,
    load_retired_overrides,
    load_skill_histories,
    load_skill_scores,
)


def elo_win_probability(elo_a: float, elo_b: float) -> float:
    diff = elo_b - elo_a
    denominator = 1 + 10 ** (diff / 400)
    return 1.0 / denominator


def _ranking_entry(item: Dict[str, object], division: str, index: int, is_champion: bool = False) -> Dict[str, object]:
    return {
        "fighter_id": str(item.get("id") or item.get("fighter_id") or item.get("fighter")),
        "fighter_name": item.get("name") or item.get("fighter_name"),
        "division": division,
        "elo": float(item.get("elo", 0)),
        "rank": index,
        "record": item.get("record"),
        "fight_count": item.get("fight_count"),
        "last_fight_date": item.get("last_fight_date"),
        "peak_elo": float(item["peak_elo"]) if item.get("peak_elo") is not None else None,
        "peak_elo_date": item.get("peak_elo_date"),
        "peak_elo_opponent": item.get("peak_elo_opponent"),
        "active": item.get("active"),
        "streak": item.get("streak", 0),
        "is_champion": is_champion,
    }


_DIVISIONS_ALL = [
    "heavyweight", "light heavyweight", "middleweight", "welterweight",
    "lightweight", "featherweight", "bantamweight", "flyweight",
]


def _division_elo_index() -> tuple:
    """Single pass over all divisions.
    Returns (primary_div_map, max_elo_map):
      primary_div_map  — {fighter_id: division with highest ELO}
      max_elo_map      — {fighter_id: highest ELO across all divisions}
    """
    best_elo: Dict[str, float] = {}
    best_div: Dict[str, str] = {}
    for div in _DIVISIONS_ALL:
        try:
            for item in load_rankings(div):
                fid = str(item.get("id") or item.get("fighter_id") or "")
                if not fid:
                    continue
                elo = float(item.get("elo", 0))
                if elo > best_elo.get(fid, 0):
                    best_elo[fid] = elo
                    best_div[fid] = div
        except Exception:
            continue
    return best_div, best_elo


def build_ranking_response(division: str, alltime: bool = False) -> List[Dict[str, object]]:
    rankings = load_rankings(division, alltime=alltime)
    if alltime:
        return [_ranking_entry(item, division, item.get("alltime_rank", i + 1)) for i, item in enumerate(rankings)]

    retired_overrides = load_retired_overrides()
    primary_map, max_elo_map = _division_elo_index()
    all_champions = load_champions()

    # fighter_id → their champion division (skip empty IDs for TBD entries)
    champ_divisions: Dict[str, str] = {
        info["fighter_id"]: div
        for div, info in all_champions.items()
        if isinstance(info, dict) and info.get("fighter_id")
    }
    champ_id = (all_champions.get(division.lower()) or {}).get("fighter_id") or ""

    sorted_rankings = sorted(rankings, key=lambda item: float(item.get("elo", 0)), reverse=True)
    active = []
    for item in sorted_rankings:
        fid = str(item.get("id") or item.get("fighter_id") or "")
        if not fid:
            continue
        if retired_overrides.get(fid, False):
            continue
        fighter_champ_div = champ_divisions.get(fid)
        if fighter_champ_div:
            # Champion: only include in their designated division
            if fighter_champ_div != division:
                continue
        else:
            # Non-champion: only include in the division where their ELO is highest
            if primary_map.get(fid, division) != division:
                continue
        # Use the fighter's best ELO across all divisions (carries over on division move)
        max_e = max_elo_map.get(fid, 0)
        if max_e > float(item.get("elo", 0)):
            item = dict(item)
            item["elo"] = max_e
        active.append(item)

    # Inject champion at position #1 regardless of ELO rank
    result = []
    champion_item = None
    rest = []
    for item in active:
        fid = str(item.get("id") or item.get("fighter_id") or "")
        if champ_id and fid == champ_id:
            champion_item = item
        else:
            rest.append(item)
    if champion_item:
        result.append(_ranking_entry(champion_item, division, 1, is_champion=True))
        for i, item in enumerate(rest, start=2):
            result.append(_ranking_entry(item, division, i))
    else:
        for i, item in enumerate(active, start=1):
            result.append(_ranking_entry(item, division, i))
    return result


def _get_current_elo(fighter_id: str, fighter: Dict[str, object], division: str = "heavyweight") -> float:
    elo_value = float(fighter.get("elo", 0) or 0)
    if elo_value > 0:
        return elo_value
    histories = load_elo_histories(division).get(str(fighter_id), [])
    if not histories:
        return 0.0
    last_entry = sorted(histories, key=lambda entry: entry.get("date") or "")[-1]
    raw_elo = float(last_entry.get("elo", 0))
    last_date_str = last_entry.get("date")
    if last_date_str:
        try:
            last_dt = datetime.strptime(last_date_str, "%Y-%m-%d")
            months_inactive = (datetime.now() - last_dt).days / 30.44
            if months_inactive > 0:
                capped = min(24.0, months_inactive)
                decay_delta = (raw_elo - 1500.0) * 0.005 * capped
                return raw_elo - decay_delta
        except ValueError:
            pass
    return raw_elo


def build_fighter_profile(fighter_id: str, division: str = "heavyweight") -> Optional[Dict[str, object]]:
    fighter = get_fighter_by_id(fighter_id, division)
    if not fighter:
        return None

    elo_histories = load_elo_histories(division).get(str(fighter_id), [])
    sorted_histories = sorted(elo_histories, key=lambda entry: entry.get("date") or "")
    elo_history_response = []
    prev_elo: Optional[float] = None
    for item in sorted_histories:
        cur_elo = float(item.get("elo", 0))
        elo_change = round(cur_elo - prev_elo, 1) if prev_elo is not None else None
        prev_elo = cur_elo
        elo_history_response.append({
            "date": item.get("date"),
            "elo": cur_elo,
            "elo_change": elo_change,
            "opponent_id": item.get("opponent_id"),
            "opponent_name": item.get("opponent_name"),
            "result": item.get("result"),
            "method": item.get("method"),
            "round": item.get("round"),
            "time": item.get("time"),
            "is_title_fight": item.get("is_title_fight", False),
            "event": item.get("event"),
        })

    skill_item = get_skill_score_by_id(fighter_id, division) or {}
    skill_score = skill_item.get("skill_score", {})
    skill_composite = skill_item.get("skill_composite")
    skill_histories = load_skill_histories(division).get(str(fighter_id), [])
    skill_history_response = []
    for item in sorted(skill_histories, key=lambda entry: entry.get("date") or ""):
        skill_history_response.append(
            {
                "date": item.get("date"),
                "fight_id": item.get("fight_id"),
                "opponent_id": item.get("opponent_id"),
                "opponent_name": item.get("opponent_name"),
                "result": item.get("result"),
                "skill_score": item.get("skill_score", {}),
                "event": item.get("event"),
            }
        )

    return {
        "fighter_id": str(fighter.get("id") or fighter.get("fighter_id") or fighter_id),
        "fighter_name": fighter.get("name") or fighter.get("full_name"),
        "division": fighter.get("division") or division.title(),
        "elo": _get_current_elo(fighter_id, fighter, division),
        "record": fighter.get("record"),
        "country": fighter.get("country"),
        "height": fighter.get("height"),
        "weight": fighter.get("weight"),
        "reach": fighter.get("reach"),
        "stance": fighter.get("stance"),
        "elo_history": elo_history_response,
        "skill_score": skill_score,
        "skill_composite": skill_composite,
        "skill_history": skill_history_response,
    }


def _predict_method(favored_skill: Dict[str, float]) -> str:
    striking = favored_skill.get("Striking", 50)
    grappling = favored_skill.get("Grappling", 50)
    finish_rate = favored_skill.get("Finish Rate", 50)
    if finish_rate < 55:
        return "DEC"
    # When both are elite finishers, prefer the dominant style
    if striking >= 65 and grappling >= 65:
        return "SUB" if grappling > striking else "KO/TKO"
    if striking >= 65:
        return "KO/TKO"
    if grappling >= 65:
        return "SUB"
    return "DEC"


def _skill_composite(skill: Dict[str, float]) -> float:
    """Weighted composite score from the 7 skill dimensions (0–100 scale)."""
    if not skill:
        return 50.0
    weights = {
        "Striking": 0.20,
        "Grappling": 0.15,
        "Defensa": 0.20,
        "Consistencia": 0.15,
        "Finish Rate": 0.10,
        "Cardio/Durabilidad": 0.10,
        "Presión": 0.10,
    }
    total_w = sum(weights.get(k, 0) for k in skill)
    if total_w == 0:
        return sum(skill.values()) / len(skill)
    return sum(skill[k] * weights.get(k, 0) for k in skill) / total_w


def build_prediction(fighter_a_id: str, fighter_b_id: str, division: str = "heavyweight") -> Optional[Dict[str, object]]:
    fighter_a = get_fighter_by_id(fighter_a_id, division)
    fighter_b = get_fighter_by_id(fighter_b_id, division)
    if not fighter_a or not fighter_b:
        return None

    elo_a = _get_current_elo(fighter_a_id, fighter_a, division)
    elo_b = _get_current_elo(fighter_b_id, fighter_b, division)
    prob_elo_a = elo_win_probability(elo_a, elo_b)

    skill_item_a = get_skill_score_by_id(fighter_a_id, division) or {}
    skill_item_b = get_skill_score_by_id(fighter_b_id, division) or {}
    skill_a: Dict[str, float] = skill_item_a.get("skill_score", {})
    skill_b: Dict[str, float] = skill_item_b.get("skill_score", {})

    comp_a = _skill_composite(skill_a)
    comp_b = _skill_composite(skill_b)

    # Blend ELO probability with a skill-derived shift (max ±5%)
    skill_diff_normalized = (comp_a - comp_b) / 100.0  # range roughly -1 to +1
    skill_adjustment = skill_diff_normalized * 0.10    # max ±10% of full diff
    prob_a = max(0.05, min(0.95, prob_elo_a + skill_adjustment))
    prob_b = 1.0 - prob_a

    # Per-dimension advantages (positive = favors A, negative = favors B)
    dims = set(skill_a) | set(skill_b)
    skill_advantages = {
        dim: round((skill_a.get(dim, 50.0) - skill_b.get(dim, 50.0)), 2)
        for dim in dims
    }

    favored_skill = skill_a if prob_a >= 0.5 else skill_b
    method_prediction = _predict_method(favored_skill)

    dim_diffs = {dim: abs(skill_a.get(dim, 50.0) - skill_b.get(dim, 50.0)) for dim in dims}
    key_advantage = max(dim_diffs, key=dim_diffs.get) if dim_diffs else None

    return {
        "fighter_a_id": str(fighter_a_id),
        "fighter_b_id": str(fighter_b_id),
        "fighter_a_name": fighter_a.get("name") or fighter_a.get("full_name"),
        "fighter_b_name": fighter_b.get("name") or fighter_b.get("full_name"),
        "probability_a": round(prob_a, 4),
        "probability_b": round(prob_b, 4),
        "elo_probability_a": round(prob_elo_a, 4),
        "elo_difference": round(elo_a - elo_b, 2),
        "skill_composite_a": round(comp_a, 2),
        "skill_composite_b": round(comp_b, 2),
        "skill_advantages": skill_advantages,
        "method_prediction": method_prediction,
        "key_advantage": key_advantage,
    }


def build_matchmaking(division: str, top_n: int = 50) -> List[Dict[str, object]]:
    rankings = build_ranking_response(division)  # active + non-retired only
    if not rankings:
        return []

    # Build recent-opponent sets from elo_histories (last 2 years)
    histories = load_elo_histories(division)
    cutoff_str = (datetime.now() - timedelta(days=730)).strftime("%Y-%m-%d")
    recent_opponents: Dict[str, set] = {}
    for fid, hist in histories.items():
        recent_opponents[fid] = {
            str(entry["opponent_id"])
            for entry in hist
            if entry.get("date", "") >= cutoff_str and entry.get("opponent_id")
        }

    # Build skill score lookup in one pass
    all_skills = load_skill_scores(division)
    skill_lookup: Dict[str, Dict[str, float]] = {
        str(s.get("fighter_id") or s.get("id") or ""): s.get("skill_score", {})
        for s in all_skills
    }

    matchups = []
    for i in range(len(rankings)):
        for j in range(i + 1, len(rankings)):
            a = rankings[i]
            b = rankings[j]
            fid_a = a["fighter_id"]
            fid_b = b["fighter_id"]

            elo_diff = abs(a["elo"] - b["elo"])
            if elo_diff > 300:
                continue
            if fid_b in recent_opponents.get(fid_a, set()):
                continue

            comp_score = max(0.0, 1.0 - (elo_diff / 200.0))

            sa = skill_lookup.get(fid_a, {})
            sb = skill_lookup.get(fid_b, {})
            dims = set(sa) | set(sb)
            if dims:
                dim_diffs = {d: abs(sa.get(d, 50.0) - sb.get(d, 50.0)) for d in dims}
                skill_contrast = sum(dim_diffs.values()) / (len(dims) * 100.0)
                key_dim = max(dim_diffs, key=dim_diffs.get)
                key_diff = dim_diffs[key_dim]
            else:
                skill_contrast = 0.0
                key_dim = None
                key_diff = 0.0

            matchup_score = 0.70 * comp_score + 0.30 * skill_contrast

            prob_a = 1.0 / (1.0 + 10 ** ((b["elo"] - a["elo"]) / 400.0))

            matchups.append({
                "fighter_a_id": fid_a,
                "fighter_b_id": fid_b,
                "fighter_a_name": a["fighter_name"],
                "fighter_b_name": b["fighter_name"],
                "elo_a": a["elo"],
                "elo_b": b["elo"],
                "elo_difference": round(elo_diff, 2),
                "competitiveness_score": round(comp_score, 4),
                "skill_contrast_score": round(skill_contrast, 4),
                "matchup_score": round(matchup_score, 4),
                "key_dimension": key_dim,
                "key_dimension_diff": round(key_diff, 2),
                "probability_a": round(prob_a, 4),
                "probability_b": round(1.0 - prob_a, 4),
            })

    matchups.sort(key=lambda m: m["matchup_score"], reverse=True)
    return matchups[:top_n]


# ── Fight simulation ──────────────────────────────────────────────────────────

def _sim_method(skill: Dict[str, float], rng: _random.Random) -> str:
    striking = skill.get("Striking", 50) / 100
    grappling = skill.get("Grappling", 50) / 100
    finish_rate = skill.get("Finish Rate", 50) / 100
    ko_w = striking * finish_rate
    sub_w = grappling * finish_rate
    dec_w = max(0.10, 1.0 - (ko_w + sub_w))
    total = ko_w + sub_w + dec_w
    r = rng.random() * total
    if r < ko_w:
        return "KO/TKO"
    if r < ko_w + sub_w:
        return "SUB"
    return "DEC"


def _sim_round(method: str, skill: Dict[str, float], max_rounds: int, rng: _random.Random) -> int:
    presion = skill.get("Presión", 50) / 100
    cardio = skill.get("Cardio/Durabilidad", 50) / 100
    if method == "KO/TKO":
        weights = [max(0.05, 0.40 + presion * 0.15), max(0.05, 0.35), max(0.05, 0.25 - presion * 0.10)]
    else:  # SUB
        weights = [max(0.05, 0.20), max(0.05, 0.35), max(0.05, 0.30 + cardio * 0.15)]
    weights = weights[:max_rounds]
    total = sum(weights)
    r = rng.random() * total
    cumulative = 0.0
    for i, w in enumerate(weights, 1):
        cumulative += w
        if r <= cumulative:
            return i
    return max_rounds


def build_fight_simulation(
    fighter_a_id: str,
    fighter_b_id: str,
    n: int = 1000,
    rounds: int = 3,
    seed: Optional[int] = None,
    division: str = "heavyweight",
) -> Optional[Dict[str, object]]:
    fighter_a = get_fighter_by_id(fighter_a_id, division)
    fighter_b = get_fighter_by_id(fighter_b_id, division)
    if not fighter_a or not fighter_b:
        return None

    elo_a = _get_current_elo(fighter_a_id, fighter_a, division)
    elo_b = _get_current_elo(fighter_b_id, fighter_b, division)

    skill_item_a = get_skill_score_by_id(fighter_a_id, division) or {}
    skill_item_b = get_skill_score_by_id(fighter_b_id, division) or {}
    skill_a: Dict[str, float] = skill_item_a.get("skill_score", {})
    skill_b: Dict[str, float] = skill_item_b.get("skill_score", {})

    # Same blended probability as build_prediction
    prob_elo_a = elo_win_probability(elo_a, elo_b)
    comp_a = _skill_composite(skill_a)
    comp_b = _skill_composite(skill_b)
    skill_diff = (comp_a - comp_b) / 100.0
    prob_a = max(0.05, min(0.95, prob_elo_a + skill_diff * 0.10))

    rng = _random.Random(seed)
    a_wins = 0
    b_wins = 0
    method_counts: Dict[str, Dict[str, int]] = {
        "fighter_a": {"KO/TKO": 0, "SUB": 0, "DEC": 0},
        "fighter_b": {"KO/TKO": 0, "SUB": 0, "DEC": 0},
    }
    round_counts: Dict[str, Dict[str, int]] = {
        "KO/TKO": {str(r): 0 for r in range(1, rounds + 1)},
        "SUB": {str(r): 0 for r in range(1, rounds + 1)},
    }

    for _ in range(n):
        if rng.random() < prob_a:
            winner_key = "fighter_a"
            winner_skill = skill_a
            a_wins += 1
        else:
            winner_key = "fighter_b"
            winner_skill = skill_b
            b_wins += 1

        method = _sim_method(winner_skill, rng)
        method_counts[winner_key][method] += 1
        if method in ("KO/TKO", "SUB"):
            round_counts[method][str(_sim_round(method, winner_skill, rounds, rng))] += 1

    # Normalize to percentages
    method_breakdown: Dict[str, Dict[str, float]] = {}
    for key, counts in method_counts.items():
        total = sum(counts.values())
        method_breakdown[key] = {m: round(c / total, 4) if total else 0.0 for m, c in counts.items()}

    round_distribution: Dict[str, Dict[str, float]] = {}
    for method, counts in round_counts.items():
        total = sum(counts.values())
        if total:
            round_distribution[method] = {r: round(c / total, 4) for r, c in counts.items()}

    # Most likely single outcome
    best_key = "fighter_a" if a_wins >= b_wins else "fighter_b"
    best_fighter = fighter_a if best_key == "fighter_a" else fighter_b
    best_name = best_fighter.get("name") or best_fighter.get("full_name") or ""
    best_method = max(method_counts[best_key], key=method_counts[best_key].get)
    if best_method == "DEC":
        most_likely = f"{best_name} wins by Decision"
    else:
        best_round = max(round_counts[best_method], key=round_counts[best_method].get)
        most_likely = f"{best_name} wins by {best_method} in Round {best_round}"

    name_a = fighter_a.get("name") or fighter_a.get("full_name")
    name_b = fighter_b.get("name") or fighter_b.get("full_name")
    return {
        "fighter_a_id": str(fighter_a_id),
        "fighter_b_id": str(fighter_b_id),
        "fighter_a_name": name_a,
        "fighter_b_name": name_b,
        "simulations": n,
        "rounds": rounds,
        "probability_a": round(prob_a, 4),
        "probability_b": round(1.0 - prob_a, 4),
        "fighter_a_wins": a_wins,
        "fighter_b_wins": b_wins,
        "method_breakdown": method_breakdown,
        "round_distribution": round_distribution,
        "most_likely_outcome": most_likely,
        "skill_comparison": {"fighter_a": skill_a, "fighter_b": skill_b},
    }


def build_upcoming_events(division: str = "heavyweight") -> List[Dict[str, object]]:
    events = get_upcoming_events()
    response = []
    for event in events:
        fights = []
        for fight in event.get("fights", []):
            fight_id = str(fight.get("id") or fight.get("fight_id") or f"{fight.get('fighter_a')}-{fight.get('fighter_b')}")
            fighter_a_id = str(fight.get("fighter_a") or fight.get("fighter_a_id") or fight.get("a_id"))
            fighter_b_id = str(fight.get("fighter_b") or fight.get("fighter_b_id") or fight.get("b_id"))
            prediction = None
            if fighter_a_id and fighter_b_id:
                prediction = build_prediction(fighter_a_id, fighter_b_id, division)
            fights.append(
                {
                    "fight_id": fight_id,
                    "fighter_a_id": fighter_a_id,
                    "fighter_b_id": fighter_b_id,
                    "fighter_a_name": fight.get("fighter_a_name") or fight.get("fighter_a") or "Unknown",
                    "fighter_b_name": fight.get("fighter_b_name") or fight.get("fighter_b") or "Unknown",
                    "scheduled_round": fight.get("round"),
                    "scheduled_time": fight.get("time"),
                    "prediction": prediction,
                }
            )
        response.append(
            {
                "event_id": str(event.get("id") or event.get("event_id") or event.get("name")),
                "name": event.get("name"),
                "date": event.get("parsed_date"),
                "venue": event.get("venue"),
                "fights": fights,
            }
        )
    return response
