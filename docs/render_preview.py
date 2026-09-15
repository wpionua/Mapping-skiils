# -*- coding: utf-8 -*-
"""Schematic rasteriser for OpenOrienteering Mapper .omap files.

Mapper 0.9.x has no headless export, so this draws a simplified preview:
area fills, line strokes with dash patterns and casings, and point symbols as
dots. It does NOT reproduce point-symbol geometry, area patterns or text.
Good enough to show a before/after conversion at a glance.
"""
import io
import math
import re
import sys

from PIL import Image, ImageDraw

SS = 3  # supersampling factor


def parse(path, part=None):
    d = io.open(path, encoding="utf-8").read()

    # ---- colours: priority -> (r,g,b)
    colors = {}
    cb = re.search(r"<colors count=\"\d+\">.*?</colors>", d, re.S).group(0)
    for b in re.findall(r"<color .*?</color>", cb, re.S):
        p = int(re.search(r'priority="(\d+)"', b).group(1))
        m = re.search(r'<rgb[^>]*r="([\d.]+)" g="([\d.]+)" b="([\d.]+)"', b)
        if m:
            colors[p] = tuple(int(round(float(x) * 255)) for x in m.groups())
        else:
            c, mg, y, k = (float(re.search(r'\b%s="([\d.]+)"' % a, b).group(1))
                           for a in "cmyk")
            colors[p] = (int((1 - c) * (1 - k) * 255), int((1 - mg) * (1 - k) * 255),
                         int((1 - y) * (1 - k) * 255))

    # ---- symbols: id -> list of draw styles
    sb = re.search(r"<symbols.*?</symbols>", d, re.S).group(0)
    opens = list(re.finditer(r'<symbol [^>]*\bid="(\d+)"[^>]*>', sb))
    ends = [m.start() for m in opens[1:]] + [sb.rindex("</symbols>")]
    raw, styles = {}, {}
    for m, e in zip(opens, ends):
        a = dict(re.findall(r'(\w+)="([^"]*)"', m.group(0)))
        raw[a["id"]] = (a["type"], sb[m.end():e])

    def style_of(sid, depth=0):
        if sid in styles:
            return styles[sid]
        typ, body = raw.get(sid, (None, ""))
        out = []
        if typ == "4":
            t = re.search(r"<area_symbol[^>]*>", body)
            if t:
                c = int(re.search(r'inner_color="(-?\d+)"', t.group(0)).group(1))
                if c >= 0:
                    out.append(("fill", c, 0, None))
        elif typ == "2":
            t = re.search(r"<line_symbol[^>]*>", body).group(0)
            g = dict(re.findall(r'(\w+)="([^"]*)"', t))
            w = int(g.get("line_width", 0))
            c = int(g.get("color", -1))
            dash = None
            if g.get("dashed") == "true":
                dash = (int(g.get("dash_length", 0)), int(g.get("break_length", 0)))
            bm = re.search(r"<border ([^>]*)/>", body)
            if bm:  # cased line: paint casing wide underneath, infill on top
                bg = dict(re.findall(r'(\w+)="([^"]*)"', bm.group(1)))
                bw, bc = int(bg.get("width", 0)), int(bg.get("color", -1))
                sh = int(bg.get("shift", 0))
                if bc >= 0:
                    out.append(("line", bc, max(w + 2 * bw, 2 * sh + bw), None))
            if c >= 0 and w > 0:
                out.append(("line", c, w, dash))
            elif c >= 0:
                out.append(("line", c, 60, dash))
        elif typ == "1":
            t = re.search(r"<point_symbol[^>]*>", body).group(0)
            g = dict(re.findall(r'(\w+)="([^"]*)"', t))
            ic, ir = int(g.get("inner_color", -1)), int(g.get("inner_radius", 0))
            oc, ow = int(g.get("outer_color", -1)), int(g.get("outer_width", 0))
            if oc >= 0 and ow:
                out.append(("dot", oc, ir + ow, None))
            if ic >= 0:
                out.append(("dot", ic, max(ir, 60), None))
            if not out:  # element-based point symbol: use the first colour we find
                cm = re.search(r'(?:^|[^_a-z])color="(\d+)"', body)
                if cm:
                    out.append(("dot", int(cm.group(1)), 200, None))
        elif typ == "16" and depth < 3:
            for pid in re.findall(r'<part symbol="(\d+)"/>', body):
                out += style_of(pid, depth + 1)
        styles[sid] = out
        return out

    for sid in raw:
        style_of(sid)

    # ---- objects
    objs = []
    pb = re.search(r"<parts.*?</parts>", d, re.S).group(0)
    if part:
        keep = [m.group(0) for m in re.finditer(r"<part(?!s)[^>]*>.*?</part>", pb, re.S)
                if (re.search(r'name="([^"]*)"', m.group(0)) or [None, ""])[1] == part]
        pb = "".join(keep)
    for m in re.finditer(r'<object type="(\d+)" symbol="(\d+)"[^>]*>(.*?)</object>',
                         pb, re.S):
        otype, sid, body = m.group(1), m.group(2), m.group(3)
        cm = re.search(r'<coords count="\d+">(.*?)</coords>', body, re.S)
        if not cm:
            continue
        pts = []
        for tok in cm.group(1).split(";"):
            tok = tok.strip()
            if not tok:
                continue
            p = tok.split()
            pts.append((int(p[0]), int(p[1]), int(p[2]) if len(p) > 2 else 0))
        if pts:
            objs.append((otype, sid, pts))
    return colors, styles, objs


