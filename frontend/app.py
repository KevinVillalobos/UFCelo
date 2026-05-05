import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st
import plotly.graph_objects as go
from backend.services import build_ranking_response, build_prediction

st.set_page_config(
    page_title="UFCelo.gg",
    page_icon="UFC",
    layout="wide",
    initial_sidebar_state="expanded",
)

DIVISIONS = ["heavyweight", "light heavyweight", "middleweight", "welterweight", "lightweight", "featherweight", "bantamweight", "flyweight"]
DIVISION_LABELS = {
    "heavyweight":       "Heavyweight  265 lbs",
    "light heavyweight": "Light Heavyweight  205 lbs",
    "middleweight":      "Middleweight  185 lbs",
    "welterweight":      "Welterweight  170 lbs",
    "lightweight":       "Lightweight  155 lbs",
    "featherweight":     "Featherweight  145 lbs",
    "bantamweight":      "Bantamweight  135 lbs",
    "flyweight":         "Flyweight  125 lbs",
}

st.markdown("""
<div style='text-align:center; padding: 1rem 0 0.5rem 0;'>
    <h1 style='font-size:2.8rem; font-weight:800; letter-spacing:-1px;'>UFCelo.gg</h1>
    <p style='color:#888; font-size:1.1rem;'>Independent ELO rankings for UFC/MMA</p>
</div>
""", unsafe_allow_html=True)

st.divider()

# ── Division overview cards ────────────────────────────────────────────────
available = []
for div in DIVISIONS:
    r = build_ranking_response(div)
    if r:
        available.append((div, r))

if not available:
    st.warning("No data available. Run the ELO engine first.")
    st.stop()

cols = st.columns(min(len(available), 3))
for idx, (div, rankings) in enumerate(available):
    col = cols[idx % 3]
    top3 = rankings[:3]
    with col:
        st.markdown(f"### {DIVISION_LABELS.get(div, div.title())}")
        for i, f in enumerate(top3, 1):
            streak = f.get("streak", 0)
            is_champ = f.get("is_champion", False)
            streak_icon = f"+{streak}W" if streak >= 3 else (f"{streak}L" if streak <= -3 else "")
            champ_icon = "[C] " if is_champ else ""
            st.markdown(
                f"**#{i}** {champ_icon}{f['fighter_name']} "
                f"<span style='color:#E8281E; font-weight:700;'>{f['elo']:.0f}</span> "
                f"{streak_icon}",
                unsafe_allow_html=True,
            )
        if len(rankings) > 3:
            st.caption(f"+{len(rankings)-3} more fighters")
        st.markdown("")

st.divider()

# ── Quick predictor ────────────────────────────────────────────────────────
st.subheader("Quick prediction")
div_sel = st.selectbox(
    "Division",
    [d for d, _ in available],
    format_func=lambda d: DIVISION_LABELS.get(d, d.title()),
    key="home_div",
)
rankings_sel = next(r for d, r in available if d == div_sel)
names = [f["fighter_name"] for f in rankings_sel]
ids   = [f["fighter_id"]   for f in rankings_sel]

c1, c2 = st.columns(2)
with c1:
    fa_name = st.selectbox("Fighter A", names, key="home_fa")
with c2:
    fb_name = st.selectbox("Fighter B", names, index=min(1, len(names)-1), key="home_fb")

if fa_name != fb_name:
    fa_id = ids[names.index(fa_name)]
    fb_id = ids[names.index(fb_name)]
    pred  = build_prediction(fa_id, fb_id, div_sel)
    if pred:
        pa = pred["probability_a"]
        pb = pred["probability_b"]
        winner = fa_name if pa >= pb else fb_name
        prob   = max(pa, pb)
        fig = go.Figure(go.Bar(
            x=[pa * 100, pb * 100],
            y=[fa_name, fb_name],
            orientation="h",
            marker_color=["#E8281E" if pa >= pb else "#555", "#E8281E" if pb > pa else "#555"],
            text=[f"{pa*100:.1f}%", f"{pb*100:.1f}%"],
            textposition="inside",
        ))
        fig.update_layout(
            height=120, margin=dict(l=0, r=0, t=10, b=0),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            xaxis=dict(range=[0, 100], showticklabels=False, showgrid=False),
            yaxis=dict(showgrid=False),
            font=dict(color="#FAFAFA"),
        )
        st.plotly_chart(fig, use_container_width=True)
        st.success(
            f"**{winner}** wins with **{prob*100:.1f}%** probability — "
            f"predicted method: {pred.get('method_prediction', '—')}"
        )
