"""Chat can apply accepted edits to saved paragraph roles without a polish queue."""
import unittest

from test_paper_outline_proposal import Project, SECTIONS
import journal
import outline
import workspace_server


class PolishTests(unittest.TestCase):
    def setUp(self):
        self.paper = Project(self)
        plan = self.paper.propose(SECTIONS)
        self.sid = plan["sections"][1]["id"]
        with self.paper.db() as db:
            outline.adopt(db, self.paper.root, plan["version"])
        self.roles = [{"type": "heading", "title": "Model"}, {"purpose": "Rough first."}, {"purpose": "Rough second."}]

    def submit(self, items):
        with self.paper.db() as db:
            return outline.submit(db, self.paper.root, self.paper.state()["version"], "section", items, section=self.sid)

    def apply(self, version, changes):
        return self.paper.call("apply_section_polish", section=self.sid, version=version, changes=changes)["outline"]

    def test_confirmed_subset_revises_only_selected_roles_and_remains_editable(self):
        plan = self.submit(self.roles)
        p1, p2 = plan["sections"][1]["paragraphs"]
        with self.paper.db() as db:
            for p in (p1, p2):
                plan = outline.submit(db, self.paper.root, plan["version"], "paragraph", ["My own intent."],
                                      section=self.sid, paragraph=p["id"])
        before = plan["sections"][1]
        changes = [dict(paragraph=p2["id"], before=p2["purpose"], purpose="State the rule.")]
        result = self.apply(plan["version"], changes)["sections"][1]
        self.assertEqual(result["paragraphs"][0], before["paragraphs"][0])
        self.assertEqual(result["subheadings"], before["subheadings"])
        second = result["paragraphs"][1]
        self.assertEqual((second["id"], second["purpose"], second["sentences"], second["ready"]),
                         (p2["id"], "State the rule.", ["My own intent."], True))
        self.assertEqual(second["revision"], before["paragraphs"][1]["revision"] + 1)
        with self.paper.db() as db:
            event = journal.export_events(db)[-1]
        logged_changes = [event["disclosed"][c["id"]]["content"] for c in event["commitments"]]
        self.assertEqual((event["kind"], logged_changes), ("section_polish_adopted", changes))
        self.submit([dict(id=p1["id"], purpose=p1["purpose"]), dict(id=p2["id"], purpose="My newer wording.")])
        events = self.paper.events()
        with self.assertRaises(ValueError):
            self.apply(plan["version"], changes)
        self.assertEqual(self.paper.events(), events)
        self.assertEqual(self.paper.state()["sections"][1]["paragraphs"][1]["purpose"], "My newer wording.")

    def test_mismatched_original_missing_duplicate_and_wrong_section_all_rollback(self):
        plan = self.submit(self.roles)
        p1, p2 = plan["sections"][1]["paragraphs"]
        change = dict(paragraph=p1["id"], before=p1["purpose"], purpose="Define the cost.")
        events = self.paper.events()
        for invalid in (dict(change, paragraph="missing"), dict(change, paragraph=p2["id"], before="stale"), change):
            with self.assertRaises(ValueError):
                self.apply(plan["version"], [change, invalid])
        with self.assertRaises(ValueError):
            self.paper.call("apply_section_polish", section=plan["sections"][0]["id"],
                            version=plan["version"], changes=[change])
        self.assertEqual(self.paper.state(), plan)
        self.assertEqual(self.paper.events(), events)

    def test_subheading_polish_retains_position_and_paragraph_revision(self):
        plan = self.submit(self.roles)
        sec = plan["sections"][1]
        with self.paper.db() as db:
            plan = outline.submit(db, self.paper.root, plan["version"], "paragraph", ["Introduce the cost."],
                                  section=self.sid, paragraph=sec["paragraphs"][0]["id"])
        sec = plan["sections"][1]
        change = dict(subheading=1, before="Model", title="Growth model")
        for bad in ([change, change], [dict(change, before="stale")], [dict(change, subheading=2)]):
            with self.assertRaises(ValueError):
                self.apply(plan["version"], bad)
            self.assertEqual(self.paper.state(), plan)
        revised = self.apply(plan["version"], [change])["sections"][1]
        self.assertEqual(revised["subheadings"], [{"before": 0, "title": "Growth model"}])
        self.assertEqual(revised["paragraphs"], sec["paragraphs"])
        # A saved heading can exist even before the author has written the first paragraph.
        partial = self.submit([{"type": "heading", "title": "Early plan"}])
        revised = self.apply(partial["version"], [dict(change, before="Early plan")])["sections"][1]
        self.assertFalse(revised["planned"])
        self.assertEqual(revised["paragraphs"], [])

    def test_level_one_updates_adopted_fields_and_keeps_descendant_text(self):
        plan = self.submit(self.roles)
        target = plan["sections"][1]
        pid = target["paragraphs"][0]["id"]
        with self.paper.db() as db:
            plan = outline.submit(db, self.paper.root, plan["version"], "paragraph", ["Introduce the cost."],
                                  section=self.sid, paragraph=pid)
        changes = [dict(section=self.sid, field=field, before=target[field], after=value)
                   for field, value in [("title", "Revised methods"), ("purpose", "Introduce the rule.")]]
        def polish(changes):
            return self.paper.call("apply_paper_polish", version=plan["version"], changes=changes)["outline"]
        for bad in ([changes[0], changes[0]], [changes[0], dict(changes[1], before="wrong")],
                    [dict(changes[0], after="First\nSecond")]):
            with self.assertRaises(ValueError):
                polish(bad)
            self.assertEqual(self.paper.state(), plan)
        result = polish(changes)
        revised = result["sections"][1]
        self.assertEqual(result["sections"][0], plan["sections"][0])
        self.assertEqual((revised["title"], revised["purpose"]), ("Revised methods", "Introduce the rule."))
        self.assertTrue(revised["adopted"])
        self.assertTrue(revised["planned"])
        self.assertTrue(revised["paragraphs"][0]["ready"])
        self.assertFalse(revised["paragraphs"][1]["ready"])
        self.assertEqual(revised["subheadings"], target["subheadings"])
        self.assertEqual(revised["paragraphs"][0]["id"], pid)
        self.assertEqual(revised["paragraphs"][0]["sentences"], ["Introduce the cost."])
        self.assertEqual(self.paper.state(), result)
        with self.paper.db() as db:
            ev = journal.export_events(db)[-1]
            self.assertEqual([ev["disclosed"][c["id"]]["content"] for c in ev["commitments"]], changes)

    def test_level_three_cannot_create_intents_and_preserves_permission(self):
        plan = self.submit(self.roles)
        p1, p2 = plan["sections"][1]["paragraphs"]
        def polish(version, changes):
            return self.paper.call("apply_paragraph_polish", version=version, section=self.sid,
                                   paragraph=p1["id"], changes=changes)["outline"]
        change = dict(sentence=2, before="Show the consequence.", after=r"Show $\Delta$ and its sign.")
        with self.assertRaises(ValueError):
            polish(plan["version"], [change])
        with self.paper.db() as db:
            plan = outline.submit(db, self.paper.root, plan["version"], "paragraph",
                                  ["Define the term.", change["before"]], section=self.sid, paragraph=p1["id"])
        revision = plan["sections"][1]["paragraphs"][0]["revision"]
        for invalid in (change, dict(change, sentence=3), dict(change, before="stale", sentence=1)):
            with self.assertRaises(ValueError):
                polish(plan["version"], [change, invalid])
            self.assertEqual(self.paper.state(), plan)
        result = polish(plan["version"], [change])
        changed, other = result["sections"][1]["paragraphs"]
        self.assertTrue(changed["ready"])
        self.assertEqual(changed["revision"], revision + 1)
        self.assertEqual(changed["sentences"], ["Define the term.", change["after"]])
        self.assertEqual(other, p2)
        with self.assertRaises(ValueError):
            polish(plan["version"], [change])
        with self.paper.db() as db:
            ev = journal.export_events(db)[-1]
            self.assertEqual([ev["disclosed"][c["id"]]["content"] for c in ev["commitments"]], [change])
        # A stale paragraph with saved intents can be polished but never becomes ready.
        stale = self.submit([dict(id=p1["id"], purpose="New role."), dict(id=p2["id"], purpose=p2["purpose"])])
        result = polish(stale["version"], [dict(change, before=change["after"], after="State consequence.")])
        self.assertFalse(result["sections"][1]["paragraphs"][0]["ready"])
        self.assertEqual(self.paper.state(), result)

    def test_an_old_pending_request_is_inert_and_left_in_place(self):
        plan = self.submit(self.roles)
        with self.paper.db() as db:
            self.assertIsNone(db.execute("SELECT 1 FROM sqlite_master WHERE name='v2_section_polish'").fetchone())
            db.execute("CREATE TABLE v2_section_polish (section TEXT PRIMARY KEY, details TEXT NOT NULL)")
            old = '{"state":"requested","request_id":"old"}'
            db.execute("INSERT INTO v2_section_polish VALUES (?,?)", (self.sid, old))
            db.commit()
            state = workspace_server.snapshot(db, self.paper.root, self.sid)
            self.assertNotIn("open_polish_requests", state)
            self.assertNotIn("polish", state)
        p1 = plan["sections"][1]["paragraphs"][0]
        self.apply(plan["version"], [dict(paragraph=p1["id"], before=p1["purpose"], purpose="Revised.")])
        with self.paper.db() as db:
            self.assertEqual(db.execute("SELECT details FROM v2_section_polish").fetchone()[0], old)
