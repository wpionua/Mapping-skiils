#!/usr/bin/env python3
"""Build a base MTBO map (ISMTBOM 2022) from OpenStreetMap data, optionally with
the path network reinforced from a Strava global-heatmap screenshot.

    python mtbo_base.py init  --lat 49.8993 --lon 23.9866 \
                              [--heatmap data/heatmap.png --scalebar-m 100] \
                              [--extent 3900x1900] [--scale 15000] \
                              --donor "ISMTBOM2022_15000.omap" --out map.omap
    python mtbo_base.py fetch     [--config project.json]   # Overpass -> data/osm.json
    python mtbo_base.py heatmap   [--config project.json]   # screenshot -> network.json
    python mtbo_base.py build     [--config project.json]   # -> the .omap
    python mtbo_base.py render    [--config project.json]   # -> preview.png

Every step writes its state into project.json, so the steps can be re-run
individually. `heatmap` is optional: with no screenshot the map is built from OSM
alone.

Coordinate system: a local transverse Mercator centred on the map (k=1, false
origin 0), so grid north is true north, the scale factor is exactly 1 and no grid
convergence or auxiliary scale factor is involved.

Attribution / licence:
  * OSM data is (c) OpenStreetMap contributors, ODbL 1.0. The attribution must
    stay on any published map.
  * The donor symbol set comes from OpenOrienteering Mapper (GPLv3, and its
    `symbol sets/` carries no separate licence). Fine privately; flag it before
    anything commercial or redistributed.
  * Riding-speed classes derived here are INFERRED from OSM tags and heatmap
    usage. They are not a survey.
"""
import argparse, collections, glob, io, json, math, os, re, sys, time

# ---------------------------------------------------------------- configuration
DEFAULTS = {
    "scale": 15000,
    "pad_m": 250.0,
    # heatmap extraction
    "weak_bg": 18, "weak_rb": 25, "core_bg": 30, "core_gr": 18, "core_min": 6,
    "hairline_dt": 1.2, "max_dt": 13.0, "min_blob": 220, "close_r": 4, "open_r": 2,
    "min_spur_m": 45.0, "min_line_m": 60.0, "rdp_m": 3.0,
    # merge
    "match_m": 22.0, "step_m": 8.0, "heat_line_matched": 0.65,
    "osm_confirmed": 0.55, "min_new_m": 60.0, "heat_track": 85.0,
    "upgrade_confirmed": True,
    # output
    "north_lines": True, "template": True,
    "contours_json": "data/contours.json", "contours": False,
    "satellite_png": "data/satellite.png", "s2_npz": "data/s2_stack.npz",
    "vegetation_json": "data/vegetation.json", "vegetation": False,
    "satellite_template": True,
    "contour_min_len_m": 45.0,
    # riding speed measured from GPS traces
    "speeds_json": "data/speeds.json", "speeds": False, "tracks_dir": "",
    "speed_v_ref_kmh": 30.0, "speed_bands": [0.75, 0.45, 0.20],
    "speed_quantile": 0.75, "speed_hr_lo": 160, "speed_hr_hi": 180,
    "speed_hr_lag_s": 25, "speed_p_ref_w": 228.0,
    "speed_mass_kg": 85.0, "speed_crr": 0.012, "speed_cda": 0.42,
    "speed_overrides_heat": True,
}


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def load_config(path):
    cfg = dict(DEFAULTS)
    cfg.update(json.load(io.open(path, encoding="utf-8")))
    return cfg


def save_config(path, cfg):
    io.open(path, "w", encoding="utf-8").write(json.dumps(cfg, indent=2))


# ---------------------------------------------------------------- projection
A_WGS = 6378137.0
F_WGS = 1 / 298.257223563
E2 = F_WGS * (2 - F_WGS)
R_MERC = 6378137.0


def _arc(lat):
    e2, e4, e6 = E2, E2 * E2, E2 ** 3
    return A_WGS * ((1 - e2 / 4 - 3 * e4 / 64 - 5 * e6 / 256) * lat
                    - (3 * e2 / 8 + 3 * e4 / 32 + 45 * e6 / 1024) * math.sin(2 * lat)
                    + (15 * e4 / 256 + 45 * e6 / 1024) * math.sin(4 * lat)
                    - (35 * e6 / 3072) * math.sin(6 * lat))


class Frame:
    """Local transverse Mercator about (lat0, lon0); x east, y south, metres."""

    def __init__(self, lat0, lon0):
        self.lat0, self.lon0 = lat0, lon0
        self.m0 = _arc(math.radians(lat0))

    @property
    def proj4(self):
        return (f"+proj=tmerc +lat_0={self.lat0} +lon_0={self.lon0} +k=1 "
                f"+x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs")

    def fwd(self, lon, lat):
        p = math.radians(lat)
        dl = math.radians(lon - self.lon0)
        sp, cp, tp = math.sin(p), math.cos(p), math.tan(p)
        N = A_WGS / math.sqrt(1 - E2 * sp * sp)
        T, C, A = tp * tp, E2 / (1 - E2) * cp * cp, dl * cp
        ep = E2 / (1 - E2)
        x = N * (A + (1 - T + C) * A ** 3 / 6
                 + (5 - 18 * T + T * T + 72 * C - 58 * ep) * A ** 5 / 120)
        y = (_arc(p) - self.m0 + N * tp * (A * A / 2
             + (5 - T + 9 * C + 4 * C * C) * A ** 4 / 24
             + (61 - 58 * T + T * T + 600 * C - 330 * ep) * A ** 6 / 720))
        return (x, -y)

    def inv(self, x, y):
        M = self.m0 - y
        e1 = (1 - math.sqrt(1 - E2)) / (1 + math.sqrt(1 - E2))
        mu = M / (A_WGS * (1 - E2 / 4 - 3 * E2 ** 2 / 64 - 5 * E2 ** 3 / 256))
        p1 = (mu + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * math.sin(2 * mu)
              + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * math.sin(4 * mu)
              + (151 * e1 ** 3 / 96) * math.sin(6 * mu))
        sp, cp, tp = math.sin(p1), math.cos(p1), math.tan(p1)
        ep = E2 / (1 - E2)
        C1, T1 = ep * cp * cp, tp * tp
        N1 = A_WGS / math.sqrt(1 - E2 * sp * sp)
        R1 = A_WGS * (1 - E2) / (1 - E2 * sp * sp) ** 1.5
        D = x / N1
        lat = p1 - (N1 * tp / R1) * (D * D / 2
              - (5 + 3 * T1 + 10 * C1 - 4 * C1 * C1 - 9 * ep) * D ** 4 / 24
              + (61 + 90 * T1 + 298 * C1 + 45 * T1 * T1 - 252 * ep
                 - 3 * C1 * C1) * D ** 6 / 720)
        lon = (D - (1 + 2 * T1 + C1) * D ** 3 / 6
               + (5 - 2 * C1 + 28 * T1 - 3 * C1 * C1 + 8 * ep
                  + 24 * T1 * T1) * D ** 5 / 120) / cp
        return self.lon0 + math.degrees(lon), math.degrees(lat)


class Screenshot:
    """The heatmap screenshot's own frame: Web Mercator, north up, centred."""

    def __init__(self, cfg):
        h = cfg["heatmap"]
        self.w, self.h, self.mpp = h["width"], h["height"], h["m_per_px"]
        self.lat0, self.lon0 = cfg["lat"], cfg["lon"]

    def to_lonlat(self, px, py):
        k = math.cos(math.radians(self.lat0))
        x = (px - self.w / 2.0) * self.mpp / k
        y = (py - self.h / 2.0) * self.mpp / k
        y0 = R_MERC * math.log(math.tan(math.pi / 4 + math.radians(self.lat0) / 2))
        return (self.lon0 + math.degrees(x / R_MERC),
                math.degrees(2 * math.atan(math.exp((y0 - y) / R_MERC)) - math.pi / 2))

    def from_lonlat(self, lon, lat):
        k = math.cos(math.radians(self.lat0))
        y0 = R_MERC * math.log(math.tan(math.pi / 4 + math.radians(self.lat0) / 2))
        y1 = R_MERC * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))
        return (math.radians(lon - self.lon0) * R_MERC * k / self.mpp + self.w / 2.0,
                -(y1 - y0) * k / self.mpp + self.h / 2.0)


# ---------------------------------------------------------------- init
def detect_scalebar(path, region=(0, 0.86, 0.18, 1.0), dark=(330, 480, 620),
                    tick_w=5, min_gap=20, min_rows=4):
    """Find the map scale bar's pixel width in a screenshot.

    The bar is a horizontal rule with two vertical end ticks, so the same pair
    of narrow dark clusters repeats on every row the ticks span. Do *not*
    demand that the row hold nothing else: the corner also carries the zoom and
    3D buttons and the (i) attribution, and the bar's own "100 m" label sits
    between the ticks. Instead take every pair of narrow clusters in the row and
    keep the pair that repeats on the most rows - the ticks are the only pair
    that recurs at identical x, since glyph strokes shift shape row to row.

    `dark` is tried in order, so a light-themed bar (grey ticks) still lands.
    Returns the outer width in pixels, or None.
    """
    import numpy as np
    from PIL import Image
    a = np.asarray(Image.open(path).convert("RGB")).astype(int)
    h, w, _ = a.shape
    x0, y0 = int(region[0] * w), int(region[1] * h)
    x1, y1 = int(region[2] * w), int(region[3] * h)
    for cut in (dark if isinstance(dark, (tuple, list)) else [dark]):
        runs = collections.Counter()
        for y in range(y0, y1):
            xs = np.nonzero(a[y, x0:x1].sum(axis=1) < cut)[0]
            if not len(xs) or len(xs) > 60:      # 60 = a solid UI panel, not ticks
                continue
            # consecutive runs of dark pixels, narrow ones only
            breaks = np.nonzero(np.diff(xs) > 1)[0]
            starts = np.concatenate(([xs[0]], xs[breaks + 1]))
            ends = np.concatenate((xs[breaks], [xs[-1]]))
            ticks = [(int(s), int(e)) for s, e in zip(starts, ends)
                     if e - s + 1 <= tick_w]
            for i in range(len(ticks)):
                for j in range(i + 1, len(ticks)):
                    if ticks[j][0] - ticks[i][1] >= min_gap:
                        runs[(ticks[i][0], ticks[j][1])] += 1
        if not runs:
            continue
        # most rows wins; on a tie prefer the wider pair
        (lo, hi), n = max(runs.items(), key=lambda kv: (kv[1], kv[0][1] - kv[0][0]))
        if n < min_rows:
            continue
        return hi - lo + 1
    return None


def cmd_init(args):
    cfg = dict(DEFAULTS)
    cfg["lat"], cfg["lon"] = args.lat, args.lon
    cfg["scale"] = args.scale
    cfg["donor"] = args.donor
    cfg["out"] = args.out
    cfg["osm_json"] = args.osm_json
    cfg["network_json"] = args.network_json
    cfg["contours_json"] = args.contours_json
    cfg["satellite_png"] = args.satellite_png
    cfg["s2_npz"] = args.s2_npz
    cfg["vegetation_json"] = args.vegetation_json
    cfg["name"] = args.name or os.path.splitext(os.path.basename(args.out))[0]
    if args.tracks_dir:
        cfg["tracks_dir"] = args.tracks_dir.replace("\\", "/")

    if args.heatmap:
        from PIL import Image
        im = Image.open(args.heatmap)
        mpp = args.m_per_px
        if mpp is None:
            px = detect_scalebar(args.heatmap)
            if px is None:
                sys.exit("could not find a scale bar; pass --m-per-px explicitly")
            mpp = args.scalebar_m / px
            log(f"scale bar: {px} px = {args.scalebar_m} m -> {mpp:.4f} m/px")
        cfg["heatmap"] = {"path": args.heatmap.replace("\\", "/"),
                          "width": im.width, "height": im.height, "m_per_px": mpp}
        cfg["extent_m"] = [im.width * mpp, im.height * mpp]
    else:
        if not args.extent:
            sys.exit("without --heatmap you must give --extent WIDTHxHEIGHT in metres")
        w, h = (float(v) for v in args.extent.lower().split("x"))
        cfg["heatmap"] = None
        cfg["extent_m"] = [w, h]
    log(f"extent {cfg['extent_m'][0]:.0f} x {cfg['extent_m'][1]:.0f} m "
        f"= {cfg['extent_m'][0]/cfg['scale']*1000:.0f} x "
        f"{cfg['extent_m'][1]/cfg['scale']*1000:.0f} mm at 1:{cfg['scale']}")
    save_config(args.config, cfg)
    log(f"wrote {args.config}")


# ---------------------------------------------------------------- fetch
THEMES = {
    "highway": ['way["highway"]({bb});'],
    "rail_power": ['way["railway"]({bb});', 'way["power"]({bb});',
                   'way["aeroway"]({bb});'],
    "water": ['way["waterway"]({bb});',
              'way["natural"~"water|wetland|spring"]({bb});'],
    "landuse": ['way["landuse"]({bb});', 'way["landcover"]({bb});',
                'way["leisure"]({bb});', 'way["natural"]({bb});'],
    "building": ['way["building"]({bb});', 'way["man_made"]({bb});'],
    "barrier": ['way["barrier"]({bb});'],
    "relations": ['relation["type"="multipolygon"]({bb});'],
    "points": ['node["natural"]({bb});', 'node["man_made"]({bb});',
               'node["historic"]({bb});', 'node["tourism"]({bb});',
               'node["barrier"]({bb});'],
}
ENDPOINTS = ["https://overpass-api.de/api/interpreter",
             "https://overpass.kumi.systems/api/interpreter"]


