"""Exercise the same HTTP forms and stdio tool dispatch that the two clients use."""
import http.client
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

RUNTIME = Path(__file__).resolve().parents[1] / 'plugins/paperroom/runtime'
sys.path.insert(0, str(RUNTIME))
import paperroom_mcp as mcp
import workspace_server as web


class WorkspaceIntegration(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.handler = web.handler_for(web.database_path(self.root), 'author-token', self.root)

    def http(self, path, data=None, *, token='author-token'):
        conn, server = socket.socketpair()
        self.addCleanup(conn.close)
        self.addCleanup(server.close)
        thread = threading.Thread(target=self.handler, args=(server, ('127.0.0.1', 9000), type('LocalServer', (), {'server_port': 8765})()))
        body = json.dumps(data).encode() if data is not None else b''
        method = 'POST' if data is not None else 'GET'
        request = (f'{method} {path} HTTP/1.0\r\nHost: 127.0.0.1:8765\r\nOrigin: http://127.0.0.1:8765\r\n'
                   f'X-Paperroom-Token: {token}\r\nContent-Length: {len(body)}\r\n\r\n').encode()
        thread.start()
        conn.sendall(request + body)
        response = http.client.HTTPResponse(conn)
        response.begin()
        content = response.read()
        thread.join(5)
        self.assertFalse(thread.is_alive())
        return response.status, content

    def tool(self, name, **args):
        return mcp.invoke(name, {'project': str(self.root), **args})

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
        untouched = self.tool('workspace_status')
        self.assertEqual(untouched['outline']['version'], 0)
        self.assertEqual(list(self.root.iterdir()), [])
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

    def test_scope_checks_apply_at_agent_entry_points(self):
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
        with self.assertRaises(ValueError):
            self.tool('publish_section', section=section, expected_revision=0)

    def test_mixed_prose_and_raw_latex_survive_outline_reload(self):
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
        self.assertIn('Private outline rationale', json.dumps(exported['payload']))

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

    def test_chat_can_attach_an_original_without_unlocking_the_section(self):
        self.tool('update_research_assets', question='Why?', evidence='Pilot', version=0)
        _, content = self.http('/api/workspace', dict(action='outline', version=1, level='paper',
                                items=[{'title':'Introduction','purpose':'Present the question'}]))
        section = json.loads(content)['section']
        fixture = RUNTIME.parents[2] / 'demo/examples/intro.pdf'
        with self.assertRaises(ValueError):
            self.tool('import_section_reference', section=section, pdf=str(fixture))
        (self.root / 'paper.pdf').write_bytes(fixture.read_bytes())
        with patch.object(mcp.pr, 'render_document', return_value=(b'%PDF-example', [b'page'])):
            result = self.tool('import_section_reference', section=section, pdf='paper.pdf',
                               title='Existing introduction', pages='1')
        self.assertEqual(result['phase'], 'outlining')
        doc, = result['documents']
        self.assertEqual(self.http(doc['pdf_url']), (200, b'%PDF-example'))
        self.assertEqual(self.tool('workspace_status', section=section)['review']['documents'], [doc])

    def test_open_pinned_review_targets_without_recompiling_or_substituting(self):
        self.tool("update_research_assets", question="Why?", evidence="Pilot", version=0)
        _, body = self.http("/api/workspace", dict(action="outline", version=1, level="paper",
                            items=[{"title":"Method", "purpose":"Explain the rule"}]))
        section = json.loads(body)["section"]
        (self.root / "paper.pdf").write_bytes((RUNTIME.parents[2] / "demo/examples/intro.pdf").read_bytes())
        with patch.object(mcp.pr, "render_document", return_value=(b"%PDF-1", [b"page1"])):
            first = self.tool("import_section_reference", section=section, pdf="paper.pdf", title="First")
        with patch.object(mcp.pr, "render_document", return_value=(b"%PDF-2", [b"page2"])):
            second = self.tool("import_section_reference", section=section, pdf="paper.pdf", title="Second")
        before, after = first["reference_id"], second["reference_id"]
        with patch.object(mcp, "ensure_original", side_effect=AssertionError("unexpected compile")), \
             patch.object(mcp, "show_author", return_value={"room_url":"local"}) as show:
            self.tool("open_writing_workspace", panel="comparison", section=section, before=before, after=after)
            query = show.call_args.kwargs["query"]
            self.assertEqual((query["panel"], query["section"], query["before"], query["after"]),
                             ("comparison", section, before, after))
            for invalid in [{"panel":"comparison", "section":section, "after":"rev-99"},
                            {"panel":"comparison", "section":section, "before":before, "after":before},
                            {"panel":"figures", "build":999}, {"section":section,"revision":999}]:
                with self.assertRaises(ValueError):
                    self.tool("open_writing_workspace", **invalid)
            self.assertEqual(show.call_count, 1)


if __name__ == '__main__':
    unittest.main()
