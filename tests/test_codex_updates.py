import io
import json
from pathlib import Path
import plistlib
import sys
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import install
from scripts import codex_updates as updates


def manifest(number):
    return json.dumps({"name": "paperroom", "version": number}).encode()


def package(number):
    stream = io.BytesIO()
    with ZipFile(stream, "w") as archive:
        for folder in install.FOLDERS:
            for item in (ROOT / folder).rglob("*"):
                if item.is_file() and "__pycache__" not in item.parts and item.name != ".DS_Store":
                    name = item.relative_to(ROOT).as_posix()
                    data = manifest(number) if name.endswith("-plugin/plugin.json") else item.read_bytes()
                    archive.writestr("paperroom-plugin/" + name, data)
        archive.write(ROOT / "LICENSE", "paperroom-plugin/LICENSE")
    return stream.getvalue()


class DailyUpdates(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.parent = self.home / "data"
        self.parent.mkdir()
        self.cli = self.home / "Codex CLI"
        self.local_version = "0.6.17"

    def run_update(self, fetched, enabled=True):
        def local_entry(*unused):
            return {"version": self.local_version, "enabled": enabled}
        with patch.object(install, "installed_entry", side_effect=local_entry), \
                patch.object(install, "register") as apply, \
                patch.object(updates, "fetch", side_effect=fetched) as fetch:
            updates.apply_latest(self.cli, self.parent)
        return apply, fetch

    def test_offline_no_downgrade_no_reenable(self):
        current = self.parent / "marketplace-0.6.17"
        current.mkdir()
        marker = current / "source"
        marker.write_text("preserved")
        for remote, enabled in [("0.6.16", True), ("0.6.17", True), ("0.7.0", False)]:
            with self.subTest(remote=remote, enabled=enabled):
                apply, fetch = self.run_update([manifest(remote)], enabled)
                apply.assert_not_called()
                self.assertEqual(fetch.call_count, 1)
        with self.assertRaises(OSError):
            self.run_update([OSError("offline")])
        self.assertEqual(marker.read_text(), "preserved")

    def test_uses_newer_published_archive_after_matching_manifests(self):
        apply, fetch = self.run_update([manifest("0.6.19"), package("0.6.19")])
        target = self.parent / "marketplace-0.6.19"
        apply.assert_called_once_with("codex", self.cli, target, "0.6.19")
        self.assertTrue((target / updates.MANIFEST).is_file())
        self.assertEqual(fetch.call_args_list[-1].args, ("packages/Paperroom-Plugin-0.6.19.zip",))

    def test_mismatched_release_archive_keeps_old_catalog(self):
        with self.assertRaisesRegex(ValueError, "版本不一致"):
            self.run_update([manifest("0.7.0"), package("0.6.17")])
        self.assertFalse((self.parent / "marketplace-0.7.0").exists())

    def test_job_survives_deleting_download_and_setup_is_idempotent(self):
        target = self.parent / "marketplace-0.6.17"
        running = set()
        mutations = []

        def launchctl(action, name, *args, check=True):
            if action == "print":
                return 0 if running else 1
            mutations.append(action)
            if action == "bootstrap":
                running.add(name)
            elif action == "bootout":
                running.clear()
            return 0

        with patch.object(updates, "launchctl", side_effect=launchctl):
            updates.enable(self.home, ROOT, target, self.cli)
            updates.enable(self.home, ROOT, target, self.cli)
            config = plistlib.loads(updates.plist_path(self.home).read_bytes())
            self.assertEqual(config["StartInterval"], 86400)
            self.assertTrue(config["RunAtLoad"])
            self.assertEqual(config["ProgramArguments"][-1], str(self.cli))
            self.assertEqual(Path(config["ProgramArguments"][1]).parent.parent, target)
            self.assertTrue((target / "scripts/codex_updates.py").is_file())
            self.assertEqual(mutations, ["bootstrap"])
            updates.disable(self.home)
            self.assertFalse(updates.plist_path(self.home).exists())
            self.assertEqual(mutations, ["bootstrap", "bootout"])

    def test_failed_codex_add_restores_old_plugin(self):
        old = install.deploy_source(self.parent, ROOT, "0.6.16")
        new = install.deploy_source(self.parent, ROOT, "0.6.17")
        state = {"source": old, "version": "0.6.16"}
        def output(cli, *args):
            if args[:2] == ("marketplace", "list"):
                return json.dumps({"marketplaces": [{"name": install.MARKET, "root": str(state["source"])}]})
            if args[:2] == ("marketplace", "remove"):
                state["source"] = None
            elif args[:2] == ("marketplace", "add"):
                state["source"] = Path(args[2])
            elif args[0] == "list":
                return json.dumps({"installed": [{"pluginId": install.PLUGIN, "enabled": True,
                                                 "version": state["version"]}]})
            elif args[0] == "add":
                if state["source"] == new:
                    raise RuntimeError("client declined plugin")
                state["version"] = "0.6.16"
            return ""
        with patch.object(install, "output", side_effect=output), self.assertRaisesRegex(RuntimeError, "declined"):
            install.register("codex", self.cli, new, "0.6.17")
        self.assertEqual(state, {"source": old, "version": "0.6.16"})
