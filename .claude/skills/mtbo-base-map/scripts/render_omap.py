#!/usr/bin/env python3
"""Rough raster preview of an .omap file, so the result can be looked at.

Mapper 0.9.x has no headless export, so this draws the objects itself: line
symbols as polylines of their own width and colour (dashes included), area
symbols as filled polygons, point symbols as a small ring, text as a dot. It is
a sanity check on geometry and symbol assignment, NOT a rendering of the map --
point symbol drawings, area patterns, combined symbols and knockout are ignored.

  python tools/render_omap.py MTBO_Bryukhovychi_15000.omap out.png [px_per_mm]
"""
import io, re, sys, xml.etree.ElementTree as ET
from PIL import Image, ImageDraw

NS = "{http://openorienteering.org/apps/mapper/xml/v2}"


def rgb(c):
    r = c.find(NS + "rgb")
    if r is None:
        return (0, 0, 0)
    return tuple(int(round(float(r.get(k, 0)) * 255)) for k in "rgb")


def main():
    src = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else "preview.png"
    ppmm = float(sys.argv[3]) if len(sys.argv) > 3 else 6.0

    t = ET.fromstring(io.open(src, encoding="utf-8").read())
    colors = [rgb(c) for c in t.find(NS + "colors")]
    bar = t.find(NS + "barrier")
    syms = {}
    for s in bar.find(NS + "symbols"):
        sid, st = int(s.get("id")), int(s.get("type"))
        d = {"type": st, "code": s.get("code"), "color": None, "width": 0,
             "dash": None, "gap": 0}
        ls = s.find(NS + "line_symbol")
        if ls is not None:
            d["color"] = int(ls.get("color"))
            d["width"] = int(ls.get("line_width", 0)) / 1000.0
            if ls.get("dashed") == "true":
                d["dash"] = int(ls.get("dash_length", 0)) / 1000.0
                d["gap"] = int(ls.get("break_length", 0)) / 1000.0
        a = s.find(NS + "area_symbol")
        if a is not None:
            ic = int(a.get("inner_color"))
            d["color"] = ic if ic >= 0 else None
        cs = s.find(NS + "combined_symbol")
        if cs is not None:
            d["parts"] = [int(p.get("symbol")) for p in cs if p.get("symbol")]
        syms[sid] = d

    objs = []
    for part in bar.find(NS + "parts"):
        for o in part.find(NS + "objects"):
            pts, flags = [], []
            for tok in o.find(NS + "coords").text.strip().strip(";").split(";"):
                f = tok.split()
                if len(f) < 2:
                    continue
                pts.append((int(f[0]) / 1000.0, int(f[1]) / 1000.0))
                flags.append(int(f[2]) if len(f) > 2 else 0)
            objs.append((int(o.get("type")), int(o.get("symbol")), pts, flags))

    xs = [p[0] for _, _, ps, _ in objs for p in ps]
    ys = [p[1] for _, _, ps, _ in objs for p in ps]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    W = int((x1 - x0) * ppmm) + 20
    H = int((y1 - y0) * ppmm) + 20
    im = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(im)

    def P(p):
        return ((p[0] - x0) * ppmm + 10, (p[1] - y0) * ppmm + 10)

    def rings(pts, flags):
        out, cur = [], []
        for p, f in zip(pts, flags):
            cur.append(p)
            if f & 16:
                out.append(cur)
                cur = []
        if cur:
            out.append(cur)
        return out

    def draw_line(pts, col, w, dash=None, gap=0):
        px = [P(p) for p in pts]
        wpx = max(1, int(round(w * ppmm)))
        if not dash or gap <= 0:
            d.line(px, fill=col, width=wpx, joint="curve")
            return
        # walk the polyline, alternating dash / gap
        on, left = True, dash
        for a, b in zip(px, px[1:]):
            seg = ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5 / ppmm
            pos = 0.0
            while pos < seg:
                step = min(left, seg - pos)
                if on:
                    f0, f1 = pos / seg, (pos + step) / seg
                    d.line([(a[0] + (b[0] - a[0]) * f0, a[1] + (b[1] - a[1]) * f0),
                            (a[0] + (b[0] - a[0]) * f1, a[1] + (b[1] - a[1]) * f1)],
                           fill=col, width=wpx)
                pos += step
                left -= step
                if left <= 1e-9:
                    on = not on
                    left = dash if on else gap

    def render(sid, otype, pts, flags):
        s = syms.get(sid)
        if s is None:
            return
        if s["type"] == 16:                          # combined: draw each part
            for psid in s.get("parts", []):
                render(psid, otype, pts, flags)
            return
        ci = s["color"]
        col = colors[ci] if ci is not None and 0 <= ci < len(colors) else (0, 0, 0)
        if s["type"] == 4 and otype == 1:            # area
            if ci is None:                           # pattern-only area (north lines)
                return
            for ring in rings(pts, flags):
                if len(ring) >= 3:
                    d.polygon([P(p) for p in ring], fill=col)
        elif s["type"] == 2 and otype == 1:          # line
            draw_line(pts, col, max(s["width"], 0.08), s["dash"], s["gap"])
        elif otype == 0:                             # point
            x, y = P(pts[0])
            r = 1.6 * ppmm / 2
            d.ellipse([x - r, y - r, x + r, y + r], outline=col, width=2)
        elif otype == 4:                             # text anchor
            x, y = P(pts[0])
            d.ellipse([x - 2, y - 2, x + 2, y + 2], fill=col)

    # colour priority: the first colour in the table prints on top, so draw the
    # table back to front.
    order = {}
    for i, (otype, sid, pts, flags) in enumerate(objs):
        s = syms.get(sid, {})
        ci = s.get("color")
        if s.get("type") == 16 and s.get("parts"):
            ci = min([syms[p].get("color") for p in s["parts"]
                      if syms.get(p, {}).get("color") is not None] or [99])
        order[i] = -(ci if ci is not None else 99)
    for i in sorted(order, key=lambda k: order[k]):
        otype, sid, pts, flags = objs[i]
        render(sid, otype, pts, flags)

    im.save(out)
    print(f"{out}  {W}x{H} px at {ppmm} px/mm  "
          f"({x1-x0:.0f} x {y1-y0:.0f} mm, {len(objs)} objects)")


if __name__ == "__main__":
    main()
