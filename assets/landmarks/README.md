# Landmarks

Named landmarks in Antwerp tiles are mesh-only: geometry plus tiling
brick/stone/slate/render materials — **no facade photographs, billboards or decals**.
See `manifest.json` for OSM id / name matching, survey heights, massing presets
and attribution (reference photos and Inventaris Onroerend Erfgoed entries).

- Churches extrude the OSM volume with pitched roofs, portals and tower/spire
  massing. Heilige Geestkerk: single left square tower + round stair turret
  (`neo_romanesque_tower_left`).
- Entries with `"custom": "<builder>"` are hand-modelled by
  `cityview/landmark_models.py` on the shared kit in `cityview/landmark_kit.py`
  (facade skins, window cells, gables, roofs, turrets). Each has a triangle
  budget (`TRI_BUDGET`). `params` entries ending in `_at` are `[lat, lon]` and
  reach the builder as local `<key>_xy`.
- Those meshes, the Peter Benoit monument, and any entry with `"stream": true`
  (Heilige Geestkerk) are exported as `viewer/landmarks/<osm-id>.glb` (same
  folder Pages serves at `/metropolis/landmarks/`). The city GLB keeps the
  ordinary building as `lmbase_<id>` until that GLB loads; point landmarks keep
  a small `lmhold_<id>` pad. The viewer loads a GLB inside 300 m and drops it
  past 420 m; free view above 190 m camera height shows all of them.
- `"nodes"` places point landmarks (e.g. the Peter Benoit monument) from an
  OSM node.

Custom builders: `zas_vincentius`, `feestzaal_harmonie`, `art_deco_ms123`,
`gulden_spoor`, `gulden_spoor_gate`, `albertpark_kiosk`, `benoit_monument`,
`harmonie_koetshuis`, `benoit_34`, `benoit_38`, `benoit_40`, `bonifacius`,
`heilig_hart`, `heilig_hart_klooster`.
Render street-level checks with
`Blender -b output/antwerp_harmonie.blend --python scripts/render_landmarks.py -- --layout output/antwerp_harmonie_layout.json --tag after`.
