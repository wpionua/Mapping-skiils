---
name: mtbo-base-map
description: Build a base MTBO map (ISMTBOM 2022, 1:15 000) for an area from open data - OpenStreetMap for the path network and features, Copernicus DEM for 5 m contours, several dates of Sentinel-2 plus ESA WorldCover for vegetation, and optionally a Strava global-heatmap screenshot to confirm and extend the rides. The rider's own GPS tracks (Strava MCP activity streams) can replace the inferred riding-speed classes with measured ones: flat-equivalent speed at a reference power, solved through a cycling power model. Produces an OpenOrienteering Mapper .omap restricted to ISMTBOM 2022 symbols. Use when asked to make an MTBO map for a region, digitise a heatmap into a map, build a base/draft map from OSM, add contours, derive vegetation from satellite imagery, or classify paths by measured riding speed from Strava rides, power or heart-rate data.
---

# OSM (+ Strava heatmap) -> ISMTBOM 2022 base map

This builds a **draft base map** for field work: the geometry is real, the
rideability classes are inferred, and nothing has been surveyed. Say that plainly
every time; never present the output as a competition map.

For converting an *existing* foot-orienteering map to MTBO, use the
`mtbo-map-conversion` skill instead. This skill starts from open data.

## Step 0 - ask the user, before anything else

Ask both of these in one `AskUserQuestion`, and say the heatmap is optional:

1. **Area.** A Strava global-heatmap permalink is the easiest way to give it -
   `https://www.strava.com/maps/global-heatmap?...#15.02/49.8993/23.9866` -
   the fragment is `zoom/lat/lon`. Otherwise: centre lat/lon plus the extent in
   metres (at 1:15 000, A4 landscape ~ 2800 x 1900 m, A3 ~ 4000 x 2800 m).
2. **Heatmap screenshot** (skippable). A PNG of the heatmap view, taken with the
   **scale bar visible** and **no 3D tilt**, plus the same permalink. With it, the
   path network gets Strava usage data merged in; without it, the map is OSM only.
   If the user skips it, do not push - OSM path coverage is often excellent.

Do **not** trust the zoom in the permalink for scale. Measure the screenshot's own
scale bar (`init` does it automatically); on this project's data the permalink said
z15.02 while the picture was really ~z16, a factor-of-two error in ground scale.

Also settle, if the user has not said:

* **contours** - yes/no and interval (default 5 m, index every 25 m);
* **vegetation** - yes/no. It needs one summer and one winter satellite pass and
  gives 406 / 401 / 308 areas; without it the forest is plain white.
* **own GPS tracks** - has the user ridden the area, and is the Strava MCP
  connector available? Their rides turn the riding-speed classes from a tag guess
  into a measurement (the `speed` step). Ask what speed counts as a good, fast
  track - that one number anchors the whole 815-822 ladder.
