# City View

Generate walkable Antwerp streets and orbitable district tiles in Blender from facade photos and OpenStreetMap. The hero deliverable is **Klein Antwerpen / Harmonie · 2018**: LOD1 footprints coloured with historic neighbourhood palettes.

Generation can run headless through the local Blender binary, or live through the official Blender Lab MCP add-on (Blender 5.1+).

## What you get

- **District orbit** — Harmonie / Klein Antwerpen from OSM, with neoclassical, eclectic, neo-Flemish, Art Nouveau, Art Deco, International Style, and modern-infill colours
- A photo-textured hero building street mode (late 70s / early 80s rijhuizen)
- Procedural neighbors, sidewalks, asphalt, lamps
- `.blend`, `.glb`, preview renders, and a Three.js viewer
- GitHub Pages deploy of the Klein Antwerpen orbit viewer

## Requirements

- macOS with Blender 5.1+ at `/Applications/Blender.app` (or set `BLENDER_BIN`)
- Python 3.11+

## Klein Antwerpen district (2018)

```bash
python3 -m cityview city --place klein-antwerpen
python3 -m cityview serve
```

Open http://127.0.0.1:8765/ — you spawn at **Velo Harmonie (042)** on Mechelsesteenweg at eye height. Click or tap to walk (WASD + mouse look on desktop; on-screen stick + drag look on iPad/phone); press **E** to take a Velo or board a stopped tram. The tile uses LOD2 roofs (gable / hip / mansard / flat from OSM + style) and style-driven procedural facades on street-facing edges. Colours come from [`assets/styles/klein_antwerpen_2018.json`](assets/styles/klein_antwerpen_2018.json).

Alias: `--place harmonie` uses the same bbox, spawn, and historic style policy. OSM for this tile is cached at [`assets/osm/harmonie.json`](assets/osm/harmonie.json) (committed for reproducible CI).

