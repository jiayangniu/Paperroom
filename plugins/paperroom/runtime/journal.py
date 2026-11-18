"""Local, salted SHA-256 commitments for completed Paperroom actions.

The hash input is every event field except 'digest', including payload, salt
(32 random bytes in lowercase hex), seq (1-based) and previous_digest (null
at genesis). Serialize with Python json.dumps using sort_keys=True,
ensure_ascii=False, separators=(',', ':'), allow_nan=False, then encode as
UTF-8, with no BOM or trailing newline. Digest is lowercase hexadecimal.
"""

import hashlib
import json
import secrets
from datetime import datetime, timezone


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def event_digest(event):
    content = {key: value for key, value in event.items() if key != "digest"}
    return hashlib.sha256(_json(content).encode("utf-8")).hexdigest()


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def append(db, kind, payload, *, section=None, paragraph=None, revision=None, recorded_at=None):
    """Participate in the caller's transaction, which must hold the write lock."""
    if not db.in_transaction:
        raise RuntimeError("Journal writes need the action's transaction")
    db.execute("""CREATE TABLE IF NOT EXISTS v2_journal (
        seq INTEGER PRIMARY KEY, digest TEXT UNIQUE NOT NULL, event TEXT NOT NULL)""")
    head = db.execute("SELECT seq,digest FROM v2_journal ORDER BY seq DESC LIMIT 1").fetchone()
    event = dict(schema="paperroom.event.v1", seq=head[0] + 1 if head else 1,
                 kind=kind, recorded_at=recorded_at or utc_now(),
                 previous_digest=head[1] if head else None, salt=secrets.token_hex(32),
                 payload=payload)
    for key, value in (("section", section), ("paragraph", paragraph), ("revision", revision)):
        if value is not None:
            event[key] = value
    event["digest"] = event_digest(event)
    db.execute("INSERT INTO v2_journal VALUES (?,?,?)", (event["seq"], event["digest"], _json(event)))


def export_events(db):
    """Private evidence for opt-in export. Opening a legacy project creates no records."""
    if db is None or not db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='v2_journal'"
    ).fetchone():
        return []
    return [json.loads(row[0]) for row in db.execute("SELECT event FROM v2_journal ORDER BY seq")]


def events(db):
    visible = ("seq", "kind", "recorded_at", "digest", "section", "paragraph", "revision")
    return [{key: event[key] for key in visible if key in event} for event in export_events(db)]
