import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st
import pandas as pd
from backend.services import build_ranking_response
from backend.data_loader import load_rankings

st.set_page_config(page_title="Rankings — UFCelo.gg", layout="wide")

DIVISIONS = ["heavyweight", "light heavyweight", "middleweight", "welterweight", "lightweight", "featherweight", "bantamweight", "flyweight"]
DIVISION_LABELS = {
    "heavyweight": "Heavyweight 265",
    "lightweight": "Lightweight 155",
    "welterweight": "Welterweight 170",
    "featherweight": "Featherweight 145",
    "middleweight": "Middleweight 185",
    "flyweight": "Flyweight 125",
    "light heavyweight": "Light Heavyweight 205",
    "bantamweight": "Bantamweight 135",
}

st.title("ELO Rankings")
st.caption(
    "Active fighters ranked by ELO with inactivity decay. Retired fighters excluded. "
    "[C] = current UFC champion, always shown at #1 regardless of ELO."
)

available = [d for d in DIVISIONS if build_ranking_response(d)]
c1, c2 = st.columns([2, 1])
with c1:
    div = st.selectbox("Division", available, format_func=lambda d: DIVISION_LABELS.get(d, d.title()))
with c2:
    alltime = st.toggle("All-time (by peak ELO)", value=False)

rankings = build_ranking_response(div, alltime=alltime) if alltime else None
raw_rankings = load_rankings(div, alltime=alltime)
active_rankings = build_ranking_response(div)  # always get with champion injection

if alltime:
    display_rankings = rankings
else:
    display_rankings = active_rankings

if not display_rankings:
    st.warning("No data for this division.")
    st.stop()

rows = []
for i, f in enumerate(display_rankings, 1):
    streak = f.get("streak", 0)
    is_champ = f.get("is_champion", False)

    if streak >= 3:
        streak_str = f"+{streak} W"
    elif streak <= -3:
        streak_str = f"{streak} L"
    else:
        streak_str = str(streak) if streak != 0 else "—"

    visitor_label = f.get("visitor_label")
    name_display = (
        f"[C] {f.get('fighter_name', '—')}" if is_champ
        else f"{f.get('fighter_name', '—')}  [{visitor_label}]" if visitor_label
        else f.get("fighter_name", "—")
    )
    rank_display = f.get("rank", i) if alltime else i

    rows.append({
        "Rank": rank_display,
        "Fighter": name_display,
        "ELO": round(f.get("elo", 0), 1),
        "Peak ELO": round(f.get("peak_elo", 0), 1) if f.get("peak_elo") else "—",
        "Peak vs": f.get("peak_elo_opponent", "—"),
        "Record": f.get("record", "—"),
        "Fights": f.get("fight_count", 0),
        "Last Fight": f.get("last_fight_date", "—"),
        "Streak": streak_str,
    })

df = pd.DataFrame(rows)

st.markdown(f"**{len(df)} fighters** — {DIVISION_LABELS.get(div, div.title())}")

st.dataframe(
    df,
    use_container_width=True,
    hide_index=True,
    column_config={
        "ELO": st.column_config.NumberColumn(format="%.1f"),
        "Peak ELO": st.column_config.NumberColumn(format="%.1f"),
    },
    height=700,
)

# ── Division stats sidebar ─────────────────────────────────────────────────
with st.expander("Division stats"):
    elos = [f.get("elo", 0) for f in display_rankings]
    if elos:
        import statistics
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Mean ELO", f"{statistics.mean(elos):.0f}")
        c2.metric("Median ELO", f"{statistics.median(elos):.0f}")
        c3.metric("Std Dev", f"{statistics.stdev(elos):.0f}" if len(elos) > 1 else "—")
        c4.metric("ELO spread (max-min)", f"{max(elos)-min(elos):.0f}")
