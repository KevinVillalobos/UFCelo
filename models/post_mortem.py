"""Post-event review: what the model would have predicted BEFORE each fight, and why it was right or wrong.

For every decided fight of an event the pre-fight state is rebuilt from earlier information only (same
reconstruction as the Style Clash backtest: effective ELO with Legacy Decay, skill state after the previous
fight) and run through backend.services._compute_blended_probability, i.e. the number the site would have shown.

Per fight it records the favourite, the confidence, hit/miss, the signals that backed the favourite, the signals
that pointed to the eventual winner, and a method check. A factor scorecard over the whole history shows which
signals are actually reliable, so a miss can be judged against how often that signal fails in general.

This is read-only analysis: it never changes model parameters. Tuning stays a manual, backtested decision
(see data/improvement_log.md).

Run from the project root:
    python -m models.post_mortem                  # latest event in the data
    python -m models.post_mortem --event "Allen vs. Duncan"
    python -m models.post_mortem --last 5         # the five most recent events
    python -m models.post_mortem --since 2026-01-01  # backfill every event from a date
    python -m models.post_mortem --new            # every event not logged yet (what run_all uses)
    python -m models.post_mortem --all-events     # backfill every event
Outputs: data/post_mortem.json (machine) and data/post_mortem_log.md (human, newest event first).
"""
import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.services import HEAVY_FAVORITE_PROB, _compute_blended_probability, _predict_method  # noqa: E402
from models.backtest_style_clash import load_rows  # noqa: E402

EDGE = 10.0          # skill-point gap that counts as a real edge on a dimension
LOW_SAMPLE = 3       # UFC fights before this one; below it a fighter's ELO/skills are mostly priors
COIN_FLIP = 0.55     # favourite probability below this = near coin flip
CONF_THRESHOLDS = [0.55, 0.60, 0.65, 0.70]            # "favourite had at least this probability"
CONF_BANDS = [(0.50, 0.55), (0.55, 0.60), (0.60, 0.65), (0.65, 0.70), (0.70, 1.01)]
ELO_BUCKETS = [(0, 25), (25, 75), (75, 150), (150, 10_000)]


def _method_group(method: str) -> str:
    raw = (method or "").upper()
    if "KO" in raw or "TKO" in raw:
        return "KO/TKO"
    if "SUB" in raw:
        return "SUB"
    return "DEC"


def _method_dists(data_dir: Path) -> Dict[str, List[tuple]]:
    """fighter_id -> [(date, method_group)] for their wins, used to rebuild the pre-fight finishing profile."""
    from models.backtest_style_clash import _careers
    wins: Dict[str, List[tuple]] = {}
    for fighter_id, hist in _careers(data_dir, "elo_histories").items():
        wins[fighter_id] = [(p["date"], _method_group(p.get("method")))
                            for p in hist if (p.get("result") or "").lower() == "win"]
    return wins


def _dist_before(wins: List[tuple], date: str) -> Dict[str, float]:
    counts = {"KO/TKO": 0, "SUB": 0, "DEC": 0}
    for d, m in wins:
        if d < date:
            counts[m] += 1
    total = sum(counts.values())
    if not total:
        return {"KO/TKO": 0.33, "SUB": 0.33, "DEC": 0.34}
    return {m: c / total for m, c in counts.items()}


