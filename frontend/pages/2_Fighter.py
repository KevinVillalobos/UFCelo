import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st
import plotly.graph_objects as go
import pandas as pd
from backend.services import build_fighter_profile, build_ranking_response

st.set_page_config(page_title="Fighter — UFCelo.gg", page_icon="UFC", layout="wide")

DIVISIONS = ["heavyweight", "light heavyweight", "middleweight", "welterweight", "lightweight", "featherweight", "bantamweight", "flyweight"]
DIVISION_LABELS = {
    "heavyweight":      "Heavyweight 265",
    "light heavyweight": "Light Heavyweight 205",
    "middleweight":     "Middleweight 185",
    "welterweight":     "Welterweight 170",
    "lightweight":      "Lightweight 155",
    "featherweight":    "Featherweight 145",
    "bantamweight":     "Bantamweight 135",
    "flyweight":        "Flyweight 125",
}
SKILL_LABELS = {
    "Striking":         "Striking",
    "Grappling":        "Grappling",
    "Defensa":          "Defense",
    "Consistencia":     "Consistency",
    "Finish Rate":      "Finish Rate",
    "Cardio/Durabilidad": "Cardio / Durability",
    "Presión":          "Pressure",
}
SKILL_DIMS = list(SKILL_LABELS.keys())

st.title("Fighter Profile")

available = [d for d in DIVISIONS if build_ranking_response(d)]
c1, c2 = st.columns([1, 2])
with c1:
    div = st.selectbox("Division", available, format_func=lambda d: DIVISION_LABELS.get(d, d.title()))

rankings = build_ranking_response(div)
if not rankings:
    st.warning("No data for this division.")
    st.stop()

names = [f["fighter_name"] for f in rankings]
ids   = [f["fighter_id"]   for f in rankings]

with c2:
    selected_name = st.selectbox("Fighter", names)

fighter_id = ids[names.index(selected_name)]
profile = build_fighter_profile(fighter_id, div)

if not profile:
    st.error("Fighter not found.")
    st.stop()

# ── Header ─────────────────────────────────────────────────────────────────
rank_entry = next((f for f in rankings if f["fighter_id"] == fighter_id), None)
rank_num   = rankings.index(rank_entry) + 1 if rank_entry else "—"
streak     = rank_entry.get("streak", 0) if rank_entry else 0
is_champ   = rank_entry.get("is_champion", False) if rank_entry else False

if is_champ:
    st.markdown(
        "<span style='background:#E8281E; color:white; padding:2px 10px; "
        "border-radius:4px; font-size:0.82rem; font-weight:700; letter-spacing:1px;'>"
        "UFC CHAMPION</span>",
        unsafe_allow_html=True,
    )
    st.markdown("")

streak_delta = (
    f"+{streak} W streak" if streak >= 3
    else (f"{streak} L streak" if streak <= -3 else None)
)

col_h1, col_h2, col_h3, col_h4, col_h5 = st.columns(5)
col_h1.metric("Current ELO", f"{profile['elo']:.1f}")

elo_history = profile.get("elo_history", [])
peak_elo   = max((h["elo"] for h in elo_history), default=0) if elo_history else profile.get("elo", 0)
peak_entry = max(elo_history, key=lambda h: h["elo"]) if elo_history else {}
col_h2.metric(
    "Peak ELO", f"{peak_elo:.0f}",
    help=f"vs {peak_entry.get('opponent_name','?')} on {peak_entry.get('date','?')}",
)
col_h3.metric("Record", profile.get("record", "—"))
col_h4.metric("Division Rank", f"#{rank_num}" if rank_num != "—" else "—", delta=streak_delta)
col_h5.metric("Fights in DB", profile.get("fight_count", "—"))

st.divider()

