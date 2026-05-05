import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st
import plotly.graph_objects as go
import pandas as pd
from backend.services import (
    build_prediction,
    build_ranking_response,
    build_fighter_profile,
    build_fight_simulator_data,
)
from frontend.silhouette import fighter_svg_comparison, COLOR_A, COLOR_B

st.set_page_config(page_title="Predictor — UFCelo.gg", page_icon="UFC", layout="wide")

st.markdown("""
<style>
.block-container { padding-top: 1rem !important; }

@media (max-width: 768px) {
    .block-container { padding: 0.75rem 0.5rem !important; }
    [data-testid="stMetricValue"] { font-size: 1.1rem !important; }
    [data-testid="stMetricLabel"] { font-size: 0.65rem !important; }
    [data-testid="stMetricDelta"] { font-size: 0.65rem !important; }
    .streamlit-expanderHeader { font-size: 0.78rem !important; white-space: normal !important; }
    [data-testid="stHorizontalBlock"] { gap: 0.25rem !important; }
    .stDataFrame { overflow-x: auto !important; }
    .stCaption { font-size: 0.7rem !important; }
}

@media (max-width: 480px) {
    [data-testid="stMetricValue"] { font-size: 0.95rem !important; }
    h1 { font-size: 1.4rem !important; }
    h2, h3 { font-size: 1.1rem !important; }
}
</style>
""", unsafe_allow_html=True)

DIVISIONS = ["heavyweight", "light heavyweight", "middleweight", "welterweight",
             "lightweight", "featherweight", "bantamweight", "flyweight"]
DIVISION_LABELS = {
    "heavyweight":       "Heavyweight 265",
    "lightweight":       "Lightweight 155",
    "welterweight":      "Welterweight 170",
    "featherweight":     "Featherweight 145",
    "middleweight":      "Middleweight 185",
    "flyweight":         "Flyweight 125",
    "light heavyweight": "Light Heavyweight 205",
    "bantamweight":      "Bantamweight 135",
}
SKILL_LABELS = {
    "Striking":           "Striking",
    "Grappling":          "Grappling",
    "Defensa":            "Defense",
    "Consistencia":       "Consistency",
    "Finish Rate":        "Finish Rate",
    "Cardio/Durabilidad": "Cardio / Durability",
    "Presión":            "Pressure",
}
SKILL_DIMS = list(SKILL_LABELS.keys())


# ── Simulator helpers ────────────────────────────────────────────────────────

def _fight_weight(method: str, is_title: bool, rnd: int) -> float:
    """Mirrors elo_engine._fight_weight for the winner."""
    weights = {
        "KO/TKO": {1: 1.40, 2: 1.25},
        "SUB":    {1: 1.25, 2: 1.25},
    }
    if method in weights:
        w = weights[method].get(rnd, 1.10)
    elif method == "DEC U":
        w = 1.05
    elif method == "DEC M":
        w = 0.90
    else:
        w = 0.80
    if is_title:
        w *= 1.20
    return w


def _loss_weight(method: str, is_title: bool, rnd: int, was_favorite: bool) -> float:
    """Mirrors elo_engine._loss_method_mult for the loser."""
    weights_ko = {1: 1.40, 2: 1.25}
    if method == "KO/TKO":
        w = weights_ko.get(rnd, 1.10)
    elif method == "SUB":
        w = 1.20
    elif method == "DEC U":
        w = 1.05
    elif method == "DEC M":
        w = 0.90
    else:
        w = 0.80
    if is_title and was_favorite:
        w *= 1.20
    return w


def _clm(streak: int) -> float:
    """Consecutive loss multiplier if this fight is a loss."""
    consec = max(0, -streak) + 1
    if consec >= 5: return 1.80
    if consec >= 4: return 1.60
    if consec >= 3: return 1.40
    if consec >= 2: return 1.20
    return 1.00


