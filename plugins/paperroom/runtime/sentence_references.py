"""AI reading references, kept separate from the author's sentence intents."""
import hashlib
import json
import time

import journal
import outline


def context(plan, section):
    """Inputs to the AI reference. Author-written sentence intents do not change its basis."""
    return dict(question=plan["question"], evidence=plan["evidence"], section=section["id"],
                title=section["title"], purpose=section["purpose"],
                section_reference=(section.get("hint") or {}).get("text", ""),
                subheadings=section.get("subheadings", []),
                paragraphs=[dict(id=p["id"], purpose=p["purpose"]) for p in section["paragraphs"]])


def basis_for(inputs):
    stored = json.dumps(inputs, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(stored).hexdigest()


def status(db, plan, section):
    if not section or not section["planned"]:
        return None
    basis = basis_for(context(plan, section))
    entries, earlier = {}, {}
    if db is not None and db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='v2_sentence_references'"
    ).fetchone():
        ids = {p["id"] for p in section["paragraphs"]}
        for pid, saved_basis, sentences in db.execute(
                "SELECT paragraph, basis, sentences FROM v2_sentence_references WHERE section=?", (section["id"],)):
            if pid in ids:
                destination = entries if saved_basis == basis else earlier
                destination[pid] = json.loads(sentences)
    return dict(basis=basis, by_paragraph=entries, earlier_by_paragraph=earlier,
                pending=[p["id"] for p in section["paragraphs"] if not p["ready"] and p["id"] not in entries])



def prepare(db, project, section_id, wait_seconds=0):
    """Allow an active host conversation to await a browser submission for one short call."""
    if type(wait_seconds) is not int or not 0 <= wait_seconds <= 20:
        raise ValueError("等待时间须在 0 到 20 秒之间。")
    deadline = time.monotonic() + wait_seconds
    while True:
        plan = outline.state(db, project)
        section = outline._item(plan["sections"], section_id, "章节")
        current = status(db, plan, section)
        if current:
            return dict(state="ready", context=context(plan, section), basis=current["basis"], pending=current["pending"])
        if time.monotonic() >= deadline:
            return dict(state="awaiting_author", section=section_id)
        time.sleep(min(0.5, max(0, deadline - time.monotonic())))


def save(db, project, section_id, basis, references):
    if not isinstance(references, list) or not 1 <= len(references) <= 100:
        raise ValueError("每次请提供 1 至 100 段的逐句参考。")
    with db:
        db.execute("BEGIN IMMEDIATE")
        prepared = prepare(db, project, section_id)
        if prepared.get("basis") != basis or not basis:
            raise ValueError("段落大纲或上一级参考已更新，请重新读取后生成逐句参考。")
        ids = {p["id"] for p in prepared["context"]["paragraphs"]}
        db.execute("""CREATE TABLE IF NOT EXISTS v2_sentence_references (
            section TEXT NOT NULL, paragraph TEXT NOT NULL, basis TEXT NOT NULL, sentences TEXT NOT NULL,
            PRIMARY KEY(section, paragraph))""")
        for entry in references:
            pid = entry.get("paragraph") if isinstance(entry, dict) else None
            if not isinstance(pid, str) or pid not in ids:
                raise ValueError("逐句参考含未知或重复的段落。")
            ids.remove(pid)
            rows = entry.get("sentences")
            if ("text" in entry) == ("sentences" in entry):
                raise ValueError("请为每段提供参考文字或逐句列表，二选一。")
            if "text" in entry:
                text = outline.reference_text(entry["text"])
                sentences = [dict(content=text, connection="")]
                payload = dict(basis=basis, text=text)
            else:
                if not isinstance(rows, list) or not 1 <= len(rows) <= 100:
                    raise ValueError("每段参考需有 1 至 100 句。")
                sentences = []
                for row in rows:
                    if not isinstance(row, dict) or any(not isinstance(row.get(k), str) or not row[k].strip()
                                                         or len(row[k]) > 2000 for k in ("content", "connection")):
                        raise ValueError("请为每句分别提供具体内容与逻辑衔接，各不超过 2000 字。")
                    sentences.append({k: row[k].strip() for k in ("content", "connection")})
                payload = dict(basis=basis, sentences=sentences)
            encoded = json.dumps(sentences, ensure_ascii=False)
            prior = db.execute("SELECT basis, sentences FROM v2_sentence_references WHERE section=? AND paragraph=?",
                               (section_id, pid)).fetchone()
            if prior and tuple(prior) == (basis, encoded):
                continue
            db.execute("INSERT OR REPLACE INTO v2_sentence_references VALUES (?,?,?,?)",
                       (section_id, pid, basis, encoded))
            journal.append(db, "sentence_reference", payload,
                           section=section_id, paragraph=pid)
    return dict(section=section_id, basis=basis, saved=[entry["paragraph"] for entry in references])
