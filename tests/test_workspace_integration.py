"""Exercise the same HTTP forms and stdio tool dispatch that the two clients use."""
from contextlib import closing
import io
import zipfile
import http.client
import json
import os
import uuid
from pathlib import Path
import socket
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

RUNTIME = Path(__file__).resolve().parents[1] / 'plugins/paperroom/runtime'
sys.path.insert(0, str(RUNTIME))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import paperroom_mcp as mcp
import versions
import workspace_server as web


class WorkspaceIntegration(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.handler = web.handler_for(web.database_path(self.root), 'author-token', self.root)

    def http(self, path, data=None, *, token='author-token', generation='', origin='http://127.0.0.1:8765'):
        conn, server = socket.socketpair()
        self.addCleanup(conn.close)
        self.addCleanup(server.close)
        thread = threading.Thread(target=self.handler, args=(server, ('127.0.0.1', 9000), type('LocalServer', (), {'server_port': 8765})()))
        body = json.dumps(data).encode() if data is not None else b''
        method = 'POST' if data is not None else 'GET'
        request = (f'{method} {path} HTTP/1.0\r\nHost: 127.0.0.1:8765\r\nOrigin: {origin}\r\n'
                   f'X-Paperroom-Token: {token}\r\nX-Paperroom-Generation: {generation}\r\nContent-Length: {len(body)}\r\n\r\n').encode()
        thread.start()
        conn.sendall(request + body)
        response = http.client.HTTPResponse(conn)
        response.begin()
        content = response.read()
        thread.join(5)
        self.assertFalse(thread.is_alive())
        return response.status, content

    def enroll(self):
        with patch.object(mcp, "show_author", return_value={"room_url": "local"}):
            return self.tool("activate_project")

    def tool(self, name, **args):
        return mcp.invoke(name, {'project': str(self.root), **args})

    def test_workspace_errors_follow_project_language(self):
        for lang, expected in (("en", "The checkpoint changed"), ("zh", "工作区已切换存档")):
            web.i18n.set_language(self.root, lang)
            for path in ("/api/versions/1/pdf?generation=old", "/workspace?revision=1&generation=old"):
                code, body = self.http(path)
                self.assertEqual(code, 409)
                self.assertIn(expected, body.decode())
                if lang == "en":
                    self.assertNotRegex(body.decode(), "[一-鿿]")
            code, body = self.http("/api/checkpoints", token="invalid")
            self.assertEqual(code, 403)
            if lang == "en":
                self.assertNotRegex(body.decode(), "[一-鿿]")

    def test_coauthor_download_roundtrip(self):
        temp = self.root
        self.root = temp / "论文"
        self.root.mkdir()
        self.handler = web.handler_for(web.database_path(self.root), "author-token", self.root)
        with patch.dict(os.environ, {"PAPERROOM_STATE_DIR": str(temp / "state")}):
            self.enroll()
            tex = self.root / "main.tex"
            tex.write_text("old")
            code, snapshot = self.http("/api/checkpoints", {"action":"save", "request_id":uuid.uuid4().hex})
            self.assertEqual(code, 200, snapshot)
            tex.write_text("new")
            self.assertEqual(self.http("/api/workspace", dict(action="assets", version=0,
                                  question="Shared question", evidence="Results"))[0], 200)
            data = {"action":"export"}
            self.assertEqual(self.http("/api/checkpoints", data, token="wrong")[0], 403)
            self.assertEqual(self.http("/api/checkpoints", data, generation="stale")[0], 409)
            for history in (False, True):
                if history:
                    data["include_history"] = True
                code, body = self.http("/api/checkpoints", data)
                self.assertEqual(code, 200, body[:200])
                destination = temp / str(history)
                with zipfile.ZipFile(io.BytesIO(body)) as bundle:
                    bundle.extractall(destination)
                received = destination / self.root.name
                self.assertEqual((received / "main.tex").read_text(), "new")
                self.assertTrue(web.database_path(received).is_file())
                with patch.object(mcp, "show_author", return_value={"room_url": "local"}):
                    status = mcp.invoke("open_writing_workspace", {"project": str(received)})
                self.assertTrue(status["paperroom_selected"])
                self.assertEqual(mcp.invoke("workspace_status", {"project": str(received)})["outline"]["question"], "Shared question")
                self.assertEqual(len(web.archives.listing(received)["archives"]), int(history))
                if history:
                    web.archives.switch(received, json.loads(snapshot)["created"],
                                        request_id=uuid.uuid4().hex, expected_generation="")
                    self.assertEqual((received / "main.tex").read_text(), "old")
            self.assertEqual(tex.read_text(), "new")

    def test_checkpoint_switch_protects_earlier_tabs_and_chat_calls(self):
        temp = self.root
        self.root = temp / "manuscript"
        self.root.mkdir()
        self.handler = web.handler_for(web.database_path(self.root), 'author-token', self.root)
        with patch.dict(os.environ, {"PAPERROOM_STATE_DIR": str(temp / "state")}):
            self.enroll()
            def rpc(action, **payload):
                return {"action": action, "request_id": str(uuid.uuid4()), **payload}

            baseline = dict(action="assets", question="First outline", evidence="First run", version=0)
            self.assertEqual(self.http("/api/workspace", baseline)[0], 200)
            self.assertEqual(self.http("/api/checkpoints", token="wrong")[0], 403)
            save = rpc("save", commit="Initial")
            self.assertEqual(self.http("/api/checkpoints", save, origin="https://other.invalid")[0], 403)
            code, body = self.http("/api/checkpoints", save)
            self.assertEqual(code, 200, body)
            first = json.loads(body)["created"]
            with patch.object(web.archives, "create", side_effect=PermissionError(1, "Operation not permitted", str(self.root.parent))):
                code, body = self.http("/api/checkpoints", rpc("save"))
                self.assertEqual((code, json.loads(body)["code"]), (403, "checkpoint_permission"))
                self.assertIn(str(self.root.parent), json.loads(body)["error"])
            with patch.object(web.archives, "_capture", side_effect=OSError("Disk full")):
                code, body = self.http("/api/checkpoints", rpc("switch", id=first))
                self.assertEqual((code, json.loads(body)["code"]), (409, "safety_copy_failed"))
                self.assertIn("Disk full", json.loads(body)["error"])
            updated = dict(baseline, version=1, question="Revised outline")
            self.assertEqual(self.http("/api/workspace", updated)[0], 200)
            before = self.tool("workspace_status")
            switch = rpc("switch", id=first)
            code, body = self.http("/api/checkpoints", switch)
            self.assertEqual(code, 200, body)
            result = json.loads(body)
            epoch = result["generation"]
            self.assertTrue(epoch)
            # A lost response may be retried from the original generation.
            self.assertEqual(json.loads(self.http("/api/checkpoints", switch)[1])["backup"], result["backup"])
            self.assertEqual(len(json.loads(self.http("/api/checkpoints")[1])["archives"]), 2)
            code, body = self.http("/api/workspace", updated)
            self.assertEqual((code, json.loads(body)["code"]), (409, "checkpoint_switched"))
            self.assertEqual(self.http("/api/outline-draft", {"draft": None})[0], 409)
            self.assertEqual(self.http("/api/versions/1/pdf")[0], 409)
            self.assertEqual(self.http("/workspace?revision=1")[0], 409)
            self.assertEqual(self.http("/workspace?revision=1&generation=" + epoch)[0], 200)
            # Even an otherwise valid version counter from another timeline cannot write.
            mutation = dict(question="Stale chat", evidence="Old", version=1)
            with self.assertRaisesRegex(ValueError, "workspace_status"):
                self.tool("update_research_assets", **mutation)
            now = self.tool("workspace_status")
            self.assertEqual(now["outline"]["question"], "First outline")
            self.assertNotEqual(now["project"], before["project"])
            self.assertEqual(now["generation"], epoch)
            self.assertIn("note", now)
            self.assertEqual(self.http("/api/workspace", updated, generation=epoch)[0], 200)
            self.tool("update_research_assets", question="Continued", evidence="Fresh", version=2)
            code, body = self.http("/api/checkpoints", rpc("switch", id=result["backup"]), generation=epoch)
            self.assertEqual(code, 200, body)
            self.assertEqual(self.tool("workspace_status")["outline"]["question"], "Revised outline")

    def test_standalone_cli_joins_manuscript_locks_and_preserves_custom_databases(self):
        legacy_db = self.root / "paperroom_tool/.paperroom/project.sqlite3"
        custom_db = self.root / "custom.sqlite"
        for target, managed in ((legacy_db, True), (custom_db, False)):
            with self.subTest(target=target), patch.dict(os.environ, {"PAPERROOM_DB": str(target)}), \
                    patch.object(sys, "argv", ["paperroom", "status"]), patch("builtins.print"), \
                    patch.object(web.archives, "workspace_lock", wraps=web.archives.workspace_lock) as locked:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.touch()
                web.pr.main()
                if managed:
                    locked.assert_called_once_with(self.root)
                else:
                    locked.assert_not_called()
                with patch.object(sys, "argv", ["paperroom", "serve"]), patch("room_server.serve") as serve:
                    web.pr.main()
                    serve.assert_called_once_with(target, 8765, True, project=self.root if managed else None)

    def test_get_usage_and_view_prepared_files_before_starting_a_manuscript(self):
        with patch.object(web, "read_snapshot", side_effect=AssertionError("manual opened a manuscript")):
            guide = mcp.invoke("get_usage", {})
        self.assertEqual(guide["version"], mcp.VERSION)
        self.assertIn('panel="figures"', guide["usage"])
        self.assertEqual(list(self.root.iterdir()), [])

        table_dir = self.root / "paperroom-assets/tables"
        table_dir.mkdir(parents=True)
        from test_reference_pdf import two_page_pdf
        pdf = two_page_pdf()
        (table_dir / "table-1.pdf").write_bytes(pdf)
        (table_dir / "table-1.csv").write_text("sample,result\nA,12\n")
        self.enroll()
        status = self.tool("workspace_status")
        self.assertEqual(status["prepared_assets"]["tables"], 1)
        with patch.object(mcp, "ensure_original", side_effect=AssertionError("viewer tried to render prose")), \
                patch.object(mcp, "show_author", return_value={"room_url": "/workspace?panel=figures"}) as opened:
            self.tool("open_writing_workspace", panel="figures")
        self.assertEqual(opened.call_args.kwargs["query"]["panel"], "figures")
        code, listing = self.http("/api/prepared-assets")
        self.assertEqual(code, 200)
        table, = json.loads(listing)["tables"]
        self.assertEqual((table["name"], table["kind"]), ("table-1.pdf", "pdf"))
        self.assertEqual(self.http(table["preview_url"]), (200, pdf))
        self.assertFalse(web.database_path(self.root).exists())

    def test_author_only_forms_and_workspace_routing(self):
        self.enroll()
        untouched = self.tool('workspace_status')
        self.assertEqual(untouched['outline']['version'], 0)
        self.assertFalse(web.database_path(self.root).exists())
        with tempfile.TemporaryDirectory() as other:
            self.assertNotEqual(untouched['project'], web.read_snapshot(Path(other))['project'])
        data = dict(action='assets', version=0, question='When?', evidence='First evidence')
        self.assertEqual(self.http('/api/workspace', data, token='different')[0], 403)
        status, content = self.http('/workspace')
        self.assertEqual(status, 200)
        self.assertIn(b'window.roomToken="author-token"', content)
        self.assertEqual(self.http('/api/workspace', data)[0], 200)
        self.assertEqual(self.http('/api/workspace', data)[0], 409)
        data = dict(action='outline', version=1, level='paper', items=[{'title':'Methods','purpose':'Explain controls'}])
        status, content = self.http('/api/workspace', data)
        self.assertEqual(status, 200)
        section = json.loads(content)['section']
        with patch.object(mcp, 'show_author', return_value={'room_url':'http://localhost/workspace'}) as opened:
            job = self.tool('begin_writing', title='Methods')
            self.assertEqual(job['section'], section)
            self.assertEqual(opened.call_args.kwargs['query'], {'view':'section', 'section':section, 'paragraph':None})
        names = {item['name'] for item in mcp.TOOLS}
        self.assertFalse(names & {'submit_outline', 'submit_review', 'author_action'})
        self.assertEqual(self.tool('workspace_status')['legacy'], [])

    def test_ordinary_save_supports_chat_polish_and_subsequent_author_edits(self):
        self.enroll()
        def submit(**form):
            code, body = self.http("/api/workspace", form)
            self.assertEqual(code, 200, body)
            return json.loads(body)

        submit(action="assets", version=0, question="Which rule?", evidence="Ablation results")
        state = submit(action="outline", version=1, level="paper", items=[
            {"title": "Introduction", "purpose": "Motivation"}, {"title": "Method", "purpose": "Explain rule"}])
        section = state["outline"]["sections"][1]["id"]
        form = dict(action="outline", level="section", section=section)
        state = submit(**form, version=2, items=[{"purpose": "Define cost"}, {"purpose": "Apply rule"}])
        self.assertNotIn("polish", state)
        rows = [{k: p[k] for k in ("id", "purpose")} for p in state["outline"]["sections"][1]["paragraphs"]]
        md = self.root / "paper.md"
        original = md.read_bytes()
        latest = self.tool("workspace_status", section=section)
        self.assertNotIn("open_polish_requests", latest)
        self.assertEqual(md.read_bytes(), original)
        self.tool("apply_section_polish", section=section, version=latest["outline"]["version"],
                  changes=[{"paragraph": rows[1]["id"], "before": rows[1]["purpose"],
                            "purpose": "State the inclusion rule."}])
        state = self.tool("workspace_status", section=section)
        actual = state["outline"]["sections"][1]["paragraphs"]
        self.assertEqual([p["purpose"] for p in actual], ["Define cost", "State the inclusion rule."])
        rows[1]["purpose"] = "Author's next edit."
        state = submit(**form, version=state["outline"]["version"], items=rows)
        self.assertEqual(state["outline"]["sections"][1]["paragraphs"][1]["purpose"], rows[1]["purpose"])

    def test_private_outline_autosave_survives_new_server_without_submitting(self):
        self.enroll()
        project = self.tool("workspace_status")["project"]
        key = f"paperroom-author-v2:/workspace:{project}:section:abc::"
        route = "/api/outline-draft"
        form = {"base": 0, "fields": {"items": [{"purpose": r"先定义 $\Delta=r-p$。"}, {"purpose": ""}]}}
        request = {"key": key, "etag": "", "draft": form}
        self.assertEqual(self.http(route, request, token="wrong")[0], 403)
        self.assertEqual(json.loads(self.http(route + "?key=" + key)[1])["draft"], None)
        self.assertFalse(web.database_path(self.root).exists())
        code, payload = self.http(route, request)
        self.assertEqual(code, 200)
        etag = json.loads(payload)["etag"]
        self.handler = web.handler_for(web.database_path(self.root), "next-token", self.root)
        self.assertEqual(self.http(route + "?key=" + key, token="author-token")[0], 403)
        recovered = json.loads(self.http(route + "?key=" + key, token="next-token")[1])
        self.assertEqual(recovered, {"etag": etag, "draft": form})
        # Another tab's stale autosave or deletion cannot overwrite these words.
        self.assertEqual(self.http(route, request, token="next-token")[0], 409)
        self.assertEqual(self.http(route, {**request, "draft": None}, token="next-token")[0], 409)
        state = self.tool("workspace_status")
        self.assertEqual(state["outline"]["version"], 0)
        self.assertNotIn("Delta", json.dumps(state))
        self.assertEqual(self.http(route, {"key": key, "etag": etag, "draft": None}, token="next-token")[0], 200)
        self.assertIsNone(json.loads(self.http(route + "?key=" + key, token="next-token")[1])["draft"])

    def test_review_draft_survives_handoff_without_publishing_its_notes(self):
        from test_document_reader import Paper, TEXTS
        original = self.root / "first"
        original.mkdir()
        paper = Paper(original)
        paper.save(2, 1, 2, TEXTS)
        self.handler = web.handler_for(web.database_path(original), "author-token", original)
        first_id = web.read_snapshot(original)["project"]
        key = f"paperroom-author-v2:/workspace:{first_id}:review:{paper.intro}::2"
        draft = {"base": 1, "fields": {"notes": [], "entry": {"text": "Unsent review", "page": 2}},
                 "annotationIndex": -1}
        route = "/api/outline-draft"
        code, result = self.http(route, {"etag": "", "draft": draft, "key": key})
        self.assertEqual(code, 200, result)
        etag = json.loads(result)["etag"]
        copied = original.rename(self.root / "coauthor")
        self.handler = web.handler_for(web.database_path(copied), "coauthor-token", copied)
        new_id = web.read_snapshot(copied)["project"]
        key = f"paperroom-author-v2:/workspace:{new_id}:review:::2"
        self.assertNotEqual(first_id, new_id)
        self.assertEqual(self.http(route + "?key=" + key)[0], 403)
        code, result = self.http(route + "?key=" + key, token="coauthor-token")
        self.assertEqual((code, json.loads(result)), (200, {"etag": etag, "draft": draft}))
        self.assertNotIn("Unsent review", json.dumps(web.read_snapshot(copied)))
        self.assertEqual(web.read_snapshot(copied)["versions"][-1]["notes"], [])

    def test_scope_checks_apply_at_agent_entry_points(self):
        self.enroll()
        with self.assertRaises(ValueError):
            self.tool('open_writing_workspace', section='unknown')
        self.tool('update_research_assets', question='Why?', evidence='Controls', version=0)
        status, content = self.http('/api/workspace', dict(action='outline',version=1,level='paper',items=[{'title':'Intro','purpose':'Why'},{'title':'Results','purpose':'Test'}]))
        section = json.loads(content)['section']
        status, content = self.http('/api/workspace', dict(action='outline', version=2, level='section', section=section,items=[{'purpose':'Question'},{'purpose':'Gap'}]))
        self.assertEqual(status, 200)
        p1, p2 = json.loads(content)['outline']['sections'][0]['paragraphs']
        with self.assertRaises(ValueError):
            self.tool('save_paragraph_draft', section=section,paragraph=p1['id'],plan_revision=1,expected_version=0,text='Too soon.')
        status, content = self.http('/api/workspace', dict(action='outline',version=3,level='paragraph',section=section,paragraph=p1['id'],items=['Define stopping.']))
        self.assertEqual(status, 200)
        revision = json.loads(content)['outline']['sections'][0]['paragraphs'][0]['revision']
        saved = self.tool('save_paragraph_draft',section=section,paragraph=p1['id'],plan_revision=revision,expected_version=0,text='We study stopping.')
        self.assertTrue(saved['drafts'][p1['id']]['current'])
        # This project has no .tex: there is no paper to typeset as a version.
        with self.assertRaisesRegex(ValueError, "主 .tex"):
            self.tool('save_version')
        self.assertEqual(self.tool('workspace_status')['versions'], [])

    def test_mixed_prose_and_raw_latex_survive_outline_reload(self):
        self.enroll()
        def submit(level, version, items, **target):
            status, body = self.http('/api/workspace', dict(
                action='outline', level=level, version=version, items=items, **target))
            self.assertEqual(status, 200, body)
            return json.loads(body)

        purpose = r'定义 $\Delta_i = r_i - p_i$，讨论 $r_i > p_i$。'
        intent = (r'先给出 \(\theta_0\)，再比较 $E(A) < E(B)$ 和 $E(A) \ge E(B)$。'
                  '\n' + r'\[ \begin{aligned} a &= b \\ c &= d \end{aligned} \]')
        self.http('/api/workspace', dict(action='assets', version=0, question='Q?', evidence='E.'))
        paper = submit('paper', 1, [dict(title='Method', purpose='Method')])
        section = paper['section']
        plan = submit('section', 2, [dict(purpose=purpose)], section=section)
        paragraph = plan['outline']['sections'][0]['paragraphs'][0]['id']
        submit('paragraph', 3, [intent], section=section, paragraph=paragraph)

        reopened = self.tool('workspace_status', section=section)['outline']
        saved = reopened['sections'][0]['paragraphs'][0]
        self.assertEqual((saved['purpose'], saved['sentences']), (purpose, [intent]))
        self.assertTrue(saved['ready'])
        self.assertIn(purpose, (self.root / 'paper.md').read_text())

    def test_timestamp_history_and_private_export(self):
        route = '/api/timestamps'
        self.assertEqual(json.loads(self.http(route)[1])['events'], [])
        self.assertEqual(self.http(route + '/export', token='wrong')[0], 403)
        self.assertEqual(list(self.root.iterdir()), [])
        self.enroll()
        self.tool('update_research_assets', question='Why?', evidence='Private evidence', version=0)
        form = dict(action='outline', version=1, level='paper',
                    items=[{'title': 'Intro', 'purpose': 'Private outline rationale'}])
        self.assertEqual(self.http('/api/workspace', form)[0], 200)
        event, = json.loads(self.http(route)[1])['events']
        self.assertEqual(event['kind'], 'paper_outline')
        self.assertIsNone(event['receipt'])
        self.assertNotIn('payload', event)
        self.assertNotIn('salt', event)
        status, content = self.http(route + '/export')
        self.assertEqual(status, 200)
        bundle = json.loads(content)
        self.assertEqual(bundle['format'], 'paperroom-timestamps-v1')
        exported, = bundle['events']
        self.assertEqual(exported['digest'], event['digest'])
        self.assertIn('Private outline rationale', json.dumps(exported['disclosed']))

        request = dict(seq=event['seq'], digest=event['digest'])
        with patch.object(web.timestamps.tsa, 'stamp', side_effect=ValueError('机构暂时不可用')) as stamp:
            self.assertEqual(self.http(route, request, token='wrong')[0], 403)
            self.assertEqual(self.http(route, dict(request, digest='0' * 64))[0], 409)
            stamp.assert_not_called()
            self.assertEqual(self.http(route, request)[0], 409)
            stamp.assert_called_once_with(event['digest'])
        self.assertEqual(json.loads(self.http(route)[1])['events'], [event])
        receipt = dict(authority='tsa.example', verified_at='2026-11-18T02:00:00Z',
                       query_der=b'query', reply_der=b'reply')
        with patch.object(web.timestamps.tsa, 'stamp', return_value=receipt) as stamp:
            self.assertEqual(self.http(route, request)[0], 200)
            self.assertEqual(self.http(route, request)[0], 200)
            stamp.assert_called_once_with(event['digest'])
        event, = json.loads(self.http(route)[1])['events']
        self.assertEqual(event['receipt'], {k: receipt[k] for k in ('authority', 'verified_at')})
        exported, = json.loads(self.http(route + '/export')[1])['events']
        self.assertEqual(exported['receipt']['reply_der_b64'], 'cmVwbHk=')

    def test_status_of_an_empty_folder_writes_nothing(self):
        with self.assertRaises(ValueError):
            self.tool('workspace_status')
        self.assertEqual(list(self.root.iterdir()), [])

    def add_version(self, number, page):
        """A saved whole-paper version, stored as save_version stores it, without a compiler."""
        compiled = dict(pdf=b"%PDF-" + page, images=[page], main="main.tex", map={}, texts={}, source_sha256=str(number))
        with closing(mcp.pr.connect(web.database_path(self.root))) as db, db:
            versions.create_tables(db)
            versions._store(db, number, "original" if number == 0 else "version", "", compiled, None)

    def test_open_pinned_versions_without_recompiling_or_substituting(self):
        self.enroll()
        self.tool("update_research_assets", question="Why?", evidence="Pilot", version=0)
        _, body = self.http("/api/workspace", dict(action="outline", version=1, level="paper",
                            items=[{"title":"Method", "purpose":"Explain the rule"}]))
        section = json.loads(body)["section"]
        for number in range(3):
            self.add_version(number, b"page%d" % number)
        self.assertEqual(self.http("/api/versions/1/pages/1"), (200, b"page1"))
        self.assertEqual(self.http("/api/versions/2/pdf")[0], 200)
        self.assertEqual(self.http("/api/versions/3/pages/1")[0], 404)
        with patch.object(mcp, "ensure_original", side_effect=AssertionError("unexpected compile")), \
             patch.object(mcp, "show_author", return_value={"room_url":"local"}) as show:
            self.tool("open_writing_workspace", panel="versions", section=section, mode="compare", before=0, after=1)
            query = show.call_args.kwargs["query"]
            self.assertEqual((query["panel"], query["section"], query["mode"], query["before"], query["after"]),
                             ("versions", section, "compare", 0, 1))
            self.tool("open_writing_workspace", view="review", revision=1)
            self.assertEqual({k: show.call_args.kwargs["query"][k] for k in ("view", "revision")},
                             {"view": "review", "revision": 1})
            for invalid in [{"panel":"versions", "after":2}, {"panel":"versions", "before":1, "after":1},
                            {"panel":"versions", "before":0, "after":9}, {"panel":"figures", "build":999},
                            {"view":"review", "revision":999}, {"panel":"versions", "revision":1},
                            {"before":0, "after":1}]:
                with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                    self.tool("open_writing_workspace", **invalid)
            self.assertEqual(show.call_count, 2)

    def test_browser_cleanup_preserves_chat_version_ids_and_legacy_links(self):
        self.enroll()
        for number in range(5):
            self.add_version(number, f"page {number}".encode())
        form = dict(action="cleanup_versions", numbers=[1, 2, 3],
                    expected_numbers=list(range(5)), expected_notes=[0] * 5)
        self.assertEqual(self.http("/api/workspace", form, token="wrong")[0], 403)
        code, body = self.http("/api/workspace", form)
        self.assertEqual(code, 200, body)
        current = self.tool("workspace_status")
        self.assertEqual(json.loads(body)["versions"], current["versions"])
        self.assertEqual([(v["number"], v["display_number"]) for v in current["versions"]], [(0, 0), (4, 1)])
        self.assertEqual([v["number"] for v in current["archived_versions"]], [1, 2, 3])
        self.assertEqual(self.http("/api/versions/1/pdf")[0], 410)
        self.assertEqual(self.http("/api/versions/1/pages/1")[0], 410)
        self.assertEqual(self.http("/api/versions/4/pdf"), (200, b"%PDF-page 4"))
        self.assertEqual(self.http("/api/versions/4/pages/1"), (200, b"page 4"))
        compiled = dict(pdf=b"%PDF-next", images=[b"next"], main="main.tex", map={}, texts={}, source_sha256="next")
        with patch.object(mcp, "show_author", return_value={"room_url": "local"}) as show, \
             patch.object(versions, "_compile", return_value=compiled):
            self.tool("open_writing_workspace", view="review", revision=1)
            self.assertEqual(show.call_args.kwargs["query"]["revision"], 1)
            self.tool("open_writing_workspace", panel="versions", before=1, after=4)
            self.assertEqual(show.call_args.kwargs["query"]["before"], 1)
            with self.assertRaises(ValueError):
                self.tool("save_version", expected_version=1)
            with self.assertRaisesRegex(ValueError, "expected_version"):
                self.tool("save_version")
            saved = self.tool("save_version", expected_version=4)
            self.assertEqual((saved["saved_version"], saved["display_number"]), (5, 2))
            self.assertEqual((show.call_args.kwargs["query"]["before"], show.call_args.kwargs["query"]["after"]), (4, 5))
            # A deleted most-recent revision leaves a gap between permanent IDs.
            form.update(numbers=[5], expected_numbers=[0, 4, 5], expected_notes=[0, 0, 0])
            self.assertEqual(self.http("/api/workspace", form)[0], 200)
            rebuilt = self.tool("save_version", expected_version=4)
            self.assertEqual((rebuilt["saved_version"], rebuilt["display_number"]), (6, 2))
            self.assertEqual((show.call_args.kwargs["query"]["before"], show.call_args.kwargs["query"]["after"]), (4, 6))

if __name__ == '__main__':
    unittest.main()
