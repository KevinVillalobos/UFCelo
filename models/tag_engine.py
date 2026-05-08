"""
Tag engine: computes descriptive tags for UFC fighters based on their fight history,
ELO history, and skill history data.

Public API:
    calculate_tags(fighter_id, division) -> List[str]
    TAG_GROUPS: Dict[str, str]
    TAG_TOOLTIPS: Dict[str, str]
"""
import csv
import json
import math
import statistics
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

DATA_DIR = Path(__file__).parent.parent / "data"

ALL_DIVISIONS = [
    "heavyweight",
    "light heavyweight",
    "middleweight",
    "welterweight",
    "lightweight",
    "featherweight",
    "bantamweight",
    "flyweight",
]

# ── Module-level caches ────────────────────────────────────────────────────────

_elo_cache: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
_csv_cache: Dict[str, Dict[str, Dict[str, Any]]] = {}
_skill_cache: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
_pct_cache: Dict[str, Dict[str, float]] = {}


# ── Tag metadata ───────────────────────────────────────────────────────────────

TAG_GROUPS: Dict[str, str] = {
    "Glass Jaw": "resistance",
    "Stone Fists": "striking",
    "Volume Puncher": "striking",
    "Sniper": "striking",
    "Bomber": "striking",
    "Body Snatcher": "striking",
    "Artistic KO": "striking",
    "No Second Round": "striking",
    "Grappler": "grappling",
    "Wall": "grappling",
    "Submission Artist": "grappling",
    "Octopus": "grappling",
    "Ground Magnet": "grappling",
    "Never Grounded": "grappling",
    "Iron Chin": "resistance",
    "Resilient": "resistance",
    "Survivor": "resistance",
    "Progressive Chin": "resistance",
    "Finisher": "performance",
    "Decision Master": "performance",
    "Controller": "performance",
    "Consistent": "performance",
    "Unpredictable": "performance",
    "KO Specialist": "performance",
    "Sub Specialist": "performance",
    "Decision Specialist": "performance",
    "Explosive": "performance",
    "Marathon Man": "performance",
    "Chameleon": "performance",
    "Undefeated in UFC": "achievement",
    "Giant Slayer": "achievement",
    "Streak Killer": "achievement",
    "Big Fight Performer": "achievement",
    "War Veteran": "achievement",
}

TAG_TOOLTIPS: Dict[str, str] = {
    "Glass Jaw": "Has suffered 2+ KO losses or been knocked down 3+ times in their UFC career.",
    "Stone Fists": "KO rate above 40% with moderate strike volume (below division p40).",
    "Volume Puncher": "High significant strike volume (p70+) but low KO rate (below 30%).",
    "Sniper": "Significant strike accuracy above 60% with moderate volume (below division p50).",
    "Bomber": "Combines high volume (p70+) with high KO rate (above 40%).",
    "Body Snatcher": "More than 30% of significant strikes target the body.",
    "Artistic KO": "More than 50% of KO/TKO victories come in the first round.",
    "No Second Round": "More than 65% of finishes occur in the first round.",
    "Grappler": "High takedown accuracy (45%+), solid takedown defense (70%+), and dominant control time (p60+).",
    "Wall": "Exceptional takedown defense: stuffs more than 85% of opponent attempts.",
    "Submission Artist": "More than 35% of victories are by submission.",
    "Octopus": "Average submission attempts per fight in the top 30% of the division (p70+).",
    "Ground Magnet": "Takedown accuracy above 55% and control time in the division p75+.",
    "Never Grounded": "Takedown defense above 80% and opponent control time is less than 10% of total fight time.",
    "Iron Chin": "Has never been knocked out or knocked down in their UFC career.",
    "Resilient": "Has won at least one fight in which they were knocked down.",
    "Survivor": "Has won at least one fight after facing a knockdown or 2+ submission attempts from the opponent.",
    "Progressive Chin": "No knockdowns in their first 5 UFC fights, but suffered 2+ in their last 5.",
    "Finisher": "More than 70% of victories are by KO/TKO or submission.",
    "Decision Master": "More than 60% of victories are by decision.",
    "Controller": "In victories, dominates control time by occupying more than 55% of fight time.",
    "Consistent": "Standard deviation of composite skill score across last 8 fights is below 5.0.",
    "Unpredictable": "Has significant win rates by KO (20%+), submission (20%+), and decision (20%+), with 5+ wins.",
    "KO Specialist": "More than 80% of victories are by KO/TKO.",
    "Sub Specialist": "More than 80% of victories are by submission.",
    "Decision Specialist": "More than 80% of victories are by decision.",
    "Explosive": "More than 60% of finishes occur in rounds 1 or 2.",
    "Marathon Man": "More than 60% of UFC fights go to a decision.",
    "Chameleon": "Evolved form of Unpredictable: wins by KO (20%+), Sub (20%+), and decision (20%+) across 10+ UFC fights.",
    "Undefeated in UFC": "Has not lost a single fight in the UFC.",
    "Giant Slayer": "Has defeated 2+ opponents who held an ELO advantage of 150+ points at fight time.",
    "Streak Killer": "Has defeated 2+ opponents who were riding a 3+ fight winning streak.",
    "Big Fight Performer": "Title fight win rate exceeds non-title fight win rate by at least 15 percentage points (min 2 title fights).",
    "War Veteran": "Has completed at least 5 UFC fights that reached round 3 or later.",
}


