#!/usr/bin/env python3
"""Cutest Cat entry for make.fun (cutest-cat-01).

Draws one very cute chibi kitten with nothing but the Python standard
library: the picture is painted as anti-aliased vector shapes (ellipses,
polygons, strokes and soft blobs) on a 4x supersampled canvas, then
box-downscaled to 1024x1024 and written as a PNG with a hand-rolled
encoder (zlib + struct). Fully deterministic: no randomness, no clock,
no network, no files read. Both grader runs produce identical bytes.

Output: $MAKEFUN_OUTPUT_DIR/entry.png (default /output/entry.png).
"""

import math
import os
import struct
import zlib
from array import array

# ---------------------------------------------------------------- canvas

W = H = 1024          # final image size
SS = 4                # supersampling factor
SW = SH = W * SS      # canvas size (4096 x 4096)

# Three colour planes, one byte per canvas pixel.
planes = [bytearray(SW * SH), bytearray(SW * SH), bytearray(SW * SH)]


def _blend_span(y, x0, x1, color, a):
    """Blend a horizontal run of canvas pixels with coverage alpha a."""
    if x1 <= x0 or a <= 0.0:
        return
    if a >= 0.999:
        n = x1 - x0
        base = y * SW + x0
        for p in range(3):
            planes[p][base:base + n] = bytes((color[p],)) * n
        return
    ia = 1.0 - a
    base = y * SW
    for p in range(3):
        pl = planes[p]
        c = color[p]
        for x in range(x0, x1):
            i = base + x
            pl[i] = int(pl[i] * ia + c * a + 0.5)


def _blend_px(x, y, color, a):
    if a <= 0.0:
        return
    if x < 0 or y < 0 or x >= SW or y >= SH:
        return
    i = y * SW + x
    if a >= 0.999:
        for p in range(3):
            planes[p][i] = color[p]
        return
    ia = 1.0 - a
    for p in range(3):
        pl = planes[p]
        pl[i] = int(pl[i] * ia + color[p] * a + 0.5)


def ellipse(cx, cy, rx, ry, color, a=1.0, rot=0.0):
    """Filled ellipse; centre/radii in final-image units."""
    if rot == 0.0:
        y0 = max(0, int((cy - ry) * SS))
        y1 = min(SH - 1, int((cy + ry) * SS) + 1)
        for y in range(y0, y1 + 1):
            yc = (y + 0.5) / SS
            dy = (yc - cy) / ry
            t = 1.0 - dy * dy
            if t <= 0.0:
                continue
            hw = rx * math.sqrt(t)
            x0 = max(0, int((cx - hw) * SS))
            x1 = min(SW, int((cx + hw) * SS) + 1)
            _blend_span(y, x0, x1, color, a)
        return
    # Rotated ellipse: per-pixel test inside its bounding box.
    cs, sn = math.cos(rot), math.sin(rot)
    ex = math.sqrt((rx * cs) ** 2 + (ry * sn) ** 2)
    ey = math.sqrt((rx * sn) ** 2 + (ry * cs) ** 2)
    x0 = max(0, int((cx - ex) * SS))
    x1 = min(SW - 1, int((cx + ex) * SS) + 1)
    y0 = max(0, int((cy - ey) * SS))
    y1 = min(SH - 1, int((cy + ey) * SS) + 1)
    for y in range(y0, y1 + 1):
        dy = (y + 0.5) / SS - cy
        for x in range(x0, x1 + 1):
            dx = (x + 0.5) / SS - cx
            u = dx * cs + dy * sn
            v = -dx * sn + dy * cs
            r2 = (u / rx) ** 2 + (v / ry) ** 2
            if r2 < 1.0:
                rr = math.sqrt(r2)
                cov = min(1.0, max(0.0, (1.0 - rr) * SS * 1.5 + 0.5))
                _blend_px(x, y, color, a * cov)


def circle(cx, cy, r, color, a=1.0):
    ellipse(cx, cy, r, r, color, a)


def polygon(points, color, a=1.0):
    """Scanline-filled polygon; points in final-image units."""
    pts = [(x * SS, y * SS) for (x, y) in points]
    ys = [p[1] for p in pts]
    y0 = max(0, int(min(ys)))
    y1 = min(SH - 1, int(max(ys)) + 1)
    n = len(pts)
    for y in range(y0, y1 + 1):
        yc = y + 0.5
        xs = []
        for i in range(n):
            xa, ya = pts[i]
            xb, yb = pts[(i + 1) % n]
            if (ya <= yc < yb) or (yb <= yc < ya):
                xs.append(xa + (xb - xa) * (yc - ya) / (yb - ya))
        xs.sort()
        for k in range(0, len(xs) - 1, 2):
            _blend_span(y, int(xs[k]), int(xs[k + 1]) + 1, color, a)


