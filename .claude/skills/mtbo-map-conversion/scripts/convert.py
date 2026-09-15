# -*- coding: utf-8 -*-
"""ISOM 2000 -> ISMTBOM 2022 converter (OpenOrienteering Mapper .omap).

TEMPLATE - adapt, do not run blind. OBJ_MAP below assumes an ISOM **2000**
source (106 Earth bank, 206 Boulder, 526 Building). ISMTBOM 2022 shares
ISOM 2017-2 numbering, so for a 2017-2 source most of OBJ_MAP is an identity
map and applying this one unchanged would corrupt the conversion - check the
source codes first (see ../reference/mapping.md). Set the three paths below, then review
SPEC (the ISMTBOM 2022 symbol set) and OBJ_MAP (how source objects are
reclassified). OBJ_MAP encodes decisions the user must make first: the
rideability ladder, the vegetation collapse, and what to drop.

Symbol geometry comes from the official Mapper set, which is the PRE-2022
ISMTBOM; this script renumbers, reorders and recolours it to ISMTBOM 2022,
and additionally appends the ISOM 2000 symbols ISMTBOM 2022 does not define.

Download the base set with:
  curl -sSL -o ISMTBOM_15000.omap "https://raw.githubusercontent.com/\\
OpenOrienteering/mapper/master/symbol%20sets/15000/ISMTBOM_15000.omap"

Licence: that file is part of OpenOrienteering Mapper (GPLv3) and its geometry
ends up in the output. Flag this before any commercial or redistributed use.

See ../reference/mapping.md for the full symbol table.
"""
import io
import re

SRC = "CHANGE-ME/source-isom-map.omap"      # the foot-orienteering map to convert
SET = "CHANGE-ME/ISMTBOM_15000.omap"        # official Mapper set, downloaded above
DST = "CHANGE-ME/output-mtbo-15000.omap"

SRC_SCALE, DST_SCALE = 10000, 15000         # source map scale -> MTBO base scale

K = SRC_SCALE / float(DST_SCALE)

src = io.open(SRC, encoding="utf-8").read()
sset = io.open(SET, encoding="utf-8").read()


def section(text, tag):
    m = re.search(r"<%s\b[^>]*>.*?</%s>" % (tag, tag), text, re.S)
    return m.group(0), m.start(), m.end()


# ============================================================== 1. COLOUR TABLE
# The official set is kept, with three ISMTBOM 2022 corrections:
#   * "Black 70%" -> "Black 60%"      (4.4 rock / 4.7 man-made are black 60%)
#   * OO Orange   -> ISMTBOM orange   (60% magenta + 100% yellow, 4.2)
#   * "Black 25%" inserted after Black 30%   (522 Canopy)
BLACK25_AT = 12
colors_block = section(sset, "colors")[0]
entries = re.split(r"(?=<color )", colors_block[colors_block.index(">") + 1:
                                                colors_block.rindex("</colors>")])
entries = [e for e in entries if e.strip().startswith("<color")]

entries[3] = re.sub(r'name="[^"]*"', 'name="Black 60%"', entries[3])
entries[3] = re.sub(r'\bk="[^"]*"', 'k="0.6"', entries[3])
entries[3] = re.sub(r'factor="[^"]*"', 'factor="0.6"', entries[3])
entries[3] = re.sub(r'<rgb [^/]*/>', '<rgb method="cmyk" r="0.4" g="0.4" b="0.4"/>', entries[3])

entries[7] = re.sub(r'name="[^"]*"', 'name="Orange"', entries[7])
entries[7] = re.sub(r'\bc="[^"]*" m="[^"]*" y="[^"]*" k="[^"]*"',
                    'c="0" m="0.6" y="1" k="0"', entries[7])
entries[7] = re.sub(r'<spotcolors[^>]*>.*?</spotcolors>|<spotcolors[^>]*/>',
                    '<spotcolors/>', entries[7], flags=re.S)
entries[7] = re.sub(r'<cmyk [^/]*/>', '<cmyk method="custom"/>', entries[7])
entries[7] = re.sub(r'<rgb [^/]*/>', '<rgb method="cmyk" r="1" g="0.4" b="0"/>', entries[7])

black25 = ('<color priority="%d" name="Black 25%%" c="0" m="0" y="0" k="0.25" opacity="1">'
           '<spotcolors knockout="true"><component factor="0.25" spotcolor="1"/>'
           '</spotcolors><cmyk method="custom"/>'
           '<rgb method="cmyk" r="0.75" g="0.75" b="0.75"/></color>\n' % BLACK25_AT)
