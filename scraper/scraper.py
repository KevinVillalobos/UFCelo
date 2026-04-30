import argparse
import csv
import json
import logging
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

BASE_URL = "http://ufcstats.com"

_DIVISION_FILTERS = {
    "heavyweight":      lambda wc: "heavyweight" in wc and "light heavyweight" not in wc,
    "light heavyweight": lambda wc: "light heavyweight" in wc,
    "middleweight":     lambda wc: "middleweight" in wc and "women" not in wc,
    "welterweight":     lambda wc: "welterweight" in wc and "women" not in wc,
    "lightweight":      lambda wc: "lightweight" in wc and "women" not in wc,
    "featherweight":    lambda wc: "featherweight" in wc and "women" not in wc,
    "bantamweight":     lambda wc: "bantamweight" in wc and "women" not in wc,
    "flyweight":        lambda wc: "flyweight" in wc and "women" not in wc,
}


def _matches_division(weight_class: str, division: str) -> bool:
    wc_lower = weight_class.lower()
    fn = _DIVISION_FILTERS.get(division.lower())
    return fn(wc_lower) if fn else division.lower() in wc_lower

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "http://ufcstats.com/",
}
@dataclass
class Fighter:
    fighter_id: str
    name: str
    nickname: str
    height: str
    weight: str
    reach: str
    stance: str
    dob: str
    wins: int
    losses: int
    draws: int
    url: str


@dataclass
class FightStats:
    fighter_id: str
    strikes_landed: int
    strikes_attempted: int
    takedowns_landed: int
    takedowns_attempted: int
    knockdowns: int
    control_time: str
    submission_attempts: int
    reversals: int
    head_strikes_landed: int
    head_strikes_attempted: int
    body_strikes_landed: int
    body_strikes_attempted: int
    leg_strikes_landed: int
    leg_strikes_attempted: int


@dataclass
class Fight:
    fight_id: str
    event_id: str
    event_name: str
    event_date: str
    fighter_a_id: str
    fighter_a_name: str
    fighter_b_id: str
    fighter_b_name: str
    winner_id: str
    method: str
    round: int
    time: str
    weight_class: str
    is_title_fight: bool
    fighter_a_stats: Optional[FightStats] = None
    fighter_b_stats: Optional[FightStats] = None


