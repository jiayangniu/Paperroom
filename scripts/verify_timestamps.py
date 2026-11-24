#!/usr/bin/env python3
"""Offline verification of a Paperroom writing log or timestamp export."""
import argparse
import base64
import binascii
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins/paperroom/runtime"))
import journal
import tsa


DIGEST = re.compile(r"[0-9a-f]{64}\Z")
KINDS = journal.VALID_KINDS
V1_FIELDS = {"schema", "seq", "kind", "recorded_at", "previous_digest", "salt", "payload", "digest", "receipt"}
V2_FIELDS = {"schema", "seq", "kind", "recorded_at", "previous_digest", "summary", "commitments", "digest", "receipt"}
OPTIONAL_LOC = {"section", "paragraph", "revision"}


def unique_keys(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError("导出文件含有重复的 JSON 键。")
        obj[key] = value
    return obj


def decode_der(data):
    if not isinstance(data, str) or not data:
        raise ValueError("缺少时间戳二进制数据。")
    try:
        return base64.b64decode(data, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("时间戳数据的 Base64 编码无效。") from exc


def _check_recorded_at(seq, value):
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
    except (TypeError, ValueError) as exc:
        raise ValueError(f"第 {seq} 条事件的本机时间格式无效。") from exc


def _verify_v1_event(seq, event):
    if event.get("redacted_v1"):
        if not isinstance(event.get("digest"), str) or not DIGEST.fullmatch(event["digest"]):
            raise ValueError(f"第 {seq} 条事件的数据格式无效。")
        _check_recorded_at(seq, event.get("recorded_at"))
        return
    if not V1_FIELDS <= event.keys() or event.keys() - V1_FIELDS - OPTIONAL_LOC:
        raise ValueError(f"第 {seq} 条事件的格式、顺序或前序摘要无效。")
    if (not isinstance(event["payload"], dict) or not isinstance(event["salt"], str)
            or not DIGEST.fullmatch(event["salt"]) or not isinstance(event["digest"], str)
            or not DIGEST.fullmatch(event["digest"])):
        raise ValueError(f"第 {seq} 条事件的数据格式无效。")
    _check_recorded_at(seq, event["recorded_at"])
    record = {key: value for key, value in event.items() if key != "receipt"}
    if journal.event_digest(record) != event["digest"]:
        raise ValueError(f"第 {seq} 条事件的内容与摘要不符。")


def _verify_v2_event(seq, event):
    if not V2_FIELDS <= event.keys() or event.keys() - V2_FIELDS - OPTIONAL_LOC - {"disclosed"}:
        raise ValueError(f"第 {seq} 条事件的格式、顺序或前序摘要无效。")
    if (not isinstance(event["summary"], dict) or not isinstance(event["commitments"], list)
            or not isinstance(event["digest"], str) or not DIGEST.fullmatch(event["digest"])):
        raise ValueError(f"第 {seq} 条事件的数据格式无效。")
    _check_recorded_at(seq, event["recorded_at"])
    commit_map = {}
    for item in event["commitments"]:
        if (not isinstance(item, dict) or set(item) != {"id", "kind", "label", "sha256"}
                or not isinstance(item["id"], str) or not isinstance(item["kind"], str)
                or not isinstance(item["label"], str) or not isinstance(item["sha256"], str)
                or not DIGEST.fullmatch(item["sha256"]) or item["id"] in commit_map):
            raise ValueError(f"第 {seq} 条事件的承诺条目格式无效。")
        commit_map[item["id"]] = item
    if journal.event_digest(event) != event["digest"]:
        raise ValueError(f"第 {seq} 条事件的内容与摘要不符。")
    disclosed = event.get("disclosed")
    if disclosed is not None:
        if not isinstance(disclosed, dict):
            raise ValueError(f"第 {seq} 条事件的公开原文格式无效。")
        for cid, entry in disclosed.items():
            spec = commit_map.get(cid)
            if (spec is None or not isinstance(entry, dict) or set(entry) != {"content", "salt"}
                    or not isinstance(entry["salt"], str) or not DIGEST.fullmatch(entry["salt"])):
                raise ValueError(f"第 {seq} 条事件的公开原文条目无效。")
            calc = journal.commitment_digest(cid, spec["kind"], entry["content"], entry["salt"])
            if calc != spec["sha256"]:
                raise ValueError(f"第 {seq} 条事件的公开原文与摘要不符。")


def _pdf_target(bundle):
    """The exporter ends at the selected saved version or its subsequent review.

    The envelope is a convenience for locating that event. Only bytes committed
    by a verified event can identify a manuscript.
    """
    event = next((e for e in reversed(bundle["events"]) if e["kind"] == "version_saved"), None)
    claim = bundle.get("target_version")
    if claim is not None and (not isinstance(claim, dict) or event is None
                              or type(claim.get("event_seq")) is not int or claim["event_seq"] != event["seq"]):
        raise ValueError("导出的投稿版本与日志中的保存记录不一致。")
    if event is None:
        return None, None
    if event["schema"] == "paperroom.event.v1" and event.get("redacted_v1"):
        # The summary of a redacted v1 event is a display hint; its fields
        # cannot be authenticated even when the event digest has a receipt.
        return event, None
    data = event["summary"] if event["schema"] == "paperroom.event.v2" else event["payload"]
    number = data.get("number", event.get("revision"))
    sha = data.get("pdf_sha256")
    if (type(number) is not int or number < 0 or
            (sha is not None and (not isinstance(sha, str) or not DIGEST.fullmatch(sha)))):
        raise ValueError("论文保存记录中的版本编号或 PDF 指纹无效。")
    if claim is not None and (type(claim.get("number")) is not int or claim["number"] != number
                              or claim.get("pdf_sha256") != sha):
        raise ValueError("导出的投稿版本与日志中的保存记录不一致。")
    return event, sha


def _covered_records(events, receipts):
    """A hidden v1 event cannot authenticate its link back to the previous event."""
    anchors = {seq for seq, _ in receipts}
    covered = set()
    anchored = False
    for event in reversed(events):
        if event["schema"] == "paperroom.event.v1" and event.get("redacted_v1"):
            anchored = False
            continue
        anchored = anchored or event["seq"] in anchors
        if anchored:
            covered.add(event["seq"])
    return covered


def verify_bundle(bundle, ca_file=None, pdf_file=None):
    if (not isinstance(bundle, dict)
            or bundle.get("format") not in ("paperroom-timestamps-v1", "paperroom-log-v2")
            or not isinstance(bundle.get("events"), list)):
        raise ValueError("请选择 Paperroom 导出的写作日志或时间戳 JSON 文件。")
    previous = None
    receipts = []
    for seq, event in enumerate(bundle["events"], 1):
        if (not isinstance(event, dict) or type(event.get("seq")) is not int
                or event["seq"] != seq or event.get("previous_digest") != previous
                or not isinstance(event.get("kind"), str) or event["kind"] not in KINDS):
            raise ValueError(f"第 {seq} 条事件的格式、顺序或前序摘要无效。")
        schema = event.get("schema")
        if schema == "paperroom.event.v1":
            _verify_v1_event(seq, event)
        elif schema == "paperroom.event.v2":
            _verify_v2_event(seq, event)
        else:
            raise ValueError(f"第 {seq} 条事件的格式、顺序或前序摘要无效。")
        previous = event["digest"]
        receipt = event.get("receipt")
        if receipt is None:
            continue
        if (not isinstance(receipt, dict)
                or set(receipt) != {"authority", "verified_at", "query_der_b64", "reply_der_b64"}
                or not isinstance(receipt["authority"], str) or not receipt["authority"].strip()):
            raise ValueError(f"第 {seq} 条事件的时间戳回执格式无效。")
        try:
            signed_at = tsa.verify_receipt(previous, decode_der(receipt["query_der_b64"]),
                                           decode_der(receipt["reply_der_b64"]), ca_file=ca_file)
        except ValueError as exc:
            raise ValueError(f"第 {seq} 条事件的回执验证失败。{exc}") from exc
        if signed_at != receipt["verified_at"]:
            raise ValueError(f"第 {seq} 条事件的回执时间与签名时间不符。")
        receipts.append((seq, signed_at))
    event, expected = _pdf_target(bundle)
    if pdf_file is not None:
        if event and event["schema"] == "paperroom.event.v1" and event.get("redacted_v1"):
            raise ValueError("所选旧版保存记录未披露原文，无法核对投稿 PDF。")
        if not expected:
            raise ValueError("日志中没有可供核对的 PDF 指纹。")
        actual = hashlib.sha256(Path(pdf_file).read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError("投稿 PDF 与保存记录中的指纹不符。")
    return len(bundle["events"]), receipts


def main():
    parser = argparse.ArgumentParser(description="离线核验 Paperroom 写作日志或时间戳导出文件的摘要链、签名、时间和 PDF。")
    parser.add_argument("export", type=Path, help="写作间导出的 JSON 文件")
    parser.add_argument("--ca-file", type=Path, help="核验者信任的 CA 证书文件（PEM）")
    parser.add_argument("--pdf", type=Path, help="待核对的投稿 PDF 文件（可选）")
    args = parser.parse_args()
    try:
        with args.export.open(encoding="utf-8") as source:
            loaded = json.load(source, object_pairs_hook=unique_keys)
            count, receipts = verify_bundle(loaded, args.ca_file, pdf_file=args.pdf)
    except (OSError, ValueError, RecursionError) as exc:
        print(f"核验失败。{exc}", file=sys.stderr)
        return 1
    covered = _covered_records(loaded["events"], receipts)
    print(f"事件 {count} 条，已核验的独立时间戳回执 {len(receipts)} 份。")
    print(f"回执覆盖 {len(covered)} 条，仅有本机记录 {count - len(covered)} 条。")
    redacted_v1 = sum(1 for e in loaded.get("events", []) if isinstance(e, dict) and e.get("redacted_v1"))
    if redacted_v1:
        print(f"注意：含 {redacted_v1} 条未公开原文的旧格式（v1）记录，无法重算其单条摘要。")
    for seq, signed_at in receipts:
        print(f"事件 #{seq} 的摘要最迟于 {signed_at} 已存在。")
    if args.pdf is not None:
        event, _ = _pdf_target(loaded)
        seal = "有受信时间戳覆盖" if event["seq"] in covered else "不在受信时间戳覆盖范围内"
        print(f"投稿 PDF 与保存记录 #{event['seq']} 匹配。该记录{seal}。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