entries.insert(BLACK25_AT, black25)
for i, e in enumerate(entries):
    e = re.sub(r'priority="\d+"', 'priority="%d"' % i, e, count=1)
    # Screened colours reference their base spot colour by priority index, so the
    # insertion has to be applied to those references too (the new Black 25% entry
    # already refers to Black at 1, which is below the insertion point).
    if i != BLACK25_AT:
        e = re.sub(r'spotcolor="(\d+)"',
                   lambda m: 'spotcolor="%d"' % (int(m.group(1)) + 1
                                                 if int(m.group(1)) >= BLACK25_AT
                                                 else int(m.group(1))), e)
    entries[i] = e
new_colors = '<colors count="%d">\n%s</colors>' % (len(entries), "".join(entries))


def shift_color(xml):
    """Colour indices >= BLACK25_AT move down one because Black 25% was inserted."""
    def rep(m):
        v = int(m.group(2))
        return '%s="%d"' % (m.group(1), v + 1 if v >= BLACK25_AT else v)
    return re.sub(r'(\w*color)="(\d+)"', rep, xml)


PURPLE, BLACK, LPURPLE, BLACK60, BROWN50 = 0, 1, 2, 3, 4
BLK_UNDER, BROWN, ORANGE, BLUE = 5, 6, 7, 9
BLACK25, GREENYELLOW, GREEN, YELLOW50 = 12, 13, 18, 23

# ================================================== 2. SOURCE SYMBOL DEFINITIONS
def top_level_symbols(symbols_block):
    """Split a <symbols> block into its top-level <symbol> entries.

    Only top-level symbols carry an id="..."; the nested <symbol> elements used
    by mid-symbols, patterns and point elements do not. Splitting on the first
    </symbol> would truncate any symbol that contains those, so anchor on the
    id-bearing openers and take everything up to the next one instead.
    """
    opens = [m for m in re.finditer(r'<symbol [^>]*\bid="\d+"[^>]*>', symbols_block)]
    ends = [m.start() for m in opens[1:]] + [symbols_block.rindex("</symbols>")]
    out = {}
    for m, end in zip(opens, ends):
        a = dict(re.findall(r'(\w+)="([^"]*)"', m.group(0)))
        body = symbols_block[m.end():end].rstrip()
        assert body.endswith("</symbol>"), a
        out[a["code"]] = (a["type"], body[:-len("</symbol>")])
    return out


set_syms = top_level_symbols(section(sset, "symbols")[0])


def line(color, w, dash=None, gap=None):
    a = ('color="%d" line_width="%d" minimum_length="0" join_style="1" cap_style="0" '
         'start_offset="0" end_offset="0" ' % (color, w))
    if dash:
        a += 'dashed="true" '
    a += ('segment_length="4000" end_length="0" show_at_least_one_symbol="true" '
          'minimum_mid_symbol_count="0" minimum_mid_symbol_count_when_closed="0" '
          'dash_length="%d" break_length="%d" dashes_in_group="1" '
          'in_group_break_length="500" mid_symbols_per_spot="1" mid_symbol_distance="0"'
          % (dash or 4000, gap or 1000))
    return '<line_symbol %s/>' % a


def dots(color, radius, spacing):
    return ('<pattern type="2" angle="0.785398" line_spacing="%d" line_offset="0" '
            'offset_along_line="0" point_distance="%d" rotatable="true">'
            '<symbol type="1" code=""><point_symbol rotatable="true" inner_radius="%d" '
            'inner_color="%d" outer_width="0" outer_color="-1" elements="0"/></symbol>'
            '</pattern>' % (spacing, spacing, radius, color))


