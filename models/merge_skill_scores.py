"""
Global skill score merge.

After the ELO engine runs per-division skill scores, this script:
1. Finds the "best" skill score for each fighter (from the division with the most fights)
2. Writes data/skill_scores.json (one entry per fighter, global)
3. Updates each divisional skill_scores_*.json so cross-division fighters
   show their REAL skills (not flat defaults from 1-2 fights in a new division)

Run: python models/merge_skill_scores.py [--output data]
"""
import argparse
import json
from pathlib import Path

DIVISION_SLUGS = [
    "heavyweight", "light_heavyweight", "middleweight", "welterweight",
    "lightweight", "featherweight", "bantamweight", "flyweight",
]


def load(path: Path) -> list:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8")) or []


def merge(data_dir: Path) -> None:
    # Step 1: collect ALL skill entries, grouped by fighter_id
    # key: fighter_id → list of entries, sorted by num_fights descending
    by_fighter: dict[str, list] = {}

    for slug in DIVISION_SLUGS:
        entries = load(data_dir / f"skill_scores_{slug}.json")
        for entry in entries:
            fid = str(entry.get("fighter_id") or entry.get("id") or "")
            if not fid:
                continue
            by_fighter.setdefault(fid, []).append(entry)

    # Step 2: for each fighter, pick the entry with the most fights as canonical
    canonical: dict[str, dict] = {}
    for fid, entries in by_fighter.items():
        best = max(entries, key=lambda e: e.get("num_fights", 0))
        canonical[fid] = best

    print(f"  {len(canonical)} fighters with skill scores")

    # Step 3: write global skill_scores.json
    global_list = sorted(canonical.values(), key=lambda e: e.get("fighter_name", ""))
    (data_dir / "skill_scores.json").write_text(
        json.dumps(global_list, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"  Wrote skill_scores.json ({len(global_list)} entries)")

    # Step 4: update each divisional file so cross-division fighters use their
    # canonical (career-division) skill score instead of flat defaults
    replaced_total = 0
    for slug in DIVISION_SLUGS:
        path = data_dir / f"skill_scores_{slug}.json"
        entries = load(path)
        if not entries:
            continue

        replaced = 0
        for i, entry in enumerate(entries):
            fid = str(entry.get("fighter_id") or entry.get("id") or "")
            if not fid:
                continue
            canon = canonical.get(fid)
            if canon is None:
                continue
            if canon is entry:
                continue  # already the best entry
            # Only replace if canonical has significantly more fights
            canon_fights = canon.get("num_fights", 0)
            this_fights = entry.get("num_fights", 0)
            if canon_fights > this_fights:
                # Preserve the division label but use canonical skill data
                entries[i] = {
                    **canon,
                    "division": entry.get("division", canon.get("division")),
                }
                replaced += 1

        if replaced:
            path.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  [{slug}] updated {replaced} cross-division fighters to their career skills")
        replaced_total += replaced

    print(f"  {replaced_total} skill score entries updated across all divisions")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="data")
    args = parser.parse_args()
    data_dir = Path(args.output)
    print(f"Merging skill scores in {data_dir.resolve()}...")
    merge(data_dir)
    print("Done.")


if __name__ == "__main__":
    main()
