"""Local, salted SHA-256 commitments for completed Paperroom actions.

v2 events ("paperroom.event.v2") separate public summary fields from private
authored/AI content. Each private item is committed individually with its own
32-byte random salt:
    sha256(canonical_json({"content": content, "id": id, "kind": kind, "salt": salt}))

The event digest hashes the public core (every field except 'digest',
'receipt', and 'disclosed'), which includes 'summary' and the list of
'commitments' ({id, kind, label, sha256}). Authors can therefore disclose any
subset of private items at submission time while reviewers still verify the
full hash chain, RFC 3161 receipts, and every disclosed item.

Legacy v1 events ("paperroom.event.v1") remain readable and verifiable.
"""

import hashlib
import json
import secrets
from datetime import datetime, timezone


VALID_KINDS = frozenset({
    "paper_outline", "paper_outline_proposed", "paper_outline_adopted",
    "paper_hint", "paper_polish_adopted",
    "section_outline", "section_hint", "section_polish_proposed", "section_polish_adopted",
    "paragraph_outline", "paragraph_polish_adopted", "sentence_reference",
    "section_published", "section_reviewed",
    "version_saved", "version_reviewed", "versions_cleaned",
    "checkpoint_restored",
})


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def canonical_json(value):
    return _json(value)


def commitment_digest(item_id, kind, content, salt):
    record = {"content": content, "id": item_id, "kind": kind, "salt": salt}
    return hashlib.sha256(_json(record).encode("utf-8")).hexdigest()


