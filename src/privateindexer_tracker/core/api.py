import random
import socket
from urllib.parse import parse_qs

import bencode2
from fastapi import HTTPException, Query, Request, Form, APIRouter, Depends, Header
from fastapi.responses import Response, PlainTextResponse

from privateindexer_tracker.core import mysql, utils
from privateindexer_tracker.core.config import PEER_TIMEOUT, ANNOUNCE_INTERVAL, ANNOUNCE_JITTER_PERCENT
from privateindexer_tracker.core.logger import log
from privateindexer_tracker.core.utils import User

router = APIRouter()


async def api_key_required(apikey_query: str | None = Query(None, alias="apikey"), apikey_form: str | None = Form(None, alias="apikey"),
                           apikey_header: str | None = Header(None, alias="X-API-Key"), ) -> User:
    apikey = apikey_query or apikey_form or apikey_header

    if not apikey:
        raise HTTPException(status_code=401, detail="API key missing")

    user = await utils.get_user_by_key(apikey)
    if not user:
        log.warning(f"[USER] Invalid API key sent: {apikey}")
        raise HTTPException(status_code=401, detail="Invalid API key")
    return user


@router.get("/health")
def get_health():
    """
    Endpoint to be used by Docker for checking the readiness of the API
    """
    return PlainTextResponse("OK")


@router.get("/announce")
async def announce(user: User = Depends(api_key_required), request: Request = None):
    user_label = user.user_label

    user_agent = request.headers.get("User-Agent")
    if not user_agent or not user_agent.startswith("privateindexer-client"):
        log.warning(f"[ANNOUNCE] User '{user_label}' announce request comes from non-PrivateIndexer client: {user_agent}")
        raise HTTPException(status_code=403, detail="Invalid PrivateIndexer client version")

    raw_qs = request.scope["query_string"]

    raw_info_hash_bytes = utils.extract_bt_param(raw_qs, "info_hash")
    raw_peer_id_bytes = utils.extract_bt_param(raw_qs, "peer_id")
    if not raw_info_hash_bytes or not raw_peer_id_bytes:
        log.warning(f"[ANNOUNCE] User '{user_label}' announce request is missing info_hash or peer_id")
        raise HTTPException(status_code=400, detail="Missing info_hash or peer_id")

    if len(raw_info_hash_bytes) != 20:
        log.warning(f"[ANNOUNCE] User '{user_label}' announce request has malformed info_hash ({len(raw_info_hash_bytes)})")
        raise HTTPException(status_code=400, detail="Malformed info_hash")
    if len(raw_peer_id_bytes) != 20:
        log.warning(f"[ANNOUNCE] User '{user_label}' announce request has malformed peer_id ({len(raw_peer_id_bytes)})")
        raise HTTPException(status_code=400, detail="Malformed peer_id")

    info_hash_hex = raw_info_hash_bytes.hex().lower()
    peer_id_hex = raw_peer_id_bytes.hex()
    qs = parse_qs(raw_qs.decode("latin-1"), keep_blank_values=True)

    left = int(qs.get("left", ["0"])[0])
    uploaded = int(qs.get("uploaded", ["0"])[0])
    downloaded = int(qs.get("downloaded", ["0"])[0])
    event = qs.get("event", [""])[0].lower()
    port = int(qs.get("port", ["6881"])[0])
    announce_ip = qs.get("ip", [utils.get_client_ip(request)])[0]

    torrent = await mysql.fetch_one("SELECT id, name FROM torrents WHERE hash_v1 = %s OR hash_v2_trunc = %s LIMIT 1", (info_hash_hex, info_hash_hex,))
    if not torrent:
        log.warning(f"[ANNOUNCE] User '{user_label}' announced an unknown torrent with hash: {info_hash_hex}")
        raise HTTPException(status_code=404, detail="Torrent not found")

    torrent_id = torrent["id"]

    prev_peer = await mysql.fetch_one("SELECT last_uploaded, last_downloaded FROM peers WHERE torrent_id=%s AND peer_id=%s", (torrent_id, peer_id_hex))

    delta_up = max(0, uploaded - (prev_peer["last_uploaded"] if prev_peer else 0))
    delta_down = max(0, downloaded - (prev_peer["last_downloaded"] if prev_peer else 0))

    await mysql.background_updates.put(("UPDATE users SET uploaded = uploaded + %s, downloaded = downloaded + %s, last_ip = %s, last_seen=NOW() WHERE id = %s",
                                        (delta_up, delta_down, f"{announce_ip}:{port}", user.user_id)))

    await mysql.background_updates.put(("UPDATE torrents SET last_seen=NOW() WHERE id=%s", (torrent_id,)))

    peers_bin = bytearray()

    if event == "stopped":
        await mysql.background_updates.put(("DELETE FROM peers WHERE torrent_id=%s AND peer_id=%s", (torrent_id, peer_id_hex)))

        seeders = leechers = 0

        log.debug(f"[ANNOUNCE] User '{user_label}' stopped announcing '{torrent['name']}' from IP '{announce_ip}'")

    else:
        await mysql.background_updates.put(("""
                                            INSERT INTO peers (torrent_id, peer_id, ip, port, left_bytes, last_uploaded, last_downloaded, last_seen, user_id)
                                            VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), %s)
                                            ON DUPLICATE KEY UPDATE ip=%s,
                                                                    port=%s,
                                                                    left_bytes=%s,
                                                                    last_uploaded=%s,
                                                                    last_downloaded=%s,
                                                                    last_seen=NOW()
                                            """, (torrent_id, peer_id_hex, announce_ip, port, left, uploaded, downloaded, user.user_id, announce_ip, port, left, uploaded,
                                                  downloaded)))

        db_peers = await mysql.fetch_all("""
                                         SELECT peer_id, ip, port, left_bytes
                                         FROM peers
                                         WHERE torrent_id = %s
                                           AND last_seen > NOW() - INTERVAL %s SECOND
                                         """, (torrent_id, PEER_TIMEOUT))

        peers = list(db_peers)

        seeders = sum(peer["left_bytes"] == 0 for peer in peers)
        leechers = len(peers) - seeders

        # check if current peer not in peers list
        if not any(p["peer_id"] == peer_id_hex for p in peers):
            # increment seeders/leechers if peer not in peers pulled from database
            if left == 0:
                seeders += 1
            else:
                leechers += 1

        for peer in peers:
            # do not add the announcer to the peer list in the response
            if peer["peer_id"] == peer_id_hex:
                continue
            try:
                peers_bin.extend(socket.inet_aton(peer["ip"]))
                peers_bin.extend(peer["port"].to_bytes(2, "big"))
            except OSError:
                continue

        log.debug(f"[ANNOUNCE] User '{user_label}' announced '{torrent['name']}' (S: {seeders} L: {leechers}) from IP '{announce_ip}'")

    jitter = random.randint(-ANNOUNCE_INTERVAL // ANNOUNCE_JITTER_PERCENT, ANNOUNCE_INTERVAL // ANNOUNCE_JITTER_PERCENT)
    announce_interval = ANNOUNCE_INTERVAL + jitter

    response_dict = {b"complete": seeders, b"incomplete": leechers, b"interval": announce_interval, b"peers": bytes(peers_bin), }

    sanitized = utils.sanitize_bencode(response_dict)
    return Response(content=bencode2.bencode(sanitized), media_type="application/x-bittorrent")
