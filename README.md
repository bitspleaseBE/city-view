<<<<<<< HEAD
# city-view

Antwerp street generation from facade photos.
=======
# City View

Generate a walkable Antwerp side street in Blender from facade photos. The first block is a late-70s / early-80s Flemish rijhuis street: shopfronts, plaster, brick, and black aluminum frames.

There is **no Blender MCP** in this project. Generation runs headless through the local Blender 4.4 binary.

## What you get

- A photo-textured hero building from a street photo
- Procedural neighbors in period Antwerp styles
- Sidewalks, asphalt, lamps, overcast light
- `.blend`, `.glb`, a preview render, and a Three.js viewer

## Requirements

- macOS with Blender at `/Applications/Blender.app` (or set `BLENDER_BIN`)
- Python 3.11+

## Build the street

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

- `antwerp_street.blend`
- `antwerp_street.glb`
- `antwerp_street_preview.jpg`

## View it

```bash
python3 -m cityview serve
```

Open http://127.0.0.1:8765/

## Add buildings

Edit `scenes/antwerp_side_street.json`. A photo building needs a facade image and a crop rectangle. Procedural buildings take `style`, `floors`, `bays`, and `ground` (`shop` or `door`).

Styles: `yellow-brick`, `cream-tile`, `white-modern`, `prefab-70s`, `red-brick`, `brown-tile`, `antwerp-70s`.

## Blender MCP

This session does not expose a Blender MCP server. To drive Blender live from Cursor later, install [blender-mcp](https://github.com/ahujasid/blender-mcp) (addon + `uvx blender-mcp`) and add it to Cursor MCP settings. The CLI path here stays the source of truth for reproducible streets.
>>>>>>> 4d87083 (Add Antwerp 70s-80s street builder from facade photos)