# ── Data loading helpers ───────────────────────────────────────────────────────

def _division_slug(division: str) -> str:
    return division.lower().replace(" ", "_")


def _load_elo_history(division: str) -> Dict[str, List[Dict[str, Any]]]:
    slug = _division_slug(division)
    if slug not in _elo_cache:
        path = DATA_DIR / f"elo_histories_{slug}.json"
        if path.exists():
            with path.open("r", encoding="utf-8") as f:
                _elo_cache[slug] = json.load(f)
        else:
            _elo_cache[slug] = {}
    return _elo_cache[slug]


def _load_csv(division: str) -> Dict[str, Dict[str, Any]]:
    slug = _division_slug(division)
    if slug not in _csv_cache:
        path = DATA_DIR / f"fights_{slug}.csv"
        result: Dict[str, Dict[str, Any]] = {}
        if path.exists():
            with path.open(newline="", encoding="utf-8") as fh:
                for row in csv.DictReader(fh):
                    fid = row.get("fight_id", "")
                    if fid:
                        result[fid] = row
        _csv_cache[slug] = result
    return _csv_cache[slug]


def _load_skill_history(division: str) -> Dict[str, List[Dict[str, Any]]]:
    slug = _division_slug(division)
    if slug not in _skill_cache:
        path = DATA_DIR / f"skill_histories_{slug}.json"
        if path.exists():
            with path.open("r", encoding="utf-8") as f:
                _skill_cache[slug] = json.load(f)
        else:
            _skill_cache[slug] = {}
    return _skill_cache[slug]


def _load_rankings(division: str) -> List[Dict[str, Any]]:
    slug = _division_slug(division)
    path = DATA_DIR / f"rankings_{slug}.json"
    if path.exists():
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    return []


# ── Time parsing helpers ───────────────────────────────────────────────────────

def _ctrl_secs(time_str: Optional[str]) -> int:
    if not time_str:
        return 0
    try:
        parts = time_str.strip().split(":")
        return int(parts[0]) * 60 + int(parts[1])
    except (ValueError, IndexError):
        return 0


def _fight_secs(row: Dict[str, Any]) -> int:
    try:
        rnd = int(row.get("round", 0) or 0)
        method = row.get("method", "")
        time_str = row.get("time", "")
        parts = time_str.strip().split(":")
        time_secs = int(parts[0]) * 60 + int(parts[1])
        if method in ("KO/TKO", "SUB") or method.startswith("OTHER"):
            return (rnd - 1) * 300 + time_secs
        return rnd * 300
    except (ValueError, IndexError, AttributeError):
        return 0