# ── ELO History chart ──────────────────────────────────────────────────────
history = profile.get("elo_history", [])
if history:
    dates      = [h["date"] for h in history]
    elos       = [h["elo"] for h in history]
    results    = [h.get("result", "") for h in history]
    opps       = [h.get("opponent_name", "") for h in history]
    methods    = [h.get("method", "") for h in history]
    elo_deltas = [h.get("elo_change") for h in history]
    events_    = [h.get("event", "") for h in history]
    title_flags = [h.get("is_title_fight", False) for h in history]

    colors = ["#4CAF50" if r == "Win" else "#E8281E" if r == "Loss" else "#888" for r in results]

    hover_texts = []
    for r, opp, meth, delta, ev, is_title in zip(results, opps, methods, elo_deltas, events_, title_flags):
        delta_str  = f"  ({delta:+.1f})" if delta is not None else ""
        title_note = "  [TITLE FIGHT]" if is_title else ""
        hover_texts.append(
            f"<b>{r}</b> vs {opp}<br>"
            f"Method: {meth}{title_note}<br>"
            f"ELO{delta_str}<br>"
            f"{ev}"
        )

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=dates, y=elos,
        mode="lines+markers",
        line=dict(color="#E8281E", width=2),
        marker=dict(color=colors, size=9, line=dict(color="#fff", width=1)),
        text=hover_texts,
        hovertemplate="%{text}<extra></extra>",
        name="ELO",
    ))
    fig.add_hline(y=1500, line_dash="dot", line_color="#555", annotation_text="Baseline 1500")
    fig.update_layout(
        title="ELO History",
        height=360,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#FAFAFA"),
        xaxis=dict(showgrid=False, title=""),
        yaxis=dict(showgrid=True, gridcolor="#222", title="ELO"),
        hovermode="x unified",
        margin=dict(l=0, r=0, t=40, b=0),
    )
    st.plotly_chart(fig, use_container_width=True)

    # ── Fight log ──────────────────────────────────────────────────────────
    with st.expander("Full fight log"):
        log_rows = []
        for h in reversed(history):
            delta = h.get("elo_change")
            title_note = " [T]" if h.get("is_title_fight") else ""
            log_rows.append({
                "Date":      h.get("date", "—"),
                "Result":    h.get("result", "—"),
                "Opponent":  h.get("opponent_name", "—"),
                "Method":    (h.get("method") or "—") + title_note,
                "Rd":        h.get("round", "—"),
                "Time":      h.get("time", "—"),
                "ELO":       round(h.get("elo", 0), 1),
                "Delta ELO": round(delta, 1) if delta is not None else None,
                "Event":     h.get("event", "—"),
            })
        df_log = pd.DataFrame(log_rows)
        st.dataframe(
            df_log,
            use_container_width=True,
            hide_index=True,
            column_config={
                "ELO":       st.column_config.NumberColumn(format="%.1f"),
                "Delta ELO": st.column_config.NumberColumn(format="%+.1f"),
            },
        )

st.divider()

# ── Skill radar ────────────────────────────────────────────────────────────
skill = profile.get("skill_score", {})
if skill:
    display_dims = [SKILL_LABELS.get(d, d) for d in SKILL_DIMS]
    vals = [skill.get(d, 50) for d in SKILL_DIMS]

    fig_r = go.Figure(go.Scatterpolar(
        r=vals + [vals[0]],
        theta=display_dims + [display_dims[0]],
        fill="toself",
        fillcolor="rgba(232,40,30,0.25)",
        line=dict(color="#E8281E", width=2),
        name=selected_name,
    ))
    fig_r.update_layout(
        polar=dict(
            bgcolor="rgba(0,0,0,0)",
            radialaxis=dict(range=[0, 100], showticklabels=True, tickfont=dict(size=9), gridcolor="#333"),
            angularaxis=dict(gridcolor="#333"),
        ),
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#FAFAFA"),
        height=380,
        margin=dict(l=50, r=50, t=20, b=20),
        showlegend=False,
    )
    st.plotly_chart(fig_r, use_container_width=True)

    comp = profile.get("skill_composite")
    if comp:
        st.caption(f"Composite skill score: **{comp:.1f} / 100**")

    with st.expander("Skill score breakdown"):
        skill_rows = []
        for dim in SKILL_DIMS:
            v     = skill.get(dim, 50)
            label = SKILL_LABELS.get(dim, dim)
            tier  = "Elite" if v >= 80 else "Above avg" if v >= 65 else "Average" if v >= 45 else "Below avg"
            skill_rows.append({"Dimension": label, "Score": round(v, 1), "Tier": tier})
        st.dataframe(
            pd.DataFrame(skill_rows),
            use_container_width=True,
            hide_index=True,
            column_config={
                "Score": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.1f")
            },
        )