def blob(cx, cy, rx, ry, color, a0):
    """Soft radial-gradient ellipse (blush, shadows): alpha fades to 0."""
    x0 = max(0, int((cx - rx) * SS))
    x1 = min(SW - 1, int((cx + rx) * SS) + 1)
    y0 = max(0, int((cy - ry) * SS))
    y1 = min(SH - 1, int((cy + ry) * SS) + 1)
    for y in range(y0, y1 + 1):
        dy = ((y + 0.5) / SS - cy) / ry
        for x in range(x0, x1 + 1):
            dx = ((x + 0.5) / SS - cx) / rx
            q = dx * dx + dy * dy
            if q < 1.0:
                _blend_px(x, y, color, a0 * (1.0 - q) ** 1.6)


def stroke_segment(x0, y0, x1, y1, r0, r1, color, a=1.0):
    """Tapered line segment with round caps (whiskers, lines)."""
    pad = max(r0, r1) + 2
    bx0 = max(0, int((min(x0, x1) - pad) * SS))
    bx1 = min(SW - 1, int((max(x0, x1) + pad) * SS) + 1)
    by0 = max(0, int((min(y0, y1) - pad) * SS))
    by1 = min(SH - 1, int((max(y0, y1) + pad) * SS) + 1)
    vx, vy = x1 - x0, y1 - y0
    vv = vx * vx + vy * vy
    for y in range(by0, by1 + 1):
        py = (y + 0.5) / SS
        for x in range(bx0, bx1 + 1):
            px = (x + 0.5) / SS
            t = 0.0 if vv == 0 else max(0.0, min(1.0, ((px - x0) * vx + (py - y0) * vy) / vv))
            qx, qy = x0 + t * vx, y0 + t * vy
            d = math.hypot(px - qx, py - qy)
            r = r0 + (r1 - r0) * t
            cov = min(1.0, max(0.0, (r - d) * SS + 0.5))
            if cov > 0.0:
                _blend_px(x, y, color, a * cov)


def stroke_points(points, r, color, a=1.0):
    """Draw a smooth thick curve by stamping circles along it."""
    for (x, y) in points:
        circle(x, y, r, color, a)


def arc_points(cx, cy, r, deg0, deg1, step=3.0):
    """Points along a circular arc (degrees, y axis pointing down)."""
    pts = []
    d = deg0
    while d <= deg1:
        rad = math.radians(d)
        pts.append((cx + r * math.cos(rad), cy + r * math.sin(rad)))
        d += step
    return pts


def bezier_points(p0, p1, p2, steps=16):
    pts = []
    for i in range(steps + 1):
        t = i / steps
        u = 1.0 - t
        pts.append((u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0],
                    u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1]))
    return pts


# ---------------------------------------------------------------- palette

BG_CENTRE = (255, 248, 233)
BG_EDGE = (255, 203, 148)
DOT = (255, 183, 120)
FUR = (250, 178, 110)        # soft ginger
FUR_SHADE = (240, 152, 82)   # deeper ginger for rims and shading
FUR_DARK = (228, 132, 64)    # stripes
CREAM = (255, 241, 222)      # belly, muzzle, tail tip
INNER_EAR = (255, 172, 183)
IRIS_RIM = (94, 54, 26)
IRIS = (133, 80, 36)
IRIS_LIGHT = (168, 110, 48)
PUPIL = (26, 17, 12)
WHITE = (255, 255, 255)
NOSE = (245, 121, 141)
MOUTH = (122, 72, 44)
TONGUE = (255, 148, 164)
BLUSH = (255, 128, 148)
WHISKER = (206, 138, 84)
BOW = (255, 111, 152)
BOW_SHADE = (232, 84, 128)
BOW_KNOT = (255, 140, 172)
YARN = (186, 158, 232)
YARN_DARK = (152, 122, 208)
GOLD = (255, 201, 84)
GOLD_DARK = (230, 170, 60)
PAD = (255, 155, 170)

# ---------------------------------------------------------------- background