# ── Percentile computation ─────────────────────────────────────────────────────

def _compute_percentiles(division: str) -> Dict[str, float]:
    slug = _division_slug(division)
    if slug in _pct_cache:
        return _pct_cache[slug]

    rankings = _load_rankings(division)
    fighter_ids = {r["fighter_id"] for r in rankings}
    csv_rows = _load_csv(division)

    sig_pm_vals: List[float] = []
    ctrl_pm_vals: List[float] = []
    sub_att_vals: List[float] = []

    for fid in fighter_ids:
        fight_sig_pm: List[float] = []
        fight_ctrl_pm: List[float] = []
        fight_sub_att: List[int] = []

        for row in csv_rows.values():
            a_id = row.get("fighter_a_id", "")
            b_id = row.get("fighter_b_id", "")
            if fid not in (a_id, b_id):
                continue

            prefix = "fighter_a_" if fid == a_id else "fighter_b_"
            fsecs = _fight_secs(row)
            if fsecs <= 0:
                continue
            fmins = fsecs / 60.0

            try:
                head = int(row.get(f"{prefix}head_strikes_landed", 0) or 0)
                body = int(row.get(f"{prefix}body_strikes_landed", 0) or 0)
                leg = int(row.get(f"{prefix}leg_strikes_landed", 0) or 0)
                sig_landed = head + body + leg
                fight_sig_pm.append(sig_landed / fmins)
            except (ValueError, ZeroDivisionError):
                pass

            ctrl = _ctrl_secs(row.get(f"{prefix}control_time"))
            fight_ctrl_pm.append(ctrl / fmins)

            try:
                sub_att = int(row.get(f"{prefix}submission_attempts", 0) or 0)
                fight_sub_att.append(sub_att)
            except ValueError:
                pass

        if fight_sig_pm:
            sig_pm_vals.append(sum(fight_sig_pm) / len(fight_sig_pm))
        if fight_ctrl_pm:
            ctrl_pm_vals.append(sum(fight_ctrl_pm) / len(fight_ctrl_pm))
        if fight_sub_att:
            sub_att_vals.append(sum(fight_sub_att) / len(fight_sub_att))

    def percentile(data: List[float], p: float) -> float:
        if not data:
            return 0.0
        sorted_data = sorted(data)
        idx = (p / 100.0) * (len(sorted_data) - 1)
        lo, hi = int(idx), min(int(idx) + 1, len(sorted_data) - 1)
        return sorted_data[lo] + (sorted_data[hi] - sorted_data[lo]) * (idx - lo)

    result = {
        "sig_pm_p40": percentile(sig_pm_vals, 40),
        "sig_pm_p50": percentile(sig_pm_vals, 50),
        "sig_pm_p70": percentile(sig_pm_vals, 70),
        "ctrl_pm_p60": percentile(ctrl_pm_vals, 60),
        "ctrl_pm_p75": percentile(ctrl_pm_vals, 75),
        "sub_att_p70": percentile(sub_att_vals, 70),
    }
    _pct_cache[slug] = result
    return result


# ── Fighter stats aggregation ──────────────────────────────────────────────────