def bbox(cfg):
    hw = cfg["extent_m"][0] / 2 + cfg["pad_m"]
    hh = cfg["extent_m"][1] / 2 + cfg["pad_m"]
    dlat = hh / 111320.0
    dlon = hw / (111320.0 * math.cos(math.radians(cfg["lat"])))
    return (cfg["lat"] - dlat, cfg["lon"] - dlon, cfg["lat"] + dlat, cfg["lon"] + dlon)


def cmd_fetch(args):
    import requests
    cfg = load_config(args.config)
    bb = "%.6f,%.6f,%.6f,%.6f" % bbox(cfg)
    log("bbox S,W,N,E =", bb)
    seen, els = set(), []

    def ask(parts):
        q = ("[out:json][timeout:180];\n(\n  "
             + "\n  ".join(p.format(bb=bb) for p in parts) + "\n);\nout geom qt;\n")
        last = None
        for attempt in range(5):
            for url in ENDPOINTS:
                try:
                    r = requests.post(url, data={"data": q}, timeout=180,
                                      headers={"User-Agent": "mtbo-base-map/1.0"})
                    if r.status_code == 200:
                        return r.json()["elements"]
                    last = f"{url} HTTP {r.status_code}"
                except Exception as e:
                    last = f"{url} {type(e).__name__}: {e}"
                log("   retry:", last)
                time.sleep(8 + 7 * attempt)
        sys.exit("Overpass failed: " + str(last))

    for name, parts in THEMES.items():
        got = ask(parts)
        new = 0
        for e in got:
            k = (e["type"], e["id"])
            if k not in seen:
                seen.add(k)
                els.append(e)
                new += 1
        log(f"  {name:<10} {len(got):>5} got, {new:>5} new")
        time.sleep(5)
    os.makedirs(os.path.dirname(cfg["osm_json"]) or ".", exist_ok=True)
    json.dump({"elements": els, "bbox": bbox(cfg),
               "fetched": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
              io.open(cfg["osm_json"], "w", encoding="utf-8"))
    log(f"{cfg['osm_json']}: {len(els)} elements")


# ---------------------------------------------------------------- heatmap
def cmd_heatmap(args):
    import numpy as np
    from PIL import Image, ImageDraw
    from scipy import ndimage as ndi
    from skimage.morphology import skeletonize, remove_small_objects, remove_small_holes
    cfg = load_config(args.config)
    if not cfg.get("heatmap"):
        sys.exit("no heatmap in the config -- run init with --heatmap, or skip this step")
    hm = cfg["heatmap"]
    mpp = hm["m_per_px"]
    a = np.asarray(Image.open(hm["path"]).convert("RGB")).astype(int)
    H, W, _ = a.shape

    def disk(r):
        y, x = np.ogrid[-r:r + 1, -r:r + 1]
        return (y * y + x * x) <= r * r + 0.5

    R, G, B = a[..., 0], a[..., 1], a[..., 2]
    weak = (B - G >= cfg["weak_bg"]) & (B - R >= cfg["weak_rb"])
    core = (B - G >= cfg["core_bg"]) & (G - R <= cfg["core_gr"])
    for x0, y0, x1, y1 in cfg.get("ui_rects") or default_ui_rects(W, H):
        weak[y0:y1, x0:x1] = False
        core[y0:y1, x0:x1] = False

    grown = ndi.binary_propagation(ndi.distance_transform_edt(weak) >= cfg["hairline_dt"],
                                   mask=weak, structure=np.ones((3, 3), bool))
    lab, n = ndi.label(grown, structure=np.ones((3, 3), int))
    cnt = np.bincount(lab[core & grown], minlength=n + 1)
    keep = np.zeros(n + 1, bool)
    keep[1:] = cnt[1:] >= cfg["core_min"]
    mask = keep[lab]
    log(f"components {n} -> kept {int(keep.sum())}")

    dt2 = ndi.distance_transform_edt(mask)
    wide = dt2 > cfg["max_dt"]
    if wide.any():                       # water bodies, urban fill: not a corridor
        blob = ndi.binary_propagation(wide, mask=mask,
                                      structure=np.ones((3, 3), bool)) & (dt2 > cfg["max_dt"] * 0.55)
        mask &= ~blob
        log(f"dropped {int(blob.sum())} px of over-wide fill")

    mask = ndi.binary_closing(mask, disk(cfg["close_r"]))
    mask = ndi.binary_opening(mask, disk(cfg["open_r"]))
    mask = remove_small_holes(mask, 2000)
    mask = remove_small_objects(mask, cfg["min_blob"], connectivity=2)
    heat = ndi.gaussian_filter((B - G).astype(float), 1.0)
    dt = ndi.distance_transform_edt(mask)
    skel = skeletonize(mask)
    log(f"mask {mask.mean()*100:.2f} %, skeleton {int(skel.sum())} px")

    nodes, edges = trace_graph(skel)
    edges = prune(edges, cfg["min_spur_m"] / mpp)
    paths = merge_chains(edges)
    log(f"graph {len(nodes)} nodes -> {len(edges)} edges -> {len(paths)} paths")

    lines = []
    for path in paths:
        if plen(path) * mpp < cfg["min_line_m"]:
            continue
        idx = tuple(np.asarray(path).T)
        pts = rdp(chaikin(path, 2), cfg["rdp_m"] / mpp)
        if len(pts) < 2:
            continue
        lines.append({"yx": [[round(float(y), 2), round(float(x), 2)] for y, x in pts],
                      "len_m": round(plen(path) * mpp, 1),
                      "width_m": round(float(np.median(2.0 * dt[idx] * mpp)), 2),
                      "heat": round(float(np.median(heat[idx])), 1)})
    total = sum(l["len_m"] for l in lines) / 1000.0
    log(f"{len(lines)} lines, {total:.1f} km")
    json.dump({"meta": {"m_per_px": mpp, "width": W, "height": H}, "lines": lines},
              io.open(cfg["network_json"], "w", encoding="utf-8"))

    im = Image.open(hm["path"]).convert("RGB")
    d = ImageDraw.Draw(im)
    for l in lines:
        d.line([(x, y) for y, x in l["yx"]], fill=(255, 0, 0), width=3)
    im.resize((W // 2, H // 2)).save(os.path.splitext(cfg["network_json"])[0] + "_overlay.png")
    log("wrote " + cfg["network_json"] + " and its _overlay.png -- LOOK AT THE OVERLAY")


def default_ui_rects(w, h):
    """Blank out the usual Strava web UI: top bar, left controls, bottom-left."""
    return [(0, 0, int(0.36 * w), int(0.062 * h)),
            (int(0.82 * w), 0, w, int(0.062 * h)),
            (0, int(0.04 * h), int(0.023 * w), int(0.16 * h)),
            (0, int(0.895 * h), int(0.095 * w), h),
            (int(0.968 * w), int(0.95 * h), w, h)]


NB = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]


def neighbours(skel, y, x):
    h, w = skel.shape
    return [(y + dy, x + dx) for dy, dx in NB
            if 0 <= y + dy < h and 0 <= x + dx < w and skel[y + dy, x + dx]]


def trace_graph(skel):
    import numpy as np
    ys, xs = np.nonzero(skel)
    pix = list(zip(ys.tolist(), xs.tolist()))
    node_at, nodes = {}, []
    for p in pix:
        if len(neighbours(skel, *p)) != 2:
            node_at[p] = len(nodes)
            nodes.append(p)
    edges, used_mid, started = [], set(), set()
    for ni, np0 in enumerate(nodes):
        for start in neighbours(skel, *np0):
            if (np0, start) in started:
                continue
            started.add((np0, start))
            path, prev, cur = [np0], np0, start
            while True:
                path.append(cur)
                if cur in node_at:
                    started.add((cur, prev))
                    break
                used_mid.add(cur)
                nxt = [p for p in neighbours(skel, *cur) if p != prev]
                if not nxt:
                    break
                prev, cur = cur, nxt[0]
            edges.append([ni, node_at.get(path[-1]), path])
    rest = set(pix) - used_mid - set(node_at)
    while rest:
        s = rest.pop()
        path, cur, prev = [s], s, None
        while True:
            nxt = [p for p in neighbours(skel, *cur) if p != prev and p in rest]
            if not nxt:
                break
            prev, cur = cur, nxt[0]
            rest.discard(cur)
            path.append(cur)
        if len(path) > 8:
            path.append(path[0])
            edges.append([None, None, path])
    return nodes, edges


def plen(path):
    import numpy as np
    d = np.diff(np.asarray(path, float), axis=0)
    return float(np.hypot(d[:, 0], d[:, 1]).sum())


def degrees_of(edges):
    d = {}
    for n0, n1, p in edges:
        for n in (n0, n1):
            if n is not None:
                d[n] = d.get(n, 0) + 1
    return d


def prune(edges, min_spur_px):
    for _ in range(30):
        deg = degrees_of(edges)
        drop = set()
        for i, (n0, n1, p) in enumerate(edges):
            ends = [n for n in (n0, n1) if n is not None]
            short = plen(p) < min_spur_px
            if len(ends) < 2 or n0 == n1:
                if short:
                    drop.add(i)
                continue
            if short and any(deg.get(n, 0) == 1 for n in ends):
                drop.add(i)
        if not drop:
            break
        edges = [e for i, e in enumerate(edges) if i not in drop]
    return edges


def merge_chains(edges):
    deg = degrees_of(edges)
    alive = [True] * len(edges)
    at = {}
    for i, (n0, n1, p) in enumerate(edges):
        for n in (n0, n1):
            if n is not None:
                at.setdefault(n, []).append(i)
    out = []
    for i, e in enumerate(edges):
        if not alive[i]:
            continue
        alive[i] = False
        path, ends = list(e[2]), [e[0], e[1]]
        for side in (0, 1):
            while True:
                n = ends[side]
                if n is None or deg.get(n, 0) != 2:
                    break
                nxt = [j for j in at[n] if alive[j]]
                if not nxt:
                    break
                j = nxt[0]
                alive[j] = False
                q = list(edges[j][2])
                far = edges[j][1] if edges[j][0] == n else edges[j][0]
                if side == 1:
                    if q[0] != path[-1]:
                        q.reverse()
                    path += q[1:]
                else:
                    if q[-1] != path[0]:
                        q.reverse()
                    path = q[:-1] + path
                ends[side] = far
        out.append(path)
    return out


def chaikin(pts, iters=2):
    pts = [tuple(p) for p in pts]
    closed = pts[0] == pts[-1]
    for _ in range(iters):
        out = [] if closed else [pts[0]]
        for a, b in zip(pts, pts[1:]):
            out.append((0.75 * a[0] + 0.25 * b[0], 0.75 * a[1] + 0.25 * b[1]))
            out.append((0.25 * a[0] + 0.75 * b[0], 0.25 * a[1] + 0.75 * b[1]))
        out.append(out[0] if closed else pts[-1])
        pts = out
    return pts


def rdp(pts, eps):
    import numpy as np
    pts = np.asarray(pts, float)
    if len(pts) < 3:
        return pts
    keep = np.zeros(len(pts), bool)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        p, q = pts[i], pts[j]
        seg = q - p
        L = float(np.hypot(*seg))
        sub = pts[i + 1:j]
        if L < 1e-9:
            d = np.hypot(*(sub - p).T)
        else:
            d = np.abs((sub - p)[:, 0] * seg[1] - (sub - p)[:, 1] * seg[0]) / L
        k = int(np.argmax(d))
        if d[k] > eps:
            keep[i + 1 + k] = True
            stack += [(i, i + 1 + k), (i + 1 + k, j)]
    return pts[keep]


# ---------------------------------------------------------------- satellite imagery
# Sentinel-2 L2A, 10 m, as COGs on AWS open data, searched through the Earth Search
# STAC API. Free and open (Copernicus Sentinel data, attribution required).
#
# One image cannot tell forest types apart, so several are merged:
#   * two or more LEAF-ON scenes (Jun-Sep)  -> the visual composite and summer NDVI
#   * two or more LEAF-OFF scenes (Nov-Mar) -> winter NDVI
# High NDVI in BOTH seasons is evergreen (spruce/pine thicket -> poor visibility and
# poor off-track rideability); high in summer only is deciduous forest, which in
# ISMTBOM is plain white forest. That contrast is the whole point of using more than
# one date.
STAC = "https://earth-search.aws.element84.com/v1/search"
S2_BANDS = ("red", "green", "blue", "nir", "swir16", "scl")
SCL_BAD = (0, 1, 3, 8, 9, 10)      # no data, saturated, cloud shadow, clouds, cirrus


def stac_search(bbox, start, end, max_cloud, limit):
    import requests
    r = requests.post(STAC, timeout=120, json={
        "collections": ["sentinel-2-l2a"], "bbox": list(bbox),
        "datetime": f"{start}T00:00:00Z/{end}T23:59:59Z",
        "query": {"eo:cloud_cover": {"lt": max_cloud}}, "limit": limit,
        "sortby": [{"field": "properties.eo:cloud_cover", "direction": "asc"}]})
    r.raise_for_status()
    return r.json()["features"]


def local_grid(cfg, res, pad):
    import numpy as np
    hw, hh = cfg["extent_m"][0] / 2, cfg["extent_m"][1] / 2
    xs = np.arange(-hw - pad, hw + pad + res, res)
    ys = np.arange(-hh - pad, hh + pad + res, res)
    return xs, ys


def grid_lonlat(frame, xs, ys):
    import numpy as np
    X, Y = np.meshgrid(xs, ys)
    lon = np.empty(X.shape)
    lat = np.empty(X.shape)
    for j in range(X.shape[0]):
        for i in range(X.shape[1]):
            lon[j, i], lat[j, i] = frame.inv(X[j, i], Y[j, i])
    return lon, lat


def read_scene(feat, lon, lat):
    """Sample one Sentinel-2 scene onto the grid. -> dict band -> float array."""
    import numpy as np
    import rasterio
    from rasterio.windows import from_bounds
    from rasterio.warp import transform
    from scipy.ndimage import map_coordinates
    os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
    os.environ.setdefault("CPL_VSIL_CURL_ALLOWED_EXTENSIONS", ".tif,.TIF")
    out, cache = {}, {}
    for b in S2_BANDS:
        href = feat["assets"][b]["href"]
        with rasterio.open("/vsicurl/" + href) as ds:
            key = str(ds.crs)
            if key not in cache:
                ex, ny = transform("EPSG:4326", ds.crs, lon.ravel().tolist(),
                                   lat.ravel().tolist())
                cache[key] = (np.array(ex).reshape(lon.shape),
                              np.array(ny).reshape(lon.shape))
            ex, ny = cache[key]
            win = from_bounds(ex.min() - 60, ny.min() - 60, ex.max() + 60,
                              ny.max() + 60, ds.transform)
            a = ds.read(1, window=win).astype(float)
            tr = ds.window_transform(win)
            col = (ex - tr.c) / tr.a
            row = (ny - tr.f) / tr.e
            order = 0 if b == "scl" else 1
            out[b] = map_coordinates(a, [row, col], order=order, mode="nearest")
    bad = np.isin(out["scl"].astype(int), SCL_BAD)
    for b in S2_BANDS:
        if b != "scl":
            out[b] = np.where(bad, np.nan, out[b])
    out["_bad"] = bad
    return out


def ndvi_of(sc):
    import numpy as np
    with np.errstate(invalid="ignore", divide="ignore"):
        return (sc["nir"] - sc["red"]) / (sc["nir"] + sc["red"])


def cmd_imagery(args):
    import numpy as np
    from PIL import Image
    cfg = load_config(args.config)
    frame = Frame(cfg["lat"], cfg["lon"])
    xs, ys = local_grid(cfg, args.res, args.pad)
    lon, lat = grid_lonlat(frame, xs, ys)
    bbox = (float(lon.min()), float(lat.min()), float(lon.max()), float(lat.max()))
    log(f"grid {len(ys)}x{len(xs)} at {args.res} m; bbox {bbox}")

    seasons = {"leaf_on": (args.on_start, args.on_end),
               "leaf_off": (args.off_start, args.off_end)}
    stacks, used = {}, []
    for season, (a, b) in seasons.items():
        feats = stac_search(bbox, a, b, args.max_cloud, args.per_season * 3)
        picked, seen = [], set()
        for f in feats:
            day = f["properties"]["datetime"][:10]
            if day in seen:
                continue
            seen.add(day)
            picked.append(f)
            if len(picked) >= args.per_season:
                break
        if not picked:
            log(f"!! no {season} scene under {args.max_cloud} % cloud in {a}..{b}")
            continue
        scenes = []
        for f in picked:
            sc = read_scene(f, lon, lat)
            frac = float(np.mean(sc["_bad"]))
            log(f"  {season:<8} {f['id']} {f['properties']['datetime'][:10]} "
                f"cloud {f['properties'].get('eo:cloud_cover', 0):.1f} %, "
                f"masked here {frac*100:.1f} %")
            if frac > 0.4:
                log("    too much cloud over the map itself; skipped")
                continue
            scenes.append(sc)
            used.append({"season": season, "id": f["id"],
                         "date": f["properties"]["datetime"][:10],
                         "cloud": f["properties"].get("eo:cloud_cover")})
        if not scenes:
            continue
        stacks[season] = {
            "ndvi": np.nanmedian(np.stack([ndvi_of(s) for s in scenes]), axis=0),
            "swir": np.nanmedian(np.stack([s["swir16"] for s in scenes]), axis=0),
            "rgb": [np.nanmedian(np.stack([s[c] for s in scenes]), axis=0)
                    for c in ("red", "green", "blue")],
            "n": len(scenes)}
    if "leaf_on" not in stacks:
        sys.exit("no usable leaf-on scene; widen --on-start/--on-end or --max-cloud")

    # ---- visual composite, in the map's own frame, for use as a Mapper template
    rgb = stacks["leaf_on"]["rgb"]
    img = np.zeros(rgb[0].shape + (3,), np.uint8)
    for i, band in enumerate(rgb):
        v = np.nan_to_num(band, nan=float(np.nanmedian(band)))
        lo, hi = np.percentile(v, (1, 97))
        t = np.clip((v - lo) / max(hi - lo, 1e-6), 0, 1) ** 0.55   # gamma: forest is dark
        img[..., i] = (t * 255).astype(np.uint8)
    Image.fromarray(img).save(cfg["satellite_png"])
    with io.open(os.path.splitext(cfg["satellite_png"])[0] + ".pgw", "w") as f:
        # world file in the map's own projected CRS (y north), pixel centres
        f.write(f"{args.res}\n0.0\n0.0\n{-args.res}\n"
                f"{xs[0] + args.res/2}\n{-ys[0] - args.res/2}\n")
    with io.open(os.path.splitext(cfg["satellite_png"])[0] + ".prj", "w") as f:
        f.write(frame.proj4 + "\n")

    np.savez_compressed(cfg["s2_npz"],
                        x0=xs[0], y0=ys[0], res=args.res,
                        shape=np.array(img.shape[:2]),
                        ndvi_on=stacks["leaf_on"]["ndvi"],
                        swir_on=stacks["leaf_on"]["swir"],
                        ndvi_off=stacks.get("leaf_off", {}).get(
                            "ndvi", np.full(img.shape[:2], np.nan)))
    cfg["imagery"] = {"scenes": used, "res": args.res, "pad": args.pad,
                      "leaf_off": "leaf_off" in stacks}
    save_config(args.config, cfg)
    log(f"wrote {cfg['satellite_png']} (+ .pgw/.prj) and {cfg['s2_npz']} from "
        f"{len(used)} scenes")

    # a quick NDVI-difference review picture
    if "leaf_off" in stacks:
        d = stacks["leaf_on"]["ndvi"] - stacks["leaf_off"]["ndvi"]
        v = np.clip((np.nan_to_num(d, nan=0) + 0.2) / 0.8, 0, 1)
        Image.fromarray((v * 255).astype(np.uint8)).save(
            os.path.splitext(cfg["satellite_png"])[0] + "_ndvi_diff.png")


# ---------------------------------------------------------------- vegetation
# ESA WorldCover 10 m (2021, v200): free, CC BY 4.0, 3x3 degree tiles on AWS.
WORLDCOVER = ("https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/"
              "ESA_WorldCover_10m_2021_v200_{ns}{lat:02d}{ew}{lon:03d}_Map.tif")
WC_TREE, WC_SHRUB, WC_GRASS, WC_CROP = 10, 20, 30, 40
WC_BUILT, WC_BARE, WC_WATER, WC_WETLAND = 50, 60, 80, 90


def read_worldcover(lon, lat):
    import numpy as np
    import rasterio
    from rasterio.windows import from_bounds
    from scipy.ndimage import map_coordinates
    os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
    os.environ.setdefault("CPL_VSIL_CURL_ALLOWED_EXTENSIONS", ".tif,.TIF")
    out = np.zeros(lon.shape, np.uint8)
    la0 = int(math.floor(lat.min() / 3) * 3)
    la1 = int(math.floor(lat.max() / 3) * 3)
    lo0 = int(math.floor(lon.min() / 3) * 3)
    lo1 = int(math.floor(lon.max() / 3) * 3)
    for la in range(la0, la1 + 1, 3):
        for lo in range(lo0, lo1 + 1, 3):
            url = WORLDCOVER.format(ns="N" if la >= 0 else "S", lat=abs(la),
                                    ew="E" if lo >= 0 else "W", lon=abs(lo))
            try:
                with rasterio.open("/vsicurl/" + url) as ds:
                    b = ds.bounds
                    if (lon.max() < b.left or lon.min() > b.right
                            or lat.max() < b.bottom or lat.min() > b.top):
                        continue
                    win = from_bounds(max(lon.min() - 0.01, b.left),
                                      max(lat.min() - 0.01, b.bottom),
                                      min(lon.max() + 0.01, b.right),
                                      min(lat.max() + 0.01, b.top), ds.transform)
                    a = ds.read(1, window=win)
                    tr = ds.window_transform(win)
                log(f"WorldCover {os.path.basename(url)[-16:]} window {a.shape}")
            except Exception as ex:
                log(f"WorldCover tile failed ({type(ex).__name__}: {ex})")
                continue
            col = (lon - tr.c) / tr.a
            row = (lat - tr.f) / tr.e
            ok = ((col >= 0) & (col <= a.shape[1] - 1)
                  & (row >= 0) & (row <= a.shape[0] - 1))
            if ok.any():
                v = map_coordinates(a, [row[ok], col[ok]], order=0, mode="nearest")
                out[ok] = v
    return out


def polygonise(mask, x0, y0, res, min_area_m2, simplify_m):
    """Boolean grid -> list of ring lists in local metres."""
    import numpy as np
    from rasterio.features import shapes
    from rasterio.transform import Affine
    from shapely.geometry import shape as shp_shape
    tr = Affine(res, 0, x0 - res / 2, 0, res, y0 - res / 2)
    out = []
    for geom, val in shapes(mask.astype(np.uint8), mask=mask, transform=tr):
        g = shp_shape(geom)
        if g.area < min_area_m2:
            continue
        g = g.simplify(simplify_m, preserve_topology=True)
        if g.is_empty or g.area < min_area_m2:
            continue
        for poly in getattr(g, "geoms", [g]):
            out.append([list(poly.exterior.coords)]
                       + [list(h.coords) for h in poly.interiors
                          if abs(h.length) > 4 * simplify_m])
    return out


def cmd_vegetation(args):
    import numpy as np
    from scipy import ndimage as ndi
    from shapely.geometry import Polygon, box
    from shapely.ops import unary_union
    cfg = load_config(args.config)
    frame = Frame(cfg["lat"], cfg["lon"])
    if not os.path.exists(cfg["s2_npz"]):
        sys.exit("run `imagery` first")
    z = np.load(cfg["s2_npz"])
    res = float(z["res"])
    x0, y0 = float(z["x0"]), float(z["y0"])
    ndvi_on, ndvi_off = z["ndvi_on"], z["ndvi_off"]
    xs = x0 + np.arange(ndvi_on.shape[1]) * res
    ys = y0 + np.arange(ndvi_on.shape[0]) * res
    lon, lat = grid_lonlat(frame, xs, ys)
    wc = read_worldcover(lon, lat)
    has_off = bool(np.isfinite(ndvi_off).mean() > 0.5)
    log(f"grid {ndvi_on.shape} at {res} m; leaf-off NDVI available: {has_off}")
    for k, v in sorted(collections.Counter(wc.ravel().tolist()).items()):
        log(f"  WorldCover class {k:>3}: {v/wc.size*100:5.1f} %")

    tree = wc == WC_TREE
    # Evergreen canopy: NDVI barely drops when the leaves come off. Deciduous forest
    # here falls by ~0.40 (median), conifer by <0.20 -- the histogram of the drop
    # inside tree cover is bimodal, which is why two seasons are worth fetching.
    delta = ndvi_on - ndvi_off
    if has_off:
        evergreen = tree & (delta < args.evergreen_delta) & (ndvi_off > args.evergreen_ndvi)
    else:
        evergreen = np.zeros_like(tree)
        log("!! no leaf-off scene: evergreen/thicket detection disabled")
    dense = evergreen | (wc == WC_SHRUB)
    log(f"  drop within tree cover: median {np.nanmedian(delta[tree]):.2f}, "
        f"{float(np.mean(delta[tree] < args.evergreen_delta))*100:.0f} % below "
        f"{args.evergreen_delta}")
    classes = {
        "406": dense,                                    # thicket / evergreen: poor visibility
        "401": (wc == WC_CROP) | (wc == WC_GRASS) | (wc == WC_BARE),
        "308": wc == WC_WETLAND,
    }
    # WorldCover's built-up class is the settlement, already handled from OSM
    out = {}
    minpx = int(round(args.min_area_m2 / (res * res)))
    for code, m in classes.items():
        m = ndi.binary_opening(m, np.ones((3, 3), bool))
        m = ndi.binary_closing(m, np.ones((5, 5), bool))
        m = ndi.binary_fill_holes(m)
        lab, n = ndi.label(m)
        if n:
            keep = np.zeros(n + 1, bool)
            cnt = np.bincount(lab.ravel(), minlength=n + 1)
            keep[1:] = cnt[1:] >= minpx
            m = keep[lab]
        rings = polygonise(m, x0, y0, res, args.min_area_m2, args.simplify_m)
        out[code] = rings
        log(f"  {code}: {m.sum()*res*res/1e4:.1f} ha -> {len(rings)} areas")

    # do not draw over what OSM already says: OSM polygons are surveyed, these are not
    osm_union = None
    if args.subtract_osm and os.path.exists(cfg["osm_json"]):
        polys = []
        for e in json.load(io.open(cfg["osm_json"], encoding="utf-8"))["elements"]:
            t = e.get("tags") or {}
            code, kind = classify_way(t)
            if kind != "area" or not code:
                continue
            g = e.get("geometry") or []
            pts = [frame.fwd(p["lon"], p["lat"]) for p in g if p]
            if len(pts) < 4:
                continue
            try:
                p = Polygon(pts)
                if not p.is_valid:
                    p = p.buffer(0)
                if not p.is_empty:
                    polys.append(p)
            except Exception:
                pass
        if polys:
            osm_union = unary_union(polys)
            log(f"subtracting {len(polys)} OSM area polygons "
                f"({osm_union.area/1e4:.0f} ha)")

    hw, hh = cfg["extent_m"][0] / 2, cfg["extent_m"][1] / 2
    clip = box(-hw, -hh, hw, hh)
    veg = []
    for code, rings in out.items():
        for r in rings:
            try:
                p = Polygon(r[0], r[1:])
                if not p.is_valid:
                    p = p.buffer(0)
            except Exception:
                continue
            p = p.intersection(clip)
            if osm_union is not None and not p.is_empty:
                p = p.difference(osm_union)
            if p.is_empty:
                continue
            for q in getattr(p, "geoms", [p]):
                if not isinstance(q, Polygon) or q.area < args.min_area_m2:
                    continue
                veg.append({"code": code,
                            "rings": [[list(c) for c in q.exterior.coords]]
                                     + [[list(c) for c in h.coords] for h in q.interiors]})
    json.dump({"source": "ESA WorldCover 10 m 2021 v200 + Sentinel-2 seasonal NDVI",
               "evergreen_delta": args.evergreen_delta,
               "evergreen_ndvi": args.evergreen_ndvi, "areas": veg},
              io.open(cfg["vegetation_json"], "w", encoding="utf-8"))
    cfg["vegetation"] = True
    save_config(args.config, cfg)
    log(f"wrote {cfg['vegetation_json']}: {len(veg)} areas")

    # review picture: the classified areas over the satellite composite
    if os.path.exists(cfg["satellite_png"]):
        from PIL import Image, ImageDraw
        im = Image.open(cfg["satellite_png"]).convert("RGB")
        d = ImageDraw.Draw(im)
        cols = {"406": (255, 0, 255), "401": (255, 255, 0), "308": (0, 255, 255)}
        for a in veg:
            for ring in a["rings"]:
                pts = [((x - x0) / res, (y - y0) / res) for x, y in ring]
                d.line(pts + [pts[0]], fill=cols.get(a["code"], (255, 0, 0)), width=2)
        out = os.path.splitext(cfg["out"])[0] + "_veg_check.png"
        im.save(out)
        log("wrote " + out + " -- LOOK AT IT: 406 must land on darker, denser canopy")


# ---------------------------------------------------------------- contours
# Copernicus DEM GLO-30: 1-degree COGs on AWS open data, no credentials, free
# licence with attribution ("(c) DLR e.V. 2010-2014 and (c) Airbus Defence and
# Space GmbH 2014-2018 provided under COPERNICUS by the European Union and ESA").
# It is a SURFACE model at 30 m posting: in forest it follows the canopy, so 5 m
# contours out of it are indicative shapes, not surveyed contours.
DEM_URL = ("https://copernicus-dem-30m.s3.eu-central-1.amazonaws.com/"
           "Copernicus_DSM_COG_10_{ns}{lat:02d}_00_{ew}{lon:03d}_00_DEM/"
           "Copernicus_DSM_COG_10_{ns}{lat:02d}_00_{ew}{lon:03d}_00_DEM.tif")


def dem_tiles(s_, w_, n_, e_):
    for la in range(math.floor(s_), math.floor(n_) + 1):
        for lo in range(math.floor(w_), math.floor(e_) + 1):
            yield DEM_URL.format(ns="N" if la >= 0 else "S", lat=abs(la),
                                 ew="E" if lo >= 0 else "W", lon=abs(lo))


def sample_dem(cfg, frame, xs, ys):
    """Sample the DEM onto the local grid (xs east, ys south), metres. -> 2-D array."""
    import numpy as np
    import rasterio
    from rasterio.windows import from_bounds
    from scipy.ndimage import map_coordinates
    os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
    os.environ.setdefault("CPL_VSIL_CURL_ALLOWED_EXTENSIONS", ".tif")

    X, Y = np.meshgrid(xs, ys)
    lon = np.empty(X.shape)
    lat = np.empty(X.shape)
    for j in range(X.shape[0]):
        for i in range(X.shape[1]):
            lon[j, i], lat[j, i] = frame.inv(X[j, i], Y[j, i])
    out = np.full(X.shape, np.nan)
    s_, w_, n_, e_ = lat.min(), lon.min(), lat.max(), lon.max()
    pad = 0.01
    for url in dem_tiles(s_, w_, n_, e_):
        try:
            with rasterio.open("/vsicurl/" + url) as ds:
                b = ds.bounds
                if e_ < b.left or w_ > b.right or n_ < b.bottom or s_ > b.top:
                    continue
                win = from_bounds(max(w_ - pad, b.left), max(s_ - pad, b.bottom),
                                  min(e_ + pad, b.right), min(n_ + pad, b.top),
                                  ds.transform)
                a = ds.read(1, window=win, masked=True).filled(np.nan)
                tr = ds.window_transform(win)
                log(f"DEM {os.path.basename(url)[:34]}... window {a.shape}")
        except Exception as ex:
            log(f"DEM tile unavailable ({type(ex).__name__}: {ex}); skipped")
            continue
        # pixel indices of every grid node in this window
        col = (lon - tr.c) / tr.a
        row = (lat - tr.f) / tr.e
        inside = (col >= 0) & (col <= a.shape[1] - 1) & (row >= 0) & (row <= a.shape[0] - 1)
        if not inside.any():
            continue
        v = map_coordinates(np.nan_to_num(a, nan=float(np.nanmin(a))),
                            [row[inside], col[inside]], order=1, mode="nearest")
        out[inside] = v
    return out


def cmd_contours(args):
    """Write a contour .omap-fragment file that `build` splices in."""
    import numpy as np
    from scipy.ndimage import gaussian_filter
    from skimage.measure import find_contours
    cfg = load_config(args.config)
    frame = Frame(cfg["lat"], cfg["lon"])
    hw, hh = cfg["extent_m"][0] / 2, cfg["extent_m"][1] / 2
    pad = args.pad
    step = args.spacing
    xs = np.arange(-hw - pad, hw + pad + step, step)
    ys = np.arange(-hh - pad, hh + pad + step, step)
    z = sample_dem(cfg, frame, xs, ys)
    if np.isnan(z).all():
        sys.exit("no DEM data covered the map extent")
    z = np.where(np.isnan(z), np.nanmedian(z), z)
    log(f"DEM grid {z.shape} at {step} m, elevation {z.min():.1f}-{z.max():.1f} m")

    sigma = args.smooth_m / step
    zs = gaussian_filter(z, sigma) if sigma > 0 else z
    interval = args.interval
    lo = math.floor(zs.min() / interval) * interval
    hi = math.ceil(zs.max() / interval) * interval
    lines = []
    for lev in np.arange(lo, hi + interval, interval):
        for c in find_contours(zs, lev):
            pts = [(xs[0] + p[1] * step, ys[0] + p[0] * step) for p in c]
            if len(pts) < 3:
                continue
            pts = [(float(x), float(y)) for x, y in rdp(pts, args.rdp_m)]
            lines.append({"z": float(lev), "pts": pts})
    log(f"{len(lines)} contour lines, {interval} m interval, "
        f"index every {interval*args.index_every} m, smoothing sigma {args.smooth_m} m")
    json.dump({"interval": interval, "index_every": args.index_every,
               "smooth_m": args.smooth_m, "spacing_m": step,
               "source": "Copernicus DEM GLO-30 (DSM, 30 m)",
               "z_min": float(z.min()), "z_max": float(z.max()), "lines": lines},
              io.open(cfg["contours_json"], "w", encoding="utf-8"))
    cfg["contours"] = True
    save_config(args.config, cfg)
    log("wrote " + cfg["contours_json"])


# ---------------------------------------------------------------- rideability
FAST, MED, SLOW, VSLOW = 0, 1, 2, 3
TRACK = ["815", "817", "819", "821"]
PATH = ["816", "818", "820", "822"]
PAVED = {"asphalt", "concrete", "concrete:plates", "concrete:lanes", "paving_stones",
         "sett", "cobblestone", "chipseal", "metal", "wood", "paved", "bricks"}
SMOOTH_PENALTY = {"bad": 1, "very_bad": 1, "horrible": 2, "very_horrible": 2,
                  "impassable": 3}
SURF_BAND = {"": MED, "compacted": FAST, "gravel": FAST, "fine_gravel": FAST,
             "pebblestone": MED, "unpaved": MED, "ground": MED, "dirt": MED,
             "earth": MED, "mud": VSLOW, "grass": SLOW, "sand": SLOW,
             "dirt/sand": SLOW, "woodchips": SLOW}
TRACKTYPE_BAND = {"grade1": FAST, "grade2": FAST, "grade3": MED, "grade4": SLOW,
                  "grade5": VSLOW}
ROADS = {"motorway", "trunk", "primary", "secondary", "tertiary", "unclassified",
         "residential", "living_street", "service", "road", "motorway_link",
         "trunk_link", "primary_link", "secondary_link", "tertiary_link"}
PATHS = {"path", "cycleway", "footway", "bridleway"}


def band(t):
    surf = t.get("surface", "")
    b = TRACKTYPE_BAND.get(t.get("tracktype", ""))
    if b is None:
        b = FAST if surf in PAVED else SURF_BAND.get(surf, MED)
    if surf in ("sand", "mud"):
        b = max(b, SLOW)
    return min(b + SMOOTH_PENALTY.get(t.get("smoothness", ""), 0), VSLOW)


def width_of(t):
    for k in ("width", "est_width"):
        m = re.match(r"\s*([\d.]+)", str(t.get(k, "")))
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                pass
    return None


def classify_highway(t):
    hw, surf = t.get("highway"), t.get("surface", "")
    if hw == "steps":
        return "532", None, None
    if hw in ROADS:
        if surf in PAVED or surf == "":
            return "502", None, None
        b = band(t)
        return ("502.1" if b == FAST else TRACK[b]), b, "road"
    if hw == "track":
        if surf in PAVED:
            return "502", None, None
        b = band(t)
        return TRACK[b], b, "track"
    if hw in PATHS:
        b = band(t)
        w = width_of(t)
        wide = w is not None and w >= 1.8
        return (TRACK if wide else PATH)[b], b, ("track" if wide else "path")
    return None, None, None


def code_for(fam, b):
    if fam == "road" and b == FAST:
        return "502.1"
    return (PATH if fam == "path" else TRACK)[b]


def classify_way(t):
    if t.get("railway") in ("rail", "light_rail", "narrow_gauge", "tram", "subway"):
        return "509", "line"
    if t.get("power") == "line":
        return "511", "line"
    if t.get("power") in ("minor_line", "cable"):
        return "510", "line"
    wr = t.get("waterway")
    if wr in ("river", "canal"):
        return "304", "line"
    if wr == "stream":
        return "305", "line"
    if wr in ("ditch", "drain"):
        return "306", "line"
    nat, lu, le = t.get("natural"), t.get("landuse"), t.get("leisure")
    if nat == "water" or lu in ("reservoir", "basin") or le == "swimming_pool" or t.get("water"):
        return "301.2", "area"
    if nat == "wetland":
        return "308", "area"
    if nat == "scrub":
        return "406", "area"
    if nat in ("sand", "beach"):
        return "213", "area"
    if nat in ("bare_rock", "rock", "scree"):
        return "214", "area"
    if nat == "wood" or lu == "forest":
        return None, None                       # forest is the white background
    if nat in ("grassland", "meadow"):
        return "401", "area"
    if nat == "heath":
        return "403", "area"
    if lu == "orchard":
        return "413", "area"
    if lu == "vineyard":
        return "414", "area"
    if lu in ("plant_nursery", "allotments"):
        return "413", "area"
    if lu in ("meadow", "grass", "farmland", "farmyard", "village_green",
              "recreation_ground", "cemetery", "construction", "religious"):
        return "401", "area"
    if lu in ("residential", "industrial", "commercial", "retail", "garages"):
        return "520", "area"        # no ISMTBOM settlement symbol; private land

    if le in ("pitch", "playground", "park", "garden", "golf_course", "track"):
        return "401", "area"
    if t.get("building"):
        return "521", "area"
    bar = t.get("barrier")
    if bar in ("fence", "guard_rail", "handrail"):
        return "516", "line"
    if bar in ("wall", "retaining_wall", "city_wall"):
        return "513", "line"
    if bar == "hedge":
        return "528", "line"        # ISMTBOM 410 is an area only
    if t.get("man_made") == "pier":
        return "528", "line"
    return None, None


def classify_node(t):
    if t.get("natural") == "peak":
        return "603"
    if t.get("natural") == "tree":
        return "417"
    if t.get("natural") == "spring":
        return "313"
    if t.get("natural") in ("rock", "stone"):
        return "204"
    if t.get("man_made") in ("mast", "tower", "water_tower", "communications_tower"):
        return "524"
    if t.get("man_made") in ("cross", "obelisk", "flagpole"):
        return "531"
    if t.get("man_made") in ("water_well", "spring_box"):
        return "313"
    if t.get("historic") in ("monument", "memorial", "wayside_cross", "wayside_shrine"):
        return "531"
    if t.get("barrier") in ("gate", "lift_gate", "swing_gate", "cycle_barrier", "bollard"):
        return "519"
    if t.get("tourism") in ("picnic_site", "viewpoint"):
        return "530"
    return None


# ---------------------------------------------------------------- the spec's own list
# Symbol numbers defined by ISMTBOM 2022 (Revision 4, January 2025). Nothing else
# may reach the map: the OpenOrienteering donor set also carries ISOM symbols that
# ISMTBOM does not define. Those are dropped from the symbol set, and objects that
# would have used them are moved onto the nearest ISMTBOM symbol (ISOM_TO_ISMTBOM).
SPEC_CODES = {
    "101", "102", "104", "105", "107", "108", "109",
    "201", "204", "206", "210", "213", "214",
    "301", "304", "305", "306", "307", "308", "313",
    "401", "402", "403", "404", "405", "406", "407", "410", "413", "414",
    "417", "418", "419",
    "501", "501.1", "501.4", "502", "502.1",
    "509", "510", "511", "512", "513", "515", "516", "518", "519", "520",
    "521", "522", "522.1", "524", "525", "527", "528", "529", "530", "531", "532",
    "601", "603",
    "701", "702", "703", "703.1", "704", "705", "706", "707", "708", "709",
    "710", "712", "713", "715", "716", "717", "718", "719",
    "815", "816", "817", "818", "819", "820", "821", "822", "823",
    "824", "825", "825.1", "825.2", "826", "827", "828", "829", "830", "841",
}

# Everything on the left is NOT an ISMTBOM 2022 symbol; the right-hand side is.
ISOM_TO_ISMTBOM = {
    "312": "313",           # Well             -> Prominent water feature
    "313-ISOM": "313",      # Spring           -> Prominent water feature
    "302": "301",           # Pond             -> Uncrossable body of water
    "303": "313",           # Waterhole        -> Prominent water feature
    "311": "308",           # Indistinct marsh -> Marsh
    "308-ISOM": "308",      # Narrow marsh     -> Marsh
    "415": "401",           # Cultivated land  -> Open land
    "527.1": "520",         # Settlement       -> Area that shall not be entered
    "527-ISOM": "520",
    "408": "406", "409": "406",
    "103": "101",           # Form line        -> Contour
    "504": "817", "505": "819", "506": "818", "507": "820", "508": "822",
    "509-ISOM": "830",      # Narrow ride      -> narrow ride, permitted to ride
    "512-ISOM": "512", "520-ISOM": "515", "523": "516", "537": "530",
    "530-ISOM": "530", "530.1": "530", "530.2": "530",
    "531-ISOM": "531", "532-ISOM": "530", "204-ISOM": "204", "206.1": "204",
    "207": "204", "208": "210", "208.1": "210", "209": "210", "209.1": "210",
    "210-ISOM": "210", "113": "109", "115": "109", "116": "109",
    "117.1": "210", "117.2": "210", "118": "531", "205": "530",
    "108-ISOM": "105", "416": "528", "414-ISOM": "528", "203": "201",
    "203.1": "201", "203.2": "201", "411.0": "406", "411.1": "406", "411.2": "406",
    "501.0": "502", "501.5": "502", "502.1-ISOM": "502", "503.1": "502",
    "602": None, "799": None, "980.0.2": None, "999": None,   # no ISMTBOM equivalent
}


def spec_variant(code, name):
    """True for an ISMTBOM 2022 symbol, or a Mapper implementation detail of one:
    301.2 = area + bank line, 601.1 = the north-line pattern, 603.1 = the spot
    height's text, X.0.1 = a minimum-size point version of a line/area symbol."""
    if "-ISOM" in code or "(ISOM)" in name:
        return False
    c = code
    while True:
        if c in SPEC_CODES:
            return True
        if "." not in c:
            return False
        c = c.rsplit(".", 1)[0]


def filter_symbol_set(symbols):
    """Drop every symbol ISMTBOM 2022 does not define, renumber the rest, and fix
    the combined symbols' part references.

    Only top-level symbols carry id="..."; mid-symbols and point elements are
    nested <symbol> tags without one, so the blocks must be cut at the id-bearing
    openers -- a non-greedy <symbol ...>.*?</symbol> truncates them silently.
    """
    opens = list(re.finditer(
        r'<symbol type="(\d+)" id="(\d+)" code="([^"]*)" name="([^"]*)"', symbols))
    end = symbols.rindex("</symbols>")
    blocks = []
    for i, m in enumerate(opens):
        stop = opens[i + 1].start() if i + 1 < len(opens) else end
        blocks.append({"id": int(m.group(2)), "code": m.group(3),
                       "name": m.group(4), "xml": symbols[m.start():stop]})
    by_id = {b["id"]: b for b in blocks}
    keep = {b["id"] for b in blocks if spec_variant(b["code"], b["name"])}
    changed = True
    while changed:                       # a kept combined symbol needs its parts
        changed = False
        for i in list(keep):
            for pm in re.finditer(r'<part symbol="(\d+)"/>', by_id[i]["xml"]):
                j = int(pm.group(1))
                if j in by_id and j not in keep:
                    keep.add(j)
                    changed = True
    kept = [b for b in blocks if b["id"] in keep]
    remap = {b["id"]: i for i, b in enumerate(kept)}
    out, by_code = [], {}
    for b in kept:
        x = re.sub(r'(<symbol type="\d+" id=")\d+(")',
                   lambda m, nid=remap[b["id"]]: m.group(1) + str(nid) + m.group(2),
                   b["xml"], count=1)
        x = re.sub(r'<part symbol="(\d+)"/>',
                   lambda m: '<part symbol="%d"/>' % remap[int(m.group(1))], x)
        out.append(x)
        by_code[b["code"]] = (remap[b["id"]], None)
    log(f"symbol set: {len(blocks)} donor symbols -> {len(kept)} ISMTBOM 2022 "
        f"({len(blocks) - len(kept)} non-ISMTBOM dropped)")
    return ('<symbols count="%d" id="ISMTBOM2022">' % len(kept)
            + "".join(out) + "</symbols>"), by_code


# ---------------------------------------------------------------- omap writing
class Objects:
    def __init__(self, by_code, um_per_m):
        self.by_code, self.um = by_code, um_per_m
        self.parts, self.count = [], collections.Counter()
        self.missing, self.converted = collections.Counter(), collections.Counter()

    def resolve(self, code):
        """Non-ISMTBOM code -> the ISMTBOM symbol it becomes (or None to drop)."""
        if code in self.by_code:
            return code
        if code in ISOM_TO_ISMTBOM:
            alt = ISOM_TO_ISMTBOM[code]
            if alt and alt in self.by_code:
                self.converted[code + " -> " + alt] += 1
                return alt
        self.missing[code] += 1
        return None

    def _sid(self, code):
        return None if code is None else self.by_code[code][0]

    def _coords(self, pts, closed=False):
        out = ["%d %d" % (round(x * self.um), round(y * self.um)) for x, y in pts]
        if closed:
            out[-1] += " 18"
        return ";".join(out) + ";"

    def line(self, code, pts):
        code = self.resolve(code)
        sid = self._sid(code)
        if sid is None or len(pts) < 2:
            return
        self.parts.append('<object type="1" symbol="%d"><coords count="%d">%s</coords>'
                          '<pattern rotation="0"><coord x="0" y="0"/></pattern></object>'
                          % (sid, len(pts), self._coords(pts)))
        self.count[code] += 1

    def area(self, code, rings):
        code = self.resolve(code)
        sid = self._sid(code)
        if sid is None:
            return
        chunks, n = [], 0
        for ring in rings:
            pts = list(ring)
            if pts[0] != pts[-1]:
                pts.append(pts[0])
            if len(pts) < 4:
                continue
            chunks.append(self._coords(pts, closed=True))
            n += len(pts)
        if not chunks:
            return
        self.parts.append('<object type="1" symbol="%d"><coords count="%d">%s</coords>'
                          '<pattern rotation="0"><coord x="0" y="0"/></pattern></object>'
                          % (sid, n, "".join(chunks)))
        self.count[code] += 1

    def point(self, code, pt):
        code = self.resolve(code)
        sid = self._sid(code)
        if sid is None:
            return
        self.parts.append('<object type="0" symbol="%d"><coords count="1">%s</coords>'
                          '</object>' % (sid, self._coords([pt])))
        self.count[code] += 1

    def text(self, code, pt, s):
        code = self.resolve(code)
        sid = self._sid(code)
        if sid is None:
            return
        esc = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        self.parts.append('<object type="4" symbol="%d" h_align="0" v_align="2">'
                          '<coords count="1">%s</coords><text>%s</text></object>'
                          % (sid, self._coords([pt]), esc))
        self.count[code] += 1


def load_donor(path, scale):
    d = io.open(path, encoding="utf-8").read()
    colors = re.search(r"<colors count=\"\d+\">.*?</colors>", d, re.S).group(0)
    symbols = re.search(r"<symbols count=\"\d+\" id=\"[^\"]*\">.*?</symbols>", d, re.S).group(0)
    src_scale = int(re.search(r"<georeferencing[^>]*?scale=\"(\d+)\"", d).group(1))
    if src_scale != scale:
        raise SystemExit(f"donor symbol set is at 1:{src_scale}, target is 1:{scale} -- "
                         "rescale the set first (see the mtbo-map-conversion skill)")
    if 'line_spacing="30000"' in symbols and scale == 15000:
        symbols = symbols.replace('<pattern type="1" angle="1.5708" line_spacing="30000"',
                                  '<pattern type="1" angle="1.5708" line_spacing="20000"')
    symbols, by_code = filter_symbol_set(symbols)
    return colors, symbols, by_code


def matrix(f):
    v = [f, 0, 0, 0, f, 0, 0, 0, 1]
    return "".join('<element value="%g"/>' % x for x in v)


NOTES = """{name} -- MTBO base map, ISMTBOM 2022, 1:{scale}.

Base data: (c) OpenStreetMap contributors, ODbL 1.0. This attribution must be
kept on any printed or published version of this map.
{heat}
{dem}{veg}NOT SURVEYED. The riding-speed classes (502/502.1/815-822) are inferred from OSM
surface, tracktype and smoothness tags{heat2}; contours are not included at all.
Everything needs field checking before the map is used for a competition.
"""


def write_omap(cfg, colors, symbols, obj, frame):
    scale = cfg["scale"]
    hw, hh = cfg["extent_m"][0] / 2, cfg["extent_m"][1] / 2
    heat_note, heat2 = "", ""
    tpl_items = []
    if cfg.get("heatmap"):
        hm = cfg["heatmap"]
        heat_note = (f"Path network reinforced from a Strava global heatmap screenshot "
                     f"({hm['width']}x{hm['height']} px at {hm['m_per_px']:.4f} m/px, "
                     f"centred on {cfg['lat']} / {cfg['lon']}).\n")
        heat2 = " plus heatmap usage"
        if cfg.get("template"):
            tpl_items.append((hm["path"], hm["m_per_px"], 0.0, 0.0))
    if cfg.get("satellite_template") and cfg.get("imagery") \
            and os.path.exists(cfg["satellite_png"]):
        r = cfg["imagery"]["res"]
        # the composite is drawn on the local grid, so its centre is the map centre
        tpl_items.append((cfg["satellite_png"].replace("\\", "/"), r, 0.0, 0.0))
    if tpl_items:
        parts = []
        for path, mpp, tx, ty in tpl_items:
            f = mpp / scale * 1000.0
            parts.append(
                f'<template type="TemplateImage" open="true" '
                f'name="{os.path.basename(path)}" path="{path}">'
                '<transformations adjustment_dirty="true" passpoints="0">'
                f'<transformation role="active" x="{round(tx)}" y="{round(ty)}" '
                f'scale_x="{f:.7f}" scale_y="{f:.7f}" rotation="0"/>'
                '<transformation role="other" x="0" y="0" scale_x="1" scale_y="1" '
                'rotation="0"/>'
                f'<matrix role="map_to_template" n="3" m="3">{matrix(1/f)}</matrix>'
                f'<matrix role="template_to_map" n="3" m="3">{matrix(f)}</matrix>'
                '<matrix role="template_to_map_other" n="0" m="0"/>'
                '</transformations></template>')
        templates = ('<templates count="%d" first_front_template="%d">'
                     % (len(parts), len(parts)) + "".join(parts)
                     + '<defaults use_meters_per_pixel="true" meters_per_pixel="1" '
                       'dpi="0" scale="0"/></templates>')
    else:
        templates = ('<templates count="0" first_front_template="0">'
                     '<defaults use_meters_per_pixel="true" meters_per_pixel="1" '
                     'dpi="0" scale="0"/></templates>')
    geo = (f'<georeferencing scale="{scale}" declination="0" grivation="0">'
           f'<ref_point x="0" y="0"/>'
           f'<projected_crs id="PROJ.4"><spec language="PROJ.4">{frame.proj4}</spec>'
           f'<ref_point x="0" y="0"/></projected_crs>'
           f'<geographic_crs id="Geographic coordinates"><spec language="PROJ.4">'
           f'+proj=latlong +datum=WGS84</spec>'
           f'<ref_point_deg lat="{cfg["lat"]}" lon="{cfg["lon"]}"/></geographic_crs>'
           f'</georeferencing>')
    dem_note = ""
    if cfg.get("contours") and os.path.exists(cfg["contours_json"]):
        cd = json.load(io.open(cfg["contours_json"], encoding="utf-8"))
        dem_note = (f"Contours: {cd['interval']:g} m interval from {cd['source']}, "
                    f"(c) DLR e.V. 2010-2014 and (c) Airbus Defence and Space GmbH "
                    f"2014-2018, provided under COPERNICUS by the European Union and "
                    f"ESA. A 30 m surface model follows the forest canopy: treat the "
                    f"contours as indicative shapes only.\n\n")
    veg_note = ""
    if cfg.get("vegetation") and os.path.exists(cfg["vegetation_json"]):
        sc = ", ".join(f"{x['date']}" for x in cfg.get("imagery", {}).get("scenes", []))
        veg_note = ("Vegetation (406/401/308) classified from ESA WorldCover 10 m 2021 "
                    "(CC BY 4.0) refined with seasonal Sentinel-2 NDVI "
                    f"({sc}); Copernicus Sentinel data, (c) ESA. Remotely sensed at "
                    "10 m: 406 marks evergreen or shrub canopy as a proxy for reduced "
                    "visibility and off-track rideability.\n\n")
    notes = NOTES.format(name=cfg["name"], scale=scale, heat=heat_note, heat2=heat2,
                         dem=dem_note, veg=veg_note)
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<map xmlns="http://openorienteering.org/apps/mapper/xml/v2" version="9">\n'
           f'<notes>{notes}</notes>\n{geo}\n{colors}\n'
           '<barrier version="6" required="0.6.0">\n'
           f'{symbols}\n<parts count="1" current="0">\n'
           f'<part name="Map"><objects count="{len(obj.parts)}">\n'
           + "\n".join(obj.parts) +
           '\n</objects></part>\n</parts>\n'
           f'{templates}\n<view>\n'
           '<grid color="#646464" display="0" alignment="0" additional_rotation="0" '
           'unit="1" h_spacing="500" v_spacing="500" h_offset="0" v_offset="0" '
           'snapping_enabled="true"/>\n'
           '<map_view zoom="1" position_x="0" position_y="0" '
           'overprinting_simulation_enabled="true"><map opacity="1" visible="true"/>'
           '<templates count="0"/></map_view>\n</view>\n'
           f'<print scale="{scale}" resolution="600" simulate_overprinting="true" '
           'mode="vector"><page_format paper_size="A3" orientation="landscape" '
           'h_overlap="5" v_overlap="5"><dimensions width="420" height="297"/>'
           '<page_rect left="10" top="10" width="400" height="277"/></page_format>'
           f'<print_area left="{-hw/scale*1000:.1f}" top="{-hh/scale*1000:.1f}" '
           f'width="{2*hw/scale*1000:.1f}" height="{2*hh/scale*1000:.1f}" '
           'center_area="false"/></print>\n</barrier>\n</map>\n')
    io.open(cfg["out"], "w", encoding="utf-8", newline="\n").write(xml)
    log(f"wrote {cfg['out']} ({len(xml)/1024:.0f} kB, {len(obj.parts)} objects)")


# ---------------------------------------------------------------- riding speed
# Flat-equivalent speed at a reference effort. Raw GPS speed conflates three
# things -- the terrain, the gradient, and how hard the rider was trying -- so
# fix the last two and what is left is a property of the path.
#
# With a power meter the physics is exact enough to be worth doing properly:
#
#   1. from measured power, speed and grade, solve for the path's EFFECTIVE
#      ROLLING RESISTANCE. That single number carries the surface: mud, roots,
#      sand and loose stone all show up as a higher crr_eff.
#   2. put that crr_eff back into the same model at a REFERENCE POWER (the
#      athlete's FTP by default) on zero gradient, and solve for speed.
#
# The answer is "how fast does this path let you ride, on the flat, at
# threshold" -- which is what 815-822 encode. Without a power meter, power is
# estimated from a nominal crr instead, and only the gradient is normalised
# away; heart rate then has to carry the effort control, shifted back by
# `hr_lag_s` because heart rate lags its cause by 20-30 s.
#
# It remains one rider on a handful of days. It is evidence, not a survey.
G0, RHO = 9.80665, 1.225


def power_at(v, grade, m, crr, cda):
    """Watts to hold v m/s on a slope; steady state, no drivetrain loss."""
    th = math.atan(grade)
    return v * (crr * m * G0 * math.cos(th) + 0.5 * RHO * cda * v * v
                + m * G0 * math.sin(th))


def crr_from(p, v, grade, m, cda, accel=0.0):
    """Invert the model for the rolling resistance the path must have had.

    `accel` matters: a forest ride is a chain of surges and brakes, and without
    the kinetic term every acceleration is charged to the surface instead.
    """
    th = math.atan(grade)
    return (p / v - 0.5 * RHO * cda * v * v - m * G0 * math.sin(th)
            - m * accel) / (m * G0 * math.cos(th))


def flat_speed(p, m, crr, cda):
    """Speed those watts give on the flat against that rolling resistance."""
    lo, hi = 0.0, 30.0
    for _ in range(50):
        mid = (lo + hi) / 2
        if power_at(mid, 0.0, m, crr, cda) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def _localname(tag):
    return tag.rpartition("}")[2]


def _parse_time(s):
    """GPX timestamps: ...Z, ...+02:00, with or without fractional seconds."""
    import datetime
    s = (s or "").strip()
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    if "." in s:                                  # trim fractional seconds
        head, _, tail = s.partition(".")
        keep = ""
        for ch in tail:
            if not ch.isdigit():
                keep += ch
        s = head + keep
    try:
        return datetime.datetime.fromisoformat(s)
    except ValueError:
        return None


def _haversine(a, b):
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * 6371000.0 * math.asin(min(1.0, math.sqrt(h)))


def read_gpx(path, smooth_ele=9, speed_win=2, grade_m=30.0, min_kmh=3.0, gap_s=10):
    """GPX -> the same stream dict the Strava connector returns.

    Heart rate and power come from the Garmin TrackPointExtension where the
    device wrote them. Speed and grade have to be derived, and both are noisy at
    1 Hz, so speed is taken over a centred +/-`speed_win` sample window and grade
    over a `grade_m` horizontal window on a smoothed elevation profile. Grade is
    the sensitive one: at 85 kg and 6 m/s a 1 % grade error is ~50 W, which lands
    straight in the rolling-resistance inversion. Elevation from a barometric
    device is usable; from a phone's GPS it is not.
    """
    import xml.etree.ElementTree as ET
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as ex:
        log(f"  skip {os.path.basename(path)}: not parseable XML ({ex})")
        return None
    lat, lon, ele, tim, hr, pw = [], [], [], [], [], []
    for trkpt in root.iter():
        if _localname(trkpt.tag) != "trkpt":
            continue
        try:
            la, lo = float(trkpt.get("lat")), float(trkpt.get("lon"))
        except (TypeError, ValueError):
            continue
        e = t = h = w = None
        for node in trkpt.iter():
            n = _localname(node.tag)
            if n == "ele" and node.text:
                try:
                    e = float(node.text)
                except ValueError:
                    pass
            elif n == "time" and node.text:
                t = _parse_time(node.text)
            elif n == "hr" and node.text:
                try:
                    h = int(float(node.text))
                except ValueError:
                    pass
            elif n in ("PowerInWatts", "power", "watts") and node.text:
                try:
                    w = float(node.text)
                except ValueError:
                    pass
        lat.append(la), lon.append(lo), ele.append(e), tim.append(t), hr.append(h), pw.append(w)
    if len(lat) < 10:
        log(f"  skip {os.path.basename(path)}: {len(lat)} points")
        return None
    if not any(t is not None for t in tim):
        log(f"  skip {os.path.basename(path)}: no timestamps, so no speed")
        return None

    t0 = next(t for t in tim if t is not None)
    secs = [None if t is None else (t - t0).total_seconds() for t in tim]
    # smooth the elevation profile before any gradient is taken from it
    known = [e for e in ele if e is not None]
    if known:
        fill, last = [], known[0]
        for e in ele:
            last = e if e is not None else last
            fill.append(last)
        half = smooth_ele // 2
        sm = [sum(fill[max(0, i - half):i + half + 1])
              / len(fill[max(0, i - half):i + half + 1]) for i in range(len(fill))]
    else:
        sm = [0.0] * len(lat)

    n = len(lat)
    vel, grd, mov = [0.0] * n, [0.0] * n, [False] * n
    for i in range(n):
        a, b = max(0, i - speed_win), min(n - 1, i + speed_win)
        if secs[a] is None or secs[b] is None:
            continue
        dt = secs[b] - secs[a]
        if dt <= 0 or dt > gap_s * (b - a + 1):        # a pause, not riding
            continue
        d = sum(_haversine((lat[k], lon[k]), (lat[k + 1], lon[k + 1])) for k in range(a, b))
        vel[i] = d / dt
        mov[i] = vel[i] * 3.6 >= min_kmh
        # gradient over a fixed ground distance, not a fixed sample count
        j, run = i, 0.0
        while j + 1 < n and run < grade_m:
            run += _haversine((lat[j], lon[j]), (lat[j + 1], lon[j + 1]))
            j += 1
        k, back = i, 0.0
        while k > 0 and back < grade_m:
            back += _haversine((lat[k - 1], lon[k - 1]), (lat[k], lon[k]))
            k -= 1
        if run + back > 5.0:
            grd[i] = (sm[j] - sm[k]) / (run + back) * 100.0
    return {"location": [[la, lo] for la, lo in zip(lat, lon)],
            "time": [int(s) if s is not None else 0 for s in secs],
            "altitude": sm, "velocity_smooth": vel, "grade_smooth": grd,
            "moving": mov,
            "heart_rate": hr if any(h is not None for h in hr) else None,
            "watts": pw if any(w is not None for w in pw) else None}


def load_tracks(specs, clip, frame, min_in_area=10, smooth_ele=9,
                speed_win=2, grade_m=30.0):
    """Every track in the given folders/files, keeping only those in the map.

    A rider's archive is mostly elsewhere; this is what filters it down to the
    area being mapped. Accepts .gpx and the JSON stream dicts the Strava MCP
    connector returns, mixed freely.
    """
    from shapely.geometry import Point
    paths = []
    for spec in specs:
        if os.path.isdir(spec):
            for root, _dirs, files in os.walk(spec):
                paths += [os.path.join(root, f) for f in sorted(files)
                          if os.path.splitext(f)[1].lower() in (".gpx", ".json")]
        else:
            paths += sorted(glob.glob(spec)) if any(c in spec for c in "*?") else [spec]
    log(f"{len(paths)} candidate track file(s)")
    out, skipped = [], 0
    for p in paths:
        if os.path.splitext(p)[1].lower() == ".json":
            try:
                d = json.load(io.open(p, encoding="utf-8"))
            except ValueError:
                log(f"  skip {os.path.basename(p)}: not JSON")
                continue
            if "location" not in d:
                log(f"  skip {os.path.basename(p)}: no location stream")
                continue
        else:
            d = read_gpx(p, smooth_ele=smooth_ele, speed_win=speed_win,
                         grade_m=grade_m)
            if d is None:
                continue
        inside = 0
        for la, lo in d["location"]:
            x, y = frame.fwd(lo, la)
            if clip.contains(Point(x, y)):
                inside += 1
                if inside >= min_in_area:
                    break
        if inside < min_in_area:
            skipped += 1
            continue
        out.append((os.path.basename(p), d))
        log(f"  {os.path.basename(p)}: {len(d['location'])} points, in the map"
            + ("" if d.get("watts") else ", no power")
            + ("" if d.get("heart_rate") else ", no heart rate"))
    log(f"{len(out)} track(s) cross this map, {skipped} elsewhere")
    return out


def cmd_speed(args):
    from shapely.geometry import LineString, Point, box
    from shapely.strtree import STRtree
    import statistics
    cfg = load_config(args.config)
    frame = Frame(cfg["lat"], cfg["lon"])
    hw, hh = cfg["extent_m"][0] / 2, cfg["extent_m"][1] / 2
    clip = box(-hw, -hh, hw, hh)
    for k, v in (("speed_v_ref_kmh", args.v_ref), ("speed_p_ref_w", args.p_ref),
                 ("speed_hr_lo", args.hr_lo), ("speed_hr_hi", args.hr_hi),
                 ("speed_quantile", args.quantile), ("speed_hr_lag_s", args.hr_lag),
                 ("speed_mass_kg", args.mass), ("speed_crr", args.crr),
                 ("speed_cda", args.cda)):
        cfg[k] = v
    if args.bands:
        cfg["speed_bands"] = [float(x) / args.v_ref for x in args.bands.split(",")]
    m, cda = cfg["speed_mass_kg"], cfg["speed_cda"]

    # ---- the rideable network, keyed by OSM way id
    osm = json.load(io.open(cfg["osm_json"], encoding="utf-8"))
    geoms, ids, tagged = [], [], {}
    for e in osm["elements"]:
        if e["type"] != "way":
            continue
        t = e.get("tags") or {}
        code, b, fam = classify_highway(t)
        if not code or b is None:
            continue
        pts = [frame.fwd(p["lon"], p["lat"]) for p in (e.get("geometry") or []) if p]
        if len(pts) < 2:
            continue
        g = LineString(pts)
        if not g.intersects(clip):
            continue
        geoms.append(g)
        ids.append(e["id"])
        tagged[e["id"]] = {"code": code, "band": b, "fam": fam,
                           "name": t.get("name", ""), "highway": t.get("highway", "")}
    tree = STRtree(geoms)
    log(f"network: {len(geoms)} rideable ways inside the map")

    # ---- the tracks that cross this map
    streams = load_tracks(args.tracks or args.streams or [cfg.get("tracks_dir", "")],
                          clip, frame, smooth_ele=args.ele_smooth,
                          speed_win=args.speed_win, grade_m=args.grade_m)
    if not streams:
        sys.exit("no track crosses this map; check --tracks")

    per_way = collections.defaultdict(list)
    kept = unmatched = 0
    drop = collections.Counter()
    for name, d in streams:
        loc = d["location"]
        tim = d.get("time") or list(range(len(loc)))
        vel, grd = d.get("velocity_smooth"), d.get("grade_smooth")
        hr, mov, watts = d.get("heart_rate"), d.get("moving"), d.get("watts")
        byt = {t: i for i, t in enumerate(tim)}
        n_file = 0
        for i in range(1, len(loc)):
            if mov and not mov[i]:
                continue
            v = vel[i] if vel else 0.0
            if not (args.min_kmh / 3.6 <= v <= args.max_kmh / 3.6):
                drop["speed out of range"] += 1
                continue
            if hr is not None and args.hr_lo > 0:
                # heart rate lags its cause: pair speed at t with heart rate at t+lag
                j = byt.get(tim[i] + cfg["speed_hr_lag_s"])
                if j is None or not hr[j]:
                    drop["no heart rate at t+lag"] += 1
                    continue
                if not (cfg["speed_hr_lo"] <= hr[j] <= cfg["speed_hr_hi"]):
                    drop["heart rate outside band"] += 1
                    continue
            grade = (grd[i] / 100.0) if grd else 0.0
            if watts and watts[i]:
                p_meas = float(watts[i])
                dt = max(1e-3, tim[i] - tim[i - 1])
                accel = ((v - vel[i - 1]) / dt) if vel else 0.0
                crr_eff = crr_from(p_meas, v, grade, m, cda, accel)
                if not (args.crr_min <= crr_eff <= args.crr_max):
                    drop["implausible rolling resistance"] += 1
                    continue
            else:                      # no power meter: gradient only, nominal surface
                p_meas = power_at(v, grade, m, cfg["speed_crr"], cda)
                crr_eff = cfg["speed_crr"]
            if p_meas < args.min_watts:
                drop["coasting"] += 1
                continue
            vf = flat_speed(cfg["speed_p_ref_w"], m, crr_eff, cda)
            x, y = frame.fwd(loc[i][1], loc[i][0])
            if not clip.contains(Point(x, y)):
                continue
            px, py = frame.fwd(loc[i - 1][1], loc[i - 1][0])
            head = math.degrees(math.atan2(y - py, x - px))
            pt = Point(x, y)
            best, bestd = None, args.match_m
            for k in tree.query(pt.buffer(args.match_m)):
                g = geoms[k]
                dist = g.distance(pt)
                if dist > bestd:
                    continue
                s = g.project(pt)
                a = g.interpolate(max(0.0, s - 3.0))
                b2 = g.interpolate(min(g.length, s + 3.0))
                wh = math.degrees(math.atan2(b2.y - a.y, b2.x - a.x))
                off = abs((head - wh + 180) % 360 - 180)
                if min(off, 180 - off) > args.heading_deg:   # a parallel way, not this one
                    continue
                best, bestd = k, dist
            if best is None:
                unmatched += 1
                continue
            per_way[ids[best]].append((vf * 3.6, crr_eff, name))   # speed kept for reference
            kept, n_file = kept + 1, n_file + 1
        log(f"  {name}: {n_file} samples matched"
            + ("" if watts else "  (no power meter: gradient-only normalisation)"))
    log(f"kept {kept}, unmatched {unmatched}; dropped " +
        ", ".join(f"{k} {v}" for k, v in drop.most_common()))

    # ---- aggregate per way and classify
    vref, fr = cfg["speed_v_ref_kmh"], cfg["speed_bands"]
    ways, changed = {}, 0
    for wid, rows in per_way.items():
        traces = {r[2] for r in rows}
        if len(rows) < args.min_pts or len(traces) < args.min_traces:
            drop["way below evidence threshold"] += 1
            continue
        # the path has one effective rolling resistance, so take a quantile of
        # THAT and derive a single speed from it -- a quantile of the per-sample
        # speeds would not correspond to the crr reported beside it.
        cs = sorted(r2[1] for r2 in rows)
        crr_q = cs[min(len(cs) - 1, int((1.0 - cfg["speed_quantile"]) * len(cs)))]
        kmh = flat_speed(cfg["speed_p_ref_w"], m, crr_q, cda) * 3.6
        r = kmh / vref
        b = FAST if r >= fr[0] else MED if r >= fr[1] else SLOW if r >= fr[2] else VSLOW
        old = tagged[wid]
        ways[str(wid)] = {"kmh": round(kmh, 1), "ratio": round(r, 2), "band": b,
                          "crr": round(crr_q, 4),
                          "crr_median": round(statistics.median(cs), 4),
                          "n": len(rows), "traces": len(traces),
                          "was": old["code"], "code": code_for(old["fam"], b),
                          "highway": old["highway"], "name": old["name"]}
        changed += b != old["band"]
    cfg["speeds"] = True
    cfg["speeds_json"] = args.speeds_json or cfg.get("speeds_json", "data/speeds.json")
    save_config(args.config, cfg)
    io.open(cfg["speeds_json"], "w", encoding="utf-8").write(json.dumps(
        {"v_ref_kmh": vref, "p_ref_w": cfg["speed_p_ref_w"], "bands": fr,
         "quantile": cfg["speed_quantile"],
         "hr_band": [cfg["speed_hr_lo"], cfg["speed_hr_hi"]],
         "hr_lag_s": cfg["speed_hr_lag_s"],
         "model": {"mass_kg": m, "cda": cda, "crr_nominal": cfg["speed_crr"]},
         "traces": [s[0] for s in streams], "ways": ways}, indent=1))
    log(f"{len(ways)} ways measured, {changed} differ from their OSM-tag class"
        f" -> {cfg['speeds_json']}")
    for wid, w in sorted(ways.items(), key=lambda kv: -kv[1]["kmh"]):
        flag = "  <-- changed" if w["was"] != w["code"] else ""
        log(f"  {w['was']:>5} -> {w['code']:>5}  {w['kmh']:5.1f} km/h  crr {w['crr']:.3f}  "
            f"n={w['n']:3d}/{w['traces']}  {w['highway']} {w['name']}{flag}")


# ---------------------------------------------------------------- build
def cmd_build(args):
    from shapely.geometry import LineString, Point, Polygon, box
    from shapely.ops import unary_union
    from shapely.strtree import STRtree
    cfg = load_config(args.config)
    scale = cfg["scale"]
    frame = Frame(cfg["lat"], cfg["lon"])
    hw, hh = cfg["extent_m"][0] / 2, cfg["extent_m"][1] / 2
    clip = box(-hw, -hh, hw, hh)
    colors, symbols, by_code = load_donor(cfg["donor"], scale)
    obj = Objects(by_code, 1e6 / scale)

    def cl_lines(pts):
        if len(pts) < 2:
            return []
        g = LineString(pts).intersection(clip)
        if g.is_empty:
            return []
        return [list(p.coords) for p in getattr(g, "geoms", [g])
                if isinstance(p, LineString) and len(p.coords) >= 2]

    def cl_polys(outer, inner=()):
        polys = []
        for o in outer:
            try:
                p = Polygon(o, inner if len(outer) == 1 else ())
                if not p.is_valid:
                    p = p.buffer(0)
            except Exception:
                continue
            if not p.is_empty:
                polys.append(p)
        if not polys:
            return []
        g = unary_union(polys).intersection(clip)
        out = []
        for p in getattr(g, "geoms", [g]):
            if isinstance(p, Polygon) and p.area >= 1.0:
                out.append([list(p.exterior.coords)] + [list(h.coords) for h in p.interiors])
        return out

    osm = json.load(io.open(cfg["osm_json"], encoding="utf-8"))
    ride_geoms, ride_meta, other_lines, areas, points = [], [], [], [], []
    for e in osm["elements"]:
        t = e.get("tags") or {}
        if e["type"] == "node":
            code = classify_node(t)
            if code:
                xy = frame.fwd(e["lon"], e["lat"])
                if clip.contains(Point(xy)):
                    points.append((code, xy, t))
            continue
        if e["type"] == "relation":
            code, kind = classify_way(t)
            if not (code and kind == "area"):
                continue
            o, i = [], []
            for mem in e.get("members", []):
                if mem.get("type") != "way" or not mem.get("geometry"):
                    continue
                ring = [frame.fwd(p["lon"], p["lat"]) for p in mem["geometry"] if p]
                if len(ring) >= 3:
                    (o if mem.get("role") != "inner" else i).append(ring)
            for rings in cl_polys(o, i):
                areas.append((code, rings))
            continue
        pts = [frame.fwd(p["lon"], p["lat"]) for p in (e.get("geometry") or []) if p]
        if len(pts) < 2:
            continue
        hcode, hband, hfam = classify_highway(t)
        if hcode:
            for seg in cl_lines(pts):
                ride_geoms.append(LineString(seg))
                ride_meta.append({"code": hcode, "band": hband, "fam": hfam,
                                  "tags": t, "id": e["id"]})
            continue
        code, kind = classify_way(t)
        if not code:
            continue
        closed = len(pts) > 3 and pts[0] == pts[-1]
        if kind == "area" and closed:
            for rings in cl_polys([pts]):
                areas.append((code, rings))
        else:
            for seg in cl_lines(pts):
                other_lines.append((code, seg))
    log(f"osm: {len(ride_geoms)} rideable lines, {len(other_lines)} other lines, "
        f"{len(areas)} areas, {len(points)} points")

    measured = {}
    # ---- measured riding speed (optional): a measurement outranks a tag guess
    if cfg.get("speeds") and os.path.exists(cfg.get("speeds_json", "")):
        sd = json.load(io.open(cfg["speeds_json"], encoding="utf-8"))
        for meta in ride_meta:
            w = sd["ways"].get(str(meta.get("id")))
            if not w or meta["band"] is None:
                continue
            meta["measured"] = w["kmh"]
            if w["band"] != meta["band"]:
                measured[meta["id"]] = (meta["code"], w["code"], w["kmh"], w["n"])
                meta["band"], meta["code"] = w["band"], code_for(meta["fam"], w["band"])
        log(f"speed: {len(sd['ways'])} ways measured at {sd['p_ref_w']:.0f} W / "
            f"{sd['v_ref_kmh']:.0f} km/h reference, {len(measured)} reclassified")

    # ---- heatmap merge (optional)
    new_lines, upgraded, matched_full, confirmed, heat_lines = [], [], 0, 0, []
    if cfg.get("heatmap") and os.path.exists(cfg["network_json"]):
        shot = Screenshot(cfg)
        net = json.load(io.open(cfg["network_json"], encoding="utf-8"))
        for l in net["lines"]:
            pts = [frame.fwd(*shot.to_lonlat(x, y)) for y, x in l["yx"]]
            g = LineString(pts).intersection(clip)
            for part in (getattr(g, "geoms", [g]) if not g.is_empty else []):
                if isinstance(part, LineString) and part.length >= cfg["min_new_m"]:
                    heat_lines.append({"geom": part, "heat": l["heat"]})
        log(f"heatmap: {len(heat_lines)} lines, "
            f"{sum(h['geom'].length for h in heat_lines)/1000:.1f} km")

        tree = STRtree(ride_geoms) if ride_geoms else None

        def sample(line):
            n = max(2, int(line.length / cfg["step_m"]) + 1)
            return [line.interpolate(i / (n - 1), normalized=True) for i in range(n)]

        for h in heat_lines:
            pts = sample(h["geom"])
            flags = []
            for p in pts:
                idx = tree.query(p.buffer(cfg["match_m"])) if tree is not None else []
                flags.append(any(ride_geoms[i].distance(p) <= cfg["match_m"] for i in idx))
            if sum(flags) / len(flags) >= cfg["heat_line_matched"]:
                matched_full += 1
                continue
            run = []
            for f, p in list(zip(flags, pts)) + [(True, None)]:
                if not f:
                    run.append((p.x, p.y))
                    continue
                if len(run) > 1 and LineString(run).length >= cfg["min_new_m"]:
                    new_lines.append({"pts": run, "heat": h["heat"]})
                run = []

        heat_union = unary_union([h["geom"] for h in heat_lines]) if heat_lines else None
        for i, g in enumerate(ride_geoms):
            meta = ride_meta[i]
            if heat_union is None or meta["band"] is None:
                continue
            pts = sample(g)
            cov = sum(1 for p in pts if heat_union.distance(p) <= cfg["match_m"]) / len(pts)
            if cov < cfg["osm_confirmed"]:
                continue
            confirmed += 1
            if meta.get("measured") is not None and cfg.get("speed_overrides_heat", True):
                continue                      # measured: do not also guess from usage
            if cfg["upgrade_confirmed"] and meta["band"] > FAST:
                old, b = meta["code"], meta["band"]
                meta["band"] = b - 1
                meta["code"] = code_for(meta["fam"], b - 1)
                upgraded.append((old, meta["code"], meta["tags"].get("highway"),
                                 round(g.length), round(cov, 2)))
        log(f"merge: {matched_full}/{len(heat_lines)} heat lines already in OSM, "
            f"{len(new_lines)} new fragments, {confirmed} OSM ways confirmed, "
            f"{len(upgraded)} upgraded one band")

    # ---- emit: vegetation and contours first, they belong under everything else
    n_veg = 0
    if cfg.get("vegetation") and os.path.exists(cfg["vegetation_json"]):
        vd = json.load(io.open(cfg["vegetation_json"], encoding="utf-8"))
        for a in vd["areas"]:
            obj.area(a["code"], a["rings"])
            n_veg += 1
        log(f"vegetation: {n_veg} areas from {vd['source']}")

    n_contour = 0
    if cfg.get("contours") and os.path.exists(cfg["contours_json"]):
        cd = json.load(io.open(cfg["contours_json"], encoding="utf-8"))
        every = cd.get("index_every", 5) * cd["interval"]
        for cl in cd["lines"]:
            code = "102" if abs(cl["z"] / every - round(cl["z"] / every)) < 1e-6 else "101"
            for seg in cl_lines(cl["pts"]):
                if LineString(seg).length >= cfg["contour_min_len_m"]:
                    obj.line(code, seg)
                    n_contour += 1
        log(f"contours: {n_contour} objects from {cd['source']} "
            f"({cd['interval']:g} m interval)")

    for code, rings in areas:
        obj.area(code, rings)
    for code, seg in other_lines:
        obj.line(code, seg)
    for i, g in enumerate(ride_geoms):
        obj.line(ride_meta[i]["code"], list(g.coords))
    n_track = 0
    for nl in new_lines:
        code = "815" if nl["heat"] >= cfg["heat_track"] else "816"
        n_track += code == "815"
        obj.line(code, nl["pts"])
    for code, pt, t in points:
        obj.point(code, pt)
        if code == "603" and t.get("ele"):
            m = re.match(r"\s*([\d.]+)", t["ele"])
            if m:
                obj.text("603.1", (pt[0] + 12, pt[1] + 30), str(int(float(m.group(1)))))
    if cfg.get("north_lines"):
        obj.area("601.1", [[(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)]])

    write_omap(cfg, colors, symbols, obj, frame)

    rep = [f"{cfg['name']} -- ISMTBOM 2022 1:{scale}", "", "Objects per symbol:"]
    if n_veg:
        vd = json.load(io.open(cfg["vegetation_json"], encoding="utf-8"))
        rep.insert(1, f"Vegetation: {n_veg} areas from {vd['source']} -- REMOTELY "
                      f"SENSED, 10 m resolution; 406 means evergreen/thicket canopy, "
                      f"which is a proxy for reduced visibility, not a survey")
    if cfg.get("imagery"):
        sc = ", ".join(f"{x['season']} {x['date']}" for x in cfg["imagery"]["scenes"])
        rep.insert(1, f"Imagery merged: {sc}")
    if n_contour:
        cd = json.load(io.open(cfg["contours_json"], encoding="utf-8"))
        rep.insert(1, f"Contours: {cd['interval']:g} m interval from {cd['source']}, "
                      f"DEM smoothed with sigma {cd['smooth_m']:g} m -- INDICATIVE, "
                      f"a 30 m surface model cannot resolve 5 m contours in forest")
    for code, n in sorted(obj.count.items()):
        rep.append(f"  {code:<9} {n:>5}")
    if obj.converted:
        rep.append("")
        rep.append("Non-ISMTBOM symbols converted to their ISMTBOM equivalent:")
        for k, n in sorted(obj.converted.items()):
            rep.append(f"  {k:<22} {n:>5}")
    if obj.missing:
        rep.append("Codes with no ISMTBOM equivalent (dropped): " + str(dict(obj.missing)))
    if measured:
        sd = json.load(io.open(cfg["speeds_json"], encoding="utf-8"))             if cfg.get("speeds") and os.path.exists(cfg.get("speeds_json", "")) else {}
        rep += ["", f"Riding speed MEASURED from {len(sd.get('traces', []))} GPS "
                    f"track(s): flat-equivalent speed at {sd.get('p_ref_w', 0):.0f} W "
                    f"(the athlete's FTP), samples filtered to heart rate "
                    f"{sd.get('hr_band', ['?', '?'])[0]}-{sd.get('hr_band', ['?', '?'])[1]} "
                    f"bpm shifted back {sd.get('hr_lag_s', 0)} s. "
                    f"{sd.get('v_ref_kmh', 0):.0f} km/h counts as a fast track.",
                "ONE RIDER, a handful of days -- evidence, not a survey. Where a way was "
                "measured the heatmap upgrade is suppressed.",
                "", "Reclassified by measured speed (old -> new, km/h, samples):"]
        rep += [f"  {o} -> {n}  {kmh:.1f} km/h  n={cnt}"
                for (o, n, kmh, cnt) in measured.values()]
    rep += ["", f"Heat lines: {len(heat_lines)}  already mapped: {matched_full}  "
                f"new: {len(new_lines)} ({n_track} x 815, {len(new_lines)-n_track} x 816)",
            f"OSM ways confirmed by heat: {confirmed}, upgraded one band: {len(upgraded)}",
            "", "Upgraded (old -> new, highway, length m, coverage):"]
    rep += ["  " + " ".join(str(x) for x in r) for r in upgraded[:500]]
    txt = "\n".join(rep) + "\n"
    io.open(os.path.splitext(cfg["out"])[0] + "_report.txt", "w", encoding="utf-8").write(txt)
    print(txt)

    if cfg.get("heatmap") and heat_lines:
        draw_merge_overlay(cfg, ride_geoms, ride_meta, new_lines, frame)


def draw_merge_overlay(cfg, ride_geoms, ride_meta, new_lines, frame):
    from PIL import Image, ImageDraw
    hm = cfg["heatmap"]
    shot = Screenshot(cfg)
    im = Image.open(hm["path"]).convert("RGB")
    d = ImageDraw.Draw(im)

    def px(p):
        return shot.from_lonlat(*frame.inv(p[0], p[1]))

    for i, g in enumerate(ride_geoms):
        code = ride_meta[i]["code"]
        col = (255, 140, 0) if code in PATH else (200, 0, 0)
        if code.startswith("502"):
            col = (0, 0, 0)
        d.line([px(c) for c in g.coords], fill=col, width=2)
    for nl in new_lines:
        d.line([px(p) for p in nl["pts"]], fill=(0, 220, 255), width=4)
    out = os.path.splitext(cfg["out"])[0] + "_merge_check.png"
    im.resize((im.width // 2, im.height // 2)).save(out)
    log("wrote " + out + " -- LOOK AT IT: the OSM lines must sit on the heat corridors")


def cmd_render(args):
    import subprocess
    cfg = load_config(args.config)
    here = os.path.dirname(os.path.abspath(__file__))
    out = os.path.splitext(cfg["out"])[0] + "_preview.png"
    subprocess.run([sys.executable, os.path.join(here, "render_omap.py"),
                    cfg["out"], out, str(args.ppmm)], check=True)


# ---------------------------------------------------------------- cli
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init")
    p.add_argument("--config", default="project.json")
    p.add_argument("--lat", type=float, required=True)
    p.add_argument("--lon", type=float, required=True)
    p.add_argument("--heatmap", help="Strava global-heatmap screenshot (optional)")
    p.add_argument("--scalebar-m", type=float, default=100.0,
                   help="the distance printed on the screenshot's scale bar")
    p.add_argument("--m-per-px", type=float, help="override the scale-bar measurement")
    p.add_argument("--extent", help="WIDTHxHEIGHT in metres, when there is no screenshot")
    p.add_argument("--scale", type=int, default=15000)
    p.add_argument("--donor", required=True, help="ISMTBOM 2022 .omap to take colours "
                                                  "and symbols from, at the target scale")
    p.add_argument("--out", required=True)
    p.add_argument("--osm-json", default="data/osm.json")
    p.add_argument("--network-json", default="data/heatmap_network.json")
    p.add_argument("--contours-json", default="data/contours.json")
    p.add_argument("--satellite-png", default="data/satellite.png")
    p.add_argument("--s2-npz", default="data/s2_stack.npz")
    p.add_argument("--vegetation-json", default="data/vegetation.json")
    p.add_argument("--tracks-dir", help="folder of GPS tracks (.gpx) to take "
                                       "riding speed from")
    p.add_argument("--name")
    p.set_defaults(func=cmd_init)

    for name, fn in (("fetch", cmd_fetch), ("heatmap", cmd_heatmap), ("build", cmd_build)):
        p = sub.add_parser(name)
        p.add_argument("--config", default="project.json")
        p.set_defaults(func=fn)

    p = sub.add_parser("contours")
    p.add_argument("--config", default="project.json")
    p.add_argument("--interval", type=float, default=5.0, help="contour interval, m")
    p.add_argument("--index-every", type=int, default=5, help="index contour every Nth")
    p.add_argument("--spacing", type=float, default=10.0, help="DEM resample grid, m")
    p.add_argument("--smooth-m", type=float, default=35.0,
                   help="Gaussian smoothing of the DEM, m; a 30 m DSM needs a lot")
    p.add_argument("--rdp-m", type=float, default=2.5)
    p.add_argument("--pad", type=float, default=150.0)
    p.set_defaults(func=cmd_contours)

    p = sub.add_parser("imagery")
    p.add_argument("--config", default="project.json")
    p.add_argument("--res", type=float, default=5.0, help="output grid, m/px")
    p.add_argument("--pad", type=float, default=100.0)
    p.add_argument("--per-season", type=int, default=2, help="scenes per season to merge")
    p.add_argument("--max-cloud", type=float, default=10.0)
    p.add_argument("--on-start", default="2024-06-01")
    p.add_argument("--on-end", default="2025-09-15")
    p.add_argument("--off-start", default="2024-11-15")
    p.add_argument("--off-end", default="2025-03-31")
    p.set_defaults(func=cmd_imagery)

    p = sub.add_parser("vegetation")
    p.add_argument("--config", default="project.json")
    p.add_argument("--evergreen-delta", type=float, default=0.22,
                   help="leaf-on minus leaf-off NDVI below which tree cover is evergreen")
    p.add_argument("--evergreen-ndvi", type=float, default=0.40,
                   help="and its leaf-off NDVI must still be above this")
    p.add_argument("--min-area-m2", type=float, default=4000.0)
    p.add_argument("--simplify-m", type=float, default=8.0)
    p.add_argument("--subtract-osm", type=int, default=1)
    p.set_defaults(func=cmd_vegetation)

    p = sub.add_parser("speed")
    p.add_argument("--config", default="project.json")
    p.add_argument("--tracks", nargs="+",
                   help="folder(s) of GPS tracks, or single files/globs. .gpx and "
                        "the JSON stream dicts the Strava MCP connector returns are "
                        "both accepted; tracks outside the map are skipped")
    p.add_argument("--streams", nargs="+", help="deprecated alias for --tracks")
    p.add_argument("--ele-smooth", type=int, default=15,
                   help="GPX only: elevation moving-average window, samples")
    p.add_argument("--speed-win", type=int, default=3,
                   help="GPX only: half-width of the speed window, samples")
    p.add_argument("--grade-m", type=float, default=60.0,
                   help="GPX only: ground distance the gradient is taken over")
    p.add_argument("--speeds-json")
    p.add_argument("--v-ref", type=float, default=30.0,
                   help="flat-equivalent km/h at the reference effort that counts "
                        "as a good, fast track")
    p.add_argument("--p-ref", type=float, default=228.0,
                   help="reference power, W -- the athlete's FTP")
    p.add_argument("--hr-lo", type=int, default=160, help="0 disables the heart-rate filter")
    p.add_argument("--hr-hi", type=int, default=180)
    p.add_argument("--hr-lag", type=int, default=25,
                   help="seconds heart rate lags the effort that caused it")
    p.add_argument("--bands", help="band thresholds in km/h, fast,medium,slow "
                                   "(e.g. 20,10,5): at or above the first is a fast "
                                   "track, below the last is very slow")
    p.add_argument("--quantile", type=float, default=0.75,
                   help="quantile of the matched samples: what the path permits, "
                        "not what the rider averaged")
    p.add_argument("--mass", type=float, default=85.0, help="rider + bike, kg")
    p.add_argument("--crr", type=float, default=0.012,
                   help="nominal rolling resistance, used only without a power meter")
    p.add_argument("--cda", type=float, default=0.42)
    p.add_argument("--crr-min", type=float, default=0.003)
    p.add_argument("--crr-max", type=float, default=0.15)
    p.add_argument("--min-watts", type=float, default=30.0)
    p.add_argument("--min-kmh", type=float, default=3.0)
    p.add_argument("--max-kmh", type=float, default=50.0)
    p.add_argument("--match-m", type=float, default=12.0)
    p.add_argument("--heading-deg", type=float, default=40.0)
    p.add_argument("--min-pts", type=int, default=12)
    p.add_argument("--min-traces", type=int, default=1)
    p.set_defaults(func=cmd_speed)

    p = sub.add_parser("render")
    p.add_argument("--config", default="project.json")
    p.add_argument("--ppmm", type=float, default=6.0)
    p.set_defaults(func=cmd_render)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
