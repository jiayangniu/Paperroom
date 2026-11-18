"""Optional RFC 3161 witness for a Paperroom journal SHA-256 commitment."""
import http.client
import os
import re
import shutil
import ssl
import subprocess
import tempfile
from email.utils import parsedate_to_datetime
from pathlib import Path
from time import monotonic
from urllib.parse import urlsplit

MAX_REPLY = 1024 * 1024
TIMEOUT = 10


def _endpoint():
    value = os.environ.get("PAPERROOM_TSA_URL", "").strip()
    if not value:
        raise ValueError("尚未配置时间戳机构。")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("时间戳机构的 HTTPS 地址或端口格式错误。") from exc
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.fragment or port == 0
            or not value.isascii() or re.search(r"[\s\x00-\x1f\x7f]", value)):
        raise ValueError("时间戳机构须使用不含账号密码的 HTTPS 地址。")
    return parsed


def authority():
    try:
        return _endpoint().hostname
    except ValueError:
        return None


def configured():
    return bool(authority())


def _check_digest(digest):
    if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise ValueError("记录摘要必须为 SHA-256。")


def _openssl(*arguments):
    command = shutil.which("openssl")
    if not command:
        raise ValueError("时间戳核验需要 OpenSSL 的 ts 命令。")
    try:
        result = subprocess.run([command, "ts", *arguments], capture_output=True,
                                timeout=TIMEOUT, env={**os.environ, "LC_ALL": "C"}, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError("本机时间戳核验程序未能完成。") from exc
    if result.returncode:
        raise ValueError("时间戳处理失败，请检查回执、记录摘要、请求随机数与受信 CA 证书。")
    return result.stdout


def _trust_options(ca_file):
    custom = ca_file if ca_file is not None else os.environ.get("PAPERROOM_TSA_CA_FILE")
    if custom:
        path = Path(custom).expanduser().resolve()
        if not path.is_file():
            raise ValueError("找不到指定的时间戳 CA 证书文件。")
        return ["-CAfile", str(path)]
    paths = ssl.get_default_verify_paths()
    options = []
    if paths.cafile:
        options.extend(["-CAfile", paths.cafile])
    if paths.capath:
        options.extend(["-CApath", paths.capath])
    if not options:
        raise ValueError("未找到系统根证书，请配置 PAPERROOM_TSA_CA_FILE。")
    return options


def _signed_time(reply):
    line = re.search(rb"^Time stamp:\s*(.+?)\s*$", reply, re.MULTILINE)
    if line:
        match = re.fullmatch(r"([A-Za-z]{3}\s+\d+\s+\d\d:\d\d:\d\d)(\.\d+)?\s+(\d{4}) GMT",
                             line[1].decode("ascii", "replace"))
        if match:
            dt = parsedate_to_datetime(match[1] + " " + match[3] + " GMT")
            return dt.strftime("%Y-%m-%dT%H:%M:%S") + (match[2] or "") + "Z"
    raise ValueError("无法读取回执中签署的 UTC 时间。")


def verify_receipt(digest, query_der, reply_der, ca_file=None):
    """Offline verification against verifier-selected trust roots; return signed UTC."""
    _check_digest(digest)
    if not isinstance(query_der, bytes) or not 0 < len(query_der) <= 8192:
        raise ValueError("时间戳请求格式错误或过大。")
    if not isinstance(reply_der, bytes) or not 0 < len(reply_der) <= MAX_REPLY:
        raise ValueError("时间戳回执格式错误或过大。")
    trust = _trust_options(ca_file)
    with tempfile.TemporaryDirectory() as directory:
        query = Path(directory) / "request.tsq"
        reply = Path(directory) / "reply.tsr"
        query.write_bytes(query_der)
        reply.write_bytes(reply_der)
        desc = _openssl("-query", "-in", str(query), "-text")
        if (not re.search(rb"^Hash Algorithm: sha256\s*$", desc, re.MULTILINE)
                or not re.search(rb"^Nonce: 0x[0-9a-fA-F]+\s*$", desc, re.MULTILINE)):
            raise ValueError("时间戳请求缺少 SHA-256 或随机数。")
        # Check the original request (including nonce) and independently compare the
        # signed imprint to the caller's journal commitment; an exported TSQ is untrusted.
        common = ["-verify", "-in", str(reply), *trust]
        _openssl(*common, "-queryfile", str(query))
        _openssl(*common, "-digest", digest)
        return _signed_time(_openssl("-reply", "-in", str(reply), "-text"))


def _post(endpoint, query):
    # No cookies, authorization, client identifiers or redirects. The request body
    # contains the commitment, a nonce, the algorithm and the certificate request.
    conn = http.client.HTTPSConnection(endpoint.hostname, endpoint.port, timeout=TIMEOUT)
    target = endpoint.path or "/"
    if endpoint.query:
        target += "?" + endpoint.query
    try:
        conn.request("POST", target, body=query, headers={"Content-Type": "application/timestamp-query",
                                                         "Accept": "application/timestamp-reply"})
        response = conn.getresponse()
        if response.status != 200:
            raise ValueError(f"时间戳机构返回 HTTP {response.status}。")
        chunks = bytearray()
        deadline = monotonic() + TIMEOUT
        while len(chunks) <= MAX_REPLY:
            if monotonic() >= deadline:
                raise ValueError("时间戳机构响应超时。")
            part = response.read1(min(65536, MAX_REPLY + 1 - len(chunks)))
            if not part:
                return bytes(chunks)
            chunks.extend(part)
        raise ValueError("时间戳回执超过 1 MiB。")
    except (OSError, http.client.HTTPException) as exc:
        raise ValueError("无法连接时间戳机构，本机写作记录可稍后再验证。") from exc
    finally:
        conn.close()


def stamp(digest):
    """Explicitly send one digest to the configured HTTPS TSA and verify its reply."""
    _check_digest(digest)
    endpoint = _endpoint()
    query = _openssl("-query", "-sha256", "-digest", digest, "-cert")
    reply = _post(endpoint, query)
    signed_at = verify_receipt(digest, query, reply)
    return dict(verified_at=signed_at, authority=endpoint.hostname, query_der=query, reply_der=reply)
