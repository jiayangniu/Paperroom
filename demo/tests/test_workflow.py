import sqlite3
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import paperroom as pr


class WorkflowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = pr.connect(Path(self.tmp.name) / "paper.sqlite")
        self.addCleanup(self.db.close)
        self.job = pr.start(self.db, "Introduction", "讨论所得的整体框架", 2, 2, False)

    def submit(self, answer):
        job = pr.get(self.db, self.job["id"])
        return pr.respond(self.db, job["id"], job["version"], answer)

    def test_outline_then_each_paragraph_then_review(self):
        self.assertEqual(self.job["phase"], "outline")
        self.assertRaises(ValueError, self.submit, ["  "])
        self.submit(["先讲问题，再给出证据。"])
        for i in (1, 2):
            pr.plan(self.db, self.job["id"], f"第{i}段讨论")
            self.submit([f"第{i}段中第一句定义问题，第二句解释。"])
        row = pr.get(self.db, self.job["id"])
        self.assertEqual(row["phase"], "ready")
        self.assertEqual(len(row["paragraphs"]), 2)
        def publish():
            current = pr.get(self.db, row["id"])
            return pr.publish(self.db, row["id"], current["version"], b"source", [b"image"])
        publish()
        self.assertRaises(ValueError, self.submit, ["一个意见"])
        self.assertRaises(ValueError, self.submit, ["重复", " 重复 "])
        self.assertEqual(self.submit(["第一段有依据。", "第二段结论需要收窄。"])["phase"], "reviewed")
        publish()
        review = self.submit(["第一段已改好。", "可以删掉最后一句。"])
        self.assertEqual(len(review["drafts"]), 2)
        self.assertEqual(len(review["drafts"][0]["notes"]), 2)

    def test_stale_submission_cannot_advance(self):
        self.submit(["整体逻辑"])
        self.assertRaises(ValueError, pr.respond, self.db, self.job["id"], self.job["version"], ["旧页面"])

    def test_cannot_publish_early_or_skip_paragraph(self):
        self.assertRaises(ValueError, pr.publish, self.db, self.job["id"], self.job["version"], b"src", [b"img"])
        self.assertRaises(ValueError, pr.plan, self.db, self.job["id"], "给第一段的计划")

    def test_targeted_revision_and_shared_state(self):
        one = pr.start(self.db, "Results · 第三段", "已有讨论", 1, 1, True)
        with pr.connect(Path(self.tmp.name)/"paper.sqlite") as other:
            self.assertEqual(pr.get(other, one["id"])["phase"], "paragraph")
            pr.respond(other, one["id"], one["version"], ["第一句陈述观测，最后一句限定适用范围。"])
        self.assertEqual(pr.get(self.db, one["id"])["phase"], "ready")

if __name__ == "__main__":
    unittest.main()
