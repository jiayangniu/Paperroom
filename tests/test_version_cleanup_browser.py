"""The author can compact the version reader without invalidating old review links."""
from pathlib import Path
import shutil
import tempfile
import unittest

from test_document_reader import Paper, TEXTS, chrome, serve
import i18n


def seed_manuscript(project):
    paper = Paper(project)
    i18n.set_language(project, "zh")
    paper.original(2, 1, 2, TEXTS)
    for number in range(1, 5):
        answers = ([{"note": 1, "status": "changed", "text": "Clarified the original scope."}]
                   if number == 2 else None)
        paper.save(2, 1, 2, [*TEXTS[:2], f"Result {number}."], label=f"Run {number}", responses=answers)
        if number in (1, 4):
            paper.review(number, [{"kind": "keep", "page": 1, "text": f"Note on Run {number}."}])
    return paper


class VersionCleanupBrowser(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node") and chrome(), "Needs Node.js and Chrome.")
    def test_cleanup_and_save_with_old_links_and_reviews(self):
        with tempfile.TemporaryDirectory(prefix="paperroom-cleanup-") as folder:
            project = Path(folder) / "paper"
            project.mkdir()
            paper = seed_manuscript(project)
            run = serve(project, "cleanup.mjs", "cleanup")
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            paper.save(2, 1, 2, [*TEXTS[:2], "Final result."], label="Next draft",
                       responses=[{"note": 1, "status": "kept", "text": "Kept the reviewed result."}])
            run = serve(project, "cleanup.mjs", "next-version")
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
