import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st
import plotly.graph_objects as go
import pandas as pd
from backend.services import build_prediction, build_ranking_response
from backend.data_loader import get_skill_score_by_id

st.set_page_config(page_title="Predictor — UFCelo.gg", page_icon="UFC", layout="wide")

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
    "Striking": "Striking",
    "Grappling": "Grappling",
    "Defensa": "Defense",
    "Consistencia": "Consistency",
    "Finish Rate": "Finish Rate",
    "Cardio/Durabilidad": "Cardio / Durability",
    "Presión": "Pressure",
}
SKILL_DIMS = list(SKILL_LABELS.keys())

st.title("Fight Predictor")
st.caption("Blends ELO + skill scores (Striking, Grappling, Defense, Consistency, Finish Rate, Cardio, Pressure) to predict the most likely winner.")

available = [d for d in DIVISIONS if build_ranking_response(d)]
div = st.selectbox("Division", available, format_func=lambda d: DIVISION_LABELS.get(d, d.title()))

rankings = build_ranking_response(div)
if not rankings:
    st.warning("No data.")
    st.stop()

names = [f["fighter_name"] for f in rankings]
ids   = [f["fighter_id"]   for f in rankings]
elos  = {f["fighter_id"]: f["elo"] for f in rankings}
champs = {f["fighter_id"]: f.get("is_champion", False) for f in rankings}

c1, c2 = st.columns(2)
with c1:
    fa_name = st.selectbox("Fighter A", names, key="pred_fa")
    fa_id = ids[names.index(fa_name)]
    champ_a = "[C] " if champs.get(fa_id) else ""
    st.caption(f"{champ_a}ELO: **{elos.get(fa_id, 0):.1f}**")
with c2:
    fb_name = st.selectbox("Fighter B", names, index=min(1, len(names)-1), key="pred_fb")
    fb_id = ids[names.index(fb_name)]
    champ_b = "[C] " if champs.get(fb_id) else ""
    st.caption(f"{champ_b}ELO: **{elos.get(fb_id, 0):.1f}**")

if fa_name == fb_name:
    st.warning("Select two different fighters.")
    st.stop()

pred = build_prediction(fa_id, fb_id, div)
if not pred:
    st.error("Could not compute prediction.")
    st.stop()

pa = pred["probability_a"]
pb = pred["probability_b"]
winner = fa_name if pa >= pb else fb_name
prob   = max(pa, pb)

st.divider()

# ── Probability bar ────────────────────────────────────────────────────────
fig = go.Figure(go.Bar(
    x=[pa * 100, pb * 100],
    y=[fa_name, fb_name],
    orientation="h",
    marker_color=["#E8281E" if pa >= pb else "#445", "#E8281E" if pb > pa else "#445"],
    text=[f"{pa*100:.1f}%", f"{pb*100:.1f}%"],
    textposition="inside",
    textfont=dict(size=16, color="white"),
))
fig.update_layout(
    height=130, margin=dict(l=0, r=0, t=5, b=0),
    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    xaxis=dict(range=[0, 100], showticklabels=False, showgrid=False, zeroline=False),
    yaxis=dict(showgrid=False),
    font=dict(color="#FAFAFA", size=14),
)
st.plotly_chart(fig, use_container_width=True)

m1, m2, m3, m4 = st.columns(4)
m1.metric("Predicted winner", winner)
m2.metric("Win probability", f"{prob*100:.1f}%")
m3.metric("Predicted method", pred.get("method_prediction", "—"))
m4.metric("ELO edge", f"{pred.get('elo_difference', 0):+.0f}", help="ELO difference A − B")

elo_diff = pred.get("elo_difference", 0)
key_adv  = pred.get("key_advantage", "—")
# Translate key advantage label
key_adv_display = SKILL_LABELS.get(key_adv, key_adv)
st.caption(
    f"ELO difference: **{elo_diff:+.1f}**  ·  "
    f"Key advantage dimension: **{key_adv_display}**  ·  "
    f"ELO probability (pure): **{pred.get('elo_probability_a', pa)*100:.1f}%** — "
    f"skill adjustment shifts it to **{pa*100:.1f}%**"
)

