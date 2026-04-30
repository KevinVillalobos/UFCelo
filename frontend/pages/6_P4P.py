import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import statistics
from backend.services import build_ranking_response
from backend.data_loader import load_champions

st.set_page_config(page_title="P4P Rankings — UFCelo.gg", page_icon="UFC", layout="wide")

DIVISIONS = ["heavyweight", "light heavyweight", "middleweight", "welterweight", "lightweight", "featherweight", "bantamweight", "flyweight"]
DIVISION_LABELS = {
    "heavyweight":      "HW",
    "light heavyweight": "LHW",
    "middleweight":     "MW",
    "welterweight":     "WW",
    "lightweight":      "LW",
    "featherweight":    "FW",
    "bantamweight":     "BW",
    "flyweight":        "FL",
}
DIVISION_COLORS = {
    "heavyweight":      "#E8281E",
    "light heavyweight": "#FF4444",
    "middleweight":     "#AA44AA",
    "welterweight":     "#4455FF",
    "lightweight":      "#FF8C00",
    "featherweight":    "#44AA44",
    "bantamweight":     "#44AACC",
    "flyweight":        "#22CCAA",
}

st.title("Pound-for-Pound ELO Rankings")
st.caption(
    "Cross-division comparison using two methods: **Raw ELO** (direct comparison, all divisions start at 1500) "
    "and **Normalized ELO** (z-score within division, removes divisional inflation/deflation)."
)

# ── Load all divisions ─────────────────────────────────────────────────────
all_fighters = []
div_stats = {}
champions = load_champions()
champ_ids = {info["fighter_id"] for info in champions.values() if isinstance(info, dict)}

for div in DIVISIONS:
    rankings = build_ranking_response(div)
    if not rankings:
        continue
    elos = [f["elo"] for f in rankings]
    if len(elos) < 2:
        continue
    mean_elo = statistics.mean(elos)
    std_elo  = statistics.stdev(elos)
    div_stats[div] = {"mean": mean_elo, "std": std_elo, "count": len(elos)}
    for f in rankings:
        z_score = (f["elo"] - mean_elo) / std_elo if std_elo > 0 else 0.0
        all_fighters.append({
            "fighter_id":   f["fighter_id"],
            "fighter_name": f["fighter_name"],
            "division":     div,
            "div_label":    DIVISION_LABELS[div],
            "elo":          f["elo"],
            "z_score":      z_score,
            "peak_elo":     f.get("peak_elo"),
            "record":       f.get("record", "—"),
            "streak":       f.get("streak", 0),
            "is_champion":  f.get("is_champion", False),
        })

if not all_fighters:
    st.warning("No data available.")
    st.stop()

# ── Mode toggle ────────────────────────────────────────────────────────────
mode = st.radio(
    "Ranking method",
    ["Raw ELO", "Normalized ELO (z-score)"],
    horizontal=True,
    help="Raw: direct ELO comparison. Normalized: how many std devs above the divisional average.",
)

sort_key = "elo" if mode == "Raw ELO" else "z_score"
sorted_fighters = sorted(all_fighters, key=lambda x: x[sort_key], reverse=True)

# ── Table ──────────────────────────────────────────────────────────────────
top_n = st.slider("Show top N", 10, 100, 50)
display = sorted_fighters[:top_n]

rows = []
for i, f in enumerate(display, 1):
    streak = f["streak"]
    if streak >= 3:
        streak_str = f"+{streak} W"
    elif streak <= -3:
        streak_str = f"{streak} L"
    else:
        streak_str = str(streak) if streak != 0 else "—"

    name_display = ("[C] " if f["is_champion"] else "") + f["fighter_name"]
    rows.append({
        "P4P Rank": i,
        "Fighter": name_display,
        "Division": f["div_label"],
        "ELO": round(f["elo"], 1),
        "Z-score": round(f["z_score"], 2),
        "Peak ELO": round(f["peak_elo"], 1) if f.get("peak_elo") else "—",
        "Record": f["record"],
        "Streak": streak_str,
    })

