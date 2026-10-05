"""Backtest of the Style Clash adjustment on historical fights.

For every past fight the state BEFORE the fight is rebuilt from earlier information only:
  * ELO: the fighter's effective rating (initial + earlier ELO changes weighted by Legacy Decay),
  * skills: the skill-score state after their previous fight (neutral 50s for a debut).
The win probability comes from backend.services._compute_blended_probability, i.e. the exact function
the site uses, with and without the style adjustment.

Fights are split chronologically: the first (1 - holdout) share is the tuning set, the last share is
the holdout. The holdout is only read to report results; nothing is tuned here.

Run from the project root:
    python -m models.backtest_style_clash
    python -m models.backtest_style_clash --baseline-path ../EloSys_backup_data_pre_q
    python -m models.backtest_style_clash --params data/style_params.json

Known limitation: the fight CSVs do not record card position, so historically the 5-round (cardio) rule
only fires for title fights; live predictions also use the main-event flag from ufc.com.
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.services import STYLE_DEFAULTS, _compute_blended_probability  # noqa: E402
from models.elo_engine import _DIVISIONS_ALL, compute_legacy_decay, load_all_fights  # noqa: E402

SKILL_DIMS = ["Striking", "Grappling", "Defensa", "Consistencia", "Finish Rate", "Cardio/Durabilidad", "Presión"]
NEUTRAL = {dim: 50.0 for dim in SKILL_DIMS}

MAX_DIVISION_DROP = -1.5     # pp, per division in the holdout
MIN_OVERALL_GAIN = 0.5       # pp, overall in the holdout
MIN_ACTIVATION = 0.10        # warn below this share of fights with a non-zero style adjustment
MAX_COFIRE = 0.30            # rules 1 and 2 firing together: above this share, soften rule 2


def _day(text: str):
    return datetime.strptime(text, "%Y-%m-%d").date()


def _careers(data_dir: Path, prefix: str) -> Dict[str, List[dict]]:
    """fighter_id -> all their history points across divisions, deduped, oldest first."""
    careers: Dict[str, List[dict]] = {}
    seen = set()
    for division in _DIVISIONS_ALL:
        path = data_dir / f"{prefix}_{division.replace(' ', '_')}.json"
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8") as handle:
            for fighter_id, hist in json.load(handle).items():
                for point in hist:
                    key = (fighter_id, point.get("fight_id"))
                    if key in seen or not point.get("fight_id"):
                        continue
                    seen.add(key)
                    careers.setdefault(fighter_id, []).append(point)
    for hist in careers.values():
        hist.sort(key=lambda point: point["date"])
    return careers


def load_rows(data_dir: Path) -> List[dict]:
    """One row per decided fight with both fighters' pre-fight state, chronologically."""
    elo_careers = _careers(data_dir, "elo_histories")
    skill_careers = _careers(data_dir, "skill_histories")

    pre_elo: Dict[tuple, tuple] = {}     # (fighter, fight) -> (rating, fights before)
    for fighter_id, hist in elo_careers.items():
        start = (hist[0].get("breakdown") or {}).get("elo_before")
        if start is None:
            continue
        days = [_day(point["date"]) for point in hist]
        for i, point in enumerate(hist):
            total = float(start)
            for j in range(i):
                delta = (hist[j].get("breakdown") or {}).get("delta")
                if delta is None:
                    total = None
                    break
                total += float(delta) * compute_legacy_decay(days[j], days[i])
            if total is not None:
                pre_elo[(fighter_id, point["fight_id"])] = (total, i)

    pre_skill: Dict[tuple, Dict[str, float]] = {}
    for fighter_id, hist in skill_careers.items():
        for i, point in enumerate(hist):
            pre_skill[(fighter_id, point["fight_id"])] = hist[i - 1]["skill_score"] if i else NEUTRAL

    rows = []
    for fight in load_all_fights(data_dir):
        if fight.winner_id not in (fight.fighter_a_id, fight.fighter_b_id):
            continue
        key_a = (fight.fighter_a_id, fight.fight_id)
        key_b = (fight.fighter_b_id, fight.fight_id)
        if key_a not in pre_elo or key_b not in pre_elo:
            continue
        rows.append({
            "date": fight.event_date.strftime("%Y-%m-%d"),
            "division": fight.division,
            "y": 1 if fight.winner_id == fight.fighter_a_id else 0,
            "elo_a": pre_elo[key_a][0],
            "elo_b": pre_elo[key_b][0],
            "n_a": pre_elo[key_a][1],
            "n_b": pre_elo[key_b][1],
            "skill_a": pre_skill.get(key_a, NEUTRAL),
            "skill_b": pre_skill.get(key_b, NEUTRAL),
            "title": bool(fight.is_title_fight),
        })
    rows.sort(key=lambda row: row["date"])
    return rows


