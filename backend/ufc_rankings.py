"""Official UFC rankings (ufc.com/rankings): fetch, cache to disk, keep champions in sync.

ufc.com localises the division headings by IP/language, so divisions are taken by
position instead of by label: the page always lists P4P first, then men's
flyweight -> heavyweight.
"""
import json
import logging
import threading
import time
import unicodedata
from datetime import datetime, timezone
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup

from .data_loader import _ALL_DIVISION_SLUGS, DATA_DIR, load_json_file

log = logging.getLogger("ufc_rankings")

_URL = "https://www.ufc.com/rankings"
_HEADERS = {"User-Agent": "Mozilla/5.0", "Accept-Language": "en-US,en;q=0.9"}
_REFRESH_SECONDS = 6 * 3600

# Order of the men's groups on ufc.com/rankings, after the P4P group.
_PAGE_ORDER = [
    "flyweight", "bantamweight", "featherweight", "lightweight",
    "welterweight", "middleweight", "light heavyweight", "heavyweight",
]

_RANKINGS_FILE = DATA_DIR / "ufc_rankings.json"
_CHAMPIONS_FILE = DATA_DIR / "champions.json"
_lock = threading.Lock()


def _norm(name: str) -> str:
    s = unicodedata.normalize("NFKD", name or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).replace("ł", "l").replace("Ł", "L")
    return " ".join(s.lower().replace("-", " ").replace(".", "").replace("'", "").replace("’", "").split())


def _name_index() -> Dict[str, str]:
    """normalised name -> fighter_id, from every division's rankings and fighters files."""
    index: Dict[str, str] = {}
    for slug in _ALL_DIVISION_SLUGS:
        sources = (load_json_file(f"rankings_{slug}.json") or []) + (load_json_file(f"fighters_{slug}.json") or [])
        for f in sources:
            fid = str(f.get("fighter_id") or f.get("id") or "")
            name = f.get("name") or f.get("fighter_name")
            if fid and name:
                index.setdefault(_norm(name), fid)
    return index


def fetch_ufc_rankings() -> Dict[str, dict]:
    """Return {division: {"champion": name, "ranked": [name x15]}} straight from ufc.com."""
    resp = requests.get(_URL, headers=_HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")
    groups = soup.select(".view-grouping")
    if len(groups) < 1 + len(_PAGE_ORDER):
        raise ValueError(f"ufc.com layout changed: only {len(groups)} ranking groups found")

    result: Dict[str, dict] = {}
    for division, group in zip(_PAGE_ORDER, groups[1:1 + len(_PAGE_ORDER)]):
        champ_el = group.select_one("caption h5 a")
        ranked = [
            a.get_text(strip=True)
            for a in (row.select_one("td.views-field-title a") for row in group.select("tbody tr"))
            if a
        ]
        if not champ_el or len(ranked) < 15:
            raise ValueError(f"ufc.com layout changed: bad group for {division}")
        result[division] = {"champion": champ_el.get_text(strip=True), "ranked": ranked[:15]}
    return result


def refresh() -> Optional[dict]:
    """Fetch, resolve names to our fighter ids, persist rankings + champions. None on failure."""
    try:
        raw = fetch_ufc_rankings()
    except Exception as exc:
        log.warning("UFC rankings refresh failed: %s", exc)
        return None

    ids = _name_index()
    divisions: Dict[str, dict] = {}
    champions: Dict[str, dict] = {
        "_comment": "Auto-synced from ufc.com/rankings by backend/ufc_rankings.py. Do not edit by hand."
    }
    for division, info in raw.items():
        champ_name = info["champion"]
        champ_id = ids.get(_norm(champ_name), "")
        divisions[division] = {
            "champion": {"rank": 0, "fighter_name": champ_name, "fighter_id": champ_id},
            "ranked": [
                {"rank": i, "fighter_name": n, "fighter_id": ids.get(_norm(n), "")}
                for i, n in enumerate(info["ranked"], start=1)
            ],
        }
        champions[division] = {"fighter_id": champ_id, "fighter_name": champ_name}

    payload = {"updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "divisions": divisions}
    try:
        with _lock:
            _RANKINGS_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            _CHAMPIONS_FILE.write_text(json.dumps(champions, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError as exc:  # data/ not writable
        log.warning("Could not persist UFC rankings: %s", exc)
        return None
    return payload


def load_ufc_rankings() -> dict:
    data = load_json_file("ufc_rankings.json")
    return data if isinstance(data, dict) else {"updated_at": None, "divisions": {}}


def ufc_rank_map(division: str) -> Dict[str, int]:
    """fighter_id -> official UFC rank in this division (0 = champion, 1-15)."""
    info = load_ufc_rankings().get("divisions", {}).get(division.lower())
    if not info:
        return {}
    entries = [info["champion"], *info["ranked"]]
    return {e["fighter_id"]: e["rank"] for e in entries if e.get("fighter_id")}


def _loop() -> None:
    while True:
        refresh()
        time.sleep(_REFRESH_SECONDS)


def start_background_refresh() -> None:
    threading.Thread(target=_loop, name="ufc-rankings-refresh", daemon=True).start()


if __name__ == "__main__":
    # python -m backend.ufc_rankings  -> one-off sync of ufc_rankings.json + champions.json
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    raise SystemExit(0 if refresh() else 1)