def _sim_scenario(sim: dict, winner: str, method: str, rnd: int, is_title: bool):
    """
    Compute ELO delta for both fighters given a winner + method + round.
    Returns dict with keys: delta_winner, delta_loser, k_winner, k_loser,
                            elo_winner_after, elo_loser_after, expected_winner.
    """
    elo_a = sim["elo_a"]
    elo_b = sim["elo_b"]
    expected_a = 1.0 / (1.0 + 10 ** ((elo_b - elo_a) / 400.0))
    expected_b = 1.0 - expected_a

    if winner == "a":
        elo_w, elo_l = elo_a, elo_b
        kvar_w, kvar_l = sim["k_var_a"], sim["k_var_b"]
        sm_w, sm_l = sim["streak_mult_a"], sim["streak_mult_b"]
        streak_l = sim["streak_b"]
        exp_w, exp_l = expected_a, expected_b
        fav_l = elo_b >= elo_a
    else:
        elo_w, elo_l = elo_b, elo_a
        kvar_w, kvar_l = sim["k_var_b"], sim["k_var_a"]
        sm_w, sm_l = sim["streak_mult_b"], sim["streak_mult_a"]
        streak_l = sim["streak_a"]
        exp_w, exp_l = expected_b, expected_a
        fav_l = elo_a >= elo_b

    fw = _fight_weight(method, is_title, rnd)
    lw = _loss_weight(method, is_title, rnd, was_favorite=fav_l)
    clm = _clm(streak_l)

    k_base = sim["k_base"]
    k_w = k_base * fw * sm_w * kvar_w
    k_l = k_base * lw * clm * sm_l * kvar_l

    dw = k_w * (1.0 - exp_w)
    dl = k_l * (0.0 - exp_l)

    # Same caps as engine
    if elo_l < 1300 and dw > 8.0:
        dw = 8.0
    dw = max(dw, 1.0)
    dl = max(-80.0, min(dl, -1.0))

    return {
        "delta_winner":      round(dw, 1),
        "delta_loser":       round(dl, 1),
        "k_winner":          round(k_w, 2),
        "k_loser":           round(k_l, 2),
        "elo_winner_before": round(elo_w, 1),
        "elo_loser_before":  round(elo_l, 1),
        "elo_winner_after":  round(max(1000.0, elo_w + dw), 1),
        "elo_loser_after":   round(max(1000.0, elo_l + dl), 1),
        "expected_winner":   round(exp_w, 4),
        "fight_weight":      round(fw, 4),
        "loss_weight":       round(lw, 4),
        "consec_loss_mult":  round(clm, 2),
    }


def _sim_insight(sc: dict, winner_name: str, loser_name: str, method: str, rnd: int) -> str:
    exp = sc["expected_winner"]
    surprise = 1.0 - exp
    lines = []
    if exp < 0.45:
        lines.append(f"Upset — {winner_name} was the underdog ({exp*100:.0f}% win chance). ELO gain amplified.")
    elif exp > 0.70:
        lines.append(f"Expected result — {winner_name} was heavily favored ({exp*100:.0f}%). Limited ELO gain.")
    if method in ("KO/TKO", "SUB") and rnd == 1:
        lines.append("First-round finish: highest method weight (1.40× or 1.25×).")
    elif method in ("KO/TKO", "SUB"):
        lines.append(f"Finish in round {rnd}: method weight {sc['fight_weight']:.2f}×.")
    if sc["consec_loss_mult"] > 1.0:
        lines.append(
            f"{loser_name} is on a loss streak — consecutive-loss multiplier {sc['consec_loss_mult']:.2f}× inflates the drop."
        )
    lines.append(
        f"Net K — winner: {sc['k_winner']:.1f}  ·  loser: {sc['k_loser']:.1f}"
    )
    return "  \n".join(lines)


# ── Page ─────────────────────────────────────────────────────────────────────

st.title("Fight Predictor")
st.caption("Blends ELO + skill scores to predict the most likely winner.")

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


@st.cache_data(ttl=3600)
def get_profile(fid, d):
    return build_fighter_profile(fid, d)