AUTHORED = {
    "823": ("1", "The end of the track or path, it is no longer possible to continue in "
                 "its direction. Footprint: 16.5 m. Colour: black.",
            '<point_symbol rotatable="true" inner_radius="0" inner_color="-1" '
            'outer_width="0" outer_color="-1" elements="1"><element>'
            '<symbol type="2" code="">%s</symbol><object type="1">'
            '<coords count="2">-550 0;550 0;</coords></object></element></point_symbol>'
            % line(BLACK, 250)),
    "532": ("2", "Steps or stairways which present a challenge to riding. An easily "
                 "rideable or indistinct stairway should be drawn as a path. Minimum "
                 "length: 3 steps (1.2 mm). Minimum width: 0.4 mm (IM). Colour: black.",
            '<line_symbol color="-1" line_width="0" minimum_length="0" join_style="1" '
            'cap_style="0" start_offset="0" end_offset="0" segment_length="4000" '
            'end_length="0" show_at_least_one_symbol="true" minimum_mid_symbol_count="0" '
            'minimum_mid_symbol_count_when_closed="0" dash_length="4000" '
            'break_length="1000" dashes_in_group="1" in_group_break_length="500" '
            'mid_symbols_per_spot="1" mid_symbol_distance="0"><borders>'
            '<border color="%d" width="120" shift="200" dashed="false" '
            'dash_length="4000" break_length="1000"/></borders></line_symbol>' % BLACK),
    "501.4": ("4", "An area with gravel or other unpaved surface. Minimum width: 0.9 mm. "
                   "Minimum area: 2 mm2. Colour: brown 50%, black.",
              '<area_symbol inner_color="%d" min_area="2000" patterns="0"/>' % BROWN50),
    "824": ("4", "An area of open land that is permitted to ride, when off-track riding "
                 "is otherwise forbidden. The permitted area should have obvious borders "
                 "or be marked in the terrain. Minimum width: 0.9 mm. Minimum area: "
                 "2 mm2. Colour: orange.",
            '<area_symbol inner_color="%d" min_area="2000" patterns="0"/>' % ORANGE),
    "825.1": ("4", "An area of terrain with a dense track network or little ground "
                   "vegetation where riding everywhere is allowed. Predominant "
                   "tracks/paths going through this area shall be shown to aid "
                   "navigation. The symbol is orientated to north. Minimum width: 3 mm. "
                   "Minimum area: 10 mm2. Colour: black.",
              '<area_symbol inner_color="-1" min_area="10000" patterns="1">%s</area_symbol>'
              % dots(BLACK, 175, 900)),
    "825.2": ("4", "Used where symbol Forested area, permitted to ride (825.1) is too "
                   "small. Minimum width: 2 mm. Minimum area: 4 mm2, maximum 10 mm2. "
                   "Colour: black.",
              '<area_symbol inner_color="-1" min_area="4000" patterns="1">%s</area_symbol>'
              % dots(BLACK, 175, 600)),
    "826": ("4", "Heath, moorland, felled or newly planted areas or other generally open "
                 "land with rough ground vegetation that is permitted to ride, when "
                 "off-track riding is otherwise forbidden. The symbol is orientated to "
                 "north. Minimum width: 1.5 mm. Minimum area: 4 mm2. Colour: orange.",
            '<area_symbol inner_color="-1" min_area="4000" patterns="1">%s</area_symbol>'
            % dots(ORANGE, 125, 400)),
    "522": ("4", "A building construction (with a roof), normally supported by pillars, "
                 "poles or walls. Minimum width: 1 mm. Minimum area: 2 mm2. "
                 "Colour: black 25%.",
            '<area_symbol inner_color="%d" min_area="2000" patterns="0"/>' % BLACK25),
    "522.1": ("1", "A pillar is an upright shaft or structure used as a building support. "
                   "Pillars smaller than 1 m x 1 m are generally not represented. "
                   "Colour: black 60%.",
              '<point_symbol inner_radius="250" inner_color="%d" outer_width="0" '
              'outer_color="-1" elements="0"/>' % BLACK60),
    "841": ("1", "One-way compulsory. APPROXIMATED - verify against the specification "
                 "before use. Colour: upper purple.",
            '<point_symbol rotatable="true" inner_radius="0" inner_color="-1" '
            'outer_width="0" outer_color="-1" elements="2">'
            '<element><symbol type="2" code="">%s</symbol><object type="1">'
            '<coords count="2">0 900;0 -900;</coords></object></element>'
            '<element><symbol type="2" code="">%s</symbol><object type="1">'
            '<coords count="3">-450 -350;0 -900;450 -350;</coords></object></element>'
            '</point_symbol>' % (line(PURPLE, 200), line(PURPLE, 200))),
}
for _c, _n, _d, _g, _m in [
    ("827", "fast riding", None, None, "Minimum width: 0.9 mm."),
    ("828", "medium riding", 3000, 500, "Minimum length (isolated): 2 dashes (6.5 mm)."),
    ("829", "slow riding", 1500, 400, "Minimum length (isolated): 2 dashes (3.4 mm)."),
    ("830", "very slow riding", 800, 300, "Minimum length (isolated): 2 dashes (1.9 mm)."),
]:
    AUTHORED[_c] = ("2",
                    "A forest ride or a prominent trace (forestry extraction track, sandy "
                    "track, ski track) through the terrain which does not have a distinct "
                    "rideable path along it, %s. %s Colour: orange." % (_n, _m),
                    line(ORANGE, 900, _d, _g))

