# ISOM / ISSprOM <-> ISMTBOM 2022 reference

> **Format.** These tables describe symbols in OpenOrienteering Mapper's native XML
> format — `.omap` (and its verbose twin `.xmap`). Dimensions are given in the units
> Mapper stores, 1/1000 mm at the map's own scale. They do **not** apply to OCAD
> `.ocd` files: open such a map in Mapper and save it as `.omap` first.
> <https://github.com/OpenOrienteering/mapper>

> **Source and attribution.** Symbol numbers, names, dimensions and colours are facts
> taken from **ISMTBOM 2022**, **ISOM 2017-2** and **ISSprOM 2019**, published by the
> IOF Map Commission. The specifications are licensed CC BY-ND 4.0 and are not
> reproduced here — consult the IOF publications for the authoritative text and
> drawings. <https://omapwiki.orienteering.sport/>

Specs:
- ISMTBOM 2022 — https://omapwiki.orienteering.sport/specifications/ismtbom/
  (the omapwiki page 403s to WebFetch; get the PDF instead, e.g. the IOF revision
  hosted by member federations, and extract text with PyMuPDF `fitz`)
- ISOM 2017-2 — https://omapwiki.orienteering.sport/specifications/isom/

The wiki has a page per symbol, e.g. `/symbols/521-building/`. **Those default to the
ISOM entry**; the ISMTBOM variant of the same number lives at a suffixed slug such as
`/symbols/521-building-3/` (find it by following the link from the ISMTBOM index).
The colours differ between specs — ISOM 521 is black 50%, ISMTBOM 521 is black 60% —
so always confirm you are reading the ISMTBOM page.

omapwiki returns 403 to WebFetch; fetch with curl and a browser User-Agent instead.

## Basics (ISMTBOM 2022 section 3)

- Base scale **1:15 000**. Sprint MTBO 1:5 000.
- Symbol dimensions in the spec are given at 1:15 000. Enlargement: 1:12 500 x1.2,
  1:10 000 / 1:7 500 / 1:5 000 x1.5 (course symbols follow the same factors).
- Contour interval **5 m** (10 m in very hilly, 2.5 m in flat/sprint terrain).
- Track/path width classes: **track or wide path 0.6 mm** (>= ~1.8 m on the ground),
  **narrow path 0.4 mm** (< ~1.8 m).
- Speed bands relative to a hard smooth surface: fast 75-100 %, medium 50-75 %,
  slow 25-50 %, very slow 0-25 %.

## Section 4.1 — paths, tracks and roads (black)

| Code | Name | Width | Dash / gap |
|---|---|---|---|
| 502 | Paved road | 0.3 + 2x0.18 min | brown 50 % fill, black casing |
| 502.1 | Wide unpaved road, fast riding | as 502 | " |
| 501.1 | Step or edge of paved area | 0.18 | solid |
| 815 | Track: fast riding | 0.6 | solid |
| 816 | Path: fast riding | 0.4 | solid |
| 817 | Track: medium riding | 0.6 | 3.0 / 0.5 |
| 818 | Path: medium riding | 0.4 | 3.0 / 0.5 |
| 819 | Track: slow riding | 0.6 | 1.5 / 0.4 |
| 820 | Path: slow riding | 0.4 | 1.5 / 0.4 |
| 821 | Track: very slow riding | 0.6 | 0.8 / 0.3 |
| 822 | Path: very slow riding | 0.4 | 0.6 / 0.3 |
| 823 | Track end point | 1.1 x 0.25 bar | optional |
| 532 | Stairs | 2 x 0.12, min 0.4 IM | |

## Section 4.2 — other features where riding is permitted

Used when off-track riding is **forbidden**, to show where it is allowed.

| Code | Name | Colour |
|---|---|---|
| 501 | Paved area | brown 50 % + black |
| 501.4 | Unpaved area, fast riding | brown 50 % + black |
| 824 | Open land, permitted to ride | orange, solid |
| 825.1 | Forested area, permitted to ride | black dots o0.35 @ 0.9 CC, 45 deg |
| 825.2 | Minor forested area, permitted to ride | black dots o0.35 @ 0.6 CC |
| 826 | Rough open land, permitted to ride | orange dots o0.25 @ 0.4 CC, 45 deg |
| 827 / 828 / 829 / 830 | Narrow ride, permitted to ride: fast / medium / slow / very slow | orange 0.9 wide; dashes as 815/817/819/821 |
| 213 | Open sandy ground | black 60 % dots + yellow 50 % |

Orange is **60 % magenta + 100 % yellow** — it must read as clearly different from
yellow 100 %.

## Colours that depend on the map scale

Two symbols in section 4.7 are specified differently for enlarged maps:

