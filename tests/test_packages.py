import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


builder = load_module("release_builder", ROOT / "scripts/build_packages.py")
installer = load_module("release_installer", ROOT / "install.py")


def rpc(command, cwd):
    calls = [
        {"id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
        {"id": 2, "method": "tools/list"},
    ]
    wire = "".join(json.dumps(dict(jsonrpc="2.0", **call)) + "\n" for call in calls)
    proc = subprocess.run(command, input=wire, cwd=cwd, text=True, capture_output=True, timeout=15, check=True)
    return [json.loads(line)["result"] for line in proc.stdout.splitlines()]


class ReleaseTests(unittest.TestCase):
    def test_extracted_demo_prepares_a_rendered_section(self):
        if os.name != "posix" or not shutil.which("unzip"):
            self.skipTest("The double-click launcher uses POSIX executable permissions.")
        if sys.platform != "darwin" and not shutil.which("pdftoppm"):
            self.skipTest("Rendering requires pdftoppm or macOS PDFKit.")
        archive = ROOT / "packages" / f"Paperroom-Plugin-{installer.VERSION}.zip"
        with tempfile.TemporaryDirectory(prefix="paperroom extracted demo ") as temporary:
            folder = Path(temporary)
            subprocess.run(["unzip", "-q", str(archive), "-d", str(folder)], check=True)
            distribution = folder / "paperroom-plugin"
            launcher = distribution / "Try-Paperroom.command"
            self.assertTrue(os.access(launcher, os.X_OK))
            self.assertTrue(os.access(distribution / "Enable-Claude-Updates.command", os.X_OK))
            examples = distribution / "demo/examples"
            self.assertEqual({p.name for p in examples.iterdir()}, {"evidence.csv", "intro.tex", "intro.pdf"})
            for link in re.findall(r"\]\(([^)]+)\)", (distribution / "README.md").read_text()):
                if "://" not in link:
                    self.assertTrue((distribution / link).is_file(), link)
            project = folder / "new example project"
            subprocess.run([str(launcher), "--prepare-only", str(project)], cwd=folder, check=True,
                           timeout=45, capture_output=True, text=True)
            self.assertIn("Introduction", (project / "paper.md").read_text())
            with sqlite3.connect(project / ".paperroom/project.sqlite3") as db:
                self.assertEqual(db.execute("SELECT count(*) FROM v2_editions").fetchone()[0], 1)
                self.assertGreater(db.execute("SELECT count(*) FROM v2_pages").fetchone()[0], 0)

    @unittest.skipUnless(os.name == "posix", "The Finder launcher targets macOS.")
    def test_update_command_runs_after_downloading_only_that_file(self):
        archive = ROOT / "packages" / f"Paperroom-Plugin-{installer.VERSION}.zip"
        name = "Enable-Claude-Updates.command"
        with tempfile.TemporaryDirectory(prefix="paperroom downloaded file ") as temporary:
            root = Path(temporary)
            downloads = root / "Downloads"
            downloads.mkdir()
            command = downloads / name
            with ZipFile(archive) as zipped:
                entry = zipped.getinfo("paperroom-plugin/" + name)
                command.write_bytes(zipped.read(entry))
                command.chmod((entry.external_attr >> 16) & 0o777)
            self.assertEqual(command.read_bytes(), (ROOT / name).read_bytes())
            self.assertTrue(os.access(command, os.X_OK))
            work = root / "unrelated working directory"
            work.mkdir()
            home = root / "temporary home"
            home.mkdir()
            binaries = root / "bin"
            binaries.mkdir()
            (binaries / "python3").symlink_to(sys.executable)
            # No Claude executable or repository files are available to the launcher.
            env = {"HOME": str(home), "PATH": str(binaries), "CLAUDE_CONFIG_DIR": str(root / "profile")}
            for invocation in ([str(command)], ["/bin/sh", str(command)]):
                with self.subTest(invocation=invocation):
                    run = subprocess.run(invocation, cwd=work, env=env, capture_output=True, text=True, timeout=10)
                    self.assertNotEqual(run.returncode, 0)
                    self.assertIn("未找到 Claude Code", run.stdout + run.stderr)
            self.assertEqual(list(downloads.iterdir()), [command])

    def test_bundles_start_from_extracted_paths_and_ship_the_same_ui(self):
        with tempfile.TemporaryDirectory(prefix="paperroom packaging ") as temporary:
            destination = Path(temporary)
            names = builder.build(destination)
            extension = destination / "Paperroom.mcpb"
            initial = {name: (destination / name).read_bytes() for name in names}
            builder.build(destination)
            self.assertEqual(initial, {name: (destination / name).read_bytes() for name in names})
            for name in names:
                with ZipFile(ROOT / "packages" / name) as shipped, ZipFile(io.BytesIO(initial[name])) as expected:
                    self.assertEqual(shipped.namelist(), expected.namelist())
                    for member in expected.namelist():
                        self.assertEqual(shipped.read(member), expected.read(member),
                                         f"{name}: rebuild {member} with scripts/build_packages.py")
            with ZipFile(extension) as archive:
                archive.extractall(destination / "chat")
            with ZipFile(io.BytesIO(initial["Paperroom-Plugin-" + installer.VERSION + ".zip"])) as archive:
                launch_mode = archive.getinfo("paperroom-plugin/plugins/paperroom/runtime/paperroom_mcp.py").external_attr >> 16
                self.assertTrue(launch_mode & 0o111)
                self.assertIsNone(archive.testzip())
                archive.extractall(destination / "code")
            chat = destination / "chat"
            manifest = json.loads((chat / "manifest.json").read_text())
            stdio = manifest["server"]["mcp_config"]
            # Linux developers run this host-side simulation with the same Python
            # interpreter as the build. The actual Desktop launcher targets macOS.
            self.assertEqual(stdio["command"], "/usr/bin/python3")
            args = [arg.replace("${__dirname}", str(chat)) for arg in stdio["args"]]
            chat_hello, chat_tools = rpc([sys.executable, *args], destination)
            plugin = destination / "code/paperroom-plugin/plugins/paperroom"
            config = json.loads((plugin / ".mcp.json").read_text())["mcpServers"]["paperroom"]
            args = [arg.replace("${CLAUDE_PLUGIN_ROOT}", str(plugin)) for arg in config["args"]]
            code_hello, code_tools = rpc([sys.executable, "-B", *args], destination)
            self.assertEqual(chat_hello["serverInfo"], code_hello["serverInfo"])
            self.assertEqual(chat_hello["serverInfo"]["version"], manifest["version"])
            self.assertEqual(chat_tools, code_tools)
            tool_names = {tool["name"] for tool in chat_tools["tools"]}
            self.assertEqual({tool["name"] for tool in manifest["tools"]}, tool_names)
            self.assertTrue({"open_writing_workspace", "publish_section", "save_paragraph_draft"} <= tool_names)
            self.assertTrue({"workspace.html", "workspace_server.py", "outline.py", "section_review.py"}
                            <= {p.name for p in (chat / "server").iterdir()})
            for file in builder.runtime_files():
                relative = file.relative_to(builder.RUNTIME)
                self.assertEqual((chat / "server" / relative).read_bytes(), file.read_bytes())
                self.assertEqual((plugin / "runtime" / relative).read_bytes(), file.read_bytes())

    def test_codex_restores_previous_registration_if_replacement_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            previous = parent / "marketplace-0.2.0"
            destination = parent / "marketplace-0.3.0"
            for file in [".agents/plugins/marketplace.json", ".claude-plugin/marketplace.json"]:
                target = previous / file
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((ROOT / file).read_bytes())
            events = []

            def registry(cli, *args):
                events.append(args)
                if args == ("marketplace", "list", "--json"):
                    return json.dumps({"marketplaces": [{"name": installer.MARKET, "root": str(previous)}]})
                if args == ("marketplace", "add", str(destination)):
                    raise RuntimeError("client declined source")
                return ""

            with patch.object(installer, "output", side_effect=registry), self.assertRaisesRegex(RuntimeError, "declined"):
                installer.register("codex", "codex", destination)
            self.assertEqual(events[-1], ("marketplace", "add", str(previous)))

    def test_custom_catalog_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            previous = parent / "marketplace-0.2.0"
            catalog = previous / ".agents/plugins/marketplace.json"
            catalog.parent.mkdir(parents=True)
            catalog.write_text(json.dumps({"name": installer.MARKET, "plugins": [{"name": "paperroom"}, {"name": "user-tool"}]}))
            self.assertFalse(installer.previous_source(previous, parent))
            self.assertFalse(installer.previous_source(parent / "other-catalog", parent))