* the **donor symbol set**: an ISMTBOM 2022 `.omap` at the target scale to take
  the colour table and symbols from. Mapper ships no ISMTBOM 2022 set
  ([issue #1107]), so this is usually a set produced by `mtbo-map-conversion`.
  `load_donor()` refuses a set at the wrong scale rather than silently rescaling.

## The pipeline

```bash
cd <project dir>
S=".claude/skills/mtbo-base-map/scripts/mtbo_base.py"

python $S init --lat 49.8993 --lon 23.9866 \
    --heatmap data/heatmap.png --scalebar-m 100 \
    --donor "ISMTBOM2022_15000.omap" --out "MTBO_area_15000.omap" --name "Area"
# no screenshot: --extent 3900x1900   (metres, instead of --heatmap)

python $S fetch        # Overpass -> data/osm.json          (network)
python $S heatmap      # screenshot -> data/heatmap_network.json + overlay  (skip if none)
python $S contours     # Copernicus GLO-30 -> data/contours.json            (network)
python $S imagery      # Sentinel-2, several dates -> data/satellite.png + s2_stack.npz
python $S vegetation   # WorldCover + seasonal NDVI -> data/vegetation.json
python $S speed        # GPS tracks -> data/speeds.json     (measured riding speed)
python $S build        # -> the .omap, _report.txt, _merge_check.png
python $S render       # -> _preview.png   (Mapper 0.9.x has no headless export)
```

Every step stores its state in `project.json`; steps are independently re-runnable,
and `build` picks up whatever exists. Tuning parameters (thresholds, merge
distances) live in `project.json` too - edit and re-run rather than editing code.

**Look at the two review images before reporting.** `..._merge_check.png` draws
the OSM network back over the heatmap screenshot: the lines must sit on the heat
corridors: if they are offset or rotated, the scale bar or the centre is wrong.
`..._preview.png` is a rough raster of the finished map. For vegetation, draw the
polygons over `data/satellite.png` and check the 406 patches land on visibly darker,
denser canopy.

## Only ISMTBOM 2022 symbols

`SPEC_CODES` in the script is the symbol list of **ISMTBOM 2022, Revision 4
(January 2025)**. `filter_symbol_set()` throws away every donor symbol the spec
does not define (typically ~60 of 185: the ISOM leftovers a converted set carries),
renumbers the survivors and fixes the combined symbols' `<part symbol="N"/>`
references. Mapper implementation details of a spec symbol are kept - `301.2`
(area + bank line), `601.1` (the north-line pattern), `603.1` (the spot height's
text), `X.0.1` (minimum-size point versions).

Objects that would have landed on a non-spec symbol are **converted**, not dropped:
`ISOM_TO_ISMTBOM` holds the equivalences (Well 312 -> 313 Prominent water feature,
Settlement 527.1 -> 520 Area that shall not be entered, Cultivated land 415 ->
401 Open land, ...). The report lists every conversion and its count. Anything with
no equivalent is dropped and reported - check that list, it is where a mapping
mistake shows up.

## OSM -> symbol, and the rideability guess

`reference/osm-mapping.md` has the full table. The shape of it:

| OSM | ISMTBOM |
|---|---|
| `highway` road, paved or unstated | 502 Paved road |
| `highway=track` / unpaved road | 815 / 817 / 819 / 821 by `tracktype`, `surface`, `smoothness` |
| `highway=path\|cycleway\|footway\|bridleway` | 816 / 818 / 820 / 822, same ladder; `width>=1.8` moves it to the track family |
| `highway=steps` | 532 |
| water, marsh, vegetation, buildings, fences, towers | 301/304/305/306/308, 401/403/406/413, 521, 513/516, 524/525 |
| `natural=wood`, `landuse=forest` | *nothing* - forest is the white background |
| `landuse=residential` and friends | 520 (there is no ISMTBOM settlement symbol) |

The speed band comes from `tracktype` first, then `surface`, then a `smoothness`
penalty; sand and mud are forced to at least "slow". **This is a guess.** ISOM/OSM
record what a path is made of; ISMTBOM records how fast you ride it.

With a heatmap, `build` does three things:

1. a heat line lying on an OSM way for >= 65 % of its length **is** that way and is
   discarded (no double lines);
2. an OSM way carrying heat over >= 55 % of its length is **confirmed ridden** and
   moves one speed band faster (819 -> 817 ...), capped at "fast". Every upgrade is
   listed in the report so a surveyor can check it;
3. a heat stretch >= 60 m with no OSM way under it is **added** - as 815 if the
   trace is strong, 816 if it is faint (the two solid symbols).

Set `"upgrade_confirmed": false` in `project.json` if the user wants the OSM tags
taken at face value.

## Measured riding speed - the `speed` step

The tag ladder above says what a path is *made of*; 815-822 record how fast you
*ride* it. With the rider's own GPS tracks that stops being a guess.

```bash
python $S speed --config project.json \
    --streams data/streams/*.json \
    --v-ref 30 --bands 28,13.5,6 --p-ref 228 --hr-lo 160 --hr-hi 180
```

Input is one JSON file per ride holding Strava activity streams - `location`,
`time`, `velocity_smooth`, `grade_smooth`, `moving`, and `heart_rate` and `watts`
where they exist. The official **Strava MCP connector** produces exactly this from
`get_activity_streams`; save each result to `data/streams/ride_<id>.json`. Find the
rides that touch the map by listing activities with `include_polyline` and decoding
the polyline against the map bbox - most of an athlete's rides will be elsewhere.

**What it computes.** Raw GPS speed conflates three things - the terrain, the
gradient, and how hard the rider was trying. Remove the last two:

1. **effort** - keep only samples inside a heart-rate band (hard but steady).
   Heart rate lags its cause, so the stream is shifted back `--hr-lag` (25 s).
2. **gradient, and the surface** - with a power meter, invert a cycling power
   model at the measured watts, speed and grade to get the path's **effective
   rolling resistance**, *including* an acceleration term (`m*a*v`); without it a
   forest ride's constant surging is charged to the surface and crr comes out
   two to three times too high. Then put that crr back into the model at a
   **reference power** (the athlete's FTP) on zero gradient and solve for speed.

The answer is "how fast does this path let you ride, on the flat, at threshold".
Rolling resistance is deliberately **not** held constant - it is the signal. On a
real forest map it ranged 0.012 on smooth tracks to 0.033 on rough ones, and the
band boundary that matters falls between those populations rather than through one.

Without a power meter only the gradient is normalised away, against the nominal
`--crr`; then heart rate carries the whole effort control.

**Bands.** `--bands` takes km/h thresholds directly (fast, medium, slow), so the
config says what the user said. Ask them to anchor it: "what speed is a good, fast
track?" Beware that a threshold set too low puts every measured way in one band and
the classification stops discriminating - on the Bryukhovychi map, 22.5 km/h made
18 of 19 ways "fast", while 28 km/h split them 8 fast / 11 medium. Print the
measured distribution before settling it.

**Evidence gating.** A way needs `--min-pts` (12) samples from `--min-traces`
rides before a measurement may override its tag. Matching is nearest way within
`--match-m` (12 m) *and* aligned within `--heading-deg` (40 deg), so a parallel
track does not steal the samples. Expect a third to a half of samples to match
nothing: some is GPS scatter under canopy, but much of it is trail OSM does not
have - a useful hint about where the map is incomplete.

In `build` a measured way outranks both the tag guess and the heatmap: it
has its heatmap upgrade suppressed (`"speed_overrides_heat"`), because a
measurement should never compete with an inference. Every reclassified way goes
into the report with its speed and sample count.

It is still one rider on a handful of days. Say so; a surveyor will move some of it.

## Contours

Source: **Copernicus DEM GLO-30**, 1-degree COGs on AWS open data, no credentials,
free licence with attribution. Other options, if asked: GLO-90 (same bucket,
coarser), NASADEM/SRTM GL1 via OpenTopography (needs an API key), ALOS AW3D30
(registration), FABDEM (canopy removed, so *better shapes under forest* - but it is
**CC BY-NC-SA**: non-commercial and share-alike, so flag it and do not use it for a
commercial or redistributed map). National LiDAR, where it exists, beats all of them.

GLO-30 is a **surface** model at 30 m posting: under forest it follows the canopy.
So the DEM is smoothed hard (sigma 35 m by default) before contouring, and the
result is an indicative landform, not surveyed contours. Say so. If the contours
come out noisy or terraced, raise `--smooth-m`; do not lower the interval.

Levels that are multiples of `interval * index_every` become 102 index contours,
the rest 101. Contour value text (102.1) is not placed automatically.

## Satellite imagery and vegetation

`imagery` merges **several** Sentinel-2 L2A scenes, not one - free and open
(Copernicus), COGs on AWS, found through the Earth Search STAC API, no credentials:

* 2+ **leaf-on** scenes (Jun-Sep) -> the RGB composite (a Mapper template for
  tracing) and summer NDVI;
* 2+ **leaf-off** scenes (Nov-Mar) -> winter NDVI.

Per-pixel median across the scenes of a season, with the SCL band masking cloud,
cirrus and cloud shadow first, so a partly clouded date does no harm; a scene with
more than 40 % of *this map* masked is skipped. Everything is sampled straight onto
the map's own grid, so no reprojection is needed later. Output: `data/satellite.png`
(+ `.pgw`/`.prj` for GIS) and `data/s2_stack.npz` (summer NDVI, winter NDVI, SWIR).

`vegetation` classifies **ESA WorldCover 10 m 2021** (free, CC BY 4.0) and refines
it with the seasonal NDVI:

| Evidence | ISMTBOM |
|---|---|
| tree cover, NDVI drops little from summer to winter (< 0.22) | **406** forest: reduced rideability and visibility |
| WorldCover shrubland | **406** |
| grassland, cropland, bare | **401** open land |
| herbaceous wetland | **308** marsh |
| tree cover, big seasonal drop (deciduous) | *nothing* - white forest |
| built-up | *nothing* - buildings and 520 come from OSM |

**Why two seasons.** Deciduous forest here drops ~0.40 NDVI between August and
January; conifer drops < 0.20. Inside tree cover the histogram of that drop is
bimodal, so the split is a real signal rather than a threshold pulled from the air -
print the percentiles before trusting the number, and re-tune `--evergreen-delta`
per area and per winter (snow ruins it: SCL masks cloud, not snow). Absolute winter
NDVI alone is *not* reliable - it moved 0.45 median here, well above the textbook
deciduous value.

Then satellite polygons are clipped and the union of the OSM area polygons is
**subtracted**, because OSM is surveyed and this is not. Small patches below
`--min-area-m2` (4000 m^2, ~18 mm^2 at 1:15 000) are dropped.

What this cannot see: undergrowth *below* a closed canopy - the very thing 406 is
about. It sees the canopy. Deciduous forest with a bramble understorey reads as
white; a mature open pine plantation reads as 406. Say that; expect a surveyor to
move perhaps a third of it. Garden trees on the settlement fringe are a known false
positive where OSM has no polygon to subtract.

## Georeferencing

The map's CRS is a **local transverse Mercator centred on the map** (`+proj=tmerc
+lat_0=... +lon_0=... +k=1`), so grid north is true north, the scale factor is
exactly 1, and `declination`/`grivation`/`auxiliary_scale_factor` are all zero or
absent. That removes the whole class of sign errors you get by declaring UTM and
then having to state a grid convergence. GPS import/export works because Mapper
hands the PROJ string to PROJ.

The screenshot is Web Mercator, which stretches E-W by 1/cos(lat) - handled - but
it still differs from the map frame by up to ~4 m at the edges of a 4 km map. That
is why the heatmap template is a convenience for tracing, not a reference.

North lines are drawn to **true** north (601.1 over the map extent), not magnetic
north. If the user wants magnetic north, set the declination in Mapper and rotate,
or delete that one object.

## Traps hit for real

* **The permalink zoom is not the screenshot scale.** Measure the scale bar.
  `detect_scalebar` looks for the *pair of narrow vertical ticks that repeats
  across rows*, not for a row containing only the bar - the corner also holds
  the zoom/3D buttons and the (i) attribution, and the bar's own "100 m" label
  sits between its ticks. An earlier version demanded exactly two dark clusters
  per row and so found nothing whenever the strip caught the (i) button.
  If it still returns nothing, measure the bar in an image editor and pass
  `--m-per-px`; then check the merge overlay, which is what actually proves it.
  A cross-check: `m/px = 156543.03 * cos(lat) / 2**(zoom + 1)` for a screenshot
  taken at device-pixel-ratio 2, the usual case.
* **Water is blue and so is the heatmap.** No colour test separates a faint trace
  from a stream, so the extraction keeps a blue component only if it contains a
  *violet* core (water never does), and cuts out anything wider than a corridor
  (ponds, urban fill).
* **Skeletonising a fat glow grows hair.** Close the gaps (`close_r`), smooth the
  corridor edge (`open_r`), prune spurs, then merge chains through degree-2 nodes -
  otherwise you get 11 000 stubs instead of 220 routes.
* **Only top-level symbols carry `id=`** in `<symbols>`. Cut symbol blocks at the
  id-bearing openers; a non-greedy `<symbol ...>.*?</symbol>` truncates any symbol
  containing mid-symbols or point elements.
* **Renumbering symbols breaks references.** `<object symbol="N">` and
  `<part symbol="N"/>` are ids, not codes.
* **Areas close with flag 18** on the repeated first coordinate; each further ring
  is a hole. Points are `type="0"`, text `type="4"`, everything path-like `type="1"`.
* **`remove_small_holes`/`remove_small_objects`** changed argument names in
  scikit-image 0.26; the warnings are harmless.
* **Overpass 504s a big query** and rate-limits (429) - the fetch is split per
  theme with backoff. `overpass.osm.ch` answers 200 with zero elements: do not use it.
* **Node data comes with the fetch pad**, so clip point features to the map
  rectangle or the extent grows past the paper size.

## Validate before reporting

```
XML parses; colour priorities contiguous; every spotcolor resolves
symbol ids contiguous 0..n-1, codes unique, every code in SPEC_CODES (or a kept variant)
every <object symbol="N"> and <part symbol="N"/> in range
object count attribute == actual object count, per part
object/symbol type compatibility (0->point, 4->text, 1->line/area/combined)
coordinate extent == the requested ground extent / scale, exactly
the merge overlay: OSM lines sit on the heat corridors
```

## Licences to state in the report

* OSM data: **(c) OpenStreetMap contributors, ODbL 1.0** - attribution required on
  any published map. Written into `<notes>`.
* Copernicus DEM: free with attribution (also in `<notes>`).
* Sentinel-2: **Copernicus Sentinel data, (c) ESA** - free, attribution required.
* ESA WorldCover 10 m: **CC BY 4.0** - attribution required, no share-alike.
* Donor symbol geometry comes from OpenOrienteering Mapper, **GPLv3**, whose
  `symbol sets/` carries no separate licence. Harmless for private use; flag it
  before anything commercial or redistributed.
* Strava heatmap: Strava's terms cover the imagery. Tracing it into a map you
  publish is the user's call to make - say so once, do not argue it.

## Files

* `scripts/mtbo_base.py` - the whole pipeline (`init`/`fetch`/`heatmap`/`contours`/
  `imagery`/`vegetation`/`speed`/`build`/`render`), the ISMTBOM 2022 code list, the
  OSM classification, the heatmap merge, the vegetation classifier and the
  cycling power model.
* `scripts/render_omap.py` - rough raster preview of any `.omap`.
* `reference/osm-mapping.md` - the full OSM tag -> ISMTBOM table, the speed-band
  ladder, the ISMTBOM 2022 code list and the non-spec equivalences.

[issue #1107]: https://github.com/OpenOrienteering/mapper/issues/1107
