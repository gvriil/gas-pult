"""Знак-арфа в технике гравюры (владелец 26.11: «где-то линия есть, где-то прерывается — светотень; изящная и цельная»).

Исходник — ``tools/harp-source.svg``: силуэт, обведённый с утверждённого листа, и 13 струн по замеру (7-я красная).
Корпус тёмный, к свету (слева сверху) его режут светлые штрихи — толще у света, к тени тоньше и пунктиром; струны —
тонкие, с разрывом по диагонали света; 7-я — красная и целая. Под размер вывода — лесенка, ни одна линия не тоньше
1 px: ≥96 — ``ladeya-mark``, 48–95 — ``-m`` (7 струн, реже штрих), 24–47 — ``-small`` (силуэт и 5 струн: 1, 4, 7, 10,
13-я), 16–23 — ``favicon`` (силуэт и красная струна), от 192 — ``-xl`` (значки и превью — ``tools/brand_images.py``).
Запуск из корня: ``python tools/harp_engraving.py``, затем ``python tools/brand_images.py``."""
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRAND = ROOT / "src/gas_pult/web/brand"
s = (Path(__file__).with_name("harp-source.svg")).read_text(encoding="utf-8")
FRAME = re.search(r'<path[^>]*d="([^"]*)"', s).group(1)
RECTS = re.findall(r'<rect x="([\d.]+)" y="(\d+)" width="4" height="(\d+)" rx="[\d.]+" fill="([^"]+)"/>', s)
VX, VY, VW, VH = 19, 13, 316, 427

def shade(x, y):
    """0 — свет (слева сверху), 1 — тень (справа снизу)."""
    return max(0.0, min(1.0, 0.55 * (x - VX) / VW + 0.45 * (y - VY) / VH + 0.05))


def frame(ink, extra=""):
    return f'<path fill="{ink}" fill-rule="evenodd"{extra} d="{FRAME}"/>'


def cuts_mask(px, uid):
    """Светлые штрихи по корпусу: толще у света, к тени — тоньше, потом пунктиром; одна толщина — один путь."""
    u = VH / px
    step, cmax, lo = max((2.4 if px >= 96 else 3.2) * u, 6.0), max(u, 2.0) * 1.8, max(u, 1.2)
    ang = math.radians(-58)
    dx, dy = math.cos(ang), math.sin(ang)
    nx, ny = -dy, dx
    diag, cx, cy = math.hypot(VW, VH), VX + VW / 2, VY + VH / 2
    n, seg = int(diag / step) + 2, max(4, 2 * u)
    cuts: dict[float, list[str]] = {}
    for i in range(-n // 2, n // 2 + 1):
        ox, oy = cx + nx * i * step, cy + ny * i * step
        t = -diag / 2
        while t < diag / 2:
            x, y = ox + dx * t, oy + dy * t
            w, k = cmax * (1 - shade(x, y) / 0.78), round(t / seg)
            if w >= lo or (px >= 192 and w > lo * 0.3 and k % (2 if w > lo * 0.65 else 3) == 0):   # пунктир — от 192 px
                cuts.setdefault(round(max(w, lo) * 4) / 4, []).append(f"M{x:.0f} {y:.0f}l{dx * seg:.1f} {dy * seg:.1f}")
            t += seg
    paths = "".join(f'<path stroke-width="{q:g}" d="{"".join(v)}"/>' for q, v in sorted(cuts.items()))
    return (f'<defs><mask id="{uid}k"><rect x="{VX}" y="{VY}" width="{VW}" height="{VH}" fill="#fff"/>'
            f'<g stroke="#000" fill="none">{paths}</g></mask></defs>')


def mark(px, ink, red, uid="h"):
    """px — высота вывода в пикселях: под неё шаг штриха и толщины (не тоньше 1 px)."""
    u = VH / px
    if px < 24:                                          # 16–23: цельный силуэт и красная струна
        x, y, h = float(RECTS[6][0]) + 2, RECTS[6][1], RECTS[6][2]
        w = max(1.2 * u, 14)
        sw = f' stroke="{ink}" stroke-width="{0.35 * u:.1f}" stroke-linejoin="round"'
        return frame(ink, sw) + f'<rect x="{x - w / 2:.1f}" y="{y}" width="{w:.1f}" height="{h}" fill="{red}"/>'
    if px < 48:                                          # 24–47: силуэт и 5 тонких струн: 1, 4, 7 (красная), 10, 13-я
        out, idx, w = [frame(ink)], [0, 3, 6, 9, 12], max(u, 4)
    else:                                                # 48+: гравюра
        out = [cuts_mask(px, uid), frame(ink, f' mask="url(#{uid}k)"')]
        idx, w = (range(13) if px >= 96 else [0, 2, 4, 6, 8, 10, 12]), max(u, 2.4)
    for i in idx:                                        # струны: разрыв по диагонали света; 7-я — целая и красная
        x, y, h = float(RECTS[i][0]) + 2, int(RECTS[i][1]), int(RECTS[i][2])
        if i == 6:
            out.append(f'<path d="M{x} {y}V{y + h}" stroke="{red}" stroke-width="{w * 1.25:.2f}" '
                       'stroke-linecap="round"/>')
            continue
        g, yb = max(2.0 * u, 9), y + h * 0.18 + (x - 83) * 0.55
        brk = px >= 48 or i in (0, 3)                    # мелко — разрыв только у двух струн со стороны света
        ys = [y, yb, yb + g, y + h] if brk and y + 4 < yb < y + h - g - 4 else [y, y + h]
        d = "".join(f"M{x} {ys[k]:.1f}V{ys[k + 1]:.1f}" for k in range(0, len(ys), 2))
        out.append(f'<path d="{d}" stroke="{ink}" stroke-width="{w:.2f}" stroke-linecap="round" fill="none"/>')
    return "".join(out)


def svg(body, label="Ладэя"):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{VX} {VY} {VW} {VH}" role="img" '
            f'aria-label="{label}">{body}</svg>\n')


G, G2, R, R2 = "#232326", "#F4F4F2", "#E8421C", "#FF5A2D"   # графит, тёплый белый, красный (светлая / тёмная тема)


def main():
    for name, px in {"ladeya-mark": 96, "ladeya-mark-xl": 300, "ladeya-mark-m": 48, "ladeya-mark-small": 24}.items():
        (BRAND / f"{name}.svg").write_text(svg(mark(px, G, R, "l")), encoding="utf-8")
        (BRAND / f"{name}-dark.svg").write_text(svg(mark(px, G2, R2, "d")), encoding="utf-8")
    fav = mark(16, "var(--i)", "var(--r)", "f")
    theme = f":root{{--i:{G};--r:{R}}}@media (prefers-color-scheme:dark){{:root{{--i:{G2};--r:{R2}}}}}"
    (BRAND / "favicon.svg").write_text(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{VX} {VY} {VW} {VH}" '
                                       f'aria-hidden="true"><style>{theme}</style>{fav}</svg>\n', encoding="utf-8")
    sc = 360 / VH
    tx, ty = 256 - (VX + VW / 2) * sc, 256 - (VY + VH / 2) * sc
    body = f'<g transform="translate({tx:.1f} {ty:.1f}) scale({sc:.4f})">{mark(360, G, R, "a")}</g>'
    (BRAND / "ladeya-app-icon.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" role="img" aria-label="Ладэя">'
        f'<rect width="512" height="512" fill="#F4F4F2"/>{body}</svg>\n', encoding="utf-8")

if __name__ == "__main__":
    main()
