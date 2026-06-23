"""Runs scraper + ELO engine for all 8 divisions in sequence."""
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
    slug = div.replace(" ", "_")

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

print("\n" + "="*60)
if failed:
    print(f"TERMINADO con errores en: {', '.join(failed)}")
else:
    print("TERMINADO — todas las divisiones actualizadas.")
print("="*60)
