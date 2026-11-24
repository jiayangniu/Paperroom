"""Local timestamp history, project-level auto-sealing, and selective-disclosure export."""
import base64
from contextlib import closing
import json
from pathlib import Path
import re
import sqlite3

import journal
import paperroom
import tsa


def _has_table(db, name):
    return db is not None and bool(db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone())


def _read_settings(db):
    auto_seal = False
    tsa_url = ""
    if _has_table(db, "v2_timestamp_settings"):
        rows = dict(db.execute("SELECT key, value FROM v2_timestamp_settings").fetchall())
        auto_seal = rows.get("enabled") == "1"
        tsa_url = (rows.get("tsa_url") or "").strip()
    effective_url = None
    if tsa_url:
        effective_url = tsa_url
    elif tsa.configured():
        effective_url = None  # let tsa._endpoint read PAPERROOM_TSA_URL
    elif auto_seal:
        effective_url = tsa.DEFAULT_TSA_URL
    host = tsa.authority(effective_url) if (effective_url is not None or tsa.configured()) else None
    configured = bool(host)
    return {
        "auto_seal": auto_seal,
        "tsa_url": tsa_url,
        "effective_url": effective_url,
        "tsa_configured": configured,
        "authority": host,
        "presets": list(tsa.PRESET_AUTHORITIES),
    }


def _read_receipts(db, *, include_der=False):
    receipts = {}
    if _has_table(db, "timestamp_receipts"):
        fields = "digest, authority, verified_at" + (", query_der, reply_der" if include_der else "")
        for digest, authority, verified_at, *evidence in db.execute("SELECT " + fields + " FROM timestamp_receipts"):
            receipt = {"authority": authority, "verified_at": verified_at}
            if include_der:
                receipt["query_der_b64"], receipt["reply_der_b64"] = [
                    base64.b64encode(binary).decode("ascii") for binary in evidence
                ]
            receipts[digest] = receipt
    return receipts


def _read_pending(db):
    pending = {}
    if _has_table(db, "v2_timestamp_pending"):
        for digest, seq, error, updated_at in db.execute(
            "SELECT digest, seq, error, updated_at FROM v2_timestamp_pending"
        ):
            pending[digest] = {"seq": seq, "error": error, "updated_at": updated_at}
    return pending


def _read_versions_meta(db):
    """Map stable version numbers to current display metadata."""
    meta = {}
    if _has_table(db, "v2_versions"):
        for row in db.execute("SELECT body FROM v2_versions ORDER BY number"):
            body = json.loads(row[0])
            meta[body["number"]] = {
                "number": body["number"],
                "kind": body.get("kind"),
                "display_number": body.get("display_number"),
                "last_display_number": body.get("last_display_number"),
                "cleaned_at": body.get("cleaned_at"),
                "label": body.get("label"),
                "pages": body.get("pages"),
                "pdf_sha256": body.get("pdf_sha256"),
                "created": body.get("created"),
            }
    return meta


def settings(path):
    path = Path(path)
    if path.is_file():
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
            return _read_settings(db)
    return _read_settings(None)


