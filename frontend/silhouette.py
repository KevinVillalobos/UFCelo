"""SVG silhouette generator — proportional fighter figures from physical measurements."""
from typing import Optional


COLOR_A = "#D85A30"
COLOR_B = "#378ADD"

_BODY_H = 240  # fixed pixel height for the tallest / solo figure


def _figure(cx: float, feet_y: float, H_px: float, R_px: float, color: str, name: str = "") -> str:
    """SVG elements for one orthostatic figure. feet_y = bottom of figure."""
    fill = color + "28"
    sw = max(1.2, H_px * 0.007)  # stroke width scales with figure

    hr  = H_px * 0.075          # head radius
    hcy = feet_y - H_px + hr    # head center y

    sh_y  = feet_y - H_px * 0.860  # shoulder line y
    sh_x  = H_px * 0.115           # shoulder half-width

    wst_y = feet_y - H_px * 0.470  # waist
    wst_x = H_px * 0.078

    hip_y = feet_y - H_px * 0.400
    hip_x = H_px * 0.095

    kn_y  = feet_y - H_px * 0.240
    kn_x  = H_px * 0.070

    an_y  = feet_y - H_px * 0.055
    an_x  = H_px * 0.054

    ft_x  = H_px * 0.088

    arm_half = R_px / 2.0

    # Body polygon (torso + legs)
    path = (
        f"M {cx:.1f},{sh_y:.1f} "
        f"L {cx - sh_x:.1f},{sh_y:.1f} "
        f"Q {cx - sh_x * 1.10:.1f},{wst_y:.1f} {cx - wst_x:.1f},{wst_y:.1f} "
        f"Q {cx - hip_x * 1.05:.1f},{hip_y:.1f} {cx - hip_x:.1f},{hip_y:.1f} "
        f"L {cx - kn_x:.1f},{kn_y:.1f} "
        f"L {cx - an_x:.1f},{an_y:.1f} "
        f"L {cx - ft_x:.1f},{feet_y:.1f} "
        f"L {cx + ft_x:.1f},{feet_y:.1f} "
        f"L {cx + an_x:.1f},{an_y:.1f} "
        f"L {cx + kn_x:.1f},{kn_y:.1f} "
        f"L {cx + hip_x:.1f},{hip_y:.1f} "
        f"Q {cx + hip_x * 1.05:.1f},{hip_y:.1f} {cx + wst_x:.1f},{wst_y:.1f} "
        f"Q {cx + sh_x * 1.10:.1f},{wst_y:.1f} {cx + sh_x:.1f},{sh_y:.1f} "
        f"Z"
    )

    neck_w = H_px * 0.035
    parts = [
        # neck
        f'<line x1="{cx:.1f}" y1="{hcy + hr:.1f}" x2="{cx:.1f}" y2="{sh_y:.1f}" '
        f'stroke="{color}" stroke-width="{neck_w:.1f}" stroke-linecap="round"/>',
        # head
        f'<circle cx="{cx:.1f}" cy="{hcy:.1f}" r="{hr:.1f}" '
        f'fill="{fill}" stroke="{color}" stroke-width="{sw:.1f}"/>',
        # body
        f'<path d="{path}" fill="{fill}" stroke="{color}" '
        f'stroke-width="{sw:.1f}" stroke-linejoin="round"/>',
        # left arm
        f'<line x1="{cx - sh_x:.1f}" y1="{sh_y:.1f}" '
        f'x2="{cx - arm_half:.1f}" y2="{sh_y:.1f}" '
        f'stroke="{color}" stroke-width="{H_px * 0.026:.1f}" stroke-linecap="round"/>',
        # right arm
        f'<line x1="{cx + sh_x:.1f}" y1="{sh_y:.1f}" '
        f'x2="{cx + arm_half:.1f}" y2="{sh_y:.1f}" '
        f'stroke="{color}" stroke-width="{H_px * 0.026:.1f}" stroke-linecap="round"/>',
    ]

    if name:
        parts.append(
            f'<text x="{cx:.1f}" y="{feet_y + 18:.1f}" '
            f'text-anchor="middle" font-size="12" fill="{color}" '
            f'font-family="sans-serif" font-weight="700">{name}</text>'
        )

    return "\n  ".join(parts)


def _fmt_ht(h: Optional[float]) -> str:
    if h is None:
        return "??"
    return f"{int(h) // 12}'{int(h) % 12}\""


def fighter_svg_solo(
    height_in: Optional[float],
    reach_in: Optional[float],
    weight_lbs: Optional[int],
    color: str,
    name: str,
) -> str:
    H = height_in or 70.0
    R = reach_in or H
    scale = _BODY_H / H

    H_px = _BODY_H
    R_px = R * scale

    pad_x = 16
    pad_top = 10
    pad_bot = 44

    svg_w = R_px + pad_x * 2
    svg_h = H_px + pad_top + pad_bot
    cx = svg_w / 2
    feet_y = pad_top + H_px

    body = _figure(cx, feet_y, H_px, R_px, color, name)

    wt = f" · {weight_lbs} lbs" if weight_lbs else ""
    annot = (
        f'<text x="{cx:.1f}" y="{svg_h - 5:.1f}" text-anchor="middle" '
        f'font-size="10" fill="#888" font-family="monospace">'
        f'{_fmt_ht(height_in)} · {R:.0f}" reach{wt}</text>'
    )

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {svg_w:.1f} {svg_h:.1f}" '
        f'width="100%" style="max-height:310px; display:block;">'
        f'\n  {body}\n  {annot}\n</svg>'
    )