# ISMTBOM 2022 codes drawn in black 60%
BLACK60_CODES = {"201", "201.0.1", "201.1", "201.2", "204", "206", "210", "509", "511",
                 "513", "515", "516", "518", "519", "522.1", "524", "525", "527", "528",
                 "529", "530", "531", "603", "603.1"}
# 521 Building is black at 1:15 000 (an outline + black 60% applies only to 1:5 000/1:7 500)
BLACK_CODES = {"521", "521.1", "501.1"}

# ==================================================== 3. THE ISMTBOM 2022 SET
# (new code, new name, source code in the official set or None = authored, overrides)
SPEC = [
    # ---- 4.1 Paths, tracks and roads -------------------------------------
    ("502", "Paved road", "502", {}),
    ("502.1", "Wide unpaved road, fast riding", "503", {}),
    ("501.1", "Step or edge of paved area", "529.1", {}),
    ("815", "Track: fast riding", "831", {"line_width": 600}),
    ("816", "Path: fast riding", "832", {"line_width": 400}),
    ("817", "Track: medium riding", "833", {"line_width": 600, "dash_length": 3000,
                                            "break_length": 500}),
    ("818", "Path: medium riding", "834", {"line_width": 400, "dash_length": 3000,
                                           "break_length": 500}),
    ("819", "Track: slow riding", "835", {"line_width": 600, "dash_length": 1500,
                                          "break_length": 400}),
    ("820", "Path: slow riding", "836", {"line_width": 400, "dash_length": 1500,
                                         "break_length": 400}),
    ("821", "Track: very slow riding", "837", {"line_width": 600, "dash_length": 800,
                                               "break_length": 300}),
    ("822", "Path: very slow riding", "838", {"line_width": 400, "dash_length": 600,
                                              "break_length": 300}),
    ("823", "Track end point", None, {}),
    ("532", "Stairs", None, {}),
    # ---- 4.2 Other features where riding is permitted ---------------------
    ("501", "Paved area", "529", {"min_area": 2000}),
    ("501.2", "Paved area, with bounding line", "529.2", {}),
    ("501.4", "Unpaved area, fast riding", None, {}),
    ("824", "Open land, permitted to ride", None, {}),
    ("825.1", "Forested area, permitted to ride", None, {}),
    ("825.2", "Minor forested area, permitted to ride", None, {}),
    ("826", "Rough open land, permitted to ride", None, {}),
    ("827", "Narrow ride, permitted to ride: fast riding", None, {}),
    ("828", "Narrow ride, permitted to ride: medium riding", None, {}),
    ("829", "Narrow ride, permitted to ride: slow riding", None, {}),
    ("830", "Narrow ride, permitted to ride: very slow riding", None, {}),
    ("213", "Open sandy ground", "211", {"min_area": 16000}),
    # ---- 4.3 Landforms ----------------------------------------------------
    ("101", "Contour", "101", {}),
    ("101.1", "Slope line", "104", {}),
    ("102", "Index contour", "102", {}),
    ("102.1", "Contour value", "105", {}),
    ("104", "Earth bank", "106", {}),
    ("104.0.1", "Earth bank, minimum size", "106.0.1", {}),
    ("104.1", "Earth bank, very high", "106.1", {}),
    ("104.1.1", "Earth bank, very high, minimum size", "106.1.1", {}),
    ("104.2", "Earth bank, tag line", "106.2", {}),
    ("105", "Earth wall", "107", {}),
    ("107", "Erosion gully", "109", {}),
    ("108", "Small erosion gully", "110", {}),
    ("109", "Small knoll", "112", {}),
    # ---- 4.4 Rock features (black 60%) ------------------------------------
    ("201", "Impassable cliff", "201", {}),
    ("201.0.1", "Impassable cliff, minimum size", "201.0.1", {}),
    ("201.1", "Impassable cliff, no tags", "201.1", {}),
    ("201.2", "Impassable cliff, tag line", "201.2", {}),
    ("204", "Boulder", "206", {}),
    ("206", "Gigantic boulder or rock pillar", "202", {}),
    ("210", "Stony ground", "210.1", {}),
    ("214", "Bare rock", "212", {"min_area": 4000}),
    # ---- 4.5 Water and marshes --------------------------------------------
    ("301", "Uncrossable body of water", "301", {"min_area": 1000}),
    ("301.1", "Uncrossable body of water, bank line", "301.1", {}),
    ("301.2", "Uncrossable body of water, with bank line", "301.2", {}),
    ("304", "Crossable watercourse", "305", {}),
    ("305", "Small crossable watercourse", "306", {}),
    ("306", "Minor/seasonal water channel", "307", {}),
    ("307", "Uncrossable marsh", "309", {"min_area": 2000}),
    ("307.1", "Uncrossable marsh, border line", "309.1", {}),
    ("307.2", "Uncrossable marsh, with border line", "309.2", {}),
    ("308", "Marsh", "310", {}),
    ("308.1", "Marsh, minimum size", "310.1", {}),
    ("313", "Prominent water feature", "314", {}),
    # ---- 4.6 Vegetation ----------------------------------------------------
    ("401", "Open land", "401", {"min_area": 2000}),
    ("402", "Open land with scattered trees", "402", {"min_area": 4000}),
    ("403", "Rough open land", "403", {"min_area": 2000}),
    ("404", "Rough open land with scattered trees", "404", {"min_area": 6000}),
    ("405", "Forest", "405", {"min_area": 2000}),
    ("406", "Forest: reduced rideability and visibility", "406", {"min_area": 2000}),
    ("407", "Vegetation: reduced off-track rideability, good visibility", "407", {}),
    ("410", "Impassable vegetation", "410", {}),
    ("410.1", "Impassable vegetation, line", "410.1", {}),
    ("413", "Orchard", "412", {"min_area": 4000}),
    ("414", "Vineyard or similar", "413", {"min_area": 4000}),
    ("417", "Prominent large tree", "419", {}),
    ("418", "Prominent bush or tree", "420", {}),
    ("419", "Prominent vegetation feature", "418", {}),
    # ---- 4.7 Man-made features ---------------------------------------------
    ("509", "Railway", "515", {}),
    ("510", "Power line, cableway or skilift", "516", {}),
    ("511", "Major power line", "517", {}),
    ("512", "Bridge / tunnel", "518", {}),
    ("512.1", "Bridge / tunnel, minimum size", "518.1", {}),
    ("513", "Passable wall", "519", {}),
    ("515", "Impassable wall", "521", {}),
    ("516", "Passable fence or railing", "522", {}),
    ("518", "Impassable fence or railing", "524", {}),
    ("519", "Crossing point", "525", {}),
    ("520", "Area that shall not be entered", "528",
     {"__area__": '<area_symbol inner_color="%d" min_area="2000" patterns="0"/>'
                  % GREENYELLOW}),
    ("520.1", "Area that shall not be entered, bounding line", "528.1", {}),
    ("521", "Building", "526", {"min_area": 1000}),
    ("521.1", "Building, minimum size", "526.1", {}),
    ("522", "Canopy", None, {}),
    ("522.1", "Pillar", None, {}),
    ("524", "High tower", "535", {}),
    ("525", "Small tower", "536", {}),
    ("527", "Fodder rack", "538", {}),
    ("528", "Passable line feature", "533", {}),
    ("529", "Uncrossable line feature", "534", {}),
    ("530", "Prominent man-made feature - ring", "539", {}),
    ("531", "Prominent man-made feature - x", "540", {}),
    # ---- 4.8 Technical ------------------------------------------------------
    ("601", "Magnetic north line", "601.2", {"line_width": 120}),
    ("601.1", "North lines pattern", "601.3", {}),
    ("602", "Registration mark", "602", {}),
    ("603", "Spot height, dot", "603.0", {}),
    ("603.1", "Spot height, text", "603.1", {}),
    # ---- 4.9 Course planning -------------------------------------------------
    ("701", "Start", "701", {}),
    ("702", "Map issue point", "701", {}),
    ("703", "Control point", "702", {}),
    ("703.1", "Control point with focus point", "840", {}),
    ("704", "Control number with control code", "703", {}),
    ("705", "Course line", "704", {}),
    ("706", "Finish", "706", {}),
    ("707", "Marked route", "705", {}),
    ("708", "Out-of-bounds boundary", "707", {}),
    ("709", "Out-of-bounds area", "709", {}),
    ("709.1", "Out-of-bounds area, solid boundary", "709.1", {}),
    ("709.2", "Out-of-bounds area, dashed boundary", "709.2", {}),
    ("710", "Crossing point", "708", {}),
    ("712", "First aid post", "712", {}),
    ("713", "Refreshment point", "713", {}),
    ("715", "Continuing point after map exchange", "702", {}),
    ("716", "Forbidden route", "711", {}),
    ("716.1", "Forbidden route, alternative", "711.1", {}),
    ("717", "Obstacle across track, path or road", "843", {}),
    ("718", "Forbidden to pass", "844", {}),
    ("719", "Dangerous section", "843", {}),
    ("841", "One-way compulsory", None, {}),
    # ---- helpers -------------------------------------------------------------
    ("799", "Simple Orienteering Course", "799", {}),
    ("999", "OpenOrienteering Logo", "999", {}),
]