| Symbol | 1:15 000 / 1:12 500 / 1:10 000 | 1:7 500 and 1:5 000 |
|---|---|---|
| 521 Building | solid **black** | **black 60 % fill + black outline (0.14 mm)** |
| 522 Canopy | **black 25 %**, no outline | black 25 % fill + **black 60 % outline (0.1 mm)** |

The spec wording is "Colour: black (or black (outline), black 60%). Outline shall
only apply in 1:5 000 or 1:7 500." Outline widths are quoted at 1:15 000 like every
other dimension, so they are enlarged by the same factor (x1.5 -> 0.21 mm and
0.15 mm at 1:5 000).

Mapper area symbols have **no** border property, so an outlined area has to be a
combined symbol: a fill area plus an outline line, with 521/522 as the type-16
combined symbol the objects point at. Remember to repoint its <part symbol="N"/>
ids after the symbol list is built.

## Which ISOM is the source? This decides almost everything

**ISMTBOM 2022 shares ISOM 2017-2's numbering** — both come out of the 2017
renumbering. So the work depends entirely on which ISOM the source uses:

| | ISOM 2000 | ISOM 2017-2 |
|---|---|---|
| Earth bank | 106 | **104** |
| Erosion gully | 109 | **107** |
| Boulder | 206 | **204** |
| Open sandy ground | 211 | **213** |
| Bare rock | 212 | **214** |
| Crossable watercourse | 305 | **304** |
| Uncrossable marsh | 309 | **307** |
| Marsh | 310 | **308** |
| Paved area | 529 | **501** |
| Building | 526 | **521** |
| Impassable wall | 521 | **515** |
| High fence | 524 | **518** |
| High tower / Small tower | 535 / 536 | **524 / 525** |

Check the source's own `<symbols id="...">` (`ISOM2000`, `ISOM 2017-2`, `ISSOM`,
`ISMTBOM`) **and** a few codes. Do not assume; getting this wrong silently converts
Earth banks into slope lines and Boulders into rocky pits.

- **ISOM 2000 source** -> use the full renumbering table below.
- **ISOM 2017-2 source** -> the terrain numbering is already correct. The job reduces
  to: 503-507 -> 815-822 (502 Wide road -> 502 Paved road), 508 Narrow ride ->
  827-830, merge 408/409 into 406/407, drop 415 (cultivation boundary) and
  416 (vegetation boundary) per section 4.6,
  recolour rock and man-made symbols to black 60 %, and drop the ISOM-only symbols
  ISMTBOM does not define. **Do not apply the ISOM 2000 table.**
- **ISSprOM 2019 source** -> the ISSprOM 2019 table further down.

## Renumbering: ISOM **2000** -> ISMTBOM 2022

| ISOM 2000 | ISMTBOM 2022 | Note |
|---|---|---|
| 101, 102 | 101, 102 | unchanged |
| 104 Slope line | 101.1 | ISMTBOM 104 is Earth bank |
| 105 Contour value | 102.1 | |
| 106 Earth bank | **104** | |
| 107 Earth wall | **105** | |
| 109 Erosion gully | **107** | |
| 110 Small erosion gully | **108** | |
| 112 Small knoll | **109** | |
| 201 Impassable cliff | 201 | black -> **black 60 %** |
| 202 Rock pillars/cliffs | **206** Gigantic boulder or rock pillar | black 60 % |
| 206 Boulder | **204** | black 60 % |
| 210.1 Stony ground | **210** | black 60 % |
| 211 Open sandy ground | **213** | |
| 212 Bare rock | **214** | black 30 % |
| 301 Lake | 301 Uncrossable body of water | |
| 305 / 306 / 307 | **304 / 305 / 306** | watercourses |
| 309 Uncrossable marsh | **307** | |
| 310 Marsh | **308** | |
| 314 Special water feature | **313** Prominent water feature | |
| 401-404 | 401-404 | unchanged |
| 405 Forest: easy running | 405 Forest | |
| 406 Forest: slow running | 406 Forest: reduced rideability and visibility | green 30 % |
| 407 Undergrowth: slow running | 407 Vegetation: reduced off-track rideability | optional; off-track-allowed maps only |
| 408, 409 | — | **merge into 406 / 407** |
| 410 | 410 Impassable vegetation | |
| 412 Orchard | **413** | |
| 413 Vineyard | **414** | |
| 414, 416 cultivation/vegetation boundary | — | **section 4.6 requires omitting them** (confusable with track symbols) |
| 415 Cultivated land | — | no equivalent |
| 418 Special veg. (X) | **419** Prominent vegetation feature | |
| 419 Special veg. (ring) | **417** Prominent large tree | |
| 420 Special veg. (dot) | **418** Prominent bush or tree | |
| 502 Major road | 502 Paved road | |
| 503 Minor road | 502.1 Wide unpaved road | or 502 if paved |
| 504-509 paths | **815-822 / 827-830** | see ladders below |
| 515 Railway | **509** | black 60 % |
| 516 Power line | **510** | |
| 517 Major power line | **511** | black 60 % |
| 518 Tunnel | **512** Bridge / tunnel | |
| 519 Stone wall | **513** Passable wall | black 60 % |
| 521 High stone wall | **515** Impassable wall | black 60 % |
| 522 Fence | **516** Passable fence or railing | black 60 % |
| 524 High fence | **518** Impassable fence or railing | black 60 % |
| 525 Crossing point | **519** | black 60 % |
| 526 Building | **521** | **black** at 1:15 000 (outline + black 60 % only at 1:5 000 / 1:7 500) |
| 527 Settlement | — | no equivalent; 520 is the usual substitute |
| 528 Permanently out of bounds | **520** Area that shall not be entered | yellow 100 % + green 50 % |
| 529 Paved area | **501** | |
| 533 Crossable pipeline | **528** Passable line feature | black 60 % |
| 534 Uncrossable pipeline | **529** Uncrossable line feature | black 60 % |
| 535 High tower | **524** | black 60 % |
| 536 Small tower | **525** | black 60 % |
| 538 Fodder rack | **527** | black 60 % |
| 539 / 540 Special man-made | **530 / 531** Prominent man-made feature ring / x | black 60 % |
| 601 | 601 | **blue**, 0.12 mm |
| 603.0 / 603.1 | 603 / 603.1 | black 60 % |
| 702 Control point | **703** | |
| 703 Control number | **704** | |
| 704 Line | **705** Course line | |
| 705 Marked route | **707** | |
| 707 Uncrossable boundary | **708** Out-of-bounds boundary | |
| 708 Crossing point | **710** | |
| 711 Forbidden route | **716** | |

