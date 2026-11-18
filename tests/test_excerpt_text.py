"""Compare real-world extracted typography and preserve significant manuscript text."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins/paperroom/runtime"))
import excerpt


class ExcerptTextTest(unittest.TestCase):
    def check(self, paragraphs, pages):
        with patch.object(excerpt.pdf_text, "read_pages", return_value=pages):
            excerpt.check(b"captured PDF", [{"text": item} for item in paragraphs])

    def test_typeset_prose_across_pages(self):
        self.check([r"We find \emph{efficient} representations~\cite{liu}.",
                    r"The control achieved 12\%."],
                   ["Results\nWe ﬁnd efﬁcient repre-\n1", "2\nsentations [3].\nThe control achieved 12%."])

    def test_missing_repeated_or_changed_text_is_rejected(self):
        for expected, visible, number in [
                ([r"Effect: -12\%."], ["Effect: 12%."], 1),
                (["Same sentence."] * 2, ["Same sentence."], 2),
                (["First.", "Second."], ["Second. First."], 2),
                (["Final observation."], [""], 1)]:
            with self.subTest(visible=visible), self.assertRaisesRegex(ValueError, f"第 {number} 段"):
                self.check(expected, visible)