pa = pred["probability_a"]
pb = pred["probability_b"]
winner = fa_name if pa >= pb else fb_name
prob   = max(pa, pb)

st.divider()

# ── Probability bar ─────────────────────────────────────────────────────────
fig = go.Figure(go.Bar(
    x=[pa * 100, pb * 100],
    y=[fa_name, fb_name],
    orientation="h",
    marker_color=[COLOR_A if pa >= pb else "#445", COLOR_B if pb > pa else "#445"],
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

elo_diff    = pred.get("elo_difference", 0)
key_adv     = pred.get("key_advantage", "—")
key_adv_disp = SKILL_LABELS.get(key_adv, key_adv)
st.caption(
    f"ELO difference: **{elo_diff:+.1f}**  ·  "
    f"Key advantage: **{key_adv_disp}**  ·  "
    f"Pure ELO probability: **{pred.get('elo_probability_a', pa)*100:.1f}%** → "
    f"with skill adjustment: **{pa*100:.1f}%**"
)

st.divider()

# ── Silhouette comparison ────────────────────────────────────────────────────
prof_a = get_profile(fa_id, div)
prof_b = get_profile(fb_id, div)

if prof_a and prof_b:
    svg = fighter_svg_comparison(
        height_a=prof_a.get("height_inches"), reach_a=prof_a.get("reach_inches"),
        weight_a=prof_a.get("weight_lbs"),    name_a=fa_name,
        height_b=prof_b.get("height_inches"), reach_b=prof_b.get("reach_inches"),
        weight_b=prof_b.get("weight_lbs"),    name_b=fb_name,
    )
    st.markdown(svg, unsafe_allow_html=True)
    st.divider()

# ── Skill radar comparison ───────────────────────────────────────────────────
skill_a = pred.get("skill_comparison", {}).get("fighter_a") or {}
skill_b = pred.get("skill_comparison", {}).get("fighter_b") or {}

if not skill_a and prof_a:
    skill_a = prof_a.get("skill_score", {})
if not skill_b and prof_b:
    skill_b = prof_b.get("skill_score", {})

if skill_a and skill_b:
    display_dims = [SKILL_LABELS.get(d, d) for d in SKILL_DIMS]
    vals_a = [skill_a.get(d, 50) for d in SKILL_DIMS]
    vals_b = [skill_b.get(d, 50) for d in SKILL_DIMS]

    fig_r = go.Figure()
    fig_r.add_trace(go.Scatterpolar(
        r=vals_a + [vals_a[0]], theta=display_dims + [display_dims[0]],
        fill="toself", fillcolor="rgba(216,90,48,0.18)",
        line=dict(color=COLOR_A, width=2), name=fa_name,
    ))
    fig_r.add_trace(go.Scatterpolar(
        r=vals_b + [vals_b[0]], theta=display_dims + [display_dims[0]],
        fill="toself", fillcolor="rgba(55,138,221,0.18)",
        line=dict(color=COLOR_B, width=2), name=fb_name,
    ))
    fig_r.update_layout(
        polar=dict(
            bgcolor="rgba(0,0,0,0)",
            radialaxis=dict(range=[0, 100], showticklabels=True, tickfont=dict(size=9), gridcolor="#333"),
            angularaxis=dict(gridcolor="#333"),
        ),
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#FAFAFA"),
        height=400,
        legend=dict(orientation="h", yanchor="bottom", y=-0.15, xanchor="center", x=0.5),
        margin=dict(l=60, r=60, t=20, b=40),
    )
    st.plotly_chart(fig_r, use_container_width=True)

    # Skill advantage table
    adv_rows = []
    for dim in SKILL_DIMS:
        label = SKILL_LABELS.get(dim, dim)
        a_val = skill_a.get(dim, 50)
        b_val = skill_b.get(dim, 50)
        diff  = a_val - b_val
        adv_rows.append({
            "Dimension": label,
            fa_name: round(a_val, 1),
            fb_name: round(b_val, 1),
            "Advantage": round(diff, 1),
            "Edge": fa_name if diff >= 0 else fb_name,
        })
    df_adv = pd.DataFrame(adv_rows).sort_values("Advantage")
    st.dataframe(
        df_adv, use_container_width=True, hide_index=True,
        column_config={
            "Advantage": st.column_config.NumberColumn(format="%+.1f"),
            fa_name:     st.column_config.NumberColumn(format="%.1f"),
            fb_name:     st.column_config.NumberColumn(format="%.1f"),
        },
    )

st.divider()

# ── Comparison stats panel ───────────────────────────────────────────────────
fs_a = prof_a.get("fight_stats") if prof_a else None
fs_b = prof_b.get("fight_stats") if prof_b else None

if fs_a and fs_b:
    st.subheader("Fight Statistics Comparison")

    methods_order = ["KO/TKO", "SUB", "DEC"]
    tw_a = sum(fs_a["wins"].values()) or 1
    tw_b = sum(fs_b["wins"].values()) or 1

    fig_m = go.Figure()
    fig_m.add_trace(go.Bar(
        name=fa_name,
        x=[fs_a["wins"][m] / tw_a * 100 for m in methods_order],
        y=methods_order,
        orientation="h",
        marker_color=COLOR_A,
        text=[f"{fs_a['wins'][m]/tw_a*100:.0f}%" for m in methods_order],
        textposition="outside",
    ))
    fig_m.add_trace(go.Bar(
        name=fb_name,
        x=[fs_b["wins"][m] / tw_b * 100 for m in methods_order],
        y=methods_order,
        orientation="h",
        marker_color=COLOR_B,
        text=[f"{fs_b['wins'][m]/tw_b*100:.0f}%" for m in methods_order],
        textposition="outside",
    ))
    fig_m.update_layout(
        title="Win methods (%)",
        barmode="group",
        height=200,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#FAFAFA"),
        xaxis=dict(range=[0, 100], showticklabels=False, showgrid=False),
        yaxis=dict(showgrid=False),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=0, r=60, t=40, b=0),
    )
    st.plotly_chart(fig_m, use_container_width=True)

    st.divider()

    str_col, grp_col = st.columns(2)

    def _dual_bar(container, labels, vals_a, vals_b, title, name_a, name_b, fmt=".2f", max_x=None):
        xmax = max_x or (max(vals_a + vals_b) * 1.25 + 0.01)
        fig = go.Figure()
        fig.add_trace(go.Bar(
            name=name_a, y=labels, x=vals_a, orientation="h",
            marker_color=COLOR_A,
            text=[f"{v:{fmt}}" for v in vals_a], textposition="outside",
        ))
        fig.add_trace(go.Bar(
            name=name_b, y=labels, x=vals_b, orientation="h",
            marker_color=COLOR_B,
            text=[f"{v:{fmt}}" for v in vals_b], textposition="outside",
        ))
        fig.update_layout(
            title=title, barmode="group", height=200,
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#FAFAFA"),
            xaxis=dict(range=[0, xmax], showticklabels=False, showgrid=False),
            yaxis=dict(showgrid=False),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            margin=dict(l=0, r=70, t=40, b=0),
        )
        container.plotly_chart(fig, use_container_width=True)

    with str_col:
        _dual_bar(
            st,
            labels  = ["Sig. str/min", "Accuracy", "Defense"],
            vals_a  = [fs_a["sig_strikes_per_min"], fs_a["strike_accuracy"], fs_a["strike_defense"]],
            vals_b  = [fs_b["sig_strikes_per_min"], fs_b["strike_accuracy"], fs_b["strike_defense"]],
            title   = "Striking",
            name_a  = fa_name, name_b = fb_name,
            max_x   = max(fs_a["sig_strikes_per_min"], fs_b["sig_strikes_per_min"]) * 1.4 + 0.5,
        )
        breakdown_fig = go.Figure()
        for lbl, va, vb, col in [
            ("Head", fs_a["head_pct"]*100, fs_b["head_pct"]*100, "#c04030"),
            ("Body", fs_a["body_pct"]*100, fs_b["body_pct"]*100, "#409040"),
            ("Leg",  fs_a["leg_pct"]*100,  fs_b["leg_pct"]*100,  "#6060c0"),
        ]:
            breakdown_fig.add_trace(go.Bar(
                name=lbl, y=[fa_name, fb_name], x=[va, vb], orientation="h",
                marker_color=col,
                text=[f"{va:.0f}%", f"{vb:.0f}%"], textposition="outside",
            ))
        breakdown_fig.update_layout(
            title="Target breakdown (%)", barmode="group", height=180,
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#FAFAFA"),
            xaxis=dict(range=[0, 100], showticklabels=False, showgrid=False),
            yaxis=dict(showgrid=False),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            margin=dict(l=0, r=55, t=40, b=0),
        )
        st.plotly_chart(breakdown_fig, use_container_width=True)

    with grp_col:
        _dual_bar(
            st,
            labels  = ["TD/min", "TD accuracy", "TD defense", "Ctrl %"],
            vals_a  = [fs_a["td_per_min"], fs_a["td_accuracy"], fs_a["td_defense"], fs_a["ctrl_pct"]],
            vals_b  = [fs_b["td_per_min"], fs_b["td_accuracy"], fs_b["td_defense"], fs_b["ctrl_pct"]],
            title   = "Grappling",
            name_a  = fa_name, name_b = fb_name,
        )
        kd_col1, kd_col2 = st.columns(2)
        kd_col1.metric(f"{fa_name} KD/fight", f"{fs_a['knockdowns_per_fight']:.2f}")
        kd_col2.metric(f"{fb_name} KD/fight", f"{fs_b['knockdowns_per_fight']:.2f}")
        sub_col1, sub_col2 = st.columns(2)
        sub_col1.metric(f"{fa_name} sub att/fight", f"{fs_a['sub_attempts_per_fight']:.2f}")
        sub_col2.metric(f"{fb_name} sub att/fight", f"{fs_b['sub_attempts_per_fight']:.2f}")

st.divider()

# ── ELO Simulator ────────────────────────────────────────────────────────────
st.subheader("ELO Simulator")
st.caption(
    "Exact ELO impact for any fight outcome — using the same formula as the ranking engine. "
    "Excludes quality/rematch/momentum multipliers (estimated 1.0×)."
)

sim = build_fight_simulator_data(fa_id, fb_id, div)
if sim:
    s1, s2, s3 = st.columns(3)
    with s1:
        sim_method = st.selectbox(
            "Method",
            ["KO/TKO", "SUB", "DEC U", "DEC M", "DEC S"],
            key="sim_method",
        )
    with s2:
        sim_round = st.selectbox("Round", [1, 2, 3, 4, 5], key="sim_round")
    with s3:
        sim_title = st.checkbox("Title fight", key="sim_title")

    sc_a = _sim_scenario(sim, "a", sim_method, sim_round, sim_title)
    sc_b = _sim_scenario(sim, "b", sim_method, sim_round, sim_title)

    col_a, col_b = st.columns(2)

    with col_a:
        st.markdown(
            f"<div style='color:{COLOR_A};font-size:1.1rem;font-weight:700;"
            f"margin-bottom:8px;'>{fa_name} wins</div>",
            unsafe_allow_html=True,
        )
        ra1, ra2 = st.columns(2)
        ra1.metric(
            f"{fa_name} ELO",
            f"{sc_a['elo_winner_after']}",
            delta=f"+{sc_a['delta_winner']}",
        )
        ra2.metric(
            f"{fb_name} ELO",
            f"{sc_a['elo_loser_after']}",
            delta=f"{sc_a['delta_loser']}",
        )
        st.caption(
            f"Win prob (ELO): {sc_a['expected_winner']*100:.1f}%  ·  "
            f"K win: {sc_a['k_winner']:.1f}  ·  K lose: {sc_a['k_loser']:.1f}  ·  "
            f"Method wt: {sc_a['fight_weight']:.3f}"
        )
        st.info(_sim_insight(sc_a, fa_name, fb_name, sim_method, sim_round))

    with col_b:
        st.markdown(
            f"<div style='color:{COLOR_B};font-size:1.1rem;font-weight:700;"
            f"margin-bottom:8px;'>{fb_name} wins</div>",
            unsafe_allow_html=True,
        )
        rb1, rb2 = st.columns(2)
        rb1.metric(
            f"{fb_name} ELO",
            f"{sc_b['elo_winner_after']}",
            delta=f"+{sc_b['delta_winner']}",
        )
        rb2.metric(
            f"{fa_name} ELO",
            f"{sc_b['elo_loser_after']}",
            delta=f"{sc_b['delta_loser']}",
        )
        st.caption(
            f"Win prob (ELO): {sc_b['expected_winner']*100:.1f}%  ·  "
            f"K win: {sc_b['k_winner']:.1f}  ·  K lose: {sc_b['k_loser']:.1f}  ·  "
            f"Method wt: {sc_b['fight_weight']:.3f}"
        )
        st.info(_sim_insight(sc_b, fb_name, fa_name, sim_method, sim_round))

    with st.expander("Full K breakdown", expanded=False):
        k_rows = []
        for label, w, l in [
            ("Winner K base",        sim["k_base"],                sim["k_base"]),
            ("× Method weight",      sc_a["fight_weight"],         sc_b["fight_weight"]),
            ("× Streak mult (win)",  sim["streak_mult_a"],         sim["streak_mult_b"]),
            ("× Variable K (win)",   sim["k_var_a"],               sim["k_var_b"]),
            ("= K effective (win)",  sc_a["k_winner"],             sc_b["k_winner"]),
            ("Loser: loss weight",   sc_a["loss_weight"],          sc_b["loss_weight"]),
            ("× Consec. loss mult",  sc_a["consec_loss_mult"],     sc_b["consec_loss_mult"]),
            ("× Streak mult (lose)", sim["streak_mult_b"],         sim["streak_mult_a"]),
            ("× Variable K (lose)",  sim["k_var_b"],               sim["k_var_a"]),
            ("= K effective (lose)", sc_a["k_loser"],              sc_b["k_loser"]),
        ]:
            k_rows.append({
                "Factor":            label,
                f"If {fa_name} wins": w,
                f"If {fb_name} wins": l,
            })
        st.dataframe(pd.DataFrame(k_rows), use_container_width=True, hide_index=True)
        st.caption(
            f"Current streaks — {fa_name}: **{sim['streak_a']:+d}**  ·  "
            f"{fb_name}: **{sim['streak_b']:+d}**  ·  "
            f"Fight counts — {fa_name}: **{sim['fight_count_a']}**  ·  "
            f"{fb_name}: **{sim['fight_count_b']}**"
        )

st.divider()

with st.expander("How the prediction works"):
    st.markdown(f"""
    **ELO base probability** — `P(A wins) = 1 / (1 + 10^((ELO_B − ELO_A) / 400))`, capped at ±250 ELO diff (~82% max).

    **Skill adjustment** — up to ±10% shift based on composite skill score difference.
    Composite weights: Striking 20%, Defense 20%, Grappling 15%, Consistency 15%, Finish Rate 10%, Cardio 10%, Pressure 10%.

    **Method prediction** — from the favored fighter's dominant finishing style.

    **{fa_name}:** composite = **{pred.get('skill_composite_a', 0):.1f}**  ·
    **{fb_name}:** composite = **{pred.get('skill_composite_b', 0):.1f}**

    **ELO Simulator** — uses the same K-factor formula as the engine: K_base × method_weight × streak_mult × variable_K.
    Quality, rematch, and opponent-momentum multipliers are omitted (estimated at 1.0× for an unknown future fight).
    """)
