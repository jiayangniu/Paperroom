"""The AI can guide the author's next sentence without writing their outline."""
import threading
import unittest

from test_paper_outline_proposal import Project, SECTIONS
import outline
import tex_gate
import workspace_server


class SentenceReferences(unittest.TestCase):
    def setUp(self):
        self.paper = Project(self)
        plan = self.paper.propose(SECTIONS)
        self.sid = plan["sections"][1]["id"]
        with self.paper.db() as db:
            outline.adopt(db, self.paper.root, plan["version"])

    def submit(self):
        with self.paper.db() as db:
            plan = outline.state(db, self.paper.root)
            return outline.submit(db, self.paper.root, plan["version"], "section", [
                {"type": "heading", "title": "Decision"},
                {"purpose": r"Introduce $\Delta=r-p$."}, {"purpose": "Explain the rule."}
            ], section=self.sid)

    def prepare(self):
        return self.paper.call("prepare_sentence_references", section=self.sid)

    def suggestions(self, prepared):
        return [dict(paragraph=pid, sentences=[dict(content=r"Define $\Delta=r-p$.",
                          connection="Tie the new symbol to the decision.")]) for pid in prepared["pending"]]

    def save(self, prepared, refs):
        return self.paper.call("suggest_sentence_references", section=self.sid, basis=prepared["basis"], references=refs)

    def test_all_reference_destinations_keep_author_text_and_allow_revisions(self):
        plan = self.submit()
        pid = plan["sections"][1]["paragraphs"][0]["id"]
        with self.paper.db() as db:
            outline.submit(db, self.paper.root, plan["version"], "paragraph", ["Author's existing intent."],
                           section=self.sid, paragraph=pid)
        paper_md = self.paper.root / "paper.md"
        original = paper_md.read_bytes()
        self.paper.call("suggest_paper_reference", text="Consider the scope.")
        self.paper.call("suggest_paper_reference", text="Lead with the question.")
        self.paper.call("suggest_paper_reference", text="Lead with the question.")
        self.paper.call("suggest_section_plan", section=self.sid, text="Order the two comparisons.")
        prepared = self.prepare()
        self.assertNotIn(pid, prepared["pending"])
        note = {"paragraph": pid, "text": "### Logic\nTie both comparisons to the question."}
        self.save(prepared, [note])
        self.save(prepared, [note])
        state = self.paper.call("workspace_status", section=self.sid)
        self.assertEqual(state["outline"]["hint"]["text"], "Lead with the question.")
        section = state["outline"]["sections"][1]
        self.assertEqual(section["hint"]["text"], "Order the two comparisons.")
        self.assertEqual(section["paragraphs"][0]["sentences"], ["Author's existing intent."])
        self.assertTrue(section["paragraphs"][0]["ready"])
        self.assertEqual(state["sentence_references"]["by_paragraph"][pid],
                         [{"content": note["text"], "connection": ""}])
        with self.assertRaisesRegex(ValueError, "二选一"):
            self.save(prepared, [dict(note, sentences=[])])
        self.assertEqual(self.paper.events().count("paper_hint"), 2)
        self.assertEqual(self.paper.events().count("sentence_reference"), 1)
        self.assertEqual(paper_md.read_bytes(), original)

    def test_wait_receives_new_plan_and_reads_both_inputs(self):
        self.paper.call("suggest_section_plan", section=self.sid, text="Discuss both costs.")
        self.assertEqual(self.prepare()["state"], "awaiting_author")
        writer = threading.Timer(.1, self.submit)
        writer.start()
        try:
            view = self.paper.call("prepare_sentence_references", section=self.sid, wait_seconds=5)
        finally:
            writer.join()
        context = view["context"]
        self.assertEqual(context["section_reference"], "Discuss both costs.")
        self.assertEqual(context["subheadings"], [{"before": 0, "title": "Decision"}])
        self.assertEqual(context["paragraphs"][0]["purpose"], r"Introduce $\Delta=r-p$.")
        self.assertEqual(len(view["pending"]), 2)
        route = self.paper.call("open_writing_workspace", section=self.sid, paragraph=view["pending"][0])
        self.assertNotIn("next_tool", route)
        self.assertNotIn("sentence_references", route)
        state = self.paper.call("workspace_status", section=self.sid)
        self.assertEqual(state["sentence_references"]["by_paragraph"], {})

    def test_suggestions_are_atomic_idempotent_and_never_unlock_prose(self):
        self.submit()
        prepared = self.prepare()
        refs = self.suggestions(prepared)
        with self.assertRaisesRegex(ValueError, "重复"):
            self.save(prepared, [refs[0], refs[0]])
        self.assertEqual(self.prepare()["pending"], prepared["pending"])
        with self.assertRaisesRegex(ValueError, "具体内容"):
            self.save(prepared, [{**refs[0], "sentences": [{"content": "A."}]}])
        src = self.paper.root / "paper.md"
        before = src.read_bytes()
        tool = tex_gate.handle({"hook_event_name": "UserPromptSubmit", "cwd": str(self.paper.root)})
        self.assertIsNone(tool, "Missing references alone must not prompt the assistant to write them.")
        self.save(prepared, refs)
        self.save(prepared, refs)
        self.assertEqual(self.paper.events().count("sentence_reference"), 2)
        self.assertEqual(src.read_bytes(), before)
        self.assertFalse(self.prepare()["pending"])
        state = workspace_server.read_snapshot(self.paper.root, self.sid)
        stored = state["sentence_references"]["by_paragraph"]
        self.assertEqual(stored[refs[0]["paragraph"]], refs[0]["sentences"])
        self.assertFalse(any(p["ready"] for p in state["outline"]["sections"][1]["paragraphs"]))
        with self.assertRaises(ValueError):
            self.paper.call("save_paragraph_draft", section=self.sid, paragraph=refs[0]["paragraph"],
                            plan_revision=1, text="AI draft")

    def test_changes_in_either_source_make_old_references_inapplicable(self):
        self.submit()
        prepared = self.prepare()
        refs = self.suggestions(prepared)
        self.save(prepared, refs)
        self.paper.call("suggest_section_plan", section=self.sid, text="New reference.")
        self.assertNotEqual(self.prepare()["basis"], prepared["basis"])
        with self.assertRaisesRegex(ValueError, "重新读取"):
            self.save(prepared, refs)
        prepared = self.prepare()
        self.save(prepared, refs)
        with self.paper.db() as db:
            plan = outline.state(db, self.paper.root)
            rows = [dict(id=p["id"], purpose=p["purpose"]) for p in plan["sections"][1]["paragraphs"]]
            rows[1]["purpose"] = "The author now chooses an alternative logical order."
            outline.submit(db, self.paper.root, plan["version"], "section", rows, section=self.sid)
        state = workspace_server.read_snapshot(self.paper.root, self.sid)
        self.assertEqual(state["sentence_references"]["by_paragraph"], {})
        self.assertEqual(state["sentence_references"]["earlier_by_paragraph"],
                         {r["paragraph"]: r["sentences"] for r in refs})
        self.assertEqual(len(state["sentence_references"]["pending"]), 2)
        old_pid, other_pid = (r["paragraph"] for r in refs)
        self.save(self.prepare(), [dict(paragraph=old_pid, text="Use the revised argument.")])
        updated = workspace_server.read_snapshot(self.paper.root, self.sid)["sentence_references"]
        self.assertEqual(set(updated["by_paragraph"]), {old_pid})
        self.assertEqual(set(updated["earlier_by_paragraph"]), {other_pid})
