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
  (facade skins, window cells, gables, roofs, turrets). They always get full
  detail, whatever their distance from spawn, and each has a triangle budget
  (`TRI_BUDGET`). `params` entries ending in `_at` are `[lat, lon]` and reach the
  builder as local `<key>_xy`.
- `"nodes"` places point landmarks (e.g. the Peter Benoit monument) from an
  OSM node.

Custom builders: `zas_vincentius`, `feestzaal_harmonie`, `art_deco_ms123`,
`gulden_spoor`, `gulden_spoor_gate`, `albertpark_kiosk`, `benoit_monument`.
Render street-level checks with
`Blender -b output/antwerp_harmonie.blend --python scripts/render_landmarks.py -- --layout output/antwerp_harmonie_layout.json --tag after`.
