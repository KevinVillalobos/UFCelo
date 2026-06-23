"""
Post-processing step: determines each fighter's "current division" from their
most recent fight across ALL weight classes, then filters every division's
ranking so a fighter appears in exactly ONE division.

Run after elo_engine.py has processed all divisions.
"""
import csv
import json
import logging
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

_DIVISIONS = [
    "heavyweight", "light heavyweight", "middleweight", "welterweight",
    "lightweight", "featherweight", "bantamweight", "flyweight",
]

_DATE_FMTS = ["%B %d, %Y", "%B %d %Y", "%b %d, %Y", "%b %d %Y", "%m/%d/%Y"]


def _parse_date(s: str):
    for fmt in _DATE_FMTS:
        try:
            return datetime.strptime(s.strip(), fmt)
        except ValueError:
            pass
    return None


def _slug(div: str) -> str:
    return div.lower().replace(" ", "_")


def determine_current_divisions(data_dir: Path) -> dict[str, str]:
    """
    Returns {fighter_id: current_division} based on the most recent fight
    date across all division CSVs.
    """
    latest: dict[str, tuple] = {}  # fighter_id -> (last_date, division)

    for div in _DIVISIONS:
        csv_path = data_dir / f"fights_{_slug(div)}.csv"
        if not csv_path.exists():
            continue
        with csv_path.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                d = _parse_date(row.get("event_date", ""))
                if not d:
                    continue
                for fid_key in ("fighter_a_id", "fighter_b_id"):
                    fid = row.get(fid_key, "").strip()
                    if not fid:
                        continue
                    prev = latest.get(fid)
                    if prev is None or d > prev[0]:
                        latest[fid] = (d, div)

    return {fid: info[1] for fid, info in latest.items()}


def unify(data_dir: Path) -> None:
    data_dir = Path(data_dir)
    current_div = determine_current_divisions(data_dir)
    log.info("Current division determined for %d fighters", len(current_div))

    for div in _DIVISIONS:
        slug = _slug(div)
        rank_path = data_dir / f"rankings_{slug}.json"
        alltime_path = data_dir / f"rankings_{slug}_alltime.json"

        if not rank_path.exists():
            log.warning("No rankings file for %s — skipping", div)
            continue

        ranking = json.loads(rank_path.read_text(encoding="utf-8"))
        alltime = json.loads(alltime_path.read_text(encoding="utf-8")) if alltime_path.exists() else []

        before = len(ranking)
        ranking = [
            r for r in ranking
            if current_div.get(str(r["fighter_id"]), div) == div
        ]
        alltime = [
            r for r in alltime
            if current_div.get(str(r["fighter_id"]), div) == div
        ]

        # Re-assign ranks after filtering
        for i, r in enumerate(ranking, 1):
            r["rank"] = i
        for i, r in enumerate(alltime, 1):
            r["alltime_rank"] = i

        rank_path.write_text(json.dumps(ranking, indent=2, ensure_ascii=False), encoding="utf-8")
        if alltime_path.exists():
            alltime_path.write_text(json.dumps(alltime, indent=2, ensure_ascii=False), encoding="utf-8")

        removed = before - len(ranking)
        log.info("[%s] %d fighters → %d after unification (%d moved out)", div, before, len(ranking), removed)

    log.info("Unification complete.")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="data")
    args = parser.parse_args()
    unify(Path(args.output))
