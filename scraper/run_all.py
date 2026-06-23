"""Runs scraper + ELO engine for all 8 divisions, then unifies cross-division rankings."""
import subprocess
import sys
from pathlib import Path

DIVISIONS = [
    "heavyweight",
    "light heavyweight",
    "middleweight",
    "welterweight",
    "lightweight",
    "featherweight",
    "bantamweight",
    "flyweight",
]

ROOT = Path(__file__).parent.parent
SCRAPER = ROOT / "scraper" / "scraper.py"
ELO     = ROOT / "models" / "elo_engine.py"
UNIFY   = ROOT / "models" / "unify_rankings.py"


def run(cmd: list, label: str):
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    result = subprocess.run(cmd, cwd=str(ROOT))
    if result.returncode != 0:
        print(f"[WARN] {label} salió con código {result.returncode}")
    return result.returncode


failed = []
for div in DIVISIONS:
    rc = run(
        [sys.executable, str(SCRAPER), "--division", div, "--output", "data"],
        f"SCRAPER: {div}",
    )
    if rc != 0:
        failed.append(f"scraper:{div}")

    rc = run(
        [sys.executable, str(ELO), "--division", div, "--output", "data"],
        f"ELO: {div}",
    )
    if rc != 0:
        failed.append(f"elo:{div}")

# After all divisions: unify cross-division fighter assignments
run(
    [sys.executable, str(UNIFY), "--output", "data"],
    "UNIFY: cross-division rankings",
)

print("\n" + "="*60)
if failed:
    print(f"TERMINADO con errores en: {', '.join(failed)}")
else:
    print("TERMINADO — todas las divisiones actualizadas y unificadas.")
print("="*60)
