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

Open http://127.0.0.1:8765/ — you spawn at **Gounodstraat 13** at eye height. Click to walk (WASD + mouse look). The tile uses LOD2 roofs (gable / hip / mansard / flat from OSM + style) and style-driven procedural facades on street-facing edges. Colours come from [`assets/styles/klein_antwerpen_2018.json`](assets/styles/klein_antwerpen_2018.json).

Alias: `--place harmonie` uses the same bbox, spawn, and historic style policy. OSM for this tile is cached at [`assets/osm/harmonie.json`](assets/osm/harmonie.json) (committed for reproducible CI).

**Transit:** tram/premetro tracks and bus/tram stops come from OpenStreetMap; De Lijn line numbers come from the official [GTFS static feed](https://data.belgianmobility.io/en/data.html?agency=delijn) (cached under `assets/gtfs/`). Antwerp’s underground service is De Lijn **premetro** (tram in tunnel), not a separate metro. The walk viewer loads `transit.json` for moving trams/buses with line labels. Use `--refresh` to re-download OSM + GTFS.

**Trees:** planted at surveyed positions, not on a procedural grid. [`cityview/trees.py`](cityview/trees.py) merges the **Stad Antwerpen Groeninventaris** `boom` layer (municipal tree inventory: one point per managed tree with Latin species and trunk girth; public ArcGIS service, [open data licence](https://www.antwerpen.be/info/gratis-open-data-licentie), © Stad Antwerpen) with OpenStreetMap `natural=tree` / `natural=tree_row` (ODbL). Height, crown width and conifer/columnar shape come from species and girth. Trees inside buildings, on carriageways or on a tram bed (`railclear`) are dropped, and crowns are trimmed back from the tracks. Only parks the survey barely covers get a seeded Poisson-disc fill (`parks_filled` in the build log); shrubs use the same blue-noise sampler. The raw download is cached and committed under [`assets/trees/`](assets/trees/) so CI builds offline; `--refresh` re-downloads it.

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
5. `python3 scripts/inspect_glb_textures.py viewer/klein_antwerpen.glb` proves the GLB contains the images (CI runs it).