def _collect_fighter_stats(
    fighter_id: str,
    division: str,
) -> Dict[str, Any]:
    """Aggregate all fight statistics for a fighter, deduplicating across divisions."""
    elo_hist = _load_elo_history(division).get(fighter_id, [])
    csv_rows = _load_csv(division)

    seen_fight_ids: Set[str] = set()

    ufc_fights = 0
    ufc_wins = 0
    ufc_losses = 0

    ko_wins = 0
    sub_wins = 0
    dec_wins = 0
    ko_losses = 0
    kd_received = 0

    title_wins = 0
    title_losses = 0
    title_fights = 0

    sig_landed_total = 0
    sig_attempted_total = 0
    body_attempted_total = 0

    td_landed_total = 0
    td_attempted_total = 0
    opp_td_landed_total = 0
    opp_td_attempted_total = 0

    ctrl_secs_list_wins: List[float] = []
    fight_secs_list_wins: List[float] = []
    opp_ctrl_secs_total = 0
    total_fight_secs_sum = 0

    sub_att_per_fight: List[int] = []
    ctrl_pm_per_fight: List[float] = []
    sig_pm_per_fight: List[float] = []
    sig_acc_num = 0
    sig_acc_den = 0

    r1_ko_wins = 0
    r1r2_finish_wins = 0
    r1_finish_wins = 0
    total_finish_wins = 0

    fights_r3plus = 0
    fights_to_decision = 0

    resilient_wins = 0
    sobreviviente_wins = 0

    fight_dates_ordered: List[tuple] = []

    for point in elo_hist:
        fid = point.get("fight_id", "")
        if not fid or fid in seen_fight_ids:
            continue
        if fid not in csv_rows:
            continue
        seen_fight_ids.add(fid)

        row = csv_rows[fid]
        result = point.get("result", "")
        method = point.get("method", "")
        rnd = int(row.get("round", 0) or 0)
        is_title = point.get("is_title_fight", False)
        date = point.get("date", "")

        a_id = row.get("fighter_a_id", "")
        prefix = "fighter_a_" if fighter_id == a_id else "fighter_b_"
        opp_prefix = "fighter_b_" if fighter_id == a_id else "fighter_a_"

        fsecs = _fight_secs(row)
        fmins = fsecs / 60.0 if fsecs > 0 else 1.0

        try:
            head_l = int(row.get(f"{prefix}head_strikes_landed", 0) or 0)
            head_a = int(row.get(f"{prefix}head_strikes_attempted", 0) or 0)
            body_l = int(row.get(f"{prefix}body_strikes_landed", 0) or 0)
            body_a = int(row.get(f"{prefix}body_strikes_attempted", 0) or 0)
            leg_l = int(row.get(f"{prefix}leg_strikes_landed", 0) or 0)
            leg_a = int(row.get(f"{prefix}leg_strikes_attempted", 0) or 0)
        except ValueError:
            head_l = head_a = body_l = body_a = leg_l = leg_a = 0

        sig_l = head_l + body_l + leg_l
        sig_a = head_a + body_a + leg_a

        try:
            td_l = int(row.get(f"{prefix}takedowns_landed", 0) or 0)
            td_a = int(row.get(f"{prefix}takedowns_attempted", 0) or 0)
            opp_td_l = int(row.get(f"{opp_prefix}takedowns_landed", 0) or 0)
            opp_td_a = int(row.get(f"{opp_prefix}takedowns_attempted", 0) or 0)
        except ValueError:
            td_l = td_a = opp_td_l = opp_td_a = 0

        ctrl_raw = _ctrl_secs(row.get(f"{prefix}control_time"))
        opp_ctrl_raw = _ctrl_secs(row.get(f"{opp_prefix}control_time"))

        try:
            opp_kd = int(row.get(f"{opp_prefix}knockdowns", 0) or 0)
        except ValueError:
            opp_kd = 0

        try:
            sub_att = int(row.get(f"{prefix}submission_attempts", 0) or 0)
            opp_sub_att = int(row.get(f"{opp_prefix}submission_attempts", 0) or 0)
        except ValueError:
            sub_att = opp_sub_att = 0

        ufc_fights += 1
        fight_dates_ordered.append((date, fid))

        sig_landed_total += sig_l
        sig_attempted_total += sig_a
        sig_acc_num += sig_l
        sig_acc_den += sig_a
        body_attempted_total += body_a

        td_landed_total += td_l
        td_attempted_total += td_a
        opp_td_landed_total += opp_td_l
        opp_td_attempted_total += opp_td_a

        opp_ctrl_secs_total += opp_ctrl_raw
        total_fight_secs_sum += fsecs

        sub_att_per_fight.append(sub_att)
        if fmins > 0:
            ctrl_pm_per_fight.append(ctrl_raw / fmins)
            sig_pm_per_fight.append(sig_l / fmins)

        kd_received += opp_kd

        if is_title:
            title_fights += 1

        if result == "Win":
            ufc_wins += 1
            if is_title:
                title_wins += 1

            if method == "KO/TKO":
                ko_wins += 1
                total_finish_wins += 1
                if rnd == 1:
                    r1_ko_wins += 1
                    r1_finish_wins += 1
                    r1r2_finish_wins += 1
                elif rnd == 2:
                    r1r2_finish_wins += 1
            elif method == "SUB":
                sub_wins += 1
                total_finish_wins += 1
                if rnd == 1:
                    r1_finish_wins += 1
                    r1r2_finish_wins += 1
                elif rnd == 2:
                    r1r2_finish_wins += 1
            elif method in ("DEC U", "DEC S", "DEC M"):
                dec_wins += 1
                fights_to_decision += 1

            if opp_kd > 0:
                resilient_wins += 1
            if opp_kd > 0 or opp_sub_att >= 2:
                sobreviviente_wins += 1

            ctrl_secs_list_wins.append(ctrl_raw)
            fight_secs_list_wins.append(float(fsecs) if fsecs > 0 else 1.0)

        elif result == "Loss":
            ufc_losses += 1
            if is_title:
                title_losses += 1
            if method == "KO/TKO":
                ko_losses += 1
            if method in ("DEC U", "DEC S", "DEC M"):
                fights_to_decision += 1

        if rnd >= 3:
            fights_r3plus += 1

    # Compute kd_received in first 5 and last 5 ordered fights
    fight_dates_ordered.sort(key=lambda x: x[0])
    ordered_fids = [x[1] for x in fight_dates_ordered]

    first5_fids = set(ordered_fids[:5])
    last5_fids = set(ordered_fids[-5:]) if len(ordered_fids) >= 5 else set()

    kd_first5 = 0
    kd_last5 = 0
    for point in elo_hist:
        fid = point.get("fight_id", "")
        if fid not in csv_rows:
            continue
        row = csv_rows[fid]
        a_id = row.get("fighter_a_id", "")
        opp_prefix = "fighter_b_" if fighter_id == a_id else "fighter_a_"
        try:
            opp_kd = int(row.get(f"{opp_prefix}knockdowns", 0) or 0)
        except ValueError:
            opp_kd = 0
        if fid in first5_fids:
            kd_first5 += opp_kd
        if fid in last5_fids:
            kd_last5 += opp_kd

    avg_sig_pm = (sum(sig_pm_per_fight) / len(sig_pm_per_fight)) if sig_pm_per_fight else 0.0
    avg_ctrl_pm = (sum(ctrl_pm_per_fight) / len(ctrl_pm_per_fight)) if ctrl_pm_per_fight else 0.0
    avg_sub_att_per_fight = (sum(sub_att_per_fight) / len(sub_att_per_fight)) if sub_att_per_fight else 0.0

    sig_accuracy = sig_acc_num / max(sig_acc_den, 1)
    td_acc = td_landed_total / max(td_attempted_total, 1)
    td_def = 1.0 - (opp_td_landed_total / max(opp_td_attempted_total, 1))

    ctrl_ratio_wins = 0.0
    if ctrl_secs_list_wins and fight_secs_list_wins:
        ratios = [c / max(f, 1) for c, f in zip(ctrl_secs_list_wins, fight_secs_list_wins)]
        ctrl_ratio_wins = sum(ratios) / len(ratios)

    return {
        "ufc_fights": ufc_fights,
        "ufc_wins": ufc_wins,
        "ufc_losses": ufc_losses,
        "total_wins": ufc_wins,
        "ko_wins": ko_wins,
        "sub_wins": sub_wins,
        "dec_wins": dec_wins,
        "ko_losses": ko_losses,
        "kd_received": kd_received,
        "kd_received_first5": kd_first5,
        "kd_received_last5": kd_last5,
        "title_wins": title_wins,
        "title_losses": title_losses,
        "title_fights": title_fights,
        "sig_accuracy": sig_accuracy,
        "avg_sig_pm": avg_sig_pm,
        "td_acc": td_acc,
        "td_def": td_def,
        "avg_ctrl_pm": avg_ctrl_pm,
        "avg_sub_att_per_fight": avg_sub_att_per_fight,
        "ctrl_ratio_wins": ctrl_ratio_wins,
        "body_attempted_total": body_attempted_total,
        "sig_attempted_total": sig_attempted_total,
        "total_fight_secs": total_fight_secs_sum,
        "opp_ctrl_secs_total": opp_ctrl_secs_total,
        "total_finish_wins": total_finish_wins,
        "r1_ko_wins": r1_ko_wins,
        "r1_finish_wins": r1_finish_wins,
        "r1r2_finish_wins": r1r2_finish_wins,
        "fights_r3plus": fights_r3plus,
        "fights_to_decision": fights_to_decision,
        "resilient_wins": resilient_wins,
        "sobreviviente_wins": sobreviviente_wins,
        "seen_fight_ids": seen_fight_ids,
    }


