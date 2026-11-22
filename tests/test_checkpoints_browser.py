"""Exercise switching local manuscript copies through the author's workspace."""
from pathlib import Path
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from test_document_reader import Paper, chrome, serve


@unittest.skipUnless(shutil.which("node") and chrome(), "Needs Node.js and Chrome.")
class AuthorCheckpoints(unittest.TestCase):
    def test_switch_preserves_current_manuscript_and_unsubmitted_outline(self):
        with tempfile.TemporaryDirectory(prefix="paperroom-checkpoint-browser-") as folder:
            project = Path(folder) / "paper"
            project.mkdir()
            with patch.dict(os.environ, {"PAPERROOM_STATE_DIR": str(Path(folder) / "state")}):
                paper = Paper(project)
                (project / "main.tex").write_text("Manuscript A\n")
                result = serve(project, "checkpoints.mjs", str(project), paper.intro)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual((project / "main.tex").read_text(), "Manuscript B\n")