def split_rows(rows: List[dict], holdout: float):
    cut = int(len(rows) * (1.0 - holdout))
    return rows[:cut], rows[cut:]


def predict(rows: List[dict], apply_style: bool, params: Optional[dict] = None) -> List[dict]:
    return [
        _compute_blended_probability(
            r["elo_a"], r["elo_b"], r["skill_a"], r["skill_b"],
            is_title_fight=r["title"], apply_style=apply_style, style_params=params)
        for r in rows
    ]


def summarize(rows: List[dict], base: List[dict], style: List[dict]) -> dict:
    n = len(rows)
    if not n:
        return {"n": 0}
    ys = [r["y"] for r in rows]
    pb = [b["prob_a"] for b in base]
    ps = [s["prob_a"] for s in style]

    def acc(probs, idx=None):
        idx = range(n) if idx is None else idx
        idx = list(idx)
        return 100.0 * sum((probs[i] > 0.5) == bool(ys[i]) for i in idx) / len(idx) if idx else float("nan")

    def brier(probs):
        return sum((probs[i] - ys[i]) ** 2 for i in range(n)) / n

    zone = [i for i in range(n) if 0.45 <= base[i]["prob_elo_a"] <= 0.55]
    gained = sum(1 for i in range(n) if (pb[i] > 0.5) != (ps[i] > 0.5) and (ps[i] > 0.5) == bool(ys[i]))
    lost = sum(1 for i in range(n) if (pb[i] > 0.5) != (ps[i] > 0.5) and (pb[i] > 0.5) == bool(ys[i]))
    fired = sum(1 for s in style if s["style_adjustment"] != 0.0)
    r1 = [any("Grappling" in t for t in s["style_reasons"]) for s in style]
    r2 = [any("Striking" in t for t in s["style_reasons"]) for s in style]
    either = sum(1 for a, b in zip(r1, r2) if a or b)
    both = sum(1 for a, b in zip(r1, r2) if a and b)
    return {
        "n": n,
        "acc_base": acc(pb), "acc_style": acc(ps), "acc_delta": acc(ps) - acc(pb),
        "brier_base": brier(pb), "brier_style": brier(ps),
        "flipped_to_correct": gained, "flipped_to_wrong": lost,
        "zone_n": len(zone),
        "zone_acc_base": acc(pb, zone), "zone_acc_style": acc(ps, zone),
        "activation_rate": fired / n,
        "rules12_both": both, "rules12_either": either,
        "rules12_cofire_of_either": (both / either) if either else 0.0,
        "rules12_cofire_of_all": both / n,
    }


def run(rows: List[dict], holdout: float, params: Optional[dict]) -> dict:
    tuning, hold = split_rows(rows, holdout)
    result = {"all": {}, "tuning": {}, "holdout": {}, "by_division": {}}
    for name, subset in (("all", rows), ("tuning", tuning), ("holdout", hold)):
        base, style = predict(subset, False), predict(subset, True, params)
        result[name] = summarize(subset, base, style)
    for division in _DIVISIONS_ALL:
        entry = {}
        for name, subset in (("tuning", tuning), ("holdout", hold)):
            sub = [r for r in subset if r["division"] == division]
            entry[name] = summarize(sub, predict(sub, False), predict(sub, True, params))
        result["by_division"][division] = entry
    return result


def _fmt(x, nd=1):
    return "—" if x is None or x != x else f"{x:.{nd}f}"