def _compute_skill_stdev(fighter_id: str, division: str) -> Optional[float]:
    skill_hist = _load_skill_history(division).get(fighter_id, [])
    if not skill_hist:
        return None

    _COMPOSITE_WEIGHTS = {
        "Striking": 0.20, "Grappling": 0.15, "Defensa": 0.20,
        "Consistencia": 0.15, "Finish Rate": 0.10,
        "Cardio/Durabilidad": 0.10, "Presión": 0.10,
    }

    last8 = skill_hist[-8:]
    composites = []
    for point in last8:
        ss = point.get("skill_score", {})
        c = sum(ss.get(d, 0) * w for d, w in _COMPOSITE_WEIGHTS.items())
        composites.append(c)

    if len(composites) < 2:
        return None
    return statistics.stdev(composites)


# ── Achievement tag helpers ────────────────────────────────────────────────────

def _compute_giant_slayer(fighter_id: str, division: str) -> int:
    elo_hist = _load_elo_history(division).get(fighter_id, [])
    count = 0
    for point in elo_hist:
        if point.get("result") != "Win":
            continue
        bd = point.get("breakdown", {})
        expected_prob = bd.get("expected_prob")
        if expected_prob is None:
            continue
        try:
            ep = float(expected_prob)
            if ep <= 0 or ep >= 1:
                continue
            elo_diff = 400.0 * math.log10(1.0 / ep - 1.0)
            if elo_diff > 150:
                count += 1
        except (ValueError, ZeroDivisionError):
            continue
    return count