def analyse_fight(row: dict, wins_by_fighter: Dict[str, List[tuple]]) -> dict:
    blend = _compute_blended_probability(
        row["elo_a"], row["elo_b"], row["skill_a"], row["skill_b"], is_title_fight=row["title"])
    prob_a = blend["prob_a"]
    toss_up = abs(prob_a - 0.5) < 1e-9     # the data lists the winner as fighter A, so a tie must not count as a hit
    fav_is_a = prob_a >= 0.5
    side = "a" if fav_is_a else "b"
    other = "b" if fav_is_a else "a"
    fav_prob = prob_a if fav_is_a else 1.0 - prob_a
    fav_won = None if toss_up else (bool(row["y"]) == fav_is_a)

    fav = {"id": row[f"{side}_id"], "name": row[f"{side}_name"]}
    dog = {"id": row[f"{other}_id"], "name": row[f"{other}_name"]}
    winner, loser = (fav, dog) if fav_won else (dog, fav)

    elo_gap = row[f"elo_{side}"] - row[f"elo_{other}"]          # >0: favourite also higher on ELO
    edges = {dim: round(row[f"skill_{side}"].get(dim, 50.0) - row[f"skill_{other}"].get(dim, 50.0), 1)
             for dim in set(row["skill_a"]) | set(row["skill_b"])}

    # Signals from the favourite's point of view.
    for_fav = [f"ELO +{elo_gap:.0f}"] if elo_gap >= 10 else []
    for_dog = [f"ELO {elo_gap:+.0f} (favourite rated lower on ELO; skills carried the pick)"] if elo_gap <= -10 else []
    for dim, edge in sorted(edges.items(), key=lambda kv: -abs(kv[1])):
        if edge >= EDGE:
            for_fav.append(f"{dim} +{edge:g}")
        elif edge <= -EDGE:
            for_dog.append(f"{dim} {edge:g}")
    sample = min(row["n_a"], row["n_b"])
    if sample < LOW_SAMPLE:
        for_dog.append(f"thin sample ({sample} prior UFC fights for one fighter)")

    # Method check.
    fav_wins = wins_by_fighter.get(fav["id"], [])
    fav_skill = row[f"skill_{side}"]
    method_pred = _predict_method(_dist_before(fav_wins, row["date"]), fav_skill)
    method_actual = _method_group(row["method"])

    tags = []
    if fav_prob < COIN_FLIP:
        tags.append("coin-flip")
    if toss_up:
        tags.append("toss-up")
    if fav_prob >= HEAVY_FAVORITE_PROB:
        tags.append("heavy-favourite")
    if sample < LOW_SAMPLE:
        tags.append("low-sample")
    if fav_won is False and fav_prob >= HEAVY_FAVORITE_PROB:
        tags.append("big-upset")
    if row["title"]:
        tags.append("title-fight")

    # Plain-language verdict.
    pct = f"{fav_prob:.0%}"
    if toss_up:
        why = (f"Toss-up: the model had no edge (50/50) and {winner['name']} won by {row['method']} R{row['round']}. "
               "Not counted as a hit or a miss.")
    elif fav_won:
        why = (f"Hit: {fav['name']} was the {pct} favourite and won by {row['method']} R{row['round']}. "
               f"Backed by: {', '.join(for_fav) or 'a small blend of ELO and skill (no single clear edge)'}.")
        if for_dog:
            why += f" Warning signs that did not matter: {', '.join(for_dog)}."
    else:
        winner_signals = [s for s in for_dog if not s.startswith("thin sample")]
        why = (f"Miss: {fav['name']} was the {pct} favourite but {winner['name']} won by {row['method']} R{row['round']}. "
               f"The pick leaned on: {', '.join(for_fav) or 'a small blend of ELO and skill (no single clear edge)'}. "
               f"Signals that pointed to the winner: {', '.join(winner_signals) or 'none (the model saw nothing)'}.")
        if sample < LOW_SAMPLE:
            why += " Low-sample fighter: ratings were mostly priors."
        if fav_prob < COIN_FLIP:
            why += " Near coin flip: not a real model failure."

    return {
        "fight_id": row["fight_id"], "division": row["division"], "title": row["title"],
        "fighter_a": {"id": row["a_id"], "name": row["a_name"]},
        "fighter_b": {"id": row["b_id"], "name": row["b_name"]},
        "favourite": fav, "favourite_probability": round(fav_prob, 4),
        "elo_probability_favourite": round(blend["prob_elo_a"] if fav_is_a else 1.0 - blend["prob_elo_a"], 4),
        "elo_gap_for_favourite": round(elo_gap, 1),
        "skill_edges_for_favourite": edges,
        "style_notes": blend["style_reasons"],
        "winner": winner, "result_method": row["method"], "result_round": row["round"],
        "correct": fav_won,
        "method_predicted": method_pred, "method_actual": method_actual,
        "method_correct": bool(fav_won) and method_pred == method_actual,
        "heavy_favourite": fav_prob >= HEAVY_FAVORITE_PROB,     # crown on the favourite, skull on the rival
        "signals_for_favourite": for_fav, "signals_against_favourite": for_dog,
        "tags": tags, "explanation": why,
    }


