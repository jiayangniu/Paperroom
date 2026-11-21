#!/usr/bin/env python3
"""Offline verification of a Paperroom timestamp export."""
import argparse
import base64
import binascii
from datetime import datetime
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins/paperroom/runtime"))
import journal
import tsa


DIGEST = re.compile(r"[0-9a-f]{64}\Z")
KINDS = {"paper_outline", "section_outline", "paragraph_outline", "section_published", "section_reviewed",
         "version_saved", "version_reviewed"}
FIELDS = {"schema", "seq", "kind", "recorded_at", "previous_digest", "salt", "payload", "digest", "receipt"}


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


def verify_bundle(bundle, ca_file=None):
    if (not isinstance(bundle, dict) or bundle.get("format") != "paperroom-timestamps-v1"
            or not isinstance(bundle.get("events"), list)):
        raise ValueError("请选择 Paperroom 导出的 v1 时间戳 JSON 文件。")
    previous = None
    receipts = []
    for seq, event in enumerate(bundle["events"], 1):
        if (not isinstance(event, dict) or not FIELDS <= event.keys()
                or event.keys() - FIELDS - {"section", "paragraph", "revision"}
                or event["schema"] != "paperroom.event.v1" or type(event["seq"]) is not int
                or event["seq"] != seq or event["previous_digest"] != previous):
            raise ValueError(f"第 {seq} 条事件的格式、顺序或前序摘要无效。")
        if (not isinstance(event["kind"], str) or event["kind"] not in KINDS
                or not isinstance(event["payload"], dict) or not isinstance(event["salt"], str)
                or not DIGEST.fullmatch(event["salt"]) or not isinstance(event["digest"], str)
                or not DIGEST.fullmatch(event["digest"])):
            raise ValueError(f"第 {seq} 条事件的数据格式无效。")
        try:
            datetime.strptime(event["recorded_at"], "%Y-%m-%dT%H:%M:%S.%fZ")
        except (TypeError, ValueError) as exc:
            raise ValueError(f"第 {seq} 条事件的本机时间格式无效。") from exc
        record = {key: value for key, value in event.items() if key != "receipt"}
        if journal.event_digest(record) != event["digest"]:
            raise ValueError(f"第 {seq} 条事件的内容与摘要不符。")
        previous = event["digest"]
        receipt = event["receipt"]
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
    return len(bundle["events"]), receipts


def main():
    parser = argparse.ArgumentParser(description="离线核验 Paperroom 导出文件的摘要链、签名和时间。")
    parser.add_argument("export", type=Path, help="写作间导出的 JSON 文件")
    parser.add_argument("--ca-file", type=Path, help="核验者信任的 CA 证书文件（PEM）")
    args = parser.parse_args()
    try:
        with args.export.open(encoding="utf-8") as source:
            count, receipts = verify_bundle(json.load(source, object_pairs_hook=unique_keys), args.ca_file)
    except (OSError, ValueError, RecursionError) as exc:
        print(f"核验失败。{exc}", file=sys.stderr)
        return 1
    covered = receipts[-1][0] if receipts else 0
    print(f"事件 {count} 条，已核验的独立时间戳回执 {len(receipts)} 份。")
    print(f"回执覆盖 {covered} 条，仅有本机记录 {count - covered} 条。")
    for seq, signed_at in receipts:
        print(f"事件 #{seq} 及其前序记录最迟于 {signed_at} 已存在。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