def _get_opponent_history_before(opponent_id: str, date_str: str) -> List[Dict[str, Any]]:
    """Collect all ELO history points for an opponent across all divisions before date_str."""
    all_points: List[Dict[str, Any]] = []
    for div in ALL_DIVISIONS:
        hist = _load_elo_history(div).get(opponent_id, [])
        for point in hist:
            if point.get("date", "") < date_str:
                all_points.append(point)
    all_points.sort(key=lambda x: x.get("date", ""))
    return all_points


def _opponent_had_win_streak(opponent_id: str, fight_date: str, min_streak: int = 3) -> bool:
    points = _get_opponent_history_before(opponent_id, fight_date)
    if not points:
        return False
    streak = 0
    for point in points:
        if point.get("result") == "Win":
            streak += 1
        else:
            streak = 0
    return streak >= min_streak


def _compute_streak_killer(fighter_id: str, division: str) -> int:
    elo_hist = _load_elo_history(division).get(fighter_id, [])
    count = 0
    for point in elo_hist:
        if point.get("result") != "Win":
            continue
        opp_id = point.get("opponent_id", "")
        date_str = point.get("date", "")
        if opp_id and date_str:
            if _opponent_had_win_streak(opp_id, date_str, min_streak=3):
                count += 1
    return count


# ── Main tag calculation ───────────────────────────────────────────────────────