class UFCScraper:
    def __init__(self, delay: float = 1.5, target_division: str = "heavyweight"):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.delay = delay
        self._target_division = target_division

    def _get(self, url: str) -> Optional[BeautifulSoup]:
        for attempt in range(3):
            try:
                time.sleep(self.delay)
                r = self.session.get(url, timeout=20)
                r.raise_for_status()
                return BeautifulSoup(r.text, "lxml")
            except requests.HTTPError as e:
                log.warning(f"HTTP {e.response.status_code} en {url} (intento {attempt+1}/3)")
                time.sleep(self.delay * 2)
            except requests.RequestException as e:
                log.warning(f"Error en {url}: {e} (intento {attempt+1}/3)")
                time.sleep(self.delay * 2)
        log.error(f"Falló después de 3 intentos: {url}")
        return None

    def _normalize_method(self, method_raw: str) -> str:
        """Normaliza el método de finalización de pelea."""
        method = method_raw.upper().strip()
        if "KO" in method or "TKO" in method:
            return "KO/TKO"
        if "SUB" in method or "SUBMISSION" in method:
            return "SUB"
        if "DECISION" in method or "DEC" in method:
            if "UNANIMOUS" in method or "U-DEC" in method or "U DEC" in method:
                return "DEC U"
            if "SPLIT" in method or "S-DEC" in method or "S DEC" in method:
                return "DEC S"
            if "MAJORITY" in method or "M-DEC" in method or "M DEC" in method:
                return "DEC M"
            return "DEC U"
        return "OTHER"

    def get_all_events(self) -> list[dict]:
        log.info("Obteniendo lista de todos los eventos...")
        soup = self._get(f"{BASE_URL}/statistics/events/completed?page=all")
        if not soup:
            return []

        events = []
        rows = soup.select("tr.b-statistics__table-row")
        for row in rows:
            link = row.select_one("a.b-link")
            date_td = row.select_one("span.b-statistics__date")
            if not link:
                continue
            events.append({
                "event_id": link["href"].split("/")[-1],
                "name": link.text.strip(),
                "date": date_td.text.strip() if date_td else "",
                "url": link["href"],
            })

        log.info(f"Encontrados {len(events)} eventos")
        return events

    def get_fights_from_event(self, event: dict) -> list[Fight]:
        soup = self._get(event["url"])
        if not soup:
            return []

        fights = []
        rows = soup.select("tr.b-fight-details__table-row[data-link]")
        if not rows:
            rows = soup.select("tr.b-fight-details__table-row")

        for row in rows:
            fight_url = row.get("data-link", "")
            fight_id = fight_url.split("/")[-1] if fight_url else ""
            cols = row.select("td.b-fight-details__table-col")
            if len(cols) < 8:
                continue

            fighters = cols[1].select("a")
            if len(fighters) < 2:
                continue
            f_a_name = fighters[0].text.strip()
            f_b_name = fighters[1].text.strip()
            f_a_id = fighters[0]["href"].split("/")[-1]
            f_b_id = fighters[1]["href"].split("/")[-1]

            result_text = cols[0].text.strip().upper()
            winner_id = ""
            if "W" in result_text or "WIN" in result_text:
                # El ícono o texto indica que el primer peleador es el ganador
                winner_id = f_a_id
                if "LOSS" in result_text or "L" in result_text:
                    winner_id = f_b_id

            method_raw = cols[7].text.strip().upper() if len(cols) > 7 else ""
            method = self._normalize_method(method_raw)

            round_num = 0
            fight_time = ""
            try:
                round_num = int(cols[8].text.strip()) if len(cols) > 8 else 0
                fight_time = cols[9].text.strip() if len(cols) > 9 else ""
            except ValueError:
                pass

            weight_class = cols[6].text.strip() if len(cols) > 6 else ""
            is_title = "title" in weight_class.lower() or "championship" in weight_class.lower()
            is_target = self._target_division and _matches_division(weight_class, self._target_division)

            # Only fetch per-fight stats for the target division (saves ~10 requests/event)
            fighter_a_stats = None
            fighter_b_stats = None
            if fight_url and is_target:
                if fight_url.startswith("http"):
                    full_fight_url = fight_url
                elif fight_url.startswith("/"):
                    full_fight_url = f"{BASE_URL}{fight_url}"
                else:
                    full_fight_url = f"{BASE_URL}/{fight_url}"
                fighter_a_stats, fighter_b_stats, is_title_detail = self.get_fight_stats(full_fight_url, f_a_id, f_b_id)
                is_title = is_title or is_title_detail

            fights.append(Fight(
                fight_id=fight_id,
                event_id=event["event_id"],
                event_name=event["name"],
                event_date=event["date"],
                fighter_a_id=f_a_id,
                fighter_a_name=f_a_name,
                fighter_b_id=f_b_id,
                fighter_b_name=f_b_name,
                winner_id=winner_id,
                method=method,
                round=round_num,
                time=fight_time,
                weight_class=weight_class,
                is_title_fight=is_title,
                fighter_a_stats=fighter_a_stats,
                fighter_b_stats=fighter_b_stats,
            ))

        return fights

    def get_fight_stats(self, fight_url: str, fighter_a_id: str, fighter_b_id: str) -> tuple[Optional[FightStats], Optional[FightStats], bool]:
        """Extrae estadísticas detalladas de una pelea específica."""
        soup = self._get(fight_url)
        if not soup:
            return None, None, False

        # Title fight detection from the fight detail page header
        is_title_from_page = False
        fight_head = soup.select_one(".b-fight-details__fight-head, .b-fight-details__fight, .b-fight-details")
        if fight_head:
            head_text = fight_head.get_text().lower()[:600]
            is_title_from_page = "title bout" in head_text or "championship" in head_text

        def extract_of(text: str) -> tuple[int, int]:
            """Returns (landed, attempted) from 'X of Y' text."""
            try:
                parts = text.strip().split(" of ")
                return int(parts[0]), int(parts[1])
            except (ValueError, IndexError):
                return 0, 0

        def extract_int(text: str) -> int:
            try:
                clean = text.strip().replace("--", "0").replace("N/A", "0")
                return int(clean) if clean else 0
            except ValueError:
                return 0

        # UFCstats fight detail page has two main stat sections:
        # 1. "Totals" — columns: Fighter, KD, Sig.Str.(X of Y), Sig.Str.%, Total Str.(X of Y),
        #                         Td(X of Y), Td%, Sub.Att, Rev., Ctrl
        # 2. "Significant Strikes by Position" — columns: Fighter, Sig.Str., Sig.Str.%,
        #                                                  Head(X of Y), Body(X of Y), Leg(X of Y), ...
        # Each section has one "overall" table followed by per-round breakdown tables.
        # We only want the first (overall) table from each section, identified by thead header text.

        totals_data: dict = {}    # {fighter_id: dict of totals fields}
        sig_data: dict = {}       # {fighter_id: dict of sig-strike fields}

        for table in soup.select("table.b-fight-details__table"):
            thead = table.select_one("thead tr")
            if not thead:
                continue
            ths = [th.get_text(strip=True).upper() for th in thead.select("th, td")]
            tbody = table.select_one("tbody")
            if not tbody:
                continue

            is_totals = "CTRL" in ths
            is_sig = "HEAD" in ths
            if not is_totals and not is_sig:
                continue

            # UFCstats fight pages put BOTH fighters in a single <tr>.
            # Each stat <td> has two <p> elements: p[0]=fighter shown first, p[1]=fighter shown second.
            # cols[0] has two <a> links in the same order.
            for row in tbody.select("tr"):
                cols = row.select("td")
                if len(cols) < 5:
                    continue
                fighter_links = cols[0].select("a")
                if not fighter_links:
                    continue

                for idx, link in enumerate(fighter_links):
                    href = link.get("href", "")
                    fid = None
                    if fighter_a_id in href:
                        fid = fighter_a_id
                    elif fighter_b_id in href:
                        fid = fighter_b_id
                    else:
                        continue

                    def get_val(col_n: int, _idx: int = idx) -> str:
                        if col_n >= len(cols):
                            return ""
                        ps = cols[col_n].select("p")
                        if ps and _idx < len(ps):
                            return ps[_idx].get_text(strip=True)
                        return cols[col_n].get_text(strip=True)

                    # Only store first occurrence per fighter per table type (= overall, not per-round)
                    if is_totals and fid not in totals_data:
                        l, a = extract_of(get_val(4))
                        td_l, td_a = extract_of(get_val(5))
                        totals_data[fid] = {
                            "knockdowns":          extract_int(get_val(1)),
                            "strikes_landed":      l,
                            "strikes_attempted":   a,
                            "takedowns_landed":    td_l,
                            "takedowns_attempted": td_a,
                            "submission_attempts": extract_int(get_val(7)),
                            "reversals":           extract_int(get_val(8)),
                            "control_time":        get_val(9),
                        }

                    elif is_sig and fid not in sig_data:
                        h_l, h_a = extract_of(get_val(3))
                        b_l, b_a = extract_of(get_val(4))
                        lg_l, lg_a = extract_of(get_val(5))
                        sig_data[fid] = {
                            "head_strikes_landed":    h_l,
                            "head_strikes_attempted": h_a,
                            "body_strikes_landed":    b_l,
                            "body_strikes_attempted": b_a,
                            "leg_strikes_landed":     lg_l,
                            "leg_strikes_attempted":  lg_a,
                        }

        def build_stats(fid: str) -> Optional[FightStats]:
            t = totals_data.get(fid)
            s = sig_data.get(fid)
            if not t:
                return None
            return FightStats(
                fighter_id=fid,
                strikes_landed=t["strikes_landed"],
                strikes_attempted=t["strikes_attempted"],
                takedowns_landed=t["takedowns_landed"],
                takedowns_attempted=t["takedowns_attempted"],
                knockdowns=t["knockdowns"],
                control_time=t["control_time"],
                submission_attempts=t["submission_attempts"],
                reversals=t["reversals"],
                head_strikes_landed=s["head_strikes_landed"] if s else 0,
                head_strikes_attempted=s["head_strikes_attempted"] if s else 0,
                body_strikes_landed=s["body_strikes_landed"] if s else 0,
                body_strikes_attempted=s["body_strikes_attempted"] if s else 0,
                leg_strikes_landed=s["leg_strikes_landed"] if s else 0,
                leg_strikes_attempted=s["leg_strikes_attempted"] if s else 0,
            )

        return build_stats(fighter_a_id), build_stats(fighter_b_id), is_title_from_page

    def get_fighter_details(self, fighter_id: str, name: str) -> Optional[Fighter]:
        url = f"{BASE_URL}/fighter-details/{fighter_id}"
        soup = self._get(url)
        if not soup:
            return None

        def get_stat(label: str) -> str:
            for li in soup.select("li.b-list__box-list-item"):
                if label.lower() in li.text.lower():
                    parts = li.text.strip().split(":" )
                    return parts[1].strip() if len(parts) > 1 else ""
            return ""

        record_text = soup.select_one("span.b-content__title-record")
        wins, losses, draws = 0, 0, 0
        if record_text:
            parts = record_text.text.strip().replace("Record:", "").strip().split("-")
            try:
                wins = int(parts[0])
                losses = int(parts[1]) if len(parts) > 1 else 0
                draws = int(parts[2].split("(")[0]) if len(parts) > 2 else 0
            except (ValueError, IndexError):
                pass

        return Fighter(
            fighter_id=fighter_id,
            name=name,
            nickname=get_stat("Nickname"),
            height=get_stat("Height"),
            weight=get_stat("Weight"),
            reach=get_stat("Reach"),
            stance=get_stat("Stance"),
            dob=get_stat("DOB"),
            wins=wins,
            losses=losses,
            draws=draws,
            url=url,
        )

    def get_all_fighters(self) -> list[dict]:
        log.info("Obteniendo lista de todos los peleadores...")
        fighters = []
        for char in "abcdefghijklmnopqrstuvwxyz":
            url = f"{BASE_URL}/statistics/fighters?char={char}&page=all"
            soup = self._get(url)
            if not soup:
                continue
            rows = soup.select("tr.b-statistics__table-row")
            for row in rows:
                cols = row.select("td")
                if len(cols) < 2:
                    continue
                link = row.select_one("a")
                if not link:
                    continue
                fighter_id = link["href"].split("/")[-1]
                name = f"{cols[0].text.strip()} {cols[1].text.strip()}".strip()
                fighters.append({"id": fighter_id, "name": name, "url": link["href"]})
            log.info(f"  Letra '{char}': {len(rows)} peleadores")

        log.info(f"Total peleadores encontrados: {len(fighters)}")
        return fighters