def fighter_svg_comparison(
    height_a: Optional[float], reach_a: Optional[float], weight_a: Optional[int], name_a: str,
    height_b: Optional[float], reach_b: Optional[float], weight_b: Optional[int], name_b: str,
) -> str:
    H_a = height_a or 70.0
    H_b = height_b or 70.0
    R_a = reach_a or H_a
    R_b = reach_b or H_b

    # same physical scale — based on the taller fighter
    scale = _BODY_H / max(H_a, H_b)

    H_px_a = H_a * scale
    H_px_b = H_b * scale
    R_px_a = R_a * scale
    R_px_b = R_b * scale

    pad_x   = 16
    pad_top = 24   # extra top space for height-diff annotation
    pad_bot = 52
    gap     = 48

    # Each figure is centered so its arm tips stay inside the SVG
    cx_a = pad_x + R_px_a / 2
    cx_b = cx_a + R_px_a / 2 + gap + R_px_b / 2
    svg_w = cx_b + R_px_b / 2 + pad_x

    # All feet at the same baseline
    feet_y = pad_top + _BODY_H
    svg_h  = feet_y + pad_bot

    body_a = _figure(cx_a, feet_y, H_px_a, R_px_a, COLOR_A, name_a)
    body_b = _figure(cx_b, feet_y, H_px_b, R_px_b, COLOR_B, name_b)

    extras: list[str] = []

    # Height reference dashed lines at each head
    head_y_a = feet_y - H_px_a + H_px_a * 0.075  # ≈ top of head
    head_y_b = feet_y - H_px_b + H_px_b * 0.075

    extras.append(
        f'<line x1="{cx_a - R_px_a * 0.18:.1f}" y1="{feet_y - H_px_a:.1f}" '
        f'x2="{cx_a + R_px_a * 0.18:.1f}" y2="{feet_y - H_px_a:.1f}" '
        f'stroke="{COLOR_A}" stroke-width="1" stroke-dasharray="4,3" opacity="0.55"/>'
    )
    extras.append(
        f'<line x1="{cx_b - R_px_b * 0.18:.1f}" y1="{feet_y - H_px_b:.1f}" '
        f'x2="{cx_b + R_px_b * 0.18:.1f}" y2="{feet_y - H_px_b:.1f}" '
        f'stroke="{COLOR_B}" stroke-width="1" stroke-dasharray="4,3" opacity="0.55"/>'
    )

    # Height difference badge (above the shorter fighter's head)
    h_diff = abs(H_a - H_b)
    if h_diff >= 0.5:
        taller_name = name_a if H_a > H_b else name_b
        badge_color = COLOR_A if H_a > H_b else COLOR_B
        in_diff = round(h_diff)
        badge_txt = f'+{in_diff}" height ({taller_name})'
        mid_x = (cx_a + cx_b) / 2
        badge_y = min(feet_y - H_px_a, feet_y - H_px_b) - 6
        extras.append(
            f'<text x="{mid_x:.1f}" y="{badge_y:.1f}" text-anchor="middle" '
            f'font-size="10" fill="{badge_color}" font-family="sans-serif" '
            f'font-weight="600">{badge_txt}</text>'
        )

    # Reach difference badge (bottom center)
    r_diff = R_a - R_b
    if abs(r_diff) >= 0.5:
        adv_name  = name_a if r_diff > 0 else name_b
        adv_color = COLOR_A if r_diff > 0 else COLOR_B
        reach_txt = f'+{abs(r_diff):.0f}" reach ({adv_name})'
        mid_x = (cx_a + cx_b) / 2
        extras.append(
            f'<text x="{mid_x:.1f}" y="{feet_y + 34:.1f}" text-anchor="middle" '
            f'font-size="10" fill="{adv_color}" font-family="sans-serif" '
            f'font-weight="600">{reach_txt}</text>'
        )

    # Individual measurements at bottom
    wt_a = f" · {weight_a} lbs" if weight_a else ""
    wt_b = f" · {weight_b} lbs" if weight_b else ""
    extras.append(
        f'<text x="{cx_a:.1f}" y="{svg_h - 4:.1f}" text-anchor="middle" '
        f'font-size="9" fill="#777" font-family="monospace">'
        f'{_fmt_ht(height_a)} · {R_a:.0f}" reach{wt_a}</text>'
    )
    extras.append(
        f'<text x="{cx_b:.1f}" y="{svg_h - 4:.1f}" text-anchor="middle" '
        f'font-size="9" fill="#777" font-family="monospace">'
        f'{_fmt_ht(height_b)} · {R_b:.0f}" reach{wt_b}</text>'
    )

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {svg_w:.1f} {svg_h:.1f}" '
        f'width="100%" style="max-height:360px; display:block;">'
        f'\n  {body_a}\n  {body_b}'
        f'\n  ' + '\n  '.join(extras) +
        f'\n</svg>'
    )