def calculate_tags(fighter_id: str, division: str) -> List[str]:
    """Return sorted list of tag strings for a fighter."""
    pct = _compute_percentiles(division)
    stats = _collect_fighter_stats(fighter_id, division)

    ufc_fights = stats["ufc_fights"]
    total_wins = stats["total_wins"]
    ko_wins = stats["ko_wins"]
    sub_wins = stats["sub_wins"]
    dec_wins = stats["dec_wins"]
    ko_losses = stats["ko_losses"]
    kd_received = stats["kd_received"]
    ufc_losses = stats["ufc_losses"]

    tags: Set[str] = set()
    min5 = ufc_fights >= 5
    min3 = ufc_fights >= 3

    # ── Striking ──────────────────────────────────────────────────────────────

    if min5:
        ko_rate = ko_wins / total_wins if total_wins > 0 else 0.0

        if ko_losses >= 2 or kd_received >= 3:
            tags.add("Glass Jaw")

        if ko_rate > 0.40 and stats["avg_sig_pm"] < pct["sig_pm_p40"]:
            tags.add("Stone Fists")

        if stats["avg_sig_pm"] > pct["sig_pm_p70"] and ko_rate < 0.30:
            tags.add("Volume Puncher")

        if stats["sig_accuracy"] > 0.60 and stats["avg_sig_pm"] < pct["sig_pm_p50"]:
            tags.add("Sniper")

        if stats["avg_sig_pm"] > pct["sig_pm_p70"] and ko_rate > 0.40:
            tags.add("Bomber")

        if stats["sig_attempted_total"] > 0:
            body_ratio = stats["body_attempted_total"] / stats["sig_attempted_total"]
            if body_ratio > 0.30:
                tags.add("Body Snatcher")

        if ko_wins > 0 and stats["r1_ko_wins"] / ko_wins > 0.50:
            tags.add("Artistic KO")

    if min3:
        if total_wins > 0 and stats["total_finish_wins"] > 0:
            if stats["r1_finish_wins"] / stats["total_finish_wins"] > 0.65:
                tags.add("No Second Round")

    # ── Grappling ─────────────────────────────────────────────────────────────

    if min5:
        td_acc = stats["td_acc"]
        td_def = stats["td_def"]
        avg_ctrl_pm = stats["avg_ctrl_pm"]

        grappler = (
            td_acc > 0.45
            and td_def > 0.70
            and avg_ctrl_pm > pct["ctrl_pm_p60"]
        )
        if grappler:
            tags.add("Grappler")

        if td_def > 0.85 and "Grappler" not in tags:
            tags.add("Wall")

        if total_wins > 0 and sub_wins / total_wins > 0.35:
            tags.add("Submission Artist")

        if stats["avg_sub_att_per_fight"] > pct["sub_att_p70"]:
            tags.add("Octopus")

        if td_acc > 0.55 and avg_ctrl_pm > pct["ctrl_pm_p75"]:
            tags.add("Ground Magnet")

        total_fsecs = stats["total_fight_secs"]
        opp_ctrl = stats["opp_ctrl_secs_total"]
        opp_ctrl_ratio = opp_ctrl / total_fsecs if total_fsecs > 0 else 1.0
        if td_def > 0.80 and opp_ctrl_ratio < 0.10:
            tags.add("Never Grounded")

    # ── Resistance ────────────────────────────────────────────────────────────

    if min5:
        if ko_losses == 0 and kd_received == 0:
            tags.add("Iron Chin")

        if stats["kd_received_first5"] == 0 and stats["kd_received_last5"] >= 2:
            tags.add("Progressive Chin")

    if min3:
        if stats["resilient_wins"] >= 1:
            tags.add("Resilient")

        if stats["sobreviviente_wins"] >= 1:
            tags.add("Survivor")

    # ── Performance ───────────────────────────────────────────────────────────

    if min5:
        finish_rate = (ko_wins + sub_wins) / total_wins if total_wins > 0 else 0.0
        dec_rate_w = dec_wins / total_wins if total_wins > 0 else 0.0

        if finish_rate > 0.70:
            tags.add("Finisher")
        elif dec_rate_w > 0.60:
            tags.add("Decision Master")

        if stats["ctrl_ratio_wins"] > 0.55:
            tags.add("Controller")

        stdev = _compute_skill_stdev(fighter_id, division)
        if stdev is not None and stdev < 5.0:
            tags.add("Consistent")

        ko_rate_t = ko_wins / total_wins if total_wins > 0 else 0.0
        sub_rate_t = sub_wins / total_wins if total_wins > 0 else 0.0
        dec_rate_t = dec_wins / total_wins if total_wins > 0 else 0.0

        is_unpredictable = (
            ko_rate_t >= 0.20
            and sub_rate_t >= 0.20
            and dec_rate_t >= 0.20
            and total_wins >= 5
        )
        is_chameleon = is_unpredictable and ufc_fights >= 10

        if is_chameleon:
            tags.add("Chameleon")
        elif is_unpredictable:
            tags.add("Unpredictable")
        else:
            for tag_name, method_wins in [
                ("KO Specialist", ko_wins),
                ("Sub Specialist", sub_wins),
                ("Decision Specialist", dec_wins),
            ]:
                if total_wins > 0 and method_wins / total_wins > 0.80:
                    tags.add(tag_name)

        if stats["total_finish_wins"] > 0:
            if stats["r1r2_finish_wins"] / stats["total_finish_wins"] > 0.60:
                tags.add("Explosive")

        if ufc_fights > 0 and stats["fights_to_decision"] / ufc_fights > 0.60:
            tags.add("Marathon Man")

    # ── Achievement ───────────────────────────────────────────────────────────

    if min3:
        if ufc_losses == 0:
            tags.add("Undefeated in UFC")

    if min5:
        if _compute_giant_slayer(fighter_id, division) >= 2:
            tags.add("Giant Slayer")

        if _compute_streak_killer(fighter_id, division) >= 2:
            tags.add("Streak Killer")

        title_fights = stats["title_fights"]
        title_wins_count = stats["title_wins"]
        non_title_fights = ufc_fights - title_fights
        non_title_wins = total_wins - title_wins_count
        if title_fights >= 2:
            title_win_rate = title_wins_count / title_fights
            non_title_win_rate = non_title_wins / non_title_fights if non_title_fights > 0 else 0.0
            if title_win_rate - non_title_win_rate >= 0.15:
                tags.add("Big Fight Performer")

        if stats["fights_r3plus"] >= 5:
            tags.add("War Veteran")

    # ── Exclusions ────────────────────────────────────────────────────────────

    if "Iron Chin" in tags:
        tags.discard("Glass Jaw")
        tags.discard("Progressive Chin")

    if "Glass Jaw" in tags:
        tags.discard("Progressive Chin")

    if "Finisher" in tags:
        tags.discard("Decision Master")

    if "Grappler" in tags:
        tags.discard("Wall")

    if "Chameleon" in tags:
        tags.discard("Unpredictable")

    if "Unpredictable" in tags or "Chameleon" in tags:
        tags.discard("KO Specialist")
        tags.discard("Sub Specialist")
        tags.discard("Decision Specialist")

    return sorted(tags)
