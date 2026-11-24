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


def _target_pdf_sha256(bundle):
    target = bundle.get("target_version")
    if isinstance(target, dict) and isinstance(target.get("pdf_sha256"), str):
        return target["pdf_sha256"]
    for event in reversed(bundle.get("events") or []):
        if event.get("kind") == "version_saved":
            sha = (event.get("summary") or {}).get("pdf_sha256") or (event.get("payload") or {}).get("pdf_sha256")
            if isinstance(sha, str) and DIGEST.fullmatch(sha):
                return sha
    return None


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
    if pdf_file is not None:
        expected = _target_pdf_sha256(bundle)
        if not expected:
            raise ValueError("日志中没有可供核对的封存 PDF 指纹。")
        actual = hashlib.sha256(Path(pdf_file).read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError("投稿 PDF 与日志中封存版本的指纹不符。")
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
    covered = receipts[-1][0] if receipts else 0
    print(f"事件 {count} 条，已核验的独立时间戳回执 {len(receipts)} 份。")
    print(f"回执覆盖 {covered} 条，仅有本机记录 {count - covered} 条。")
    redacted_v1 = sum(1 for e in loaded.get("events", []) if isinstance(e, dict) and e.get("redacted_v1"))
    if redacted_v1:
        print(f"注意：含 {redacted_v1} 条未公开原文的旧格式（v1）记录，无法重算其单条摘要。")
    for seq, signed_at in receipts:
        print(f"事件 #{seq} 及其前序记录最迟于 {signed_at} 已存在。")
    if args.pdf is not None:
        print("投稿 PDF 匹配。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
