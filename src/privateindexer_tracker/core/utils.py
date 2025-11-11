from decimal import Decimal
from urllib.parse import unquote_to_bytes

from fastapi import Request

from privateindexer_tracker.core import mysql


class User:

    def __init__(self, user_id: int, user_label: str, apikey: str, downloaded: int, uploaded: int):
        self.user_id: int = user_id
        self.user_label: str = user_label
        self.apikey: str = apikey
        self.downloaded: int = downloaded
        self.uploaded: int = uploaded


async def get_user_by_key(apikey: str) -> User | None:
    if not apikey:
        return None

    row = await mysql.fetch_one("SELECT id, label, downloaded, uploaded FROM users WHERE api_key = %s", (apikey,))
    if not row:
        return None

    return User(row["id"], row["label"], apikey, row["downloaded"], row["uploaded"])


def extract_bt_param(raw_qs: bytes, key: str) -> bytes:
    prefix = key.encode("ascii") + b"="
    start = raw_qs.find(prefix)
    if start == -1:
        return None
    start += len(prefix)
    end = raw_qs.find(b"&", start)
    if end == -1:
        end = len(raw_qs)
    raw_value = raw_qs[start:end]
    return unquote_to_bytes(raw_value.decode("ascii"))


def sanitize_bencode(obj):
    if isinstance(obj, Decimal):
        return int(obj)
    elif isinstance(obj, dict):
        return {k: sanitize_bencode(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_bencode(v) for v in obj]
    elif isinstance(obj, tuple):
        return tuple(sanitize_bencode(v) for v in obj)
    return obj


def get_client_ip(request: Request) -> str:
    x_forwarded_for = request.headers.get("x-forwarded-for")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()

    x_real_ip = request.headers.get("x-real-ip")
    if x_real_ip:
        return x_real_ip

    return request.client.host