def update_settings(path, data):
    if not isinstance(data, dict):
        raise ValueError("时间戳设置格式不正确。")
    auto_seal = bool(data.get("auto_seal", False))
    raw_url = data.get("tsa_url", "")
    if not isinstance(raw_url, str):
        raise ValueError("时间戳机构须使用不含账号密码的 HTTPS 地址。")
    tsa_url = raw_url.strip()
    if tsa_url:
        tsa.parse_endpoint(tsa_url)
    path = Path(path)
    with closing(paperroom.connect(path)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("CREATE TABLE IF NOT EXISTS v2_timestamp_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        db.execute("INSERT OR REPLACE INTO v2_timestamp_settings VALUES ('enabled', ?)", ("1" if auto_seal else "0",))
        db.execute("INSERT OR REPLACE INTO v2_timestamp_settings VALUES ('tsa_url', ?)", (tsa_url,))
    return history(path)


def _version_entries(events, version_meta):
    versions = []
    for event in events:
        if event.get("kind") != "version_saved":
            continue
        summary = event.get("summary") or {}
        number = summary.get("number") if "number" in summary else event.get("revision")
        if number is None:
            continue
        current = version_meta.get(number, {})
        versions.append({
            "number": number,
            "kind": summary.get("kind") or current.get("kind") or ("original" if number == 0 else "version"),
            "display_number": current.get("display_number") if number in version_meta else summary.get("display_number"),
            "cleaned_at": current.get("cleaned_at"),
            "label": summary.get("label") if summary.get("label") is not None else current.get("label"),
            "pages": summary.get("pages") if summary.get("pages") is not None else current.get("pages"),
            "pdf_sha256": summary.get("pdf_sha256") or current.get("pdf_sha256"),
            "event_seq": event["seq"],
            "recorded_at": event["recorded_at"],
            "sealed": bool(event.get("receipt")),
            "pending_seal": event.get("pending_seal"),
        })
    return versions


def history(path, *, export=False):
    path = Path(path)
    events = []
    cfg = _read_settings(None)
    version_meta = {}
    pending = {}
    if path.is_file():
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db, db:
            db.execute("BEGIN")
            cfg = _read_settings(db)
            events = journal.export_events(db) if export else journal.events(db)
            receipts = _read_receipts(db, include_der=export)
            pending = _read_pending(db) if not export else {}
            version_meta = _read_versions_meta(db) if not export else {}
            enriched = []
            for event in events:
                receipt = receipts.get(event["digest"])
                item = dict(event, receipt=receipt)
                if not export:
                    item["pending_seal"] = None if receipt else pending.get(event["digest"])
                enriched.append(item)
            events = enriched
    if export:
        return {"format": "paperroom-timestamps-v1", "events": events}
    versions = _version_entries(events, version_meta)
    pending_count = sum(1 for e in events if e.get("pending_seal") and not e.get("receipt"))
    return {
        "events": events,
        "tsa_configured": cfg["tsa_configured"],
        "authority": cfg["authority"],
        "auto_seal": cfg["auto_seal"],
        "tsa_url": cfg["tsa_url"],
        "presets": cfg["presets"],
        "pending_count": pending_count,
        "versions": versions,
    }


def _store_receipt(path, seq, digest, receipt):
    with closing(sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, timeout=10)) as db, db:
        db.execute("PRAGMA journal_mode=TRUNCATE")
        db.execute("BEGIN IMMEDIATE")
        if not any(e["seq"] == seq and e["digest"] == digest for e in journal.events(db)):
            raise ValueError("记录已变动，请刷新时间记录。")
        db.execute("""CREATE TABLE IF NOT EXISTS timestamp_receipts (
            digest TEXT PRIMARY KEY, authority TEXT NOT NULL, verified_at TEXT NOT NULL,
            query_der BLOB NOT NULL, reply_der BLOB NOT NULL)""")
        db.execute("""INSERT INTO timestamp_receipts VALUES (?, ?, ?, ?, ?)
                      ON CONFLICT(digest) DO NOTHING""",
                   (digest, receipt["authority"], receipt["verified_at"], receipt["query_der"], receipt["reply_der"]))
        if _has_table(db, "v2_timestamp_pending"):
            db.execute("DELETE FROM v2_timestamp_pending WHERE digest=?", (digest,))


def _store_pending(path, seq, digest, error_text):
    with closing(sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, timeout=10)) as db, db:
        db.execute("PRAGMA journal_mode=TRUNCATE")
        db.execute("BEGIN IMMEDIATE")
        db.execute("""CREATE TABLE IF NOT EXISTS v2_timestamp_pending (
            digest TEXT PRIMARY KEY, seq INTEGER NOT NULL, error TEXT NOT NULL, updated_at TEXT NOT NULL)""")
        db.execute("INSERT OR REPLACE INTO v2_timestamp_pending VALUES (?, ?, ?, ?)",
                   (digest, seq, str(error_text), journal.utc_now()))


