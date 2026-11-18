from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins/paperroom/runtime"))
import pdf_text


class ExtractedPagesTest(unittest.TestCase):
    def test_poppler_preserves_blank_pages_and_a_final_blank_page(self):
        with patch.object(pdf_text.shutil, "which", return_value="/tools/pdftotext"), \
                patch.object(pdf_text.subprocess, "run") as process:
            process.return_value.stdout = "甲\n\f\f乙\n\f\f".encode()
            self.assertEqual(pdf_text.read_pages(b"%PDF-example"), ["甲\n", "", "乙\n", ""])

    def test_without_a_pdf_reader_the_failure_is_explicit(self):
        with patch.object(pdf_text.shutil, "which", return_value=None), \
                self.assertRaisesRegex(ValueError, "pdftotext"):
            pdf_text.read_pages(b"%PDF-example")
