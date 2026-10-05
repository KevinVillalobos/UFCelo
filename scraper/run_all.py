"""Full data update: scrape all 8 divisions, run the unified ELO engine, sync official UFC rankings."""
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
    rc = run(
        [sys.executable, str(SCRAPER), "--division", div, "--output", "data"],
        f"SCRAPER: {div}",
    )
    if rc != 0:
        failed.append(f"scraper:{div}")

# One ELO per fighter: a single pass over every division's fights, chronologically.
rc = run([sys.executable, str(ELO), "--output", "data"], "ELO: todas las divisiones (ELO unificado)")
if rc != 0:
    failed.append("elo")

# Official UFC top 15 + champions (ufc.com) -> data/ufc_rankings.json, data/champions.json
rc = run([sys.executable, "-m", "backend.ufc_rankings"], "UFC: rankings oficiales y campeones")
if rc != 0:
    failed.append("ufc-rankings")

print("\n" + "="*60)
if failed:
    print(f"TERMINADO con errores en: {', '.join(failed)}")
else:
    print("TERMINADO — todas las divisiones actualizadas.")
print("="*60)
