# OSM tags -> ISMTBOM 2022, and the symbol list

## ISMTBOM 2022 (Revision 4, January 2025) symbol numbers

Landform and rock: `101` contour, `102` index contour (L, T), `104` earth bank,
`105` earth wall, `107` erosion gully, `108` small erosion gully, `109` small knoll,
`201` impassable cliff, `204` boulder, `206` gigantic boulder / rock pillar,
`210` stony ground, `213` open sandy ground, `214` bare rock.

Water and marsh: `301` uncrossable body of water, `304` crossable watercourse,
`305` small crossable watercourse, `306` minor/seasonal water channel,
`307` uncrossable marsh, `308` marsh, `313` prominent water feature.

Vegetation: `401` open land, `402` open land with scattered trees,
`403` rough open land, `404` rough open land with scattered trees, `405` forest,
`406` forest: reduced rideability and visibility,
`407` vegetation: reduced off-track rideability, good visibility,
`410` impassable vegetation, `413` orchard, `414` vineyard or similar,
`417` prominent large tree, `418` prominent bush or tree,
`419` prominent vegetation feature.

Man-made: `501` paved area, `501.1` step or edge of paved area,
`501.4` unpaved area fast riding, `502` paved road,
`502.1` wide unpaved road fast riding, `509` railway,
`510` power line / cableway / skilift, `511` major power line,
`512` bridge / tunnel, `513` passable wall, `515` impassable wall,
`516` passable fence or railing, `518` impassable fence or railing,
`519` crossing point, `520` area that shall not be entered, `521` building,
`522` canopy, `522.1` pillar, `524` high tower, `525` small tower,
`527` fodder rack, `528` passable line feature, `529` uncrossable line feature,
`530` prominent man-made feature (ring), `531` prominent man-made feature (x),
`532` stairs.

Technical: `601` magnetic north line, `603` spot height (P, T).

Rideability (section 4.1 / 4.2): `815`/`816` track/path fast,
`817`/`818` medium, `819`/`820` slow, `821`/`822` very slow, `823` track end point,
`824` open land permitted to ride, `825`/`825.1`/`825.2` forested area permitted to
ride, `826` rough open land permitted to ride, `827`-`830` narrow ride permitted to
ride (fast/medium/slow/very slow), `841` one-way compulsory.

Course symbols: `701`-`719` as ISOM, `704` control number, `705` course line,
`707` marked route, `708`/`709` out-of-bounds, `710` crossing point.

Widths: track or wide path **0.6 mm**, narrow path **0.4 mm**. Speed bands relative
to a hard smooth surface: fast 75-100 %, medium 50-75 %, slow 25-50 %,
very slow 0-25 %. Base scale 1:15 000; symbols enlarge x1.2 at 1:12 500 and x1.5 at
1:10 000 and larger.

## Not in ISMTBOM 2022 -> what it becomes

These are the ISOM symbols a converted donor set still carries. `ISOM_TO_ISMTBOM`
in the script moves the objects; `filter_symbol_set` removes the symbols.

| Not in the spec | Becomes | Why |
|---|---|---|
| 103 form line | 101 contour | no form lines in ISMTBOM |
| 113 elongated knoll, 115 small depression, 116 pit | 109 small knoll | nearest point feature |
| 117.1/117.2 broken ground, 207/208/209 boulder groups | 210 stony ground | area of rough ground |
| 203.x passable rock face | 201 impassable cliff | only one cliff symbol |
| 204-ISOM rocky pit, 205 cave | 204 boulder / 530 | point feature |
| 302 pond | 301 uncrossable body of water | |
| 303 waterhole, 312 well, 313-ISOM spring | 313 prominent water feature | |
| 311 indistinct marsh, 308-ISOM narrow marsh | 308 marsh | |
| 408/409 dense forest, 411.x directional forest | 406 reduced rideability | one green level |
| 415 cultivated land | 401 open land | |
| 416 / 414-ISOM vegetation boundary | 528 passable line feature | ISMTBOM has none |
| 501.0/501.5 motorway, 503.1 minor road | 502 paved road | |
| 504-508 ISOM paths | 817 / 819 / 818 / 820 / 822 | the ladder, see below |
| 509-ISOM narrow ride | 830 narrow ride, very slow | off-track group |
| 520-ISOM ruined stone wall, 523 ruined fence | 515 / 516 | |
| 527.1 / 527-ISOM settlement | 520 area that shall not be entered | **no settlement symbol in ISMTBOM**; 527 is a fodder rack |
| 530.x / 537 cairn / 532-ISOM grave | 530 prominent man-made feature | |
| 602 registration mark, 799, 980.x text, 999 logo | dropped | not map content |

Mapper implementation variants that are **kept**, because they render a spec
symbol: `X.0.1`/`X.1` minimum-size point versions, `301.1`/`301.2` bank line and
the area+bank combined symbol, `307.1`/`307.2`, `308.1`, `520.1`, `521.1`,
`601.1` north-line pattern, `603.1` spot-height text, `709.1`/`709.2`.