def request_receipt(path, data):
    if not isinstance(data, dict):
        raise ValueError("请选择一条已有的时间记录。")
    seq, digest = data.get("seq"), data.get("digest")
    if type(seq) is not int or seq < 1 or not isinstance(digest, str) or not re.fullmatch("[0-9a-f]{64}", digest):
        raise ValueError("时间记录标识无效。")
    path = Path(path)
    cfg = settings(path)
    initial = history(path)
    event = next((e for e in initial["events"] if e["seq"] == seq and e["digest"] == digest), None)
    if event is None:
        raise ValueError("未找到对应事件，请刷新记录。")
    if event["receipt"]:
        return initial
    receipt = tsa.stamp(digest) if cfg["effective_url"] is None else tsa.stamp(digest, url=cfg["effective_url"])
    # The network call runs outside the transaction, so the author can keep writing.
    _store_receipt(path, seq, digest, receipt)
    return history(path)


def try_auto_seal(path, seq, digest):
    """Best-effort auto-sealing after a version save. Never raises on network/TSA errors."""
    if not path:
        return None
    path = Path(path)
    if not path.is_file():
        return None
    cfg = settings(path)
    if not cfg["auto_seal"]:
        return None
    try:
        receipt = tsa.stamp(digest) if cfg["effective_url"] is None else tsa.stamp(digest, url=cfg["effective_url"])
        _store_receipt(path, seq, digest, receipt)
        return {"status": "sealed", "authority": receipt["authority"], "verified_at": receipt["verified_at"]}
    except (ValueError, OSError, sqlite3.Error) as exc:
        try:
            _store_pending(path, seq, digest, str(exc))
        except (OSError, sqlite3.Error):
            pass
        return {"status": "pending", "error": str(exc)}


def seal_pending(path):
    """Retry stamping all pending events when back online."""
    path = Path(path)
    if not path.is_file():
        return {**history(path), "sealed_now": 0, "remaining_pending": 0}
    cfg = settings(path)
    if not cfg["tsa_configured"]:
        raise ValueError("尚未配置时间戳机构。")
    current = history(path)
    targets = [e for e in current["events"] if e.get("pending_seal") and not e.get("receipt")]
    sealed_now = 0
    last_error = ""
    for event in targets:
        try:
            receipt = tsa.stamp(event["digest"], url=cfg["effective_url"])
            _store_receipt(path, event["seq"], event["digest"], receipt)
            sealed_now += 1
        except (ValueError, OSError, sqlite3.Error) as exc:
            last_error = str(exc)
            try:
                _store_pending(path, event["seq"], event["digest"], last_error)
            except (OSError, sqlite3.Error):
                pass
    updated = history(path)
    updated["sealed_now"] = sealed_now
    updated["remaining_pending"] = updated["pending_count"]
    if last_error and updated["pending_count"]:
        updated["last_seal_error"] = last_error
    return updated


