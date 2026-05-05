# UFCelo.gg

Independent ELO-based ranking and skill scoring system for all 8 UFC men's divisions. Built entirely from raw fight data scraped from UFCStats.com, processed through a custom multi-factor ELO engine with 7-dimensional skill scoring, and served through a Streamlit frontend with prediction, simulation, and matchmaking tools.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Tech Stack](#tech-stack)
3. [Data Pipeline](#data-pipeline)
4. [Scraper](#scraper)
5. [ELO Engine](#elo-engine)
6. [Skill Scoring Engine](#skill-scoring-engine)
7. [Validation Framework](#validation-framework)
8. [Backend Layer](#backend-layer)
9. [Frontend Pages](#frontend-pages)
10. [Data Schemas](#data-schemas)
11. [Validation Results](#validation-results)
12. [Champion System](#champion-system)
13. [Cross-Division Deduplication](#cross-division-deduplication)
14. [Updating the Data](#updating-the-data)

---

## Architecture Overview

```
ufcstats.com
     │
     ▼
scraper/scraper.py
     │  (per division)
     ▼
data/fights_{division}.csv          ← fight records + per-fight stats
data/fighters_{division}.json       ← fighter profiles (bio, record)
     │
     ▼
models/elo_engine.py
     │  (per division)
     ├─► data/rankings_{division}.json          ← active ELO rankings
     ├─► data/rankings_{division}_alltime.json  ← all-time by peak ELO
     ├─► data/elo_histories_{division}.json     ← per-fight ELO history + K breakdown
     ├─► data/skill_scores_{division}.json      ← current 7D skill scores
     └─► data/skill_histories_{division}.json   ← skill evolution over time
     │
     ▼
models/validate.py
     └─► data/validation_report_{division}.json
     │
     ▼
scripts/generate_simulations.py
     ├─► data/simulation_{division}_top5.json
     ├─► data/matchmaking_{division}.json
     └─► data/matchmaking_all_divisions.json
     │
     ▼
backend/
  data_loader.py   ← JSON/CSV file access layer
  services.py      ← rankings, prediction, simulation, matchmaking, simulator-data logic
  stats.py         ← per-fighter fight statistics aggregation
     │
     ▼
frontend/
  silhouette.py    ← SVG proportional figure generator (solo + comparison)
  app.py           ← Streamlit home page
  pages/
    1_Rankings.py
    2_Fighter.py
    3_Predict.py
    4_Simulate.py
    5_Matchmaking.py
```

---

## Tech Stack

| Layer | Library |
|-------|---------|
| Scraping | `requests`, `beautifulsoup4` |
| Data | Python stdlib (`csv`, `json`) |
| Engine | Pure Python (no ML frameworks) |
| Frontend | `streamlit`, `plotly`, `pandas` |

No database. All state lives in flat JSON/CSV files in `data/`.

---

## Data Pipeline

### Install dependencies

```bash
pip install streamlit plotly pandas requests beautifulsoup4
```

### Run the full pipeline (per division)

```bash
# 1. Scrape
python scraper/scraper.py --division heavyweight --output data
python scraper/scraper.py --division "light heavyweight" --output data
python scraper/scraper.py --division middleweight --output data
python scraper/scraper.py --division welterweight --output data
python scraper/scraper.py --division lightweight --output data
python scraper/scraper.py --division featherweight --output data
python scraper/scraper.py --division bantamweight --output data
python scraper/scraper.py --division flyweight --output data

# 2. Run ELO engine (repeat for each division)
python models/elo_engine.py --division heavyweight --output data
python models/elo_engine.py --division "light heavyweight" --output data
# ...

# 3. Validate
python -m models.validate --division heavyweight
# ...

# 4. Pre-generate simulations and matchmaking
python scripts/generate_simulations.py

# 5. Launch frontend
streamlit run frontend/app.py
```

Scraper logs: `data/scrape_{division}.log` / `data/scrape_{division}_err.log`.  
Completion marker: log line containing `completado`.

To re-scrape only fight stats (without re-fetching events/fighters):

```bash
python scraper/scraper.py --division heavyweight --output data --refresh-stats
```

---

## Scraper

**File:** `scraper/scraper.py`  
**Source:** `http://ufcstats.com`

### Strategy

UFCStats structures its data across three page types: event lists, event detail pages (fight rows), and individual fight detail pages (per-fight stats). The scraper makes three passes:

1. **Event list** — `GET /statistics/events/completed?page=all` — parses all ~771 UFC events into `(event_id, event_name, event_date, event_url)`.
2. **Fights per event** — parses each event page's HTML table. Extracts fighters (matched via `<a>` href fighter IDs), winner, method, round, time, weight class.
3. **Per-fight stats** — only fetched for target division (saves ~80% of HTTP requests). Parses the fight detail page which contains two HTML table types: "Totals" and "Significant Strikes by Position".

All HTTP calls use Chrome user-agent, 1.5s polite delay, and 3 retries with exponential backoff.

### Division Filtering

Each scraper invocation targets one division via `--division`. A regex filter excludes fights that match similar weight class names. For example, `heavyweight` scraping excludes rows matching `(?i)light\s+heavyweight` and `(?i)women`. This prevents heavyweight data from being contaminated with LHW or women's fights.

The 8 supported slugs: `heavyweight`, `light heavyweight`, `middleweight`, `welterweight`, `lightweight`, `featherweight`, `bantamweight`, `flyweight`.

### Data Classes

**`Fighter`**
```
fighter_id, name, nickname, height, weight, reach, stance, dob,
wins, losses, draws, url
```

**`FightStats`** (per fighter, per fight)
```
strikes_landed, strikes_attempted
head_strikes_landed, head_strikes_attempted
body_strikes_landed, body_strikes_attempted
leg_strikes_landed, leg_strikes_attempted
takedowns_landed, takedowns_attempted
knockdowns, reversals, submission_attempts
control_time          ← raw string "MM:SS"
```

**`Fight`**
```
fight_id, event_id, event_name, event_date
fighter_a_id, fighter_a_name, fighter_b_id, fighter_b_name
winner_id, method, round, time, weight_class, is_title_fight
stats_a: FightStats, stats_b: FightStats
```

### Method Normalization

Raw UFCStats method strings are normalized to a fixed vocabulary:

| Raw string | Normalized |
|------------|-----------|
| KO, TKO | `KO/TKO` |
| Submission | `SUB` |
| Unanimous Decision | `DEC U` |
| Split Decision | `DEC S` |
| Majority Decision | `DEC M` |
| Everything else | `OTHER` |

### Title Fight Detection

Detected from the individual fight detail page via CSS selector `.b-fight-details__fight-head`. If that element's text contains "Title Bout", `is_title_fight = True`. This was a specific fix applied during re-scraping (prior version used event-level heuristics which missed interim title fights).

### CSV Output

`data/fights_{division}.csv` — 35 columns:

| Column group | Columns |
|---|---|
| Event metadata | `fight_id`, `event_id`, `event_name`, `event_date` |
| Fighters | `fighter_a_id`, `fighter_a_name`, `fighter_b_id`, `fighter_b_name` |
| Result | `winner_id`, `method`, `round`, `time`, `weight_class`, `is_title_fight` |
| Fighter A stats | `a_strikes_landed/attempted`, `a_head/body/leg_strikes_landed/attempted`, `a_td_landed/attempted`, `a_knockdowns`, `a_control_time`, `a_sub_attempts`, `a_reversals` |
| Fighter B stats | (same 14 columns, `b_` prefix) |

`data/fighters_{division}.json` — array of fighter profile objects.

---

## ELO Engine

**File:** `models/elo_engine.py`  
**Run:** `python models/elo_engine.py --division <div> --output data`

The engine processes all fights in chronological order and maintains a live ELO rating per fighter. The core ELO update formula is:

```
new_elo = old_elo + K × W × (S - E)
```

Where:
- `K` = effective K-factor (variable, see below)
- `W` = fight weight multiplier (finish type, title fight)
- `S` = actual score (1.0 win, 0.5 draw, 0.0 loss)
- `E` = expected score based on current ELO difference

### Initial ELO

Fighters enter the system with a non-neutral starting ELO based on their pre-scrape record:

```python
initial_elo = 1500 + (win_rate - 0.5) * 400
# Clamped to [1300, 1700]
```

A fighter arriving with a 10-0 record outside the UFC gets a higher starting point than a 0-1 fighter. Fallback is 1500.

### Expected Score

Standard ELO formula with a hard clamp on the ELO difference to prevent extreme probabilities:

```python
diff = max(-250, min(250, elo_a - elo_b))
E_a = 1.0 / (1.0 + 10 ** (-diff / 400))
```

The ±250 clamp sets a maximum of ~82% win probability regardless of ELO gap. This prevents complete dominance situations from fully collapsing ratings.

### K-Factor

K is variable by fight count and then multiplied by a per-division constant:

**Base K by fight count:**

| Fights | Raw K |
|--------|-------|
| 1–4    | 64    |
| 5–14   | 32    |
| 15+    | 20    |

**Per-division multiplier:**

| Division | Multiplier | Rationale |
|----------|-----------|-----------|
| Heavyweight | 1.00 | Reference division |
| Light Heavyweight | 0.95 | Slightly more stable |
| Middleweight | 0.90 | High-quality depth |
| Bantamweight | 0.90 | — |
| Flyweight | 0.90 | — |
| Lightweight | 0.85 | Large, deep roster |
| Featherweight | 0.85 | — |
| Welterweight | 0.75 | Historically most volatile, large roster |

Effective K before multipliers: `k_base * division_mult`.

### Multi-Factor K Adjustment

The final K applied to each fight is the product of 8 independent multipliers:

```
K_final = k_base × W_finish × Q_opponent × S_streak × R_rematch × M_momentum × T_time × D_division
```

#### 1. Fight Weight (`W_finish`)

| Method | Round | Multiplier |
|--------|-------|-----------|
| KO/TKO | R1 | 1.40 |
| KO/TKO | R2 | 1.25 |
| KO/TKO | R3+ | 1.10 |
| SUB | R1 | 1.40 |
| SUB | R2 | 1.25 |
| SUB | R3+ | 1.10 |
| DEC U | any | 1.05 |
| DEC M | any | 0.90 |
| DEC S / OTHER | any | 0.80 |

Title fight bonus: all of the above × 1.20.

#### 2. Quality Multiplier (`Q_opponent`)

Accounts for who you beat or lost to relative to the current rankings:

| Opponent rank | Win modifier | Loss modifier |
|--------------|-------------|--------------|
| Top 5 | +0.10 | -0.05 |
| Top 6–10 | +0.05 | 0.00 |
| Bottom 5 | -0.05 | -0.10 |
| Other | 0.00 | 0.00 |

Floor: 0.70 (quality never reduces the multiplier below this).

#### 3. Streak Multiplier (`S_streak`)

Current streak at fight time (tracked from prior results in the same pass):

| Streak | Multiplier |
|--------|-----------|
| Win streak ≥ 8 | 1.35 |
| Win streak ≥ 5 | 1.25 |
| Win streak ≥ 3 | 1.15 |
| Neutral | 1.00 |
| Loss streak ≤ -3 | 1.25 |
| Loss streak ≤ -5 | 1.40 |
| Loss streak ≤ -8 | 1.55 |

Fighters on long losing streaks lose proportionally more ELO per loss. This accelerates the draining of fighters who are declining but were historically high-rated.

#### 4. Rematch Multiplier (`R_rematch`)

The engine tracks fight history per fighter pair using `frozenset(fighter_a_id, fighter_b_id)` → list of results:

| Fight instance | Multiplier |
|---------------|-----------|
| First fight | 1.00 |
| 2nd fight, same winner | 1.20 (recency bonus) |
| 2nd fight, result reversed | 0.70 (upset dampener) |
| 3rd fight or more | 0.50 |

Prevents ELO from becoming unrealistically lopsided in rivalry situations.

#### 5. Opponent Momentum (`M_momentum`)

| Opponent streak | Multiplier |
|----------------|-----------|
| Win streak ≥ 3 | 1.15 (beating a hot fighter is worth more) |
| Loss streak ≤ -3 | 0.90 (losing to a cold fighter hurts more) |
| Neutral | 1.00 |

#### 6. Time Percentage (`T_time`)

Measures how early/late in the fight the finish occurred relative to total scheduled time:

| Finish timing | Win mult | Loss mult |
|---|---|---|
| < 30% of scheduled time (early) | 1.15 | 0.90 |
| > 80% of scheduled time (late) | 0.90 | 0.85 |
| 30–80% | 1.00 | 1.00 |

#### 7. Division Change Penalty (`D_division`)

When a fighter competes in a new division, only the `_expected_score()` calculation is affected — their effective ELO is discounted by 15% of the deviation from 1500:

```python
effective_elo = raw_elo - (raw_elo - 1500) * 0.15
```

Stored ELO is unchanged; this only penalizes the win probability estimate for that fight, reflecting the uncertainty of moving between weight classes.

### Peak ELO Degradation Penalty

If a fighter is simultaneously on a loss streak ≤ -3 AND their current ELO has fallen below 85% of their career peak, an additional 20% penalty is applied to the loss delta:

```python
if elo < peak_elo * 0.85 and streak <= -3:
    delta *= 1.20
```

This accelerates the rating decline of aging, formerly elite fighters who remain in the rankings due to legacy ELO rather than current form (the "Usman problem").

### ELO Floor/Ceiling Guards

- Beating a low-rated opponent (ELO < 1300): gains capped at +8.0
- Losing to a highly-rated opponent (ELO > 1700): minimum loss of -12.0

### Inactivity Decay

Applied at output time (not stored in fight history, display-only):

```python
months_inactive = (today - last_fight_date).days / 30.44
months_capped = min(months_inactive - 18, 24)   # only starts after 18-month grace

if months_inactive > 18:
    decay_rate = 0.005   # 0.5% per month toward 1500
    if streak <= -3:
        decay_rate *= 1.30
    displayed_elo = raw_elo - (raw_elo - 1500) * decay_rate * months_capped
```

Fighters on both a losing streak and inactivity see their displayed ELO deflate significantly faster. Peak ELO is always recorded from raw (pre-decay) values.

### Peak ELO Tracking

The engine tracks per-fighter:
- `peak_elos[fighter_id]`: highest raw ELO ever recorded mid-fight
- `peak_elo_dates[fighter_id]`: date of that fight
- `peak_elo_opponents[fighter_id]`: opponent name when peak was set

Recorded before inactivity decay is applied so it represents the true career-best rating.

### Per-Fight ELO Breakdown

Every entry in `elo_histories_{division}.json` now includes a `breakdown` dict with 18 fields covering every multiplier that produced the final ELO delta:

```json
"breakdown": {
  "elo_before": 1594.27,  "elo_after": 1542.77,  "delta": -51.49,
  "k_base": 32.0,          "k_var": 2.0,           "div_mult": 1.0,
  "streak_before": -1,     "streak_mult": 1.0,     "method_weight": 1.44,
  "consec_loss_mult": 1.2, "quality_mult": 1.0,    "rematch_mult": 1.0,
  "opp_mom_mult": 1.0,     "time_mult": 1.0,       "k_effective": 92.16,
  "expected_prob": 0.5587, "surprise": -0.5587,
  "cap_applied": false,    "peak_penalty": false
}
```

This powers the per-fight expandable breakdown in the Fighter Profile page and the ELO Simulator on the Predictor page.

### Engine Output

Per division, 5 JSON files:

- **`rankings_{division}.json`** — active fighters (fought within 2 years), sorted by displayed ELO
- **`rankings_{division}_alltime.json`** — all fighters ever, sorted by peak ELO
- **`elo_histories_{division}.json`** — `{fighter_id: [EloHistoryPoint, ...]}` with per-fight `breakdown`
- **`skill_scores_{division}.json`** — current 7D skill scores per fighter
- **`skill_histories_{division}.json`** — skill score state after each fight

---

## Skill Scoring Engine

**File:** `models/elo_engine.py` (`SkillScoreEngine` class)

Separate from ELO, the skill engine builds a multi-dimensional fighter profile from raw fight stats. It runs in parallel with the ELO engine over the same chronological fight pass.

### 7 Dimensions

| Key | Display | Composite weight |
|-----|---------|-----------------|
| `Striking` | Striking | 20% |
| `Defensa` | Defense | 20% |
| `Grappling` | Grappling | 15% |
| `Consistencia` | Consistency | 15% |
| `Finish Rate` | Finish Rate | 10% |
| `Cardio/Durabilidad` | Cardio / Durability | 10% |
| `Presión` | Pressure | 10% |

All dimensions are 0–100 floats.

### Exponential Moving Average

Each fight updates skills with EMA smoothing (α = 0.80):

```python
new_score[dim] = current[dim] * 0.80 + raw_score[dim] * 0.20
```

New fights have limited influence on established fighters; early fights shape a fighter faster.

### Raw Score Calculation

When detailed fight stats are available (CSV columns non-null):

**Striking:**
```python
accuracy = strikes_landed / strikes_attempted
volume   = strikes_landed / (rounds * 5 * baseline_spm)   # baseline_spm = 5.0
raw = min(1.0, (accuracy * 0.6 + volume * 0.4) * 1.2)
```

**Grappling:**
```python
td_acc    = td_landed / td_attempted
td_def    = 1 - opp_td_landed / opp_td_attempted
raw = min(1.0, (td_acc * 0.7 + td_def * 0.3) * 1.1)
```

**Defense:**
```python
td_def        = 1 - opp_td_landed / opp_td_attempted
strike_def    = 1 - opp_strikes_landed / opp_strikes_attempted
raw = td_def * 0.8 + strike_def * 0.2
```

**Consistency:**
Average accuracy across all three strike zones (head, body, leg).

**Finish Rate:**
1.0 if fighter won by KO/TKO or SUB, 0.3 otherwise.

**Cardio:**
```python
raw = 0.8 + (round - 1) * 0.1   # better in later rounds = better cardio score
```

**Pressure:**
```python
control_ratio = control_seconds / (round * 300)
striking_vol  = strikes_landed / (rounds * 5 * baseline_spm)
raw = control_ratio * 0.7 + striking_vol * 0.3
```

### Post-Calculation Adjustments

Method bonuses (applied to winner's raw scores before EMA):

| Method | Dimension boosted | Multiplier |
|--------|------------------|-----------|
| KO/TKO | Striking | ×1.30 |
| KO/TKO | Finish Rate | = 1.00 |
| SUB | Grappling | ×1.30 |
| SUB | Finish Rate | = 1.00 |
| DEC (win) | Consistencia | ×1.20 |
| DEC (win) | Cardio | ×1.20 |
| DEC (win) | Presión | ×1.10 |

Outcome penalties (applied to all dimensions on loss):

| Opponent method | All-dim penalty |
|----------------|----------------|
| KO/TKO | ×0.75 |
| SUB | ×0.80 |
| DEC | ×0.90 |
| Draw | ×0.95 |

Additional bonuses:
- Title fight: +4 pts across all dimensions
- R1–R2 finish: +3 pts across all dimensions

### Fallback (no stats)

When fight stats are unavailable (older fights, scraped without `--refresh-stats`), synthetic scores are assigned based on method alone:

| Method | Striking | Grappling | Defensa | Finish Rate |
|--------|----------|-----------|---------|-------------|
| KO/TKO win | 0.80 | 0.40 | 0.50 | 1.00 |
| SUB win | 0.40 | 0.80 | 0.60 | 1.00 |
| DEC win | 0.60 | 0.60 | 0.70 | 0.30 |
| Loss | 0.45 | 0.45 | 0.45 | 0.20 |

---

## Validation Framework

**File:** `models/validate.py`  
**Run:** `python -m models.validate --division <div>`

### Methodology

1. Load all fights for the division, sort chronologically.
2. Split 80% train / 20% test (chronological, no shuffling to prevent data leakage).
3. Run the ELO engine on training fights only.
4. For each test fight, compute `P(A wins)` from ELO ratings at test-time.
5. Predict winner = whichever fighter has P > 0.50.
6. Compare to actual outcome.

### Report Breakdowns

The validation report breaks accuracy down by:

- **ELO difference band**: clear favorites (>150 ELO diff), competitive (50–150), coin-flip (<50)
- **Method**: KO/TKO, SUB, DEC/OTHER
- **Streak context**: winner was on win-streak (+3), loss-streak (-2), or neutral
- **Experience filter**: fighters with ≥3 prior fights only (removes predictions on debut fighters)

Output: `data/validation_report_{division}.json` + a Unicode box display to stdout.

**Baseline:** 50% (coin flip). All reported accuracy figures are vs. this baseline.

---

## Backend Layer

### `backend/data_loader.py`

Pure file I/O with caching and legacy fallbacks. Key functions:

| Function | Returns |
|----------|---------|
| `load_rankings(division, alltime)` | List of ranking dicts |
| `load_skill_scores(division)` | List of skill score dicts |
| `load_fighters(division)` | Standardized fighter list |
| `load_elo_histories(division)` | `{fighter_id: [HistoryPoint]}` |
| `load_skill_histories(division)` | Skill evolution per fight |
| `load_champions()` | `{division: {fighter_id, fighter_name}}` |
| `get_fighter_by_id(id, division)` | Single fighter dict |
| `get_skill_score_by_id(id, division)` | Skill dimensions dict |
| `get_upcoming_events()` | Future events from events.json |
| `set_fighter_retired(id, bool)` | Persists to retired_overrides.json |

**Division slug normalization:** `"light heavyweight"` → `"light_heavyweight"` (lowercase + underscore).

**Legacy fallbacks:** First tries `skill_scores_{division}.json`, then falls back to `skill_scores.json`. This preserves compatibility with older outputs.

### `backend/services.py`

Business logic layer. All functions return serializable dicts/lists ready for the frontend.

#### `build_ranking_response(division, alltime)`

1. Load raw rankings.
2. Build a cross-division ELO index: scan all 8 divisions, record `{fighter_id: max_elo_seen}`.
3. Determine each fighter's primary division (where their ELO is highest).
4. Deduplicate: show each fighter only in their primary division.
5. Apply champion lock: champion from `champions.json` is always pinned to their designated division at rank 1.
6. Apply ELO carry-over: use the fighter's best ELO across all divisions as their displayed ELO (prevents deflated ratings when a champion moves up).
7. Filter retired fighters via `retired_overrides.json`.

#### `build_fighter_profile(fighter_id, division)`

Assembles: current ELO + peak, ELO history with per-fight deltas, 7D skill scores, skill history, record, physical stats (height, reach, stance, DOB).

#### `build_prediction(fighter_a_id, fighter_b_id, division)`

**Step 1 — ELO probability:**
```python
diff = max(-250, min(250, elo_a - elo_b))
p_elo = 1.0 / (1.0 + 10 ** (-diff / 400))
```

**Step 2 — Skill composite:**
```python
weights = {"Striking": 0.20, "Defensa": 0.20, "Grappling": 0.15,
           "Consistencia": 0.15, "Finish Rate": 0.10,
           "Cardio/Durabilidad": 0.10, "Presión": 0.10}
composite = sum(score[dim] * w for dim, w in weights.items())
```

**Step 3 — Blend:**
```python
skill_adj = (composite_a - composite_b) / 100 * 0.10   # max ±10%
p_final = max(0.05, min(0.95, p_elo + skill_adj))
```

**Step 4 — Method prediction** (from favored fighter's skills):
- Both Striking ≥ 65 AND Grappling ≥ 65 → compare: `SUB` if Grappling > Striking, else `KO/TKO`
- Striking ≥ 65 only → `KO/TKO`
- Grappling ≥ 65 only → `SUB`
- Finish Rate < 55 → `DEC`
- Otherwise → `DEC`

**Step 5 — Key advantage:** dimension with the largest absolute difference between fighters.

#### `build_fight_simulator_data(fighter_a_id, fighter_b_id, division)`

Returns the current ELO state and all K-factor parameters for both fighters so the frontend can compute exact ELO deltas for any hypothetical fight outcome without re-running the engine. Includes: current ELOs, fight counts, streaks, variable-K values, streak multipliers, division multiplier, win probability, and the method weight tables.

#### `build_fight_simulation(fighter_a_id, fighter_b_id, division, n_trials)`

Monte Carlo simulation. Default: 1000 independent trials, max championship rounds (5).

Each trial:

```python
# Winner
winner = A if random() < p_final else B

# Method
ko_w  = (Striking/100) * (Finish_Rate/100)
sub_w = (Grappling/100) * (Finish_Rate/100)
dec_w = max(0.10, 1.0 - ko_w - sub_w)
method = choices(["KO/TKO", "SUB", "DEC"], weights=[ko_w, sub_w, dec_w])

# Round (3-round fight unless title)
if method == "KO/TKO":
    # R1 boosted by Presión, R3 reduced by it
    weights_r = [0.40 + presión*0.15, 0.35, 0.25 - presión*0.10]
elif method == "SUB":
    # R3 boosted by Cardio (late submissions)
    weights_r = [0.20, 0.35, 0.30 + cardio*0.15]
else:
    weights_r = [0.10, 0.20, 0.70]   # decisions go the distance
```

Aggregates: win %, method breakdown (%), round distribution (%), most likely outcome string.

#### `build_matchmaking(division, top_n)`

Surfaces the most attractive fights within a division.

**Filters:**
- Only fighters who have been active within 2 years
- ELO difference ≤ 300 (filters non-competitive matchups)
- Excludes pairs who fought each other within the past 2 years

**Scoring:**
```python
competitiveness = max(0, 1.0 - elo_diff / 200)
style_contrast  = mean(|skill_a[dim] - skill_b[dim]| for all dims) / 100
matchup_score   = 0.70 * competitiveness + 0.30 * style_contrast
```

Top-N matchups returned sorted by `matchup_score` descending.

---

## Frontend Pages

**Launch:** `streamlit run frontend/app.py`

### Home (`app.py`)

- 8 division cards with top-3 fighters (ELO, streak badge, champion crown)
- Quick predictor widget with probability bar chart

### Rankings (`pages/1_Rankings.py`)

- Full division ELO table: Rank, Fighter, ELO, Peak ELO, Peak Opponent, Record, Fights, Last Fight, Streak
- Active / All-Time toggle (all-time sorts by peak ELO)
- Division stats sidebar: mean ELO, median, std dev, spread

### Fighter Profile (`pages/2_Fighter.py`)

- Current ELO, peak ELO, career record, division rank, streak delta
- Proportional SVG silhouette (height, reach, weight) + skill radar side-by-side
- ELO history line chart with W/L/D color-coded fight markers
- Full fight summary table (all fights at a glance: date, result, opponent, method, ELO, Δ ELO)
- Per-fight expandable rows with:
  - ELO before/after/delta metrics
  - Complete K-factor breakdown table (base × variable K × division × method × streak × quality × rematch × momentum × time = K effective)
  - Natural language insight (upset detection, streak bonuses, early-finish bonus, cap/peak-penalty flags)
- Projected ELO vs 5 nearest rivals (estimated win/loss delta for each potential matchup)
- Fight statistics panel: win/loss method chart, striking bars + head/body/leg target breakdown, grappling bars, career striking trend
- Skill radar + composite score breakdown table with tier labels (Elite / Above avg / Average / Below avg)
- Fully responsive layout (mobile-optimized CSS)

### Predictor (`pages/3_Predict.py`)

- Fighter A vs Fighter B selector with ELO display
- Horizontal probability bar (ELO + skill blended)
- Win probability %, ELO edge, predicted method, key advantage
- Proportional SVG silhouette comparison (height diff badge, reach advantage badge)
- Overlaid dual skill radar + per-dimension advantage table
- Fight statistics comparison panel (methods %, striking, grappling, target breakdown)
- **ELO Simulator** — pick method, round, and title-fight toggle to see:
  - Exact ELO delta for both fighters under any outcome (mirrors the engine formula)
  - K breakdown expander with all multipliers, current streaks, and fight counts
  - Natural language insight per scenario
- Model explanation expander
- Fully responsive layout (mobile-optimized CSS)

### Simulator (`pages/4_Simulate.py`)

- Configurable trial count (100–10,000)
- Win distribution donut chart
- Method breakdown bar chart
- Finishing round distribution (separate by method)
- Most likely outcome headline
- Methodology explanation expander

### Matchmaking (`pages/5_Matchmaking.py`)

- Sortable matchup table: fighters, ELO, matchup score, competitiveness, style contrast
- Detail card for selected matchup (probability bar, gauge charts)
- Scatter plot: Competitiveness vs Style Contrast (ideal matchup = top-right corner)

---

## Data Schemas

### `rankings_{division}.json`

```json
[
  {
    "fighter_id": "...",
    "fighter_name": "Tom Aspinall",
    "division": "Heavyweight",
    "elo": 1712.4,
    "peak_elo": 1724.1,
    "peak_elo_date": "2024-10-26",
    "peak_elo_opponent": "Curtis Blaydes",
    "record": "15-3-0",
    "fight_count": 18,
    "last_fight_date": "2024-10-26",
    "active": true,
    "streak": 7
  }
]
```

`rankings_{division}_alltime.json` adds `"alltime_rank": 1`.

### `elo_histories_{division}.json`

```json
{
  "fighter_id": [
    {
      "date": "2024-10-26",
      "fight_id": "...",
      "opponent_id": "...",
      "opponent_name": "Curtis Blaydes",
      "result": "Win",
      "elo": 1712.4,
      "event": "UFC 307",
      "method": "KO/TKO",
      "round": 1,
      "time": "0:53",
      "weight_class": "Heavyweight",
      "is_title_fight": true,
      "breakdown": {
        "elo_before": 1693.7, "elo_after": 1712.4, "delta": 18.7,
        "k_base": 32.0, "k_var": 0.625, "div_mult": 1.0,
        "streak_before": 6, "streak_mult": 1.25,
        "method_weight": 1.68, "consec_loss_mult": 1.0,
        "quality_mult": 1.1, "rematch_mult": 1.0,
        "opp_mom_mult": 1.0, "time_mult": 1.15,
        "k_effective": 47.3, "expected_prob": 0.6451, "surprise": 0.3549,
        "cap_applied": false, "peak_penalty": false
      }
    }
  ]
}
```

### `skill_scores_{division}.json`

```json
[
  {
    "fighter_id": "...",
    "fighter_name": "Tom Aspinall",
    "division": "Heavyweight",
    "skill_score": {
      "Striking": 82.4,
      "Grappling": 74.1,
      "Defensa": 78.9,
      "Consistencia": 71.3,
      "Finish Rate": 91.0,
      "Cardio/Durabilidad": 68.5,
      "Presión": 83.2
    },
    "skill_composite": 78.6
  }
]
```

### `champions.json`

```json
{
  "heavyweight":       { "fighter_id": "...", "fighter_name": "Tom Aspinall" },
  "lightweight":       { "fighter_id": "...", "fighter_name": "Ilia Topuria" },
  "welterweight":      { "fighter_id": "...", "fighter_name": "Islam Makhachev" },
  "featherweight":     { "fighter_id": "...", "fighter_name": "Alexander Volkanovski" },
  "middleweight":      { "fighter_id": "...", "fighter_name": "Khamzat Chimaev" },
  "flyweight":         { "fighter_id": "...", "fighter_name": "Joshua Van" },
  "light heavyweight": { "fighter_id": "...", "fighter_name": "Carlos Ulberg" },
  "bantamweight":      { "fighter_id": "...", "fighter_name": "Petr Yan" }
}
```

### `simulation_{division}_top5.json`

```json
{
  "champion": "Tom Aspinall",
  "matchups": [
    {
      "fighter_a_id": "...",
      "fighter_b_id": "...",
      "fighter_a_name": "Tom Aspinall",
      "fighter_b_name": "Curtis Blaydes",
      "probability_a": 0.74,
      "probability_b": 0.26,
      "fighter_a_wins": 738,
      "fighter_b_wins": 262,
      "method_breakdown": { "KO/TKO": 0.52, "SUB": 0.14, "DEC": 0.34 },
      "round_distribution": { "1": 0.38, "2": 0.29, "3": 0.21, "4": 0.07, "5": 0.05 },
      "most_likely_outcome": "Tom Aspinall wins by KO/TKO in Round 1 (38%)",
      "simulations": 1000
    }
  ]
}
```

---

## Validation Results

80/20 chronological train/test split. Baseline = 50% (coin flip).

| Division | Overall accuracy | Accuracy (≥3 fights) | vs baseline |
|---|---|---|---|
| Heavyweight | ~62% | ~58% | +12% |
| Light Heavyweight | 60.1% | 51.0% | +10.1% |
| Middleweight | ~60% | ~55% | +10% |
| Welterweight | ~61% | ~56% | +11% |
| Lightweight | ~62% | ~57% | +12% |
| Featherweight | ~60% | ~54% | +10% |
| Bantamweight | 56.2% | 45.2% | +6.2% |
| Flyweight | ~59% | ~52% | +9% |

**Note on Bantamweight:** The 45.2% accuracy on experienced fighters (≥3 fights) is below baseline. This division has historically higher upset rates and more stylistic mismatches that ELO alone does not capture. The division K-multiplier (0.90) may warrant tuning.

The "accuracy drops when filtering to ≥3 fights" pattern seen across all divisions is expected — debut fighters are easy to model (any record is predictive) while established fighters are closer to parity.

---

## Champion System

Champions are stored in `data/champions.json` (manually maintained). The champion is always displayed at rank #1 in their division regardless of their numerical ELO. This decouples the political reality (belt ownership) from the algorithmic ranking.

When a belt changes hands:

1. Find the new champion's `fighter_id` in `data/rankings_{division}.json`
2. Update **both** `fighter_id` and `fighter_name` in `data/champions.json`
3. Restart or reload the Streamlit app

The system matches champions using `fighter_id`. A name mismatch is cosmetic. A wrong `fighter_id` will badge the wrong fighter.

---

## Cross-Division Deduplication

A fighter who has competed in multiple divisions (e.g. a champion who moved up) appears in **only one division** in the rankings — the one where their current ELO is highest. Champions are always locked to their designated division from `champions.json` regardless.

**ELO carry-over:** When a fighter moves to a new division, their best ELO across all prior divisions is used as their displayed ELO in the new division. This prevents a top-tier fighter from appearing artificially low just because they have only a few fights in the new weight class.

Implementation in `build_ranking_response`:
1. Build a cross-division index `{fighter_id: (max_elo, primary_division)}` by scanning all 8 division ranking files.
2. For each division being rendered, filter out fighters whose primary division is elsewhere.
3. Inject the fighter's max ELO (from any division) into the displayed record.

---

## Retired Fighter Overrides

Some fighters remain active by fight date but are retired or inactive. Override in `data/retired_overrides.json`:

```json
{
  "fighter_id_here": true
}
```

Retired fighters are excluded from active rankings and matchmaking. The `set_fighter_retired()` function in `data_loader.py` persists changes to this file.

---

## Updating the Data

To refresh a single division after new UFC events:

```bash
# Re-scrape (adds new fights to the existing CSV)
python scraper/scraper.py --division heavyweight --output data

# Re-run ELO engine
python models/elo_engine.py --division heavyweight --output data

# Re-validate (optional)
python -m models.validate --division heavyweight

# Regenerate simulations and matchmaking
python scripts/generate_simulations.py
```

To update only fight stats for existing records (title fight fix, method fix) without re-scraping the full event list:

```bash
python scraper/scraper.py --division heavyweight --output data --refresh-stats
```
