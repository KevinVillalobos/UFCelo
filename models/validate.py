"""
Validates ELO predictive accuracy — 80/20 chronological train/test split.
Run from the project root:  python -m models.validate
"""
import argparse
import logging
from collections import Counter
from pathlib import Path
from typing import Dict, List

from .elo_engine import EloEngine, load_fighters, read_fights, write_json

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

_W = 44          # total box width
_I = _W - 2     # inner content width (42)
_DIV = "╠" + "═" * _I + "╣"
_TOP = "╔" + "═" * _I + "╗"
_BOT = "╚" + "═" * _I + "╝"


def _row(label: str, value: str) -> str:
    content = f" {label}"
    spaces = _I - len(content) - len(value) - 1
    return f"║{content}{' ' * max(1, spaces)}{value} ║"


def _sub(label: str, value: str) -> str:
    content = f"   {label}"
    spaces = _I - len(content) - len(value) - 1
    return f"║{content}{' ' * max(1, spaces)}{value} ║"


def _hdr(text: str) -> str:
    return f"║ {text:<{_I - 2}} ║"


def _pct(items: List[Dict]) -> str:
    if not items:
        return "N/A"
    c = sum(1 for r in items if r["correct"])
    return f"{c / len(items) * 100:.1f}%  ({c}/{len(items)})"


