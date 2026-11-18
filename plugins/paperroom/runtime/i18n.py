"""Chinese/English messages. The code is written in Chinese; English comes from one
catalog (i18n_en.json, built by scripts/build_i18n.py) shared with the browser.

Lookup order: exact string, then patterns ({1} = group, {t1} = translated group),
then " · "-separated segments. Text that matches nothing stays as it is, so the
author's own words are never altered.
"""
import json
import os
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
_CATALOG = None
LANGUAGES = ("zh", "en")


def catalog():
    global _CATALOG
    if _CATALOG is None:
        data = json.loads((HERE / "i18n_en.json").read_text("utf-8"))
        _CATALOG = (data["exact"], [(re.compile(p), t) for p, t in data["patterns"]])
    return _CATALOG


def translate(text, lang="en"):
    if lang != "en" or not isinstance(text, str) or not text.strip():
        return text
    exact, patterns = catalog()
    core = text.strip()
    lead, tail = text[:len(text) - len(text.lstrip())], text[len(text.rstrip()):]
    if core in exact:
        return lead + exact[core] + tail
    for pattern, template in patterns:
        match = pattern.fullmatch(core)
        if match:
            def fill(slot):
                value = match.group(int(slot.group(2))) or ""
                return translate(value) if slot.group(1) else value
            return lead + re.sub(r"\{(t?)(\d+)\}", fill, template) + tail
    if " · " in core:
        parts = core.split(" · ")
        translated = [translate(part) for part in parts]
        if translated != parts:
            return lead + " · ".join(translated) + tail
    return text


def deep(value, lang="en"):
    """Translate every string in a JSON-like value (dict keys are left alone)."""
    if lang != "en":
        return value
    if isinstance(value, str):
        return translate(value)
    if isinstance(value, list):
        return [deep(v) for v in value]
    if isinstance(value, dict):
        return {k: deep(v) for k, v in value.items()}
    return value


def _preference(project):
    return Path(project) / ".paperroom" / "language"


def language(project=None):
    """The author's chosen language, else the system locale, else Chinese."""
    if project is not None:
        try:
            chosen = _preference(project).read_text("utf-8").strip()
            if chosen in LANGUAGES:
                return chosen
        except OSError:
            pass
    locale = (os.environ.get("PAPERROOM_LANG") or os.environ.get("LC_ALL") or os.environ.get("LANG") or "").lower()
    if locale.startswith("en"):
        return "en"
    return "zh"


def chosen(project):
    """The language the author picked in the workspace, or None."""
    try:
        value = _preference(project).read_text("utf-8").strip()
    except OSError:
        return None
    return value if value in LANGUAGES else None


def set_language(project, lang):
    if lang not in LANGUAGES:
        raise ValueError("Unknown language.")
    path = _preference(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(lang, encoding="utf-8")
