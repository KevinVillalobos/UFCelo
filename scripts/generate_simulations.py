"""
Genera simulaciones del top-1 vs top-5 contendientes y top-10 matchups por división.
Ejecutar desde la raíz del proyecto: python scripts/generate_simulations.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from backend.services import build_fight_simulation, build_matchmaking, build_ranking_response

DIVISIONS = ["heavyweight", "light heavyweight", "middleweight", "welterweight", "lightweight", "featherweight", "bantamweight", "flyweight"]
DATA_DIR = Path("data")


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def run_simulations():
    all_simulations = {}

    for division in DIVISIONS:
        print(f"\n{'='*50}")
        print(f"  {division.upper()} — Simulaciones")
        print(f"{'='*50}")

        rankings = build_ranking_response(division)
        if not rankings:
            print(f"  [!] Sin rankings para {division}")
            continue

        top6 = rankings[:6]
        if len(top6) < 2:
            print(f"  [!] Menos de 2 peleadores activos en {division}")
            continue

        champion = top6[0]
        contenders = top6[1:]

        div_simulations = []
        for contender in contenders:
            sim = build_fight_simulation(
                champion["fighter_id"],
                contender["fighter_id"],
                n=1000,
                rounds=5,
                division=division,
            )
            if not sim:
                print(f"  [!] No se pudo simular: {champion['fighter_name']} vs {contender['fighter_name']}")
                continue

            div_simulations.append(sim)
            winner_name = sim["fighter_a_name"] if sim["probability_a"] >= 0.5 else sim["fighter_b_name"]
            prob = max(sim["probability_a"], sim["probability_b"])
            print(
                f"  #{rankings.index(champion)+1} {champion['fighter_name']} ({champion['elo']:.0f})"
                f" vs #{rankings.index(contender)+1} {contender['fighter_name']} ({contender['elo']:.0f})"
                f"  →  {winner_name} {prob*100:.1f}%  |  {sim['most_likely_outcome']}"
            )

        all_simulations[division] = div_simulations
        out_path = DATA_DIR / f"simulation_{division}_top5.json"
        write_json(out_path, div_simulations)
        print(f"  Guardado → {out_path}")

    write_json(DATA_DIR / "simulation_all_divisions.json", all_simulations)
    print(f"\n  Guardado completo → data/simulation_all_divisions.json")


def run_matchmaking():
    all_matchups = {}

    for division in DIVISIONS:
        print(f"\n{'='*50}")
        print(f"  {division.upper()} — Top 10 Matchups")
        print(f"{'='*50}")

        matchups = build_matchmaking(division, top_n=10)
        if not matchups:
            print(f"  [!] Sin matchups para {division}")
            continue

        all_matchups[division] = matchups
        for i, m in enumerate(matchups, 1):
            print(
                f"  #{i:2d}  {m['fighter_a_name']} ({m['elo_a']:.0f})"
                f" vs {m['fighter_b_name']} ({m['elo_b']:.0f})"
                f"  score={m['matchup_score']:.3f}  diff_ELO={m['elo_difference']:.0f}"
                f"  clave={m['key_dimension']}"
            )

        out_path = DATA_DIR / f"matchmaking_{division}.json"
        write_json(out_path, matchups)
        print(f"  Guardado → {out_path}")

    write_json(DATA_DIR / "matchmaking_all_divisions.json", all_matchups)
    print(f"\n  Guardado completo → data/matchmaking_all_divisions.json")


if __name__ == "__main__":
    run_simulations()
    run_matchmaking()
