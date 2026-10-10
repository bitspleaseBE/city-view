# Mixamo character clips

Adobe Mixamo civilians for the web viewer. Humanoids + animation clips only — vehicle meshes stay procedural (`viewer/micromobility.js`, `viewer/velo.js`, `blender/velo_blender.py`).

| File | Clip |
|------|------|
| `{Name}_Walking.glb` | Rider mesh and textures, plus the in-place walk the rider clips are baked from |
| `{Name}_Riding.glb` | Seated bike pedal loop, hands on the grips (micromobility bikes / cargo) |
| `{Name}_Scooter.glb` | Standing on an e-scooter deck, hands on the grips |
| `{Name}_GetUp.glb` | Face down → push-up → all fours → kneel → stand (source for the Rocketbox get-up) |

Riders: Remy, Amy, James, Michelle. Sidewalk pedestrians use the Rocketbox people below.

## Playable cast (`players/`)

Pieter, Mo and Jacob (never used as pedestrians), each with `_Walking`, `_Riding` and `_Scooter` GLBs:
Pieter (`Male_Adult_07`) and Mo (`Male_Adult_04`) are Rocketbox avatars baked via
`scripts/rocketbox_to_player_glb.py` + `scripts/style_player_textures.py`.
Jacob is a copy of the Mixamo `James` pedestrian (hat + black coat already on the mesh).

## Convert Walking FBX → GLB

```bash
# After downloading FBX from Mixamo into this folder as Name_Walking.fbx:
blender --background --python scripts/fbx_to_glb.py -- viewer/characters/*_Walking.fbx
```

## Bake Riding + Scooter + GetUp from Walking

Pose-baked clips on the Mixamo skeleton (Blender 5 slotted actions): the looping rider poses and
the IK-solved scramble back up after a knock-down. Re-run after replacing Walking assets:

```bash
blender --background --python scripts/bake_mixamo_rider_clips.py            # all
blender --background --python scripts/bake_mixamo_rider_clips.py -- GetUp   # some kinds
```

Assets are Adobe Mixamo characters; use under Mixamo’s license terms.

# Rocketbox people (`people/`)

79 pedestrians (adults, seniors and real child models) built from
[Microsoft Rocketbox](https://github.com/microsoft/Microsoft-Rocketbox) avatars (MIT). Each GLB has
its own baked walk clip; `people/manifest.json` lists `age`, `sex`, `look`, `height` and natural
`walkSpeed`, which `viewer/people.js` uses to put households together and to stream them in.

The roster (`scripts/rocketbox_roster.py`) also defines recoloured variants and the Hasidic
family: a black suit and coat, a wide-brimmed hat, a beard and peyos, a kippah for the boys, and
long skirts. All of these are generated in Blender by `scripts/rocketbox_props.py`.

```bash
python3 scripts/fetch_rocketbox.py                      # ~3.8 GB into assets/rocketbox/ (gitignored)
blender --background --python scripts/build_rocketbox_characters.py              # all
blender --background --python scripts/build_rocketbox_characters.py -- Hasidic_Father  # some
blender --background --python scripts/_render_people_check.py -- /tmp/lineup.png 12 Hasidic_Father Hasidic_Mother
```

Rocketbox has no fall or get-up animation, so `people/getup/<id>.glb` (animation only, ~100 KB)
is the Mixamo `Remy_GetUp.glb` scramble retargeted onto each person: bones matched in world space,
wrists and ankles IK'd to the source's floor heights, and the root raised where a bulkier body or
coat would sink into the paving. Knocked-down pedestrians play it after lying still for a while.
Re-run after rebuilding people:

```bash
blender --background --python scripts/bake_rocketbox_getup.py                  # all
blender --background --python scripts/bake_rocketbox_getup.py -- Male_Adult_15 # some
```
