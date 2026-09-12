# City View

Generate a walkable Antwerp side street in Blender from facade photos. The first block is a late-70s / early-80s Flemish rijhuis street: shopfronts, plaster, brick, and black aluminum frames.

Generation can run headless through the local Blender binary, or live through the official Blender Lab MCP add-on (Blender 5.1+).

## What you get

- A photo-textured hero building from a street photo
- Procedural neighbors in period Antwerp styles
- Sidewalks, asphalt, lamps, overcast light
- `.blend`, `.glb`, a preview render, and a Three.js viewer

## Requirements

- macOS with Blender 5.1+ at `/Applications/Blender.app` (or set `BLENDER_BIN`)
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