# codes carried over from ISMTBOM_15000.omap purely as approximations
APPROXIMATE = {"702", "715", "719", "841"}


def build(code, name, src_code, ov):
    if src_code is None:
        typ, desc, body = AUTHORED[code]
        return typ, '<description>%s</description>%s' % (desc, body)
    typ, body = set_syms[src_code]
    body = shift_color(body)
    if "__area__" in ov:
        body = re.sub(r'<area_symbol.*?</area_symbol>|<area_symbol[^>]*/>',
                      ov["__area__"], body, flags=re.S)
    if code in BLACK60_CODES:
        body = re.sub(r'(\w*color)="1"', r'\g<1>="%d"' % BLACK60, body)
    if code in BLACK_CODES:
        # the pre-2022 set drew these in black 70%; ISMTBOM 2022 has them black
        body = re.sub(r'(\w*color)="%d"' % BLACK60, r'\g<1>="%d"' % BLACK, body)
    head = re.search(r'<(?:line|point|area|text|combined)_symbol[^>]*>', body)
    if head:
        tag, fixed = head.group(0), head.group(0)
        for k, v in ov.items():
            if k.startswith("__"):
                continue
            pat = r'(?<![\w-])' + re.escape(k) + r'="[^"]*"'
            if re.search(pat, fixed):
                fixed = re.sub(pat, '%s="%s"' % (k, v), fixed)
            else:
                fixed = fixed.rstrip("/>").rstrip() + ' %s="%s"%s' % (
                    k, v, "/>" if tag.endswith("/>") else ">")
        body = body.replace(tag, fixed, 1)
    if code in APPROXIMATE:
        body = re.sub(r"<description>.*?</description>", "", body, flags=re.S)
        body = ('<description>ISMTBOM 2022 symbol %s. APPROXIMATED from the pre-2022 '
                'OpenOrienteering set - verify the drawing against the specification '
                'before use.</description>' % code) + body
    return typ, body


