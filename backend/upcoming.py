"""Upcoming UFC cards (ufc.com/events): fetch, cache to disk, resolve fighters to our ids.

data/upcoming_events.json is what /events/upcoming serves. The scraper and the ELO pipeline are
not involved: like ufc_rankings.py this is a small standalone sync that runs when the backend
starts, every few hours after that, or on demand with `python -m backend.upcoming`.
"""
import json
import logging
import re
import threading
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup

from .data_loader import DATA_DIR
from .ufc_rankings import _name_index, _norm

log = logging.getLogger("upcoming")

_BASE = "https://www.ufc.com"
_HEADERS = {"User-Agent": "Mozilla/5.0", "Accept-Language": "en-US,en;q=0.9"}
_REFRESH_SECONDS = 6 * 3600
_MAX_EVENTS = 3          # next N events get their full card fetched
_OUT_FILE = DATA_DIR / "upcoming_events.json"

# ufc.com localises weight-class labels by IP (English or Spanish), so match on keywords.
# Order matters: "light heavyweight" must be tested before "heavyweight" and "lightweight".
_DIVISION_KEYWORDS = [
    ("light heavyweight", ("light heavy", "semipesado")),
    ("heavyweight",       ("heavyweight", "de peso pesado", "peso pesado")),
    ("middleweight",      ("middleweight", "peso medio")),
    ("welterweight",      ("welterweight", "peso welter")),
    ("lightweight",       ("lightweight", "ligero")),
    ("featherweight",     ("featherweight", "peso pluma")),
    ("bantamweight",      ("bantamweight", "peso gallo")),
    ("flyweight",         ("flyweight", "peso mosca")),
]
_CARDS = (("main-card", "main"), ("prelims-card", "prelims"), ("early-prelims-card", "early_prelims"))


def slugify(text: str) -> str:
    s = unicodedata.normalize("NFD", text or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def _squash(text: str) -> str:
    return " ".join((text or "").split())


def _division_from_label(label: str) -> Optional[str]:
    low = (label or "").lower()
    if "mujer" in low or "women" in low:
        return None            # our data only covers the men's divisions
    for division, keys in _DIVISION_KEYWORDS:
        if any(k in low for k in keys):
            return division
    return None


def _get(path: str) -> BeautifulSoup:
    resp = requests.get(_BASE + path, headers=_HEADERS, timeout=25)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "lxml")


def _event_list() -> List[dict]:
    soup = _get("/events")
    now = time.time()
    events = []
    for card in soup.select(".c-card-event--result"):
        link = card.select_one(".c-card-event--result__headline a")
        stamp = card.select_one(".c-card-event--result__date")
        if not link or not stamp or not stamp.get("data-main-card-timestamp"):
            continue
        ts = int(stamp["data-main-card-timestamp"])
        if ts < now - 6 * 3600:
            continue
        venue = card.select_one(".field--name-venue, .c-card-event--result__location")
        href = link.get("href", "")
        events.append({
            "slug": href.rstrip("/").split("/")[-1],
            "path": href if href.startswith("/") else "/" + href.split(".com/", 1)[-1],
            "name": _squash(link.get_text()),
            "timestamp": ts,
            # US evenings fall on the next UTC day, so shift back to the local card date
            "date": (datetime.fromtimestamp(ts, timezone.utc) - timedelta(hours=10)).date().isoformat(),
            "venue": _squash(venue.get_text(" ")) if venue else None,
        })
    events.sort(key=lambda e: e["timestamp"])
    return events


def _event_fights(path: str, slug: str, ids: Dict[str, str]) -> tuple:
    """(full event title, fights). The title comes from the page <title>: 'UFC 333: Volkanovski vs Evloev | UFC'."""
    soup = _get(path)
    title = _squash(soup.title.get_text()).split("|")[0].strip() if soup.title else ""
    fights: List[dict] = []
    for section_id, card in _CARDS:
        section = soup.select_one(f"#{section_id}")
        if not section:
            continue
        for order, node in enumerate(section.select(".c-listing-fight"), start=1):
            red = node.select_one(".c-listing-fight__corner-name--red")
            blue = node.select_one(".c-listing-fight__corner-name--blue")
            if not red or not blue:
                continue
            label = _squash((node.select_one(".c-listing-fight__class-text") or red).get_text(" "))
            name_a, name_b = _squash(red.get_text(" ")), _squash(blue.get_text(" "))
            fights.append({
                "fight_id": f"{slug}-{len(fights) + 1}",
                "card": card,
                "order": order,
                "is_main_event": card == "main" and order == 1,
                "weight_class": label,
                "division": _division_from_label(label),
                "womens": ("mujer" in label.lower() or "women" in label.lower()),
                "fighter_a_name": name_a,
                "fighter_a_id": ids.get(_norm(name_a), ""),
                "fighter_b_name": name_b,
                "fighter_b_id": ids.get(_norm(name_b), ""),
            })
    return title, fights


def refresh() -> Optional[dict]:
    """Fetch the next cards, persist them. Returns the payload, or None (keeping the old file)."""
    try:
        events = _event_list()[:_MAX_EVENTS]
        ids = _name_index()
        out = []
        for ev in events:
            title = ""
            try:
                title, fights = _event_fights(ev["path"], ev["slug"], ids)
            except Exception as exc:
                log.warning("Card for %s unavailable: %s", ev["slug"], exc)
                fights = []
            out.append({
                "event_id": ev["slug"], "slug": ev["slug"], "name": title or ev["name"], "date": ev["date"],
                "timestamp": ev["timestamp"], "venue": ev["venue"],
                "url": _BASE + ev["path"], "fights": fights,
            })
            time.sleep(1)
    except Exception as exc:
        log.warning("Upcoming events refresh failed: %s", exc)
        return None

    payload = {"updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "events": out}
    try:
        _OUT_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError as exc:  # data/ not writable
        log.warning("Could not persist upcoming events: %s", exc)
        return None
    return payload


def _loop() -> None:
    while True:
        refresh()
        time.sleep(_REFRESH_SECONDS)


def start_background_refresh() -> None:
    threading.Thread(target=_loop, name="upcoming-refresh", daemon=True).start()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    result = refresh()
    if result:
        for e in result["events"]:
            print(f'{e["date"]}  {e["name"]}  ({len(e["fights"])} peleas)')
    raise SystemExit(0 if result else 1)