df = pd.DataFrame(rows)

def highlight_division(row):
    div_full = display[row.name]["division"]
    color = DIVISION_COLORS.get(div_full, "#333")
    return [f"border-left: 3px solid {color}" if col == "Division" else "" for col in row.index]

st.dataframe(
    df,
    use_container_width=True,
    hide_index=True,
    column_config={
        "ELO": st.column_config.NumberColumn(format="%.1f"),
        "Z-score": st.column_config.NumberColumn(format="%.2f", help="Standard deviations above division mean"),
        "Peak ELO": st.column_config.NumberColumn(format="%.1f"),
    },
    height=700,
)

st.divider()

# ── ELO distribution by division ──────────────────────────────────────────
st.subheader("ELO distribution by division")
st.caption("Box plots showing the ELO spread within each division — useful for spotting outliers.")

fig_box = go.Figure()
for div in DIVISIONS:
    div_fighters = [f for f in all_fighters if f["division"] == div]
    if not div_fighters:
        continue
    elos = [f["elo"] for f in div_fighters]
    fig_box.add_trace(go.Box(
        y=elos,
        name=DIVISION_LABELS[div],
        marker_color=DIVISION_COLORS[div],
        boxmean=True,
        line=dict(color=DIVISION_COLORS[div]),
    ))

fig_box.update_layout(
    height=400,
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(color="#FAFAFA"),
    yaxis=dict(showgrid=True, gridcolor="#222", title="ELO"),
    xaxis=dict(showgrid=False),
    showlegend=False,
    margin=dict(l=0, r=0, t=10, b=0),
)
st.plotly_chart(fig_box, use_container_width=True)

# ── Division stats table ───────────────────────────────────────────────────
st.subheader("Divisional ELO stats")
stats_rows = []
for div in DIVISIONS:
    s = div_stats.get(div)
    if not s:
        continue
    stats_rows.append({
        "Division": DIVISION_LABELS[div],
        "Active fighters": s["count"],
        "Mean ELO": round(s["mean"], 1),
        "Std Dev": round(s["std"], 1),
        "CV (%)": round((s["std"] / s["mean"]) * 100, 2) if s["mean"] > 0 else "—",
    })
st.dataframe(
    pd.DataFrame(stats_rows),
    use_container_width=True,
    hide_index=True,
    column_config={
        "Mean ELO": st.column_config.NumberColumn(format="%.1f"),
        "Std Dev": st.column_config.NumberColumn(format="%.1f"),
        "CV (%)": st.column_config.NumberColumn(format="%.2f", help="Coefficient of variation — higher = more spread"),
    },
)

# ── Top 10 P4P bar chart ───────────────────────────────────────────────────
st.divider()
st.subheader(f"Top 10 P4P — {mode}")
top10 = sorted_fighters[:10]
colors_bar = [DIVISION_COLORS.get(f["division"], "#888") for f in top10]
names_bar  = [("[C] " if f["is_champion"] else "") + f["fighter_name"] + f"  [{DIVISION_LABELS[f['division']]}]" for f in top10]
vals_bar   = [f[sort_key] for f in top10]

fig_bar = go.Figure(go.Bar(
    x=vals_bar[::-1],
    y=names_bar[::-1],
    orientation="h",
    marker_color=colors_bar[::-1],
    text=[f"{v:.1f}" for v in vals_bar[::-1]],
    textposition="inside",
    textfont=dict(color="white", size=12),
))
fig_bar.update_layout(
    height=380,
    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    font=dict(color="#FAFAFA"),
    xaxis=dict(showgrid=True, gridcolor="#222", title="Z-score" if sort_key == "z_score" else "ELO"),
    yaxis=dict(showgrid=False),
    margin=dict(l=0, r=0, t=10, b=0),
)
st.plotly_chart(fig_bar, use_container_width=True)
