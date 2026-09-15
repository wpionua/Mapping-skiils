---
name: mtbo-map-conversion
description: Convert a foot-orienteering map (ISOM 2000 or ISOM 2017-2 forest, or ISSprOM 2019 sprint) into a mountain bike orienteering map (ISMTBOM 2022) in OpenOrienteering Mapper .omap/.xmap format - renumbering symbols, rebuilding the colour table, reclassifying the path network by riding speed, and rescaling to 1:15 000 (forest) or 1:5 000 (sprint). Use when asked to convert a run/foot/ISOM/ISSprOM map to MTBO/ISMTBOM, build an MTBO symbol set, or change an orienteering map's scale or specification.
---

# ISOM / ISSprOM -> ISMTBOM (foot orienteering map -> MTBO map)

## Scope: OpenOrienteering Mapper files only

This skill works **only** on [OpenOrienteering Mapper](https://github.com/OpenOrienteering/mapper)
files — `.omap`, or its verbose twin `.xmap`. Both are plain UTF-8 XML, and the whole
conversion is done by rewriting that XML with a script; do not try to drive Mapper's
GUI.

It does **not** read OCAD `.ocd` files, Purple Pen, or PDF/image maps. If the source
is one of those, say so and stop: the user must open it in Mapper and save as `.omap`
first. (A map that *originated* in OCAD is fine once exported — it arrives with
`<symbols id="OCD">` and OCAD-style codes like `501.2`, which is a source-spec
question, not a format one.)

## Step 0 — ask which MTBO format is wanted

**Ask this first, before recon**, unless the user already said. It decides the target
scale, the symbol enlargement and which script to start from:

| | **Forest** | **Sprint** |
|---|---|---|
| Target scale | **1:15 000** | **1:5 000** |
| Symbol sizes | spec values as-is (100 %) | **150 %** of the 1:15 000 values |
| Usual source | ISOM 2000 / 2017-2 | ISSprOM 2019 |
| Contour interval | 5 m (10 m hilly) | 2.5 m allowed |
| North lines | 1000 m spacing | 500 m spacing |
| Start from | `scripts/convert.py` | `scripts/convert_sprint.py` |

ISMTBOM 2022 §3.1 gives both: 1:15 000 is the base scale, and 1:5 000 is the base
scale for MTBO sprint in urban areas. §3.3 is the enlargement rule — symbols at
1:10 000 **or larger** are enlarged to 150 %, so at 1:5 000 the factor is **1.5, not
3**. Getting this wrong is the single easiest way to produce a useless map.

Offer the two as an AskUserQuestion. If the source turns out not to match the chosen
format (a sprint map for a forest conversion, say), say so and re-confirm — the
source spec drives the symbol mapping, the answer here only drives the target.

## The one thing that makes this hard

ISMTBOM 2022 shares **ISOM 2017-2's** numbering but not **ISOM 2000's**, so the same
code means different things depending on the source vintage — 104 is a slope line in
ISOM 2000 and an earth bank in ISOM 2017-2 and ISMTBOM. Establish the source spec
first (Step 1); everything else follows from it. Either way a conversion is a
*symbol set replacement plus an object remap*, not an edit.

And rideability — the entire point of an MTBO map — **is not present in the source
data**. ISOM records a path's width and distinctness; ISMTBOM records how fast you
can ride it. Any mapping between them is a guess a surveyor must later correct.
Say so plainly; never present the ladder as finished work.

## Step 1 — recon before proposing anything

```bash
python -c "
import io,re,collections
d=io.open(SRC,encoding='utf-8').read()
print(re.search(r'<georeferencing[^>]*>',d).group(0))      # source scale
print(re.search(r'<symbols count=\"\d+\" id=\"[^\"]*\"',d).group(0))
by_id={m.group(1):m.group(2) for m in re.finditer(r'<symbol [^>]*\bid=\"(\d+)\" code=\"([^\"]*)\"',d)}
used=collections.Counter(re.findall(r'<object type=\"\d+\" symbol=\"(\d+)\"',d))
for i,n in used.most_common(): print(by_id[i], n)
"
```

Only the **used** symbols matter for the object remap; the rest is palette. Note the
source scale — symbol dimensions are stored in 1/1000 mm **at the map's scale**, so a
1:10 000 map holds ISOM's 1:15 000 values enlarged 150 %.

**Identify the source specification before anything else, and do not assume.**
Check `id="…"` on `<symbols>` *and* verify against actual codes:

| Source | Tell-tale codes |
|---|---|
| ISOM 2000 | 106 Earth bank, 109 Erosion gully, 206 Boulder, 526 Building, 529 Paved area |
| ISOM 2017-2 | 104 Earth bank, 107 Erosion gully, 204 Boulder, 521 Building, 501 Paved area |
| ISSprOM 2019 | 529.0.x, 526.1, 521.1.1, 506.1.x |
| pre-2022 ISMTBOM | 831-838 |

This matters more than it looks: **ISMTBOM 2022 shares ISOM 2017-2's numbering**, so
an ISOM 2017-2 source needs almost no renumbering, while an ISOM 2000 source needs
the full table. Applying the ISOM 2000 table to a 2017-2 map silently turns Earth
banks into slope lines and Boulders into rocky pits. See `reference/mapping.md`.

Report what the file actually is before proposing anything — a file named like a
forest map may well be a sprint map, and a set tagged `ISOM2000` really is ISOM 2000.

## Step 2 — get four decisions from the user

These change the output materially and cannot be inferred. Ask them together
(AskUserQuestion), with a recommendation, before writing any file.

1. **Off-track riding permitted or forbidden?** Forbidden means you need the orange
   "permitted to ride" group (824, 825.1, 825.2, 826, 827-830) to mark where riding
   *is* allowed, and Narrow ride (ISOM 2000: 509; ISOM 2017-2: 508) becomes one of
   827-830. Permitted means linear 401/403 for rides, and symbol 407 becomes
   legitimate.
2. **Rideability ladder.** Forest: ISOM 2000 503-509, or ISOM 2017-2 502-508 — the
   vintages are shifted by one, so pick the right table. Sprint: ISSprOM 529.0.3-6
   (paved, by width), 506.1.x, 507, 508. Offer a conservative/surface-based ladder,
   a pessimistic one, and an "all fast, flag for survey" honest placeholder. Ladders
   in `reference/mapping.md`.
3. **Vegetation collapse.** ISMTBOM 2022 has one green level (406) plus optional 407,
   so 406/407/408/409 must merge — *unless* the user wants a lossless conversion, in
   which case 408/409 are carried over on their own symbols instead.
4. **Features with no ISMTBOM equivalent** — form line, small depression, pit,
   cultivated land, settlement, grave; in sprint also passable water and the
   title/legend/frame layout. Delete (MTBO generalisation) or carry over.

If the user leaves the destructive options unticked, they want a **lossless**
conversion: drop nothing, and carry every unmatched symbol across. Say so back to
them rather than dropping anything anyway.

## Step 3 — build it

Start from the official OpenOrienteering set and update it, rather than authoring
120 symbols by hand:

```
https://raw.githubusercontent.com/OpenOrienteering/mapper/master/symbol%20sets/15000/ISMTBOM_15000.omap
```

**That file is the PRE-2022 ISMTBOM** — ISOM numbering plus 831-838 rideability codes.
Mapper has not shipped an ISMTBOM 2022 set ([issue #1107]). Use it for geometry, then
renumber and recolour to 2022. Full table in `reference/mapping.md`.

Both scripts **replace**: they build the ISMTBOM colour table and symbol set from
`ISMTBOM_15000.omap` and splice them in over the source's, so the output contains
ISMTBOM 2022 symbols and nothing else. That is almost always what is wanted — a
converted map should not still be half-ISOM. `scripts/convert.py` and
`scripts/convert_sprint.py` differ only in the scale factors, the `OBJ_MAP`, and
whether non-map parts are kept.

If the user explicitly asks for a **lossless** conversion instead, keep the source's
colour table and symbols, insert only the four colours ISMTBOM adds (Black 60 %,
Black 25 %, Brown 50 %, Orange), and append the ISMTBOM set *after* the source
symbols with source ids preserved — then untouched objects and `<part symbol="N"/>`
references need no rewriting at all. Suffix the source codes that collide. Be aware
this leaves two symbol sets in one file; confirm that is really what they want.

Structure of an `.omap`: `<map>` > `<notes>`, `<georeferencing>`, `<colors>`,
`<barrier>` > `<symbols>`, `<parts>`, `<templates>`, `<view>`, `<print>`. Splice
`<colors>`, `<symbols>` and `<parts>` and keep everything else from the source.
Remember all parts, not just the first — sprint maps often carry Map / Map key /
Design.

## Traps — every one of these was hit for real

**Parsing `<symbols>`.** Only top-level symbols carry `id="…"`. Mid-symbols, pattern
symbols and point elements are nested `<symbol>` tags without an id. A non-greedy
`<symbol …>.*?</symbol>` therefore **truncates** any symbol containing them and
silently produces malformed XML. Anchor on the id-bearing openers and take everything
up to the next one.

**Colour knockout.** Mapper only accepts `knockout="true"` on a colour that has a spot
composition. An empty `<spotcolors knockout="true"/>` gives
`Could not set knockout property of color 'X'`. Define opaque whites as a *zero-factor*
component of the colour they mask: `<component factor="0" spotcolor="14"/>`.

**Inserting a colour.** Screened colours reference their base spot **by priority
index**, in `spotcolor="N"` inside the colour table. Inserting a colour shifts those
too — miss it and you get `Spot color 17 not found while processing 13 (…)`. Shift
both the `*color="N"` attributes in symbols *and* the `spotcolor="N"` attributes in
the colour table.

**Splitting the colour table.** `"<colors count=\"39\">".startswith("<color")` is
**true**. Filter on `"<color "` with the trailing space, or slice the header off
first — otherwise the header becomes a phantom colour and every index shifts by one.

**`color="-900"` is not a bug.** It is Mapper's registration-black sentinel. Allow it
when range-checking colour references.

**Colliding codes.** Whenever two symbol sets coexist in one file they will reuse the
same number for different features (ISSprOM 524 Impassable fence vs ISMTBOM 524 High
tower; ISOM 108 Small earth wall vs ISMTBOM 108 Small erosion gully). Let the ISMTBOM
symbol keep the plain code and suffix the carried-over one (`524-ISSprOM`,
`108-ISOM`), with the source spec in the name. Check for duplicate codes in
validation — Mapper will load them, but the map becomes ambiguous to edit.

**Two different scale factors.** Coordinates scale by `source_scale / target_scale`
(1:10 000 -> 1:15 000 is x 2/3; 1:4 000 -> 1:5 000 is x 0.8), and so do symbols
carried over from the source. ISMTBOM symbols taken from the 1:15 000 set scale by
the **enlargement factor** instead — x1 at 1:15 000, x1.5 at 1:5 000 — never by the
scale ratio. Keep the two factors as separate constants.

**Rescaling itself.** All length attributes scale linearly;
`min_area` scales by the **square**. Length attributes:
`line_width minimum_length start_offset end_offset segment_length end_length
dash_length break_length in_group_break_length mid_symbol_distance inner_radius
outer_width width shift line_spacing line_offset offset_along_line point_distance size`.
Do **not** scale `angle`, `factor`, `count`, `elements`, `patterns`, ids or colours.
Prefer the spec's own value over a rescaled one where you know it.

**Everything referencing a symbol does so by id, not code.** Reordering or renumbering
symbols means rewriting `<object symbol="N">` and `<part symbol="N"/>` in combined
symbols. Combined symbols with `<part private="true">` are self-contained and safe.

**Two colours depend on the target scale.** 521 Building is solid black at 1:15 000
but **black 60 % fill + black outline** at 1:5 000 / 1:7 500; 522 Canopy gains a
black 60 % outline at those scales. Mapper areas have no border property, so an
outlined area must be a combined symbol (fill + outline). Check `reference/mapping.md`
before assuming a colour is scale-independent.

**ISMTBOM 2022 defines no text or layout symbols.** Title, legend, map frame and
logos therefore *cannot* be converted to an MTBO symbol. On a pure-MTBO conversion
they have to be dropped (drop the whole layout part), or kept on neutral 980.x text
helpers. Ask; do not silently keep ISSprOM/ISOM layout symbols in a set that is
supposed to be pure. The same is true of ISOM form lines and of ISMTBOM 2022 §4.6's
cultivation/vegetation boundaries — there is no target, so dropping is the answer.

**`<georeferencing>` carries more than `scale`.** A real map has
`auxiliary_scale_factor`, `declination`, `grivation`, `<ref_point>`, `<projected_crs>`.
A literal `.replace('<georeferencing scale="4000">', …)` silently does nothing.
Use `re.sub(r'(<georeferencing[^>]*?scale=")\d+(")', …)` and **verify the scale
actually changed** in the output.

**Mapper 0.9.x has no headless export.** Passing an output path just opens the GUI.
You cannot render a preview — validate structurally and say explicitly that you have
not seen the map drawn.

**This shell mangles backslashes in heredocs.** Write Python helper files with the
Write tool and use forward slashes in Windows paths; `\b`, `\f` etc. inside a
bash heredoc can land in the file as literal control characters that are invisible
in `Read` output and break regexes silently.

## Validate before reporting

```
XML parses (xml.etree)
colour priorities contiguous 0..n-1
every spotcolor="N" resolves to a colour that has a <namedcolor>
no knockout colour lacking a composition
symbol ids contiguous 0..n-1, codes unique (suffix the collisions)
every *color="N" is -1, -900, or in range
every <object symbol="N"> and <part symbol="N"/> in range and pointing at the intended code
object/symbol type compatibility: object type 0 -> point symbol, 4 -> text, 1 -> line/area/combined
object count per part matches the actual objects, for every part
ground extent unchanged: extent_mm x new_scale == original extent_mm x old_scale
```

## Reporting

State the object counts per mapping and what was dropped and why. Flag:

- the rideability ladder is inferred and needs a field survey;
- any symbol you approximated rather than took from a spec drawing (put the warning
  in the symbol's `<description>` too, so it is visible in Mapper);
- **licence** — OpenOrienteering Mapper is GPLv3 and `symbol sets/` carries no
  separate licence, so geometry taken from it lands in the output file. Harmless for
  a map used privately; flag it before anything commercial or redistributed.

## Files

- `reference/mapping.md` — how to tell the ISOM vintages apart, the full
  ISOM 2000 -> ISMTBOM 2022 table, the ISSprOM 2019 table, the scale-dependent
  colours, the pre-2022 set's codes, and the rideability ladders for each vintage.
- `scripts/convert.py` — **forest**, 1:15 000. Replaces the symbol set and colour
  table outright, and appends the ISOM 2000 symbols ISMTBOM 2022 does not define.
- `scripts/convert_sprint.py` — **sprint**, 1:5 000, ISSprOM 2019 source. Same
  replace architecture, plus the ×1.5 symbol enlargement (`KSET`), the ISSprOM
  `OBJ_MAP`, and `KEEP_PARTS` to drop the layout parts. Output is pure ISMTBOM 2022.

[issue #1107]: https://github.com/OpenOrienteering/mapper/issues/1107