# --- source-map text symbol, appended so the one text object survives ----------
text_typ, text_body = "8", re.search(
    r'<symbol type="8" id="\d+" code="980\.0\.2"[^>]*>(.*?)</symbol>',
    section(src, "symbols")[0], re.S).group(1)
text_body = re.sub(r'<text color="\d+"', '<text color="%d"' % BROWN, text_body)
text_body = re.sub(r'\bsize="(\d+)"',
                   lambda m: 'size="%d"' % round(int(m.group(1)) * K), text_body)
SPEC.append(("980.0.2", "Text", "__TEXT__", {}))

# ============ 3b. ISOM 2000 symbols that ISMTBOM 2022 does not define ==========
# Kept available in the palette so nothing is missing while drawing. Geometry is
# taken from the ISOM source map (drawn at 1:10 000 / 150%) and rescaled to
# 1:15 000. Where the ISOM code would collide with a different ISMTBOM 2022
# feature, the code is suffixed "-ISOM"; every added symbol is named "... (ISOM)".
ISOM_COVERED = {
    "101", "102", "104", "105", "106", "106.0.1", "106.1", "106.1.1", "106.2", "107",
    "109", "110", "112", "201", "201.0.1", "201.1", "201.2", "202", "206", "210.1",
    "211", "212", "301", "301.1", "301.2", "305", "306", "307", "309", "309.1",
    "309.2", "310", "310.1", "314", "401", "402", "403", "404", "405", "406", "407",
    "410", "410.1", "412", "413", "418", "419", "420", "502", "503", "515", "516",
    "517", "518", "518.1", "519", "521", "522", "524", "525", "526", "526.1", "528",
    "528.1", "529", "529.1", "529.2", "533", "534", "535", "536", "538", "539", "540",
    "601", "601.1", "601.2", "601.3", "602", "603.0", "603.1", "701", "702", "703",
    "704", "705", "706", "707", "708", "709", "709.1", "709.2", "711", "712", "713",
    "799", "999", "980.0.2",
}
# ISOM source colour index -> ISMTBOM 2022 colour index
ISOM_CMAP = {0: 0, 1: 1, 2: 4, 3: 5, 4: 8, 5: 9, 6: 10, 7: 6, 8: 7, 9: 11, 10: 13,
             11: 14, 12: 15, 13: 17, 14: 18, 15: 19, 16: 20, 17: 21, 18: 22, 19: 23,
             20: 24, 21: 25}