def factor_scorecard(rows: List[dict]) -> dict:
    """How often each signal pointed to the eventual winner, over all decided fights in the data."""
    dims = defaultdict(lambda: [0, 0])          # dim -> [edge pointed right, edge fights]
    buckets = {b: [0, 0] for b in ELO_BUCKETS}  # |ELO gap| bucket -> [higher ELO won, fights]
    low = [0, 0]                                # favourite hit rate when a fighter has a thin sample
    overall = [0, 0]
    latest = max(r["date"] for r in rows)
    cutoff = (datetime.strptime(latest, "%Y-%m-%d") - timedelta(days=365)).strftime("%Y-%m-%d")
    conf = {"all": [], "last_12m": []}      # (favourite probability, hit) per decided, non-toss-up fight
    for row in rows:
        blend = _compute_blended_probability(
            row["elo_a"], row["elo_b"], row["skill_a"], row["skill_b"], is_title_fight=row["title"])
        if abs(blend["prob_a"] - 0.5) < 1e-9:
            continue                       # toss-up: no favourite, skip every counter
        overall[1] += 1
        overall[0] += (blend["prob_a"] > 0.5) == bool(row["y"])
        fav_p = max(blend["prob_a"], 1.0 - blend["prob_a"])
        hit = (blend["prob_a"] > 0.5) == bool(row["y"])
        conf["all"].append((fav_p, hit))
        if row["date"] >= cutoff:
            conf["last_12m"].append((fav_p, hit))
        for dim in set(row["skill_a"]) | set(row["skill_b"]):
            edge = row["skill_a"].get(dim, 50.0) - row["skill_b"].get(dim, 50.0)
            if abs(edge) >= EDGE:
                dims[dim][1] += 1
                dims[dim][0] += (edge > 0) == bool(row["y"])
        gap = row["elo_a"] - row["elo_b"]
        for lo, hi in ELO_BUCKETS:
            if lo <= abs(gap) < hi:
                buckets[(lo, hi)][1] += 1
                buckets[(lo, hi)][0] += (gap > 0) == bool(row["y"])
        if min(row["n_a"], row["n_b"]) < LOW_SAMPLE:
            low[1] += 1
            low[0] += (blend["prob_a"] > 0.5) == bool(row["y"])

    def rate(pair):
        return {"hit": pair[0], "n": pair[1], "rate": round(pair[0] / pair[1], 4) if pair[1] else None}

    def level(items):
        def agg(sel):
            n, hits = len(sel), sum(h for _, h in sel)
            return {"n": n, "hits": hits, "rate": round(hits / n, 4) if n else None,
                    "avg_predicted": round(sum(p for p, _ in sel) / n, 4) if n else None}
        return {
            "thresholds": [{"min": t, **agg([x for x in items if x[0] >= t])} for t in CONF_THRESHOLDS],
            "bands": [{"lo": lo, "hi": min(hi, 1.0), **agg([x for x in items if lo <= x[0] < hi])} for lo, hi in CONF_BANDS],
        }

    return {
        "confidence": {"all": level(conf["all"]), "last_12m": level(conf["last_12m"]), "since": cutoff,
                       "flag_threshold": HEAVY_FAVORITE_PROB},
        "overall_favourite": rate(overall),
        f"skill_edge_ge_{int(EDGE)}": {d: rate(p) for d, p in sorted(dims.items())},
        "elo_gap_bucket": {f"{lo}-{hi if hi < 10_000 else '+'}": rate(p) for (lo, hi), p in buckets.items()},
        f"favourite_when_sample_lt_{LOW_SAMPLE}": rate(low),
    }


def summarize(fights: List[dict]) -> dict:
    toss_ups = sum(1 for f in fights if f["correct"] is None)
    fights = [f for f in fights if f["correct"] is not None]      # toss-ups are neither hit nor miss
    n = len(fights)
    hits = sum(f["correct"] for f in fights)
    method_hits = sum(f["method_correct"] for f in fights)
    brier = sum((f["favourite_probability"] - (1.0 if f["correct"] else 0.0)) ** 2 for f in fights) / n if n else None
    return {"fights": n, "correct": hits, "accuracy": round(hits / n, 4) if n else None,
            "method_correct": method_hits, "toss_ups": toss_ups, "brier": round(brier, 4) if brier is not None else None}