def disclosable_items(path, *, target_version=None):
    """Return local private items grouped by event so the author can pick what to disclose."""
    path = Path(path)
    if not path.is_file():
        return {"versions": [], "events": []}
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db, db:
        db.execute("BEGIN")
        raw = journal.raw_events(db)
        secrets_map = journal.secrets_by_seq(db)
        receipts = _read_receipts(db, include_der=False)
        pending = _read_pending(db)
        version_meta = _read_versions_meta(db)
        public_events = []
        for ev in journal.events(db):
            rec = receipts.get(ev["digest"])
            public_events.append(dict(ev, receipt=rec, pending_seal=None if rec else pending.get(ev["digest"])))
        versions = _version_entries(public_events, version_meta)
        up_to_seq = None
        if target_version is not None:
            match = next((v for v in versions if v["number"] == target_version), None)
            if match is None:
                raise ValueError("找不到所选的论文版本。")
            up_to_seq = match["event_seq"]
        items_by_event = []
        for event in raw:
            seq = event["seq"]
            if up_to_seq is not None and seq > up_to_seq:
                break
            schema = event.get("schema")
            if schema == "paperroom.event.v2":
                secret_entries = secrets_map.get(seq, {})
                commitments = []
                for c in event.get("commitments") or []:
                    sec = secret_entries.get(c["id"])
                    if sec:
                        commitments.append({
                            "id": c["id"],
                            "kind": c["kind"],
                            "label": c["label"],
                            "content": sec["content"],
                        })
                if commitments:
                    items_by_event.append({
                        "seq": seq,
                        "schema": schema,
                        "kind": event["kind"],
                        "recorded_at": event["recorded_at"],
                        "section": event.get("section"),
                        "paragraph": event.get("paragraph"),
                        "revision": event.get("revision"),
                        "summary": event.get("summary") or {},
                        "items": commitments,
                    })
            else:
                payload = event.get("payload")
                if payload:
                    items_by_event.append({
                        "seq": seq,
                        "schema": schema or "paperroom.event.v1",
                        "kind": event["kind"],
                        "recorded_at": event["recorded_at"],
                        "section": event.get("section"),
                        "paragraph": event.get("paragraph"),
                        "revision": event.get("revision"),
                        "summary": {},
                        "legacy_v1": True,
                        "items": [{
                            "id": "__v1_payload__",
                            "kind": "legacy_payload",
                            "label": "旧格式整条原文",
                            "content": payload,
                        }],
                    })
        return {"versions": versions, "events": items_by_event}


def export_verifiable_log(path, *, project_name="", target_version=None, disclose=None):
    """Export a selective-disclosure paperroom-log-v2 bundle for reviewers."""
    path = Path(path)
    if not path.is_file():
        return {
            "format": "paperroom-log-v2",
            "exported_at": journal.utc_now(),
            "project_name": project_name,
            "target_version": None,
            "origin": {"started_with_existing_manuscript": False, "first_event_seq": None, "first_recorded_at": None},
            "events": [],
        }
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db, db:
        db.execute("BEGIN")
        receipts = _read_receipts(db, include_der=True)
        version_meta = _read_versions_meta(db)
        public_events = [dict(e, receipt=receipts.get(e["digest"])) for e in journal.events(db)]
        versions = _version_entries(public_events, version_meta)
        selected_version = None
        up_to_seq = None
        if target_version is not None:
            if type(target_version) is not int or target_version < 0:
                raise ValueError("版本号格式无效。")
            selected_version = next((v for v in versions if v["number"] == target_version), None)
            if selected_version is None:
                raise ValueError("找不到所选的论文版本。")
            up_to_seq = selected_version["event_seq"]
        elif versions:
            selected_version = versions[-1]
        events = journal.export_events(db, include_secrets=False, disclose=disclose or {}, up_to_seq=up_to_seq)
        events = [dict(event, receipt=receipts.get(event["digest"])) for event in events]
        has_v0 = any(
            e.get("kind") == "version_saved" and (e.get("summary") or {}).get("kind") == "original"
            for e in events
        )
        origin = {
            "started_with_existing_manuscript": has_v0,
            "first_event_seq": events[0]["seq"] if events else None,
            "first_recorded_at": events[0]["recorded_at"] if events else None,
        }
        target_info = None
        if selected_version is not None:
            target_info = {
                "number": selected_version["number"],
                "kind": selected_version["kind"],
                "display_number": selected_version["display_number"],
                "label": selected_version["label"],
                "pages": selected_version["pages"],
                "pdf_sha256": selected_version["pdf_sha256"],
                "event_seq": selected_version["event_seq"],
            }
        return {
            "format": "paperroom-log-v2",
            "exported_at": journal.utc_now(),
            "project_name": project_name,
            "target_version": target_info,
            "origin": origin,
            "events": events,
        }