def draw_background():
    # Radial gradient evaluated at final resolution, then block-upscaled:
    # the gradient is smooth, so 4x blocks of one colour cost nothing.
    grad = [[None] * W for _ in range(3)]
    for p in range(3):
        grad[p] = [bytearray(W) for _ in range(H)]
    for y in range(H):
        for x in range(W):
            d = math.hypot(x - 512, y - 400) / 780.0
            t = min(1.0, d) ** 1.25
            for p in range(3):
                grad[p][y][x] = int(BG_CENTRE[p] + (BG_EDGE[p] - BG_CENTRE[p]) * t + 0.5)
    for p in range(3):
        pl = planes[p]
        for y in range(H):
            row = grad[p][y]
            wide = bytearray(SW)
            for x in range(W):
                wide[x * SS:(x + 1) * SS] = bytes((row[x],)) * SS
            for k in range(SS):
                base = (y * SS + k) * SW
                pl[base:base + SW] = wide
    # Soft polka dots.
    row_i = 0
    gy = 90
    while gy < H:
        off = 85 if row_i % 2 else 0
        gx = 60 + off
        while gx < W:
            circle(gx, gy, 20, DOT, 0.15)
            gx += 175
        gy += 175
        row_i += 1
    # Tiny hearts and sparkles, kept faint so nothing crowds the cat.
    for (hx, hy, s) in ((168, 205, 15), (862, 150, 12), (905, 455, 10)):
        circle(hx - s * 0.5, hy - s * 0.25, s * 0.55, BLUSH, 0.5)
        circle(hx + s * 0.5, hy - s * 0.25, s * 0.55, BLUSH, 0.5)
        polygon([(hx - s, hy - s * 0.1), (hx + s, hy - s * 0.1), (hx, hy + s * 1.05)], BLUSH, 0.5)
    for (sx, sy, s) in ((250, 118, 14), (792, 302, 11)):
        polygon([(sx, sy - s), (sx + s * 0.28, sy - s * 0.28), (sx + s, sy),
                 (sx + s * 0.28, sy + s * 0.28), (sx, sy + s), (sx - s * 0.28, sy + s * 0.28),
                 (sx - s, sy), (sx - s * 0.28, sy - s * 0.28)], (255, 225, 150), 0.8)


# ---------------------------------------------------------------- the cat


