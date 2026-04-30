import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st
import plotly.graph_objects as go
import pandas as pd
from backend.services import build_matchmaking, build_ranking_response

st.set_page_config(page_title="Matchmaking — UFCelo.gg", page_icon="UFC", layout="wide")

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
SKILL_LABELS = {
    "Striking": "Striking", "Grappling": "Grappling", "Defensa": "Defense",
    "Consistencia": "Consistency", "Finish Rate": "Finish Rate",
    "Cardio/Durabilidad": "Cardio / Durability", "Presión": "Pressure",
}

st.title("Matchmaking Engine")
st.caption("Surfaces the best potential matchups using competitiveness (ELO parity) and style contrast.")

available = [d for d in DIVISIONS if build_ranking_response(d)]
c1, c2 = st.columns([2, 1])
with c1:
    div = st.selectbox("Division", available, format_func=lambda d: DIVISION_LABELS.get(d, d.title()))
with c2:
    top_n = st.slider("Top N fighters to consider", 5, 25, 15)

matchups = build_matchmaking(div, top_n=top_n)
if not matchups:
    st.warning("No matchmaking data available.")
    st.stop()

# ── Score explanation ──────────────────────────────────────────────────────
with st.expander("Matchmaking score explained"):
    st.markdown("""
    | Component | Weight | Definition |
    |---|---|---|
    | **Competitiveness** | 70% | How even the ELO matchup is. ELO diff of 0 = 1.0, diff of 200 = ~0.0 |
    | **Style contrast** | 30% | Euclidean distance across 7 skill dimensions (normalized). High = striker vs grappler, etc. |
    | **Matchup score** | — | `0.70 × competitiveness + 0.30 × contrast` |

    Top-right corner of the scatter chart = most competitive **and** most stylistically interesting.
    """)

st.divider()

# ── Top matchups table ─────────────────────────────────────────────────────
rows = []
for i, m in enumerate(matchups, 1):
    rows.append({
        "#": i,
        "Fighter A": m["fighter_a_name"],
        "ELO A": round(m["elo_a"], 1),
        "Fighter B": m["fighter_b_name"],
        "ELO B": round(m["elo_b"], 1),
        "ΔELO": round(abs(m["elo_difference"]), 1),
        "Competitiveness": round(m["competitiveness_score"] * 100, 1),
        "Contrast": round(m["skill_contrast_score"] * 100, 1),
        "Score": round(m["matchup_score"] * 100, 1),
        "Key dimension": SKILL_LABELS.get(m.get("key_dimension", "—"), m.get("key_dimension", "—")),
        "Prob A": f"{m['probability_a']*100:.1f}%",
        "Prob B": f"{m['probability_b']*100:.1f}%",
    })

df = pd.DataFrame(rows)
st.dataframe(
    df,
    use_container_width=True,
    hide_index=True,
    column_config={
        "Competitiveness": st.column_config.ProgressColumn(format="%.1f", min_value=0, max_value=100),
        "Score": st.column_config.ProgressColumn(format="%.1f", min_value=0, max_value=100),
    },
    height=500,
)

st.divider()

# ── Matchup detail card ────────────────────────────────────────────────────
st.subheader("Matchup detail")
matchup_labels = [f"#{i+1}  {m['fighter_a_name']} vs {m['fighter_b_name']}" for i, m in enumerate(matchups)]
sel_idx = st.selectbox("Select a matchup", range(len(matchup_labels)), format_func=lambda i: matchup_labels[i])

m = matchups[sel_idx]
fa_name = m["fighter_a_name"]
fb_name = m["fighter_b_name"]
pa = m["probability_a"]
pb = m["probability_b"]

col1, col2, col3, col4 = st.columns(4)
col1.metric("Matchup Score", f"{m['matchup_score']*100:.1f}")
col2.metric("ELO Δ", f"{abs(m['elo_difference']):.1f}")
col3.metric("Key dimension", SKILL_LABELS.get(m.get("key_dimension", "—"), m.get("key_dimension", "—")))
col4.metric("Dim. gap", f"{m.get('key_dimension_diff', 0):.1f} pts")

# Probability bar
fig = go.Figure(go.Bar(
    x=[pa * 100, pb * 100],
    y=[fa_name, fb_name],
    orientation="h",
    marker_color=["#E8281E" if pa >= pb else "#555", "#E8281E" if pb > pa else "#555"],
    text=[f"{pa*100:.1f}%", f"{pb*100:.1f}%"],
    textposition="inside",
    textfont=dict(size=15, color="white"),
))
fig.update_layout(
    height=120, margin=dict(l=0, r=0, t=5, b=0),
    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    xaxis=dict(range=[0, 100], showticklabels=False, showgrid=False, zeroline=False),
    yaxis=dict(showgrid=False),
    font=dict(color="#FAFAFA", size=14),
)
st.plotly_chart(fig, use_container_width=True)

# Score breakdown gauges
gc1, gc2, gc3 = st.columns(3)
for col, val, label, color in [
    (gc1, m["competitiveness_score"] * 100, "Competitiveness", "#4CAF50"),
    (gc2, m["skill_contrast_score"] * 100, "Style Contrast", "#4455FF"),
    (gc3, m["matchup_score"] * 100, "Total Score", "#E8281E"),
]:
    fig_g = go.Figure(go.Indicator(
        mode="gauge+number",
        value=val,
        title={"text": label, "font": {"color": "#FAFAFA", "size": 13}},
        gauge={
            "axis": {"range": [0, 100], "tickfont": {"color": "#FAFAFA"}},
            "bar": {"color": color},
            "bgcolor": "#1a1a1a",
            "bordercolor": "#333",
        },
        number={"font": {"color": "#FAFAFA"}},
    ))
    fig_g.update_layout(height=200, paper_bgcolor="rgba(0,0,0,0)", margin=dict(l=10, r=10, t=40, b=10))
    col.plotly_chart(fig_g, use_container_width=True)

# ── Scatter map ────────────────────────────────────────────────────────────
st.divider()
st.subheader("Matchup landscape")
st.caption("X = competitiveness · Y = style contrast · Top-right corner = ideal matchup")

fig_s = go.Figure()
for i, mu in enumerate(matchups):
    label = f"{mu['fighter_a_name']} vs {mu['fighter_b_name']}"
    selected = (i == sel_idx)
    fig_s.add_trace(go.Scatter(
        x=[mu["competitiveness_score"] * 100],
        y=[mu["skill_contrast_score"] * 100],
        mode="markers+text",
        marker=dict(
            size=14 if selected else 9,
            color="#E8281E" if selected else "#4455FF",
            line=dict(color="#fff", width=2 if selected else 0),
        ),
        text=[f"#{i+1}"] if selected else [""],
        textposition="top center",
        textfont=dict(color="#FAFAFA", size=11),
        hovertext=label,
        hovertemplate=f"<b>{label}</b><br>Comp: %{{x:.1f}}  Contrast: %{{y:.1f}}<extra></extra>",
        showlegend=False,
    ))

fig_s.update_layout(
    height=350,
    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    xaxis=dict(title="Competitiveness (%)", showgrid=True, gridcolor="#222", range=[0, 105]),
    yaxis=dict(title="Style Contrast (%)", showgrid=True, gridcolor="#222", range=[0, 105]),
    font=dict(color="#FAFAFA"),
    margin=dict(l=0, r=0, t=10, b=0),
)
st.plotly_chart(fig_s, use_container_width=True)
