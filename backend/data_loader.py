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


def load_fighters(division: str = "heavyweight") -> List[Dict[str, Any]]:
    slug = _division_slug(division)
    data = load_json_file(f"fighters_{slug}.json")
    if data is None:
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
    fighters = load_fighters(division)
    for fighter in fighters:
        if str(fighter.get("id")) == str(fighter_id) or str(fighter.get("fighter_id")) == str(fighter_id):
            return fighter
    return None


def get_skill_score_by_id(fighter_id: str, division: str = "heavyweight") -> Optional[Dict[str, Any]]:
    skills = load_skill_scores(division)
    for skill in skills:
        if str(skill.get("fighter_id")) == str(fighter_id) or str(skill.get("id")) == str(fighter_id):
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