def draw_cat():
    # Ground shadow.
    blob(512, 935, 335, 40, (226, 152, 96), 0.35)

    # Curled tail behind the body on the viewer's right, cream tip.
    # Stamped densely so the outline is one smooth tapered curve.
    tail_pts = bezier_points((690, 845), (920, 830), (905, 590), steps=48)
    for i, (tx, ty) in enumerate(tail_pts):
        t = i / (len(tail_pts) - 1)
        col = CREAM if t > 0.93 else FUR_SHADE
        circle(tx, ty, 40 - 15 * t, col)

    # Ears: tall ellipses leaning outward, their lower halves tucked
    # under the head (drawn next), leaving clean rounded tips.
    ellipse(370, 190, 66, 100, FUR_SHADE, 1.0, rot=0.35)
    ellipse(372, 196, 37, 64, INNER_EAR, 1.0, rot=0.35)
    ellipse(654, 190, 66, 100, FUR_SHADE, 1.0, rot=-0.35)
    ellipse(652, 196, 37, 64, INNER_EAR, 1.0, rot=-0.35)

    # Body: shaded base, lighter top, cream belly.
    ellipse(512, 795, 252, 195, FUR_SHADE)
    ellipse(512, 775, 232, 176, FUR)
    ellipse(512, 830, 150, 120, CREAM)

    # Yarn ball beside the body, with a loose strand.
    circle(818, 872, 66, YARN)
    stroke_points(arc_points(818, 872, 40, -30, 150, 6), 3.2, YARN_DARK)
    stroke_points(arc_points(818, 872, 55, 120, 300, 6), 3.2, YARN_DARK)
    stroke_points(arc_points(818, 872, 25, 200, 380, 6), 3.2, YARN_DARK)
    stroke_points(bezier_points((772, 908), (735, 940), (688, 936), steps=12), 2.6, YARN_DARK)
    circle(795, 845, 12, WHITE, 0.35)

    # Front paws with toe lines.
    ellipse(408, 918, 82, 46, FUR)
    ellipse(616, 918, 82, 46, FUR)
    for (tx, ty) in ((385, 895), (430, 895), (594, 895), (639, 895)):
        stroke_segment(tx, ty, tx - 3 if tx < 512 else tx + 3, ty + 30, 2.2, 2.2, FUR_DARK, 0.5)

    # Raised waving paw on the viewer's left, with pink pads.
    stroke_segment(320, 730, 238, 636, 19, 19, FUR)
    ellipse(228, 612, 52, 64, FUR, 1.0, rot=-0.35)
    ellipse(228, 606, 26, 32, PAD, 1.0, rot=-0.35)
    cs, sn = math.cos(-0.35), math.sin(-0.35)
    for (ox, oy) in ((-26, -38), (0, -46), (26, -38)):
        circle(228 + ox * cs - oy * sn, 612 + ox * sn + oy * cs, 9, PAD)

    # Head: shaded base, lighter face (a thin rim of shade is enough).
    ellipse(512, 430, 302, 266, FUR_SHADE)
    ellipse(512, 416, 288, 252, FUR)

    # Forehead stripes.
    ellipse(472, 196, 13, 30, FUR_DARK, 0.38)
    ellipse(512, 188, 13, 34, FUR_DARK, 0.38)
    ellipse(552, 196, 13, 30, FUR_DARK, 0.38)

    # Collar with a little gold bell, at the neck.
    stroke_points(arc_points(512, 430, 272, 35, 145, 1.5), 7, BOW)
    circle(512, 712, 20, GOLD)
    stroke_segment(494, 705, 530, 705, 2.6, 2.6, GOLD_DARK)
    circle(512, 721, 5, (160, 110, 40))
    circle(505, 703, 6, WHITE, 0.7)

    # Muzzle and chin.
    ellipse(462, 560, 78, 52, CREAM)
    ellipse(562, 560, 78, 52, CREAM)
    ellipse(512, 592, 44, 22, CREAM)

    # Blush.
    blob(322, 552, 58, 30, BLUSH, 0.38)
    blob(702, 552, 58, 30, BLUSH, 0.38)

    # Eyes: huge, glossy, warm brown.
    for cx in (398, 626):
        ellipse(cx, 448, 64, 84, IRIS_RIM)
        ellipse(cx, 448, 58, 78, IRIS)
        ellipse(cx, 464, 46, 58, IRIS_LIGHT)
        ellipse(cx, 450, 30, 54, PUPIL)
        circle(cx - 20, 420, 20, WHITE)
        circle(cx + 17, 478, 10, WHITE, 0.95)
        circle(cx + 24, 428, 6, WHITE, 0.9)

    # Tongue first (the mouth line draws over its top), then nose and mouth.
    ellipse(512, 596, 16, 20, TONGUE)
    stroke_segment(512, 590, 512, 606, 1.6, 1.6, (230, 110, 130), 0.6)
    polygon([(484, 534), (540, 534), (512, 560)], NOSE)
    circle(484, 534, 7, NOSE)
    circle(540, 534, 7, NOSE)
    circle(512, 556, 7, NOSE)
    ellipse(500, 538, 8, 5, WHITE, 0.5)
    stroke_segment(512, 560, 512, 574, 2.2, 2.2, MOUTH, 0.8)
    stroke_points(arc_points(490, 574, 24, 15, 165, 5), 2.6, MOUTH)
    stroke_points(arc_points(534, 574, 24, 15, 165, 5), 2.6, MOUTH)

    # Whiskers.
    for (x0, y0, x1, y1) in ((330, 545, 185, 520), (322, 568, 172, 566), (330, 590, 196, 622),
                             (694, 545, 839, 520), (702, 568, 852, 566), (694, 590, 828, 622)):
        stroke_segment(x0, y0, x1, y1, 2.4, 1.1, WHISKER, 0.8)

    # Bow on the viewer's right ear base.
    ellipse(584, 208, 32, 20, BOW, 1.0, rot=0.5)
    ellipse(656, 208, 32, 20, BOW, 1.0, rot=-0.5)
    ellipse(588, 212, 20, 12, BOW_SHADE, 0.55, rot=0.5)
    ellipse(652, 212, 20, 12, BOW_SHADE, 0.55, rot=-0.5)
    circle(620, 210, 15, BOW_KNOT)
    circle(614, 204, 5, WHITE, 0.8)


# ---------------------------------------------------------------- output


def downscale():
    """Box-average the 4x canvas down to 1024x1024 (list of RGB rows)."""
    rows = []
    for y in range(H):
        acc = [None, None, None]
        for k in range(SS):
            base = (y * SS + k) * SW
            for p in range(3):
                pl = planes[p]
                hs = [sum(pl[base + i:base + i + SS]) for i in range(0, SW, SS)]
                acc[p] = hs if acc[p] is None else [a2 + b2 for a2, b2 in zip(acc[p], hs)]
        row = bytearray(W * 3)
        for p in range(3):
            vals = bytes(v >> 4 for v in acc[p])
            row[p::3] = vals
        rows.append(bytes(row))
    return rows


def write_png(rows, path):
    raw = b"".join(b"\x00" + r for r in rows)

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0)
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
           + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(png)


def main():
    draw_background()
    draw_cat()
    rows = downscale()
    out_dir = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")
    os.makedirs(out_dir, exist_ok=True)
    write_png(rows, os.path.join(out_dir, "entry.png"))


if __name__ == "__main__":
    main()
