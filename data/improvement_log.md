# Improvement Log

Record of changes to the prediction engine, with accuracy before and after.
Entry format: date, description, files changed, baseline accuracy, new accuracy, delta, per-division table,
holdout accuracy, conclusion (keep / adjust / revert), notes.

How accuracy is measured here: every past fight is rebuilt from earlier information only (effective ELO with
Legacy Decay, skill state after the fighter's previous fight). A fight counts as correct when the favourite
(probability > 50%) won. The first 80% of fights (chronologically) is the tuning set, the last 20% the holdout.
Both are in-sample with respect to the engine parameters, so real-world accuracy is likely lower.

---

## 2026-10-04 — Style Clash Adjustment (matchup-specific probability nudges)

**Description.** Four rules added on top of the linear ELO + skill blend, summed and clamped to +-10 pp:
1. Grappling dominance vs poor defence (A.Grappling - B.Defensa > 20): +-3 pp
2. Striking dominance vs poor defence (A.Striking - B.Defensa > 25): +-2 pp
3. Cardio edge in 5-round fights (title fight or main event; Cardio gap > 15): +-2 pp
4. Finish-rate edge (Finish Rate > 80 vs < 50): +-1.5 pp

The ELO + skill + style blend now lives in one function, `_compute_blended_probability`, used by
`/predict`, `/simulate` and the backtest scripts. The ELO gap is also clamped to +-250 explicitly (no effect on
accuracy, which depends only on the sign of p - 0.5).

**Files modified.** `backend/services.py` (`compute_style_adjustment`, `_compute_blended_probability`,
`build_prediction`, `build_fight_simulation`, `build_upcoming_events`), `backend/schemas.py`
(`style_adjustment`, `style_reasons`), `backend/main.py` (`is_title_fight`, `is_main_event` on `/predict`).
New: `models/backtest_style_clash.py`, `models/tune_style_clash.py`, `data/improvement_log.md`.
Results: `data/backtest_style_clash.json`, `data/tune_style_clash.json`.

**Backtest with the default parameters** (7690 decided fights, 6152 tuning / 1538 holdout)

| Set | Fights | No style | With style | Delta (pp) | Brier no style | Brier with style | Flipped to correct | Flipped to wrong |
|---|---|---|---|---|---|---|---|---|
| Tuning | 6152 | 60.37 | 60.48 | +0.11 | 0.2324 | 0.2321 | 25 | 18 |
| Holdout | 1538 | 68.73 | 68.53 | -0.20 | 0.2143 | 0.2142 | 6 | 9 |
| All | 7690 | 62.04 | 62.09 | +0.05 | 0.2288 | 0.2285 | 31 | 27 |

Fights where the ELO probability is between 0.45 and 0.55 (the zone where style should help most):

| Set | Fights in zone | No style | With style |
|---|---|---|---|
| Tuning | 2406 | 52.0 | 52.3 |
| Holdout | 544 | 55.9 | 55.3 |
| All | 2950 | 52.7 | 52.8 |

Per division (accuracy %, delta in pp):

| Division | Tune n | Base | Style | Delta | Holdout n | Base | Style | Delta |
|---|---|---|---|---|---|---|---|---|
| heavyweight | 653 | 53.3 | 53.4 | +0.15 | 129 | 65.1 | 65.9 | +0.78 |
| light heavyweight | 628 | 60.8 | 60.7 | -0.16 | 127 | 73.2 | 72.4 | -0.79 |
| middleweight | 937 | 59.4 | 59.7 | +0.21 | 231 | 65.8 | 65.8 | +0.00 |
| welterweight | 1191 | 60.1 | 59.9 | -0.25 | 214 | 73.8 | 73.8 | +0.00 |
| lightweight | 1222 | 61.0 | 61.5 | +0.49 | 255 | 71.4 | 70.6 | -0.78 |
| featherweight | 653 | 62.0 | 62.0 | +0.00 | 230 | 66.1 | 65.7 | -0.43 |
| bantamweight | 583 | 64.7 | 64.8 | +0.17 | 208 | 63.5 | 63.9 | +0.48 |
| flyweight | 285 | 64.6 | 64.9 | +0.35 | 144 | 72.2 | 71.5 | -0.69 |

**Diagnostics.**
- The adjustment is non-zero in 11.4% of fights (above the 10% warning line).
- Rules 1 and 2 fire together in 63 of the 830 fights where either fires
  (7.6%, below the 30% line), so rule 2 was **not** softened. They remain
  correlated by construction: "Defensa" is one combined defence score (strikes + takedowns), so rule 1 does not
  measure takedown defence specifically. Known limitation.
- Historically the 5-round (cardio) rule only fires for title fights: the fight CSVs do not record card position.
  Live predictions also use the main-event flag from ufc.com.

**Grid search** (19,683 combinations, thresholds and adjustments as specified; top 10 by tuning
accuracy checked once on the holdout). Defaults: tuning 60.48% / holdout 68.53%
(Brier 0.2142). Best by tuning: 60.74% tuning, 68.47% holdout.

| # | Tuning acc | Holdout acc | Holdout Brier | (a) +0.5 holdout | (b) no tuning loss | (c) Brier ok |
|---|---|---|---|---|---|---|
| 1 | 60.74 | 68.47 | 0.2141 | no | yes | yes |
| 2 | 60.74 | 68.47 | 0.2141 | no | yes | yes |
| 3 | 60.74 | 68.47 | 0.2140 | no | yes | yes |
| 4 | 60.74 | 68.47 | 0.2140 | no | yes | yes |
| 5 | 60.73 | 68.47 | 0.2141 | no | yes | yes |
| 6 | 60.73 | 68.47 | 0.2141 | no | yes | yes |
| 7 | 60.73 | 68.47 | 0.2140 | no | yes | yes |
| 8 | 60.73 | 68.47 | 0.2141 | no | yes | yes |
| 9 | 60.73 | 68.47 | 0.2141 | no | yes | yes |
| 10 | 60.73 | 68.47 | 0.2140 | no | yes | yes |

Selection rule (strict): apply a candidate only if (a) holdout beats the defaults by +0.5 pp, (b) tuning does
not fall below the defaults, (c) holdout Brier does not worsen. Result: **keep_defaults** — no candidate meets
(a); the best ones gain at most +0.26 pp in tuning and
-0.07 pp in the holdout.

**Acceptance criteria.**
- Overall accuracy +0.5 pp (holdout): **FAIL** (-0.20 pp; all fights +0.05 pp).
- No division drops more than 1.5 pp (relaxed from 0.5): **PASS** (worst: light heavyweight -0.79 pp).
- `/predict` returns `style_adjustment` and `style_reasons`: PASS (see smoke test in the notes).

**Conclusion: do not count this as an accuracy improvement.** The Style Clash is statistically neutral: +0.05 pp over all
fights, 31 picks flipped to correct against 27 to wrong, and the holdout moves
-0.20 pp, all well inside the noise of 1538 fights (about +-1.2 pp). Brier is essentially
unchanged (0.2288 to 0.2285). Default values are kept; no grid combination is better in a way the
holdout confirms. Data in `data/` was not regenerated (prediction-time change only).

**Decision (maintainer, 2026-10-04): context only.** The adjustment is NOT applied to the win probability
(`STYLE_AFFECTS_PROBABILITY = False`, `style_adjustment` stays 0.0). The matchup notes are still computed and returned
as `style_reasons`, and the UI shows them as "Style context (does not affect the %)" on the Home featured fight
and on the comparison page, naming the fighter each note favours. The backtest and tuning scripts pass
`apply_style` explicitly, so they keep measuring the adjustment and can be re-run if the rules change.

**Notes.**
- Re-run any time: `python -m models.backtest_style_clash` (add `--baseline-path ../EloSys_backup_data_pre_q` to
  also measure a no-style baseline on an external data copy) and `python -m models.tune_style_clash`.
- The backtest counts exact 50% ties (debutant vs debutant with equal rating and neutral skills) as a pick for
  fighter B, which is why its no-style accuracy is a little lower than the ELO-only figure in `/accuracy`.
- Side finding: ELO alone and ELO + skill blend are equal overall (61.96% vs 62.04%); the skill blend helps in the
  holdout (+1.0 pp) and not in the tuning set (-0.15 pp).

---

## 2026-10-04 — Sharper Q_opponent + Legacy Decay

**Description.** Q_opponent table widened (champion +0.20 / -0.10 down to unranked -0.15 / -0.20) and computed from
the opponent's standing on the fight date (active pool of the division, champion tracked through title fights).
Legacy Decay: each fight's ELO change counts 5% less per year beyond 5 years, for the shown rating and for predictions.

**Files modified.** `models/elo_engine.py`, `backend/services.py` (`_effective_elo`, `build_accuracy`, `_get_current_elo`), `README.md`.

**Result (pre-fight ELO, all decided fights; `/accuracy`).**

| Window | Before | After |
|---|---|---|
| All fights (7,614) | 62.0% | 62.6% |
| Last 500 | 67.5% | 68.4% |
| Last 100 | 66.0% | 69.0% |

**Conclusion: keep.** Small but consistent gain; the last-100 figure is noise-limited (about +-5 pp). In-sample.
