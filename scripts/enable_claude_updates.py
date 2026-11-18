"""Compatibility entry point for the standalone Claude Code update launcher."""
from pathlib import Path
import runpy

_launcher = Path(__file__).resolve().parents[1] / "Enable-Claude-Updates.command"
_api = runpy.run_path(str(_launcher), run_name=__name__)
migrate = _api["migrate"]
main = _api["main"]
