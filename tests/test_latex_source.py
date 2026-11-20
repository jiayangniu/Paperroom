"""Reading sections and paragraphs from the paper's own LaTeX files."""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins/paperroom/runtime"))
import latex_source as L


MAIN = r"""\documentclass{article}
\begin{document}
\section{Introduction} % opening
\label{sec:intro}
First paragraph line one
continues here. % a remark

\begin{figure}
Caption-like text.

\caption{A figure}
\end{figure}

Second paragraph with
\[
 y = 1
\]
and its tail.
% Commented paragraph that is not prose.

\subsection{Detail}
Third paragraph.
\clearpage
中文第四段。

\input{parts/extra}
\section{Results}
Not the introduction.
\end{document}
"""


class LatexSourceTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.project = Path(folder.name).resolve()
        (self.project / "parts").mkdir()
        (self.project / "main.tex").write_text(MAIN, encoding="utf-8")
        (self.project / "parts/extra.tex").write_text("Fifth paragraph from an input file.\n")

    def test_paragraphs_follow_blank_lines_and_skip_floats_and_comments(self):
        section = L.section(self.project, "introduction")
        texts = [p["text"] for p in section.paragraphs]
        self.assertEqual(len(texts), 5)
        self.assertEqual(texts[0], "First paragraph line one\ncontinues here.")
        self.assertIn("y = 1", texts[1])
        self.assertTrue(texts[1].endswith("and its tail."))
        self.assertEqual(texts[2:4], ["Third paragraph.", "中文第四段。"])
        self.assertEqual(section.where(section.paragraphs[4]), "parts/extra.tex:1")
        self.assertEqual(section.where(), "main.tex:3")
        by_label = L.section(self.project, "Renamed in outline", {"label": "sec:intro"})
        self.assertEqual(len(by_label.paragraphs), 5)

    def test_markers_wrap_the_section_without_touching_its_source(self):
        section = L.section(self.project, "Introduction")
        marked = section.marked()
        self.assertIn(L.START_MARK, marked.split("\\label{sec:intro}")[0])
        self.assertLess(marked.index(L.END_MARK), marked.index("\\section{Results}"))
        self.assertNotIn("paperroom", section.source())
        self.assertEqual(L.marked_pages("%paperroom-start 3\n%paperroom-end 4\n"), ("3", "4"))

    def test_include_keeps_its_page_breaks_and_subfile_only_its_body(self):
        (self.project / "parts/ch.tex").write_text("\\section{Chapter}\nBody.\n")
        (self.project / "parts/sub.tex").write_text(
            "\\documentclass[../main.tex]{subfiles}\n\\begin{document}\n\\section{Sub}\nSub body.\n\\end{document}\n")
        (self.project / "main.tex").write_text(
            "\\documentclass{article}\n\\begin{document}\n\\include{parts/ch}\n\\subfile{parts/sub}\n\\end{document}\n")
        lines = [raw for raw, _, _ in L.expand(self.project, self.project / "main.tex")]
        self.assertEqual(lines[2:6], ["\\clearpage", "\\section{Chapter}", "Body.", "\\clearpage"])
        self.assertEqual(lines.count("\\documentclass[../main.tex]{subfiles}"), 0)
        self.assertEqual([p["text"] for p in L.section(self.project, "Sub").paragraphs], ["Sub body."])

    def test_missing_ambiguous_and_absent_sources(self):
        with self.assertRaisesRegex(L.SourceError, "没有找到"):
            L.section(self.project, "Discussion")
        (self.project / "other.tex").write_text(MAIN)
        (self.project / "main.tex").rename(self.project / "draft.tex")
        with self.assertRaisesRegex(L.SourceError, "多个主"):
            L.section(self.project, "Introduction")
        self.assertEqual(len(L.section(self.project, "Introduction", {"main": "other.tex"}).paragraphs), 5)
        empty = tempfile.TemporaryDirectory()
        self.addCleanup(empty.cleanup)
        self.assertIsNone(L.section(empty.name, "Introduction"))

    def test_whole_paragraph_threshold(self):
        old = "We compare a screening rule with an unscreened search in three paired runs of the solver."
        self.assertFalse(L.is_whole_paragraph(old, old.replace("three", "four")))
        self.assertTrue(L.is_whole_paragraph("", " ".join(["word"] * 25)))
        # Very short replacements stay below the size threshold.
        self.assertFalse(L.is_whole_paragraph("Short one.", "Entirely different words here."))
        rewritten = ("Screening is assessed through a cost model whose parameters come from earlier "
                     "benchmarks rather than from any of the paired runs that follow in this paper.")
        self.assertTrue(L.is_whole_paragraph(old, rewritten))
        # CJK characters count as half a word each.
        self.assertFalse(L.is_whole_paragraph("", "中" * 30))
        self.assertTrue(L.is_whole_paragraph("", "中" * 41))


if __name__ == "__main__":
    unittest.main()