def event_digest(event):
    skip = {"digest", "receipt"}
    if event.get("schema") == "paperroom.event.v2":
        skip.add("disclosed")
    content = {key: value for key, value in event.items() if key not in skip}
    return hashlib.sha256(_json(content).encode("utf-8")).hexdigest()


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _split_payload(kind, payload):
    """Split an action payload into (public_summary, [(id, item_kind, label, content), ...])."""
    if not isinstance(payload, dict):
        return {}, [("payload", "payload", "事件内容", payload)]
    summary = {}
    items = []

    if kind in ("paper_outline", "paper_outline_proposed", "paper_outline_adopted"):
        sections = payload.get("sections") if isinstance(payload.get("sections"), list) else []
        summary["section_count"] = len(sections)
        summary["section_titles"] = [str(s.get("title", "")) for s in sections if isinstance(s, dict)]
        if payload.get("question"):
            items.append(("question", "research_question", "研究问题", payload["question"]))
        if payload.get("evidence"):
            items.append(("evidence", "research_evidence", "研究证据概述", payload["evidence"]))
        if sections:
            items.append(("sections", "paper_sections", f"整篇章节安排（{len(sections)} 节）", sections))
        return summary, items

    if kind == "section_outline":
        paragraphs = payload.get("paragraphs") if isinstance(payload.get("paragraphs"), list) else []
        subheadings = payload.get("subheadings") if isinstance(payload.get("subheadings"), list) else []
        if payload.get("title"):
            summary["section_title"] = str(payload["title"])
        summary["paragraph_count"] = len(paragraphs)
        if subheadings:
            summary["subheading_count"] = len(subheadings)
        if payload.get("purpose"):
            items.append(("section_purpose", "section_purpose", "本节作用", payload["purpose"]))
        if subheadings:
            items.append(("subheadings", "subheadings", f"小标题（{len(subheadings)} 个）", subheadings))
        if paragraphs:
            items.append(("paragraphs", "paragraph_plan", f"段落大纲（{len(paragraphs)} 段）", paragraphs))
        return summary, items

    if kind == "paragraph_outline":
        sentences = payload.get("sentences") if isinstance(payload.get("sentences"), list) else []
        if payload.get("section_title"):
            summary["section_title"] = str(payload["section_title"])
        summary["sentence_count"] = len(sentences)
        if payload.get("plan_revision") is not None:
            summary["plan_revision"] = payload["plan_revision"]
        if payload.get("purpose"):
            items.append(("paragraph_purpose", "paragraph_purpose", "本段作用", payload["purpose"]))
        if sentences:
            items.append(("sentences", "sentence_intents", f"逐句意图（{len(sentences)} 句）", sentences))
        return summary, items

    if kind in ("paper_hint", "section_hint"):
        if payload.get("title"):
            summary["section_title"] = str(payload["title"])
        if "text" in payload:
            items.append(("reference", "ai_reference", "AI 参考建议", payload["text"]))
        return summary, items

    if kind == "sentence_reference":
        if payload.get("section_title"):
            summary["section_title"] = str(payload["section_title"])
        if isinstance(payload.get("paragraphs"), list):
            summary["paragraph_count"] = len(payload["paragraphs"])
        items.append(("reference", "ai_reference", "AI 逐句参考", payload))
        return summary, items

    if kind in ("paper_polish_adopted", "section_polish_adopted", "paragraph_polish_adopted", "section_polish_proposed"):
        changes = payload.get("changes") if isinstance(payload.get("changes"), list) else []
        summary["change_count"] = len(changes)
        if payload.get("plan_revision") is not None:
            summary["plan_revision"] = payload["plan_revision"]
        for idx, change in enumerate(changes, 1):
            items.append((f"change_{idx}", "polish_change", f"润色修改 #{idx}", change))
        return summary, items

    if kind == "version_saved":
        for key in ("number", "display_number", "kind", "label", "pages", "pdf_sha256"):
            if key in payload and payload[key] is not None:
                summary[key] = payload[key]
        responses = payload.get("responses") if isinstance(payload.get("responses"), list) else []
        if responses:
            counts = {"changed": 0, "kept": 0, "discuss": 0}
            for resp in responses:
                st = resp.get("status") if isinstance(resp, dict) else None
                if st in counts:
                    counts[st] += 1
            summary["response_count"] = len(responses)
            summary["response_counts"] = counts
            for idx, resp in enumerate(responses, 1):
                note_no = resp.get("note", idx) if isinstance(resp, dict) else idx
                st = resp.get("status", "") if isinstance(resp, dict) else ""
                items.append((f"response_{note_no}", "version_response", f"回应意见 #{note_no}（{st}）", resp))
        return summary, items

    if kind == "version_reviewed":
        for key in ("number", "display_number", "approved"):
            if key in payload and payload[key] is not None:
                summary[key] = payload[key]
        notes = payload.get("notes") if isinstance(payload.get("notes"), list) else []
        summary["note_count"] = len(notes)
        summary["change_count"] = sum(1 for n in notes if isinstance(n, dict) and n.get("kind") == "change")
        summary["keep_count"] = sum(1 for n in notes if isinstance(n, dict) and n.get("kind") == "keep")
        for idx, note in enumerate(notes, 1):
            nk = note.get("kind", "") if isinstance(note, dict) else ""
            tag = "修改" if nk == "change" else ("保留" if nk == "keep" else "意见")
            items.append((f"note_{idx}", "review_note", f"审阅意见 #{idx}（{tag}）", note))
        return summary, items

    if kind == "versions_cleaned":
        for key in ("removed", "order_before"):
            if key in payload:
                summary[key] = payload[key]
        return summary, items

    if kind == "checkpoint_restored":
        for key in ("archive_id", "resumed_from_version", "resumed_display_number", "backup_archive_id"):
            if key in payload and payload[key] is not None:
                summary[key] = payload[key]
        if payload.get("commit"):
            items.append(("commit", "snapshot_message", "存档备注", payload["commit"]))
        return summary, items

    if kind == "section_published":
        public_keys = {"pages", "pdf_sha256", "min_notes", "revision", "title"}
        private_rest = {}
        for key, value in payload.items():
            if key in public_keys and value is not None:
                summary[key] = value
            else:
                private_rest[key] = value
        if private_rest:
            items.append(("section_draft", "section_draft", "章节草稿详情", private_rest))
        return summary, items

    if kind == "section_reviewed":
        notes = payload.get("notes") if isinstance(payload.get("notes"), list) else []
        summary["note_count"] = len(notes)
        if "approved" in payload:
            summary["approved"] = bool(payload["approved"])
        for idx, note in enumerate(notes, 1):
            nk = note.get("kind", "") if isinstance(note, dict) else ""
            tag = "修改" if nk == "change" else ("保留" if nk == "keep" else "意见")
            items.append((f"note_{idx}", "review_note", f"审阅意见 #{idx}（{tag}）", note))
        return summary, items

    items.append(("payload", "payload", "事件内容", payload))
    return summary, items


def _ensure_tables(db):
    db.execute("""CREATE TABLE IF NOT EXISTS v2_journal (
        seq INTEGER PRIMARY KEY, digest TEXT UNIQUE NOT NULL, event TEXT NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS v2_journal_secrets (
        seq INTEGER NOT NULL,
        item_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        label TEXT NOT NULL,
        salt TEXT NOT NULL,
        content TEXT NOT NULL,
        sha256 TEXT NOT NULL,
        PRIMARY KEY (seq, item_id))""")


