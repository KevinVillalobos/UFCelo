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
10. [Deployment (Docker)](#deployment-docker)
11. [Data Schemas](#data-schemas)
12. [Validation Results](#validation-results)
13. [Champion System](#champion-system)
14. [One ELO per Fighter](#one-elo-per-fighter)
15. [Official UFC Rankings](#official-ufc-rankings)
16. [Design System, Search & Navigation](#design-system-search--navigation)
17. [Recent Changes](#recent-changes)
18. [Updating the Data](#updating-the-data)

---

## Architecture Overview

```
ufcstats.com
     │
     ▼
scraper/scraper.py
     │  (per division)
     ▼
data/fights_{division}.csv          ← fight records + per-fight stats (both fighters)
data/fighters_{division}.json       ← fighter profiles (bio, record, physique)
     │
     ▼
models/elo_engine.py
     │  (ONE pass over all 8 divisions, chronological → one ELO per fighter)
     ├─► data/rankings_{division}.json          ← active ELO rankings (fighter listed in their current division)
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
backend/                              ← FastAPI application
  main.py          ← REST API endpoints + visit counter (Upstash Redis / local file)
  ufc_rankings.py  ← official UFC top 15 + champions, synced from ufc.com every 6 h
  data_loader.py   ← JSON/CSV file access layer
  services.py      ← rankings, prediction, simulation, matchmaking, per-fight stats
  stats.py         ← career aggregate fight statistics (strikes, TDs, control)
  schemas.py       ← Pydantic v2 response models
     │
     ▼
public/                               ← Static HTML/CSS/JS frontend
  index.html        ← Home: division cards (top 15) + ELO vs official UFC comparison
  rankings.html     ← Full ELO table per division + official UFC top 15 view
  fighter.html      ← Fighter profile: ELO history, stats, skill breakdown, per-fight stats
  comparison.html   ← Head-to-head comparison + ELO simulator + Monte Carlo simulation
  matchmaking.html  ← Best matchups by competitiveness + style contrast
  p4p.html          ← Pound-for-pound rankings (current + historical)
  app.js            ← Shared nav, global fighter search (Fuse.js), trend badges, API helpers, visit counter
  style.css         ← Design tokens + dark theme + fully responsive CSS
nginx.conf / nginx/Dockerfile          ← Static hosting + /api proxy for the Docker deployment
docker-compose.yml / Dockerfile        ← backend + nginx containers
```

---

## Tech Stack

| Layer | Library / Tool |
|-------|---------------|
| Scraping | `requests`, `beautifulsoup4` |
| Data | Python stdlib (`csv`, `json`) |
| ELO Engine | Pure Python (no ML frameworks) |
| Backend | `FastAPI`, `Pydantic v2`, `uvicorn` |
| Frontend | Vanilla JS + HTML/CSS, `Plotly.js`, `Fuse.js` (search), Bebas Neue + Inter (Google Fonts) |
| Hosting | Docker (nginx + FastAPI) |
| Visit counter | Upstash Redis (optional, falls back to a local file) |

No relational database. All ranking/history state lives in flat JSON/CSV files committed to the repo.

---

## Data Pipeline

### Install dependencies

```bash
pip install -r requirements.txt
```

### Run the full pipeline

```bash
# 1. Scrape every division (incremental: uses data/scrape_checkpoint.json)
python scraper/scraper.py --division heavyweight --output data
python scraper/scraper.py --division "light heavyweight" --output data
# ... (all 8 divisions)

# 2. ELO + skill scores for ALL divisions in one pass (one ELO per fighter)
python models/elo_engine.py --output data

# 3. Official UFC top 15 + champions (ufc.com)
python -m backend.ufc_rankings

# 4. Validate (optional)
python -m models.validate --division heavyweight

# 5. Run backend locally
uvicorn backend.main:app --reload
```

Steps 1–3 for every division are bundled in `python scraper/run_all.py` (see [Updating the Data](#updating-the-data)).

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

`data/fights_{division}.csv` — 42 columns:

| Column group | Columns |
|---|---|
| Event metadata | `fight_id`, `event_id`, `event_name`, `event_date` |
| Fighters | `fighter_a_id`, `fighter_a_name`, `fighter_b_id`, `fighter_b_name` |
| Result | `winner_id`, `method`, `round`, `time`, `weight_class`, `is_title_fight` |
| Fighter A stats | `fighter_a_strikes_landed/attempted`, `fighter_a_head/body/leg_strikes_landed/attempted`, `fighter_a_takedowns_landed/attempted`, `fighter_a_knockdowns`, `fighter_a_control_time`, `fighter_a_submission_attempts`, `fighter_a_reversals` |
| Fighter B stats | (same 14 columns, `fighter_b_` prefix) |

**Note:** Column prefix is `fighter_a_` / `fighter_b_` (full prefix), not `a_` / `b_`. This matters for the backend's `_extract_per_fight_stats` function which explicitly uses `fighter_a_`/`fighter_b_` when building column names.

---

## ELO Engine

**File:** `models/elo_engine.py`
**Run:** `python models/elo_engine.py --output data`

The engine reads the fight CSVs of **all 8 divisions**, merges them (deduplicated by `fight_id`), sorts them chronologically and maintains **one live ELO rating per fighter**. A fighter's rating follows them across weight classes (see [One ELO per Fighter](#one-elo-per-fighter)). The `--division` flag is obsolete and ignored. Core formula:

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

How good the opponent was **at the time of the fight** scales the result. The engine is a single chronological pass, so only earlier fights are used (no look-ahead). The opponent's standing is their pre-fight ELO rank among the fighters of the fight's division who fought in the previous 2 years; the division champion is tracked through title fights (the winner of the latest title fight). With fewer than 8 active fighters in the pool the multiplier stays at 1.0.

| Opponent standing | Win modifier | Loss modifier |
|--------------|-------------|--------------|
| Champion | +0.20 | -0.10 |
| Top 3 | +0.18 | -0.08 |
| Top 4–5 | +0.15 | -0.06 |
| Top 6–10 | +0.08 | -0.03 |
| Top 11–15 | +0.03 | -0.01 |
| Bottom 5 of the pool (below 15) | -0.10 | -0.15 |
| Other (unranked) | -0.15 | -0.20 |

Multiplier = `1 + modifier`, floor 0.70. Table: `_Q_TABLE` in `models/elo_engine.py`. A draw counts as a loss modifier, as before.

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

### Legacy Decay

The ELO a fight added or removed counts less the older the fight is. The stored per-fight history (`elo_histories_*`) and the peak ELO are never changed; the decay applies to the rating the site **shows and predicts with**:

```python
def compute_legacy_decay(fight_date, today=None):
    years_since = (today - fight_date).days / 365.25
    if years_since <= 5:
        return 1.00
    return 0.95 ** (years_since - 5)          # 5% less per year after 5 years

effective_elo = initial_elo + sum(delta_i * compute_legacy_decay(date_i, today))
```

Rankings (`elo`, plus `elo_raw` = engine rating and `elo_effective` = after legacy decay, before inactivity), `/predict` and `/accuracy` all use this same effective rating (`_effective_elo` in `backend/services.py`).

### Inactivity Decay

Applied on top of the effective ELO at output time only (display-only, not stored in fight history):

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

The engine computes everything once, then writes the same 5 JSON files **per division** (each fighter appears in the division of their most recent fight; histories are split by the division each fight was fought in):

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

> `validate.py` still runs one division at a time and initialises ELO from the fighter career record, which includes results from after the test window, so its figures are optimistic. A leak-free comparison over all divisions (80/20 chronological, no record initialisation) gave **53.2%** with one unified ELO vs **52.2%** with per-division ELOs (54.1% vs 52.0% when both fighters have 3+ prior fights).

---

## Backend API

**File:** `backend/main.py`
**Local:** `uvicorn backend.main:app --reload`
**Production:** Docker (`docker compose up --build -d`); nginx proxies `/api/` to the backend

All endpoints are prefixed `/api/` in production (e.g., `/api/rankings/heavyweight`).

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/rankings/{division}` | Active ELO rankings for a division |
| `GET` | `/rankings/{division}/alltime` | All-time rankings sorted by peak ELO |
| `GET` | `/fighter/{fighter_id}` | Full fighter profile (ELO history, skill scores, career stats, per-fight stats) |
| `GET` | `/predict` | Head-to-head prediction (`?fighter_a=&fighter_b=&division=`, optional `is_title_fight` / `is_main_event` for 5-round fights). Returns `style_adjustment` and `style_reasons` |
| `GET` | `/events/upcoming` | Upcoming events with ELO-based predictions |
| `GET` | `/matchmaking/{division}` | Best matchups (`?top_n=15`) |
| `GET` | `/simulator-data` | Raw K-factor state for both fighters (for frontend ELO simulator) |
| `GET` | `/simulate` | Monte Carlo simulation (`?fighter_a=&fighter_b=&simulations=1000`) |
| `PATCH` | `/fighter/{fighter_id}/retire` | Toggle retired status |
| `GET` | `/ufc-rankings` | Official UFC top 15 for every division (+ `updated_at`) |
| `GET` | `/ufc-rankings/{division}` | Official champion + top 15 for one division |
| `GET` | `/fighter/{fighter_id}/tags` | Career tags (Iron Chin, Glass Jaw, ...), computed over the whole career |
| `GET` | `/visits` | Get global visit count (read-only) |
| `POST` | `/visits` | Increment and return global visit count. **Only the Home page calls this.** |

### `backend/data_loader.py`

Pure file I/O with caching and legacy fallbacks.

| Function | Returns |
|----------|---------|
| `load_rankings(division, alltime)` | List of ranking dicts |
| `load_skill_scores(division)` | List of skill score dicts |
| `load_fighters(division)` | Standardized fighter list |
| `load_elo_histories(division)` | `{fighter_id: [HistoryPoint]}` |
| `load_skill_histories(division)` | Skill evolution per fight |
| `load_fights_csv(division)` | `{fight_id: row_dict}` from fights CSV |
| `load_champions()` | `{division: {fighter_id, fighter_name}}` |
| `get_fighter_by_id(id, division)` | Single fighter dict |
| `get_skill_score_by_id(id, division)` | Skill dimensions dict |
| `get_upcoming_events()` | Future events from events.json |
| `set_fighter_retired(id, bool)` | Persists to retired_overrides.json |

**Division slug normalization:** `"light heavyweight"` → `"light_heavyweight"`.

### `backend/services.py`

#### `build_fighter_profile(fighter_id, division)`

1. Load fighter bio from `fighters_{division}.json`.
2. Load ELO history across **all 8 divisions** (cross-division deduplication via `fight_id`).
3. For each ELO history entry, look up the corresponding fight row from `fights_{division}.csv` and call `_extract_per_fight_stats` to attach per-fight striking/grappling data.
4. Load skill history and compute physique attributes (`height_inches`, `reach_inches`, `weight_lbs`) via `parse_physical`.
5. Call `compute_fighter_stats` (from `stats.py`) for career aggregate stats.

#### `_extract_per_fight_stats(fighter_id, row)`

Given a CSV row and a fighter ID, determines if the fighter was `fighter_a` or `fighter_b` and extracts all stats for both fighters using the `fighter_a_`/`fighter_b_` column prefix:

```python
px = "fighter_a" if row["fighter_a_id"] == fighter_id else "fighter_b"
ox = "fighter_b" if px == "fighter_a" else "fighter_a"
# Returns full striking breakdown for both fighters:
# strikes, head/body/leg breakdown, TDs, KDs, control time, sub attempts
```

Returns a `PerFightStats`-compatible dict with both the fighter's and opponent's stats.

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

Pool is **top N by rank** (not just any fighters with data). This ensures matchmaking only surfaces elite-vs-elite fights. The champion (rank 1) is always in the pool.

```python
pool = rankings[:top_n]   # top N ranked fighters only
competitiveness = max(0, 1.0 - elo_diff / 200)
style_contrast  = mean(|skill_a[dim] - skill_b[dim]| for all dims) / 100
matchup_score   = 0.70 * competitiveness + 0.30 * style_contrast
```

Filters: no rematches within 2 years. Returns all C(n,2) combinations sorted by matchup score.

#### `build_fight_simulation(fighter_a_id, fighter_b_id, n_trials)`

Monte Carlo (default 1000 trials). Per trial: winner via ELO+skill probability, method via weighted KO/SUB/DEC draw from skill scores, round via method-specific distribution. Aggregates win %, method %, round distribution.

### `backend/stats.py`

Computes career aggregate statistics for the Fighter Profile page. Reads all 8 division CSV files and de-duplicates by `fight_id` to handle cross-division fighters.

Returns per-fighter:
- Striking: sig. strikes/min, accuracy, defense, KD/fight, head/body/leg target %
- Grappling: TD/min, TD accuracy, TD defense, control %, sub attempts/fight
- Career wins/losses by method, average finish round (KO and SUB separately)
- 20-fight timeline for career trend charts

The `head_pct`, `body_pct`, `leg_pct` fields power the SVG body heatmap in the Fighter Profile.

### Visit Counter

Only landing on **Home** counts as a visit (`public/app.js` sends `POST` on Home and `GET` everywhere else; the Docker healthcheck also uses `GET`). The global visit counter uses Upstash Redis when the `KV_REST_API_URL` and `KV_REST_API_TOKEN` environment variables are set. Falls back to a local file for development. The `POST /visits` endpoint uses an atomic `INCR` so concurrent requests don't cause race conditions.

### `backend/schemas.py`

Pydantic v2 models define the exact shape of every API response. Key models:

- **`RankingEntry`** — `fighter_id`, `fighter_name`, `elo`, `peak_elo`, `peak_elo_date`, `peak_elo_opponent`, `record`, `fight_count`, `last_fight_date`, `streak`, `is_champion`, `ufc_rank` (official UFC rank: `0` = champion, `1–15`, or `null`)
- **`FighterProfile`** — full profile including `elo_history`, `skill_score`, `fight_stats` (career aggregate), physical attributes (`height_inches`, `reach_inches`, `weight_lbs`)
- **`EloHistoryPoint`** — `date`, `opponent_name`, `result`, `elo`, `elo_change`, `method`, `round`, `is_title_fight`, `event`, `breakdown`, **`fight_stats` (per-fight `PerFightStats`)**
- **`EloBreakdown`** — all 18 K-factor fields
- **`PerFightStats`** — per-fight stats for both fighter and opponent: strikes landed/attempted, head/body/leg breakdown, TDs, KDs, control seconds, sub attempts (for both sides)
- **`FightStats`** — aggregated career striking/grappling stats including `head_pct`, `body_pct`, `leg_pct` for the body heatmap
- **`PredictionResult`** — `probability_a/b`, `method_prediction`, `key_advantage`, `skill_comparison`
- **`MatchupEntry`** — `matchup_score`, `competitiveness_score`, `skill_contrast_score`, `key_dimension`, `probability_a/b`

> **Important (Pydantic v2):** Field names must not shadow module-level type imports. The date type is imported as `from datetime import date as _Date` to prevent the `get_type_hints()` resolver from finding the field default (None) instead of the imported type — which would cause a `none_required` 500 error on all date fields.

---

## Frontend Pages

The frontend is plain HTML/CSS/JS with no framework. All pages share:
- `app.js` — navbar injection (mobile hamburger, global search), trend badges, API helpers, visit counter
- `style.css` — design tokens, dark theme, fully responsive
- `Plotly.js` (CDN) — all charts

### Home (`index.html`)

- Grid of 8 division cards (top 15 each). Cards use the display font, an accent underline, a gold **#1**, a lighter band for the top 5 and a separator before #6
- Streak shown as an arrow icon + number + letter (`▲ 5W`, `▼ 3L`) with a keyboard-focusable tooltip; meaning never depends on colour alone
- **UFC Official Rankings vs ELO**: pick a division and see our ELO top 15 next to the official UFC top 15, each name tagged with where the other ranking places the fighter
- Global visit counter (counts Home visits only)
- Expandable ELO explanation section

### Rankings (`rankings.html`)

- Full division ELO table: Rank, **UFC** (official UFC rank), Fighter, ELO, Peak ELO, Peak Opponent, Record, Fights, Last Fight, Streak
- Active / All-Time / **UFC Top 15** toggle:
  - **UFC Top 15**: the official ufc.com champion + top 15 for the division (synced automatically)
  - **Active** — fighters who have competed within 2 years, sorted by current ELO
  - **All-Time** — every fighter who ever competed in the division, sorted by peak ELO
- Division stats sidebar: mean ELO, median, std dev, spread

### Fighter Profile (`fighter.html`)

- Deep links: `/peleador/<slug>?id=<fighter_id>` (served by nginx as `fighter.html`) preselects division and fighter; reached from the global search
- Fighter selector with division picker
- **Active / Retired toggle** — when "Show retired" is on, loads the alltime endpoint (316+ fighters including retired legends) and marks retired fighters with a RETIRED badge
- Current ELO, peak ELO, career record, division rank, current streak
- ELO history line chart (color-coded W/L/D fight markers) with Plotly
- Skill radar chart (7 dimensions) + composite score badge
- **Skill breakdown panel** — sorted bar chart with strongest/weakest highlights, weight %, tier labels, and per-dimension tooltips
- **Physique silhouette** — proportional SVG body figure scaled to the fighter's actual height and reach, always shown when physique data is available
- **Body hit-zone heatmap** — SVG silhouette with head/torso/leg zones colored by target percentage:
  - Green: < 20% of significant strikes to that zone
  - Amber: 20–40%
  - Red: > 40%
- **Career fight statistics** — striking (sig. strikes/min, accuracy, defense, zone breakdown) and grappling (TD/min, accuracy, defense, control %, sub attempts), sourced from `stats.py` career aggregation
- **Full fight history table** — all fights: date, opponent, method, round, ELO, delta
- **Expandable fight rows** — click any fight to reveal:
  1. **Multiplier Breakdown** — full K-factor grid (all 12 fields)
  2. **Fight Stats** — two-column fighter vs opponent comparison table:
     - Sig. Strikes (landed/attempted with accuracy %)
     - Head / Body / Leg breakdown (both sides)
     - Knockdowns (both sides)
     - Takedowns (landed/attempted with accuracy %, both sides)
     - Control time (both sides, MM:SS format)
     - Submission attempts (both sides)
  3. **Insight** — natural language summary (upset detection, favorite loss, etc.)
  4. **ELO projection vs nearby rivals** — projected ELO after Win/Lose by KO or DEC against the 5 nearest-ranked opponents

### Comparison (`comparison.html`)

Merged replacement for the former `predict.html` and `simulate.html` pages.

- Fighter A vs Fighter B selector per division
- **All-time toggle** — loads `alltime` endpoint to include retired fighters in selection
- Win probability bar (ELO + skill blended), ELO edge, predicted method, key skill advantage
- Proportional SVG silhouette comparison with height/reach difference badges
- Overlaid dual skill radar + per-dimension advantage table
- Fight statistics comparison: methods %, striking, grappling, body target heatmaps side by side
- **ELO Simulator** — pick outcome method, round, and title-fight toggle to compute exact ELO deltas:
  - Shows ELO before/after for both fighters
  - Expandable K-factor breakdown for the selected scenario
  - Insight text (upset detection, streaks, early finish, peak penalty)
- **Monte Carlo Simulation** — inline runner with configurable trial count (100–10,000), rounds (3 or 5), optional seed:
  - Win distribution donut chart
  - Method breakdown (KO/TKO, SUB, DEC) per fighter
  - Finishing round distribution chart
  - Most likely single outcome headline

### Matchmaking (`matchmaking.html`)

- Pool size: Top 10 / Top 15 (default) / Top 20 **by rank** — only elite fighters, champion always included
- Sortable matchup table: Fighter A/B, ELO A/B, ELO diff, Competitiveness, Style Contrast, Score, Key dimension, Win odds
- Click any row to see detail with win probability bar and three gauge charts
- **Matchup Landscape scatter chart** — X = Competitiveness, Y = Style Contrast; click any point to select it
- Matchmaking score formula explainer (collapsible)

### Pound-for-Pound (`p4p.html`)

- **Current Rankings mode** — cross-division ranking by Raw ELO or Normalized (z-score relative to divisional mean/std dev). Adjustable Top N (10–150).
  - Bar chart: top 10 P4P fighters by chosen metric
  - Table: rank, fighter, division, ELO, z-score, peak ELO, record
  - ELO distribution box plot per division
  - Divisional stats table: active fighter count, mean ELO, std dev, coefficient of variation
- **Historical Peak ELO mode** — loads all-time rankings for all 8 divisions, deduplicates by fighter (keeping highest peak across all divisions), ranks across eras
  - Bar chart: top 10 all-time peak ELO
  - Table: rank, fighter, division, peak ELO, peak date, opponent at peak, current ELO

### Mobile Responsiveness

All pages are fully responsive:
- **Hamburger menu** — nav links collapse to a full-width dropdown at ≤768px; tap button or outside to toggle
- **Grid collapse** — `grid-2` (chart pairs, stat cards) stacks to single column at ≤768px; `grid-3`/`grid-4` collapse at ≤768px and ≤500px respectively
- **Physique/heatmap grid** — uses `repeat(auto-fit, minmax(180px, 1fr))` so cards auto-stack on narrow screens without JS
- **Tables** — all wrapped in `overflow-x: auto` scroll containers

---

## Deployment (Docker)

```bash
docker compose up --build -d      # http://localhost
docker compose logs -f backend    # backend logs (UFC sync, errors)
docker compose down
```

- **backend**: FastAPI (`uvicorn`). `./data` is mounted as a volume, so regenerated data files are served immediately without rebuilding. Healthcheck on `GET /visits`.
- **nginx**: built from `nginx/Dockerfile` (copies `public/` and `nginx.conf` into the image). Serves the static site, proxies `/api/` to the backend, routes `/peleador/<slug>` to `fighter.html`, gzips text assets. JS/CSS/HTML are served `no-cache` (revalidated on every load, same filenames across deploys); images and fonts are cached 7 days.
- Code changes in `backend/`, `models/`, `public/` or `nginx.conf` need `docker compose up --build -d`. Data-only changes do not.
- Optional visit counter in Redis: copy `.env.example` to `.env` and fill `KV_REST_API_URL` / `KV_REST_API_TOKEN`; otherwise it falls back to `data/visits.json`.

### Environment variables

| Variable | Purpose |
|----------|---------|
| `KV_REST_API_URL` | Upstash Redis REST URL for the shared visit counter (optional) |
| `KV_REST_API_TOKEN` | Upstash Redis token (optional) |

Without them the counter falls back to `data/visits.json`, which persists because `./data` is a mounted volume.

### Data and background syncs

- `data/` is read and written by the backend. Regenerated files are picked up on the next request (JSON reads are cached by file modification time).
- The backend refreshes `data/ufc_rankings.json` + `data/champions.json` and `data/upcoming_events.json` from ufc.com on start and every 6 hours.

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
      "is_title_fight": true,
      "breakdown": { "...18 fields..." }
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
    "skill_score": {
      "Striking": 82.4, "Grappling": 74.1, "Defensa": 78.9,
      "Consistencia": 71.3, "Finish Rate": 91.0,
      "Cardio/Durabilidad": 68.5, "Presión": 83.2
    },
    "skill_composite": 78.6
  }
]
```

### `champions.json`

Auto-generated from ufc.com (do not edit by hand). An empty `fighter_id` means the champion is not in our fighter data.

```json
{
  "_comment": "Auto-synced from ufc.com/rankings by backend/ufc_rankings.py. Do not edit by hand.",
  "heavyweight": { "fighter_id": "...", "fighter_name": "..." },
  "light heavyweight": { "fighter_id": "...", "fighter_name": "..." }
}
```

### `ufc_rankings.json`

```json
{
  "updated_at": "2026-10-05T00:41:14+00:00",
  "divisions": {
    "heavyweight": {
      "champion": { "rank": 0, "fighter_name": "...", "fighter_id": "..." },
      "ranked":   [ { "rank": 1, "fighter_name": "...", "fighter_id": "..." } ]
    }
  }
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

Champions are stored in `data/champions.json` and are **synced automatically from ufc.com/rankings** (see [Official UFC Rankings](#official-ufc-rankings)). Do not edit the file by hand: it is overwritten on every sync. The champion is always displayed at rank #1 regardless of their numerical ELO. This decouples belt ownership from the algorithmic ranking.

When a belt changes hands nothing needs to be done: the next sync (backend start, then every 6 hours, or `python -m backend.ufc_rankings`) picks up the new champion. A champion whose name is not found in our fighter data gets an empty `fighter_id` and is simply not pinned.

---

## One ELO per Fighter

The rating belongs to the **fighter**, not to a division. Earlier versions ran the engine once per division and only copied a fighter's exit ELO when they first entered a new division. Fighters who moved back and forth (e.g. McGregor: featherweight, welterweight, lightweight, welterweight) ended up with parallel, diverging ratings: his 2026 loss to Holloway started from a welterweight rating (1856) that never saw his lightweight losses (1742).

Now:

1. `load_all_fights()` reads all 8 `fights_{division}.csv`, dedupes by `fight_id` and sorts chronologically.
2. A single `EloEngine` pass rates every fight. Each fight still uses its own division K multiplier (`_DIVISION_K_MULT`), taken from the fight record `division`.
3. Each fighter's **current division** is the division of their most recent fight. Rankings are written per division containing only the fighters currently there; `elo_histories_{division}.json` and `skill_*_{division}.json` contain only the fights fought in that division (the backend merges them for profiles).
4. `skill_scores.json` is also written with one global entry per fighter.

The old post-processing scripts are no longer part of the pipeline (`models/unify_rankings.py`, `models/merge_skill_scores.py`; kept for reference).

**Career tags** (`models/tag_engine.py`) follow the same principle: they aggregate the whole career across divisions. Only the comparison percentiles (e.g. *Octopus*) stay per division. This fixed, for example, Alex Pereira being tagged *Iron Chin* despite two KO losses (MW and HW).

---

## Official UFC Rankings

`backend/ufc_rankings.py` reads the official rankings from `https://www.ufc.com/rankings`:

- Divisions are taken **by position** (the page always lists P4P first, then men's flyweight to heavyweight) because ufc.com localises the division headings by IP.
- Names are matched to our fighter IDs (accent and punctuation insensitive) using the rankings and fighters files.
- Writes `data/ufc_rankings.json` (`{updated_at, divisions: {division: {champion, ranked[15]}}}`) and rewrites `data/champions.json`.
- Runs on backend startup and every 6 hours in a background thread. If the request fails or the page layout changes, the previous files are kept. The files live in the mounted `data/` volume.
- One-off sync: `python -m backend.ufc_rankings`

`ufc_rank` is added to every ranking entry returned by `/rankings/{division}` (`0` = champion, `1–15`, `null` = unranked).

---

## Design System, Search & Navigation

**Tokens** (CSS variables in `public/style.css`): background `#0a0a0a`, card `#141414`, hover `#1e1e1e`, accent red `#d20a0a` (fills) and `#ff5a52` (red text, 4.5:1 or better), up `#22c55e`, down `#ef4444`, gold `#fbbf24` (#1), text `#f5f5f5` / `#a3a3a3`. Spacing scale 4/8/12/16/24/32/48. Fonts: **Bebas Neue** for display (titles, divisions) and **Inter** for data; tabular numerals on ELO, ranks and tables.

**Applied site-wide:** headings with a red accent underline, tables (dark header, gold #1 row, lighter top 5, hover), metric cards, custom select chevron, segmented toggles, dark scrollbar, consistent alerts and Plotly font.

**Global search** (navbar, press `/` to focus): fuzzy match with Fuse.js over a fighter index built from existing API endpoints (active rankings by default; **Include retired** loads the all-time rankings). Accent-insensitive, ARIA combobox with arrow-key, Enter and Esc navigation, collapses to an icon on mobile. Results show name, division badge, record and ELO and link to `/peleador/<slug>?id=<fighter_id>`. There are no fighter photos yet (the data has none).

**Streak indicator:** arrow icon + count + W/L (`▲ 5W`), never colour alone; tooltip like *Streak: 5 wins in a row*. Rank movement is not implemented: it needs the previous ranking stored by the backend.

---

## Recent Changes

- **One ELO per fighter** across all divisions (unified engine, `--division` obsolete). McGregor pre-Holloway rating went from 1856 / 1742 (two parallel histories) to a continuous 1799.
- **Career-wide tags**: the tag engine uses every division fights (fixes false *Iron Chin*).
- **Official UFC rankings and champions** auto-synced from ufc.com; `ufc_rank` column in rankings; **UFC Top 15** view; ELO-vs-UFC comparison on Home.
- **Visit counter** counts only Home visits.
- **Style Clash** (matchup notes) added behind one shared probability function; backtest and grid search included. Measured neutral, so it is context only: shown in the UI, never applied to the percentage. See `data/improvement_log.md`.
- **Sharper Q_opponent** (champion +0.20 down to unranked -0.15, time-correct standing) and **Legacy Decay** (5% per year after 5 years) used for rankings and predictions. Pre-fight accuracy over all fights went from 62.0% to 62.6% (last 100: 66% to 69%); in-sample, so optimistic.
- **Vercel removed**: `vercel.json` and `api/index.py` are gone; Docker is the only deployment.
- **UI/UX**: design system applied everywhere, global fuzzy search, trend badges, division-card hierarchy, deep links `/peleador/<slug>`, chart axis labels no longer clipped.
- **Docker**: nginx image with the static site, healthchecks, gzip and correct cache headers; backend dependencies (`requests`, `beautifulsoup4`, `lxml`) added to `requirements.txt`.
- `scraper/run_all.py` now does: scrape 8 divisions, unified ELO, UFC rankings sync.

---

## Prediction Blend and Style Clash

Every win probability (`/predict`, `/simulate`, event cards) comes from one function, `_compute_blended_probability` in `backend/services.py`:

1. **ELO**: effective ELO gap clamped to +-250, then the logistic curve (max about 81% on ELO alone).
2. **Skill**: +-10% of the composite skill gap.
3. **Style Clash** (context only): four matchup rules (`compute_style_adjustment`): grappling vs poor defence (+-3), striking vs poor defence (+-2), cardio edge in 5-round fights (+-2), finish-rate edge (+-1.5), clamped to +-10 pp. Thresholds live in `STYLE_DEFAULTS`. Because the backtest found it neutral, `STYLE_AFFECTS_PROBABILITY = False`: the adjustment is **not** added to the probability (`style_adjustment` stays `0.0`) but the notes are returned in `style_reasons` and shown in the UI as "Style context (does not affect the %)", naming the favoured fighter.

The result is clipped to [5%, 95%]. `/simulate` uses the same probability; its random draws only sample the winner, method and round.

**Measured effect: neutral.** `python -m models.backtest_style_clash` rebuilds each past fight from earlier data only and compares with and without the adjustment; `python -m models.tune_style_clash` grid-searches all 19,683 threshold/adjustment combinations. With the defaults the adjustment moves accuracy by +0.05 pp over all fights (-0.20 pp in the 20% holdout), and no grid combination beats the defaults in the holdout under the strict selection rule, so the defaults stay and the feature is kept as explanatory context only. Details, per-division tables and the decision are in `data/improvement_log.md`. Known limitations: "Defensa" is a single defence score (rules 1 and 2 are correlated), and historically the 5-round rule only fires for title fights (card position is not in the CSVs).

---

## Retired Fighter Overrides

Some fighters remain active by fight date but are effectively retired. Override in `data/retired_overrides.json`:

```json
{ "fighter_id_here": true }
```

Retired fighters are excluded from active rankings and matchmaking. The Fighter Profile page has a **Show retired** toggle that loads the alltime endpoint to include them for historical comparison. `set_fighter_retired()` in `data_loader.py` persists changes to this file.

---

## Updating the Data

### Everything, one command

```bash
python scraper/run_all.py
```

It runs, in order: the incremental scraper for the 8 divisions (`data/scrape_checkpoint.json` skips events already scraped), the unified ELO + skill engine, and the official UFC rankings/champions sync. It takes a while because of the scraping.

Then:

```bash
# data/ is a mounted volume, so the new files are served right away.
# Rebuild only if you also changed code (backend/, models/, public/, nginx.conf):
docker compose up --build -d
```

### Pieces, when you only need one

```bash
# Re-scrape one division (adds new fights)
python scraper/scraper.py --division heavyweight --output data

# Force a full scrape of a division, ignoring the checkpoint
python scraper/scraper.py --division heavyweight --output data --deep

# Re-fetch fight stats for existing records (title fight fix, method correction)
python scraper/scraper.py --division heavyweight --output data --refresh-stats

# Recompute ELO + skills for all divisions (after any scrape or engine change)
python models/elo_engine.py --output data

# Re-sync official UFC rankings + champions
python -m backend.ufc_rankings

# Validate (optional)
python -m models.validate --division heavyweight
```