def build_event(event_rows: List[dict], wins: Dict[str, List[tuple]]) -> dict:
    fights = [analyse_fight(r, wins) for r in event_rows]
    first = event_rows[0]
    day = datetime.strptime(first["date"], "%Y-%m-%d")
    week_start = (day - timedelta(days=day.weekday())).strftime("%Y-%m-%d")   # Monday of the event's week
    return {"event_id": first["event_id"], "event": first["event"], "date": first["date"], "week_start": week_start,
            "summary": summarize(fights), "fights": fights}


def render_markdown(events: List[dict], scorecard: dict) -> str:
    out = ["# Post-mortem log", "",
           "Pre-fight predictions rebuilt from earlier information only, compared with the real results. "
           "Generated by `python -m models.post_mortem`; the model is never changed from here.", ""]
    all_fights = [f for e in events for f in e["fights"]]
    tot = summarize(all_fights)
    out += [f"**Logged events:** {len(events)} · **Fights:** {tot['fights']} · "
            f"**Correct:** {tot['correct']} ({tot['accuracy']:.1%}) · **Brier:** {tot['brier']}", ""]
    out += ["## Factor scorecard (all history)", "",
            f"Overall favourite hit rate: {scorecard['overall_favourite']['rate']:.1%} on {scorecard['overall_favourite']['n']} fights.", "",
            "| Signal | Pointed to winner | Fights |", "|---|---|---|"]
    for dim, r in scorecard[f"skill_edge_ge_{int(EDGE)}"].items():
        out.append(f"| {dim} edge ≥ {int(EDGE)} | {r['rate']:.1%} | {r['n']} |")
    for bucket, r in scorecard["elo_gap_bucket"].items():
        out.append(f"| Higher ELO, gap {bucket} | {r['rate']:.1%} | {r['n']} |")
    low = scorecard[f"favourite_when_sample_lt_{LOW_SAMPLE}"]
    out += [f"| Favourite, a fighter with <{LOW_SAMPLE} prior fights | {low['rate']:.1%} | {low['n']} |", ""]
    for e in sorted(events, key=lambda ev: ev["date"], reverse=True):
        s = e["summary"]
        out += [f"## {e['event']} — {e['date']}", "",
                f"{s['correct']}/{s['fights']} correct ({s['accuracy']:.0%}) · methods right: {s['method_correct']} · Brier {s['brier']}", ""]
        for f in sorted(e["fights"], key=lambda x: -x["favourite_probability"]):
            mark = "➖" if f["correct"] is None else ("✅" if f["correct"] else "❌")
            mark += " 👑" if f["heavy_favourite"] else ""
            out.append(f"- {mark} **{f['favourite']['name']}** vs {f['fighter_a']['name'] if f['favourite']['id'] != f['fighter_a']['id'] else f['fighter_b']['name']} "
                       f"({f['favourite_probability']:.0%}; predicted {f['method_predicted']}, actual {f['method_actual']})  ")
            out.append(f"  {f['explanation']}" + (f" _[{', '.join(f['tags'])}]_" if f["tags"] else ""))
        out.append("")
    return "\n".join(out)


def _rate(items: List[dict]) -> dict:
    n = len(items)
    held = sum(1 for i in items if i["held"])
    return {"n": n, "held": held, "upsets": n - held, "rate": round(held / n, 4) if n else None,
            "avg_predicted": round(sum(i["probability"] for i in items) / n, 4) if n else None}