def append(db, kind, payload, *, section=None, paragraph=None, revision=None, recorded_at=None):
    """Participate in the caller's transaction, which must hold the write lock."""
    if not db.in_transaction:
        raise RuntimeError("Journal writes need the action's transaction")
    _ensure_tables(db)
    head = db.execute("SELECT seq,digest FROM v2_journal ORDER BY seq DESC LIMIT 1").fetchone()
    seq = head[0] + 1 if head else 1
    summary, secret_items = _split_payload(kind, payload)
    commitments = []
    secret_rows = []
    for item_id, item_kind, label, content in secret_items:
        salt = secrets.token_hex(32)
        item_hash = commitment_digest(item_id, item_kind, content, salt)
        commitments.append({"id": item_id, "kind": item_kind, "label": label, "sha256": item_hash})
        secret_rows.append((seq, item_id, item_kind, label, salt, _json(content), item_hash))
    event = dict(
        schema="paperroom.event.v2",
        seq=seq,
        kind=kind,
        recorded_at=recorded_at or utc_now(),
        previous_digest=head[1] if head else None,
        summary=summary,
        commitments=commitments,
    )
    for key, value in (("section", section), ("paragraph", paragraph), ("revision", revision)):
        if value is not None:
            event[key] = value
    event["digest"] = event_digest(event)
    db.execute("INSERT INTO v2_journal VALUES (?,?,?)", (seq, event["digest"], _json(event)))
    if secret_rows:
        db.executemany("INSERT INTO v2_journal_secrets VALUES (?,?,?,?,?,?,?)", secret_rows)
    return {"seq": seq, "digest": event["digest"]}


def _has_table(db, name):
    return db is not None and bool(db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone())


def secrets_by_seq(db):
    """Return {seq: {item_id: {id, kind, label, salt, content, sha256}}} from local DB."""
    if not _has_table(db, "v2_journal_secrets"):
        return {}
    grouped = {}
    rows = db.execute(
        "SELECT seq, item_id, kind, label, salt, content, sha256 FROM v2_journal_secrets ORDER BY seq, rowid"
    ).fetchall()
    for seq, item_id, kind, label, salt, raw_content, sha256 in rows:
        grouped.setdefault(seq, {})[item_id] = {
            "id": item_id,
            "kind": kind,
            "label": label,
            "salt": salt,
            "content": json.loads(raw_content),
            "sha256": sha256,
        }
    return grouped


def raw_events(db):
    if not _has_table(db, "v2_journal"):
        return []
    return [json.loads(row[0]) for row in db.execute("SELECT event FROM v2_journal ORDER BY seq")]


def public_restore_note(event):
    """0.7.4 bound free-text snapshot messages directly into the public event digest."""
    if event.get("schema") == "paperroom.event.v2" and event.get("kind") == "checkpoint_restored":
        return event.get("summary", {}).get("commit")


PUBLIC_RESTORE_NOTE = "__public_restore_note__"


def export_events(db, *, include_secrets=True, disclose=None, up_to_seq=None):
    """Build exportable events.

    - include_secrets=True: attach every private item (full local audit export).
    - include_secrets=False: attach ONLY items listed in disclose={seq: [item_ids...]}.
    """
    all_events = raw_events(db)
    if up_to_seq is not None:
        all_events = [e for e in all_events if e["seq"] <= up_to_seq]
    secrets_map = secrets_by_seq(db)
    selected = disclose or {}
    exported = []
    for event in all_events:
        seq = event["seq"]
        schema = event.get("schema")
        raw_ids = selected.get(seq, selected.get(str(seq), []))
        if not isinstance(raw_ids, list) or not all(isinstance(x, str) for x in raw_ids):
            raise ValueError("导出请求格式不正确。")
        if schema == "paperroom.event.v2":
            item = dict(event)
            item_secrets = secrets_map.get(seq, {})
            if include_secrets:
                chosen_ids = list(item_secrets.keys())
            else:
                if public_restore_note(event) and PUBLIC_RESTORE_NOTE not in raw_ids:
                    raise ValueError("此范围内有旧版写入公开摘要的存档备注。请勾选同意公开这些备注，或选择更早的投稿版本。")
                chosen_ids = [i for i in raw_ids if i in item_secrets]
            if chosen_ids:
                item["disclosed"] = {
                    cid: {"content": item_secrets[cid]["content"], "salt": item_secrets[cid]["salt"]}
                    for cid in chosen_ids
                }
            exported.append(item)
        else:
            # Legacy paperroom.event.v1
            if include_secrets:
                exported.append(dict(event))
            else:
                if "__v1_payload__" in raw_ids:
                    exported.append(dict(event))
                else:
                    redacted = {k: v for k, v in event.items() if k not in ("payload", "salt")}
                    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
                    v1_summary, _ = _split_payload(event.get("kind", ""), payload)
                    if v1_summary:
                        redacted["summary"] = v1_summary
                    redacted["redacted_v1"] = True
                    exported.append(redacted)
    return exported


def events(db):
    """Public metadata for the workspace journal list (never exposes private content or salts)."""
    visible = ("seq", "schema", "kind", "recorded_at", "digest", "section", "paragraph", "revision", "summary")
    output = []
    for event in raw_events(db):
        entry = {key: event[key] for key in visible if key in event}
        if event.get("schema") == "paperroom.event.v2":
            entry["commitment_count"] = len(event.get("commitments") or [])
        else:
            payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
            v1_summary, _ = _split_payload(event.get("kind", ""), payload)
            if v1_summary:
                entry["summary"] = v1_summary
            entry["commitment_count"] = 1 if payload else 0
        output.append(entry)
    return output