def main() -> None:
    import sys
    sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Validate ELO predictive accuracy")
    parser.add_argument("--division", default="heavyweight")
    parser.add_argument("--fights", default=None)
    parser.add_argument("--fighters", default=None)
    parser.add_argument("--output", default=None)
    parser.add_argument("--split", type=float, default=0.80)
    parser.add_argument("--min-fights", type=int, default=3,
                        help="Min prior fights for both fighters to count in 'con info' sample")
    args = parser.parse_args()

    slug = args.division.lower().replace(" ", "_")
    fights_path = Path(args.fights) if args.fights else Path(f"data/fights_{slug}.csv")
    fighters_path = Path(args.fighters) if args.fighters else Path(f"data/fighters_{slug}.json")
    output_path = Path(args.output) if args.output else Path(f"data/validation_report_{slug}.json")

    fights = read_fights(fights_path)
    fighters = load_fighters(fighters_path, division=args.division)

    if not fights:
        log.error("No fights found at %s", fights_path)
        return

    split_idx = int(len(fights) * args.split)
    train_fights = fights[:split_idx]
    test_fights = fights[split_idx:]

    log.info("Train: %d fights  |  Test: %d fights", len(train_fights), len(test_fights))

    # Train ELO on the training set
    ranking, _ = EloEngine(division=args.division).process(train_fights, fighters)
    elo_map = {entry["fighter_id"]: entry["elo"] for entry in ranking}
    streak_map = {entry["fighter_id"]: entry.get("streak", 0) for entry in ranking}

    # Count training fights per fighter (used for rookie filter)
    train_counts: Counter = Counter()
    for f in train_fights:
        train_counts[f.fighter_a_id] += 1
        train_counts[f.fighter_b_id] += 1

    # Evaluate each test fight
    results: List[Dict] = []
    draws_skipped = 0

    for fight in test_fights:
        winner = fight.winner_id
        if not winner or winner not in (fight.fighter_a_id, fight.fighter_b_id):
            draws_skipped += 1
            continue

        elo_a = elo_map.get(fight.fighter_a_id, 1500.0)
        elo_b = elo_map.get(fight.fighter_b_id, 1500.0)
        prob_a = 1.0 / (1.0 + 10 ** ((elo_b - elo_a) / 400.0))
        predicted = fight.fighter_a_id if prob_a >= 0.5 else fight.fighter_b_id
        correct = predicted == winner
        elo_diff = abs(elo_a - elo_b)
        has_info = (train_counts[fight.fighter_a_id] >= args.min_fights and
                    train_counts[fight.fighter_b_id] >= args.min_fights)

        # Normalize method label (scraper maps decisions → "OTHER")
        method = fight.method
        if method == "KO/TKO":
            method_group = "KO/TKO"
        elif method == "SUB":
            method_group = "SUB"
        elif method in ("DEC U", "DEC S", "DEC M", "OTHER"):
            method_group = "DEC/OTHER"
        else:
            method_group = "OTHER"

        winner_streak = streak_map.get(winner, 0)
        loser_id = fight.fighter_b_id if winner == fight.fighter_a_id else fight.fighter_a_id
        loser_streak = streak_map.get(loser_id, 0)

        results.append({
            "correct": correct,
            "elo_diff": elo_diff,
            "is_title": fight.is_title_fight,
            "method": method_group,
            "has_info": has_info,
            "winner_streak": winner_streak,
            "loser_streak": loser_streak,
        })

    # ── Aggregate stats ──────────────────────────────────────────────────────
    total = len(results)
    total_correct = sum(1 for r in results if r["correct"])
    accuracy_total = total_correct / total if total else 0.0

    info = [r for r in results if r["has_info"]]
    accuracy_info = sum(1 for r in info if r["correct"]) / len(info) if info else 0.0

    clear  = [r for r in results if r["elo_diff"] > 150]
    close  = [r for r in results if 50 <= r["elo_diff"] <= 150]
    tossup = [r for r in results if r["elo_diff"] < 50]

    titles  = [r for r in results if r["is_title"]]
    normals = [r for r in results if not r["is_title"]]

    ko_fights  = [r for r in results if r["method"] == "KO/TKO"]
    sub_fights = [r for r in results if r["method"] == "SUB"]
    dec_fights = [r for r in results if r["method"] == "DEC/OTHER"]

    streak_pos  = [r for r in results if r["winner_streak"] >= 3]
    streak_neg  = [r for r in results if r["winner_streak"] <= -2]
    streak_none = [r for r in results if -2 < r["winner_streak"] < 3]

    title_count = sum(1 for f in test_fights if f.is_title_fight)

    baseline = 0.50
    improvement = accuracy_total - baseline

    # ── Pretty-print ─────────────────────────────────────────────────────────
    print(_TOP)
    print(f"║{'REPORTE DE VALIDACIÓN — UFCelo.gg'.center(_I)}║")
    print(_DIV)
    print(_row("División:", args.division.title()))
    print(_row("Peleas entrenamiento:", str(len(train_fights))))
    print(_row("Peleas test (total):", str(len(test_fights))))
    print(_row(f"Peleas test (con ≥{args.min_fights} peleas previas):", str(len(info))))
    print(_DIV)
    print(_row("Precisión total:", f"{accuracy_total * 100:.1f}%  ({total_correct}/{total})"))
    print(_row(f"Precisión con info (≥{args.min_fights} peleas):", f"{accuracy_info * 100:.1f}%  ({sum(1 for r in info if r['correct'])}/{len(info)})"))
    print(_row("Baseline (volado):", "50.0%"))
    print(_row("Mejora sobre baseline:", f"+{improvement * 100:.1f}%"))
    print(_DIV)
    print(_hdr("Por diferencia de ELO:"))
    print(_sub(f"Favorito claro  (>150):", f"{_pct(clear)}  ({len(clear)} peleas)"))
    print(_sub(f"Pelea pareja  (50-150):", f"{_pct(close)}  ({len(close)} peleas)"))
    print(_sub(f"Sin ventaja    (<50):", f"{_pct(tossup)}  ({len(tossup)} peleas)"))
    print(_DIV)
    print(_hdr("Por método de resultado:"))
    print(_sub("KO/TKO:", f"{_pct(ko_fights)}  ({len(ko_fights)} peleas)"))
    print(_sub("SUB:", f"{_pct(sub_fights)}  ({len(sub_fights)} peleas)"))
    print(_sub("Decisión:", f"{_pct(dec_fights)}  ({len(dec_fights)} peleas)"))
    print(_DIV)
    print(_hdr("Por contexto de racha del ganador:"))
    print(_sub("Ganador en racha +3:", f"{_pct(streak_pos)}  ({len(streak_pos)} peleas)"))
    print(_sub("Ganador en racha -2:", f"{_pct(streak_neg)}  ({len(streak_neg)} peleas)"))
    print(_sub("Sin racha clara:", f"{_pct(streak_none)}  ({len(streak_none)} peleas)"))
    print(_DIV)
    print(_row("Peleas de título detectadas:", str(title_count)))
    print(_BOT)

    # ── Save JSON report ─────────────────────────────────────────────────────
    def _breakdown(lst):
        if not lst:
            return {"fights": 0, "correct": 0, "accuracy": None}
        c = sum(1 for r in lst if r["correct"])
        return {"fights": len(lst), "correct": c, "accuracy": round(c / len(lst), 4)}

    report = {
        "division": args.division,
        "train_fights": len(train_fights),
        "test_fights_total": len(test_fights),
        "draws_skipped": draws_skipped,
        "test_fights_validated": total,
        "test_fights_with_info": len(info),
        "accuracy_total": round(accuracy_total, 4),
        "accuracy_total_pct": f"{accuracy_total * 100:.1f}%",
        "accuracy_with_info": round(accuracy_info, 4),
        "accuracy_with_info_pct": f"{accuracy_info * 100:.1f}%",
        "baseline": "50.0%",
        "improvement_over_baseline": f"+{improvement * 100:.1f}%",
        "title_fights_in_test": title_count,
        "by_elo_diff": {
            "clear_favorite_gt150": _breakdown(clear),
            "close_fight_50_150": _breakdown(close),
            "tossup_lt50": _breakdown(tossup),
        },
        "by_method": {
            "KO_TKO": _breakdown(ko_fights),
            "SUB": _breakdown(sub_fights),
            "DEC_OTHER": _breakdown(dec_fights),
        },
        "by_streak_context": {
            "winner_on_winstreak_3plus": _breakdown(streak_pos),
            "winner_on_losestreak_2plus": _breakdown(streak_neg),
            "no_clear_streak": _breakdown(streak_none),
        },
    }

    write_json(output_path, report)
    log.info("Report saved → %s", output_path)


if __name__ == "__main__":
    main()