New in ISMTBOM 2022 with no ISOM source: 522 Canopy, 522.1 Pillar, 702 Map issue
point, 703.1 Control point with focus point, 715 Continuing point after map exchange,
717 Obstacle across track/path/road, 718 Forbidden to pass, 719 Dangerous section,
841 One-way compulsory, plus the 4.1/4.2 groups above.

Dropped by ISMTBOM 2022: form line, small earth wall, elongated knoll, small
depression, pit, broken ground, special land form, passable rock face, rocky pit,
cave, large boulder, boulder field, boulder cluster, pond, waterhole, narrow marsh,
indistinct marsh, well, spring, 408/409, 411.x, 414/415/416, motorway, ISOM 504-509,
footbridge, ruined wall/fence, settlement, ruin, firing range, grave, cairn,
dangerous area.

## Rideability ladders to offer

Neither is surveyed data. Present both plus an honest placeholder.

**The two ISOM vintages number the path network differently — 2017-2 is shifted one
down from 2000.** Use the table that matches the source.

ISOM **2000**:

| ISOM 2000 | conservative | pessimistic |
|---|---|---|
| 503 Minor road | 502 Paved road | 502 Paved road |
| 504 Road | 815 Track: fast | 817 Track: medium |
| 505 Vehicle track | 817 Track: medium | 819 Track: slow |
| 506 Footpath | 816 Path: fast | 818 Path: medium |
| 507 Small path | 818 Path: medium | 820 Path: slow |
| 508 Less distinct small path | 820 Path: slow | 822 Path: very slow |
| 509 Narrow ride | linear 403, or 827-830 if off-track forbidden | 830 |

ISOM **2017-2**:

| ISOM 2017-2 | conservative | pessimistic |
|---|---|---|
| 502 Wide road | 502 Paved road | 502 Paved road |
| 503 Road | 815 Track: fast | 817 Track: medium |
| 504 Vehicle track | 817 Track: medium | 819 Track: slow |
| 505 Footpath | 816 Path: fast | 818 Path: medium |
| 506 Small footpath | 818 Path: medium | 820 Path: slow |
| 507 Less distinct small footpath | 820 Path: slow | 822 Path: very slow |
| 508 Narrow ride or linear trace | linear 403, or 827-830 if off-track forbidden | 830 |

Placeholder option: everything to 815 (track) or 816 (path) by width alone, so it is
obvious the speed classification has not been surveyed.

## ISSprOM 2019 (sprint) -> ISMTBOM 2022, for the 1:5 000 format