def print_report(res: dict, params: dict) -> None:
    print("\nStyle Clash backtest —", ", ".join(f"{k}={v}" for k, v in params.items()))
    print(f"\n{'':14s}{'n':>6s} {'base':>7s} {'style':>7s} {'delta':>7s}  {'Brier b':>8s} {'Brier s':>8s}  {'to ok':>5s} {'to bad':>6s}  {'zone n':>6s} {'zone b':>7s} {'zone s':>7s}")
    for name in ("tuning", "holdout", "all"):
        s = res[name]
        print(f"{name:14s}{s['n']:6d} {_fmt(s['acc_base']):>7s} {_fmt(s['acc_style']):>7s} {s['acc_delta']:+7.2f}  "
              f"{s['brier_base']:8.4f} {s['brier_style']:8.4f}  {s['flipped_to_correct']:5d} {s['flipped_to_wrong']:6d}  "
              f"{s['zone_n']:6d} {_fmt(s['zone_acc_base']):>7s} {_fmt(s['zone_acc_style']):>7s}")
    print(f"\n{'division':18s}{'tune n':>7s} {'base':>6s} {'style':>6s} {'Δ':>6s}   {'hold n':>6s} {'base':>6s} {'style':>6s} {'Δ':>6s}")
    for division, e in res["by_division"].items():
        t, h = e["tuning"], e["holdout"]
        print(f"{division:18s}{t['n']:7d} {_fmt(t['acc_base']):>6s} {_fmt(t['acc_style']):>6s} {t['acc_delta']:+6.2f}   "
              f"{h['n']:6d} {_fmt(h['acc_base']):>6s} {_fmt(h['acc_style']):>6s} {h['acc_delta']:+6.2f}")


def check(res: dict) -> dict:
    hold = res["holdout"]
    division_deltas = {d: e["holdout"]["acc_delta"] for d, e in res["by_division"].items() if e["holdout"]["n"]}
    worst_div, worst = min(division_deltas.items(), key=lambda kv: kv[1])
    warnings = []
    if res["all"]["activation_rate"] < MIN_ACTIVATION:
        warnings.append(f"Style adjustment fires in only {res['all']['activation_rate']:.1%} of fights (< {MIN_ACTIVATION:.0%}).")
    if res["all"]["rules12_cofire_of_either"] > MAX_COFIRE:
        warnings.append(f"Rules 1 and 2 fire together in {res['all']['rules12_cofire_of_either']:.1%} of the fights where either fires (> {MAX_COFIRE:.0%}): soften rule 2 to +-0.015.")
    return {
        "overall_gain_ok": hold["acc_delta"] >= MIN_OVERALL_GAIN,
        "overall_holdout_delta": hold["acc_delta"],
        "worst_division": worst_div, "worst_division_delta": worst,
        "division_drop_ok": worst >= MAX_DIVISION_DROP,
        "warnings": warnings,
    }


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Backtest the Style Clash adjustment")
    parser.add_argument("--data", default="data", help="data directory (default: data)")
    parser.add_argument("--holdout", type=float, default=0.2, help="chronological holdout share (default 0.2)")
    parser.add_argument("--output", default="data/backtest_style_clash.json")
    parser.add_argument("--baseline-path", default=None,
                        help="external copy of data/ to measure the no-style baseline on (e.g. ../EloSys_backup_data_pre_q)")
    parser.add_argument("--params", default=None, help="JSON file with style parameter overrides")
    args = parser.parse_args()

    params = dict(STYLE_DEFAULTS)
    if args.params:
        params.update(json.loads(Path(args.params).read_text(encoding="utf-8")))

    rows = load_rows(Path(args.data))
    res = run(rows, args.holdout, params)
    print_report(res, params)

    verdict = check(res)
    print(f"\nHoldout overall delta {verdict['overall_holdout_delta']:+.2f} pp "
          f"({'PASS' if verdict['overall_gain_ok'] else 'FAIL'} vs +{MIN_OVERALL_GAIN})  |  "
          f"worst division {verdict['worst_division']} {verdict['worst_division_delta']:+.2f} pp "
          f"({'PASS' if verdict['division_drop_ok'] else 'FAIL'} vs {MAX_DIVISION_DROP})")
    for w in verdict["warnings"]:
        print("WARNING:", w)

    external = None
    if args.baseline_path:
        ext_rows = load_rows(Path(args.baseline_path))
        ext_tuning, ext_hold = split_rows(ext_rows, args.holdout)
        external = {}
        for name, subset in (("tuning", ext_tuning), ("holdout", ext_hold), ("all", ext_rows)):
            ps = [b["prob_a"] for b in predict(subset, False)]
            external[name] = {"n": len(subset),
                              "acc_no_style": 100.0 * sum((p > 0.5) == bool(r["y"]) for p, r in zip(ps, subset)) / len(subset)}
        print("\nBaseline data copy (no style):", {k: f"{v['acc_no_style']:.2f}% on {v['n']}" for k, v in external.items()})

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "generated": datetime.now().isoformat(timespec="seconds"),
        "data": args.data, "holdout_share": args.holdout, "params": params,
        "results": res, "verdict": verdict, "baseline_external": external,
        "note": "Historically the 5-round cardio rule only fires for title fights (card position is not in the CSVs).",
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved {out}")


if __name__ == "__main__":
    main()
