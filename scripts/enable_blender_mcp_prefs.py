"""Enable online access and MCP autostart, then save Blender user preferences."""

import bpy

bpy.context.preferences.system.use_online_access = True

addon_keys = list(bpy.context.preferences.addons.keys())
mcp_key = next((key for key in addon_keys if key.endswith(".mcp") or key == "mcp"), None)
if mcp_key is None:
    raise SystemExit("MCP add-on is not enabled")

prefs = bpy.context.preferences.addons[mcp_key].preferences
prefs.use_autostart = True
prefs.host = "localhost"
prefs.port = 9876

bpy.ops.wm.save_userpref()
print("MCP_ADDON:", mcp_key)
print("ONLINE:", bpy.app.online_access)
print("LISTEN:", prefs.host, prefs.port)
