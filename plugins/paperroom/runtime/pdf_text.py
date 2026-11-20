"""Read text from the exact PDF excerpt shown to the author, preserving page breaks."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def read_pages(pdf_bytes):
    """Return physical pages in order, including blank pages, or raise ValueError."""
    pdftotext = shutil.which("pdftotext")
    osascript = shutil.which("osascript") if sys.platform == "darwin" else None
    if not (pdftotext or osascript):
        raise ValueError("无法提取审阅 PDF 的文字。请安装 Poppler（pdftotext），或在 macOS 上使用 PDFKit。")
    try:
        with tempfile.TemporaryDirectory() as folder:
            pdf = Path(folder) / "review.pdf"
            pdf.write_bytes(pdf_bytes)
            if pdftotext:
                args = [pdftotext, "-enc", "UTF-8", "-eol", "unix", str(pdf), "-"]
            else:
                script = Path(__file__).with_name("pdf_text.js")
                args = [osascript, "-l", "JavaScript", str(script), str(pdf)]
            result = subprocess.run(args, capture_output=True, check=True, timeout=60)
        output = result.stdout.decode("utf-8")
        if pdftotext:
            # Poppler terminates every physical page with a form feed, even blank ones.
            pages = output.removesuffix("\f").split("\f") if output else []
        else:
            pages = json.loads(output)
        if not isinstance(pages, list) or not pages or not all(isinstance(page, str) for page in pages):
            raise ValueError("无有效页面。")
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise ValueError("无法读取审阅 PDF 的文字层，请检查 PDF 能否正常打开并选择文字。") from exc
    return pages