LEN_ATTRS = {"line_width", "minimum_length", "start_offset", "end_offset",
             "segment_length", "end_length", "dash_length", "break_length",
             "in_group_break_length", "mid_symbol_distance", "inner_radius",
             "outer_width", "width", "shift", "line_spacing", "line_offset",
             "offset_along_line", "point_distance", "size"}


def isom_rescale(xml):
    def attr(m):
        n, v = m.group(1), int(m.group(2))
        if n in LEN_ATTRS:
            return '%s="%d"' % (n, round(v * K))
        if n == "min_area":
            return '%s="%d"' % (n, round(v * K * K))
        return m.group(0)
    xml = re.sub(r'(\w+)="(-?\d+)"', attr, xml)

    def coords(cm):
        pts = []
        for tok in cm.group(2).split(";"):
            tok = tok.strip()
            if not tok:
                continue
            p = tok.split()
            p[0], p[1] = str(int(round(int(p[0]) * K))), str(int(round(int(p[1]) * K)))
            pts.append(" ".join(p))
        return "%s%s</coords>" % (cm.group(1), ";".join(pts) + ";" if pts else "")

    return re.sub(r'(<coords count="\d+">)(.*?)</coords>', coords, xml, flags=re.S)


def isom_recolor(xml):
    def rep(m):
        v = int(m.group(2))
        return '%s="%d"' % (m.group(1), ISOM_CMAP.get(v, v) if v >= 0 else v)
    return re.sub(r'(\w*color)="(-?\d+)"', rep, xml)


isom_syms = top_level_symbols(section(src, "symbols")[0])
# names must come from the top-level openers only; nested sub-symbols carry
# code="" and names like "Mid symbol" and would otherwise pollute the list
isom_names = {}
for _m in re.finditer(r'<symbol [^>]*\bid="\d+"[^>]*>', section(src, "symbols")[0]):
    _a = dict(re.findall(r'(\w+)="([^"]*)"', _m.group(0)))
    isom_names[_a["code"]] = _a.get("name", _a["code"])
taken = {c for c, _, _, _ in SPEC}
ISOM_EXTRA = []
for code in [c for c in isom_names if c not in ISOM_COVERED]:
    typ, body = isom_syms[code]
    # combined symbols are fine as long as every part is private (self-contained);
    # a part referencing another symbol by id would need remapping
    assert not re.search(r'<part symbol="\d+"', body), \
        "combined ISOM symbol %s references external parts" % code
    new_code = code + "-ISOM" if code in taken else code
    ISOM_EXTRA.append((new_code, "%s (ISOM)" % isom_names[code], typ,
                       isom_recolor(isom_rescale(body))))
def code_sort_key(code):
    """Numeric sort for symbol codes: 101 < 101.1 < 102 < 104.0.1 < 104.1 < 105,
    with a '-ISOM' variant sorting immediately after its base number."""
    return "".join(p.zfill(6) if p.isdigit() else "~" + p
                   for p in re.split(r"[.\-]", code))


built = []
for code, name, src_code, ov in SPEC:
    if src_code == "__TEXT__":
        typ, body = text_typ, text_body
    else:
        typ, body = build(code, name, src_code, ov)
    built.append((code, name, typ, body))
built.extend(ISOM_EXTRA)
built.sort(key=lambda r: code_sort_key(r[0]))

code_to_id, out_syms = {}, []
for i, (code, name, typ, body) in enumerate(built):
    code_to_id[code] = i
    out_syms.append('<symbol type="%s" id="%d" code="%s" name="%s">%s</symbol>'
                    % (typ, i, code, name.replace("&", "&amp;"), body))
new_symbols = ('<symbols count="%d" id="ISMTBOM2022">\n%s\n</symbols>'
               % (len(out_syms), "\n".join(out_syms)))