def build_watchlist_history(rows: List[dict], wins: Dict[str, List[tuple]]) -> dict:
    """Every past fight that would have been flagged (favourite >= HEAVY_FAVORITE_PROB), crown held or skull hit.

    Pre-fight state is reconstructed from earlier information only (not a frozen live prediction), and the model
    parameters were tuned on these same fights, so the rates are optimistic.
    """
    items = []
    for row in rows:
        f = analyse_fight(row, wins)
        if not f["heavy_favourite"] or f["correct"] is None:
            continue
        fav = f["favourite"]
        rival = f["fighter_b"] if f["fighter_a"]["id"] == fav["id"] else f["fighter_a"]
        items.append({
            "fight_id": f["fight_id"], "date": row["date"], "event": row["event"], "division": f["division"],
            "title": f["title"], "favourite": fav, "rival": rival, "probability": f["favourite_probability"],
            "held": f["correct"], "winner": f["winner"]["name"], "method": f["result_method"], "round": f["result_round"],
            "method_predicted": f["method_predicted"], "method_actual": f["method_actual"],
        })
    items.sort(key=lambda i: i["date"], reverse=True)

    def group(key):
        buckets: Dict[str, List[dict]] = defaultdict(list)
        for i in items:
            buckets[key(i)].append(i)
        return {k: _rate(v) for k, v in sorted(buckets.items())}

    def band(i):
        p = i["probability"]
        return "65-70" if p < 0.70 else "70-75" if p < 0.75 else "75+"

    streak = 0                       # current run of crowns that held (newest first)
    for i in items:
        if not i["held"]:
            break
        streak += 1
    return {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "threshold": HEAVY_FAVORITE_PROB,
        "note": "Reconstructed from pre-fight data (not frozen live predictions); in-sample, so likely optimistic.",
        "overall": _rate(items), "current_crown_streak": streak,
        "by_year": group(lambda i: i["date"][:4]), "by_division": group(lambda i: i["division"]),
        "by_band": group(band), "by_title": group(lambda i: "title fight" if i["title"] else "non-title"),
        "fights": items,
    }


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Post-event prediction review")
    parser.add_argument("--data", default="data")
    parser.add_argument("--event", default=None, help="substring of the event name")
    parser.add_argument("--last", type=int, default=1, help="how many of the most recent events (default 1)")
    parser.add_argument("--all-events", action="store_true")
    parser.add_argument("--since", default=None, help="backfill every event on or after YYYY-MM-DD")
    parser.add_argument("--new", action="store_true",
                        help="every event newer than the newest logged one (the latest event on a first run)")
    args = parser.parse_args()

    data_dir = Path(args.data)
    rows = load_rows(data_dir)
    wins = _method_dists(data_dir)

    # The watchlist history depends only on the data, so it is refreshed on every run (even with no new event).
    history = build_watchlist_history(rows, wins)
    (data_dir / "watchlist_history.json").write_text(json.dumps(history, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    o = history["overall"]
    print(f"Watchlist history: {o['n']} flagged fights, crown held {o['held']} ({o['rate']:.1%}) -> {data_dir / 'watchlist_history.json'}")

    by_event: Dict[str, List[dict]] = defaultdict(list)
    for r in rows:
        by_event[r["event_id"]].append(r)
    ordered = sorted(by_event.values(), key=lambda rs: rs[0]["date"], reverse=True)

    path = data_dir / "post_mortem.json"
    existing = {}
    if path.exists():
        existing = {e["event_id"]: e for e in json.loads(path.read_text(encoding="utf-8")).get("events", [])}

    if args.event:
        selected = [rs for rs in ordered if args.event.lower() in rs[0]["event"].lower()]
    elif args.all_events:
        selected = ordered
    elif args.since:
        selected = [rs for rs in ordered if rs[0]["date"] >= args.since]
    elif args.new:
        newest = max((e["date"] for e in existing.values()), default=None)
        selected = [rs for rs in ordered if newest is None or rs[0]["date"] > newest] if newest else ordered[:1]
    else:
        selected = ordered[:args.last]
    if not selected:
        print("Nothing new to review.")
        return

    for rs in selected:
        existing[rs[0]["event_id"]] = build_event(rs, wins)      # upsert: re-running an event refreshes it

    events = sorted(existing.values(), key=lambda e: e["date"], reverse=True)
    scorecard = factor_scorecard(rows)
    path.write_text(json.dumps({"generated": datetime.now().isoformat(timespec="seconds"),
                                "factor_scorecard": scorecard, "events": events},
                               indent=2, ensure_ascii=False), encoding="utf-8")
    (data_dir / "post_mortem_log.md").write_text(render_markdown(events, scorecard), encoding="utf-8")

    for rs in selected:
        e = existing[rs[0]["event_id"]]
        s = e["summary"]
        print(f"\n{e['event']} ({e['date']}): {s['correct']}/{s['fights']} correct, methods {s['method_correct']}, Brier {s['brier']}")
        for f in e["fights"]:
            print(("  --  " if f["correct"] is None else "  OK  " if f["correct"] else "  MISS"), f["explanation"])
    print(f"\nSaved {path} and {data_dir / 'post_mortem_log.md'}")


if __name__ == "__main__":
    main()
