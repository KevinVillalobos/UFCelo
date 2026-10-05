"""Grid search for the Style Clash thresholds and adjustments.

All 3^9 = 19,683 combinations are scored on the tuning set (first 80% of fights, chronologically);
the 10 best by tuning accuracy (ties broken by lower tuning Brier) are then checked ONCE on the holdout.
A candidate replaces the defaults only if it meets all three conditions:
  (a) holdout accuracy beats the defaults by at least +0.5 pp,
  (b) tuning accuracy does not fall below the defaults,
  (c) holdout Brier score does not get worse than the defaults.
If several pass, the highest holdout accuracy wins (ties: lower holdout Brier). If none passes, the
defaults stay. The vectorised scoring below is checked against backend.services before it is trusted.

Run from the project root:   python -m models.tune_style_clash
"""
import argparse
import itertools
import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.services import STYLE_CLAMP, STYLE_DEFAULTS, _compute_blended_probability  # noqa: E402
from models.backtest_style_clash import load_rows, predict, split_rows  # noqa: E402

GRID = {
    "grappling_threshold": [15, 20, 25],
    "striking_threshold": [20, 25, 30],
    "cardio_threshold": [10, 15, 20],
    "finish_high": [75, 80, 85],
    "finish_low": [40, 50, 60],
    "grappling_adj": [0.02, 0.03, 0.04],
    "striking_adj": [0.015, 0.02, 0.025],
    "cardio_adj": [0.015, 0.02, 0.025],
    "finish_adj": [0.010, 0.015, 0.020],
}
MIN_HOLDOUT_GAIN = 0.5   # pp


class Arrays:
    """Per-fight vectors so a parameter combination is scored with a few numpy operations."""

    def __init__(self, rows):
        def skill(side, dim):
            return np.array([r[f"skill_{side}"].get(dim, 50.0) for r in rows], dtype=float)

        self.y = np.array([r["y"] for r in rows], dtype=float)
        # ELO + skill part of the probability, before the style adjustment and before the final clip
        self.base = np.array([
            (lambda b: b["prob_elo_a"] + b["skill_adjustment"])(
                _compute_blended_probability(r["elo_a"], r["elo_b"], r["skill_a"], r["skill_b"], apply_style=False))
            for r in rows], dtype=float)
        self.title = np.array([r["title"] for r in rows], dtype=bool)
        self.g_a, self.g_b = skill("a", "Grappling"), skill("b", "Grappling")
        self.d_a, self.d_b = skill("a", "Defensa"), skill("b", "Defensa")
        self.s_a, self.s_b = skill("a", "Striking"), skill("b", "Striking")
        self.c_a, self.c_b = skill("a", "Cardio/Durabilidad"), skill("b", "Cardio/Durabilidad")
        self.f_a, self.f_b = skill("a", "Finish Rate"), skill("b", "Finish Rate")

    def signs(self, gth, sth, cth, fh, fl):
        sg = (self.g_a - self.d_b > gth).astype(float) - (self.g_b - self.d_a > gth).astype(float)
        ss = (self.s_a - self.d_b > sth).astype(float) - (self.s_b - self.d_a > sth).astype(float)
        cd = self.c_a - self.c_b
        sc = (self.title & (cd > cth)).astype(float) - (self.title & (-cd > cth)).astype(float)
        sf = ((self.f_a > fh) & (self.f_b < fl)).astype(float) - ((self.f_b > fh) & (self.f_a < fl)).astype(float)
        return sg, ss, sc, sf

    def score(self, signs, gadj, sadj, cadj, fadj):
        sg, ss, sc, sf = signs
        adj = np.clip(gadj * sg + sadj * ss + cadj * sc + fadj * sf, -STYLE_CLAMP, STYLE_CLAMP)
        p = np.clip(self.base + adj, 0.05, 0.95)
        return 100.0 * float(np.mean((p > 0.5) == (self.y > 0.5))), float(np.mean((p - self.y) ** 2))


