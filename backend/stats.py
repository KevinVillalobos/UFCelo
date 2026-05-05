import csv
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

_ALL_SLUGS = [
    "heavyweight", "light_heavyweight", "middleweight", "welterweight",
    "lightweight", "featherweight", "bantamweight", "flyweight",
]


def _time_to_min(time_str: str, round_num: int) -> float:
    try:
        parts = str(time_str).strip().split(":")
        m, s = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
        return (round_num - 1) * 5.0 + m + s / 60.0
    except Exception:
        return round_num * 5.0


def _ctrl_to_min(ctrl: str) -> float:
    try:
        parts = str(ctrl).strip().split(":")
        return int(parts[0]) + int(parts[1]) / 60.0
    except Exception:
        return 0.0


def _safe_int(v) -> int:
    try:
        return int(v)
    except Exception:
        return 0


def _method_bucket(method: str) -> str:
    m = method.strip().upper()
    if "KO" in m or "TKO" in m:
        return "KO/TKO"
    if "SUB" in m:
        return "SUB"
    return "DEC"


def parse_physical(fighter: Dict) -> Dict:
    h = str(fighter.get("height") or "")
    r = str(fighter.get("reach") or "")
    w = str(fighter.get("weight") or "")

    height_in: Optional[int] = None
    m = re.match(r"(\d+)'\s*(\d+)", h)
    if m:
        height_in = int(m.group(1)) * 12 + int(m.group(2))

    reach_in: Optional[float] = None
    cleaned = r.replace('"', "").strip()
    m2 = re.match(r"(\d+\.?\d*)", cleaned)
    if m2:
        v = float(m2.group(1))
        if v > 0:
            reach_in = v

    weight_lbs: Optional[int] = None
    m3 = re.match(r"(\d+)", w)
    if m3:
        weight_lbs = int(m3.group(1))

    return {
        "height_inches": height_in,
        "reach_inches": reach_in,
        "weight_lbs": weight_lbs,
        "stance": fighter.get("stance"),
    }


def compute_fighter_stats(fighter_id: str, division: str = "") -> Optional[Dict]:
    # Collect fights from every division CSV so cross-division fighters (e.g. a
    # champion who moved up) show their full career stats, not just one weight class.
    # Deduplicate by fight_id in case the same fight was scraped into multiple files.
    rows_a: List[Dict] = []
    rows_b: List[Dict] = []
    seen_fights: set = set()

    for slug in _ALL_SLUGS:
        path = DATA_DIR / f"fights_{slug}.csv"
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                fid = row.get("fight_id", "")
                if fid in seen_fights:
                    continue
                if row.get("fighter_a_id") == fighter_id:
                    rows_a.append(row)
                    seen_fights.add(fid)
                elif row.get("fighter_b_id") == fighter_id:
                    rows_b.append(row)
                    seen_fights.add(fid)

    if not rows_a and not rows_b:
        return None

    total_time = 0.0
    sl = sa = td_l = td_a = kd = sub = head = body = leg = 0
    ctrl = 0.0
    o_sl = o_sa = o_td_l = o_td_a = 0
    wins: Dict[str, int] = {"KO/TKO": 0, "SUB": 0, "DEC": 0}
    losses: Dict[str, int] = {"KO/TKO": 0, "SUB": 0, "DEC": 0}
    ko_rounds: List[int] = []
    sub_rounds: List[int] = []
    timeline: List[Dict] = []

    def _process(row: Dict, mp: str, op: str) -> None:
        nonlocal total_time, sl, sa, td_l, td_a, kd, sub, head, body, leg
        nonlocal ctrl, o_sl, o_sa, o_td_l, o_td_a

        rnd = max(_safe_int(row.get("round", 1)), 1)
        t = _time_to_min(row.get("time", "5:00"), rnd)
        if t <= 0:
            t = rnd * 5.0
        total_time += t

        my_sl  = _safe_int(row.get(f"{mp}_strikes_landed"))
        my_sa  = _safe_int(row.get(f"{mp}_strikes_attempted"))
        my_tdl = _safe_int(row.get(f"{mp}_takedowns_landed"))
        my_tda = _safe_int(row.get(f"{mp}_takedowns_attempted"))
        my_kd  = _safe_int(row.get(f"{mp}_knockdowns"))
        my_ctrl = row.get(f"{mp}_control_time", "0:00")
        my_sub = _safe_int(row.get(f"{mp}_submission_attempts"))
        my_h   = _safe_int(row.get(f"{mp}_head_strikes_landed"))
        my_b   = _safe_int(row.get(f"{mp}_body_strikes_landed"))
        my_l   = _safe_int(row.get(f"{mp}_leg_strikes_landed"))

        sl  += my_sl;  sa  += my_sa
        td_l += my_tdl; td_a += my_tda
        kd   += my_kd
        ctrl += _ctrl_to_min(my_ctrl)
        sub  += my_sub
        head += my_h; body += my_b; leg += my_l

        o_sl  += _safe_int(row.get(f"{op}_strikes_landed"))
        o_sa  += _safe_int(row.get(f"{op}_strikes_attempted"))
        o_td_l += _safe_int(row.get(f"{op}_takedowns_landed"))
        o_td_a += _safe_int(row.get(f"{op}_takedowns_attempted"))

        bucket = _method_bucket(row.get("method", ""))
        won = row.get("winner_id") == fighter_id
        if won:
            wins[bucket] += 1
            if bucket == "KO/TKO":
                ko_rounds.append(rnd)
            elif bucket == "SUB":
                sub_rounds.append(rnd)
        else:
            losses[bucket] += 1

        try:
            date_str = datetime.strptime(
                row.get("event_date", ""), "%B %d, %Y"
            ).strftime("%Y-%m-%d")
        except Exception:
            date_str = ""

        timeline.append({
            "date": date_str,
            "sig_strikes_per_min": round(my_sl / t, 2) if t > 0 else 0,
            "td_per_min": round(my_tdl / t, 3) if t > 0 else 0,
            "result": "Win" if won else "Loss",
            "method": _method_bucket(row.get("method", "")),
        })

    for row in rows_a:
        _process(row, "fighter_a", "fighter_b")
    for row in rows_b:
        _process(row, "fighter_b", "fighter_a")

    n = len(rows_a) + len(rows_b)
    if n == 0 or total_time < 0.1:
        return None

    total_str = max(head + body + leg, 1)

    timeline.sort(key=lambda x: x["date"])

    return {
        "total_fights": n,
        # striking
        "sig_strikes_per_min": round(sl / total_time, 2),
        "strike_accuracy":     round(sl  / max(sa,     1), 3),
        "strike_defense":      round(1 - o_sl  / max(o_sa,    1), 3),
        "knockdowns_per_fight": round(kd / n, 2),
        "head_pct": round(head / total_str, 3),
        "body_pct": round(body / total_str, 3),
        "leg_pct":  round(leg  / total_str, 3),
        # grappling
        "td_per_min":             round(td_l / total_time, 3),
        "td_accuracy":            round(td_l  / max(td_a,    1), 3),
        "td_defense":             round(1 - o_td_l / max(o_td_a, 1), 3),
        "ctrl_pct":               round(ctrl / total_time, 3),
        "sub_attempts_per_fight": round(sub / n, 2),
        # methods
        "wins":   wins,
        "losses": losses,
        "avg_finish_round_ko":  round(sum(ko_rounds)  / len(ko_rounds),  1) if ko_rounds  else None,
        "avg_finish_round_sub": round(sum(sub_rounds) / len(sub_rounds), 1) if sub_rounds else None,
        # timeline for career trend (last 20 fights)
        "timeline": timeline[-20:],
    }
