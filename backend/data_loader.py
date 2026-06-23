import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


def load_json_file(filename: str) -> Any:
    path = DATA_DIR / filename
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _division_slug(division: str) -> str:
    return division.lower().replace(" ", "_")


def load_rankings(division: str, alltime: bool = False) -> List[Dict[str, Any]]:
    suffix = "_alltime" if alltime else ""
    filename = f"rankings_{_division_slug(division)}{suffix}.json"
    data = load_json_file(filename)
    if not data:
        return []
    return data


def load_skill_scores(division: str = "heavyweight") -> List[Dict[str, Any]]:
    data = load_json_file(f"skill_scores_{_division_slug(division)}.json")
    if data is None:
        data = load_json_file("skill_scores.json")  # legacy fallback
    if not data:
        return []
    if isinstance(data, dict):
        return [item for item in data.values() if isinstance(item, dict)]
    return data


_ALL_DIVISION_SLUGS = [
    "heavyweight", "light_heavyweight", "middleweight", "welterweight",
    "lightweight", "featherweight", "bantamweight", "flyweight",
]


def load_fighters(division: str = "heavyweight") -> List[Dict[str, Any]]:
    slug = _division_slug(division)
    data = load_json_file(f"fighters_{slug}.json")
    if not data:
        data = load_json_file("fighters.json")  # legacy fallback
    if not data:
        return []
    if isinstance(data, dict):
        fighters = []
        for fighter_id, fighter_data in data.items():
            record = {"id": fighter_id}
            record.update(fighter_data if isinstance(fighter_data, dict) else {})
            fighters.append(record)
        return fighters
    return data


def load_event_data() -> List[Dict[str, Any]]:
    data = load_json_file("events.json")
    if not data:
        return []
    return data


def load_elo_histories(division: str = "heavyweight") -> Dict[str, List[Dict[str, Any]]]:
    data = load_json_file(f"elo_histories_{_division_slug(division)}.json")
    if data is None:
        data = load_json_file("elo_histories.json")  # legacy fallback
    if not data:
        return {}
    return data


def load_skill_histories(division: str = "heavyweight") -> Dict[str, List[Dict[str, Any]]]:
    data = load_json_file(f"skill_histories_{_division_slug(division)}.json")
    if data is None:
        data = load_json_file("skill_histories.json")  # legacy fallback
    if not data:
        return {}
    return data


def get_fighter_by_id(fighter_id: str, division: str = "heavyweight") -> Optional[Dict[str, Any]]:
    fid = str(fighter_id)
    # Try the requested division first
    for fighter in load_fighters(division):
        if str(fighter.get("id")) == fid or str(fighter.get("fighter_id")) == fid:
            return fighter
    # Fall back: search every division's JSON
    for slug in _ALL_DIVISION_SLUGS:
        if slug == _division_slug(division):
            continue
        for fighter in (load_json_file(f"fighters_{slug}.json") or []):
            if str(fighter.get("fighter_id", "")) == fid:
                return fighter
    # Final fallback: global fighters.json
    for fighter in (load_json_file("fighters.json") or []):
        if str(fighter.get("fighter_id", "")) == fid or str(fighter.get("id", "")) == fid:
            return fighter
    return None


def compute_career_record(fighter_id: str) -> Optional[str]:
    """Compute W-L-D from ELO histories across all divisions (deduped by fight_id)."""
    wins = losses = draws = 0
    seen: set = set()
    fid = str(fighter_id)
    for slug in _ALL_DIVISION_SLUGS:
        hist = load_json_file(f"elo_histories_{slug}.json") or {}
        for entry in hist.get(fid, []):
            key = entry.get("fight_id") or (entry.get("date", "") + str(entry.get("opponent_id", "")))
            if key in seen:
                continue
            seen.add(key)
            result = (entry.get("result") or "").lower()
            if result == "win":
                wins += 1
            elif result == "loss":
                losses += 1
            elif result == "draw":
                draws += 1
    if wins + losses + draws == 0:
        return None
    return f"{wins}-{losses}-{draws}"


def get_career_division(fighter_id: str) -> str:
    """Return the division where the fighter has the most ELO history entries (most fights)."""
    fid = str(fighter_id)
    best_div = "heavyweight"
    best_count = 0
    for slug in _ALL_DIVISION_SLUGS:
        hist = load_json_file(f"elo_histories_{slug}.json") or {}
        count = len(hist.get(fid, []))
        if count > best_count:
            best_count = count
            best_div = slug.replace("_", " ")
    return best_div


def get_skill_score_by_id(fighter_id: str, division: str = "heavyweight") -> Optional[Dict[str, Any]]:
    fid = str(fighter_id)
    # Try requested division
    for skill in load_skill_scores(division):
        if str(skill.get("fighter_id")) == fid or str(skill.get("id")) == fid:
            return skill
    # Fall back to the division with most career fights
    career_div = get_career_division(fighter_id)
    if career_div.replace(" ", "_") != _division_slug(division):
        for skill in load_skill_scores(career_div):
            if str(skill.get("fighter_id")) == fid or str(skill.get("id")) == fid:
                return skill
    return None


def parse_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def load_champions() -> Dict[str, Dict[str, str]]:
    data = load_json_file("champions.json")
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if k != "_comment" and isinstance(v, dict)}


def load_retired_overrides() -> Dict[str, bool]:
    data = load_json_file("retired_overrides.json")
    return data if isinstance(data, dict) else {}


def set_fighter_retired(fighter_id: str, retired: bool) -> None:
    overrides = load_retired_overrides()
    overrides[str(fighter_id)] = retired
    path = DATA_DIR / "retired_overrides.json"
    with path.open("w", encoding="utf-8") as handle:
        json.dump(overrides, handle, indent=2)


def load_fights_csv(division: str) -> Dict[str, Dict[str, Any]]:
    """Load fights CSV for a division, keyed by fight_id."""
    slug = _division_slug(division)
    path = DATA_DIR / f"fights_{slug}.csv"
    if not path.exists():
        return {}
    result: Dict[str, Dict[str, Any]] = {}
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            fid = row.get("fight_id", "")
            if fid:
                result[fid] = row
    return result


def get_upcoming_events() -> List[Dict[str, Any]]:
    events = load_event_data()
    today = datetime.utcnow()
    upcoming = []
    for event in events:
        date = parse_date(event.get("date") or event.get("event_date"))
        if date and date >= today:
            upcoming.append({**event, "parsed_date": date})
    upcoming.sort(key=lambda item: item["parsed_date"])
    return upcoming
