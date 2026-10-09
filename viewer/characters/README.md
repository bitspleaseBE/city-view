# Mixamo character clips

Adobe Mixamo civilians for the web viewer. Humanoids + animation clips only — vehicle meshes stay procedural (`viewer/micromobility.js`, `viewer/velo.js`, `blender/velo_blender.py`).

| File | Clip |
|------|------|
| `{Name}_Walking.glb` | In-place walk (sidewalk pedestrians) |
| `{Name}_Riding.glb` | Seated bike pedal loop (micromobility bikes / cargo) |
| `{Name}_Scooter.glb` | Standing kick-scooter push-step loop |

Characters: Remy, Amy, James, Michelle, Aj.

## Convert Walking FBX → GLB

```bash
# After downloading FBX from Mixamo into this folder as Name_Walking.fbx:
blender --background --python scripts/fbx_to_glb.py -- viewer/characters/*_Walking.fbx
```

## Bake Riding + Scooter from Walking

Pose-baked looping clips on the Mixamo skeleton (Blender 5 slotted actions). Re-run after replacing Walking assets:

```bash
blender --background --python scripts/bake_mixamo_rider_clips.py
```

Assets are Adobe Mixamo characters; use under Mixamo’s license terms.