def scrape_division(division: str, output_dir: str, max_events: Optional[int] = None):
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    scraper = UFCScraper(delay=1.5, target_division=division)

    events = scraper.get_all_events()
    with open(output / "events.json", "w", encoding="utf-8") as f:
        json.dump(events, f, indent=2, ensure_ascii=False)
    log.info(f"Guardados {len(events)} eventos en events.json")

    if max_events:
        events = events[:max_events]

    all_fights: list[Fight] = []
    fighter_ids: set[str] = set()

    for i, event in enumerate(events, 1):
        log.info(f"[{i}/{len(events)}] Scrapeando: {event['name']} ({event['date']})")
        fights = scraper.get_fights_from_event(event)
        for fight in fights:
            if _matches_division(fight.weight_class, division):
                all_fights.append(fight)
                fighter_ids.add(fight.fighter_a_id)
                fighter_ids.add(fight.fighter_b_id)

    all_fights.sort(key=lambda f: f.event_date)

    fights_path = output / f"fights_{division.lower().replace(' ', '_')}.csv"
    if all_fights:
        fieldnames = [
            "fight_id", "event_id", "event_name", "event_date",
            "fighter_a_id", "fighter_a_name", "fighter_b_id", "fighter_b_name",
            "winner_id", "method", "round", "time", "weight_class", "is_title_fight",
            # Estadísticas fighter_a
            "fighter_a_strikes_landed", "fighter_a_strikes_attempted",
            "fighter_a_takedowns_landed", "fighter_a_takedowns_attempted",
            "fighter_a_knockdowns", "fighter_a_control_time",
            "fighter_a_submission_attempts", "fighter_a_reversals",
            "fighter_a_head_strikes_landed", "fighter_a_head_strikes_attempted",
            "fighter_a_body_strikes_landed", "fighter_a_body_strikes_attempted",
            "fighter_a_leg_strikes_landed", "fighter_a_leg_strikes_attempted",
            # Estadísticas fighter_b
            "fighter_b_strikes_landed", "fighter_b_strikes_attempted",
            "fighter_b_takedowns_landed", "fighter_b_takedowns_attempted",
            "fighter_b_knockdowns", "fighter_b_control_time",
            "fighter_b_submission_attempts", "fighter_b_reversals",
            "fighter_b_head_strikes_landed", "fighter_b_head_strikes_attempted",
            "fighter_b_body_strikes_landed", "fighter_b_body_strikes_attempted",
            "fighter_b_leg_strikes_landed", "fighter_b_leg_strikes_attempted",
        ]

        with open(fights_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()

            for fight in all_fights:
                row = {
                    "fight_id": fight.fight_id,
                    "event_id": fight.event_id,
                    "event_name": fight.event_name,
                    "event_date": fight.event_date,
                    "fighter_a_id": fight.fighter_a_id,
                    "fighter_a_name": fight.fighter_a_name,
                    "fighter_b_id": fight.fighter_b_id,
                    "fighter_b_name": fight.fighter_b_name,
                    "winner_id": fight.winner_id,
                    "method": fight.method,
                    "round": fight.round,
                    "time": fight.time,
                    "weight_class": fight.weight_class,
                    "is_title_fight": fight.is_title_fight,
                }

                # Agregar estadísticas de fighter_a
                if fight.fighter_a_stats:
                    stats = fight.fighter_a_stats
                    row.update({
                        "fighter_a_strikes_landed": stats.strikes_landed,
                        "fighter_a_strikes_attempted": stats.strikes_attempted,
                        "fighter_a_takedowns_landed": stats.takedowns_landed,
                        "fighter_a_takedowns_attempted": stats.takedowns_attempted,
                        "fighter_a_knockdowns": stats.knockdowns,
                        "fighter_a_control_time": stats.control_time,
                        "fighter_a_submission_attempts": stats.submission_attempts,
                        "fighter_a_reversals": stats.reversals,
                        "fighter_a_head_strikes_landed": stats.head_strikes_landed,
                        "fighter_a_head_strikes_attempted": stats.head_strikes_attempted,
                        "fighter_a_body_strikes_landed": stats.body_strikes_landed,
                        "fighter_a_body_strikes_attempted": stats.body_strikes_attempted,
                        "fighter_a_leg_strikes_landed": stats.leg_strikes_landed,
                        "fighter_a_leg_strikes_attempted": stats.leg_strikes_attempted,
                    })

                # Agregar estadísticas de fighter_b
                if fight.fighter_b_stats:
                    stats = fight.fighter_b_stats
                    row.update({
                        "fighter_b_strikes_landed": stats.strikes_landed,
                        "fighter_b_strikes_attempted": stats.strikes_attempted,
                        "fighter_b_takedowns_landed": stats.takedowns_landed,
                        "fighter_b_takedowns_attempted": stats.takedowns_attempted,
                        "fighter_b_knockdowns": stats.knockdowns,
                        "fighter_b_control_time": stats.control_time,
                        "fighter_b_submission_attempts": stats.submission_attempts,
                        "fighter_b_reversals": stats.reversals,
                        "fighter_b_head_strikes_landed": stats.head_strikes_landed,
                        "fighter_b_head_strikes_attempted": stats.head_strikes_attempted,
                        "fighter_b_body_strikes_landed": stats.body_strikes_landed,
                        "fighter_b_body_strikes_attempted": stats.body_strikes_attempted,
                        "fighter_b_leg_strikes_landed": stats.leg_strikes_landed,
                        "fighter_b_leg_strikes_attempted": stats.leg_strikes_attempted,
                    })

                writer.writerow(row)
    log.info(f"Guardadas {len(all_fights)} peleas Heavyweight en fights_heavyweight.csv")

    fighters = []
    for fid in fighter_ids:
        name = next(
            (f.fighter_a_name for f in all_fights if f.fighter_a_id == fid),
            next((f.fighter_b_name for f in all_fights if f.fighter_b_id == fid), "Unknown"),
        )
        log.info(f"  Perfil: {name}")
        fighter = scraper.get_fighter_details(fid, name)
        if fighter:
            fighters.append(asdict(fighter))

    fighters_filename = f"fighters_{division.lower().replace(' ', '_')}.json"
    with open(output / fighters_filename, "w", encoding="utf-8") as f:
        json.dump(fighters, f, indent=2, ensure_ascii=False)
    log.info(f"Guardados {len(fighters)} perfiles de peleadores en {fighters_filename}")

    return all_fights, fighters


def refresh_fight_stats(csv_path: str, delay: float = 1.5) -> None:
    """Re-fetch per-fight stats for all rows in the existing CSV and write them back."""
    path = Path(csv_path)
    with path.open("r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    fieldnames = list(rows[0].keys()) if rows else []
    # Ensure stat columns are present
    stat_cols = [
        "fighter_a_strikes_landed", "fighter_a_strikes_attempted",
        "fighter_a_takedowns_landed", "fighter_a_takedowns_attempted",
        "fighter_a_knockdowns", "fighter_a_control_time",
        "fighter_a_submission_attempts", "fighter_a_reversals",
        "fighter_a_head_strikes_landed", "fighter_a_head_strikes_attempted",
        "fighter_a_body_strikes_landed", "fighter_a_body_strikes_attempted",
        "fighter_a_leg_strikes_landed", "fighter_a_leg_strikes_attempted",
        "fighter_b_strikes_landed", "fighter_b_strikes_attempted",
        "fighter_b_takedowns_landed", "fighter_b_takedowns_attempted",
        "fighter_b_knockdowns", "fighter_b_control_time",
        "fighter_b_submission_attempts", "fighter_b_reversals",
        "fighter_b_head_strikes_landed", "fighter_b_head_strikes_attempted",
        "fighter_b_body_strikes_landed", "fighter_b_body_strikes_attempted",
        "fighter_b_leg_strikes_landed", "fighter_b_leg_strikes_attempted",
    ]
    for col in stat_cols:
        if col not in fieldnames:
            fieldnames.append(col)

    scraper = UFCScraper(delay=delay)
    updated = 0

    for i, row in enumerate(rows, 1):
        fight_id = row.get("fight_id", "")
        fa_id = row.get("fighter_a_id", "")
        fb_id = row.get("fighter_b_id", "")
        if not fight_id or not fa_id or not fb_id:
            continue

        fight_url = f"http://ufcstats.com/fight-details/{fight_id}"
        log.info(f"[{i}/{len(rows)}] Stats: {row.get('fighter_a_name')} vs {row.get('fighter_b_name')}")
        fa_stats, fb_stats = scraper.get_fight_stats(fight_url, fa_id, fb_id)

        def apply_stats(prefix: str, stats: Optional[FightStats]) -> None:
            if not stats:
                return
            row[f"{prefix}_strikes_landed"] = stats.strikes_landed
            row[f"{prefix}_strikes_attempted"] = stats.strikes_attempted
            row[f"{prefix}_takedowns_landed"] = stats.takedowns_landed
            row[f"{prefix}_takedowns_attempted"] = stats.takedowns_attempted
            row[f"{prefix}_knockdowns"] = stats.knockdowns
            row[f"{prefix}_control_time"] = stats.control_time
            row[f"{prefix}_submission_attempts"] = stats.submission_attempts
            row[f"{prefix}_reversals"] = stats.reversals
            row[f"{prefix}_head_strikes_landed"] = stats.head_strikes_landed
            row[f"{prefix}_head_strikes_attempted"] = stats.head_strikes_attempted
            row[f"{prefix}_body_strikes_landed"] = stats.body_strikes_landed
            row[f"{prefix}_body_strikes_attempted"] = stats.body_strikes_attempted
            row[f"{prefix}_leg_strikes_landed"] = stats.leg_strikes_landed
            row[f"{prefix}_leg_strikes_attempted"] = stats.leg_strikes_attempted

        apply_stats("fighter_a", fa_stats)
        apply_stats("fighter_b", fb_stats)
        if fa_stats or fb_stats:
            updated += 1

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    log.info(f"Stats actualizadas para {updated}/{len(rows)} peleas en {csv_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="UFC Elo Scraper")
    parser.add_argument("--output", default="../data", help="Directorio de salida")
    parser.add_argument("--division", default="heavyweight",
                        help="División a scrapear (ej: heavyweight, lightweight, welterweight)")
    parser.add_argument("--max-events", type=int, default=None, help="Limitar número de eventos (para testing)")
    parser.add_argument("--test", action="store_true", help="Modo test: solo 10 eventos")
    parser.add_argument("--refresh-stats", action="store_true", help="Re-fetch fight stats for existing CSV")
    args = parser.parse_args()

    division_slug = args.division.lower().replace(" ", "_")
    csv_path = str(Path(args.output) / f"fights_{division_slug}.csv")

    if args.refresh_stats:
        refresh_fight_stats(csv_path)
        log.info("¡Stats actualizadas!")
    else:
        if args.test:
            args.max_events = 10
        scrape_division(args.division, args.output, max_events=args.max_events)
        log.info("¡Scraping completado!")
