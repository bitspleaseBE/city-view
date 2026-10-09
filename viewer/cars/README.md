# Street cars (Antwerp fleet mix)

Low-poly vehicles for runtime traffic and Blender parked cars. Models are from
**[Kenney Car Kit](https://kenney.nl/assets/car-kit)** (Creative Commons Zero);
see `Kenney_License.txt`.

Weights in `fleet.json` follow recent Flanders / Belgium registration patterns:
compact crossovers and city hatchbacks first, then premium EV / fleet SUVs,
saloons, and a few vans — not licensed replicas of any marque.

| File | Role on Antwerp streets |
|------|-------------------------|
| `suv.glb` | Compact crossover (most common class) |
| `suv-luxury.glb` | Premium / EV crossover |
| `hatchback-sports.glb` | City hatchback |
| `sedan.glb` | Fleet saloon |
| `sedan-sports.glb` | Sportier saloon / coupe |
| `van.glb` | Delivery van |

Replace or re-export:

```bash
# Drop new GLBs into this folder, then edit fleet.json weights / sizes.
# Rebuild the district GLB so parked cars pick up the new meshes.
python3 -m cityview city --place harmonie
```
