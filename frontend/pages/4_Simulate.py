import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st
import plotly.graph_objects as go
from backend.services import build_fight_simulation, build_ranking_response

st.set_page_config(page_title="Simulator — UFCelo.gg", page_icon="UFC", layout="wide")

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

st.title("Monte Carlo Simulator")
st.caption(
    "Runs thousands of simulated fight outcomes and shows the distribution of results. "
    "Each trial samples win probability, then method (based on striker vs grappler profile), then round."
)

available = [d for d in DIVISIONS if build_ranking_response(d)]
div = st.selectbox("Division", available, format_func=lambda d: DIVISION_LABELS.get(d, d.title()))

rankings = build_ranking_response(div)
if not rankings:
    st.warning("No data.")
    st.stop()

names  = [f["fighter_name"] for f in rankings]
ids    = [f["fighter_id"]   for f in rankings]
elos   = {f["fighter_id"]: f["elo"] for f in rankings}
champs = {f["fighter_id"]: f.get("is_champion", False) for f in rankings}

c1, c2 = st.columns(2)
with c1:
    fa_name = st.selectbox("Fighter A", names, key="sim_fa")
with c2:
    fb_name = st.selectbox("Fighter B", names, index=min(1, len(names)-1), key="sim_fb")

c3, c4, c5 = st.columns(3)
with c3:
    n_sims = st.slider("Simulations", 100, 10000, 1000, step=100)
with c4:
    rounds = st.radio("Rounds", [3, 5], horizontal=True)
with c5:
    seed = st.number_input("Seed (optional)", value=0, min_value=0)
    seed = int(seed) if seed else None

if fa_name == fb_name:
    st.warning("Select two different fighters.")
    st.stop()

if st.button("▶ Run Simulation", type="primary", use_container_width=True):
    fa_id = ids[names.index(fa_name)]
    fb_id = ids[names.index(fb_name)]

    with st.spinner("Simulating..."):
        result = build_fight_simulation(fa_id, fb_id, n=n_sims, rounds=rounds, seed=seed, division=div)

    if not result:
        st.error("Simulation failed.")
        st.stop()

    pa     = result["probability_a"]
    pb     = result["probability_b"]
    a_wins = result["fighter_a_wins"]
    b_wins = result["fighter_b_wins"]

    fa_label = ("[C] " if champs.get(fa_id) else "") + fa_name
    fb_label = ("[C] " if champs.get(fb_id) else "") + fb_name

    st.divider()
    st.markdown(f"### Result: **{result['most_likely_outcome']}**")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric(f"{fa_name} wins", f"{a_wins:,}", delta=f"{pa*100:.1f}%")
    m2.metric(f"{fb_name} wins", f"{b_wins:,}", delta=f"{pb*100:.1f}%")
    m3.metric("Simulations", f"{n_sims:,}")
    m4.metric("ELO edge (A−B)", f"{elos.get(fa_id,0)-elos.get(fb_id,0):+.0f}")

    st.divider()

    # ── Win distribution donut ─────────────────────────────────────────────
    fig_pie = go.Figure(go.Pie(
        labels=[fa_label, fb_label],
        values=[a_wins, b_wins],
        hole=0.55,
        marker_colors=["#E8281E", "#4455FF"],
        textinfo="label+percent",
        textfont_size=13,
    ))
    fig_pie.update_layout(
        height=300, paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#FAFAFA"),
        margin=dict(l=0, r=0, t=20, b=0),
        showlegend=False,
    )

    # ── Method breakdown ───────────────────────────────────────────────────
    mb      = result.get("method_breakdown", {})
    methods = ["KO/TKO", "SUB", "DEC"]
    vals_a  = [mb.get("fighter_a", {}).get(m, 0) * a_wins for m in methods]
    vals_b  = [mb.get("fighter_b", {}).get(m, 0) * b_wins for m in methods]

    fig_meth = go.Figure()
    fig_meth.add_trace(go.Bar(name=fa_name, x=methods, y=vals_a, marker_color="#E8281E",
                              text=[f"{v:.0f}" for v in vals_a], textposition="auto"))
    fig_meth.add_trace(go.Bar(name=fb_name, x=methods, y=vals_b, marker_color="#4455FF",
                              text=[f"{v:.0f}" for v in vals_b], textposition="auto"))
    fig_meth.update_layout(
        barmode="group", height=300,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#FAFAFA"),
        yaxis=dict(showgrid=True, gridcolor="#222", title="# wins"),
        xaxis=dict(showgrid=False),
        legend=dict(orientation="h", yanchor="top", y=-0.15, xanchor="center", x=0.5),
        margin=dict(l=0, r=0, t=10, b=40),
    )

    col_pie, col_meth = st.columns(2)
    with col_pie:
        st.markdown("**Win distribution**")
        st.plotly_chart(fig_pie, use_container_width=True)
    with col_meth:
        st.markdown("**By method**")
        st.plotly_chart(fig_meth, use_container_width=True)

    # ── Round distribution ─────────────────────────────────────────────────
    rd = result.get("round_distribution", {})
    if rd:
        st.markdown("**Finishing round distribution (KO/TKO and SUB)**")
        round_cols = st.columns(len(rd))
        for idx, (method, rnd_data) in enumerate(rd.items()):
            with round_cols[idx]:
                rnd_labels = [f"R{r}" for r in sorted(rnd_data.keys(), key=int)]
                rnd_vals   = [rnd_data[r] for r in sorted(rnd_data.keys(), key=int)]
                fig_rnd = go.Figure(go.Bar(
                    x=rnd_labels, y=[v * 100 for v in rnd_vals],
                    marker_color="#E8281E" if method == "KO/TKO" else "#44AA88",
                    text=[f"{v*100:.0f}%" for v in rnd_vals], textposition="auto",
                ))
                fig_rnd.update_layout(
                    title=method, height=220,
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    font=dict(color="#FAFAFA"),
                    yaxis=dict(showgrid=False, showticklabels=False),
                    xaxis=dict(showgrid=False),
                    margin=dict(l=0, r=0, t=35, b=0),
                )
                st.plotly_chart(fig_rnd, use_container_width=True)

    # ── Simulation methodology ─────────────────────────────────────────────
    with st.expander("How the simulation works"):
        st.markdown(f"""
        Each of the **{n_sims:,}** trials runs independently:

        1. **Win/loss** — sample from blended ELO + skill probability
           ({fa_name}: **{pa*100:.1f}%** | {fb_name}: **{pb*100:.1f}%**)

        2. **Method** — sampled from winner's skill profile:
           - KO/TKO weight = `(Striking / 100) × (Finish Rate / 100)`
           - SUB weight = `(Grappling / 100) × (Finish Rate / 100)`
           - DEC weight = `max(0.10, 1 − KO_w − SUB_w)`

        3. **Round** — sampled using Pressure and Cardio scores to weight early vs late stoppages.
           Pressure → earlier KOs · Cardio → later submissions.
        """)