def subpaths(pts):
    """Expand bezier segments and split on hole points (flag bit 4)."""
    out, cur, i = [], [], 0
    while i < len(pts):
        x, y, f = pts[i]
        cur.append((x, y))
        if f & 1 and i + 3 < len(pts):        # curve: 2 control points follow
            p0 = (x, y)
            c1, c2, p3 = pts[i + 1][:2], pts[i + 2][:2], pts[i + 3][:2]
            for s in range(1, 13):
                t = s / 12.0
                u = 1 - t
                cur.append((u**3 * p0[0] + 3 * u * u * t * c1[0]
                            + 3 * u * t * t * c2[0] + t**3 * p3[0],
                            u**3 * p0[1] + 3 * u * u * t * c1[1]
                            + 3 * u * t * t * c2[1] + t**3 * p3[1]))
            i += 3
            if pts[i][2] & 4:
                out.append(cur)
                cur = []
            continue
        if f & 4:                              # end of this ring
            out.append(cur)
            cur = []
        i += 1
    if cur:
        out.append(cur)
    return [s for s in out if len(s) > 1]


def dashify(path, on, off):
    """Split a polyline into dash segments."""
    if on <= 0:
        return [path]
    segs, cur, rem, drawing = [], [path[0]], on, True
    for a, b in zip(path, path[1:]):
        d = math.hypot(b[0] - a[0], b[1] - a[1])
        t0 = 0.0
        while d - t0 > rem:
            t0 += rem
            p = (a[0] + (b[0] - a[0]) * t0 / d, a[1] + (b[1] - a[1]) * t0 / d)
            if drawing:
                cur.append(p)
                segs.append(cur)
                cur = []
            else:
                cur = [p]
            drawing = not drawing
            rem = on if drawing else off
        rem -= (d - t0)
        if drawing:
            cur.append(b)
    if drawing and len(cur) > 1:
        segs.append(cur)
    return segs


def render(path, out_png, width_px=1100, bg=(255, 255, 255), part=None, bbox=None):
    colors, styles, objs = parse(path, part)
    if bbox:
        x0, y0, x1, y1 = bbox
    else:
        xs = [p[0] for _, _, pts in objs for p in pts]
        ys = [p[1] for _, _, pts in objs for p in pts]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        pad = (x1 - x0) * 0.02
        x0, x1, y0, y1 = x0 - pad, x1 + pad, y0 - pad, y1 + pad
    sc = width_px * SS / (x1 - x0)
    W, H = int(width_px * SS), int((y1 - y0) * sc)
    img = Image.new("RGB", (W, H), bg)
    dr = ImageDraw.Draw(img)

    def T(p):
        return ((p[0] - x0) * sc, (p[1] - y0) * sc)

    # bucket primitives by colour, paint bottom-up (highest priority index first)
    buckets = {}
    for otype, sid, pts in objs:
        for kind, cidx, w, dash in styles.get(sid, []):
            buckets.setdefault(cidx, []).append((kind, w, dash, otype, pts))
    for cidx in sorted(buckets, reverse=True):
        col = colors.get(cidx, (0, 0, 0))
        for kind, w, dash, otype, pts in buckets[cidx]:
            if kind == "dot":
                x, y = T(pts[0])
                r = max(w * sc, 1.2)
                dr.ellipse([x - r, y - r, x + r, y + r], fill=col)
                continue
            for sp in subpaths(pts):
                q = [T(p) for p in sp]
                if kind == "fill" and len(q) > 2:
                    dr.polygon(q, fill=col)
                elif kind == "line":
                    lw = max(int(round(w * sc)), 1)
                    parts = dashify(q, dash[0] * sc, dash[1] * sc) if dash else [q]
                    for seg in parts:
                        if len(seg) > 1:
                            dr.line(seg, fill=col, width=lw, joint="curve")
    img = img.resize((width_px, int(H / SS)), Image.LANCZOS)
    img.save(out_png, optimize=True)
    return img.size, (x0, y0, x1, y1)


if __name__ == "__main__":
    print(render(sys.argv[1], sys.argv[2],
                 int(sys.argv[3]) if len(sys.argv) > 3 else 1100,
                 part=sys.argv[4] if len(sys.argv) > 4 else None))