## highway -> symbol

Speed band: `tracktype` if present, else `surface`, then a `smoothness` penalty
(bad/very_bad +1, horrible/very_horrible +2, impassable +3); `surface=sand|mud` is
forced to at least slow. Bands are capped at very slow.

| `tracktype` | band | | `surface` | band |
|---|---|---|---|---|
| grade1, grade2 | fast | | asphalt, concrete, paving_stones, sett, ... | fast (paved) |
| grade3 | medium | | compacted, gravel, fine_gravel | fast |
| grade4 | slow | | unpaved, ground, dirt, earth, pebblestone, *unstated* | medium |
| grade5 | very slow | | grass, sand, dirt/sand, woodchips | slow |
| | | | mud | very slow |

| `highway` | family | fast | medium | slow | very slow |
|---|---|---|---|---|---|
| motorway...residential, service, road | road | **502** if paved or surface unstated, else **502.1** | 817 | 819 | 821 |
| track | track | 815 | 817 | 819 | 821 |
| path, cycleway, footway, bridleway | path (track if `width>=1.8`) | 816 | 818 | 820 | 822 |
| steps | - | 532 | | | |

## everything else

| OSM | ISMTBOM | note |
|---|---|---|
| `railway=rail\|tram\|...` | 509 | |
| `power=line` / `minor_line`,`cable` | 511 / 510 | |
| `waterway=river\|canal` / `stream` / `ditch\|drain` | 304 / 305 / 306 | |
| `natural=water`, `landuse=reservoir\|basin`, `leisure=swimming_pool`, `water=*` | 301 (Mapper 301.2, area + bank) | |
| `natural=wetland` | 308 | |
| `natural=scrub` | 406 | |
| `natural=sand\|beach` / `bare_rock\|rock\|scree` | 213 / 214 | |
| `natural=wood`, `landuse=forest` | **nothing** | forest is white |
| `natural=grassland\|meadow`, `landuse=meadow\|grass\|farmland\|farmyard\|village_green\|recreation_ground\|cemetery\|construction\|religious`, `leisure=pitch\|playground\|park\|garden\|golf_course\|track` | 401 | |
| `natural=heath` | 403 | |
| `landuse=orchard` / `vineyard` / `plant_nursery\|allotments` | 413 / 414 / 413 | |
| `landuse=residential\|industrial\|commercial\|retail\|garages` | 520 | private / not to be entered |
| `building=*` | 521 | area, whatever the size |
| `barrier=fence\|guard_rail\|handrail` / `wall\|retaining_wall\|city_wall` / `hedge` | 516 / 513 / 528 | |
| `man_made=pier` | 528 | |
| node `natural=peak` | 603 + 603.1 text from `ele` | |
| node `natural=tree` / `rock\|stone` / `spring` | 417 / 204 / 313 | |
| node `man_made=mast\|tower\|water_tower` / `cross\|obelisk\|flagpole` / `water_well` | 524 / 531 / 313 | |
| node `historic=monument\|memorial\|wayside_cross\|wayside_shrine` | 531 | |
| node `barrier=gate\|lift_gate\|swing_gate\|cycle_barrier\|bollard` | 519 | |
| node `tourism=picnic_site\|viewpoint` | 530 | |

Deliberately not mapped: `amenity=*` (parking would want 501, but the OSM polygons
rarely match what a rider sees), address nodes, `highway=bus_stop`, boundaries,
routes and any relation that is not a multipolygon.

## Off-track riding

The tables above assume off-track riding is **permitted**, i.e. the 4.1 black
network is enough. If it is forbidden, the map must instead show where riding *is*
allowed, with the orange 4.2 group: 824 open land, 825.1/825.2 forested area,
826 rough open land, 827-830 narrow rides. Ask the user; the script does not do
this automatically, and OSM has no data for it either.

## Remote-sensed vegetation (the `imagery` + `vegetation` steps)

| Evidence | ISMTBOM | note |
|---|---|---|
| WorldCover tree cover (10) + seasonal NDVI drop < 0.22 + winter NDVI > 0.40 | 406 | evergreen / conifer canopy: the visibility proxy |
| WorldCover shrubland (20) | 406 | thicket |
| WorldCover grassland (30), cropland (40), bare (60) | 401 | |
| WorldCover herbaceous wetland (90) | 308 | |
| WorldCover tree cover with a large seasonal drop | *nothing* | deciduous = white forest |
| WorldCover built-up (50), water (80) | *nothing* | OSM supplies 520/521 and 301 |

Reference numbers measured over the Bryukhovychi Forest (Aug 2025 vs Jan 2025 Sentinel-2,
two scenes each): summer NDVI median 0.85; winter NDVI median 0.45; the drop inside
tree cover was median 0.39 with 17 % of pixels below 0.22. Do not reuse the 0.22
threshold blindly - print the distribution for the area at hand first.

ISMTBOM 2022 has exactly **one** green level (406) plus the optional 407, so there
is nothing to gain from a finer density classification: any "dense vegetation" class
collapses to 406.
