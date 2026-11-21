"""Hints must stay best-effort on the live workspace and draft-saving paths."""
from contextlib import closing
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins/paperroom/runtime"))
import outline
import paperroom
import paperroom_mcp as mcp
from workspace_server import database_path


class OriginalHintTest(unittest.TestCase):
    def test_optional_scan_does_not_fail_status_or_completed_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.project = Path(tmp).resolve() / "paper"
            self.project.mkdir()
            with closing(paperroom.connect(database_path(self.project))) as db:
                state = outline.update_assets(db, self.project, 0, "Q?", "Experiment.")
                state = outline.submit(db, self.project, state["version"], "paper",
                                       [{"title": "Introduction", "purpose": "Motivation"}])
                section = state["sections"][0]["id"]
                state = outline.submit(db, self.project, state["version"], "section", [{"purpose": "Question"}],
                                       section=section)
                paragraph = state["sections"][0]["paragraphs"][0]["id"]
                state = outline.submit(db, self.project, state["version"], "paragraph", ["Ask the question"],
                                       section=section, paragraph=paragraph)
                revision = state["sections"][0]["paragraphs"][0]["revision"]

            with patch.object(mcp, "show_author", return_value={"room_url": "test"}):
                mcp.invoke("open_writing_workspace", {"project": str(self.project)})

            # Keep a valid match after problem files to ensure failures are per file.
            heading = r"\section{Introduction}"
            for name in ("denied.tex", "vanishing.tex", "valid.tex"):
                (self.project / name).write_text(heading)
            outside = self.project.parent / "outside.tex"
            outside.write_text(heading)
            (self.project / "link.tex").symlink_to(outside)
            loop = self.project / "loop.tex"
            loop.symlink_to(loop.name)
            args = {"project": str(self.project), "section": section}
            original_read = Path.read_text
            def read(path, *args, **kwargs):
                if path.name == "denied.tex":
                    raise PermissionError(path)
                if path.name == "vanishing.tex":
                    path.unlink()
                    raise FileNotFoundError(path)
                self.assertNotEqual(path.resolve(), outside)
                return original_read(path, *args, **kwargs)

            with patch.object(Path, "read_text", read):
                status = mcp.invoke("workspace_status", args)
                self.assertEqual(status["review"]["original_hint"]["files"], ["valid.tex"])
                draft = mcp.invoke("save_paragraph_draft", dict(args, paragraph=paragraph,
                                   plan_revision=revision, expected_version=0, text="What works?"))
                self.assertEqual(draft["original_hint"]["files"], ["valid.tex"])
                persisted = mcp.invoke("workspace_status", args)["review"]["drafts"][paragraph]
                self.assertEqual(persisted["version"], 1)
                self.assertEqual(persisted["text"], "What works?")
