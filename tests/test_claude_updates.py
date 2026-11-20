"""Regressions for migrating an installed Paperroom marketplace without uninstalling it."""
from importlib.machinery import SourceFileLoader
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
loader = SourceFileLoader("paperroom_claude_updates", str(ROOT / "Enable-Claude-Updates.command"))
spec = importlib.util.spec_from_loader(loader.name, loader)
updates = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updates)
VERSION = json.loads((ROOT / "plugins/paperroom/.claude-plugin/plugin.json").read_text())["version"]
MARKET = "paperroom-local"
PLUGIN = "paperroom@paperroom-local"
URL = "https://github.com/jiayangniu/Paperroom.git"
BRANCH = "main"
REMOTE = {"source": "git", "url": URL, "ref": BRANCH}
EARLIER = {"source": "git", "url": URL, "ref": "v2-author-workspace"}
UNRELATED = {"source": {"source": "github", "repo": "example/other-market"}, "autoUpdate": False}


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


class ClaudeProfile:
    """A native user registration and a settings file owned by the test."""

    def __init__(self, root):
        self.config = root / ".claude"
        self.local = root / ".local/share/paperroom"
        self.old = self.local / "marketplace-0.3.0"
        self.checkout = self.config / "plugins/marketplaces" / MARKET
        self.settings = self.config / "settings.json"
        self.directory_source = {"source": "directory", "path": str(self.old)}
        self.source = self.directory_source.copy()
        self.commands = []
        self.block = None
        self.installed = {"id": PLUGIN, "scope": "user", "enabled": True, "version": "0.3.0"}
        for folder, version in [(self.old, "0.3.0"), (self.checkout, VERSION)]:
            for name in (".claude-plugin/marketplace.json", ".agents/plugins/marketplace.json"):
                dest = folder / name
                dest.parent.mkdir(parents=True)
                shutil.copyfile(ROOT / name, dest)
            manifest = {"name": "paperroom", "version": version}
            write_json(folder / "plugins/paperroom/.claude-plugin/plugin.json", manifest)
        write_json(self.settings, {
            "theme": "dark",
            "enabledPlugins": {PLUGIN: True, "helper@other-market": True},
            "extraKnownMarketplaces": {
                MARKET: {"source": self.source.copy(), "autoUpdate": False}, "other-market": UNRELATED,
            },
        })

    def values(self):
        return json.loads(self.settings.read_text(encoding="utf-8"))

    def run_cli(self, cli, *args):
        self.commands.append(args)
        if args[:2] == ("marketplace", "list"):
            location = self.old if self.source["source"] == "directory" else self.checkout
            return json.dumps([dict(self.source, name=MARKET, installLocation=str(location))])
        if args[0] == "list":
            return json.dumps([self.installed])
        if args[:2] == ("marketplace", "add"):
            source = {URL + "#" + BRANCH: REMOTE, URL + "#v2-author-workspace": EARLIER}.get(args[2], self.directory_source)
            settings = self.values()
            declared = settings["extraKnownMarketplaces"].get(MARKET, {}).get("source")
            if declared is not None and declared != source:
                raise RuntimeError("configured marketplace source does not match")
            if source == REMOTE and self.block == "add":
                raise RuntimeError("could not fetch private marketplace")
            self.source = source.copy()
            # Claude 2.1.326 rewrites the market entry and drops its previous autoUpdate.
            settings["extraKnownMarketplaces"][MARKET] = {"source": self.source.copy()}
            write_json(self.settings, settings)
        elif args[0] == "update":
            if self.block == "update":
                # An unrelated choice saved by another client while the process was running.
                settings = self.values()
                settings["language"] = "zh-CN"
                write_json(self.settings, settings)
                raise RuntimeError("plugin update failed")
            self.installed["version"] = VERSION if self.source == REMOTE else "0.3.0"
        elif args[:2] != ("marketplace", "update"):
            raise AssertionError(f"unexpected native action: {args}")
        return ""


class UpdateMigrationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="paperroom-upgrade-test-")
        self.addCleanup(temp.cleanup)
        self.profile = ClaudeProfile(Path(temp.name))

    def migrate(self):
        profile = self.profile
        with patch.object(updates, "plugin_command", side_effect=profile.run_cli):
            updates.migrate("isolated-claude", profile.config, profile.local)

    def assert_other_settings(self):
        value = self.profile.values()
        self.assertEqual(value["theme"], "dark")
        self.assertEqual(value["extraKnownMarketplaces"]["other-market"], UNRELATED)
        self.assertTrue(value["enabledPlugins"]["helper@other-market"])

    def test_legacy_user_install_upgrades_and_can_be_run_twice(self):
        profile = self.profile
        self.migrate()
        self.assertEqual(profile.source, REMOTE)
        self.assertEqual(profile.installed, {"id": PLUGIN, "scope": "user", "enabled": True, "version": VERSION})
        self.assertEqual(profile.values()["extraKnownMarketplaces"][MARKET], {"source": REMOTE, "autoUpdate": True})
        self.assertTrue((profile.old / ".claude-plugin/marketplace.json").is_file())
        self.assertTrue(profile.values()["enabledPlugins"][PLUGIN])
        self.assert_other_settings()
        self.migrate()
        self.assertTrue(profile.values()["extraKnownMarketplaces"][MARKET]["autoUpdate"])
        switches = [cmd for cmd in profile.commands if cmd[:2] == ("marketplace", "add")]
        self.assertEqual(len(switches), 1)
        self.assert_other_settings()

    def test_versioned_paths_work_for_earlier_and_later_local_releases(self):
        for version in ["0.2.0", "0.3.0", "0.4.1", "2.0.11"]:
            path = self.profile.local / ("marketplace-" + version)
            self.assertEqual(updates.legacy_path({"source": "directory", "path": str(path)}, self.profile.local), path)

    def test_failed_fetch_keeps_previous_registration(self):
        profile = self.profile
        profile.block = "add"
        previous = profile.values()
        with self.assertRaises((ValueError, RuntimeError)):
            self.migrate()
        self.assertEqual(profile.values(), previous)
        self.assertEqual(profile.source, profile.directory_source)
        self.assertEqual(profile.installed["version"], "0.3.0")

    def test_failed_plugin_update_restores_market_and_preserves_concurrent_edits(self):
        profile = self.profile
        profile.block = "update"
        previous = profile.values()["extraKnownMarketplaces"][MARKET]
        with self.assertRaises((ValueError, RuntimeError)):
            self.migrate()
        self.assertEqual(profile.values()["extraKnownMarketplaces"][MARKET], previous)
        self.assertEqual(profile.source, profile.directory_source)
        self.assertEqual(profile.values()["language"], "zh-CN")
        self.assertEqual(profile.installed["version"], "0.3.0")
        self.assert_other_settings()

    def test_same_named_market_from_another_owner_is_left_untouched(self):
        profile = self.profile
        profile.source = {"source": "git", "url": "https://example.test/custom.git", "ref": "main"}
        initial = profile.values()
        initial["extraKnownMarketplaces"][MARKET]["source"] = profile.source.copy()
        write_json(profile.settings, initial)
        with self.assertRaises((ValueError, RuntimeError)):
            self.migrate()
        self.assertEqual(profile.values(), initial)
        for cmd in profile.commands:
            self.assertTrue(cmd[0] == "list" or cmd[:2] == ("marketplace", "list"), cmd)

    def subscribe_to_the_development_branch(self):
        profile = self.profile
        profile.source = EARLIER.copy()
        profile.installed["version"] = "0.6.11"
        settings = profile.values()
        settings["extraKnownMarketplaces"][MARKET] = {"source": EARLIER.copy(), "autoUpdate": True}
        write_json(profile.settings, settings)

    def test_development_branch_subscription_moves_to_main(self):
        profile = self.profile
        self.subscribe_to_the_development_branch()
        self.migrate()
        self.assertEqual(profile.source, REMOTE)
        self.assertEqual(profile.installed["version"], VERSION)
        self.assertEqual(profile.values()["extraKnownMarketplaces"][MARKET], {"source": REMOTE, "autoUpdate": True})
        self.assertIn(("marketplace", "add", URL + "#main", "--scope", "user"), profile.commands)
        self.assert_other_settings()

    def test_failed_move_to_main_keeps_the_development_branch(self):
        profile = self.profile
        self.subscribe_to_the_development_branch()
        profile.block = "add"
        previous = profile.values()
        with self.assertRaises((ValueError, RuntimeError)):
            self.migrate()
        self.assertEqual(profile.values(), previous)
        self.assertEqual(profile.source, EARLIER)
        self.assertEqual(profile.installed["version"], "0.6.11")


    def test_failed_upgrade_after_switching_returns_to_the_development_branch(self):
        profile = self.profile
        self.subscribe_to_the_development_branch()
        profile.block = "update"
        previous = profile.values()["extraKnownMarketplaces"][MARKET]
        with self.assertRaises((ValueError, RuntimeError)):
            self.migrate()
        self.assertEqual(profile.source, EARLIER)
        self.assertEqual(profile.values()["extraKnownMarketplaces"][MARKET], previous)
        self.assertEqual(profile.values()["language"], "zh-CN")
        self.assertIn(("marketplace", "add", URL + "#v2-author-workspace", "--scope", "user"), profile.commands)

if __name__ == "__main__":
    unittest.main()