st.divider()

# ── Skill comparison radar ─────────────────────────────────────────────────
skill_item_a = get_skill_score_by_id(fa_id, div) or {}
skill_item_b = get_skill_score_by_id(fb_id, div) or {}
skill_a = skill_item_a.get("skill_score", {})
skill_b = skill_item_b.get("skill_score", {})

if skill_a and skill_b:
    display_dims = [SKILL_LABELS.get(d, d) for d in SKILL_DIMS]
    vals_a = [skill_a.get(d, 50) for d in SKILL_DIMS]
    vals_b = [skill_b.get(d, 50) for d in SKILL_DIMS]

    fig_r = go.Figure()
    fig_r.add_trace(go.Scatterpolar(
        r=vals_a + [vals_a[0]], theta=display_dims + [display_dims[0]],
        fill="toself", fillcolor="rgba(232,40,30,0.20)",
        line=dict(color="#E8281E", width=2), name=fa_name,
    ))
    fig_r.add_trace(go.Scatterpolar(
        r=vals_b + [vals_b[0]], theta=display_dims + [display_dims[0]],
        fill="toself", fillcolor="rgba(68,85,255,0.20)",
        line=dict(color="#4455FF", width=2), name=fb_name,
    ))
    fig_r.update_layout(
        polar=dict(
            bgcolor="rgba(0,0,0,0)",
            radialaxis=dict(range=[0, 100], showticklabels=True, tickfont=dict(size=9), gridcolor="#333"),
            angularaxis=dict(gridcolor="#333"),
        ),
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#FAFAFA"),
        height=420,
        legend=dict(orientation="h", yanchor="bottom", y=-0.15, xanchor="center", x=0.5),
        margin=dict(l=60, r=60, t=20, b=40),
    )
    st.plotly_chart(fig_r, use_container_width=True)

    # ── Advantage table ────────────────────────────────────────────────────
    adv_rows = []
    for dim in SKILL_DIMS:
        label = SKILL_LABELS.get(dim, dim)
        a_val = skill_a.get(dim, 50)
        b_val = skill_b.get(dim, 50)
        diff = a_val - b_val
        adv_rows.append({
            "Dimension": label,
            fa_name: round(a_val, 1),
            fb_name: round(b_val, 1),
            "Advantage": round(diff, 1),
            "Edge": fa_name if diff >= 0 else fb_name,
        })
    df_adv = pd.DataFrame(adv_rows).sort_values("Advantage")
    st.dataframe(
        df_adv,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Advantage": st.column_config.NumberColumn(format="%+.1f"),
            fa_name: st.column_config.NumberColumn(format="%.1f"),
            fb_name: st.column_config.NumberColumn(format="%.1f"),
        },
    )

    # ── Model explanation ──────────────────────────────────────────────────
    with st.expander("How the prediction works"):
        st.markdown(f"""
        **ELO base probability** — derived from ELO difference using the standard formula:
        `P(A wins) = 1 / (1 + 10^((ELO_B - ELO_A) / 400))`, capped at ±250 ELO diff (~82% max).

        **Skill adjustment** — up to ±10% shift based on composite skill score difference.
        The composite is a weighted average: Striking 20%, Defense 20%, Grappling 15%,
        Consistency 15%, Finish Rate 10%, Cardio 10%, Pressure 10%.

        **Method prediction** — predicted from the favored fighter's dominant finishing style.
        If Grappling > Striking and both ≥ 65 → SUB. If Striking ≥ 65 and Finish Rate ≥ 55 → KO/TKO. Otherwise → Decision.

        **{fa_name}:** composite = **{pred.get('skill_composite_a', 0):.1f}**  ·
        **{fb_name}:** composite = **{pred.get('skill_composite_b', 0):.1f}**
        """)