**Transit:** tram/premetro tracks and bus/tram stops come from OpenStreetMap; De Lijn line numbers come from the official [GTFS static feed](https://data.belgianmobility.io/en/data.html?agency=delijn) (cached under `assets/gtfs/`). Antwerp’s underground service is De Lijn **premetro** (tram in tunnel), not a separate metro. The walk viewer loads `transit.json` for moving trams/buses with line labels. Use `--refresh` to re-download OSM + GTFS.

**Travel directions (one-way streets, dual carriageways, tram tracks):** `roads.json` carries `oneway` / `onewayBus` per road (1 = only along its points, -1 = only against, 0 = both) straight from the OSM `oneway`, `oneway:bus`/`psv`, `busway=opposite_lane`, roundabout and motorway rules (`cityview/directions.py`), plus `dualCarriageway` for the opposing one-way halves of a boulevard like Mechelsesteenweg. `transit.json` carries `direction` per path: tram tracks get it from the ordered `route=tram` relations (the two median tracks run opposite ways; a parallel partner track settles any track without a relation, right-hand traffic), GTFS bus shapes are stop-to-stop so always forward. `traffic.js` / `transit.js` only spawn, respawn, hand over and re-enter vehicles in a legal direction (a one-way dead end recycles the car instead of U-turning), and `lanes.js` only snaps a bus into a lane it may legally drive. `node scripts/sim_directions.mjs 10 --seeds=1,2,3` audits that against an independent oracle built from the raw OSM extract and exits non-zero on any wrong-way vehicle (`VIEWER_ROOT=<old viewer/>` replays an older build). `python3 scripts/export_viewer_data.py` re-exports `roads.json` / `transit.json` without Blender.

**Livery:** trams and buses wear De Lijn colours (white body, grey skirt `#575E62`, dark glazing band, yellow `#FFD800` door / front stripes, the "lijn" mark; palette from the [De Lijn huisstijlgids 2022](https://assets.ctfassets.net/32fmeyn9t08i/5mkxQn9jaDTevhdBym6BeK/5d87215d9dd11baeae48ca58e728e3be/huisstijlgids-2022.pdf)). Reference photos used (Wikimedia Commons, viewed only, not redistributed): [Albatros tram 7345](https://commons.wikimedia.org/wiki/File:Albatros_nr_7345.jpg), [Rooseveltplaats bus](https://commons.wikimedia.org/wiki/File:Rooseveltplaats_bus.JPG), [Antwerpen 2023-05-12 12](https://commons.wikimedia.org/wiki/File:Antwerpen_2023-05-12_12.jpg). Flat side / front / rear elevations were generated from those references (`assets/references/delijn-liveries/`), then `python3 scripts/make_delijn_livery.py` crops them, blanks the baked-in LED boards and writes the textures to `viewer/livery/` (plus emissive window maps for night). `viewer/transit.js` maps them 1:1 onto the body boxes and adds live amber LED destination boards ("7 Antwerpen Gounod"), line badges in De Lijn palette colours, headlight / tail-light glow at night, roof pods, a pantograph and yellow bus mirrors. Bump `LIVERY_VERSION` in `transit.js` when the textures change.

**Traffic soaks (headless, Node):** `node scripts/sim_flow.mjs 10 --seeds=1,2,3` runs the real `viewer/traffic.js` + `viewer/transit.js` against `roads.json` / `transit.json` and reports what a person watching the street sees: how much of the visible fleet is standing still (whatever the reason), how many trams/buses are actually *in the district* (the district is ~0.7 km of 1-5 km routes, so vehicles are seeded inside it and re-enter through gates on the rim), pile-ups and holds >60 s. It fails when trams/buses vanish, when >20 % of the fleet stands still on average, or on pile-ups. `scripts/sim_traffic.mjs` (unexplained stops, speed limits) and `scripts/sim_cars_audit.mjs` (junction stalls, footprint overlaps, car vs tram/bus) take `--player=spawn` to park the walker at the Gounod halt like a real session; `--fps=N` re-runs any of them at another frame rate (the sims sub-step real elapsed time, so 5 fps and 144 fps behave the same).

**Street-level detail:** each façade elevation is weathered when the atlas is packed (`python -m cityview.facade_textures`: ground grime, cornice soot, rain streaks, pale gable sky repainted slate). Front doors recorded per elevation in [`cityview/facade_kit.py`](cityview/facade_kit.py) (`DOORS`) get granite doorsteps. Kerbs are real ~11 cm stone prisms with a road riser and the pavement is raised to meet them; [`cityview/kerbs.py`](cityview/kerbs.py) cuts both where a side street joins so junction mouths stay open.

**Building heights (OSM first, then a footprint prior, hard cap 20 levels):** [`cityview/building_heights.py`](cityview/building_heights.py). The old pipeline gave every footprint without `building:levels` / `height` one default eaves height (12 m = "4 floors"), which in Harmonie is 96 % of the buildings: 94.7 % of the tile extruded to exactly 4 levels. Coverage in the cached tile (3,344 building ways/relations): `building:levels` on 135 (4.0 %), `height=*` on none, `building:min_level` / `building:part` essentially absent, `roof:levels` on 17. Order of evidence, recorded per building as `height_source` in the layout: `osm_height` > `osm_levels` (minus `building:min_level`) > `photo` ([`assets/heights/photo_levels.json`](assets/heights/photo_levels.json), surveyed storey counts used only where OSM is silent) > `inferred`. Inference is a deterministic draw (blake2b of the OSM id) from a type + footprint table: townhouses (addressed, < 300 m2) 2 / 3 / 4 / 5 levels at 10 / 60 / 26 / 4 %, mid and large non-apartment footprints 3-6, `building=apartments` 3-7 (mean ~4.4) under 300 m2, 4-8 up to 500 m2 and 6-12 above (so 10+ exists only for large blocks); unaddressed footprints under 60 m2 and garages / sheds / canopies are 1 level (not houses), under 150 m2 2 levels. Touching neighbours copy each other 55 % of the time (towers never spill onto the houses beside them), so terraces read as runs of one cornice line with the odd step instead of dice rolls. Levels are capped at 20 everywhere (tagged values too); eaves are `levels x 3.15 m` (+/-3 % jitter), buildings of 7+ levels get flat roofs. Churches, schools, hospitals and supermarkets without OSM numbers keep their fixed type heights (`type_default`).

**Tall facades without a kaleidoscope:** one generated elevation is a 3-5 storey house, so stretching it to 38 m smears the windows. [`assets/textures/facade_bands.json`](assets/textures/facade_bands.json) (`python -m cityview.facade_textures --bands`) stores, per elevation, a *repeatable storey strip*: the pair of picture rows (above the ground floor, below the cornice) that match best when row `hi` meets row `lo`, preferring seams between window rows and a strip about one storey tall. [`facade_kit.plan_house_bands`](cityview/facade_kit.py) then cuts each house into ground floor + `k` copies of the strip + top floor/cornice, scaled uniformly to meet the eaves (k = 0 drops a storey for 2-level houses), never mirrored. Doors, awnings and downpipes stay on the ground piece; window reveals follow the glass of every strip; towers (7+ levels) use wider 9 m elevations. 45 of 50 elevations have a clean enough seam (5 keep the single-stretch mapping and are penalised in scoring when the stretch is large).

**Windows (layered detection):** `python -m cityview.facade_windows` finds the glass in every generated elevation in three passes: (1) compact darker-than-wall blobs (tight on the glass), (2) *framed* windows that are not darker than the wall (white sashes in brick, stone surrounds) as dense rectangles of edges picked from a threshold hierarchy, and (3) every confident window is used as a template, because an elevation repeats the same sash on every floor, so normalised cross-correlation of the edge image recovers the siblings the first two passes missed. Detected windows went from 160 to 328 across the 50 elevations; the new ones get sills/heads and night glow like the old ones. Rooms on the top ~7 % of an elevation (roof/dormer band) are still skipped.

**Street clutter (OSM-mapped, not invented):** [`cityview/clutter.py`](cityview/clutter.py) reads point features straight from the cached OSM tile — `amenity=waste_basket`, `amenity=bicycle_parking` (hoop count from `capacity`), `barrier=bollard`, `emergency=fire_hydrant` (pillars only), `amenity=post_box`, `amenity=recycling` (bring-site containers), `man_made=street_cabinet`, `vending=parking_tickets` (pay & display), `man_made=flagpole`, `highway=street_lamp`. Like benches, duplicates collapse, anything inside a building or on a tram bed is dropped, and points a little inside a carriageway slide to the kerb; front doors, slots and bike-hoop rows face / run along the nearest street. The old every-7-m procedural bins, bollards and bike racks are gone (lamps stay procedural: OSM has no street lamps in this tile, and they switch off automatically once `highway=street_lamp` nodes exist). Small items are LOD-culled beyond 450 m from the spawn; hydrants, post boxes, cabinets and flagpoles are kept tile-wide. Everything is merged into one mesh per material ([`blender/clutter_blender.py`](blender/clutter_blender.py)).

**Chimneys and roof plant:** [`cityview/rooftop.py`](cityview/rooftop.py) puts brick stacks where terraced houses have them (gable: on the ridge near the party walls, mirrored when there are two; hip: near the apex; mansard: on the flat top), each seeded by building id and kept inside the footprint. Flat roofs get a stair head (roofs >= 140 m²), air-handling units, and near the spawn a vent stack and the occasional aerial. LOD: the skyline ring (beyond ~95 m) gets shaft + cap only; corbelled course, terracotta pots, vents and aerials are near-spawn. All of it is merged into five meshes for the tile.

**Road ironwork:** [`cityview/roadware.py`](cityview/roadware.py) lays cast-iron manhole covers (every ~42 m, in the lane, off the centre dashes) and kerbside gully grates (every ~26 m, alternating sides, long side along the road) on driveable streets within 200 m of the spawn. These are not surveyed in OSM, so they are a deterministic infrastructure rhythm: kept clear of road ends, junction mouths (via the kerb carriageway index) and tram beds, capped at 220 items, merged into two meshes ([`blender/roadware_blender.py`](blender/roadware_blender.py)).

**Courtyard walls, hedges and fences (OSM-mapped):** [`cityview/barriers.py`](cityview/barriers.py) turns the `barrier=wall|retaining_wall|hedge|fence` ways in the cached OSM tile (~14 km of line work that used to be ignored) into plot-boundary walls, hedges and fences, so block interiors read as back gardens and courtyards instead of a flat void behind the facades. Heights follow `height=*` when mapped (wall 1.8 m, retaining wall 1.0 m, hedge 1.3 m, fence 1.2 m otherwise), `material=*` picks brick / concrete / stone / render (unmapped = neutral render, no guessing), gates and underground ways are skipped. Every way is sampled every 0.8 m and only visible stretches survive: stretches inside or hugging (<= 0.3 m) a building footprint, on a carriageway or on a tram bed are cut out, so a wall crossing a house becomes the two runs either side. Walls (with a coping slab) are tile-wide; hedges and fences are LOD-culled beyond 450 m of the spawn. Nothing is invented: ~11.9 km of runs, ~1,000 prisms, merged into one mesh per material ([`blender/barriers_blender.py`](blender/barriers_blender.py)). Balconies were checked and skipped: this OSM tile has no `balcony=*` / `building:part=balcony` data, and it has no `highway=street_lamp` nodes either, so procedural lamps stay.

**Parked cars (OSM-mapped, not invented):** [`cityview/parking.py`](cityview/parking.py) draws a static parked car only where OSM tags kerbside parking on that side of the way (`parking:both` / `:left` / `:right` = `lane`, `street_side`, `on_kerb`, `half_on_kerb`, `yes`; parallel orientation only). Untagged ways, `parking:*=no` sides and perpendicular / diagonal bays get none. The old builder put a box car on both kerbs of every street within 150 m of the spawn regardless of tags, inside the lane the runtime traffic drives in, so they read as a permanent jam. Now cars sit at the kerb edge (clear of the 1.15 m runtime lane), face the right-hand-traffic direction of their side, keep ~6 m off other streets, crossings, signals, transit stops, tram beds (tram-shared streets get none), trees, benches and street clutter, and never overlap each other. ~55% of bays are occupied; meshes are Kenney Car Kit GLBs weighted like Flanders traffic (compact SUVs + hatchbacks first — see [`viewer/cars/`](viewer/cars/)); the same fleet drives in `viewer/traffic.js`.

**Courtyard ground (OSM-mapped):** [`cityview/courtyards.py`](cityview/courtyards.py) replaces the flat gravel plane under yards with the closed areas OSM maps there: surface car parks and forecourts, playgrounds, a pitch, a schoolyard, a terrace, garage courts, building sites, woods, village greens, dog park, and pool / fountain basins (67 areas, ~11 ha in this tile). `surface=*` is honoured where mapped (paving stones, sett, concrete, gravel, grass, artificial turf), otherwise each kind gets a plain default (lots asphalt, play areas rubber, sites bare earth). Street-side / lane / multi-storey / underground / roof parking, `building=*` areas and anything already drawn as a park or water body are skipped; nothing is clipped or invented. Areas are flat polygons a few millimetres apart in five layers (earth < grass < paving < sport < water), all below the carriageway, merged into one mesh per surface ([`blender/courtyards_blender.py`](blender/courtyards_blender.py)); lot asphalt, yard paving and concrete are tinted variants of the existing surface kit, while the rest have their own baked-colour 256 px tiles in `assets/surfaces/` (`python -m cityview.surface_textures --only sett rubber turf dirt forest`): 10 cm granite setts in staggered courses with mossy joints, EPDM playground mats (1 m, hairline seams, sun-faded wear), artificial-turf rolls (2 m, alternating pile, infill showing), compacted site earth (stones, damp patches, dried cracks) and woodland leaf litter over humus. Pitch markings are not drawn (OSM does not record them).

**Trees:** planted at surveyed positions, not on a procedural grid. [`cityview/trees.py`](cityview/trees.py) merges the **Stad Antwerpen Groeninventaris** `boom` layer (municipal tree inventory: one point per managed tree with Latin species and trunk girth; public ArcGIS service, [open data licence](https://www.antwerpen.be/info/gratis-open-data-licentie), © Stad Antwerpen) with OpenStreetMap `natural=tree` / `natural=tree_row` (ODbL). Height, crown width and conifer/columnar shape come from species and girth. Trees inside buildings, on carriageways or on a tram bed (`railclear`) are dropped, and crowns are trimmed back from the tracks. Only parks the survey barely covers get a seeded Poisson-disc fill (`parks_filled` in the build log); shrubs use the same blue-noise sampler. The raw download is cached and committed under [`assets/trees/`](assets/trees/) so CI builds offline; `--refresh` re-downloads it.

**Roof colours (aerial match):** roofs, yards and parks are tuned against a real orthophoto instead of guessed palettes. Source: Digitaal Vlaanderen *Orthofotomozaïek, middenschalig, winteropnamen* (WMS `https://geo.api.vlaanderen.be/OMW/wms`, layer `OMWRGB25VL`, winter 2025, 15 cm; free under the [Gebruiksrecht geografische webdiensten](https://www.vlaanderen.be/digitaal-vlaanderen/onze-oplossingen/geografische-webdiensten/gebruiksrecht-en-privacyverklaring-geografische-webdiensten)). A 2240 px JPEG of the district is committed at [`assets/references/klein-antwerpen/aerial_ortho.jpg`](assets/references/klein-antwerpen/aerial_ortho.jpg) for future matching.

```bash
pip install pillow numpy
python -m cityview.aerial fetch     # re-download the orthophoto (WMS, 4x4 tiles)
python -m cityview.aerial sample    # per-building roof family + tint -> assets/styles/roof_aerial.json
```

[`cityview/aerial.py`](cityview/aerial.py) draws every OSM building footprint (eroded ~1 m) onto the photo and takes the median of its *sunlit* pixels (50th-92nd luma percentile; the shaded slope only reflects blue skylight, so a mild blue-cast correction is applied to grey roofs). A building with >= 6 % clearly red/orange pixels is a clay pantile roof; other pitched roofs are slate (dark) or zinc / fibre-cement (light grey); OSM `flat` roofs keep bitumen/gravel. Per family the colours are k-means clustered into 5 tints; `roof_aerial.json` stores each building's family + cluster, so the roof you see from above is the roof in the photo. Measured mix for pitched roofs: ~36 % slate, ~56 % zinc/light grey, ~8 % red clay (the old gable/hip table had ~50 % clay). The four roof textures are bright neutral detail maps (glTF Base Color factors are <= 1) and the tint carries the colour; `RENDER_GAIN` maps aerial colour to albedo for the viewer lighting. Yard (`ground`) and park tints in `blender/build_city.py` come from the same photo.

To re-check a build against the photo, serve the repo and open `scripts/topdown_probe.html?glb=../viewer/klein_antwerpen.glb` (same lights, tone mapping and fog as the viewer, top-down), save `window.__probe.jpeg`, then run `python scripts/compare_roofs.py probe.json out.jpg` for aerial-vs-render colours per roof family, yards and a side-by-side image. After the retune the median roof luminance was within ~2 % of the aerial (0.473 vs 0.464) per family.

**Benches:** surveyed positions with a surveyed or rule-derived facing, no procedural scatter. [`cityview/benches.py`](cityview/benches.py) merges, in priority order: (1) OpenStreetMap `amenity=bench` nodes/ways (ODbL; `direction=*` is the compass bearing a person *sitting* on the bench faces and is used verbatim; `backrest=no` drops the backrest; `access=private` is ignored); (2) the **Stad Antwerpen Groeninventaris** layer *meubilair in parken*, `CATEGORIE='Bank'` (municipal park-furniture inventory, positions only; same open-data licence as the trees); (3) OSM bus stops / tram platforms tagged `bench=yes` (De Lijn shelters), only where no surveyed bench already stands within 6 m. Duplicates within 2 m collapse (OSM first); benches inside a building footprint, on a carriageway (nudged to the kerb when < 2 m deep, else dropped) or on a tram bed are dropped. Benches without a surveyed heading face by rule: **back to a wall ≤ 2.2 m; seat toward a footway/path (not a pedestrian area) ≤ 8 m; back to the road ≤ 4.5 m from the kerb; seat toward the park centre inside a park; seat toward the street when set back ≤ 12 m; shelter benches face the track/carriageway from just behind the pole**. The thresholds were checked against the 18 OSM benches in this tile that carry a surveyed `direction` (rule heading vs. surveyed: 8 within 45°, 13 within 90°, 2 opposite; the sample is small and the thresholds were tuned on it, so treat the rules as a plausible default, not ground truth — surveyed headings always win). A fallback bench (max 2 per park, on an existing footway) is only invented in parks ≥ 1800 m² that hold no surveyed bench; the old random park scatter and the every-7-m kerb benches are gone. The municipal download is cached and committed under [`assets/benches/`](assets/benches/); `--refresh` re-downloads it. Known gap: no open street-bench inventory beyond the park-furniture layer was found on the city's public ArcGIS services, so unmapped street benches are not invented.

**Velo Antwerpen:** docking stations from the official Clear Channel SmartBike [GBFS feed](https://gbfs.smartbike.com/antwerp/1.0/gbfs.json) (`station_information`; 323 citywide). [`cityview/velo.py`](cityview/velo.py) caches the tile slice under [`assets/velo/`](assets/velo/), places stations along the nearest street (nudged off the carriageway), and seeds dock occupancy from capacity so CI stays offline — live `station_status` is not polled. Blender builds black dock rails ([`blender/velo_blender.py`](blender/velo_blender.py)); the walk viewer loads `viewer/velo.json` and spawns red city bikes so **E** takes / returns a Velo (same key as tram boarding; bike first when you are at a station or already riding). Rebuild the district GLB after a Velo cache change so rails appear in the tile. `python3 scripts/export_viewer_data.py --refresh` re-downloads GBFS and rewrites `velo.json` without Blender. OSM `amenity=bicycle_rental` nodes are not used (duplicates and metre-scale drift vs GBFS).

```bash
python3 -m cityview city --place centrum
python3 -m cityview city --place eilandje
python3 -m cityview city --bbox 51.218,4.388,51.226,4.405
```

Presets live in `scenes/antwerp_places.json`. Other OSM downloads cache under `assets/osm/` (gitignored except Harmonie).

## Build a side street

```bash
python3 -m cityview build
```

Use another facade photo:

```bash
python3 -m cityview build --photo /path/to/facade.jpg --name my-building
```

Optional UV crop, origin at the bottom-left of the image:

```bash
python3 -m cityview build --photo ./shot.jpg --crop 0.0,0.24,0.80,0.99
```

Outputs land in `output/`:

- `antwerp_street.blend` / `.glb` (street mode)
- `antwerp_harmonie.blend` / `.glb` (district mode)
- preview JPEGs

## GitHub Pages

CI (`.github/workflows/pages.yml`) downloads Blender on Ubuntu, rebuilds `--place klein-antwerpen --no-render`, and deploys `viewer/` (including `klein_antwerpen.glb`).

1. Repo **Settings → Pages → Build and deployment → Source: GitHub Actions**
2. Push to `main` or `klein-antwerpen-2018`, or run the workflow manually
3. Site URL: `https://<org>.github.io/city-view/`

## Whole city LOD strategy

```
OpenStreetMap (now) / GRB + Stad Antwerpen 3D (later)
    → water, roads, building footprints
    → LOD1 extruded blocks for a whole district
    → near-camera tiles swap in procedural rijhuizen + facade photos
```

Do not generate every house in Flanders at street-photo detail. Tile the city (~1 km) and use three levels:

1. **Far** — water and road skeleton. This is what makes it *read* as Antwerp.
2. **Mid** — LOD2 footprints with roof shapes + street-edge procedural facades (`city` command).
3. **Near** — denser facades within ~180 m of the human spawn; photo street generator for hero blocks.

Later upgrades: Flemish **GRB** footprints and the city's own 1 km² GLB/CityGML tiles for real roof heights, then snap facade photos onto street-facing edges.

Edit `scenes/antwerp_side_street.json` for street mode. Styles for the 70s street: `yellow-brick`, `cream-tile`, `white-modern`, `prefab-70s`, `red-brick`, `brown-tile`, `antwerp-70s`.

Historic district styles: `neoclassical`, `eclectic`, `neo-flemish`, `neo-gothic`, `art-nouveau`, `art-deco`, `international`, `modern-infill`.

Special OSM uses become first-class types: `school`, `restaurant`, `supermarket` (brand fascia for Aldi/Lidl/Jumbo/Carrefour), `church`, `hospital`. Amenity/shop nodes are joined onto footprints; named landmarks under [`assets/landmarks/`](assets/landmarks/) are mesh-only (no photo façades): churches use massing presets, and ZAS Sint-Vincentius, Feestzaal Harmonie, Mechelsesteenweg 123, In de Gulden Spoor, the Koning Albertpark bandstand and the Peter Benoit monument are hand-modelled on a shared landmark kit. OSM multipolygon relations are extruded with their courtyard holes; campus outlines (`amenity=hospital/school` without `building=*`) are not extruded.

## Blender MCP

Uses the official Blender Lab server from `~/blender_mcp`, not a third-party fork.

1. Blender 5.1+ (this machine: 5.2.1 LTS)
2. MCP add-on installed and enabled (`scripts/setup_blender_mcp.sh`)
3. **Allow Online Access** in Blender Preferences → System
4. Cursor MCP entry pointing at the local `uv` project:

```json
"blender": {
  "command": "/Users/emielmasyn/.local/bin/uv",
  "args": [
    "--directory",
    "/Users/emielmasyn/blender_mcp/mcp",
    "run",
    "blender-mcp"
  ]
}
```

`$HOME` is not expanded in Cursor MCP JSON — use the absolute path.

Restart the Blender GUI after installing the add-on. Autostart listens on `localhost:9876`. Confirm in Preferences → Add-ons → MCP that the server shows as running. Then reload the Blender MCP server in Cursor Settings.

## Generated façade textures

Walls in the 3D city are real image textures, not flat colours:

1. `assets/generated/facades/facade_01…50.jpg` — **50 image-generated, straight (orthographic, upright, level) Antwerp townhouse elevations**: Art Nouveau, neo-Flemish, neoclassical, brick and stone variety. `assets/generated/walls/` holds six generated seamless wall textures for side walls.
2. `cityview/facade_kit.py` — per façade: storeys, real-world width and building-type tags; plus the layout maths. Each street edge is cut into houses of ~6.4 m; every house gets **one full elevation, ground to eaves, mapped without mirroring** (no flipped repeats, no per-floor band cropping). Neighbouring houses always differ, so a long edge reads as a terrace. Selection scores storey count, horizontal stretch, building-type tags and a seeded jitter.
3. `python -m cityview.facade_textures` (needs `pip install -e .[textures]`) packs them into `assets/textures/facade_atlas.jpg` + `wall_*.jpg`. **These are committed**, so CI only needs Blender.
4. `blender/build_city.py` maps the atlas onto each street façade (`facade_photo_atlas` material) and tiles wall textures on block walls; the glTF export embeds the JPEGs.
5. **Windows, awnings and night** — `python -m cityview.facade_windows` finds the glass in each elevation (dark compact blobs of window proportions) and commits `assets/textures/facade_windows.json` + `facade_emissive.jpg`. Near the spawn, detected windows get 3D relief (granite sill with drip lip, head hood, jamb fins) and wide ground-floor glazing gets a shop awning; the emissive atlas lights a seeded subset of windows from their actual glass pixels, so the glow lines up with the photo. Near the spawn, dark cast-iron **downpipes** (brackets, hopper head, foot shoe) run down party-wall joints between neighbouring houses, thinned to one per ~5 m and kept clear of doors and shop glazing (`facade_kit.downpipes`); distant edges skip all of this relief (LOD).
6. `python3 scripts/inspect_glb_textures.py viewer/klein_antwerpen.glb` proves the GLB contains the images (CI runs it).

## Day / night

The viewer opens on a sunny day. **N** (or the *Night* button; `?night` in the URL starts at night) eases the whole scene to night over ~2 s: dusk-to-night sky gradient with stars and moon, fog, ambient/moon light, glowing façade windows (glTF `emissiveTexture` scaled by time of day), emissive lamp heads with a few point lights pooled on the lamps nearest the walker, car head/tail lamps, and lit tram/bus windows.
