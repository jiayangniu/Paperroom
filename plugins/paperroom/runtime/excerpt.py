"""Check the registered prose against the text layer of the frozen review PDF."""
import re
import unicodedata

import pdf_text


# Curly quotes, ligatures and discretionary line-break hyphens vary across PDF fonts.
QUOTES = str.maketrans({"’": "'", "‘": "'", "”": '"', "“": '"', "\u00ad": ""})
FORMATTING = re.compile(r"\\(?:emph|textbf|textit|textrm|textsf|texttt|textnormal|underline|mbox)(?=\s*\{)")
LAYOUT = re.compile(r"\\(?:newpage|clearpage|noindent|allowbreak)(?![A-Za-z])")
CITATION = re.compile(r"\\(?:cite|citep)\{[^{}]+\}")
PRINTED_CITATION = r"(?:\[[^\[\]]{1,180}\]|\([^()]{1,180}\))"


def compact(text):
    return "".join(unicodedata.normalize("NFKC", text).translate(QUOTES).split())


def paragraph_pattern(tex):
    # Keep unknown commands literal. If a template expands one in a way we cannot
    # verify, report uncertainty instead of silently dropping part of the paragraph.
    tex = re.sub(r"(?<!\\)%[^\n]*", "", tex)
    tex = FORMATTING.sub("", tex)
    tex = LAYOUT.sub(" ", tex).replace(r"\-", "").replace(r"\\", " ")
    tex = re.sub(r"\\label\{[^{}]*\}", "", tex)
    tex = tex.replace("``", '"').replace("''", '"').replace("---", "—").replace("--", "–")
    pieces = CITATION.split(tex)
    literals = []
    for piece in pieces:
        piece = re.sub(r"(?<!\\)[{}$~]", "", piece)
        piece = re.sub(r"\\([%$&#_{} ])", r"\1", piece)
        literals.append(compact(piece))
    if not any(literals):
        return None
    return re.compile(PRINTED_CITATION.join(re.escape(value) for value in literals))


def check(captured, paragraphs):
    pages = pdf_text.read_pages(captured)
    # Page numbers outside the body break prose that continues onto the next page.
    # Try the original as well, so a standalone number in the manuscript is kept.
    raw = "\n".join(pages)
    trimmed = []
    for page in pages:
        lines = page.strip().splitlines()
        if lines and lines[0].strip().isdigit():
            lines = lines[1:]
        if lines and lines[-1].strip().isdigit():
            lines = lines[:-1]
        trimmed.extend(lines)
    candidates = []
    for text in (raw, "\n".join(trimmed)):
        for variant in (text, re.sub(r"(?<=[^\W\d_])[-‐][ \t]*\n\s*(?=[^\W\d_])", "", text)):
            value = compact(variant)
            if value not in candidates:
                candidates.append(value)
    # Advance through each candidate independently. Repeated or reordered drafts
    # must match distinct occurrences in the same reading order.
    positions = [(candidate, 0) for candidate in candidates]
    for number, paragraph in enumerate(paragraphs, 1):
        pattern = paragraph_pattern(paragraph["text"])
        matched = []
        if pattern is not None:
            for candidate, start in positions:
                match = pattern.search(candidate, start)
                if match:
                    matched.append((candidate, match.end()))
        if not matched:
            raise ValueError(
                f"无法在本次审阅 PDF 中核实第 {number} 段的完整正文。请重新检查改后 PDF 的物理页码及文件版本，"
                "确保包含该段首尾；公式、自定义宏或缺少可提取文字也可能导致无法核验。")
        positions = matched
