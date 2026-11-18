import json
from pathlib import Path
import sys
from zipfile import ZIP_DEFLATED, ZipFile

package = Path(__file__).resolve().parents[1]
plugin = package / "plugins/paperroom"
runtime = plugin / "runtime"
sys.path.insert(0, str(runtime))
from paperroom_mcp import TOOLS

manifest = json.loads((plugin / ".claude-plugin/plugin.json").read_text())
manifest.update({
    "manifest_version": "0.3",
    "display_name": "Paperroom",
    "description": "Author-led academic writing in Claude Chat. Discuss freely, restate the plan before drafting, and review the rendered manuscript in a local browser.",
    "server": {
        "type": "python",
        "entry_point": "server/paperroom_mcp.py",
        "mcp_config": {
            "command": "/usr/bin/python3",
            "args": ["-B", "${__dirname}/server/paperroom_mcp.py"]
        }
    },
    "tools": [{key: tool[key] for key in ("name","description")} for tool in TOOLS],
    "compatibility": {"platforms": ["darwin"], "runtimes": {"python": ">=3.9.0"}}
})
with ZipFile(package / "packages/Paperroom.mcpb", "w", compression=ZIP_DEFLATED) as archive:
    archive.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
    archive.write(package / "LICENSE", "LICENSE")
    for name in ["paperroom_mcp.py", "paperroom.py", "room_server.py", "room.html", "render_pdf.js"]:
        archive.write(runtime / name, "server/" + name)
