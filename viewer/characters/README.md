# Mixamo pedestrian characters

Adobe Mixamo civilians exported with the **Walking** (in-place) clip, converted to GLB for the web viewer.

| File | Character |
|------|-----------|
| `Remy_Walking.glb` | Remy |
| `Amy_Walking.glb` | Amy |
| `James_Walking.glb` | James |
| `Michelle_Walking.glb` | Michelle |
| `Aj_Walking.glb` | Aj |

Re-export / convert:

```bash
# After downloading FBX from Mixamo into this folder as Name_Walking.fbx:
blender --background --python scripts/fbx_to_glb.py -- viewer/characters/*_Walking.fbx
```

Assets are Adobe Mixamo characters; use under Mixamo’s license terms.