def score_params(arr: Arrays, params: dict):
    return arr.score(arr.signs(params["grappling_threshold"], params["striking_threshold"],
                               params["cardio_threshold"], params["finish_high"], params["finish_low"]),
                     params["grappling_adj"], params["striking_adj"], params["cardio_adj"], params["finish_adj"])


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Grid search for the Style Clash parameters")
    parser.add_argument("--data", default="data")
    parser.add_argument("--holdout", type=float, default=0.2)
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--output", default="data/tune_style_clash.json")
    args = parser.parse_args()

    rows = load_rows(Path(args.data))
    tuning_rows, holdout_rows = split_rows(rows, args.holdout)
    tune, hold = Arrays(tuning_rows), Arrays(holdout_rows)
    print(f"{len(tuning_rows)} tuning fights, {len(holdout_rows)} holdout fights")

    # Trust check: the vectorised scorer must reproduce the service function exactly
    for name, arr, subset in (("tuning", tune, tuning_rows), ("holdout", hold, holdout_rows)):
        ps = [s["prob_a"] for s in predict(subset, True, STYLE_DEFAULTS)]
        ref = 100.0 * sum((p > 0.5) == bool(r["y"]) for p, r in zip(ps, subset)) / len(subset)
        got, _ = score_params(arr, STYLE_DEFAULTS)
        assert abs(ref - got) < 1e-9, (name, ref, got)
    print("vectorised scorer matches backend.services on the defaults")

    names = list(GRID)
    results = []
    thresholds = list(itertools.product(GRID["grappling_threshold"], GRID["striking_threshold"],
                                        GRID["cardio_threshold"], GRID["finish_high"], GRID["finish_low"]))
    adjustments = list(itertools.product(GRID["grappling_adj"], GRID["striking_adj"],
                                         GRID["cardio_adj"], GRID["finish_adj"]))
    for th in thresholds:
        signs = tune.signs(*th)
        for adj in adjustments:
            acc, brier = tune.score(signs, *adj)
            results.append((acc, brier, th + adj))
    print(f"scored {len(results):,} combinations on the tuning set")

    results.sort(key=lambda r: (-r[0], r[1]))
    default_t = score_params(tune, STYLE_DEFAULTS)
    default_h = score_params(hold, STYLE_DEFAULTS)
    print(f"defaults: tuning {default_t[0]:.2f}% (Brier {default_t[1]:.4f})  holdout {default_h[0]:.2f}% (Brier {default_h[1]:.4f})")

    top = []
    for acc_t, brier_t, combo in results[:args.top]:
        params = dict(zip(names, combo))
        acc_h, brier_h = score_params(hold, params)
        cond_a = acc_h >= default_h[0] + MIN_HOLDOUT_GAIN
        cond_b = acc_t >= default_t[0]
        cond_c = brier_h <= default_h[1]
        top.append({"params": params, "tuning_acc": acc_t, "tuning_brier": brier_t,
                    "holdout_acc": acc_h, "holdout_brier": brier_h,
                    "a_holdout_gain": cond_a, "b_no_loss_in_tuning": cond_b, "c_brier_ok": cond_c,
                    "passes": bool(cond_a and cond_b and cond_c)})

    print(f"\n{'#':>2s} {'tune acc':>8s} {'tune Brier':>10s} {'hold acc':>8s} {'hold Brier':>10s}  a b c  params")
    for i, t in enumerate(top, 1):
        p = t["params"]
        short = (f"G{p['grappling_threshold']}/{p['grappling_adj']} S{p['striking_threshold']}/{p['striking_adj']} "
                 f"C{p['cardio_threshold']}/{p['cardio_adj']} F{p['finish_high']}-{p['finish_low']}/{p['finish_adj']}")
        print(f"{i:2d} {t['tuning_acc']:8.2f} {t['tuning_brier']:10.4f} {t['holdout_acc']:8.2f} {t['holdout_brier']:10.4f}  "
              f"{'Y' if t['a_holdout_gain'] else '-'} {'Y' if t['b_no_loss_in_tuning'] else '-'} {'Y' if t['c_brier_ok'] else '-'}  {short}")

    passing = [t for t in top if t["passes"]]
    best_by_holdout = max(top, key=lambda t: (t["holdout_acc"], -t["holdout_brier"]))
    if passing:
        chosen = max(passing, key=lambda t: (t["holdout_acc"], -t["holdout_brier"]))
        decision = "apply"
        print("\nDECISION: apply", chosen["params"])
    else:
        chosen = None
        decision = "keep_defaults"
        print("\nDECISION: no candidate meets all three conditions -> keep the default values")
    print(f"(for reference, best of the top {args.top} by holdout accuracy: {best_by_holdout['holdout_acc']:.2f}% "
          f"vs defaults {default_h[0]:.2f}% — selecting on the holdout would be optimistic)")

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "generated": datetime.now().isoformat(timespec="seconds"),
        "rule": "apply only if (a) holdout >= default + 0.5pp, (b) tuning >= default, (c) holdout Brier <= default",
        "combinations": len(results), "tuning_fights": len(tuning_rows), "holdout_fights": len(holdout_rows),
        "defaults": {"params": STYLE_DEFAULTS, "tuning_acc": default_t[0], "tuning_brier": default_t[1],
                     "holdout_acc": default_h[0], "holdout_brier": default_h[1]},
        "top": top, "decision": decision, "chosen": chosen,
        "best_by_holdout_reference": best_by_holdout,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved {out}")


if __name__ == "__main__":
    main()
