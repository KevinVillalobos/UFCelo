"""
Patch null records in all rankings JSON files using fighters JSON data.
Run after ELO engine when fighters_*.json files are present.
"""
import json
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
DIVISION_SLUGS = [
    "heavyweight", "light_heavyweight", "middleweight", "welterweight",
    "lightweight", "featherweight", "bantamweight", "flyweight",
]


def build_global_fighter_map() -> dict:
    global_map = {}
    # All division-specific fighter files
    for slug in DIVISION_SLUGS:
        f = DATA / f"fighters_{slug}.json"
        if not f.exists():
            continue
        fighters = json.loads(f.read_text(encoding="utf-8")) or []
        if isinstance(fighters, dict):
            fighters = [{"id": k, **v} for k, v in fighters.items()]
        for fighter in fighters:
            fid = str(fighter.get("fighter_id") or fighter.get("id") or "")
            if fid and fid not in global_map:
                global_map[fid] = fighter
    # Legacy global file
    gf = DATA / "fighters.json"
    if gf.exists():
        fighters = json.loads(gf.read_text(encoding="utf-8")) or []
        if isinstance(fighters, dict):
            fighters = [{"id": k, **v} for k, v in fighters.items()]
        for fighter in fighters:
            fid = str(fighter.get("fighter_id") or fighter.get("id") or "")
            if fid and fid not in global_map:
                global_map[fid] = fighter
    return global_map


def resolve_record(fighter: dict) -> str | None:
    rec = fighter.get("record")
    if not rec:
        w = fighter.get("wins", 0) or 0
        l = fighter.get("losses", 0) or 0
        d = fighter.get("draws", 0) or 0
        if w + l + d > 0:
            rec = f"{w}-{l}-{d}"
    return rec if rec and rec != "0-0-0" else None




def build_elo_record_map() -> dict:
    """Build {fighter_id: 'W-L-D'} from ALL ELO history files (deduped by fight_id)."""
    wld: dict = {}
    seen: dict = {}
    for slug in DIVISION_SLUGS:
        path = DATA / f"elo_histories_{slug}.json"
        if not path.exists():
            continue
        hist = json.loads(path.read_text(encoding="utf-8")) or {}
        for fid, entries in hist.items():
            if fid not in wld:
                wld[fid] = [0, 0, 0]
                seen[fid] = set()
            for entry in entries:
                key = entry.get("fight_id") or (entry.get("date", "") + str(entry.get("opponent_id", "")))
                if key in seen[fid]:
                    continue
                seen[fid].add(key)
                res = (entry.get("result") or "").lower()
                if res == "win":
                    wld[fid][0] += 1
                elif res == "loss":
                    wld[fid][1] += 1
                elif res == "draw":
                    wld[fid][2] += 1
    return {fid: f"{w}-{l}-{d}" for fid, (w, l, d) in wld.items() if w + l + d > 0}


def patch_file(path: Path, global_map: dict, elo_map: dict) -> tuple[int, int]:
    data = json.loads(path.read_text(encoding="utf-8"))
    from_json = from_elo = 0
    for entry in data:
        if entry.get("record") is not None:
            continue
        fid = str(entry.get("fighter_id") or entry.get("id") or "")
        if not fid:
            continue
        fighter = global_map.get(fid)
        if fighter:
            rec = resolve_record(fighter)
            if rec:
                entry["record"] = rec
                from_json += 1
                continue
        # Fallback: ELO history record (may be incomplete but better than null)
        rec = elo_map.get(fid)
        if rec:
            entry["record"] = rec
            from_elo += 1
    if from_json + from_elo:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return from_json, from_elo


def main():
    print("Building global fighter map...")
    global_map = build_global_fighter_map()
    print(f"  {len(global_map)} fighters indexed")

    print("Building ELO history record map (fallback)...")
    elo_map = build_elo_record_map()
    print(f"  {len(elo_map)} fighters with ELO history")

    total_json = total_elo = 0
    for slug in DIVISION_SLUGS:
        for suffix in ["", "_alltime"]:
            path = DATA / f"rankings_{slug}{suffix}.json"
            if not path.exists():
                continue
            fj, fe = patch_file(path, global_map, elo_map)
            if fj + fe:
                print(f"  [{slug}{suffix}] patched {fj} from JSON, {fe} from ELO history")
            total_json += fj
            total_elo += fe

    print(f"Done. {total_json} from fighters JSON + {total_elo} from ELO history = {total_json+total_elo} total.")


if __name__ == "__main__":
    main()
