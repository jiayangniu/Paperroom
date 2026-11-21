"""A fixed launcher opens the workspace without the AI and follows the newest installed Paperroom."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

RUNTIME = Path(__file__).resolve().parents[1] / "plugins/paperroom/runtime"
sys.path.insert(0, str(RUNTIME))
import launcher
import open_workspace
import room


class LauncherTests(unittest.TestCase):
    def setUp(self):
        state = tempfile.TemporaryDirectory()
        self.addCleanup(state.cleanup)
        env = patch.dict(os.environ, {"PAPERROOM_STATE_DIR": state.name})
        env.start()
        self.addCleanup(env.stop)
        self.state = Path(state.name)

    def runtime(self, name):
        folder = self.state / name
        folder.mkdir()
        (folder / "open_workspace.py").write_text("")
        return folder

    def test_refresh_points_at_the_newest_installed_runtime(self):
        old, new = self.runtime("old"), self.runtime("new")
        opener = launcher.refresh("0.6.15", old, python="/usr/bin/python3")
        self.assertTrue(os.access(opener, os.X_OK))
        self.assertIn(str(old / "open_workspace.py"), opener.read_text())
        launcher.refresh("0.6.16", new, python="/usr/bin/python3")
        self.assertIn(str(new / "open_workspace.py"), opener.read_text())
        # An older client starting later does not take the launcher back.
        launcher.refresh("0.6.15", old, python="/usr/bin/python3")
        self.assertIn(str(new / "open_workspace.py"), opener.read_text())
        self.assertEqual(json.loads((self.state / "launcher.json").read_text())["version"], "0.6.16")

    def test_a_removed_newer_runtime_no_longer_holds_the_launcher(self):
        old, new = self.runtime("old"), self.runtime("new")
        launcher.refresh("0.6.16", new)
        (new / "open_workspace.py").unlink()
        opener = launcher.refresh("0.6.15", old)
        self.assertIn(str(old / "open_workspace.py"), opener.read_text())

    def test_project_script_explains_a_missing_launcher(self):
        with tempfile.TemporaryDirectory() as paper:
            script = Path(paper) / "Open.command"
            script.write_text(launcher.project_script())
            run = subprocess.run(["/bin/sh", str(script)], capture_output=True, text=True,
                                 env={**os.environ, "HOME": str(self.state)})
        self.assertEqual(run.returncode, 1)
        self.assertIn("0.6.16", run.stdout)

    def test_open_with_a_folder_starts_its_room_and_the_browser(self):
        with tempfile.TemporaryDirectory() as paper, \
                patch.object(room, "ensure", return_value=47123) as ensure, \
                patch.object(open_workspace.webbrowser, "open") as browser:
            self.assertEqual(open_workspace.main([paper]), 0)
        self.assertEqual(ensure.call_args.args[0], Path(paper).resolve())
        browser.assert_called_once_with("http://127.0.0.1:47123/workspace", new=2)

    def test_without_a_folder_the_only_recent_paper_opens(self):
        with tempfile.TemporaryDirectory() as paper:
            room.write_record(paper, {"project": str(Path(paper).resolve()), "port": 1, "token": "t"})
            with patch.object(room, "ensure", return_value=47124) as ensure, \
                    patch.object(open_workspace.webbrowser, "open"):
                self.assertEqual(open_workspace.main([]), 0)
            self.assertEqual(ensure.call_args.args[0], Path(paper).resolve())


if __name__ == "__main__":
    unittest.main()
