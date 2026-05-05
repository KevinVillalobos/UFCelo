import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st
import plotly.graph_objects as go
import pandas as pd
from backend.services import build_fighter_profile, build_ranking_response
from frontend.silhouette import fighter_svg_solo

st.set_page_config(page_title="Fighter — UFCelo.gg", page_icon="UFC", layout="wide")

st.markdown("""
<style>
/* ── Responsive base ─────────────────────────────────────────── */
.block-container { padding-top: 1rem !important; }

@media (max-width: 768px) {
    .block-container { padding: 0.75rem 0.5rem !important; }

    /* Metric values smaller on mobile */
    [data-testid="stMetricValue"] { font-size: 1.1rem !important; }
    [data-testid="stMetricLabel"] { font-size: 0.65rem !important; }
    [data-testid="stMetricDelta"] { font-size: 0.65rem !important; }

    /* Expander labels wrap instead of overflow */
    .streamlit-expanderHeader { font-size: 0.78rem !important; white-space: normal !important; }

    /* Column gaps tighter */
    [data-testid="stHorizontalBlock"] { gap: 0.25rem !important; }

    /* DataFrame scrollable on narrow screens */
    .stDataFrame { overflow-x: auto !important; }

    /* Caption text smaller */
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
    "light heavyweight": "Light Heavyweight 205",
    "middleweight":      "Middleweight 185",
    "welterweight":      "Welterweight 170",
    "lightweight":       "Lightweight 155",
    "featherweight":     "Featherweight 145",
    "bantamweight":      "Bantamweight 135",
    "flyweight":         "Flyweight 125",
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
COLOR = "#D85A30"


def _elo_insight(h: dict, bd: dict) -> str:
    lines = []
    result = h.get("result", "")
    method = h.get("method", "")
    rnd    = h.get("round", 0) or 0
    delta  = bd.get("delta", 0)
    surprise = bd.get("surprise", 0)
    streak_b = bd.get("streak_before", 0)
    streak_m = bd.get("streak_mult", 1.0)
    k_eff    = bd.get("k_effective", 0)
    k_base   = bd.get("k_base", 32)

    if result == "Win":
        if method in ("KO/TKO", "SUB") and rnd == 1:
            lines.append(f"First-round finish boosted method weight to {bd.get('method_weight', 1):.2f}×.")
        elif method in ("KO/TKO", "SUB"):
            lines.append(f"Finish win (Rd {rnd}) applied method weight {bd.get('method_weight', 1):.2f}×.")
        if surprise > 0.35:
            lines.append(f"Upset win — opponent was heavily favored ({bd.get('expected_prob', 0.5)*100:.0f}% win chance), amplifying ELO gain.")
        elif surprise < -0.10:
            lines.append(f"Won as expected ({bd.get('expected_prob', 0.5)*100:.0f}% win probability); expected outcome limits gain.")
        if streak_b >= 3:
            lines.append(f"Win streak of {streak_b} applied a {streak_m:.2f}× streak multiplier.")
        if bd.get("cap_applied"):
            lines.append("ELO gain was capped — opponent ELO below threshold (weak opponent cap).")
    else:
        if surprise < -0.35:
            lines.append(f"Major upset loss — was heavily favored ({bd.get('expected_prob', 0.5)*100:.0f}% win chance), increasing ELO drop.")
        elif surprise > 0.10:
            lines.append(f"Lost as underdog ({bd.get('expected_prob', 0.5)*100:.0f}% win chance); being the underdog softens the ELO drop.")
        if streak_b <= -3:
            lines.append(f"Losing streak of {abs(streak_b)} applied a {streak_m:.2f}× consecutive-loss multiplier.")
        if bd.get("consec_loss_mult", 1.0) > 1.0:
            lines.append(f"Consecutive loss escalator: {bd['consec_loss_mult']:.2f}× for this loss in the current streak.")
        if bd.get("peak_penalty"):
            lines.append("Peak ELO decline penalty (+20%) applied — sustained losing streak far below career high.")
        if bd.get("cap_applied"):
            lines.append("ELO loss was capped at –80 (maximum single-fight loss protection).")

    opp_m = bd.get("opp_mom_mult", 1.0)
    if opp_m > 1.05:
        lines.append(f"Opponent was on a winning streak — momentum multiplier {opp_m:.2f}× inflated the stakes.")
    elif opp_m < 0.97:
        lines.append(f"Opponent was on a losing streak — momentum multiplier {opp_m:.2f}× reduced stakes.")

    rm = bd.get("rematch_mult", 1.0)
    if rm < 0.80:
        lines.append(f"Third meeting: rematch multiplier {rm:.2f}× (heavily diminished returns).")
    elif rm == 0.70:
        lines.append(f"Rematch vs same opponent (same winner): multiplier reduced to {rm:.2f}×.")
    elif rm == 1.20:
        lines.append(f"Rematch revenge win: opponent won previously — multiplier boosted to {rm:.2f}×.")

    tm = bd.get("time_mult", 1.0)
    if tm > 1.05:
        lines.append(f"Early finish time bonus: {tm:.2f}× (ended inside 30% of scheduled time).")

    k_ratio = k_eff / k_base if k_base else 1.0
    lines.append(
        f"Net K effective: {k_eff:.1f} ({k_ratio:.2f}× base) → ELO {delta:+.1f}"
    )
    return "  \n".join(lines) if lines else f"ELO change: {delta:+.1f}"


def _rivals_projection(fighter_id: str, current_elo: float, division: str) -> list[dict]:
    rankings = build_ranking_response(division)
    neighbors = []
    for r in rankings:
        if r["fighter_id"] == fighter_id:
            continue
        neighbors.append((abs(r["elo"] - current_elo), r))
    neighbors.sort(key=lambda x: x[0])
    top5 = [r for _, r in neighbors[:5]]

    rows = []
    for rival in top5:
        r_elo = rival["elo"]
        exp_a = 1.0 / (1.0 + 10 ** ((r_elo - current_elo) / 400.0))
        k = 32.0
        win_dec  = round(k * 1.05 * (1.0 - exp_a), 1)
        win_ko   = round(k * 1.30 * (1.0 - exp_a), 1)
        loss_dec = round(k * 1.05 * (0.0 - exp_a), 1)
        loss_ko  = round(k * 1.30 * (0.0 - exp_a), 1)
        rows.append({
            "Rival":          rival["fighter_name"],
            "Their ELO":      round(r_elo, 0),
            "ELO gap":        round(current_elo - r_elo, 0),
            "Win (DEC) Δ":    f"+{win_dec}",
            "Win (KO) Δ":     f"+{win_ko}",
            "Loss (DEC) Δ":   f"{loss_dec}",
            "Loss (KO) Δ":    f"{loss_ko}",
        })
    return rows


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


@st.cache_data(ttl=3600)
def get_profile(fid, d):
    return build_fighter_profile(fid, d)


profile = get_profile(fighter_id, div)
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

elo_history = profile.get("elo_history", [])
peak_elo    = max((h["elo"] for h in elo_history), default=0) if elo_history else profile.get("elo", 0)
peak_entry  = max(elo_history, key=lambda h: h["elo"]) if elo_history else {}

col_h1, col_h2, col_h3, col_h4, col_h5 = st.columns(5)
col_h1.metric("Current ELO", f"{profile['elo']:.1f}")
col_h2.metric(
    "Peak ELO", f"{peak_elo:.0f}",
    help=f"vs {peak_entry.get('opponent_name','?')} on {peak_entry.get('date','?')}",
)
col_h3.metric("Record", profile.get("record", "—"))
col_h4.metric("Division Rank", f"#{rank_num}" if rank_num != "—" else "—", delta=streak_delta)
col_h5.metric("Fights in DB", len(elo_history) or profile.get("fight_count", "—"))

st.divider()

# ── Silhouette + Skill Radar ────────────────────────────────────────────────
sil_col, radar_col = st.columns([1, 1])

with sil_col:
    svg = fighter_svg_solo(
        height_in  = profile.get("height_inches"),
        reach_in   = profile.get("reach_inches"),
        weight_lbs = profile.get("weight_lbs"),
        color      = COLOR,
        name       = selected_name,
    )
    st.markdown(svg, unsafe_allow_html=True)
    stance = profile.get("stance")
    if stance:
        st.caption(f"Stance: **{stance}**")

with radar_col:
    skill = profile.get("skill_score", {})
    if skill:
        display_dims = [SKILL_LABELS.get(d, d) for d in SKILL_DIMS]
        vals = [skill.get(d, 50) for d in SKILL_DIMS]
        fig_r = go.Figure(go.Scatterpolar(
            r=vals + [vals[0]],
            theta=display_dims + [display_dims[0]],
            fill="toself",
            fillcolor="rgba(216,90,48,0.22)",
            line=dict(color=COLOR, width=2),
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
            height=310,
            margin=dict(l=50, r=50, t=20, b=20),
            showlegend=False,
        )
        st.plotly_chart(fig_r, use_container_width=True)
        comp = profile.get("skill_composite")
        if comp:
            st.caption(f"Composite skill score: **{comp:.1f} / 100**")

st.divider()

# ── ELO History chart ───────────────────────────────────────────────────────
history = profile.get("elo_history", [])
if history:
    dates       = [h["date"] for h in history]
    elos        = [h["elo"]  for h in history]
    results     = [h.get("result", "") for h in history]
    opps        = [h.get("opponent_name", "") for h in history]
    methods     = [h.get("method", "") for h in history]
    elo_deltas  = [h.get("elo_change") for h in history]
    events_     = [h.get("event", "") for h in history]
    title_flags = [h.get("is_title_fight", False) for h in history]

    colors = ["#4CAF50" if r == "Win" else "#E8281E" if r == "Loss" else "#888" for r in results]
    hover_texts = []
    for r, opp, meth, delta, ev, is_title in zip(results, opps, methods, elo_deltas, events_, title_flags):
        delta_str  = f"  ({delta:+.1f})" if delta is not None else ""
        title_note = "  [TITLE FIGHT]" if is_title else ""
        hover_texts.append(
            f"<b>{r}</b> vs {opp}<br>Method: {meth}{title_note}<br>ELO{delta_str}<br>{ev}"
        )

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=dates, y=elos,
        mode="lines+markers",
        line=dict(color=COLOR, width=2),
        marker=dict(color=colors, size=9, line=dict(color="#fff", width=1)),
        text=hover_texts,
        hovertemplate="%{text}<extra></extra>",
        name="ELO",
    ))
    fig.add_hline(y=1500, line_dash="dot", line_color="#555", annotation_text="Baseline 1500")
    fig.update_layout(
        title="ELO History",
        height=340,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#FAFAFA"),
        xaxis=dict(showgrid=False, title=""),
        yaxis=dict(showgrid=True, gridcolor="#222", title="ELO"),
        hovermode="x unified",
        margin=dict(l=0, r=0, t=40, b=0),
    )
    st.plotly_chart(fig, use_container_width=True)

    # ── Summary table ────────────────────────────────────────────────────────
    log_rows = []
    for h in reversed(history):
        delta      = h.get("elo_change")
        title_note = " [T]" if h.get("is_title_fight") else ""
        log_rows.append({
            "Date":      h.get("date", "—"),
            "Result":    h.get("result", "—"),
            "Opponent":  h.get("opponent_name", "—"),
            "Method":    (h.get("method") or "—") + title_note,
            "Rd":        h.get("round", "—"),
            "Time":      h.get("time", "—"),
            "ELO":       round(h.get("elo", 0), 1),
            "Δ ELO":     round(delta, 1) if delta is not None else None,
            "Event":     h.get("event", "—"),
        })
    st.dataframe(
        pd.DataFrame(log_rows),
        use_container_width=True,
        hide_index=True,
        column_config={
            "ELO":   st.column_config.NumberColumn(format="%.1f"),
            "Δ ELO": st.column_config.NumberColumn(format="%+.1f"),
        },
    )

    # ── Fight Log (per-fight expandable) ────────────────────────────────────
    st.subheader("Fight Log — K Breakdown")
    for h in reversed(history):
        bd     = h.get("breakdown") or {}
        result = h.get("result", "—")
        icon   = "W" if result == "Win" else "L" if result == "Loss" else "D"
        delta  = h.get("elo_change")
        dstr   = f"  {delta:+.1f}" if delta is not None else ""
        title  = " [T]" if h.get("is_title_fight") else ""
        label  = (
            f"{icon}  {h.get('date','—')}  ·  vs {h.get('opponent_name','—')}"
            f"  ·  {h.get('method','—')} R{h.get('round','—')}"
            f"  ·  ELO {dstr}{title}"
        )
        with st.expander(label, expanded=False):
            if bd:
                m1, m2, m3 = st.columns(3)
                m1.metric("ELO Before", f"{bd.get('elo_before', 0):.1f}")
                m2.metric(
                    "ELO After",
                    f"{bd.get('elo_after', 0):.1f}",
                    delta=f"{bd.get('delta', 0):+.1f}",
                )
                m3.metric("K Effective", f"{bd.get('k_effective', 0):.2f}")

                st.markdown("**K-factor breakdown**")
                k_rows = [
                    {"Factor": "K base",             "Value": bd.get("k_base", 32)},
                    {"Factor": "× Variable K",        "Value": round(bd.get("k_var", 1), 4)},
                    {"Factor": "× Division mult",     "Value": round(bd.get("div_mult", 1), 3)},
                    {"Factor": "× Method weight",     "Value": round(bd.get("method_weight", 1), 4)},
                    {"Factor": "× Streak mult",       "Value": round(bd.get("streak_mult", 1), 3)},
                    {"Factor": "× Quality mult",      "Value": round(bd.get("quality_mult", 1), 3)},
                    {"Factor": "× Rematch mult",      "Value": round(bd.get("rematch_mult", 1), 3)},
                    {"Factor": "× Opp. momentum",     "Value": round(bd.get("opp_mom_mult", 1), 3)},
                    {"Factor": "× Time mult",         "Value": round(bd.get("time_mult", 1), 3)},
                    {"Factor": "= K effective",       "Value": round(bd.get("k_effective", 0), 3)},
                ]
                flags = []
                if bd.get("cap_applied"):
                    flags.append("cap applied")
                if bd.get("peak_penalty"):
                    flags.append("peak decline penalty")
                if bd.get("consec_loss_mult", 1.0) > 1.0:
                    flags.append(f"consec. loss ×{bd['consec_loss_mult']:.2f}")
                if flags:
                    k_rows.append({"Factor": "Modifiers", "Value": ", ".join(flags)})

                st.dataframe(
                    pd.DataFrame(k_rows),
                    use_container_width=True,
                    hide_index=True,
                )

                insight = _elo_insight(h, bd)
                st.info(insight)
            else:
                st.caption("No breakdown data — re-run the ELO engine to generate per-fight breakdowns.")

    # ── Rivals projection ────────────────────────────────────────────────────
    with st.expander("Projected ELO vs nearest rivals", expanded=False):
        proj = _rivals_projection(fighter_id, profile["elo"], div)
        if proj:
            st.caption(
                "Estimated ELO delta if this fighter fights each of the 5 nearest rivals next "
                "(simplified: K=32, no streak/quality multipliers)."
            )
            st.dataframe(pd.DataFrame(proj), use_container_width=True, hide_index=True)
        else:
            st.caption("Not enough rankings data.")

# ── Stats Panel ─────────────────────────────────────────────────────────────
fs = profile.get("fight_stats")
if fs:
    st.divider()
    st.subheader("Fight Statistics")

    # ── Methods breakdown ───────────────────────────────────────────────────
    w = fs["wins"]
    l = fs["losses"]
    total_w = sum(w.values()) or 1
    total_l = sum(l.values()) or 1
    methods_order = ["KO/TKO", "SUB", "DEC"]

    fig_m = go.Figure()
    fig_m.add_trace(go.Bar(
        name="Wins",
        y=methods_order,
        x=[w[m] for m in methods_order],
        orientation="h",
        marker_color="#4CAF50",
        text=[f"{w[m]}  ({w[m]/total_w*100:.0f}%)" for m in methods_order],
        textposition="outside",
    ))
    fig_m.add_trace(go.Bar(
        name="Losses",
        y=methods_order,
        x=[-l[m] for m in methods_order],
        orientation="h",
        marker_color="#E8281E",
        text=[f"{l[m]}  ({l[m]/total_l*100:.0f}%)" for m in methods_order],
        textposition="outside",
    ))
    fig_m.update_layout(
        title="Win / Loss Methods",
        barmode="overlay",
        height=200,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#FAFAFA"),
        xaxis=dict(showgrid=False, showticklabels=False, zeroline=True, zerolinecolor="#555"),
        yaxis=dict(showgrid=False),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=0, r=80, t=40, b=0),
    )
    st.plotly_chart(fig_m, use_container_width=True)

    ko_rd  = fs.get("avg_finish_round_ko")
    sub_rd = fs.get("avg_finish_round_sub")
    caps = []
    if ko_rd:
        caps.append(f"Avg KO/TKO finish: round **{ko_rd:.1f}**")
    if sub_rd:
        caps.append(f"Avg SUB finish: round **{sub_rd:.1f}**")
    if caps:
        st.caption("  ·  ".join(caps))

    st.divider()

    # ── Striking + Grappling ────────────────────────────────────────────────
    str_col, grp_col = st.columns(2)

    with str_col:
        st.markdown("**Striking**")

        def _pct_bar(label, value, max_val=1.0, fmt=".0%"):
            pct = min(value / max_val, 1.0)
            formatted = f"{value:{fmt}}" if fmt == ".0%" else f"{value:.2f}"
            st.markdown(
                f"<div style='font-size:13px;margin-bottom:4px;'>"
                f"<span style='color:#aaa;'>{label}</span> "
                f"<span style='color:{COLOR};font-weight:700;'>{formatted}</span></div>"
                f"<div style='background:#1a1a1a;border-radius:3px;height:6px;margin-bottom:10px;'>"
                f"<div style='background:{COLOR};width:{pct*100:.1f}%;height:6px;border-radius:3px;'></div>"
                f"</div>",
                unsafe_allow_html=True,
            )

        _pct_bar("Sig. strikes / min", fs["sig_strikes_per_min"], max_val=8.0, fmt=".2f")
        _pct_bar("Strike accuracy",    fs["strike_accuracy"],     max_val=1.0)
        _pct_bar("Strike defense",     fs["strike_defense"],      max_val=1.0)
        st.metric("Knockdowns / fight", f"{fs['knockdowns_per_fight']:.2f}")

        st.markdown("<div style='font-size:12px;color:#aaa;margin-top:8px;'>Target breakdown</div>",
                    unsafe_allow_html=True)
        breakdown_fig = go.Figure(go.Bar(
            y=["Head", "Body", "Leg"],
            x=[fs["head_pct"] * 100, fs["body_pct"] * 100, fs["leg_pct"] * 100],
            orientation="h",
            marker_color=[COLOR, "#E8821E", "#C0A020"],
            text=[f"{fs['head_pct']*100:.0f}%", f"{fs['body_pct']*100:.0f}%", f"{fs['leg_pct']*100:.0f}%"],
            textposition="outside",
        ))
        breakdown_fig.update_layout(
            height=130, margin=dict(l=0, r=40, t=5, b=0),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#FAFAFA", size=11),
            xaxis=dict(range=[0, 100], showticklabels=False, showgrid=False),
            yaxis=dict(showgrid=False),
        )
        st.plotly_chart(breakdown_fig, use_container_width=True)

    with grp_col:
        st.markdown("**Grappling**")

        BLUE = "#378ADD"

        def _pct_bar_b(label, value, max_val=1.0, fmt=".0%"):
            pct = min(value / max_val, 1.0)
            formatted = f"{value:{fmt}}" if fmt == ".0%" else f"{value:.3f}"
            st.markdown(
                f"<div style='font-size:13px;margin-bottom:4px;'>"
                f"<span style='color:#aaa;'>{label}</span> "
                f"<span style='color:{BLUE};font-weight:700;'>{formatted}</span></div>"
                f"<div style='background:#1a1a1a;border-radius:3px;height:6px;margin-bottom:10px;'>"
                f"<div style='background:{BLUE};width:{pct*100:.1f}%;height:6px;border-radius:3px;'></div>"
                f"</div>",
                unsafe_allow_html=True,
            )

        _pct_bar_b("Takedowns / min",     fs["td_per_min"],             max_val=2.0,  fmt=".3f")
        _pct_bar_b("TD accuracy",         fs["td_accuracy"],            max_val=1.0)
        _pct_bar_b("TD defense",          fs["td_defense"],             max_val=1.0)
        _pct_bar_b("Control time (% of fight)", fs["ctrl_pct"],         max_val=1.0)
        st.metric("Sub attempts / fight", f"{fs['sub_attempts_per_fight']:.2f}")

    st.divider()

    # ── Career trend ────────────────────────────────────────────────────────
    timeline = fs.get("timeline", [])
    if len(timeline) >= 3:
        t_dates  = [t["date"] for t in timeline]
        t_spm    = [t["sig_strikes_per_min"] for t in timeline]
        t_colors = ["#4CAF50" if t["result"] == "Win" else "#E8281E" for t in timeline]
        t_hover  = [
            f"<b>{t['result']}</b> · {t['method']}<br>{t['sig_strikes_per_min']:.2f} sig. strikes/min"
            for t in timeline
        ]

        fig_t = go.Figure()
        fig_t.add_trace(go.Scatter(
            x=t_dates, y=t_spm,
            mode="lines+markers",
            line=dict(color="#555", width=1.5),
            marker=dict(color=t_colors, size=10, line=dict(color="#fff", width=1)),
            text=t_hover,
            hovertemplate="%{text}<extra></extra>",
        ))
        fig_t.update_layout(
            title="Career striking output (sig. strikes / min)",
            height=240,
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#FAFAFA"),
            xaxis=dict(showgrid=False, title=""),
            yaxis=dict(showgrid=True, gridcolor="#222", title="Sig. strikes / min"),
            hovermode="x unified",
            margin=dict(l=0, r=0, t=40, b=0),
        )
        st.plotly_chart(fig_t, use_container_width=True)

# ── Skill score breakdown table ─────────────────────────────────────────────
skill = profile.get("skill_score", {})
if skill:
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
