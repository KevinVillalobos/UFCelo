# UFCelo.gg

Independent ELO-based ranking and prediction system for all 8 UFC men's divisions. Built entirely from raw fight data scraped from UFCStats.com, processed through a custom multi-factor ELO engine with 7-dimensional skill scoring, and served through a modern web frontend with ranking, prediction, simulation, matchmaking, and pound-for-pound tools.

**Live site:** [ufcelo.gg](https://ufcelo.gg)

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Tech Stack](#tech-stack)
3. [Data Pipeline](#data-pipeline)
4. [Scraper](#scraper)
5. [ELO Engine](#elo-engine)
6. [Skill Scoring Engine](#skill-scoring-engine)
7. [Validation Framework](#validation-framework)
8. [Backend API](#backend-api)
9. [Frontend Pages](#frontend-pages)
10. [Deployment (Vercel)](#deployment-vercel)
11. [Data Schemas](#data-schemas)
12. [Validation Results](#validation-results)
13. [Champion System](#champion-system)
14. [Cross-Division Deduplication](#cross-division-deduplication)
15. [Updating the Data](#updating-the-data)

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
backend/                              ← FastAPI application
  main.py          ← REST API endpoints + visit counter (Vercel KV)
  data_loader.py   ← JSON/CSV file access layer
  services.py      ← rankings, prediction, simulation, matchmaking logic
  stats.py         ← per-fighter fight statistics aggregation
  schemas.py       ← Pydantic v2 response models
     │
     ▼
api/index.py                          ← Vercel serverless entrypoint (ASGI wrapper)
     │
     ▼
public/                               ← Static HTML/CSS/JS frontend
  index.html       ← Home: division cards + quick predictor
  rankings.html    ← Full ELO table per division
  fighter.html     ← Fighter profile: ELO history, stats, skill breakdown
  predict.html     ← Head-to-head prediction + ELO simulator
  simulate.html    ← Monte Carlo fight simulation
  matchmaking.html ← Best matchups by competitiveness + style contrast
  p4p.html         ← Pound-for-pound rankings (current + historical)
  app.js           ← Shared nav, visit counter, API helpers
  style.css        ← Global dark theme CSS
```

---

## Tech Stack

| Layer | Library / Tool |
|-------|---------------|
| Scraping | `requests`, `beautifulsoup4` |
| Data | Python stdlib (`csv`, `json`) |
| ELO Engine | Pure Python (no ML frameworks) |
| Backend | `FastAPI`, `Pydantic v2`, `uvicorn` |
| Frontend | Vanilla JS + HTML/CSS, `Plotly.js` |
| Hosting | Vercel (serverless + static) |
| Visit counter | Vercel KV (Upstash Redis) |

No relational database. All ranking/history state lives in flat JSON/CSV files committed to the repo.

---

## Data Pipeline

### Install dependencies

```bash
pip install fastapi uvicorn python-dateutil requests beautifulsoup4
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
# ... (all 8 divisions)

# 3. Validate (optional)
python -m models.validate --division heavyweight

# 4. Pre-generate simulations and matchmaking
python scripts/generate_simulations.py

# 5. Run backend locally
uvicorn backend.main:app --reload

# 6. Open frontend
# Navigate to http://localhost:8000 or open public/index.html
```

Scraper logs: `data/scrape_{division}.log` / `data/scrape_{division}_err.log`.

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
3. **Per-fight stats** — only fetched for the target division (saves ~80% of HTTP requests). Parses the fight detail page which contains two HTML table types: "Totals" and "Significant Strikes by Position".

All HTTP calls use a Chrome user-agent, 1.5s polite delay, and 3 retries with exponential backoff.

### Division Filtering

Each scraper invocation targets one division via `--division`. A regex filter excludes fights that match similar weight class names. For example, `heavyweight` scraping excludes rows matching `(?i)light\s+heavyweight` and `(?i)women`.

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

| Raw string | Normalized |
|------------|-----------|
| KO, TKO | `KO/TKO` |
| Submission | `SUB` |
| Unanimous Decision | `DEC U` |
| Split Decision | `DEC S` |
| Majority Decision | `DEC M` |
| Everything else | `OTHER` |

### Title Fight Detection

Detected from the individual fight detail page via CSS selector `.b-fight-details__fight-head`. If that element's text contains "Title Bout", `is_title_fight = True`.

### CSV Output

`data/fights_{division}.csv` — 35 columns:

| Column group | Columns |
|---|---|
| Event metadata | `fight_id`, `event_id`, `event_name`, `event_date` |
| Fighters | `fighter_a_id`, `fighter_a_name`, `fighter_b_id`, `fighter_b_name` |
| Result | `winner_id`, `method`, `round`, `time`, `weight_class`, `is_title_fight` |
| Fighter A stats | `a_strikes_landed/attempted`, `a_head/body/leg_strikes_landed/attempted`, `a_td_landed/attempted`, `a_knockdowns`, `a_control_time`, `a_sub_attempts`, `a_reversals` |
| Fighter B stats | (same 14 columns, `b_` prefix) |

---

## ELO Engine

**File:** `models/elo_engine.py`
**Run:** `python models/elo_engine.py --division <div> --output data`

The engine processes all fights in chronological order and maintains a live ELO rating per fighter. Core formula:

```
new_elo = old_elo + K × W × (S - E)
```

Where:
- `K` = effective K-factor (variable, see below)
- `W` = fight weight multiplier (finish type + title fight)
- `S` = actual score (1.0 win, 0.5 draw, 0.0 loss)
- `E` = expected score from current ELO difference

### Initial ELO

Fighters enter the system with a non-neutral starting ELO based on their pre-UFC record:

```python
initial_elo = 1500 + (win_rate - 0.5) * 400
# Clamped to [1300, 1700]
```

### Expected Score

Standard ELO formula with a hard clamp on the ELO difference to prevent extreme probabilities:

```python
diff = max(-250, min(250, elo_a - elo_b))
E_a = 1.0 / (1.0 + 10 ** (-diff / 400))
```

The ±250 clamp caps win probability at ~82% regardless of ELO gap.

### K-Factor

K is variable by fight count, then multiplied by a per-division constant:

**Base K by fight count:**

| Fights | Raw K |
|--------|-------|
| 1–4    | 64    |
| 5–14   | 32    |
| 15+    | 20    |

**Per-division multiplier:**

| Division | Multiplier |
|----------|-----------|
| Heavyweight | 1.00 |
| Light Heavyweight | 0.95 |
| Middleweight | 0.90 |
| Bantamweight | 0.90 |
| Flyweight | 0.90 |
| Lightweight | 0.85 |
| Featherweight | 0.85 |
| Welterweight | 0.75 |

### Multi-Factor K Adjustment

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

| Opponent rank | Win modifier | Loss modifier |
|--------------|-------------|--------------|
| Top 5 | +0.10 | -0.05 |
| Top 6–10 | +0.05 | 0.00 |
| Bottom 5 | -0.05 | -0.10 |
| Other | 0.00 | 0.00 |

Floor: 0.70.

#### 3. Streak Multiplier (`S_streak`)

| Streak | Multiplier |
|--------|-----------|
| Win streak ≥ 8 | 1.35 |
| Win streak ≥ 5 | 1.25 |
| Win streak ≥ 3 | 1.15 |
| Neutral | 1.00 |
| Loss streak ≤ -3 | 1.25 |
| Loss streak ≤ -5 | 1.40 |
| Loss streak ≤ -8 | 1.55 |

#### 4. Rematch Multiplier (`R_rematch`)

| Fight instance | Multiplier |
|---------------|-----------|
| First fight | 1.00 |
| 2nd fight, same winner | 1.20 |
| 2nd fight, result reversed | 0.70 |
| 3rd fight or more | 0.50 |

#### 5. Opponent Momentum (`M_momentum`)

| Opponent streak | Multiplier |
|----------------|-----------|
| Win streak ≥ 3 | 1.15 |
| Loss streak ≤ -3 | 0.90 |
| Neutral | 1.00 |

#### 6. Time Percentage (`T_time`)

| Finish timing | Win mult | Loss mult |
|---|---|---|
| < 30% of scheduled time | 1.15 | 0.90 |
| > 80% of scheduled time | 0.90 | 0.85 |
| 30–80% | 1.00 | 1.00 |

#### 7. Division Change Penalty (`D_division`)

When a fighter competes in a new division, their effective ELO for win probability calculation is discounted:

```python
effective_elo = raw_elo - (raw_elo - 1500) * 0.15
```

Stored ELO is unchanged; this only adjusts the expected score for that fight.

### Peak ELO Degradation Penalty

If a fighter is on a loss streak ≤ -3 AND their current ELO has fallen below 85% of their career peak:

```python
if elo < peak_elo * 0.85 and streak <= -3:
    delta *= 1.20
```

This accelerates decline for aging, formerly elite fighters ("the Usman problem").

### ELO Floor/Ceiling Guards

- Beating an opponent with ELO < 1300: gains capped at +8.0
- Losing to an opponent with ELO > 1700: minimum loss of -12.0

### Inactivity Decay

Applied at output time only (display-only, not stored in fight history):

```python
months_inactive = (today - last_fight_date).days / 30.44
months_capped = min(months_inactive - 18, 24)   # grace period: 18 months

if months_inactive > 18:
    decay_rate = 0.005   # 0.5% per month toward 1500
    if streak <= -3:
        decay_rate *= 1.30
    displayed_elo = raw_elo - (raw_elo - 1500) * decay_rate * months_capped
```

### Peak ELO Tracking

The engine tracks per-fighter:
- `peak_elos[fighter_id]`: highest raw ELO ever recorded
- `peak_elo_dates[fighter_id]`: date of that fight
- `peak_elo_opponents[fighter_id]`: opponent name when peak was set

Recorded before inactivity decay so it represents the true career-best rating.

### Per-Fight ELO Breakdown

Every entry in `elo_histories_{division}.json` includes a `breakdown` dict with 18 fields covering every multiplier that produced the final ELO delta:

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

This powers the per-fight expandable K-factor breakdown in the Fighter Profile page.

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

Separate from ELO, the skill engine builds a multi-dimensional fighter profile from raw fight stats. It runs in the same chronological pass as the ELO engine.

### 7 Dimensions

| Internal key | Display label | Composite weight |
|---|---|---|
| `Striking` | Striking | 20% |
| `Defensa` | Defense | 20% |
| `Grappling` | Grappling | 15% |
| `Consistencia` | Consistency | 15% |
| `Finish Rate` | Finish Rate | 10% |
| `Cardio/Durabilidad` | Cardio / Durability | 10% |
| `Presión` | Pressure | 10% |

All dimensions are 0–100 floats. Internal keys match the JSON data files; display labels are used in the UI.

### Exponential Moving Average

Each fight updates skills with EMA smoothing (α = 0.80):

```python
new_score[dim] = current[dim] * 0.80 + raw_score[dim] * 0.20
```

New fights have limited influence on established fighters; early fights shape a fighter faster.

### Raw Score Calculation

**Striking:**
```python
accuracy = strikes_landed / strikes_attempted
volume   = strikes_landed / (rounds * 5 * 5.0)   # baseline 5 spm
raw = min(1.0, (accuracy * 0.6 + volume * 0.4) * 1.2)
```

**Grappling:**
```python
td_acc = td_landed / td_attempted
td_def = 1 - opp_td_landed / opp_td_attempted
raw = min(1.0, (td_acc * 0.7 + td_def * 0.3) * 1.1)
```

**Defense:**
```python
td_def     = 1 - opp_td_landed / opp_td_attempted
strike_def = 1 - opp_strikes_landed / opp_strikes_attempted
raw = td_def * 0.8 + strike_def * 0.2
```

**Consistency:** Average strike accuracy across head, body, and leg zones.

**Finish Rate:** 1.0 if won by KO/TKO or SUB, 0.3 otherwise.

**Cardio:**
```python
raw = 0.8 + (round - 1) * 0.1   # later round = better cardio proxy
```

**Pressure:**
```python
control_ratio = control_seconds / (round * 300)
striking_vol  = strikes_landed / (rounds * 5 * 5.0)
raw = control_ratio * 0.7 + striking_vol * 0.3
```

### Post-Calculation Adjustments

Method bonuses (applied to winner's raw scores before EMA):

| Method | Dimension | Multiplier |
|--------|-----------|-----------|
| KO/TKO | Striking | ×1.30 |
| KO/TKO | Finish Rate | = 1.00 |
| SUB | Grappling | ×1.30 |
| SUB | Finish Rate | = 1.00 |
| DEC (win) | Consistency | ×1.20 |
| DEC (win) | Cardio | ×1.20 |
| DEC (win) | Pressure | ×1.10 |

Outcome penalties (applied to all dimensions on loss):

| Opponent method | Penalty |
|----------------|---------|
| KO/TKO | ×0.75 |
| SUB | ×0.80 |
| DEC | ×0.90 |
| Draw | ×0.95 |

Additional bonuses: title fight → +4 pts across all dimensions; R1–R2 finish → +3 pts.

### Fallback (no stats)

When fight stats are unavailable, synthetic scores are assigned from method alone:

| Method | Striking | Grappling | Defense | Finish Rate |
|--------|----------|-----------|---------|-------------|
| KO/TKO win | 0.80 | 0.40 | 0.50 | 1.00 |
| SUB win | 0.40 | 0.80 | 0.60 | 1.00 |
| DEC win | 0.60 | 0.60 | 0.70 | 0.30 |
| Loss | 0.45 | 0.45 | 0.45 | 0.20 |

---

## Validation Framework

**File:** `models/validate.py`
**Run:** `python -m models.validate --division <div>`

1. Load all fights for the division, sort chronologically.
2. Split 80% train / 20% test (chronological — no shuffling to prevent data leakage).
3. Run the ELO engine on training fights only.
4. For each test fight, compute `P(A wins)` from ELO ratings.
5. Predict winner = fighter with P > 0.50.
6. Compare to actual outcome.

Report breaks accuracy down by ELO difference band (clear favorite / competitive / coin-flip), method, streak context, and experience filter (≥3 prior fights).

Output: `data/validation_report_{division}.json` + Unicode box display to stdout.

---

## Backend API

**File:** `backend/main.py`
**Local:** `uvicorn backend.main:app --reload`
**Production:** Vercel serverless via `api/index.py`

All endpoints are prefixed `/api/` in production (e.g., `/api/rankings/heavyweight`).

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/rankings/{division}` | Active ELO rankings for a division |
| `GET` | `/rankings/{division}/alltime` | All-time rankings sorted by peak ELO |
| `GET` | `/fighter/{fighter_id}` | Full fighter profile |
| `GET` | `/predict` | Head-to-head prediction (`?fighter_a=&fighter_b=&division=`) |
| `GET` | `/events/upcoming` | Upcoming events with ELO-based predictions |
| `GET` | `/matchmaking/{division}` | Best matchups (`?top_n=15`) |
| `GET` | `/simulator-data` | Raw K-factor state for both fighters (for frontend simulator) |
| `GET` | `/simulate` | Monte Carlo simulation (`?fighter_a=&fighter_b=&simulations=1000`) |
| `PATCH` | `/fighter/{fighter_id}/retire` | Toggle retired status |
| `GET` | `/visits` | Get global visit count |
| `POST` | `/visits` | Increment and return global visit count |

### `backend/data_loader.py`

Pure file I/O with caching and legacy fallbacks.

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

**Division slug normalization:** `"light heavyweight"` → `"light_heavyweight"`.

### `backend/services.py`

#### `build_ranking_response(division, alltime)`

1. Load raw rankings.
2. Build a cross-division ELO index: scan all 8 divisions, record `{fighter_id: max_elo_seen}`.
3. Determine each fighter's primary division (where their ELO is highest).
4. Deduplicate: show each fighter only in their primary division.
5. Apply champion lock: champion from `champions.json` is always pinned to rank 1.
6. Apply ELO carry-over: use the fighter's best ELO across all divisions.
7. Filter retired fighters via `retired_overrides.json`.

#### `build_prediction(fighter_a_id, fighter_b_id, division)`

**Step 1 — ELO probability:**
```python
diff = max(-250, min(250, elo_a - elo_b))
p_elo = 1.0 / (1.0 + 10 ** (-diff / 400))
```

**Step 2 — Skill blend:**
```python
skill_adj = (composite_a - composite_b) / 100 * 0.10   # max ±10%
p_final = max(0.05, min(0.95, p_elo + skill_adj))
```

**Step 3 — Method prediction:** from the favored fighter's Striking/Grappling/Finish Rate scores.

#### `build_matchmaking(division, top_n)`

```python
competitiveness = max(0, 1.0 - elo_diff / 200)
style_contrast  = mean(|skill_a[dim] - skill_b[dim]| for all dims) / 100
matchup_score   = 0.70 * competitiveness + 0.30 * style_contrast
```

Filters: active within 2 years, ELO diff ≤ 300, no rematches within 2 years. Default pool: top 15 fighters.

#### `build_fight_simulation(fighter_a_id, fighter_b_id, n_trials)`

Monte Carlo (default 1000 trials). Per trial: winner via ELO probability, method via weighted KO/SUB/DEC draw from skill scores, round via method-specific distribution. Aggregates win %, method %, round distribution.

### Visit Counter

The global visit counter uses Vercel KV (Upstash Redis) when the `KV_REST_API_URL` and `KV_REST_API_TOKEN` environment variables are set. Falls back to a local file for development. The `POST /visits` endpoint uses an atomic `INCR` so concurrent requests don't cause race conditions.

### `backend/schemas.py`

Pydantic v2 models define the exact shape of every API response. Key models:

- **`RankingEntry`** — `fighter_id`, `fighter_name`, `elo`, `peak_elo`, `peak_elo_date`, `peak_elo_opponent`, `record`, `fight_count`, `last_fight_date`, `streak`, `is_champion`
- **`FighterProfile`** — full profile including `elo_history`, `skill_score`, `fight_stats`, physical attributes (`height_inches`, `reach_inches`, `weight_lbs`)
- **`EloHistoryPoint`** — `date`, `opponent_name`, `result`, `elo`, `elo_change`, `method`, `round`, `is_title_fight`, `event`, `breakdown`
- **`EloBreakdown`** — all 18 K-factor fields
- **`FightStats`** — aggregated career striking/grappling stats including `head_pct`, `body_pct`, `leg_pct` for the body heatmap
- **`PredictionResult`** — `probability_a/b`, `method_prediction`, `key_advantage`, `skill_comparison`
- **`MatchupEntry`** — `matchup_score`, `competitiveness_score`, `skill_contrast_score`, `key_dimension`, `probability_a/b`

> **Important (Pydantic v2):** Field names must not shadow module-level type imports. The date type is imported as `from datetime import date as _Date` to prevent the `get_type_hints()` resolver from finding the field default (None) instead of the imported type — which would cause a `none_required` 500 error on all date fields.

---

## Frontend Pages

The frontend is plain HTML/CSS/JS with no framework. All pages share:
- `app.js` — navbar injection, API helpers, visit counter
- `style.css` — global dark theme
- `Plotly.js` (CDN) — all charts

### Home (`index.html`)

- Grid of 8 division cards showing top 15 fighters per division (ELO, streak badge, champion crown)
- Global visit counter displayed in nav and on page (backed by Vercel KV)
- Quick predictor: select division + two fighters → live horizontal probability bar + predicted method
- Expandable ELO explanation section

### Rankings (`rankings.html`)

- Full division ELO table: Rank, Fighter, ELO, Peak ELO, Peak Opponent, Record, Fights, Last Fight, Streak
- Active / All-Time toggle:
  - **Active** — fighters who have competed within 2 years, sorted by current ELO
  - **All-Time** — every fighter who ever competed in the division, sorted by peak ELO
- Division stats sidebar: mean ELO, median, std dev, spread

### Fighter Profile (`fighter.html`)

- Fighter selector with division picker
- **Active / Retired toggle** — when "Show retired" is on, loads the alltime endpoint (316+ fighters including retired legends) and marks retired fighters with a RETIRED badge
- Current ELO, peak ELO, career record, division rank, current streak
- ELO history line chart (color-coded W/L/D fight markers) with Plotly
- Skill radar chart (7 dimensions) + composite score badge
- **Skill breakdown panel** — sorted bar chart with strongest/weakest highlights, weight %, tier labels (Elite / Above avg / Average / Below avg), and per-dimension tooltips
- **Body hit-zone heatmap** — SVG silhouette with head/torso/leg colored by target percentage:
  - Green: < 20% of strikes to that zone
  - Amber: 20–40%
  - Red: > 40%
- **Fight statistics panel** — striking (sig. strikes/min, accuracy, defense) and grappling (TD/min, accuracy, defense, control %, sub attempts)
- **Full fight history table** — all fights at a glance: date, event, opponent, method, round, ELO before/after, delta
- **Expandable fight rows** — click any fight to reveal:
  1. **Multiplier Breakdown** — full K-factor grid (K base, K division, K experience, K streak, K effective, expected probability, surprise factor, method mult, title mult, consecutive mult, calculated delta, final delta)
  2. **Insight** — natural language summary of the result (e.g., "Upset — won as underdog (32% expected), earned much more ELO.")
  3. **ELO projection vs nearby rivals** — table showing projected ELO after Win (KO), Lose (KO), Win (DEC), Lose (DEC) against the 5 nearest-ranked opponents

### Predictor (`predict.html`)

- Fighter A vs Fighter B selector per division
- Horizontal probability bar (ELO + skill blended)
- Win probability %, ELO edge, predicted method, key skill advantage
- Proportional SVG silhouette comparison with height/reach difference badges
- Overlaid dual skill radar + per-dimension advantage table
- Fight statistics comparison (methods %, striking, grappling, body target heatmaps)
- **ELO Simulator** — pick outcome method, round, and title-fight toggle to compute exact ELO deltas mirroring the engine formula:
  - Shows ELO before/after for both fighters
  - Expandable K-factor breakdown for the selected scenario
  - Insight text (upset detection, streaks, early finish, peak penalty)
- Model explanation expander

### Simulator (`simulate.html`)

- Configurable trial count (100–10,000)
- Win distribution donut chart
- Method breakdown bar chart (KO/TKO / SUB / DEC)
- Finishing round distribution (separate series per method)
- Most likely outcome headline
- Methodology explanation expander

### Matchmaking (`matchmaking.html`)

- Pool size: Top 10 / Top 15 (default) / Top 20
- Sortable matchup table: Fighter A, Fighter B, ELO A/B, ELO diff, Competitiveness %, Style Contrast %, Score, Key dimension, Win odds
- Click any row to see detail:
  - Win probability bar for selected matchup
  - Three gauge charts: Competitiveness, Style Contrast, Total Score
- **Matchup Landscape scatter chart** — X = Competitiveness, Y = Style Contrast; top-right corner = ideal matchup; click any point to select it
- Matchmaking score formula explainer (collapsible)

### Pound-for-Pound (`p4p.html`)

- **Current Rankings mode** — cross-division ranking by Raw ELO or Normalized (z-score relative to divisional mean/std dev). Adjustable Top N (10–150).
  - Bar chart: top 10 P4P fighters by chosen metric
  - Table: rank, fighter, division, ELO, z-score, peak ELO, record
  - ELO distribution box plot per division
  - Divisional stats table: active fighter count, mean ELO, std dev, coefficient of variation
- **Historical Peak ELO mode** — loads all-time rankings for all 8 divisions simultaneously, deduplicates by fighter (keeping highest peak across all divisions they competed in), and ranks across eras
  - Bar chart: top 10 all-time peak ELO
  - Table: rank, fighter, division, peak ELO, peak date, opponent at peak, current ELO

---

## Deployment (Vercel)

The project is deployed as a single Vercel project with two components:

**Static frontend** — `public/` is served as static files. Vercel automatically serves `public/index.html` at `/`, `public/rankings.html` at `/rankings.html`, etc.

**Serverless backend** — `api/index.py` is the single serverless function entry point. `vercel.json` rewrites all `/api/*` requests to it. The function strips the `/api` prefix before forwarding to FastAPI.

```json
{
  "version": 2,
  "functions": {
    "api/index.py": { "maxDuration": 30 }
  },
  "rewrites": [
    { "source": "/api/:path*", "destination": "/api/index.py" }
  ]
}
```

### Environment Variables (Vercel Dashboard)

| Variable | Purpose |
|----------|---------|
| `KV_REST_API_URL` | Upstash Redis REST URL (auto-set when KV store is linked) |
| `KV_REST_API_TOKEN` | Upstash Redis token (auto-set when KV store is linked) |

### Setting up the Visit Counter (Vercel KV)

1. Vercel Dashboard → your project → **Storage** tab
2. **Create Database** → **KV**
3. Name it anything, click **Create**
4. **Connect to Project** → select the project → **Connect**
5. Vercel auto-injects the env vars and triggers a redeploy

The counter is globally shared across all users, persists indefinitely, and uses atomic Redis `INCR` to avoid race conditions.

### Vercel Constraints

- `data/` and all committed files are **read-only** on the serverless runtime
- `/tmp/` is writable but resets on cold starts — not suitable for persistent state
- All ranking/history data is pre-generated and committed; the backend only reads it
- Only the visit counter requires write access — handled by Vercel KV

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
    "streak": 7,
    "is_champion": true
  }
]
```

`rankings_{division}_alltime.json` adds `"alltime_rank": 1` and includes retired fighters.

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
      "elo_change": 18.7,
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
  "lightweight":       { "fighter_id": "...", "fighter_name": "Islam Makhachev" },
  "welterweight":      { "fighter_id": "...", "fighter_name": "Jack Della Maddalena" },
  "featherweight":     { "fighter_id": "...", "fighter_name": "Ilia Topuria" },
  "middleweight":      { "fighter_id": "...", "fighter_name": "Dricus du Plessis" },
  "flyweight":         { "fighter_id": "...", "fighter_name": "Alexandre Pantoja" },
  "light heavyweight": { "fighter_id": "...", "fighter_name": "Aleksandar Rakic" },
  "bantamweight":      { "fighter_id": "...", "fighter_name": "Merab Dvalishvili" }
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

**Note on Bantamweight:** The 45.2% accuracy on experienced fighters is below baseline. This division has historically higher upset rates. The division K-multiplier (0.90) may warrant tuning.

The "accuracy drops when filtering to ≥3 fights" pattern is expected — debut fighters are easy to predict while established fighters trend toward parity.

---

## Champion System

Champions are stored in `data/champions.json` (manually maintained). The champion is always displayed at rank #1 regardless of their numerical ELO. This decouples belt ownership from the algorithmic ranking.

When a belt changes hands:

1. Find the new champion's `fighter_id` in `data/rankings_{division}.json`
2. Update **both** `fighter_id` and `fighter_name` in `data/champions.json`
3. Redeploy (or run the backend locally and reload)

---

## Cross-Division Deduplication

A fighter who has competed in multiple divisions appears in **only one division** — the one where their current ELO is highest. Champions are always locked to their designated division.

**ELO carry-over:** A fighter moving to a new division uses their best ELO across all prior divisions as their displayed rating, preventing an artificially deflated ranking due to few fights at the new weight.

Implementation in `build_ranking_response`:
1. Build `{fighter_id: (max_elo, primary_division)}` by scanning all 8 division files.
2. For each division, filter out fighters whose primary division is elsewhere.
3. Inject the fighter's max ELO into the displayed record.

---

## Retired Fighter Overrides

Some fighters remain active by fight date but are effectively retired. Override in `data/retired_overrides.json`:

```json
{ "fighter_id_here": true }
```

Retired fighters are excluded from active rankings and matchmaking. The Fighter Profile page has a **Show retired** toggle that loads the alltime endpoint to include them for historical comparison. `set_fighter_retired()` in `data_loader.py` persists changes to this file.

---

## Updating the Data

To refresh a single division after new UFC events:

```bash
# Re-scrape (adds new fights)
python scraper/scraper.py --division heavyweight --output data

# Re-run ELO engine
python models/elo_engine.py --division heavyweight --output data

# Validate (optional)
python -m models.validate --division heavyweight

# Regenerate simulations and matchmaking
python scripts/generate_simulations.py

# Commit and push — Vercel auto-deploys
git add data/ && git commit -m "Update heavyweight data" && git push
```

To update only fight stats for existing records (title fight fix, method correction):

```bash
python scraper/scraper.py --division heavyweight --output data --refresh-stats
```
