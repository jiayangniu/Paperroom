import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT/"plugins/paperroom/runtime"
sys.path.insert(0, str(RUNTIME))
import paperroom as pr
import paperroom_mcp as mcp


class PluginCases(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.paper = Path(self.temp.name)/"Paper with spaces"
        self.paper.mkdir()
        self.ui = patch.object(mcp, "show_author", return_value={"room_url":"http://127.0.0.1:9889/"})
        self.opened = self.ui.start()
        self.addCleanup(self.ui.stop)

    def tool(self, name, **args):
        return mcp.invoke(name, {"project":str(self.paper), **args})

    def legacy_task(self,title,single=False):
        path = mcp.database_path(self.paper)
        with closing(pr.connect(path)) as db:
            return pr.start(db,title,"Existing discussion",1,3,single)

    def test_status_is_read_only_and_new_papers_are_separate(self):
        with self.assertRaises(ValueError):
            self.tool("writing_status")
        self.assertEqual(list(self.paper.iterdir()), [])
        self.tool("activate_project")
        self.opened.reset_mock()
        first = self.legacy_task("Intro")
        self.tool("begin_writing", title="Intro", reference="Evidence")
        second = Path(self.temp.name)/"Second"
        second.mkdir()
        with self.assertRaises(ValueError):
            mcp.invoke("writing_status", {"project":str(second)})
        self.assertEqual(list(second.iterdir()), [])
        self.assertTrue(self.tool("writing_status", task=first["id"])["id"])
        self.assertEqual(self.opened.call_count, 1)

    def test_legacy_task_reused_and_early_draft_rejected(self):
        dbpath = self.paper/"paperroom_tool/.paperroom/project.sqlite3"
        with closing(pr.connect(dbpath)) as db:
            old = pr.start(db, "Abstract", "legacy", 1, 3, False)
        self.tool("open_writing_workspace")
        same = self.tool("begin_writing", title="Abstract", reference="fresh")
        self.assertEqual(same["id"],old["id"])
        self.assertEqual(same["reference"],"legacy")
        with self.assertRaises(ValueError):
            self.tool("publish_draft",task=old["id"],version=1,tex="draft.tex")
        self.assertFalse((self.paper/".paperroom").exists())

    def test_concurrent_begin_and_author_only_transitions(self):
        self.tool("activate_project")
        self.legacy_task("Results")
        with ThreadPoolExecutor(max_workers=4) as pool:
            outputs=list(pool.map(lambda _: self.tool("begin_writing",title="Results",reference="ref"), range(4)))
        self.assertEqual(len({j["id"] for j in outputs}), 1)
        j=outputs[0]
        path=mcp.database_path(self.paper)
        with closing(pr.connect(path)) as db:
            state=pr.respond(db,j["id"],1,["author logic"])
        new=self.tool("set_paragraph_reference",task=j["id"],version=state["version"],reference="discussed sentences")
        self.assertEqual(new["phase"],"paragraph")
        self.assertFalse(any("respond" in tool["name"] for tool in mcp.TOOLS))

    def test_render_and_revision_path_validation(self):
        self.tool("activate_project")
        started=self.legacy_task("Results P2",single=True)
        with closing(pr.connect(mcp.database_path(self.paper))) as db:
            ready=pr.respond(db,started["id"],1,["my reasoning"])
        path=self.paper/"draft.tex";path.write_text("draft")
        with self.assertRaises(ValueError):
            self.tool("publish_draft",task=ready["id"],version=ready["version"],tex="../outside.tex")
        with patch.object(pr,"render",return_value=[b"PNG"]):
            review=self.tool("publish_draft",task=ready["id"],version=ready["version"],tex="draft.tex")
        self.assertEqual(review["phase"],"review")
        self.assertEqual(review["drafts"][-1]["pages"],1)
        with closing(pr.connect(mcp.database_path(self.paper))) as db:
            done=pr.respond(db,review["id"],review["version"],["一","二","三"])
        self.assertEqual(done["phase"],"reviewed")

if __name__=="__main__": unittest.main()