| ISSprOM | ISMTBOM 2022 |
|---|---|
| 101, 102 | 101, 102 |
| 104 Slope line | 101.1 |
| 110 Small erosion gully | 108 |
| 201, 201.1, 201.2 | 201, 201.1, 201.2 (black 60 %) |
| 202 Gigantic boulder / rock pillar | 206 |
| 206 Boulder, 207 Large boulder | 204 |
| 211 Open sandy ground | 213 |
| 304.3 Impassable body of water | 301 |
| 312 Small fountain or well | 313 |
| 401, 402, 403, 405, 406, 407 | unchanged |
| 418 Prominent large tree | **417** |
| 419 Prominent bush or small tree | **418** |
| 421 / 421.1 Impassable vegetation (hedge) | 410 / 410.1 |
| 506.1.1 / 506.1.2 unpaved footpath or track | 818 / 817 |
| 507 Small unpaved footpath | 820 |
| 508 Less distinct small path | 822 |
| 512.1.1, 512.1.2 Bridge, 518.1 Underpass/tunnel | 512 |
| 519.1.1 Passable wall | 513 |
| 521.1.1 Impassable wall | 515 |
| 522, 522.0.1 Passable fence or railing | 516 |
| 524 Impassable fence or railing | 518 |
| 526.1 Building, 526.1.3 minimum size | 521, 521.1 |
| 526.2 Canopy, 526.3 Pillar | 522, 522.1 |
| 528.1 Area with forbidden access | 520 |
| 529.0.1 / 529.0.7 Paved area urban / non-urban | 501 (the tint distinction is lost) |
| 529.0.8 Paved area with border | 501.2 |
| 529.1.1 / 529.1.2 Step or edge of paved area | 501.1 |
| 529.1.3 / 529.1.4 narrow / wide stairway | 532 Stairs |
| 539 / 540 Prominent man-made feature | 530 / 531 |
| 601.0.5 / 601.0.6 north line, blue | 601 / 601.1 |
| 704 Line | 705 Course line |
| 709, 709.1 | 709, 709.1 |

Sprint rideability ladder (surface-based; paved is genuinely fast in town):

| ISSprOM | surface-based | pessimistic |
|---|---|---|
| 529.0.6 paved 0.9 mm | 502 Paved road | 502 Paved road |
| 529.0.5 paved 0.7 mm | 815 Track: fast | 817 Track: medium |
| 529.0.4 paved 0.55 mm | 815 Track: fast | 817 Track: medium |
| 529.0.3 paved 0.35 mm | 816 Path: fast | 818 Path: medium |
| 506.1.2 unpaved 0.55 mm | 817 Track: medium | 819 Track: slow |
| 506.1.1 unpaved min | 818 Path: medium | 820 Path: slow |
| 507 small unpaved | 820 Path: slow | 822 Path: very slow |
| 508 less distinct | 822 Path: very slow | 822 Path: very slow |

No ISMTBOM equivalent, carry over: 103 Form line, 208 Boulder field (point symbol —
ISMTBOM 210 is an area, so a remap would be type-incompatible), 305.0.1 / 305.1
passable body of water, 406.1 / 408 / 408.1 / 409 green variants, 414 / 415 / 416,
521.1.2 Impassable wall plan shape, 526.2.x canopy helpers, 537 Cairn, and all the
layout symbols (799.x, 800.x, 899.x, 999).

Sprint sources also need the **four extra colours** inserted into the ISSprOM table:
Black 60 % (after "Black 50-65% for buildings"), Black 25 % (after Black 30 %),
Brown 50 % (before the paved-area browns) and Orange 0/0.6/1/0 (just above Yellow, so
824/826 sit at the open-land level under green).

## The pre-2022 Mapper set (`ISMTBOM_15000.omap`, 170 symbols)

ISOM numbering plus MTBO-specific codes. Map these to 2022:

| pre-2022 | 2022 |
|---|---|
| 831 / 832 | 815 / 816 |
| 833 / 834 | 817 / 818 |
| 835 / 836 | 819 / 820 |
| 837 / 838 Track/Path: difficult to ride | 821 / 822 Track/Path: very slow riding |
| 509.1 Narrow ride | 827-830 |
| 840 Control point with focus point | 703.1 |
| 843 Dangerous object across tracks/paths | 717 |
| 844 Uncrossable barrier / forbidden to cross | 718 |

Its widths are already 0.6 / 0.4, but the **gaps differ** from 2022 — override
817/818 to 0.5, 819/820 to 0.4, and 821/822 to dash 0.8 / 0.6 with gap 0.3.

Its colour table needs three edits for 2022: `Black 70%` -> **`Black 60%`** (k 0.6,
factor 0.6), `OpenOrienteering Orange` -> **`Orange`** at 0/0.6/1/0, and a new
**`Black 25%`** for 522 Canopy. Remember to shift `spotcolor=` references when you
insert.

Symbols carried over as approximations (no recoverable 2022 drawing): 702, 715, 719,
841. Put a warning in each symbol's `<description>` so it shows up in Mapper.
