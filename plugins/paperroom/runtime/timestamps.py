"""Local timestamp history, optional receipts and author-initiated export."""
import base64
from contextlib import closing
import re
import sqlite3

import journal
import tsa


def history(path, *, export=False):
    events = []
    if path.is_file():
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db, db:
            db.execute("BEGIN")
            events = journal.export_events(db) if export else journal.events(db)
            receipts = {}
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='timestamp_receipts'").fetchone():
                fields = "digest, authority, verified_at" + (", query_der, reply_der" if export else "")
                for digest, authority, verified_at, *evidence in db.execute("SELECT " + fields + " FROM timestamp_receipts"):
                    receipt = {"authority": authority, "verified_at": verified_at}
                    if export:
                        receipt["query_der_b64"], receipt["reply_der_b64"] = [
                            base64.b64encode(binary).decode("ascii") for binary in evidence]
                    receipts[digest] = receipt
            events = [dict(event, receipt=receipts.get(event["digest"])) for event in events]
    if export:
        return {"format": "paperroom-timestamps-v1", "events": events}
    return {"events": events, "tsa_configured": tsa.configured(), "authority": tsa.authority()}


def request_receipt(path, data):
    if not isinstance(data, dict):
        raise ValueError("请选择一条已有的时间记录。")
    seq, digest = data.get("seq"), data.get("digest")
    if type(seq) is not int or seq < 1 or not isinstance(digest, str) or not re.fullmatch("[0-9a-f]{64}", digest):
        raise ValueError("时间记录标识无效。")
    initial = history(path)
    event = next((e for e in initial["events"] if e["seq"] == seq and e["digest"] == digest), None)
    if event is None:
        raise ValueError("未找到对应事件，请刷新记录。")
    if event["receipt"]:
        return initial
    receipt = tsa.stamp(digest)
    # The network call runs outside the transaction, so the author can keep writing.
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
    return history(path)