# combined symbols must point at the new ids of their components
for combo, members in (("301.2", ("301", "301.1")), ("307.2", ("307", "307.1")),
                       ("501.2", ("501", "501.1"))):
    if combo not in code_to_id:
        continue
    blk = re.search(r'<symbol type="16" id="%d".*?</symbol>' % code_to_id[combo],
                    new_symbols, re.S).group(0)
    new_symbols = new_symbols.replace(blk, re.sub(
        r'<combined_symbol parts="\d+">.*?</combined_symbol>',
        '<combined_symbol parts="2">%s</combined_symbol>'
        % "".join('<part symbol="%d"/>' % code_to_id[m] for m in members),
        blk, flags=re.S))

# ==================================================== 4. OBJECTS -> 2022 CODES
OBJ_MAP = {
    "101": "101", "102": "102", "106": "104", "107": "105", "109": "107", "110": "108",
    "103": None, "115": None, "116": None, "532": None,     # MTBO generalisation
    "201": "201",
    "401": "401", "403": "403", "404": "404", "415": "401",
    "406": "406", "408": "406",                              # green levels collapsed
    "407": "407", "409": "407",
    "410": "410",
    "414": None, "416": None,                                # ISMTBOM 2022 section 4.6
    "418": "419", "419": "417",
    "503": "502",                                            # paved road
    "504": "817", "505": "819", "506": "818", "507": "820", "508": "822",
    "509": "830",                                            # ride, off-track forbidden
    "524": "518", "526": "521", "527": "520", "529": "501",
    "536": "525", "540": "531", "980.0.2": "980.0.2",
}
src_by_id = {m.group(1): m.group(2) for m in re.finditer(
    r'<symbol type="\d+" id="(\d+)" code="([^"]*)"', section(src, "symbols")[0])}

stats, dropped = {}, [0]


def migrate(m):
    code = src_by_id.get(m.group(1))
    target = OBJ_MAP.get(code, "__unmapped__")
    if target is None or target not in code_to_id:
        stats[(code, "DROPPED")] = stats.get((code, "DROPPED"), 0) + 1
        dropped[0] += 1
        return ""
    stats[(code, target)] = stats.get((code, target), 0) + 1
    body = m.group(0).replace('symbol="%s"' % m.group(1),
                              'symbol="%d"' % code_to_id[target], 1)

    def coords(cm):
        pts = []
        for tok in cm.group(2).split(";"):
            tok = tok.strip()
            if not tok:
                continue
            p = tok.split()
            p[0], p[1] = str(int(round(int(p[0]) * K))), str(int(round(int(p[1]) * K)))
            pts.append(" ".join(p))
        return "%s%s</coords>" % (cm.group(1), ";".join(pts) + ";" if pts else "")

    body = re.sub(r'(<coords count="\d+">)(.*?)</coords>', coords, body, flags=re.S)
    return re.sub(r'(<coord )x="(-?\d+)" y="(-?\d+)"',
                  lambda c: '%sx="%d" y="%d"' % (c.group(1), round(int(c.group(2)) * K),
                                                 round(int(c.group(3)) * K)), body)


new_parts = re.sub(r'<object type="\d+" symbol="(\d+)".*?</object>\n?',
                   migrate, section(src, "parts")[0], flags=re.S)
new_parts = re.sub(r'<objects count="\d+">(.*?)</objects>',
                   lambda m: '<objects count="%d">%s</objects>'
                             % (len(re.findall(r"<object type=", m.group(1))), m.group(1)),
                   new_parts, flags=re.S)

# ======================================================== 5. WRITE THE MAP FILE
out = src
for tag, repl in (("colors", new_colors), ("symbols", new_symbols), ("parts", new_parts)):
    _, a, b = section(out, tag)
    out = out[:a] + repl + out[b:]
# the georeferencing tag can carry further attributes, so match it as a regex
out = re.sub(r'(<georeferencing[^>]*?scale=")\d+(")', r'\g<1>%d\g<2>' % DST_SCALE, out)
out = out.replace('<print scale="%d"' % SRC_SCALE, '<print scale="%d"' % DST_SCALE)
io.open(DST, "w", encoding="utf-8", newline="\n").write(out)

print("wrote %s (%d bytes)" % (DST, len(out)))
print("colours: %d   symbols: %d   objects dropped: %d"
      % (len(entries), len(out_syms), dropped[0]))
for (old, new), n in sorted(stats.items(), key=lambda kv: -kv[1]):
    print("  %-9s -> %-9s %4d" % (old, new, n))
